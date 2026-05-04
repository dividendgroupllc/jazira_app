# Copyright (c) 2026, Jazira App and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import cint, flt, get_first_day, get_last_day, getdate


ALLOCATION_REMARK_PREFIX = "Jazira Expense Allocation:"

DEFAULT_COMPANIES = (
    "Jazira sklad",
    "Jazira Smart",
    "Jazira Saripul",
    "Jazira Xalq Banki",
)


class JaziraExpenseAllocation(Document):
    def validate(self):
        self.validate_period()

        if not self.companies:
            self.set_default_companies()

        self.validate_expense_scope()
        self.set_currency()
        self.set_source_offset_account()
        self.validate_company_rows()
        self.validate_company_currencies()
        self.set_totals()
        self.set_status()

    def before_submit(self):
        self.calculate(save=False)
        self.validate_unique_submitted_period()
        self.validate_submit_ready()

    def on_submit(self):
        created = []
        created.extend(self.create_expense_reversal_journal_entries())
        created.extend(self.create_allocation_journal_entries())
        self.db_set("status", "Submitted")

        if created:
            frappe.msgprint(
                _("Xarajat taqsimoti uchun {0} ta Journal Entry yaratildi").format(len(created)),
                indicator="green",
            )

    def on_cancel(self):
        self.cancel_allocation_journal_entries()
        self.cancel_expense_reversal_journal_entries()
        self.db_set("status", "Cancelled")

    def validate_period(self):
        if not self.from_date or not self.to_date:
            return

        from_date = getdate(self.from_date)
        to_date = getdate(self.to_date)

        if from_date > to_date:
            frappe.throw(_("Period boshi period oxiridan katta bo'lishi mumkin emas"))

        first_day = get_first_day(from_date)
        last_day = get_last_day(from_date)
        if from_date != first_day or to_date != last_day:
            frappe.throw(
                _("Oylik yopish faqat to'liq oy uchun bo'ladi: {0} - {1}").format(
                    first_day, last_day
                )
            )

        self.posting_date = self.to_date

    def set_currency(self):
        company = None
        if self.expense_company_scope == "Source Company":
            company = self.expense_source_company

        if not company:
            companies = self.get_allocation_companies()
            company = companies[0] if companies else DEFAULT_COMPANIES[0]

        if company:
            self.currency = frappe.db.get_value("Company", company, "default_currency")

    def validate_expense_scope(self):
        if self.expense_company_scope != "Source Company":
            self.expense_source_company = None
            return

        if not self.expense_source_company:
            frappe.throw(_("Source Company rejimida xarajat manba kompaniyasi majburiy"))

    def set_source_offset_account(self):
        if self.expense_company_scope != "Source Company":
            self.source_offset_account = None
            return

        if cint(self.create_source_reversal) and not self.source_offset_account:
            self.source_offset_account = self.get_default_source_offset_account(
                self.expense_source_company
            )

    def set_status(self, status=None):
        if status:
            self.status = status
        elif self.docstatus == 0:
            self.status = "Calculated" if flt(self.total_expense_amount) and self.companies else "Draft"
        elif self.docstatus == 1:
            self.status = "Submitted"
        elif self.docstatus == 2:
            self.status = "Cancelled"

    def set_default_companies(self):
        self.set("companies", [])
        for company in DEFAULT_COMPANIES:
            self.append("companies", self.get_company_row_defaults(company))

    def get_company_row_defaults(self, company):
        return {
            "company": company,
            "expense_account": self.get_default_expense_account(company),
            "offset_account": self.get_default_offset_account(company),
            "cost_center": self.get_default_cost_center(company),
        }

    @frappe.whitelist()
    def calculate(self, save=True):
        if self.docstatus != 0:
            frappe.throw(_("Faqat Draft holatdagi hujjatni qayta hisoblash mumkin"))

        self.validate_period()
        self.validate_expense_scope()
        self.set_currency()
        self.set_source_offset_account()

        company_configs = self.get_company_configs()
        expenses = self.get_period_journal_expenses()
        total_expense = flt(sum(row.net_amount for row in expenses), 2)

        profit_by_company = {
            company_config["company"]: self.get_profit_amount(company_config["company"])
            for company_config in company_configs
            if company_config.get("company")
        }

        basis_by_company = {}
        for company_config in company_configs:
            company = company_config.get("company")
            profit = flt(profit_by_company.get(company))
            basis_by_company[company] = max(profit, 0)

        total_basis = flt(sum(basis_by_company.values()), 2)

        self.set("companies", [])
        running_allocated = 0
        allocatable_rows = [
            row for row in company_configs if flt(basis_by_company.get(row.get("company"))) > 0
        ]
        last_allocatable_company = allocatable_rows[-1]["company"] if allocatable_rows else None

        for company_config in company_configs:
            company = company_config.get("company")
            profit = flt(profit_by_company.get(company), 2)
            basis = flt(basis_by_company.get(company), 2)
            percent = flt((basis / total_basis) * 100, 6) if total_basis else 0
            offset_account = company_config.get("offset_account") or self.get_default_offset_account(company)

            if (
                cint(self.create_source_reversal)
                and company == self.expense_source_company
                and self.source_offset_account
            ):
                offset_account = self.source_offset_account

            if total_basis and basis:
                if company == last_allocatable_company:
                    allocated = flt(total_expense - running_allocated, 2)
                else:
                    allocated = flt(total_expense * basis / total_basis, 2)
                    running_allocated = flt(running_allocated + allocated, 2)
            else:
                allocated = 0

            self.append(
                "companies",
                {
                    "company": company,
                    "profit_amount": profit,
                    "allocation_basis_amount": basis,
                    "profit_percent": percent,
                    "allocated_expense_amount": allocated,
                    "expense_account": company_config.get("expense_account")
                    or self.get_default_expense_account(company),
                    "offset_account": offset_account,
                    "cost_center": company_config.get("cost_center") or self.get_default_cost_center(company),
                },
            )

        self.set("expenses", [])
        for expense in expenses:
            self.append(
                "expenses",
                {
                    "journal_entry": expense.journal_entry,
                    "posting_date": expense.posting_date,
                    "company": expense.company,
                    "account": expense.account,
                    "account_name": expense.account_name,
                    "cost_center": expense.cost_center,
                    "debit": expense.debit,
                    "credit": expense.credit,
                    "net_amount": expense.net_amount,
                    "user_remark": expense.user_remark,
                    "journal_entry_detail": expense.journal_entry_detail,
                },
            )

        self.set_totals()
        self.set_status("Calculated")

        if cint(save):
            self.save()

        return {
            "total_profit": self.total_profit,
            "total_expense_amount": self.total_expense_amount,
            "allocated_total": self.allocated_total,
        }

    def get_company_configs(self):
        rows = self.companies or []
        if not rows:
            return [{"company": company} for company in DEFAULT_COMPANIES]

        configs = []
        for row in rows:
            if not row.company:
                continue
            configs.append(
                {
                    "company": row.company,
                    "expense_account": row.expense_account,
                    "offset_account": row.offset_account,
                    "cost_center": row.cost_center,
                }
            )

        return configs or [{"company": company} for company in DEFAULT_COMPANIES]

    def validate_company_rows(self):
        expected_companies = list(DEFAULT_COMPANIES)
        seen = set()

        for row in self.companies:
            if not row.company:
                frappe.throw(_("Kompaniya to'ldirilmagan"))

            if row.company in seen:
                frappe.throw(_("Kompaniya takrorlangan: {0}").format(row.company))
            seen.add(row.company)

            if not frappe.db.exists("Company", row.company):
                frappe.throw(_("Kompaniya topilmadi: {0}").format(row.company))

            if not row.expense_account:
                row.expense_account = self.get_default_expense_account(row.company)
            if not row.offset_account:
                row.offset_account = self.get_default_offset_account(row.company)
            if not row.cost_center:
                row.cost_center = self.get_default_cost_center(row.company)

            if row.cost_center:
                self.validate_cost_center_company(
                    row.cost_center,
                    row.company,
                    _("Cost Center ({0})").format(row.company),
                )

        missing = [company for company in expected_companies if company not in seen]
        if missing:
            frappe.throw(
                _("Oylik yopish uchun quyidagi kompaniyalar ham bo'lishi kerak: {0}").format(
                    ", ".join(missing)
                )
            )

    def validate_company_currencies(self):
        if not self.currency:
            return

        companies = self.get_allocation_companies()
        companies.extend(company for company in self.get_expense_companies() if company not in companies)

        mismatched = []
        for company in companies:
            currency = frappe.db.get_value("Company", company, "default_currency")
            if currency and currency != self.currency:
                mismatched.append(f"{company}: {currency}")

        if mismatched:
            frappe.throw(
                _("Barcha kompaniyalar bir xil valyutada bo'lishi kerak ({0}). Farq: {1}").format(
                    self.currency, ", ".join(mismatched)
                )
            )

    def get_allocation_companies(self):
        companies = []
        for row in self.companies:
            if row.company and row.company not in companies:
                companies.append(row.company)
        return companies

    def get_profit_amount(self, company):
        if not company:
            return 0

        if self.profit_source == "Sales Invoice Gross Profit":
            return self.get_sales_invoice_gross_profit(company)

        include_journal_entries = self.profit_source == "GL Net Profit"
        return self.get_gl_profit(company, include_journal_entries=include_journal_entries)

    def get_gl_profit(self, company, include_journal_entries=False):
        allocation_filter = self.get_journal_entry_exclusion_sql("je")
        voucher_filter = (
            ""
            if include_journal_entries
            else "AND gle.voucher_type IN ('Sales Invoice', 'POS Invoice')"
        )

        result = frappe.db.sql(
            f"""
            SELECT COALESCE(SUM(gle.credit - gle.debit), 0) AS profit
            FROM `tabGL Entry` gle
            INNER JOIN `tabAccount` acc ON acc.name = gle.account
            LEFT JOIN `tabJournal Entry` je
                ON je.name = gle.voucher_no AND gle.voucher_type = 'Journal Entry'
            WHERE gle.company = %(company)s
                AND gle.posting_date BETWEEN %(from_date)s AND %(to_date)s
                AND gle.is_cancelled = 0
                AND gle.voucher_type != 'Period Closing Voucher'
                AND acc.root_type IN ('Income', 'Expense')
                {voucher_filter}
                AND {allocation_filter}
            """,
            self.get_query_params(company),
            as_dict=True,
        )

        return flt(result[0].profit if result else 0, 2)

    def get_sales_invoice_gross_profit(self, company):
        result = frappe.db.sql(
            """
            SELECT COALESCE(
                SUM(sii.base_net_amount - (COALESCE(sii.incoming_rate, 0) * COALESCE(sii.stock_qty, 0))),
                0
            ) AS profit
            FROM `tabSales Invoice` si
            INNER JOIN `tabSales Invoice Item` sii ON sii.parent = si.name
            WHERE si.company = %(company)s
                AND si.docstatus = 1
                AND si.posting_date BETWEEN %(from_date)s AND %(to_date)s
            """,
            self.get_query_params(company),
            as_dict=True,
        )

        return flt(result[0].profit if result else 0, 2)

    def get_period_journal_expenses(self):
        companies = self.get_expense_companies()
        if not companies:
            return []

        allocation_filter = self.get_journal_entry_exclusion_sql("je")
        params = self.get_query_params(self.expense_source_company)
        params["expense_companies"] = tuple(companies)

        return frappe.db.sql(
            f"""
            SELECT
                je.name AS journal_entry,
                je.posting_date,
                je.company,
                jea.name AS journal_entry_detail,
                jea.account,
                acc.account_name,
                jea.cost_center,
                COALESCE(jea.debit, 0) AS debit,
                COALESCE(jea.credit, 0) AS credit,
                COALESCE(jea.debit, 0) - COALESCE(jea.credit, 0) AS net_amount,
                je.user_remark
            FROM `tabJournal Entry` je
            INNER JOIN `tabJournal Entry Account` jea ON jea.parent = je.name
            INNER JOIN `tabAccount` acc ON acc.name = jea.account
            WHERE je.company IN %(expense_companies)s
                AND je.docstatus = 1
                AND je.posting_date BETWEEN %(from_date)s AND %(to_date)s
                AND acc.root_type = 'Expense'
                AND ABS(COALESCE(jea.debit, 0) - COALESCE(jea.credit, 0)) > 0.005
                AND {allocation_filter}
            ORDER BY je.posting_date, je.name, jea.idx
            """,
            params,
            as_dict=True,
        )

    def get_expense_companies(self):
        if self.expense_company_scope == "Allocation Companies":
            companies = []
            for company_config in self.get_company_configs():
                company = company_config.get("company")
                if company and company not in companies:
                    companies.append(company)
            return companies

        return [self.expense_source_company] if self.expense_source_company else []

    def get_query_params(self, company):
        return {
            "company": company,
            "from_date": self.from_date,
            "to_date": self.to_date,
            "allocation_remark_like": f"{ALLOCATION_REMARK_PREFIX}%",
        }

    def get_journal_entry_exclusion_sql(self, alias):
        clauses = [f"IFNULL({alias}.user_remark, '') NOT LIKE %(allocation_remark_like)s"]

        if journal_entry_has_allocation_field():
            clauses.append(f"IFNULL({alias}.custom_jazira_expense_allocation, '') = ''")

        return " AND ".join(clauses)

    def set_totals(self):
        self.total_profit = flt(sum(flt(row.profit_amount) for row in self.companies), 2)
        self.total_basis_amount = flt(
            sum(flt(row.allocation_basis_amount) for row in self.companies), 2
        )
        self.total_expense_amount = flt(sum(flt(row.net_amount) for row in self.expenses), 2)
        self.allocated_total = flt(
            sum(flt(row.allocated_expense_amount) for row in self.companies), 2
        )
        self.allocation_difference = flt(self.total_expense_amount - self.allocated_total, 2)

    def validate_unique_submitted_period(self):
        existing = frappe.db.sql(
            """
            SELECT name, from_date, to_date
            FROM `tabJazira Expense Allocation`
            WHERE name != %(name)s
                AND docstatus = 1
                AND (
                    %(from_date)s BETWEEN from_date AND to_date
                    OR %(to_date)s BETWEEN from_date AND to_date
                    OR from_date BETWEEN %(from_date)s AND %(to_date)s
                    OR to_date BETWEEN %(from_date)s AND %(to_date)s
                )
            LIMIT 1
            """,
            {
                "name": self.name,
                "from_date": self.from_date,
                "to_date": self.to_date,
            },
            as_dict=True,
        )

        if existing:
            frappe.throw(
                _("Bu period bilan kesishadigan tasdiqlangan oylik yopish mavjud: {0} ({1} - {2})").format(
                    frappe.utils.get_link_to_form("Jazira Expense Allocation", existing[0].name),
                    existing[0].from_date,
                    existing[0].to_date,
                )
            )

    def validate_submit_ready(self):
        self.validate_company_currencies()
        self.validate_no_unsubmitted_documents()
        self.validate_accounting_periods_open()

        if flt(self.total_expense_amount) <= 0:
            frappe.throw(_("Period bo'yicha Journal Entry xarajatlari topilmadi"))

        if flt(self.total_basis_amount) <= 0:
            frappe.throw(_("Kompaniyalar bo'yicha musbat foyda topilmadi"))

        if abs(flt(self.allocation_difference)) > 0.01:
            frappe.throw(_("Ajratilgan summa jami xarajatga teng emas"))

        if cint(self.create_source_reversal):
            if self.expense_company_scope == "Source Company" and not self.source_offset_account:
                frappe.throw(_("Manba clearing account to'ldirilmagan"))

            if self.expense_company_scope == "Source Company":
                self.validate_account(
                    self.source_offset_account,
                    self.expense_source_company,
                    _("Manba clearing account"),
                )
            else:
                company_row_by_company = self.get_company_row_by_company()
                for company, amount in self.get_expense_company_totals().items():
                    if abs(flt(amount)) <= 0.005:
                        continue
                    company_row = company_row_by_company.get(company)
                    if not company_row or not company_row.offset_account:
                        frappe.throw(
                            _("{0} kompaniyasi uchun clearing/qarshi account to'ldirilmagan").format(
                                company
                            )
                        )
                    self.validate_account(
                        company_row.offset_account,
                        company,
                        _("Clearing account ({0})").format(company),
                    )

        missing = []
        for row in self.companies:
            if flt(row.allocated_expense_amount) <= 0:
                continue
            if not row.expense_account or not row.offset_account:
                missing.append(row.company)
                continue

            self.validate_account(
                row.expense_account,
                row.company,
                _("Xarajat account ({0})").format(row.company),
                root_type="Expense",
            )
            self.validate_account(
                row.offset_account,
                row.company,
                _("Qarshi account ({0})").format(row.company),
            )
            if row.cost_center:
                self.validate_cost_center_company(
                    row.cost_center,
                    row.company,
                    _("Cost Center ({0})").format(row.company),
                )

        if missing:
            frappe.throw(
                _("Quyidagi kompaniyalarda xarajat account yoki qarshi account to'ldirilmagan: {0}").format(
                    ", ".join(missing)
                )
            )

    def get_company_row_by_company(self):
        return {row.company: row for row in self.companies if row.company}

    def get_expense_company_totals(self):
        totals = {}
        for expense in self.expenses:
            if not expense.company:
                continue
            totals[expense.company] = flt(
                totals.get(expense.company, 0) + flt(expense.net_amount), 2
            )
        return totals

    def validate_no_unsubmitted_documents(self):
        profit_companies = self.get_allocation_companies()
        expense_companies = self.get_expense_companies()

        draft_invoices = []
        for doctype in ("Sales Invoice", "POS Invoice"):
            if not frappe.db.exists("DocType", doctype):
                continue
            names = frappe.get_all(
                doctype,
                filters={
                    "company": ["in", profit_companies],
                    "posting_date": ["between", [self.from_date, self.to_date]],
                    "docstatus": 0,
                },
                pluck="name",
                limit=5,
            )
            draft_invoices.extend(f"{doctype}: {name}" for name in names)

        if draft_invoices:
            frappe.throw(
                _("Oylik yopishdan oldin draft savdo hujjatlarini submit yoki cancel qiling: {0}").format(
                    ", ".join(draft_invoices)
                )
            )

        if not expense_companies:
            return

        allocation_filter = self.get_journal_entry_exclusion_sql("je")
        draft_expenses = frappe.db.sql(
            f"""
            SELECT DISTINCT je.name
            FROM `tabJournal Entry` je
            INNER JOIN `tabJournal Entry Account` jea ON jea.parent = je.name
            INNER JOIN `tabAccount` acc ON acc.name = jea.account
            WHERE je.company IN %(companies)s
                AND je.docstatus = 0
                AND je.posting_date BETWEEN %(from_date)s AND %(to_date)s
                AND acc.root_type = 'Expense'
                AND ABS(COALESCE(jea.debit, 0) - COALESCE(jea.credit, 0)) > 0.005
                AND {allocation_filter}
            ORDER BY je.posting_date, je.name
            LIMIT 5
            """,
            {
                "companies": tuple(expense_companies),
                "from_date": self.from_date,
                "to_date": self.to_date,
                "allocation_remark_like": f"{ALLOCATION_REMARK_PREFIX}%",
            },
            as_dict=True,
        )
        if draft_expenses:
            frappe.throw(
                _("Oylik yopishdan oldin draft Journal Entry xarajatlarini submit yoki cancel qiling: {0}").format(
                    ", ".join(row.name for row in draft_expenses)
                )
            )

    def validate_accounting_periods_open(self):
        companies = []
        if cint(self.create_source_reversal):
            companies.extend(company for company in self.get_expense_company_totals() if company not in companies)
        companies.extend(
            row.company
            for row in self.companies
            if row.company and flt(row.allocated_expense_amount) > 0 and row.company not in companies
        )

        for company in companies:
            closed_period = frappe.db.sql(
                """
                SELECT ap.name
                FROM `tabAccounting Period` ap
                INNER JOIN `tabClosed Document` cd ON cd.parent = ap.name
                WHERE ap.company = %(company)s
                    AND cd.document_type = 'Journal Entry'
                    AND cd.closed = 1
                    AND %(posting_date)s BETWEEN ap.start_date AND ap.end_date
                LIMIT 1
                """,
                {"company": company, "posting_date": self.posting_date},
                as_dict=True,
            )
            if closed_period:
                frappe.throw(
                    _("Journal Entry yaratib bo'lmaydi: {0} kompaniyasida {1} accounting period yopilgan").format(
                        company, closed_period[0].name
                    )
                )

    def validate_account(self, account, company, label, root_type=None):
        if not account or not company:
            return

        account_data = frappe.db.get_value(
            "Account",
            account,
            ["company", "is_group", "root_type"],
            as_dict=True,
        )
        if not account_data:
            frappe.throw(_("{0} topilmadi: {1}").format(label, account))

        if account_data.is_group:
            frappe.throw(_("{0} group account bo'lishi mumkin emas: {1}").format(label, account))

        if account_data.company != company:
            frappe.throw(
                _("{0} '{1}' {2} kompaniyasiga tegishli emas").format(
                    label, account, company
                )
            )

        if root_type and account_data.root_type != root_type:
            frappe.throw(
                _("{0} '{1}' {2} root_type bo'lishi kerak").format(label, account, root_type)
            )

    def validate_cost_center_company(self, cost_center, company, label):
        data = frappe.db.get_value(
            "Cost Center",
            cost_center,
            ["company", "is_group"],
            as_dict=True,
        )
        if not data:
            frappe.throw(_("{0} topilmadi: {1}").format(label, cost_center))
        if data.is_group:
            frappe.throw(_("{0} group cost center bo'lishi mumkin emas: {1}").format(label, cost_center))
        if data.company != company:
            frappe.throw(
                _("{0} '{1}' {2} kompaniyasiga tegishli emas").format(
                    label, cost_center, company
                )
            )

    def create_expense_reversal_journal_entries(self):
        if not cint(self.create_source_reversal):
            return []

        grouped_by_company = self.get_grouped_expenses_by_company()
        if not grouped_by_company:
            return []

        created = []
        if self.expense_company_scope == "Source Company":
            if self.source_reversal_journal_entry and frappe.db.exists(
                "Journal Entry", self.source_reversal_journal_entry
            ):
                return [self.source_reversal_journal_entry]

            journal_entry = self.create_company_reversal_journal_entry(
                self.expense_source_company,
                self.source_offset_account,
                grouped_by_company.get(self.expense_source_company, {}),
                "source reversal",
            )
            if journal_entry:
                self.db_set("source_reversal_journal_entry", journal_entry)
                self.source_reversal_journal_entry = journal_entry
                created.append(journal_entry)

            return created

        company_row_by_company = self.get_company_row_by_company()
        for company, grouped_expenses in grouped_by_company.items():
            company_row = company_row_by_company.get(company)
            if not company_row:
                continue

            if company_row.reversal_journal_entry and frappe.db.exists(
                "Journal Entry", company_row.reversal_journal_entry
            ):
                created.append(company_row.reversal_journal_entry)
                continue

            journal_entry = self.create_company_reversal_journal_entry(
                company,
                company_row.offset_account,
                grouped_expenses,
                f"{company} reversal",
            )
            if not journal_entry:
                continue

            frappe.db.set_value(
                company_row.doctype,
                company_row.name,
                "reversal_journal_entry",
                journal_entry,
                update_modified=False,
            )
            company_row.reversal_journal_entry = journal_entry
            created.append(journal_entry)

        return created

    def get_grouped_expenses_by_company(self):
        grouped_by_company = {}
        default_cost_centers = {}
        for expense in self.expenses:
            net_amount = flt(expense.net_amount, 2)
            if abs(net_amount) <= 0.005 or not expense.company:
                continue

            if expense.company not in default_cost_centers:
                default_cost_centers[expense.company] = self.get_default_cost_center(expense.company)

            grouped_expenses = grouped_by_company.setdefault(expense.company, {})
            default_cost_center = default_cost_centers.get(expense.company)
            key = (expense.account, expense.cost_center or default_cost_center)
            grouped_expenses[key] = flt(grouped_expenses.get(key, 0) + net_amount, 2)

        return grouped_by_company

    def create_company_reversal_journal_entry(self, company, offset_account, grouped_expenses, label):
        total_amount = flt(sum(grouped_expenses.values()), 2)
        if abs(total_amount) <= 0.005:
            return None

        je = frappe.new_doc("Journal Entry")
        je.voucher_type = "Journal Entry"
        je.company = company
        je.posting_date = self.posting_date or self.to_date
        je.user_remark = (
            f"{ALLOCATION_REMARK_PREFIX} {self.name} | "
            f"{self.from_date} - {self.to_date} | {label}"
        )

        if journal_entry_has_allocation_field():
            je.custom_jazira_expense_allocation = self.name

        je.append(
            "accounts",
            {
                "account": offset_account,
                "debit_in_account_currency": total_amount if total_amount > 0 else 0,
                "credit_in_account_currency": abs(total_amount) if total_amount < 0 else 0,
                "user_remark": je.user_remark,
            },
        )

        for (account, cost_center), net_amount in grouped_expenses.items():
            row = {
                "account": account,
                "user_remark": je.user_remark,
            }
            if cost_center:
                row["cost_center"] = cost_center

            if net_amount > 0:
                row.update(
                    {
                        "debit_in_account_currency": 0,
                        "credit_in_account_currency": net_amount,
                    }
                )
            else:
                row.update(
                    {
                        "debit_in_account_currency": abs(net_amount),
                        "credit_in_account_currency": 0,
                    }
                )

            je.append("accounts", row)

        je.insert(ignore_permissions=True)
        je.submit()
        return je.name

    def create_allocation_journal_entries(self):
        created = []
        for row in self.companies:
            amount = flt(row.allocated_expense_amount, 2)
            if amount <= 0:
                continue

            if row.allocation_journal_entry and frappe.db.exists(
                "Journal Entry", row.allocation_journal_entry
            ):
                continue

            je = frappe.new_doc("Journal Entry")
            je.voucher_type = "Journal Entry"
            je.company = row.company
            je.posting_date = self.posting_date or self.to_date
            je.user_remark = (
                f"{ALLOCATION_REMARK_PREFIX} {self.name} | "
                f"{self.from_date} - {self.to_date} | {row.company}"
            )

            if journal_entry_has_allocation_field():
                je.custom_jazira_expense_allocation = self.name

            debit_row = {
                "account": row.expense_account,
                "debit_in_account_currency": amount,
                "credit_in_account_currency": 0,
                "user_remark": je.user_remark,
            }
            credit_row = {
                "account": row.offset_account,
                "debit_in_account_currency": 0,
                "credit_in_account_currency": amount,
                "user_remark": je.user_remark,
            }

            if row.cost_center:
                debit_row["cost_center"] = row.cost_center

            je.append("accounts", debit_row)
            je.append("accounts", credit_row)

            je.insert(ignore_permissions=True)
            je.submit()

            frappe.db.set_value(
                row.doctype,
                row.name,
                "allocation_journal_entry",
                je.name,
                update_modified=False,
            )
            row.allocation_journal_entry = je.name
            created.append(je.name)

        return created

    def cancel_allocation_journal_entries(self):
        for row in self.companies:
            if not row.allocation_journal_entry:
                continue
            if not frappe.db.exists("Journal Entry", row.allocation_journal_entry):
                continue

            je = frappe.get_doc("Journal Entry", row.allocation_journal_entry)
            if je.docstatus == 1:
                je.flags.ignore_permissions = True
                je.cancel()

    def cancel_expense_reversal_journal_entries(self):
        journal_entries = []
        if self.source_reversal_journal_entry:
            journal_entries.append(self.source_reversal_journal_entry)
        journal_entries.extend(
            row.reversal_journal_entry for row in self.companies if row.reversal_journal_entry
        )

        for journal_entry in journal_entries:
            if not frappe.db.exists("Journal Entry", journal_entry):
                continue

            je = frappe.get_doc("Journal Entry", journal_entry)
            if je.docstatus == 1:
                je.flags.ignore_permissions = True
                je.cancel()

    def get_default_expense_account(self, company):
        if not company:
            return None

        account = get_company_default(company, "default_expense_account")
        if account:
            return account

        return frappe.db.get_value(
            "Account",
            {"company": company, "root_type": "Expense", "is_group": 0},
            "name",
            order_by="lft asc",
        )

    def get_default_offset_account(self, company):
        if not company:
            return None

        account = get_company_default(company, "default_payable_account")
        if account:
            return account

        account = frappe.db.get_value(
            "Account",
            {
                "company": company,
                "root_type": "Liability",
                "account_type": ["in", ["Payable", "Current Liability"]],
                "is_group": 0,
            },
            "name",
            order_by="lft asc",
        )
        if account:
            return account

        return frappe.db.get_value(
            "Account",
            {"company": company, "root_type": "Liability", "is_group": 0},
            "name",
            order_by="lft asc",
        )

    def get_default_source_offset_account(self, company):
        if not company:
            return None

        account = get_company_default(company, "default_receivable_account")
        if account:
            return account

        account = get_company_default(company, "default_payable_account")
        if account:
            return account

        account = frappe.db.get_value(
            "Account",
            {
                "company": company,
                "root_type": "Asset",
                "account_type": ["in", ["Receivable", "Current Asset"]],
                "is_group": 0,
            },
            "name",
            order_by="lft asc",
        )
        if account:
            return account

        return frappe.db.get_value(
            "Account",
            {"company": company, "root_type": "Asset", "is_group": 0},
            "name",
            order_by="lft asc",
        )

    def get_default_cost_center(self, company):
        if not company:
            return None

        account = get_company_default(company, "cost_center")
        if account:
            return account

        account = get_company_default(company, "default_cost_center")
        if account:
            return account

        return frappe.db.get_value(
            "Cost Center",
            {"company": company, "is_group": 0},
            "name",
            order_by="lft asc",
        )


def get_company_default(company, fieldname):
    if not company or not frappe.get_meta("Company").has_field(fieldname):
        return None
    return frappe.db.get_value("Company", company, fieldname)


def journal_entry_has_allocation_field():
    try:
        return frappe.db.has_column("Journal Entry", "custom_jazira_expense_allocation")
    except Exception:
        return False
