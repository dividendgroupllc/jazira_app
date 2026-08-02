# Copyright (c) 2026, Jazira App and contributors
# For license information, please see license.txt

"""
PL Hisoboti — PDF eksport.

Matn/qator tuzilishi butunlay Jazira'ning o'z pl_hisoboti report'idan
(build_rows) olinadi, hech narsa qattiq kodlanmagan, shuning uchun qancha
davr ustuni yoki qancha hisob qatori bo'lishidan qat'iy nazar ishlaydi.
"""

import frappe
from frappe.utils import flt
from weasyprint import HTML

from jazira_app.jazira_app.report.pl_hisoboti.pl_hisoboti import execute

C_HEADER_BG = "#0f2942"
C_SECTION_BG = "#c0392b"
C_PROFIT_BG = "#a3120f"
C_SUBTOTAL_BG = "#fdebd3"
C_DETAIL_BG = "#ffffff"


def _fmt_number(v):
	v = round(flt(v))
	txt = f"{abs(v):,.0f}".replace(",", " ")
	return f"({txt})" if v < 0 else txt


def _fmt_percent(v):
	return f"{round(flt(v))}%"


def _fmt_ratio(v):
	txt = f"{flt(v):,.2f}".replace(",", " ").replace(".", ",")
	return txt


def _row_html(row, fkeys):
	rt = row.get("row_type")

	if rt == "divider":
		cells = "".join('<td class="divider"></td>' for _ in range(len(fkeys) + 1))
		return f'<tr class="divider-row">{cells}</tr>'

	level = row.get("indent_level", 0)
	label = frappe.utils.escape_html(row.get("label") or "")
	label_style = f"padding-left:{6 + level * 16}px;"

	row_class = f"row-{rt}" if rt else "row-plain"

	cells = [f'<td class="label {row_class}" style="{label_style}">{label}</td>']
	for fk in fkeys:
		v = row.get(fk)
		if v is None or v == "":
			cells.append(f'<td class="value {row_class}"></td>')
			continue
		if rt == "percent":
			txt = _fmt_percent(v)
		elif rt == "ratio":
			txt = _fmt_ratio(v)
		elif row.get("is_qty"):
			txt = f"{round(flt(v)):,.0f}".replace(",", " ")
		else:
			txt = _fmt_number(v)
		cells.append(f'<td class="value {row_class}">{txt}</td>')

	return f'<tr>{"".join(cells)}</tr>'


def build_html(filters):
	filters = frappe._dict(filters or {})
	company = filters.get("company")
	if not company:
		return "<html><body><p>Компания танланмаган.</p></body></html>"

	columns, data, summary_html = execute(filters)
	if not columns:
		return "<html><body><p>Ma'lumot topilmadi.</p></body></html>"

	period_cols = columns[1:]
	fkeys = [c["fieldname"] for c in period_cols]
	period_labels = [c["label"] for c in period_cols]

	from_date = filters.get("from_date", "")
	to_date = filters.get("to_date", "")
	periodicity = filters.get("periodicity", "Yearly")

	n_cols = len(fkeys)
	page_size = "A3 landscape" if n_cols <= 8 else "1400pt 850pt landscape"
	base_font = 9 if n_cols <= 6 else (8 if n_cols <= 10 else 7)

	header_cells = "".join(f'<th class="value">{frappe.utils.escape_html(label_)}</th>' for label_ in period_labels)
	body_rows = "".join(_row_html(r, fkeys) for r in data)

	html = f"""
	<html>
	<head>
	<meta charset="utf-8">
	<style>
		@page {{ size: {page_size}; margin: 24px 28px; }}
		* {{ box-sizing: border-box; }}
		body {{ font-family: 'DejaVu Sans', Arial, sans-serif; font-size: {base_font}px; color: #111; }}

		.header {{
			background: {C_HEADER_BG};
			color: #fff;
			padding: 14px 18px;
			border-radius: 6px;
			margin-bottom: 12px;
			display: flex;
			justify-content: space-between;
			align-items: center;
		}}
		.header .title {{ font-size: 10px; letter-spacing: 2px; text-transform: uppercase; opacity: .65; }}
		.header .company {{ font-size: 15px; font-weight: 700; margin-top: 2px; }}
		.header .period {{ text-align: right; font-size: 10px; opacity: .8; }}

		table {{ width: 100%; border-collapse: collapse; }}
		th, td {{ padding: 4px 8px; }}
		thead th {{
			background: #eef1f4;
			font-weight: 700;
			text-align: right;
			border-bottom: 2px solid #cfd6dd;
		}}
		thead th.label {{ text-align: left; }}

		td.label {{ text-align: left; white-space: nowrap; }}
		td.value {{ text-align: right; white-space: nowrap; }}

		.divider-row td {{ padding: 2px 0; border: none; }}

		.row-root {{
			background: {C_SECTION_BG};
			color: #fff;
			font-weight: 700;
			text-transform: uppercase;
		}}
		.row-result {{
			background: {C_PROFIT_BG};
			color: #fff;
			font-weight: 800;
		}}
		.row-sub {{
			background: {C_SUBTOTAL_BG};
			color: #111;
			font-weight: 700;
		}}
		.row-detail {{
			background: {C_DETAIL_BG};
			color: #333;
			font-size: {base_font - 1}px;
		}}
		.row-percent, .row-ratio {{
			background: #fff;
			color: #666;
			font-style: italic;
			font-size: {base_font - 1}px;
		}}
	</style>
	</head>
	<body>
		<div class="header">
			<div>
				<div class="title">Фойда — зарар ҳисоботи</div>
				<div class="company">{frappe.utils.escape_html(company)} · P&amp;L Report</div>
			</div>
			<div class="period">
				<div>{from_date} — {to_date}</div>
				<div>{periodicity}</div>
			</div>
		</div>
		<table>
			<thead>
				<tr><th class="label">Кўрсаткич</th>{header_cells}</tr>
			</thead>
			<tbody>
				{body_rows}
			</tbody>
		</table>
	</body>
	</html>
	"""
	return html


@frappe.whitelist()
def generate_pl_pdf(filters):
	"""PDF serverga saqlanmaydi — javob to'g'ridan-to'g'ri brauzerga
	"download" sifatida yuboriladi. Diskda hech qanday File yozuvi qoldirilmaydi."""
	import json
	if isinstance(filters, str):
		filters = json.loads(filters)

	html = build_html(filters)
	pdf_bytes = HTML(string=html).write_pdf()

	company = (filters.get("company") or "company").replace(" ", "_")
	from_date = (filters.get("from_date") or "")[:7]
	to_date = (filters.get("to_date") or "")[:7]
	filename = f"PL_{company}_{from_date}_to_{to_date}.pdf"

	frappe.local.response.filename = filename
	frappe.local.response.filecontent = pdf_bytes
	frappe.local.response.type = "download"
