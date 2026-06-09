# -*- coding: utf-8 -*-
# Copyright (c) 2026, Jazira App
# License: MIT

"""after_migrate orkestratori.

Frappe after_migrate hooklarni try/except'siz ketma-ket chaqiradi — bittasi
xato bersa, keyingilari o'tkazib yuboriladi. Shuning uchun barcha sozlamalarni
shu yerda har birini ALOHIDA try/except bilan chaqiramiz: bittasi yiqilsa ham
qolganlari ishlaydi, xato esa Error Log'ga yoziladi.
"""

import frappe


def run():
	from jazira_app.jazira_app.setup.print_format_setup import (
		create_sales_order_print_format,
		create_purchase_order_print_format,
	)
	from jazira_app.jazira_app.overrides.purchase_order import ensure_custom_fields
	from jazira_app.jazira_app.setup.dividend_setup import create_dividend_party_types
	from jazira_app.jazira_app.setup.intercompany_setup import ensure_intercompany_customers

	tasks = [
		create_sales_order_print_format,
		create_purchase_order_print_format,
		ensure_custom_fields,
		create_dividend_party_types,
		ensure_intercompany_customers,
	]
	for fn in tasks:
		try:
			fn()
		except Exception:
			frappe.log_error(frappe.get_traceback(), f"after_migrate: {fn.__name__}")
