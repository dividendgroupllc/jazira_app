# -*- coding: utf-8 -*-
# Copyright (c) 2026, Jazira App
# License: MIT

"""Jazira Expense Allocation uchun hisoblar rejasini tayyorlash.

Bosh kompaniya (Sklad) ma'muriy xarajatining bir qismi filiallarga qayta
yoziladi. O'sha ulush filialning O'Z ma'muriy xarajatlari bilan aralashib
ketmasligi uchun har bir kompaniyada alohida hisob ochiladi:

    52002 - Адм
      └── Ма'мурий харажат улуши      <-- shu

Ishga tushirish:
    bench --site <SITE> execute jazira_app.jazira_app.setup.expense_allocation_setup.run
"""

import frappe

ADMIN_GROUP_NUMBER = "52002"
ALLOCATION_ACCOUNT_NAME = "Ма'мурий харажат улуши"


def get_admin_group(company):
	return frappe.db.get_value(
		"Account",
		{
			"company": company,
			"account_number": ADMIN_GROUP_NUMBER,
			"root_type": "Expense",
			"is_group": 1,
		},
		"name",
	)


def ensure_allocation_account(company):
	"""Kompaniyada "Ма'мурий харажат улуши" hisobini yaratadi (bo'lmasa)."""
	group = get_admin_group(company)
	if not group:
		print(f"⏭️  {company}: '{ADMIN_GROUP_NUMBER} - Адм' guruhi topilmadi, o'tkazib yuborildi")
		return None

	existing = frappe.db.get_value(
		"Account",
		{"company": company, "parent_account": group, "account_name": ALLOCATION_ACCOUNT_NAME},
		"name",
	)
	if existing:
		# Аллақачон бор — жим қайтамиз (ҳар migrate'да такрорланмасин).
		return existing

	account = frappe.get_doc(
		{
			"doctype": "Account",
			"account_name": ALLOCATION_ACCOUNT_NAME,
			"parent_account": group,
			"company": company,
			"root_type": "Expense",
			"report_type": "Profit and Loss",
			"is_group": 0,
			"account_currency": frappe.db.get_value("Company", company, "default_currency"),
		}
	)
	account.flags.ignore_permissions = True
	account.insert()
	print(f"✅ {company}: yaratildi — {account.name}")
	return account.name


def ensure_payment_entry_link_field():
	"""Payment Entry'ga "Jazira Expense Allocation" havolasini qo'shadi.

	Journal Entry'da bunday maydon allaqachon bor (custom_jazira_expense_allocation)
	— shu tufayli yaratilgan yozuvlar hujjatning "Connections" bo'limida
	ko'rinadi. To'lovlar ham xuddi shunday ko'rinishi uchun Payment Entry'ga
	ham o'sha maydon kerak.
	"""
	from frappe.custom.doctype.custom_field.custom_field import create_custom_fields

	existed = frappe.db.exists(
		"Custom Field",
		{"dt": "Payment Entry", "fieldname": "custom_jazira_expense_allocation"})

	create_custom_fields({
		"Payment Entry": [{
			"fieldname": "custom_jazira_expense_allocation",
			"label": "Jazira Expense Allocation",
			"fieldtype": "Link",
			"options": "Jazira Expense Allocation",
			"insert_after": "remarks",
			"read_only": 1,
			"no_copy": 1,
			"print_hide": 1,
			"in_standard_filter": 1,
			"description": "Jazira Expense Allocation orqali yaratilgan to'lovni belgilaydi",
		}]
	})
	if not existed:
		print("✅ Payment Entry.custom_jazira_expense_allocation maydoni yaratildi")


def get_root_company():
	"""Guruh daraxtining ildizi (parent_company yo'q kompaniya)."""
	roots = frappe.get_all("Company", filters={"parent_company": ["is", "not set"]}, pluck="name")
	return roots[0] if roots else None


def run():
	"""Hisobni tayyorlaydi.

	Kompaniyalar daraxt ko'rinishida bo'lsa (Jazira -> filiallar), ERPNext
	hisobni faqat ILDIZ kompaniyada ochishga ruxsat beradi va uni o'zi
	farzand kompaniyalarga tarqatadi. Shuning uchun avval ildizda ochamiz,
	keyin tarqalmaganlarini alohida to'ldiramiz.
	"""
	ensure_payment_entry_link_field()

	root = get_root_company()
	if root:
		ensure_allocation_account(root)

	companies = frappe.get_all("Company", filters={"is_group": 0}, pluck="name", order_by="name")
	created = 0
	for company in companies:
		before = frappe.db.exists(
			"Account",
			{"company": company, "account_name": ALLOCATION_ACCOUNT_NAME},
		)
		ensure_allocation_account(company)
		if not before:
			created += 1

	frappe.db.commit()
	# Хулоса фақат ҳақиқатан янги ҳисоб очилганда ёзилади.
	if created:
		print(f"Тайёр — {created} та компанияда ҳисоб очилди "
			  f"({len(companies)} та кўриб чиқилди).")
