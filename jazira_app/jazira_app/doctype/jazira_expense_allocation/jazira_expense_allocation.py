# Copyright (c) 2026, Jazira App and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import cint, flt, get_first_day, get_last_day, getdate


ALLOCATION_REMARK_PREFIX = "Jazira Expense Allocation:"

# Aralash foyda bazasi: manba kompaniya — маржинал, filiallar — соф foyda.
MIXED_PROFIT_SOURCE = "Маржинал (манба) / Соф фойда (филиаллар)"

# Taqsimlanadigan xarajat guruhi — faqat ma'muriy (Адм) xarajatlar.
# Operatsion (52001) xarajatlar har filialning o'zida qoladi va hovuzga kirmaydi.
ADMIN_EXPENSE_GROUP = "52002"

DEFAULT_COMPANIES = (
    "Jazira Sklad",
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
        # Frappe submit paytida AVVAL docstatus'ni 1 qilib qo'yadi, keyin
        # before_submit'ni chaqiradi (frappe/model/document.py:_submit).
        # Shuning uchun calculate() ichidagi "faqat Draft" himoyasi shu
        # yerda ishlab ketib, submit'ni butunlay bloklab qo'yardi.
        # Bayroq flags orqali beriladi — uni brauzerdan o'rnatib bo'lmaydi.
        self.flags.allow_calculate_on_submit = True
        try:
            self.calculate(save=False)
        finally:
            self.flags.allow_calculate_on_submit = False

        self.validate_unique_submitted_period()
        self.validate_submit_ready()

    def on_submit(self):
        # Yangi mexanizm (egalar talabi bilan qayta ishlangan):
        #   JE-1 (Sklad):  Дт Tranzit kassa (jami filial ulushi)
        #                  Кт asl ma'muriy hisoblar (ulush nisbatida)
        #   JE-2 (Sklad):  Дт 1310 Debtors [Customer: filial] (har biri o'z ulushi)
        #                  Кт Tranzit kassa (jami)
        #   JE-3 (filial): Дт filialning MOS ma'muriy hisoblari (hovuz tarkibida)
        #                  Кт 2110 Creditors [Supplier: Sklad]
        # Qarz keyin filialning odatiy Kassa to'lovlari bilan yopiladi —
        # avtomatik взаимозачёт YARATILMAYDI.
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
        # Tartib muhim: взаимозачёт/to'lovlar allocation JE'larga ilingan,
        # shuning uchun avval ular bekor qilinadi, keyin yozuvlar.
        self.cancel_netting_journal_entries()
        self.cancel_settlement_payment_entries()  # eski hujjatlardagi PE'lar uchun
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
        company = self.expense_source_company

        if not company:
            companies = self.get_allocation_companies()
            company = companies[0] if companies else DEFAULT_COMPANIES[0]

        if company:
            self.currency = frappe.db.get_value("Company", company, "default_currency")

    def validate_expense_scope(self):
        if not self.expense_source_company:
            frappe.throw(_("Xarajat manba kompaniyasi majburiy"))

        # Guruh kompaniyasi (masalan "Jazira") manba bo'la olmaydi — unda
        # hech qanday operatsiya yuritilmaydi, hovuz doim 0 chiqadi.
        if frappe.db.get_value("Company", self.expense_source_company, "is_group"):
            frappe.throw(
                _(
                    "'{0}' — guruh kompaniyasi, xarajat manba bo'la olmaydi. "
                    "Ishchi kompaniyani tanlang (masalan Jazira Sklad)."
                ).format(self.expense_source_company)
            )

    def set_source_offset_account(self):
        if not cint(self.create_source_reversal):
            return

        # Filiallararo qarz party bilan qayd etilgani uchun bu yerda
        # Receivable turidagi hisob kerak. Boshqa tur saqlanib qolgan bo'lsa
        # (eski hujjatlar), avtomatik to'g'risiga almashtiramiz.
        if self.source_offset_account and get_account_type(self.source_offset_account) != RECEIVABLE_TYPE:
            replacement = self.get_default_source_offset_account(self.expense_source_company)
            if replacement:
                frappe.msgprint(
                    _("Manba hisobi '{0}' → '{1}' bilan almashtirildi (debitorlik hisobi kerak).").format(
                        self.source_offset_account, replacement
                    ),
                    indicator="orange",
                    alert=True,
                )
                self.source_offset_account = replacement

        if not self.source_offset_account:
            self.source_offset_account = self.get_default_source_offset_account(
                self.expense_source_company
            )

        # Tranzit kassa (Shaxboz naqd) — JE-1/JE-2 shu orqali o'tadi
        if not self.get("source_cash_account"):
            self.source_cash_account = get_default_source_cash_account(
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
        if self.docstatus != 0 and not self.flags.get("allow_calculate_on_submit"):
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
                    "company": expense.company,
                    "account": expense.account,
                    "account_name": expense.account_name,
                    "debit": flt(expense.debit, 2),
                    "credit": flt(expense.credit, 2),
                    "net_amount": flt(expense.net_amount, 2),
                    # Qator endi hisob bo'yicha JAMI — qaysi hujjatlardan
                    # yig'ilgani soni izohda turadi.
                    "user_remark": _("{0} ta Journal Entry jami").format(expense.doc_count),
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
            # Filial tomonidagi qarz party bilan qayd etilgani uchun Payable
            # turidagi hisob kerak — boshqasi bo'lsa to'g'risiga almashtiramiz.
            if row.offset_account and get_account_type(row.offset_account) != PAYABLE_TYPE:
                row.offset_account = None
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

        if self.profit_source == MIXED_PROFIT_SOURCE:
            # Manba (Sklad): МАРЖИНАЛ foyda — Выручка − Себестоимость.
            # Sababi: Skladning o'z JE xarajatlari aynan taqsimlanadigan
            # hovuzning o'zi — ularni foydadan ayirib yuborsak, Sklad ulushi
            # sun'iy kichrayib, yuk filiallarga og'ib ketardi.
            #
            # Filiallar: СОФ (chistaya) foyda — barcha xarajatlari ayirilgan
            # haqiqiy natija. Zarar ko'rgan filial bazasi 0 bo'ladi va u
            # ma'muriy yuk olmaydi.
            if company == self.expense_source_company:
                return self.get_marginal_profit(company)
            return self.get_gl_profit(company, include_journal_entries=True)

        if self.profit_source == "Sales Invoice Gross Profit":
            return self.get_sales_invoice_gross_profit(company)

        include_journal_entries = self.profit_source == "GL Net Profit"
        return self.get_gl_profit(company, include_journal_entries=include_journal_entries)

    def get_marginal_profit(self, company):
        """Маржинал foyda = Выручка − Себестоимость (PL Hisoboti bilan bir xil).

        Себестоимость = account_type 'Cost of Goods Sold' + 'Stock Adjustment'
        (har qanday hujjat turidan). Operatsion/ma'muriy xarajatlar ayirilmaydi.
        """
        allocation_filter = self.get_journal_entry_exclusion_sql("je")

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
                AND (
                    acc.root_type = 'Income'
                    OR acc.account_type IN ('Cost of Goods Sold', 'Stock Adjustment')
                )
                AND {allocation_filter}
            """,
            self.get_query_params(company),
            as_dict=True,
        )

        return flt(result[0].profit if result else 0, 2)

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

    def get_admin_expense_groups(self, companies):
        """Berilgan kompaniyalarning "52002 - Адм" guruh hisoblarini qaytaradi.

        Taqsimlanadigan hovuzga FAQAT ma'muriy (Адм) xarajatlar kiradi —
        operatsion (52001) xarajatlar har filialning o'zida qoladi.
        """
        groups = []
        for company in companies:
            group = frappe.db.get_value(
                "Account",
                {
                    "company": company,
                    "account_number": ADMIN_EXPENSE_GROUP,
                    "root_type": "Expense",
                    "is_group": 1,
                },
                "name",
            )
            if group:
                groups.append(group)
        return groups

    def get_period_journal_expenses(self):
        companies = self.get_expense_companies()
        if not companies:
            return []

        admin_groups = self.get_admin_expense_groups(companies)
        if not admin_groups:
            frappe.throw(
                _("'{0}' kompaniyasida '{1}' (Адм) xarajat guruhi topilmadi").format(
                    companies[0], ADMIN_EXPENSE_GROUP
                )
            )

        allocation_filter = self.get_journal_entry_exclusion_sql("je")
        params = self.get_query_params(self.expense_source_company)
        params["expense_companies"] = tuple(companies)
        params["admin_groups"] = tuple(admin_groups)

        # Har bir HISOB bo'yicha JAMLANGAN summa qaytariladi (egalar talabi:
        # jadvalda "Obed-Ujen — 18 000, 466 000, 150 000..." emas, bitta qator
        # "Obed-Ujen — jami" ko'rinishi kerak). Nechta hujjatdan yig'ilgani
        # doc_count'da saqlanadi va izohda ko'rsatiladi.
        return frappe.db.sql(
            f"""
            SELECT
                je.company,
                jea.account,
                acc.account_name,
                COUNT(DISTINCT je.name) AS doc_count,
                SUM(COALESCE(jea.debit, 0)) AS debit,
                SUM(COALESCE(jea.credit, 0)) AS credit,
                SUM(COALESCE(jea.debit, 0) - COALESCE(jea.credit, 0)) AS net_amount
            FROM `tabJournal Entry` je
            INNER JOIN `tabJournal Entry Account` jea ON jea.parent = je.name
            INNER JOIN `tabAccount` acc ON acc.name = jea.account
            WHERE je.company IN %(expense_companies)s
                AND je.docstatus = 1
                AND je.posting_date BETWEEN %(from_date)s AND %(to_date)s
                AND acc.root_type = 'Expense'
                AND acc.parent_account IN %(admin_groups)s
                AND {allocation_filter}
            GROUP BY je.company, jea.account, acc.account_name
            HAVING ABS(SUM(COALESCE(jea.debit, 0) - COALESCE(jea.credit, 0))) > 0.005
            ORDER BY net_amount DESC
            """,
            params,
            as_dict=True,
        )

    def get_expense_companies(self):
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
            if not self.source_offset_account:
                frappe.throw(_("Manba clearing account to'ldirilmagan"))

            # Filiallararo qarz party bilan yoziladi — shuning uchun bu yerda
            # aynan Receivable turidagi hisob bo'lishi shart.
            if get_account_type(self.source_offset_account) != RECEIVABLE_TYPE:
                frappe.throw(
                    _(
                        "'{0}' — debitorlik (Receivable) hisobi emas. Filiallararo qarz "
                        "party bilan qayd etilishi uchun manba hisobi Receivable turida "
                        "bo'lishi kerak (masalan '1310 - Debtors')."
                    ).format(self.source_offset_account)
                )

            # Har bir qarzdor filial uchun ichki mijoz bo'lishi shart
            missing_customers = [
                row.company
                for row in self.companies
                if row.company != self.expense_source_company
                and flt(row.allocated_expense_amount) > 0
                and not get_internal_customer(row.company)
            ]
            if missing_customers:
                frappe.throw(
                    _("Quyidagi kompaniyalar uchun ichki mijoz (internal customer) topilmadi: {0}").format(
                        ", ".join(missing_customers)
                    )
                )

            self.validate_account(
                self.source_offset_account,
                self.expense_source_company,
                _("Manba clearing account"),
            )

            # Tranzit kassa — naqd (Cash/Bank) hisob bo'lishi shart
            if not self.get("source_cash_account"):
                frappe.throw(_("Tranzit kassa hisobi to'ldirilmagan"))
            if get_account_type(self.source_cash_account) not in ("Cash", "Bank"):
                frappe.throw(
                    _(
                        "'{0}' — naqd (Cash) hisobi emas. Tranzit uchun kassa hisobi "
                        "kerak (masalan '1110 - Нахт')."
                    ).format(self.source_cash_account)
                )
            self.validate_account(
                self.source_cash_account,
                self.expense_source_company,
                _("Tranzit kassa"),
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
            # Manba kompaniyaning o'z ulushi joyida qoladi — unga JE yozilmaydi,
            # shuning uchun qarshi hisob talablari ham qo'llanmaydi.
            if row.company != self.expense_source_company:
                if get_account_type(row.offset_account) != PAYABLE_TYPE:
                    frappe.throw(
                        _(
                            "'{0}' — kreditorlik (Payable) hisobi emas. '{1}' filiali Skladga "
                            "qarzdorligi party bilan qayd etilishi uchun Payable turidagi hisob "
                            "kerak (masalan '2110 - Creditors')."
                        ).format(row.offset_account, row.company)
                    )
                if not get_internal_supplier(self.expense_source_company):
                    frappe.throw(
                        _("'{0}' uchun ichki taminotchi (internal supplier) topilmadi").format(
                            self.expense_source_company
                        )
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
        """Sklad tomonidagi ikkita JE — egalar chizgan sxema bo'yicha.

        JE-1 "xarajatlarni kassaga yopish":
            Дт Tranzit kassa (Shaxboz naqd)      — jami filial ulushi
            Кт asl ma'muriy hisoblar             — ulush nisbatida sochilgan
        JE-2 "kassadan filial qarziga":
            Дт 1310 Debtors [Customer: filial]   — har filial o'z ulushi
            Кт Tranzit kassa                     — jami

        Kassa faqat TRANZIT — ikkala JE'dan keyin qoldig'i o'zgarmaydi,
        lekin kassa hisobotlarida kirim/chiqim sifatida ko'rinadi (egalar
        talabi shu edi). Manba kompaniyaning O'Z ulushi chiqarilmaydi —
        o'z xarajat hisoblarida qoladi.
        """
        if not cint(self.create_source_reversal):
            return []

        grouped_by_company = self.get_grouped_expenses_by_company()
        grouped_expenses = grouped_by_company.get(self.expense_source_company, {})
        if not grouped_expenses:
            return []

        debtor_rows = self.get_branch_share_rows()
        recharged_total = flt(sum(a for _c, _co, a in debtor_rows), 2)
        if recharged_total <= 0.005:
            return []

        created = []

        if not (
            self.source_reversal_journal_entry
            and frappe.db.exists("Journal Entry", self.source_reversal_journal_entry)
        ):
            je_name = self.create_reversal_to_cash_je(grouped_expenses, recharged_total)
            if je_name:
                self.db_set("source_reversal_journal_entry", je_name)
                self.source_reversal_journal_entry = je_name
                created.append(je_name)

        if not (
            self.get("source_receivable_journal_entry")
            and frappe.db.exists("Journal Entry", self.source_receivable_journal_entry)
        ):
            je_name = self.create_cash_to_receivable_je(debtor_rows, recharged_total)
            if je_name:
                self.db_set("source_receivable_journal_entry", je_name)
                self.source_receivable_journal_entry = je_name
                created.append(je_name)

        return created

    def get_grouped_expenses_by_company(self):
        """Xarajatlarni kompaniya -> (hisob, cost center) bo'yicha jamlash.

        Expenses jadvali endi hisob bo'yicha JAMLANGAN (cost_center bo'sh),
        shuning uchun kalitga kompaniyaning standart cost markazi tushadi.
        """
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

    def get_branch_share_rows(self):
        """Har bir filial (manbadan tashqari) uchun (customer, company, ulush)."""
        rows = []
        for row in self.companies:
            if row.company == self.expense_source_company:
                continue
            amount = flt(row.allocated_expense_amount, 2)
            if amount <= 0:
                continue
            customer = get_internal_customer(row.company)
            if not customer:
                frappe.throw(_("'{0}' uchun ichki mijoz topilmadi").format(row.company))
            rows.append((customer, row.company, amount))
        return rows

    def new_allocation_je(self, company, label):
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
        return je

    def create_reversal_to_cash_je(self, grouped_expenses, recharged_total):
        """JE-1: Дт Tranzit kassa (jami) / Кт ma'muriy hisoblar (nisbatda)."""
        total_expense = flt(sum(grouped_expenses.values()), 2)
        if abs(total_expense) <= 0.005:
            return None

        je = self.new_allocation_je(
            self.expense_source_company, "xarajatlarni kassaga yopish (filiallar ulushi)"
        )

        # Дт — tranzit kassa, bitta qator, jami summa
        je.append(
            "accounts",
            {
                "account": self.source_cash_account,
                "debit_in_account_currency": recharged_total,
                "credit_in_account_currency": 0,
                "user_remark": je.user_remark,
            },
        )

        # Кт — asl xarajat hisoblari, filiallar ulushi nisbatida
        ratio = recharged_total / total_expense if total_expense else 0
        credited = 0.0
        items = [(k, v) for k, v in grouped_expenses.items() if abs(flt(v, 2)) > 0.005]
        for idx, ((account, cost_center), net_amount) in enumerate(items):
            share = flt(flt(net_amount) * ratio, 2)
            # Oxirgi qatorga yaxlitlash qoldig'i — jami aniq mos kelsin
            if idx == len(items) - 1:
                share = flt(recharged_total - credited, 2)
            credited = flt(credited + share, 2)
            if abs(share) <= 0.005:
                continue

            row = {"account": account, "user_remark": je.user_remark}
            if cost_center:
                row["cost_center"] = cost_center
            if share > 0:
                row.update({"debit_in_account_currency": 0, "credit_in_account_currency": share})
            else:
                row.update({"debit_in_account_currency": abs(share), "credit_in_account_currency": 0})
            je.append("accounts", row)

        je.insert(ignore_permissions=True)
        je.submit()
        return je.name

    def create_cash_to_receivable_je(self, debtor_rows, recharged_total):
        """JE-2: Дт 1310 [Customer: filial] (ulushlar) / Кт Tranzit kassa (jami)."""
        je = self.new_allocation_je(
            self.expense_source_company, "kassadan filial qarziga (1310)"
        )

        # Дт — har filial alohida, party bilan
        for customer, branch, amount in debtor_rows:
            je.append(
                "accounts",
                {
                    "account": self.source_offset_account,
                    "party_type": "Customer",
                    "party": customer,
                    "debit_in_account_currency": amount,
                    "credit_in_account_currency": 0,
                    "user_remark": f"{je.user_remark} | {branch}",
                },
            )

        # Кт — tranzit kassa, jami
        je.append(
            "accounts",
            {
                "account": self.source_cash_account,
                "debit_in_account_currency": 0,
                "credit_in_account_currency": recharged_total,
                "user_remark": je.user_remark,
            },
        )

        je.insert(ignore_permissions=True)
        je.submit()
        return je.name

    def get_branch_admin_spread(self, row, amount):
        """Filial ulushini hovuz tarkibi nisbatida MOS hisoblarga taqsimlash.

        Hovuz (Sklad'ning 52002 xarajatlari) hisob nomlari bo'yicha olinadi,
        filialda XUDDI SHU NOMLI hisob 52002 guruhi ostidan qidiriladi
        (raqam bo'yicha emas — masalan "Ish haqqi" Sklad'da 5201, filialda
        5259). Topilmaganlari row.expense_account'ga jamlanadi.

        Qaytaradi: [(account, summa)] — yig'indisi aynan `amount`.
        """
        pool_total = flt(self.total_expense_amount, 2)
        pool_items = [
            (e.account_name, flt(e.net_amount))
            for e in self.expenses
            if e.company == self.expense_source_company and abs(flt(e.net_amount)) > 0.005
        ]
        if not pool_items or pool_total <= 0:
            return [(row.expense_account, amount)]

        admin_group = frappe.db.get_value(
            "Account",
            {
                "company": row.company,
                "account_number": ADMIN_EXPENSE_GROUP,
                "root_type": "Expense",
                "is_group": 1,
            },
            "name",
        )

        raw = {}
        for account_name, net in pool_items:
            target = None
            if admin_group and account_name:
                target = frappe.db.get_value(
                    "Account",
                    {
                        "company": row.company,
                        "parent_account": admin_group,
                        "account_name": account_name,
                        "is_group": 0,
                    },
                    "name",
                )
            target = target or row.expense_account
            raw[target] = raw.get(target, 0) + amount * flt(net) / pool_total

        rows = [(acc, flt(v, 2)) for acc, v in raw.items()]
        rows = [(acc, v) for acc, v in rows if abs(v) > 0.005]
        if not rows:
            return [(row.expense_account, amount)]

        # Yaxlitlash qoldig'i eng katta qatorga — jami aynan amount bo'lsin
        diff = flt(amount - sum(v for _a, v in rows), 2)
        if abs(diff) > 0.001:
            idx = max(range(len(rows)), key=lambda i: abs(rows[i][1]))
            rows[idx] = (rows[idx][0], flt(rows[idx][1] + diff, 2))

        return rows

    def create_allocation_journal_entries(self):
        created = []
        source_supplier = get_internal_supplier(self.expense_source_company)

        for row in self.companies:
            amount = flt(row.allocated_expense_amount, 2)
            if amount <= 0:
                continue

            # Manba kompaniyaning o'z ulushi allaqachon o'z xarajat
            # hisoblarida turibdi — unga qayta yozuv kerak emas.
            if row.company == self.expense_source_company:
                continue

            if row.allocation_journal_entry and frappe.db.exists(
                "Journal Entry", row.allocation_journal_entry
            ):
                continue

            if not source_supplier:
                frappe.throw(
                    _("'{0}' uchun ichki taminotchi topilmadi").format(self.expense_source_company)
                )

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

            # Дт — ulush filialning MOS ma'muriy hisoblariga sochiladi
            # (hovuz tarkibi nisbatida: Ish haqqi ulushi -> filialning
            # "Ish haqqi"siga va h.k.). Mos hisob topilmasa —
            # row.expense_account ("Ма'мурий харажат улуши") ga tushadi.
            for account, share in self.get_branch_admin_spread(row, amount):
                debit_row = {
                    "account": account,
                    "user_remark": je.user_remark,
                }
                if share > 0:
                    debit_row.update(
                        {"debit_in_account_currency": share, "credit_in_account_currency": 0}
                    )
                else:
                    debit_row.update(
                        {"debit_in_account_currency": 0, "credit_in_account_currency": abs(share)}
                    )
                if row.cost_center:
                    debit_row["cost_center"] = row.cost_center
                je.append("accounts", debit_row)

            # Кт — Skladga qarz, party (ichki taminotchi) bilan qayd etiladi.
            # Qarz keyin filialning odatiy Kassa to'lovlari (Дт 2110) bilan
            # tabiiy ravishda yopiladi.
            je.append(
                "accounts",
                {
                    "account": row.offset_account,
                    "party_type": "Supplier",
                    "party": source_supplier,
                    "debit_in_account_currency": 0,
                    "credit_in_account_currency": amount,
                    "user_remark": je.user_remark,
                },
            )

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

    # ------------------------------------------------------------------
    # Bekor qilish. cancel_netting/settlement — ESKI hujjatlar uchun
    # saqlangan (yangi mexanizm взаимозачёт/PE yaratmaydi).
    # ------------------------------------------------------------------

    def cancel_netting_journal_entries(self):
        for row in self.companies:
            name = row.get("netting_journal_entry")
            if not name or not frappe.db.exists("Journal Entry", name):
                continue
            je = frappe.get_doc("Journal Entry", name)
            if je.docstatus == 1:
                je.flags.ignore_permissions = True
                je.cancel()

    def cancel_settlement_payment_entries(self):
        for row in self.companies:
            for fieldname in ("branch_payment_entry", "source_payment_entry"):
                name = row.get(fieldname)
                if not name or not frappe.db.exists("Payment Entry", name):
                    continue
                pe = frappe.get_doc("Payment Entry", name)
                if pe.docstatus == 1:
                    pe.flags.ignore_permissions = True
                    pe.cancel()

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
        # Avval JE-2 (1310 <- kassa), keyin JE-1 (kassa <- xarajatlar)
        if self.get("source_receivable_journal_entry"):
            journal_entries.append(self.source_receivable_journal_entry)
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
        """Filialga tushadigan ma'muriy ulush qaysi hisobga yoziladi.

        Bu — MA'MURIY xarajat, shuning uchun u "52002 Адм" guruhi ostida
        bo'lishi kerak. Kompaniyaning default_expense_account'i odatda
        "5111 Cost of Goods Sold" bo'ladi — unga yozilsa ma'muriy xarajat
        tannarxga tushib, yalpi marjani buzardi.
        """
        if not company:
            return None

        admin_group = frappe.db.get_value(
            "Account",
            {
                "company": company,
                "account_number": ADMIN_EXPENSE_GROUP,
                "root_type": "Expense",
                "is_group": 1,
            },
            "name",
        )
        if admin_group:
            # Maxsus "ulush" hisobi bo'lsa — o'sha, aks holda guruhning
            # birinchi hisobi.
            account = frappe.db.get_value(
                "Account",
                {
                    "company": company,
                    "parent_account": admin_group,
                    "is_group": 0,
                    "account_name": ["like", "%улуш%"],
                },
                "name",
            )
            if account:
                return account

            account = frappe.db.get_value(
                "Account",
                {"company": company, "parent_account": admin_group, "is_group": 0},
                "name",
                order_by="lft asc",
            )
            if account:
                return account

        return frappe.db.get_value(
            "Account",
            {"company": company, "root_type": "Expense", "is_group": 0},
            "name",
            order_by="lft asc",
        )

    def get_default_offset_account(self, company):
        """Filialning qarshi (offset) hisobi — "biz bosh kompaniyaga qarzdormiz".

        Party (ichki taminotchi = Sklad) bilan birga ishlatiladi, shuning uchun
        Payable turidagi hisob aynan kerak.
        """
        if not company:
            return None

        account = get_company_default(company, "default_payable_account")
        if account and get_account_type(account) == PAYABLE_TYPE:
            return account

        return frappe.db.get_value(
            "Account",
            {
                "company": company,
                "root_type": "Liability",
                "is_group": 0,
                "account_type": PAYABLE_TYPE,
            },
            "name",
            order_by="lft asc",
        )

    def get_default_source_offset_account(self, company):
        return get_default_clearing_account(company)

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


# Filiallararo qarz PARTY (mijoz/taminotchi) bilan qayd etiladi — shundagina
# uni Akt Sverkada ko'rish va Payment Entry bilan yopish mumkin. Shuning uchun
# manba tomonida Receivable, filial tomonida Payable turidagi hisob KERAK.
RECEIVABLE_TYPE = "Receivable"
PAYABLE_TYPE = "Payable"


def get_account_type(account):
    return frappe.db.get_value("Account", account, "account_type") if account else None


def get_internal_customer(company):
    """Shu kompaniyani ifodalovchi ichki mijoz — boshqa kompaniya kitobida
    "bu filial bizga qarzdor" deb yozish uchun kerak."""
    if not company:
        return None
    return frappe.db.get_value(
        "Customer", {"represents_company": company, "is_internal_customer": 1}, "name"
    )


def get_internal_supplier(company):
    """Shu kompaniyani ifodalovchi ichki taminotchi — filial kitobida
    "biz bosh kompaniyaga qarzdormiz" deb yozish uchun kerak."""
    if not company:
        return None
    return frappe.db.get_value(
        "Supplier", {"represents_company": company, "is_internal_supplier": 1}, "name"
    )


@frappe.whitelist()
def get_default_source_cash_account(company):
    """Tranzit kassa — "Shaxboz kassa" (naqd).

    Egalar sxemasida filiallar ulushi avval SHU kassaga "tushadi" (JE-1),
    keyin undan filial qarziga o'tadi (JE-2). Qidiruv tartibi:
      1) nomida "shaxboz" bo'lgan Mode of Payment'ning shu kompaniyadagi
         hisobi (jonli bazada: "Нахт Склад Shaxboz" -> 1110 - Нахт - JS);
      2) kompaniyaning default_cash_account'i;
      3) birinchi Cash hisob.
    """
    if not company:
        return None

    mop_account = frappe.db.sql(
        """
        SELECT mpa.default_account
        FROM `tabMode of Payment Account` mpa
        INNER JOIN `tabMode of Payment` mop ON mop.name = mpa.parent
        WHERE mpa.company = %s
          AND (LOWER(mop.name) LIKE '%%shaxboz%%' OR LOWER(mop.name) LIKE '%%шахбоз%%')
          AND IFNULL(mpa.default_account, '') != ''
        LIMIT 1
        """,
        (company,),
    )
    if mop_account and mop_account[0][0]:
        return mop_account[0][0]

    account = get_company_default(company, "default_cash_account")
    if account:
        return account

    return frappe.db.get_value(
        "Account",
        {"company": company, "account_type": "Cash", "is_group": 0},
        "name",
        order_by="lft asc",
    )


@frappe.whitelist()
def get_default_clearing_account(company):
    """Manba kompaniyaning debitorlik hisobi — "filiallar bizga qarzdor".

    Party bilan birga ishlatiladi (party = filialning ichki mijozi), shuning
    uchun Receivable turidagi hisob aynan kerak.

    Foydalanuvchi kompaniyani tanlaganda brauzerdan ham chaqiriladi.
    """
    if not company:
        return None

    account = get_company_default(company, "default_receivable_account")
    if account and get_account_type(account) == RECEIVABLE_TYPE:
        return account

    return frappe.db.get_value(
        "Account",
        {"company": company, "root_type": "Asset", "account_type": RECEIVABLE_TYPE, "is_group": 0},
        "name",
        order_by="lft asc",
    )


def journal_entry_has_allocation_field():
    try:
        return frappe.db.has_column("Journal Entry", "custom_jazira_expense_allocation")
    except Exception:
        return False


def payment_entry_has_allocation_field():
    try:
        return frappe.db.has_column("Payment Entry", "custom_jazira_expense_allocation")
    except Exception:
        return False
