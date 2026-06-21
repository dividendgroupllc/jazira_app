# -*- coding: utf-8 -*-
# Copyright (c) 2026, Jazira App
# License: MIT

"""
Kassa v3.6 - Company Mode of Payment'dan avtomatik

Company tekshiruvi FAQAT Расходы uchun!
Перемещение da har xil company bo'lishi mumkin.
"""

import frappe
from frappe import _
from frappe.model.document import Document

# Divident kontragent turlari -> hisob raqami (to'lovchi company bo'yicha olinadi)
DIVIDEND_ACCOUNT_NUMBERS = {
    "Divident Akmal": "3200",
    "Divident Elyor": "3201",
}


class Kassa(Document):
    """Kassa Document."""
    
    def validate(self):
        self.validate_summa()
        self.validate_kontragent()
        self.set_company_and_accounts()
        self.validate_transfer()
        self.validate_expense_kontragent()
        self.clear_irrelevant_fields()

    def validate_summa(self):
        """Summa > 0 bo'lishi kerak."""
        if self.summa <= 0:
            frappe.throw(_("Summa 0 dan katta bo'lishi kerak"))

    def validate_kontragent(self):
        """- CUSTOMER: company-ifodalovchi ichki kontragentni qo'lda tanlash
             taqiqlanadi (self-dealing).
           - SUPPLIER: faqat o'z company'sini ifodalovchi supplier taqiqlanadi
             (o'ziga to'lov). Boshqa company supplier'iga (masalan Sklad)
             filialdan to'lash mumkin."""
        if self.party_type == "Customer" and self.kontragent:
            represents = frappe.db.get_value(
                "Customer", self.kontragent, "represents_company"
            )
            payer_company = self._payer_company()
            # Faqat o'ziga to'lovni (self-dealing) bloklaymiz: kontragent
            # to'lovchi company'ning o'zini ifodalasa. Boshqa filialni
            # ifodalovchi internal customer (Sklad -> filial) RUXSAT etiladi.
            if represents and payer_company and represents == payer_company:
                frappe.throw(_(
                    "'{0}' — to'lovchi kompaniyaning ({1}) o'zini ifodalovchi "
                    "ichki kontragent. Bu o'ziga to'lov bo'lib qoladi. Boshqa "
                    "kontragent yoki boshqa kassani tanlang."
                ).format(self.kontragent, payer_company))

        if self.party_type == "Supplier" and self.kontragent:
            represents = frappe.db.get_value(
                "Supplier", self.kontragent, "represents_company"
            )
            payer_company = self._payer_company()
            if represents and payer_company and represents == payer_company:
                frappe.throw(_(
                    "'{0}' supplier '{1}' kompaniyasini ifodalaydi — to'lov ham shu "
                    "kompaniya kassasidan. Bu o'ziga to'lov bo'lib qoladi. Boshqa "
                    "supplier yoki boshqa kassani tanlang."
                ).format(self.kontragent, payer_company))

    def _payer_company(self):
        """To'lovchi (Qaysi hisobdan) company'si."""
        if self.company:
            return self.company
        if self.source_account:
            return get_mode_of_payment_info(self.source_account).get("company")
        return None
    
    def set_company_and_accounts(self):
        """Mode of Payment'dan company va account olish."""
        if self.oborot == "Перемещение":
            source_company = None
            target_company = None
            
            if self.transfer_source_display:
                info = get_mode_of_payment_info(self.transfer_source_display)
                if info.get("account"):
                    self.payment_account = info["account"]
                    self.company = info["company"]
                    source_company = info["company"]
                else:
                    frappe.throw(_("'{0}' uchun hisob topilmadi.").format(self.transfer_source_display))
            
            if self.target_account:
                info2 = get_mode_of_payment_info(self.target_account)
                if info2.get("account"):
                    self.payment_account_2 = info2["account"]
                    target_company = info2["company"]
                else:
                    frappe.throw(_("'{0}' uchun hisob topilmadi.").format(self.target_account))
            
            # MUHIM: Перемещение da company bir xil bo'lishi SHART
            if source_company and target_company and source_company != target_company:
                frappe.throw(
                    _("Перемещение: Manba ({0}) va maqsad ({1}) hisob bir xil kompaniyaga tegishli bo'lishi kerak.").format(
                        source_company, target_company
                    )
                )
        else:
            if self.source_account:
                info = get_mode_of_payment_info(self.source_account)
                if info.get("account"):
                    self.payment_account = info["account"]
                    self.company = info["company"]
                else:
                    frappe.throw(_("'{0}' uchun hisob topilmadi.").format(self.source_account))
        
        # Приход + Supplier/Employee/Shareholder uchun ogohlantirish
        if self.oborot == "Приход" and self.party_type in ["Supplier", "Employee", "Shareholder"]:
            self._warn_prihod_payable_party()
    
    def validate_transfer(self):
        """Перемещение uchun validatsiya."""
        if self.oborot == "Перемещение":
            if not self.transfer_source_display:
                frappe.throw(_("'Qaysi hisobdan' majburiy"))
            if not self.target_account:
                frappe.throw(_("'Qaysi hisobga' majburiy"))
            if self.transfer_source_display == self.target_account:
                frappe.throw(_("Manba va maqsad hisob bir xil bo'lishi mumkin emas"))
    
    def validate_expense_kontragent(self):
        """
        FAQAT Расходы uchun tekshiruv.
        - Filial majburiy (xarajat egasi company'sini belgilaydi).
        - Expense account «Expense» turida bo'lishi kerak.
        - Amortizatsiya (Depreciation) hisobi kassadan to'lanmaydi -> taqiqlanadi.
        - Xarajat hisobi FILIAL company'siga tegishli bo'lishi kerak (xarajat shu
          filial kitobida yoziladi; inter-company'da to'g'ridan-to'g'ri ishlatiladi).
        """
        if self.party_type != "Расходы":
            return

        if not self.filial:
            frappe.throw(_("Расходы uchun Filial tanlanishi shart"))

        filial_company = frappe.db.get_value("Kassa Filial", self.filial, "company")

        if self.expense_kontragent:
            account_data = frappe.db.get_value(
                "Account",
                self.expense_kontragent,
                ["root_type", "company", "account_type"],
                as_dict=True
            )

            if not account_data:
                frappe.throw(_("Xarajat kontragenti topilmadi."))

            if account_data.root_type != "Expense":
                frappe.throw(_("Xarajat kontragenti faqat Expense account bo'lishi kerak."))

            if account_data.account_type == "Depreciation":
                frappe.throw(_(
                    "Amortizatsiya (Depreciation) hisobini kassadan to'lab bo'lmaydi. "
                    "U Asset moduli orqali avtomatik yoziladi. Boshqa xarajat hisobini tanlang."
                ))

            # Xarajat hisobi FILIAL company'siga tegishli bo'lishi kerak
            if filial_company and account_data.company != filial_company:
                frappe.throw(
                    _("Xarajat hisobi '{0}' filiali ({1}) kompaniyasiga tegishli bo'lishi kerak.").format(
                        self.filial, filial_company
                    )
                )
    
    def _warn_prihod_payable_party(self):
        """
        Приход + Supplier/Employee/Shareholder uchun ogohlantirish.
        
        Bu holat odatda "avans qaytishi" uchun ishlatiladi:
        - Avval Supplier/Employee/Shareholder ga avans berilgan (Расход)
        - Endi ular pulni qaytaryapti (Приход)
        
        JE mantiq: Cash Debit, Payable Credit (qarz kamayadi)
        """
        if not self.kontragent or not self.company:
            return
        
        try:
            from erpnext.accounts.party import get_party_account
            party_account = get_party_account(self.party_type, self.kontragent, self.company)
            
            if party_account:
                # Party account balansini tekshirish
                balance = frappe.db.sql("""
                    SELECT SUM(debit) - SUM(credit) as balance
                    FROM `tabGL Entry`
                    WHERE account = %s 
                        AND party_type = %s 
                        AND party = %s 
                        AND is_cancelled = 0
                """, (party_account, self.party_type, self.kontragent), as_dict=True)
                
                current_balance = balance[0].balance if balance and balance[0].balance else 0
                
                # Agar balans 0 yoki credit (manfiy) bo'lsa - ogohlantirish
                if current_balance <= 0:
                    frappe.msgprint(
                        _("⚠️ Diqqat: '{0}' ({1}) uchun avans balansi topilmadi yoki 0.<br><br>"
                          "Bu operatsiya odatda <b>avans qaytishi</b> uchun ishlatiladi - "
                          "ya'ni avval siz ularga pul bergansiz (Расход), endi ular qaytaryapti.<br><br>"
                          "Joriy balans: {2}<br><br>"
                          "Agar bu oddiy daromad bo'lsa, 'Customer' tanlang.").format(
                            self.kontragent, self.party_type, current_balance
                        ),
                        title=_("Avans qaytishi haqida"),
                        indicator="orange"
                    )
        except Exception:
            # Xato bo'lsa ham davom etsin
            pass
    
    def clear_irrelevant_fields(self):
        """Oborot ga qarab keraksiz field'larni tozalash."""
        if self.oborot == "Перемещение":
            self.party_type = None
            self.kontragent = None
            self.expense_kontragent = None
            self.filial = None
            self.source_account = None
            self.source_balance = 0
        else:
            self.transfer_source_display = None
            self.transfer_source_balance = 0
            self.target_account = None
            self.target_balance = 0
            self.payment_account_2 = None
            
            if self.party_type != "Расходы":
                self.filial = None
    
    # =========================================================================
    # ACCOUNTING (Payment Entry / Journal Entry)
    # =========================================================================

    # Kontragent bilan pul muomalasi Payment Entry orqali yuritiladi
    PARTY_TYPES_PE = ("Customer", "Supplier", "Employee", "Shareholder")

    def on_submit(self):
        """Submit bo'lganda mos buxgalteriya hujjatini yaratish.

        - Filiallararo (inter-company) Расход «Расходы» -> 3 hujjat:
          Payment Entry Pay (to'lovchi) + Payment Entry Receive (xarajat filiali)
          + Journal Entry (xarajat, xarajat filiali kitobida)
        - Kontragent (Customer/Supplier/Employee/Shareholder) bilan
          Приход/Расход  -> Payment Entry (Receive/Pay)
        - «Расходы» (bir company ichida) va Перемещение -> Journal Entry
        """
        # Himoya: duplicate/amend orqali nusxalangan eski havolalarni tozalaymiz.
        # Aks holda submit faqat o'zi yaratgan maydonlarni yangilaydi va qolgan
        # eski havolalar (asl hujjatnikilar) cancel paytida xato bekor qilinardi.
        self._reset_accounting_links()

        if self._is_intercompany_expense():
            self.create_intercompany_expense()
        elif self._is_supplier_via_sklad():
            self.create_supplier_payment_via_sklad()
        elif self._is_sklad_to_filial():
            self.create_sklad_to_filial_payment()
        elif self._is_employee_via_filial():
            self.create_employee_payment()
        elif self.oborot in ("Приход", "Расход") and self.party_type in self.PARTY_TYPES_PE:
            self.create_payment_entry()
        else:
            self.create_journal_entry()

    def on_cancel(self):
        """Cancel bo'lganda yaratilgan hujjatni (PE yoki JE) bekor qilish."""
        self.cancel_accounting_documents()

    # Submit yaratadigan buxgalteriya havola maydonlari
    ACCOUNTING_LINK_FIELDS = (
        "payment_entry",
        "payment_entry_receive",
        "payment_entry_supplier",
        "journal_entry",
    )

    def _reset_accounting_links(self):
        """Buxgalteriya havola maydonlarini bo'shatish.

        Duplicate/amend qilinganda bu maydonlar asl hujjatdan nusxalanib qolishi
        mumkin. Submit faqat o'zi yaratgan maydonni yangilaydi, shu sabab eski
        (asl hujjatnikiga ishora qiluvchi) havola qolib ketishi va cancel paytida
        ASL hujjatning PE/JE'sini xato bekor qilishi mumkin edi.
        """
        for fieldname in self.ACCOUNTING_LINK_FIELDS:
            self.set(fieldname, None)
        # DB'dagi nusxalangan eski qiymatlarni ham tozalaymiz: no_copy o'rnatilgunga
        # qadar duplicate qilingan qoralamalarda bu qiymatlar bazaga yozilib qolgan
        # bo'lishi mumkin. Keyin create_* metodlari faqat o'zi yaratgan to'g'ri
        # havolalarni qayta yozadi.
        if not self.is_new():
            frappe.db.set_value(
                "Kassa",
                self.name,
                {f: None for f in self.ACCOUNTING_LINK_FIELDS},
                update_modified=False,
            )
    
    def create_journal_entry(self):
        """Journal Entry yaratish."""
        if not self.company:
            frappe.throw(_("Company topilmadi"))
        
        je = frappe.new_doc("Journal Entry")
        je.voucher_type = "Journal Entry"
        je.posting_date = self.date
        je.company = self.company
        je.user_remark = f"Kassa: {self.name} - {self.oborot}"
        
        if self.oborot == "Перемещение":
            self._add_transfer_entries(je)
        elif self.oborot == "Приход":
            self._add_income_entries(je)
        elif self.oborot == "Расход":
            self._add_expense_entries(je)
        
        je.insert(ignore_permissions=True)
        je.submit()
        
        frappe.db.set_value("Kassa", self.name, "journal_entry", je.name)
        
        frappe.msgprint(
            _("Journal Entry yaratildi: {0}").format(
                f'<a href="/app/journal-entry/{je.name}">{je.name}</a>'
            ),
            indicator="green"
        )

    def create_payment_entry(self):
        """Kontragent bilan pul muomalasi uchun Payment Entry yaratish.

        Приход -> Receive (Дт kassa / Кт party)
        Расход -> Pay     (Дт party / Кт kassa)
        """
        if not self.company:
            frappe.throw(_("Company topilmadi"))
        if not self.kontragent:
            frappe.throw(_("Kontragent tanlanmagan"))

        party_account = self._get_party_account()
        if not party_account:
            frappe.throw(
                _("'{0}' uchun hisob (Account) topilmadi").format(self.kontragent)
            )

        payment_type = "Receive" if self.oborot == "Приход" else "Pay"
        if payment_type == "Receive":
            paid_from, paid_to = party_account, self.payment_account
        else:
            paid_from, paid_to = self.payment_account, party_account

        pe_name = self._submit_payment_entry(
            payment_type=payment_type,
            company=self.company,
            mode_of_payment=self.source_account,
            party_type=self.party_type,
            party=self.kontragent,
            paid_from=paid_from,
            paid_to=paid_to,
        )
        frappe.db.set_value("Kassa", self.name, "payment_entry", pe_name)

        frappe.msgprint(
            _("Payment Entry yaratildi: {0}").format(
                f'<a href="/app/payment-entry/{pe_name}">{pe_name}</a>'
            ),
            indicator="green"
        )

    # -------------------------------------------------------------------------
    # INTER-COMPANY (filiallararo) Расход
    # -------------------------------------------------------------------------

    def _is_intercompany_expense(self):
        """Filiallararo xarajatmi? (Приход/Расход + Расходы + boshqa company filial)."""
        if self.oborot not in ("Приход", "Расход") or self.party_type != "Расходы" or not self.filial:
            return False
        target_company = frappe.db.get_value("Kassa Filial", self.filial, "company")
        return bool(target_company and target_company != self.company)

    def create_intercompany_expense(self):
        """Filiallararo Расход/Приход uchun 3 hujjat yaratish.

        Расход — to'lovchi (Saripul) -> xarajat filiali (Smart):
          1) PE Pay     (Saripul): Дт Debtors(target) / Кт Saripul kassa
          2) PE Receive (Smart):   Дт Smart kassa     / Кт Debtors(payer)
          3) JE         (Smart):   Дт Xarajat         / Кт Smart kassa
        Приход — teskari (pul payer kassasiga kiradi, filial xarajati kamayadi).
        """
        if not self.company:
            frappe.throw(_("To'lovchi company topilmadi"))

        filial = frappe.get_doc("Kassa Filial", self.filial)
        target_company = filial.company
        if not target_company or not filial.mode_of_payment:
            frappe.throw(
                _("'{0}' filiali uchun Kompaniya va Kassa hisobi sozlanmagan").format(
                    self.filial
                )
            )

        # Filial kassa hisobini AYNAN filial company'si bo'yicha olamiz
        target_cash = frappe.db.get_value(
            "Mode of Payment Account",
            {"parent": filial.mode_of_payment, "company": target_company},
            "default_account",
        )
        if not target_cash:
            frappe.throw(
                _("'{0}' filial kassasi ('{1}') uchun '{2}' kompaniyasida hisob topilmadi").format(
                    self.filial, filial.mode_of_payment, target_company
                )
            )

        # Har bir companyni ifodalovchi Customer
        cust_target = self._get_intercompany_customer(target_company)  # Smart
        cust_payer = self._get_intercompany_customer(self.company)     # Saripul
        if not cust_target:
            frappe.throw(_("'{0}' kompaniyasini ifodalovchi Customer topilmadi").format(target_company))
        if not cust_payer:
            frappe.throw(_("'{0}' kompaniyasini ifodalovchi Customer topilmadi").format(self.company))

        from erpnext.accounts.party import get_party_account
        payer_recv = get_party_account("Customer", cust_target, self.company)
        target_recv = get_party_account("Customer", cust_payer, target_company)

        is_expense = self.oborot == "Расход"

        if is_expense:
            # Расход: payer Pay, target Receive, JE Дт xarajat / Кт kassa
            pe_pay = self._submit_payment_entry(
                payment_type="Pay", company=self.company,
                mode_of_payment=self.source_account, party_type="Customer",
                party=cust_target, paid_from=self.payment_account, paid_to=payer_recv,
            )
            pe_recv = self._submit_payment_entry(
                payment_type="Receive", company=target_company,
                mode_of_payment=filial.mode_of_payment, party_type="Customer",
                party=cust_payer, paid_from=target_recv, paid_to=target_cash,
            )
        else:
            # Приход: teskari — payer Receive, target Pay, JE Дт kassa / Кт xarajat
            pe_pay = self._submit_payment_entry(
                payment_type="Receive", company=self.company,
                mode_of_payment=self.source_account, party_type="Customer",
                party=cust_target, paid_from=payer_recv, paid_to=self.payment_account,
            )
            pe_recv = self._submit_payment_entry(
                payment_type="Pay", company=target_company,
                mode_of_payment=filial.mode_of_payment, party_type="Customer",
                party=cust_payer, paid_from=target_cash, paid_to=target_recv,
            )

        # 3) JE (xarajat) - filial kitobida. Xarajat hisobi allaqachon filial
        # company'siniki (52001/52002 guruhdan), to'g'ridan-to'g'ri ishlatiladi.
        je_name = self._submit_expense_je(
            company=target_company,
            expense_account=self.expense_kontragent,
            cash_account=target_cash,
            expense_debit=is_expense,
        )

        frappe.db.set_value(
            "Kassa",
            self.name,
            {
                "payment_entry": pe_pay,
                "payment_entry_receive": pe_recv,
                "journal_entry": je_name,
            },
        )

        frappe.msgprint(
            _("Filiallararo xarajat yaratildi:<br>PE Pay: {0}<br>PE Receive: {1}<br>JE: {2}").format(
                f'<a href="/app/payment-entry/{pe_pay}">{pe_pay}</a>',
                f'<a href="/app/payment-entry/{pe_recv}">{pe_recv}</a>',
                f'<a href="/app/journal-entry/{je_name}">{je_name}</a>',
            ),
            indicator="green"
        )

    # -------------------------------------------------------------------------
    # SUPPLIER -> SKLAD orqali to'lov (filialdan)
    # -------------------------------------------------------------------------

    def _get_sklad_company(self):
        """Sklad company — Sklad Settings'dagi main_warehouse kompaniyasi."""
        mw = frappe.db.get_single_value("Sklad Settings", "main_warehouse")
        if not mw:
            return None
        return frappe.db.get_value("Warehouse", mw, "company")

    def _is_supplier_via_sklad(self):
        """Расход + Supplier + to'lovchi filial (Sklad emas) -> Sklad orqali yo'naltirish."""
        if self.oborot != "Расход" or self.party_type != "Supplier":
            return False
        sklad_company = self._get_sklad_company()
        return bool(sklad_company and self.company and self.company != sklad_company)

    def create_supplier_payment_via_sklad(self):
        """Filialdan supplierga to'lovni Sklad orqali yo'naltiradi.

          1) PE Pay     (Filial): Дт Debtors(Sklad)  / Кт Filial kassa
          2) PE Receive (Sklad):  Дт Sklad kassa      / Кт Debtors(Filial)
          3) PE Pay     (Sklad):  Дт Creditors(Supplier) / Кт Sklad kassa
             (supplier = Sklad o'zi bo'lsa, 3-qadam tushadi)
        """
        if not self.company:
            frappe.throw(_("To'lovchi company topilmadi"))
        if not self.kontragent:
            frappe.throw(_("Supplier tanlanmagan"))

        sklad_company = self._get_sklad_company()
        sklad_cash = frappe.db.get_value("Company", sklad_company, "default_cash_account")
        if not sklad_cash:
            frappe.throw(
                _("'{0}' kompaniyasida Default Cash Account sozlanmagan").format(sklad_company)
            )

        cust_sklad = self._get_intercompany_customer(sklad_company)   # filial kitobida Sklad
        cust_payer = self._get_intercompany_customer(self.company)    # Sklad kitobida filial
        if not cust_sklad:
            frappe.throw(_("'{0}' kompaniyasini ifodalovchi Customer topilmadi").format(sklad_company))
        if not cust_payer:
            frappe.throw(_("'{0}' kompaniyasini ifodalovchi Customer topilmadi").format(self.company))

        from erpnext.accounts.party import get_party_account
        filial_recv = get_party_account("Customer", cust_sklad, self.company)
        sklad_recv = get_party_account("Customer", cust_payer, sklad_company)

        # 1) Filial -> Sklad
        pe_pay = self._submit_payment_entry(
            payment_type="Pay", company=self.company,
            mode_of_payment=self.source_account, party_type="Customer",
            party=cust_sklad, paid_from=self.payment_account, paid_to=filial_recv,
        )
        # 2) Sklad qabul qiladi
        pe_recv = self._submit_payment_entry(
            payment_type="Receive", company=sklad_company,
            mode_of_payment=None, party_type="Customer",
            party=cust_payer, paid_from=sklad_recv, paid_to=sklad_cash,
        )

        # 3) Sklad -> Supplier (supplier = Sklad o'zi bo'lmasa)
        supplier_company = frappe.db.get_value("Supplier", self.kontragent, "represents_company")
        pe_supplier = None
        if supplier_company != sklad_company:
            supplier_payable = get_party_account("Supplier", self.kontragent, sklad_company)
            pe_supplier = self._submit_payment_entry(
                payment_type="Pay", company=sklad_company,
                mode_of_payment=None, party_type="Supplier",
                party=self.kontragent, paid_from=sklad_cash, paid_to=supplier_payable,
            )

        frappe.db.set_value("Kassa", self.name, {
            "payment_entry": pe_pay,
            "payment_entry_receive": pe_recv,
            "payment_entry_supplier": pe_supplier,
        })

        msg = _("Filialdan Sklad orqali to'lov:<br>PE Pay: {0}<br>PE Receive: {1}").format(
            f'<a href="/app/payment-entry/{pe_pay}">{pe_pay}</a>',
            f'<a href="/app/payment-entry/{pe_recv}">{pe_recv}</a>',
        )
        if pe_supplier:
            msg += _("<br>PE Pay (Supplier): {0}").format(
                f'<a href="/app/payment-entry/{pe_supplier}">{pe_supplier}</a>'
            )
        frappe.msgprint(msg, indicator="green")

    # -------------------------------------------------------------------------
    # EMPLOYEE to'lovi (filial orqali)
    # -------------------------------------------------------------------------

    def _is_employee_via_filial(self):
        """Employee to'lovi — qaysi filial ishchisi ekani belgilangan."""
        return bool(
            self.oborot in ("Приход", "Расход")
            and self.party_type == "Employee"
            and self.kontragent
            and self.employee_filial
        )

    def create_employee_payment(self):
        """Employee to'lovi.

        «Filial» (employee_filial) = employee'ni TO'LAYDIGAN company (uning
        kitobida to'lanadi). Manba (source_account) = moliyalashtiruvchi kassa.

        A) TO'G'RIDAN: manba kassa = to'lovchi filial -> 1 PE.
        B) ORALIQDAN: manba va to'lovchi har xil -> pul manba -> to'lovchi
           ko'chadi (inter-company), keyin to'lovchi -> employee. 3 PE.
           Manba yoki to'lovchidan biri Sklad bo'lishi shart (hub).
           Masalan: Saripul kassasi -> Sklad -> employee (Sklad to'laydi).
        """
        from erpnext.accounts.party import get_party_account

        pay_company = self.employee_filial      # employee shu company kitobida to'lanadi
        source_company = self.company

        # A) TO'G'RIDAN
        if source_company == pay_company:
            self.create_payment_entry()
            return

        # B) ORALIQDAN (biri Sklad bo'lishi shart)
        sklad_company = self._get_sklad_company()
        if sklad_company not in (source_company, pay_company):
            frappe.throw(_(
                "Manba kassa yoki «Filial»dan biri Sklad bo'lishi kerak. "
                "Ikki filial o'rtasida to'g'ridan to'lov mumkin emas (Sklad orqali)."
            ))

        pay_cash = frappe.db.get_value("Company", pay_company, "default_cash_account")
        if not pay_cash:
            frappe.throw(_("'{0}' kompaniyasida Default Cash Account sozlanmagan").format(pay_company))
        emp_account = get_party_account("Employee", self.kontragent, pay_company)

        if self.oborot == "Расход":
            # 1+2) manba -> to'lovchi kassa (inter-company)
            pe_a, pe_b = self._move_cash_sf(
                source_company, self.payment_account, self.source_account,
                pay_company, pay_cash,
            )
            # 3) to'lovchi -> employee
            pe_emp = self._submit_payment_entry(
                payment_type="Pay", company=pay_company,
                mode_of_payment=None, party_type="Employee",
                party=self.kontragent, paid_from=pay_cash, paid_to=emp_account,
            )
        else:  # Приход — employee pul qaytaradi -> to'lovchi -> manba
            pe_emp = self._submit_payment_entry(
                payment_type="Receive", company=pay_company,
                mode_of_payment=None, party_type="Employee",
                party=self.kontragent, paid_from=emp_account, paid_to=pay_cash,
            )
            pe_a, pe_b = self._move_cash_sf(
                pay_company, pay_cash, None,
                source_company, self.payment_account,
            )

        frappe.db.set_value("Kassa", self.name, {
            "payment_entry": pe_a,
            "payment_entry_receive": pe_b,
            "payment_entry_supplier": pe_emp,
        })
        frappe.msgprint(
            _("Employee to'lovi ({0} → {1} → ishchi):<br>PE: {2}<br>PE: {3}<br>PE (Employee): {4}").format(
                source_company, pay_company,
                f'<a href="/app/payment-entry/{pe_a}">{pe_a}</a>',
                f'<a href="/app/payment-entry/{pe_b}">{pe_b}</a>',
                f'<a href="/app/payment-entry/{pe_emp}">{pe_emp}</a>',
            ),
            indicator="green"
        )

    def _move_cash_sf(self, from_company, from_cash, from_mop, to_company, to_cash):
        """Sklad <-> filial o'rtasida pul ko'chirish (biri Sklad bo'lishi shart).

        Pul from_cash dan chiqib to_cash ga kiradi. Sklad kitobida filial =
        Customer (Debtors), filial kitobida Sklad = Supplier (Creditors).
        Ikki Payment Entry qaytaradi: (pe_from, pe_to).
        """
        from erpnext.accounts.party import get_party_account

        sklad = self._get_sklad_company()
        filial = to_company if from_company == sklad else from_company
        cust = self._get_intercompany_customer(filial)
        sup = self._get_intercompany_supplier(sklad)
        if not cust:
            frappe.throw(_("'{0}' kompaniyasini ifodalovchi Customer topilmadi").format(filial))
        if not sup:
            frappe.throw(_("'{0}' kompaniyasini ifodalovchi Supplier topilmadi").format(sklad))
        sklad_cust_acc = get_party_account("Customer", cust, sklad)
        filial_sup_acc = get_party_account("Supplier", sup, filial)

        if from_company == sklad:
            # Sklad -> filial: Sklad Pay (Customer filial) / filial Receive (Supplier Sklad)
            pe_from = self._submit_payment_entry(
                payment_type="Pay", company=sklad, mode_of_payment=from_mop,
                party_type="Customer", party=cust, paid_from=from_cash, paid_to=sklad_cust_acc,
            )
            pe_to = self._submit_payment_entry(
                payment_type="Receive", company=filial, mode_of_payment=None,
                party_type="Supplier", party=sup, paid_from=filial_sup_acc, paid_to=to_cash,
            )
        else:
            # filial -> Sklad: filial Pay (Supplier Sklad) / Sklad Receive (Customer filial)
            pe_from = self._submit_payment_entry(
                payment_type="Pay", company=filial, mode_of_payment=from_mop,
                party_type="Supplier", party=sup, paid_from=from_cash, paid_to=filial_sup_acc,
            )
            pe_to = self._submit_payment_entry(
                payment_type="Receive", company=sklad, mode_of_payment=None,
                party_type="Customer", party=cust, paid_from=sklad_cust_acc, paid_to=to_cash,
            )
        return pe_from, pe_to

    def _get_intercompany_customer(self, company):
        """Berilgan companyni ifodalovchi Customer (represents_company)."""
        return frappe.db.get_value("Customer", {"represents_company": company}, "name")

    def _get_intercompany_supplier(self, company):
        """Berilgan companyni ifodalovchi Supplier (represents_company)."""
        return frappe.db.get_value("Supplier", {"represents_company": company}, "name")

    # -------------------------------------------------------------------------
    # SKLAD <-> FILIAL (oddiy mijoz orqali) — supplier-via-sklad'ning teskarisi
    # -------------------------------------------------------------------------

    def _is_sklad_to_filial(self):
        """Sklad kassasi + filialga bog'langan oddiy Customer -> inter-company.

        Customer.jazira_filial_company maydoni qaysi filialni ifodalashini
        ko'rsatadi. Sklad kompaniyasidan/ga pul harakati ikkala kitobda
        (Sklad + filial) yangilanadi.
        """
        if self.oborot not in ("Приход", "Расход") or self.party_type != "Customer" or not self.kontragent:
            return False
        sklad_company = self._get_sklad_company()
        if not sklad_company or self.company != sklad_company:
            return False
        filial_company = self._filial_company_of(self.kontragent)
        return bool(filial_company and filial_company != sklad_company)

    def _filial_company_of(self, customer):
        """Customer qaysi filial company'ni ifodalaydi.

        Birinchi navbatda internal customer (represents_company), bo'lmasa
        jazira_filial_company (oddiy mijoz uchun qo'lda bog'lash) ishlatiladi.
        """
        return (
            frappe.db.get_value("Customer", customer, "represents_company")
            or frappe.db.get_value("Customer", customer, "jazira_filial_company")
        )

    def create_sklad_to_filial_payment(self):
        """Sklad <-> filial pul harakati uchun 2 Payment Entry yaratadi.

        Расход (Sklad -> filial):
          1) PE Pay     (Sklad):  Дт Debtors(oddiy mijoz) / Кт Sklad kassa
          2) PE Receive (Filial): Дт Filial default kassa / Кт Debtors(Sklad)
        Приход (filial -> Sklad) — teskari (pul Sklad kassasiga kiradi).
        """
        from erpnext.accounts.party import get_party_account

        if not self.company:
            frappe.throw(_("Sklad kompaniyasi topilmadi"))
        if not self.kontragent:
            frappe.throw(_("Kontragent tanlanmagan"))

        sklad_company = self.company
        filial_company = self._filial_company_of(self.kontragent)
        filial_cash = frappe.db.get_value("Company", filial_company, "default_cash_account")
        if not filial_cash:
            frappe.throw(
                _("'{0}' kompaniyasida Default Cash Account sozlanmagan").format(filial_company)
            )

        # Sklad kitobida — tanlangan mijoz (filial = Sklad uchun Customer)
        cust_account_sklad = self._get_party_account()
        # Filial kitobida — Sklad'ni ifodalovchi ichki SUPPLIER
        # (filial uchun Sklad = yetkazib beruvchi, Kreditorka hisobi).
        sup_sklad = self._get_intercompany_supplier(sklad_company)
        if not sup_sklad:
            frappe.throw(_("'{0}' kompaniyasini ifodalovchi Supplier topilmadi").format(sklad_company))
        filial_clearing = get_party_account("Supplier", sup_sklad, filial_company)

        if self.oborot == "Расход":
            # 1) Sklad pul beradi: Кт Sklad kassa / Дт mijoz (Debtors)
            pe_sklad = self._submit_payment_entry(
                payment_type="Pay", company=sklad_company,
                mode_of_payment=self.source_account, party_type="Customer",
                party=self.kontragent, paid_from=self.payment_account, paid_to=cust_account_sklad,
            )
            # 2) Filial qabul qiladi: Дт Filial kassa / Кт Creditors(Supplier Sklad)
            pe_filial = self._submit_payment_entry(
                payment_type="Receive", company=filial_company,
                mode_of_payment=None, party_type="Supplier",
                party=sup_sklad, paid_from=filial_clearing, paid_to=filial_cash,
            )
        else:  # Приход — filial -> Sklad
            # 1) Sklad qabul qiladi: Дт Sklad kassa / Кт mijoz (Debtors)
            pe_sklad = self._submit_payment_entry(
                payment_type="Receive", company=sklad_company,
                mode_of_payment=self.source_account, party_type="Customer",
                party=self.kontragent, paid_from=cust_account_sklad, paid_to=self.payment_account,
            )
            # 2) Filial pul beradi: Кт Filial kassa / Дт Creditors(Supplier Sklad)
            pe_filial = self._submit_payment_entry(
                payment_type="Pay", company=filial_company,
                mode_of_payment=None, party_type="Supplier",
                party=sup_sklad, paid_from=filial_cash, paid_to=filial_clearing,
            )

        frappe.db.set_value("Kassa", self.name, {
            "payment_entry": pe_sklad,
            "payment_entry_receive": pe_filial,
        })

        frappe.msgprint(
            _("Sklad ↔ filial to'lovi:<br>PE (Sklad): {0}<br>PE (Filial): {1}").format(
                f'<a href="/app/payment-entry/{pe_sklad}">{pe_sklad}</a>',
                f'<a href="/app/payment-entry/{pe_filial}">{pe_filial}</a>',
            ),
            indicator="green"
        )

    def _submit_payment_entry(self, payment_type, company, mode_of_payment,
                              party_type, party, paid_from, paid_to):
        """Payment Entry yaratib submit qiladi, nomini qaytaradi."""
        pe = frappe.new_doc("Payment Entry")
        pe.payment_type = payment_type
        pe.company = company
        pe.posting_date = self.date
        pe.mode_of_payment = mode_of_payment
        pe.party_type = party_type
        pe.party = party
        pe.paid_from = paid_from
        pe.paid_to = paid_to
        pe.paid_from_account_currency = frappe.db.get_value(
            "Account", paid_from, "account_currency"
        )
        pe.paid_to_account_currency = frappe.db.get_value(
            "Account", paid_to, "account_currency"
        )
        pe.paid_amount = self.summa
        pe.received_amount = self.summa
        pe.source_exchange_rate = 1
        pe.target_exchange_rate = 1
        pe.reference_no = self.name
        pe.reference_date = self.date
        pe.insert(ignore_permissions=True)
        pe.submit()
        return pe.name

    def _submit_expense_je(self, company, expense_account, cash_account, expense_debit=True):
        """Xarajat Journal Entry yaratib submit qiladi.

        expense_debit=True  -> Дт xarajat / Кт kassa (Расход)
        expense_debit=False -> Дт kassa / Кт xarajat (Приход, xarajat kamayadi)
        """
        je = frappe.new_doc("Journal Entry")
        je.voucher_type = "Journal Entry"
        je.posting_date = self.date
        je.company = company
        je.user_remark = f"Kassa: {self.name} - {self.oborot} (inter-company)"
        exp_dr, exp_cr = (self.summa, 0) if expense_debit else (0, self.summa)
        je.append("accounts", {
            "account": expense_account,
            "debit_in_account_currency": exp_dr,
            "credit_in_account_currency": exp_cr,
        })
        je.append("accounts", {
            "account": cash_account,
            "debit_in_account_currency": exp_cr,
            "credit_in_account_currency": exp_dr,
        })
        je.insert(ignore_permissions=True)
        je.submit()
        return je.name

    def _add_transfer_entries(self, je):
        """Перемещение - hisobdan hisobga o'tkazma."""
        # Target - Debit
        je.append("accounts", {
            "account": self.payment_account_2,
            "debit_in_account_currency": self.summa,
            "credit_in_account_currency": 0
        })
        # Source - Credit
        je.append("accounts", {
            "account": self.payment_account,
            "debit_in_account_currency": 0,
            "credit_in_account_currency": self.summa
        })
    
    def _add_income_entries(self, je):
        """Приход - pul kelishi."""
        # Cash - Debit
        je.append("accounts", {
            "account": self.payment_account,
            "debit_in_account_currency": self.summa,
            "credit_in_account_currency": 0
        })
        
        # Kontragent - Credit
        if self.party_type in ["Customer", "Supplier", "Employee", "Shareholder"]:
            party_account = self._get_party_account()
            je.append("accounts", {
                "account": party_account,
                "party_type": self.party_type,
                "party": self.kontragent,
                "debit_in_account_currency": 0,
                "credit_in_account_currency": self.summa
            })
        elif self.party_type == "Расходы":
            je.append("accounts", {
                "account": self.expense_kontragent,
                "debit_in_account_currency": 0,
                "credit_in_account_currency": self.summa
            })
        elif self.party_type in DIVIDEND_ACCOUNT_NUMBERS:
            je.append("accounts", {
                "account": self._get_dividend_account(),
                "debit_in_account_currency": 0,
                "credit_in_account_currency": self.summa
            })

    def _add_expense_entries(self, je):
        """Расход - pul chiqishi."""
        # Kontragent - Debit
        if self.party_type == "Расходы":
            je.append("accounts", {
                "account": self.expense_kontragent,
                "debit_in_account_currency": self.summa,
                "credit_in_account_currency": 0
            })
        elif self.party_type in ["Customer", "Supplier", "Employee", "Shareholder"]:
            party_account = self._get_party_account()
            je.append("accounts", {
                "account": party_account,
                "party_type": self.party_type,
                "party": self.kontragent,
                "debit_in_account_currency": self.summa,
                "credit_in_account_currency": 0
            })
        elif self.party_type in DIVIDEND_ACCOUNT_NUMBERS:
            je.append("accounts", {
                "account": self._get_dividend_account(),
                "debit_in_account_currency": self.summa,
                "credit_in_account_currency": 0
            })

        # Cash - Credit
        je.append("accounts", {
            "account": self.payment_account,
            "debit_in_account_currency": 0,
            "credit_in_account_currency": self.summa
        })

    def _get_dividend_account(self):
        """Divident kontragent turi uchun hisobni (raqam bo'yicha, to'lovchi
        company'da) qaytaradi. Har companyda 3200/3201 bir xil raqamli."""
        num = DIVIDEND_ACCOUNT_NUMBERS.get(self.party_type)
        acc = frappe.db.get_value(
            "Account",
            {"company": self.company, "account_number": num, "is_group": 0},
            "name",
        )
        if not acc:
            frappe.throw(
                _("'{0}' uchun '{1}' kompaniyasida {2} raqamli divident hisobi topilmadi").format(
                    self.party_type, self.company, num
                )
            )
        return acc

    def _get_party_account(self):
        """Party uchun account olish."""
        from erpnext.accounts.party import get_party_account
        return get_party_account(self.party_type, self.kontragent, self.company)
    
    def cancel_accounting_documents(self):
        """Yaratilgan hujjatlarni teskari tartibda bekor qilish.

        Inter-company'da: JE -> PE Receive -> PE Pay tartibida.
        """
        targets = [
            ("journal_entry", "Journal Entry"),
            ("payment_entry_supplier", "Payment Entry"),
            ("payment_entry_receive", "Payment Entry"),
            ("payment_entry", "Payment Entry"),
        ]
        for fieldname, doctype in targets:
            name = self.get(fieldname)
            if not name:
                continue
            doc = frappe.get_doc(doctype, name)
            if doc.docstatus == 1:
                doc.cancel()
                frappe.msgprint(
                    _("{0} bekor qilindi: {1}").format(doctype, name),
                    indicator="orange"
                )


# =============================================================================
# WHITELISTED METHODS
# =============================================================================

@frappe.whitelist()
def get_mode_of_payment_info(mode_of_payment: str) -> dict:
    """
    Mode of Payment'dan birinchi account, company va balans olish.
    """
    if not mode_of_payment:
        return {"account": "", "company": "", "balance": 0}
    
    # Birinchi account ni olish
    mopa = frappe.db.get_value(
        "Mode of Payment Account",
        {"parent": mode_of_payment, "default_account": ["is", "set"]},
        ["default_account", "company"],
        as_dict=True
    )
    
    if not mopa:
        return {"account": "", "company": "", "balance": 0}
    
    balance = get_account_balance(mopa.default_account)
    
    return {
        "account": mopa.default_account,
        "company": mopa.company,
        "balance": balance
    }


@frappe.whitelist()
def get_account_balance(account: str) -> float:
    """Account balansini olish."""
    if not account:
        return 0
    
    balance = frappe.db.sql("""
        SELECT SUM(debit) - SUM(credit) as balance
        FROM `tabGL Entry`
        WHERE account = %s AND is_cancelled = 0
    """, account, as_dict=True)
    
    return balance[0].balance if balance and balance[0].balance else 0


@frappe.whitelist()
def get_mode_of_payments_by_company(company: str, exclude_mop: str = None) -> list:
    """
    Berilgan company uchun Mode of Payment ro'yxatini qaytarish.
    
    Args:
        company: Kompaniya nomi
        exclude_mop: Ro'yxatdan chiqarib tashlash kerak bo'lgan Mode of Payment
    
    Returns:
        Mode of Payment nomlari ro'yxati
    """
    if not company:
        return []
    
    # Mode of Payment Account child table orqali company bo'yicha filter
    mop_list = frappe.db.sql("""
        SELECT DISTINCT mopa.parent as name
        FROM `tabMode of Payment Account` mopa
        INNER JOIN `tabMode of Payment` mop ON mop.name = mopa.parent
        WHERE mopa.company = %(company)s
            AND mopa.default_account IS NOT NULL
            AND mop.enabled = 1
    """, {"company": company}, as_dict=True)
    
    result = [m.name for m in mop_list]
    
    # Exclude qilish kerak bo'lsa
    if exclude_mop and exclude_mop in result:
        result.remove(exclude_mop)
    
    return result


@frappe.whitelist()
@frappe.validate_and_sanitize_search_inputs
def get_filtered_mode_of_payments(doctype, txt, searchfield, start, page_len, filters):
    """
    Link field uchun Mode of Payment query.
    target_account field da ishlatiladi.
    
    Filters:
        - company: faqat shu company'ga tegishli MoP lar
        - exclude: bu MoP ni ro'yxatdan chiqarish
    """
    company = filters.get("company", "")
    exclude = filters.get("exclude", "")
    
    if not company:
        # Company yo'q bo'lsa, barcha enabled MoP larni ko'rsat
        return frappe.db.sql("""
            SELECT name
            FROM `tabMode of Payment`
            WHERE enabled = 1
                AND name LIKE %(txt)s
                AND name != %(exclude)s
            ORDER BY name
            LIMIT %(start)s, %(page_len)s
        """, {
            "txt": f"%{txt}%",
            "exclude": exclude or "",
            "start": start,
            "page_len": page_len
        })
    
    # Company bo'yicha filter
    return frappe.db.sql("""
        SELECT DISTINCT mopa.parent as name
        FROM `tabMode of Payment Account` mopa
        INNER JOIN `tabMode of Payment` mop ON mop.name = mopa.parent
        WHERE mopa.company = %(company)s
            AND mopa.default_account IS NOT NULL
            AND mop.enabled = 1
            AND mopa.parent LIKE %(txt)s
            AND mopa.parent != %(exclude)s
        ORDER BY mopa.parent
        LIMIT %(start)s, %(page_len)s
    """, {
        "company": company,
        "txt": f"%{txt}%",
        "exclude": exclude or "",
        "start": start,
        "page_len": page_len
    })


@frappe.whitelist()
@frappe.validate_and_sanitize_search_inputs
def get_filial_expense_accounts(doctype, txt, searchfield, start, page_len, filters):
    """«Xarajat kontragenti» uchun query: tanlangan FILIAL company'sining
    expense_group (52001/52002) ostidagi barcha leaf xarajat hisoblari."""
    filial = filters.get("filial")
    if not filial:
        return []

    fc = frappe.db.get_value(
        "Kassa Filial", filial, ["company", "expense_group"], as_dict=True
    )
    if not fc or not fc.company or not fc.expense_group:
        return []

    grp = frappe.db.get_value(
        "Account", fc.expense_group, ["lft", "rgt"], as_dict=True
    )
    if not grp:
        return []

    return frappe.db.sql("""
        SELECT name
        FROM `tabAccount`
        WHERE company = %(company)s
            AND is_group = 0
            AND root_type = 'Expense'
            AND lft > %(lft)s AND rgt < %(rgt)s
            AND name LIKE %(txt)s
        ORDER BY name
        LIMIT %(start)s, %(page_len)s
    """, {
        "company": fc.company,
        "lft": grp.lft,
        "rgt": grp.rgt,
        "txt": f"%{txt}%",
        "start": start,
        "page_len": page_len,
    })
