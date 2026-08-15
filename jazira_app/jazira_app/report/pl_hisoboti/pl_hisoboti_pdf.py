# Copyright (c) 2026, Jazira App and contributors
# For license information, please see license.txt

"""PL Hisoboti — PDF eksport.

Dizayn va sahifa o'lchami umumiy `report/pl_pdf.py` modulida.
"""

import frappe

from jazira_app.jazira_app.report import pl_pdf
from jazira_app.jazira_app.report.pl_hisoboti.pl_hisoboti import execute


def _title(filters):
	return "%s · P&L Report" % (filters.get("company") or "")


def build_html(filters):
	filters = frappe._dict(filters or {})
	if not filters.get("company"):
		return "<html><body><p>Компания танланмаган.</p></body></html>"
	columns, data = execute(filters)
	return pl_pdf.build_html(
		_title(filters), "Фойда — зарар ҳисоботи",
		filters, columns, data,
		pl_pdf.meta_from_filters(filters),
	)


@frappe.whitelist()
def generate_pl_pdf(filters):
	import json
	pl_pdf.check_report_permission("PL Hisoboti")
	if isinstance(filters, str):
		filters = json.loads(filters)
	if not (filters or {}).get("company"):
		frappe.throw("Аввал компанияни танланг")
	pl_pdf.send(filters, execute, _title(filters), "Фойда — зарар ҳисоботи",
				"PL_" + str(filters.get("company") or "").replace(" ", "_"),
				report_name="PL Hisoboti")
