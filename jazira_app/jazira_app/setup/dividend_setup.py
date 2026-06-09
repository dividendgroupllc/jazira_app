# -*- coding: utf-8 -*-
# Copyright (c) 2026, Jazira App
# License: MIT

"""Divident kontragent turlari sozlamasi.

- create_dividend_party_types(): «Divident Akmal» / «Divident Elyor» Party Type
  larini yaratadi (Kassa «Kontragent turi» ro'yxatida chiqishi uchun).
- rename_dividend_accounts(): 3200 -> «Divident Akmal», 3201 -> «Divident Elyor»
  hisob nomlarini o'zgartiradi (har companyda, idempotent). Hisob RAQAMI
  o'zgarmaydi — kod baribir raqam bo'yicha ishlaydi.
"""

import frappe

DIVIDEND_PARTY_TYPES = ["Divident Akmal", "Divident Elyor"]
DIVIDEND_ACCOUNT_RENAME = {
	"3200": "Divident Akmal",
	"3201": "Divident Elyor",
}


def create_dividend_party_types():
	"""Divident Party Type'larni yaratadi (idempotent)."""
	for pt in DIVIDEND_PARTY_TYPES:
		if not frappe.db.exists("Party Type", pt):
			doc = frappe.new_doc("Party Type")
			doc.party_type = pt
			doc.account_type = "Payable"
			doc.flags.ignore_links = True
			doc.insert(ignore_permissions=True)
			print(f"✅ Party Type yaratildi: {pt}")
		else:
			print(f"⏭️  Party Type allaqachon bor: {pt}")


def rename_dividend_accounts():
	"""3200/3201 hisoblarini «Divident Akmal/Elyor» deb nomlaydi (idempotent).

	Hisob mavjud bo'lgan har bir companyda ishlaydi. RAQAM o'zgarmaydi.
	"""
	for number, new_name in DIVIDEND_ACCOUNT_RENAME.items():
		rows = frappe.get_all(
			"Account",
			filters={"account_number": number, "is_group": 0},
			fields=["name", "account_name", "company"],
		)
		for acc in rows:
			if acc.account_name == new_name:
				continue
			abbr = frappe.db.get_value("Company", acc.company, "abbr")
			new_id = f"{number} - {new_name} - {abbr}"
			frappe.db.set_value("Account", acc.name, "account_name", new_name)
			if acc.name != new_id and not frappe.db.exists("Account", new_id):
				frappe.rename_doc("Account", acc.name, new_id, force=True)
			print(f"✅ Hisob nomlandi: {acc.name} -> {new_name}")


def setup_dividends():
	"""To'liq divident sozlamasi (after_migrate uchun — faqat Party Type)."""
	create_dividend_party_types()
