# Copyright (c) 2026, Jazira App and contributors
# For license information, please see license.txt

"""PL Obshi — PDF eksport.

Dizayn va sahifa o'lchami umumiy `report/pl_pdf.py` modulida — uchala PL
hisoboti bir xil ko'rinishda chiqishi uchun.
"""

import frappe

from jazira_app.jazira_app.report import pl_pdf
from jazira_app.jazira_app.report.pl_obshi.pl_obshi import execute


def build_html(filters):
	filters = frappe._dict(filters or {})
	columns, data = execute(filters)
	return pl_pdf.build_html(
		"Jazira Group · Консолидация",
		"Умумий фойда — зарар ҳисоботи",
		filters, columns, data,
		pl_pdf.meta_from_filters(filters),
	)


@frappe.whitelist()
def generate_pl_obshi_pdf(filters):
	pl_pdf.send(filters, execute, "Jazira Group · Консолидация",
				"Умумий фойда — зарар ҳисоботи", "PL_Obshi")
