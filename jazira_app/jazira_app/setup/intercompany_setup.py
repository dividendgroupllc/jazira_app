# -*- coding: utf-8 -*-
# Copyright (c) 2026, Jazira App
# License: MIT

"""Inter-company kontragentlar sozlamasi.

Filiallararo Kassa oqimi har bir companyni ifodalovchi (represents_company)
Customer'ni talab qiladi. Ba'zi companylarda (masalan Jazira Sklad) faqat
Supplier bor — shuning uchun yetishmaganlar uchun Customer yaratamiz.
"""

import frappe


def ensure_intercompany_customers():
	"""Har bir company uchun represents_company Customer mavjudligini ta'minlaydi."""
	customer_group = (
		frappe.db.get_value("Customer Group", {"is_group": 0}, "name")
		or "All Customer Groups"
	)
	territory = (
		frappe.db.get_value("Territory", {"is_group": 0}, "name")
		or "All Territories"
	)

	for company in frappe.get_all("Company", pluck="name"):
		if frappe.db.exists("Customer", {"represents_company": company}):
			continue
		name = company
		# Agar shu nomli Customer boshqa company'ni ifodalasa, nomni farqlaymiz
		if frappe.db.exists("Customer", name):
			name = f"{company} (IC)"
		cust = frappe.new_doc("Customer")
		cust.customer_name = name
		cust.is_internal_customer = 1  # represents_company faqat shu bilan saqlanadi
		cust.represents_company = company
		cust.customer_group = customer_group
		cust.territory = territory
		cust.customer_type = "Company"
		cust.flags.ignore_mandatory = True
		cust.insert(ignore_permissions=True)
		print(f"✅ Inter-company Customer yaratildi: {name} -> {company}")
