# -*- coding: utf-8 -*-
# Copyright (c) 2026, Jazira App
# License: MIT

"""Production'ni bir buyruq bilan to'liq sozlash.

    bench --site <site> execute jazira_app.jazira_app.setup.production_setup.run_all

Qiladigan ishlar (hammasi idempotent):
  1. Inter-company Customer'lar (har company uchun)
  2. Divident Party Type'lar (Akmal/Elyor)
  3. Divident hisob nomlari (3200/3201 -> Divident Akmal/Elyor)
  4. Kassa Filial'larni sozlash (company + kassa hisobi + xarajat guruhi)
  5. Eski Kassa Kontragent / «Прочее лицо» ni o'chirish
"""

import frappe

# Filial -> (Company, Kassa MoP, xarajat guruhi raqami)
FILIAL_CONFIG = {
	"Saripul":    ("Jazira Saripul",    "Нахт Сарипул",   "52001"),
	"Smart":      ("Jazira Smart",      "Нахт Смарт",     "52001"),
	"Xalq banki": ("Jazira Xalq Banki", "Нахт Халк Банк", "52001"),
	"Baza":       ("Jazira Sklad",      "Нахт Склад",     "52001"),
	"Admin":      ("Jazira Sklad",      "Нахт Склад",     "52002"),
}


def configure_kassa_filials():
	"""Har bir Kassa Filial'ga company + kassa hisobi + xarajat guruhini o'rnatadi."""
	for fname, (company, mop, grp_num) in FILIAL_CONFIG.items():
		if not frappe.db.exists("Kassa Filial", fname):
			print(f"⏭️  Filial topilmadi: {fname}")
			continue
		eg = frappe.db.get_value(
			"Account",
			{"account_number": grp_num, "company": company, "is_group": 1},
			"name",
		)
		d = frappe.get_doc("Kassa Filial", fname)
		d.company = company
		if frappe.db.exists("Mode of Payment", mop):
			d.mode_of_payment = mop
		else:
			print(f"⚠️  Mode of Payment topilmadi ({fname}): {mop}")
		d.expense_group = eg
		if not eg:
			print(f"⚠️  Xarajat guruhi topilmadi ({fname}): {grp_num} / {company}")
		d.save(ignore_permissions=True)
		print(f"✅ {fname}: {company} | {mop} | guruh={eg}")
	frappe.db.commit()


def remove_legacy_kassa():
	"""Eski «Kassa Kontragent» DocType va «Прочее лицо» Party Type'ni o'chiradi."""
	if frappe.db.exists("DocType", "Kassa Kontragent"):
		frappe.delete_doc("DocType", "Kassa Kontragent", force=1, ignore_permissions=True)
		frappe.db.commit()
		frappe.db.sql_ddl("DROP TABLE IF EXISTS `tabKassa Kontragent`")
		frappe.db.commit()
		print("✅ Kassa Kontragent o'chirildi")
	else:
		print("⏭️  Kassa Kontragent allaqachon yo'q")

	if frappe.db.exists("Party Type", "Прочее лицо"):
		used = frappe.db.count("GL Entry", {"party_type": "Прочее лицо"})
		if used:
			print(f"⚠️  'Прочее лицо' {used} ta GL Entry'da ishlatilgan — o'chirilmadi")
		else:
			frappe.delete_doc("Party Type", "Прочее лицо", force=1, ignore_permissions=True)
			frappe.db.commit()
			print("✅ Party Type 'Прочее лицо' o'chirildi")
	else:
		print("⏭️  'Прочее лицо' allaqachon yo'q")


def run_all():
	from jazira_app.jazira_app.setup.dividend_setup import (
		create_dividend_party_types,
		rename_dividend_accounts,
	)
	from jazira_app.jazira_app.setup.intercompany_setup import (
		ensure_intercompany_customers,
		ensure_customer_filial_field,
	)

	print("=== 1. Inter-company Customer'lar ===")
	ensure_intercompany_customers()
	ensure_customer_filial_field()
	print("\n=== 2. Divident Party Type'lar ===")
	create_dividend_party_types()
	print("\n=== 3. Divident hisob nomlari ===")
	rename_dividend_accounts()
	print("\n=== 4. Kassa Filial'larni sozlash ===")
	configure_kassa_filials()
	print("\n=== 5. Eski Kassa Kontragent / Прочее лицо ===")
	remove_legacy_kassa()
	print("\n✅ PRODUCTION SETUP TAYYOR")
