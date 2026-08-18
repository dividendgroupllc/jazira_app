# Copyright (c) 2026, Jazira App and contributors
# License: MIT

"""Balance Calculation — PDF eksport (umumiy report/pl_pdf.py dvigateli)."""

import frappe

from jazira_app.jazira_app.report import pl_pdf
from jazira_app.jazira_app.report.balance_calculation.balance_calculation import execute


def build_html(filters):
	filters = frappe._dict(filters or {})
	columns, data = execute(filters)
	return pl_pdf.build_html(
		"Jazira Group · Баланс (филиаллар)",
		"Ҳар компания баланси",
		filters, columns, data,
		pl_pdf.meta_from_filters(filters),
	)


@frappe.whitelist()
def generate_balance_calculation_pdf(filters):
	pl_pdf.send(filters, execute, "Jazira Group · Баланс (филиаллар)",
				"Ҳар компания баланси", "Balance_Filiallar",
				report_name="Balance Calculation")
