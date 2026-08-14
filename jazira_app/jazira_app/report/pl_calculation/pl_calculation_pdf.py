# Copyright (c) 2026, Jazira App and contributors
# For license information, please see license.txt

"""PL Calculation — PDF eksport.

Dizayn va sahifa o'lchami umumiy `report/pl_pdf.py` modulida.
"""

import frappe

from jazira_app.jazira_app.report import pl_pdf
from jazira_app.jazira_app.report.pl_calculation.pl_calculation import execute


def build_html(filters):
	filters = frappe._dict(filters or {})
	columns, data = execute(filters)
	return pl_pdf.build_html(
		"Jazira Group · PL Calculation",
		"Отчёт для расчёта общий",
		filters, columns, data,
		pl_pdf.meta_from_filters(filters, ["section"]),
	)


@frappe.whitelist()
def generate_pl_calculation_pdf(filters):
	pl_pdf.send(filters, execute, "Jazira Group · PL Calculation",
				"Отчёт для расчёта общий", "PL_Calculation", ["section"])
