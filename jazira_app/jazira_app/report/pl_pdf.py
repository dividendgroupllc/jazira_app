# Copyright (c) 2026, Jazira App and contributors
# For license information, please see license.txt

"""
PL hisobotlari uchun UMUMIY PDF chiqaruvchi.

PL Hisoboti, PL Obshi va PL Calculation — uchalasi ham shu moduldan
foydalanadi, shuning uchun dizayn bir joyda turadi va bir marta
yaxshilansa uchalasiga ham tegadi.

Ҳал қилинган асосий муаммолар
─────────────────────────────
1) ТОР ЖАДВАЛ, УЗОҚ БЎШЛИҚ. Аввал саҳифа ўлчами доим A3 landscape эди.
   Битта ой танланганда жадвалда атиги 2 та устун бўларди — номлар чапда,
   рақам эса саҳифанинг ўнг четида, ораси бўм-бўш: ўқиш қийин.
   Энди саҳифа ўлчами устунлар сонига қараб танланади ва устун
   кенгликлари аниқ белгиланади — рақам ҳамиша матннинг ёнида туради.

2) ҲАММАСИ ЁЙИЛГАН ҲОЛДА. PDF'га ҳисоботнинг БАРЧА қатори тушади —
   экранда йиғилган (collapsed) бўлса ҳам. Иерархия чап томондаги
   даража чизиқлари ва сурилиш билан кўрсатилади.

3) САРЛАВҲА ҲАР САҲИФАДА. Кўп саҳифали ҳисоботда устун номлари ҳар
   саҳифа тепасида такрорланади (thead: table-header-group).
"""

import json

import frappe
from frappe import _
from frappe.utils import flt
from weasyprint import HTML

# ── Ranglar (Jazira firma uslubi) ────────────────────────────────────────────
C_HEADER_BG = "#0f2942"
C_SECTION_BG = "#c0392b"
C_RESULT_BG = "#a3120f"
C_SUB_BG = "#fdebd3"
C_NEG = "#c0392b"

# ── O'lchamlar (punktda) ─────────────────────────────────────────────────────
MARGIN = 26
MIN_LABEL_W = 260      # номлар устуни бундан тор бўлмасин
MAX_LABEL_W = 340      # ва бундан кенг ҳам бўлмасин — акс ҳолда рақам узоқлашади
MIN_VALUE_W = 100      # қулай ўқиладиган рақам устуни
MAX_VALUE_W = 145

# Ҳамиша landscape (ётиқ) — молиявий жадвалда устун кўп, тик саҳифа тор.
PAGE_SIZES = [
	# (nom, kenglik, bo'yi) — kichikdan kattaga
	("A4 landscape", 842, 595),
	("A3 landscape", 1191, 842),
]

# PDF стандарти саҳифа ўлчамини 14400pt (200 дюйм) билан чегаралайди.
MAX_PAGE_W = 14000


def _pick_page(n_cols):
	"""Устунлар сонига мос энг КИЧИК саҳифани танлайди.

	Битта ой учун A3 landscape бериш — жадвални саҳифа бўйлаб чўзиб,
	номлар билан рақам орасини бўм-бўш қолдиради. Шунинг учун ҳар доим
	мазмунга етадиган энг кичик саҳифа олинади."""
	needed = MIN_LABEL_W + n_cols * MIN_VALUE_W + 2 * MARGIN
	for name, w, h in PAGE_SIZES:
		if needed <= w:
			return name, w, h
	# Жуда кўп устун (масалан 12 ой) — саҳифа кенглиги ўзи ҳисобланади.
	#
	# ДИҚҚАТ: CSS'да аниq ўлчам билан `landscape` сўзини БИРГА ёзиб бўлмайди
	# ("1608pt 842pt landscape" — нотўғри қоида, браузер уни ташлаб юборади
	# ва A4 тикка қайтади; шунда жадвалнинг ўнг томони саҳифадан чиқиб
	# кетиб, охирги ойлар умуман кўринмай қоларди). Фақат "кенглик бўй"
	# ёзилади — кенглик бўйдан катта бўлса, саҳифа аллақачон ётиқ.
	width = min(MAX_PAGE_W, MIN_LABEL_W + n_cols * (MIN_VALUE_W + 8) + 2 * MARGIN)
	return f"{width}pt 842pt", width, 842


def _layout(n_cols):
	"""Саҳифа ўлчами, устун кенгликлари ва шрифт ўлчамини қайтаради."""
	page_size, page_w, _ = _pick_page(n_cols)
	content_w = page_w - 2 * MARGIN

	value_w = (content_w - MIN_LABEL_W) / n_cols if n_cols else content_w
	value_w = max(MIN_VALUE_W, min(MAX_VALUE_W, value_w))

	# Номлар устунига шифт қўйилади: акс ҳолда битта ой танланганда
	# жадвал саҳифа бўйлаб чўзилиб, ном билан рақам ораси бўм-бўш қоларди.
	label_w = min(MAX_LABEL_W, content_w - n_cols * value_w)
	if label_w < MIN_LABEL_W:
		label_w = MIN_LABEL_W
		value_w = (content_w - label_w) / n_cols if n_cols else content_w

	base_font = 9.5 if n_cols <= 4 else (8.5 if n_cols <= 8 else 7.5)
	return {
		"page_size": page_size,
		"label_w": round(label_w, 1),
		"value_w": round(value_w, 1),
		# Жадвал саҳифадан тор бўлса — чўзилмайди, чапга ёпишиб туради.
		"table_w": round(label_w + n_cols * value_w, 1),
		"font": base_font,
	}


# ── Raqam formati ────────────────────────────────────────────────────────────

def _num(v):
	n = round(flt(v))
	txt = f"{abs(n):,.0f}".replace(",", " ")
	return f"({txt})" if n < 0 else txt


def _cell_text(row, value):
	rt = row.get("row_type")
	if rt == "percent" or row.get("is_percent"):
		return f"{round(flt(value))}%"
	if rt == "ratio" or row.get("is_ratio"):
		return f"{flt(value):,.2f}".replace(",", " ").replace(".", ",")
	if row.get("is_qty"):
		return f"{round(flt(value)):,.0f}".replace(",", " ")
	return _num(value)


# ── Qator HTML ───────────────────────────────────────────────────────────────

def _row_html(row, fkeys):
	rt = row.get("row_type") or "plain"

	if rt == "divider":
		return f'<tr class="r-divider"><td colspan="{len(fkeys) + 1}"></td></tr>'

	level = int(row.get("indent_level") or row.get("indent") or 0)
	label = frappe.utils.escape_html(row.get("label") or "")

	# Иерархия: ҳар даража учун сурилиш + нозик вертикал чизиқ, шунда
	# қайси қатор қайси қаторнинг ичида экани PDF'да ҳам кўриниб туради.
	guides = "".join('<span class="g"></span>' for _ in range(level))
	cells = [f'<td class="lbl lv{min(level, 3)}">{guides}<span class="t">{label}</span></td>']

	for fk in fkeys:
		v = row.get(fk)
		if v is None or v == "":
			cells.append('<td class="val"></td>')
			continue
		txt = _cell_text(row, v)
		neg = "neg" if txt.startswith("(") else ""
		cells.append(f'<td class="val {neg}">{txt}</td>')

	return f'<tr class="r-{rt}">{"".join(cells)}</tr>'


# ── Sahifa qurish ────────────────────────────────────────────────────────────

def build_html(title, subtitle, filters, columns, data, meta_lines=None):
	if not columns:
		return "<html><body><p>Ma'lumot topilmadi.</p></body></html>"

	period_cols = columns[1:]
	fkeys = [c["fieldname"] for c in period_cols]
	L = _layout(len(fkeys)) if fkeys else _layout(1)

	head_cells = "".join(
		f'<th class="val">{frappe.utils.escape_html(str(c["label"]))}</th>' for c in period_cols)
	body_rows = "".join(_row_html(r, fkeys) for r in data)
	cols_html = (f'<col style="width:{L["label_w"]}pt">'
				 + f'<col style="width:{L["value_w"]}pt">' * len(fkeys))

	meta = "".join(f"<div>{frappe.utils.escape_html(m)}</div>" for m in (meta_lines or []))
	f = L["font"]

	return f"""<!DOCTYPE html>
<html><head><meta charset="utf-8">
<style>
  @page {{
    size: {L["page_size"]}; margin: {MARGIN}pt;
    @bottom-right {{ content: counter(page) " / " counter(pages);
      font-family: 'DejaVu Sans'; font-size: 7pt; color: #94a3b8; }}
  }}
  * {{ box-sizing: border-box; }}
  body {{ font-family: 'DejaVu Sans', Arial, sans-serif; font-size: {f}pt; color: #111; }}

  .hdr {{ background: {C_HEADER_BG}; color: #fff; padding: 11pt 14pt; border-radius: 5pt;
          margin-bottom: 10pt; display: flex; justify-content: space-between;
          align-items: center; }}
  .hdr .kick {{ font-size: {f - 2}pt; letter-spacing: 1.6pt; text-transform: uppercase;
                opacity: .55; }}
  .hdr .ttl {{ font-size: {f + 5}pt; font-weight: 700; margin-top: 2pt; }}
  .hdr .rgt {{ text-align: right; font-size: {f - 1}pt; opacity: .8; line-height: 1.7; }}

  table {{ width: {L["table_w"]}pt; border-collapse: collapse; table-layout: fixed; }}
  thead {{ display: table-header-group; }}
  thead th {{ background: #eef1f4; color: #0f2942; font-weight: 700; text-align: right;
              padding: 5pt 7pt; border-bottom: 1.5pt solid #cfd6dd; font-size: {f - .5}pt; }}
  thead th.lbl {{ text-align: left; }}

  td {{ padding: 3.4pt 7pt; }}
  td.lbl {{ text-align: left; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }}
  td.val {{ text-align: right; white-space: nowrap; font-variant-numeric: tabular-nums; }}
  td.neg {{ color: {C_NEG}; }}

  /* Иерархия чизиқлари — қайси қатор қайсининг ичида эканини кўрсатади */
  td.lbl .g {{ display: inline-block; width: 11pt; height: {f}pt; vertical-align: middle;
               border-left: .6pt solid #cbd5e1; margin-right: 3pt; }}
  td.lbl .t {{ vertical-align: middle; }}

  tr.r-root td {{ background: {C_SECTION_BG}; color: #fff; font-weight: 700;
                  text-transform: uppercase; letter-spacing: .2pt; }}
  tr.r-root td.neg {{ color: #ffd9d4; }}
  tr.r-root td.lbl .g {{ border-left-color: rgba(255,255,255,.35); }}

  tr.r-result td {{ background: {C_RESULT_BG}; color: #fff; font-weight: 800; }}
  tr.r-result td.neg {{ color: #ffd9d4; }}
  tr.r-result td.lbl .g {{ border-left-color: rgba(255,255,255,.35); }}

  tr.r-sub td {{ background: {C_SUB_BG}; color: #111; font-weight: 700; }}

  tr.r-detail td {{ background: #fff; color: #333; font-size: {f - .8}pt;
                    border-bottom: .4pt solid #f1f5f9; }}
  tr.r-detail:nth-child(even) td {{ background: #fafbfc; }}

  tr.r-percent td, tr.r-ratio td {{ background: #fff; color: #64748b; font-style: italic;
                                    font-size: {f - 1}pt; border-bottom: .4pt solid #f1f5f9; }}

  tr.r-divider td {{ padding: 3pt 0; border: none; background: #fff; }}
</style></head>
<body>
  <div class="hdr">
    <div>
      <div class="kick">{frappe.utils.escape_html(subtitle)}</div>
      <div class="ttl">{frappe.utils.escape_html(title)}</div>
    </div>
    <div class="rgt">{meta}</div>
  </div>
  <table>
    <colgroup>{cols_html}</colgroup>
    <thead><tr><th class="lbl">Кўрсаткич</th>{head_cells}</tr></thead>
    <tbody>{body_rows}</tbody>
  </table>
</body></html>"""


def meta_from_filters(filters, extra_keys=None):
	"""Саҳифа тепасидаги ўнг блок — қайси фильтр билан олингани."""
	lines = []
	fd, td = filters.get("from_date"), filters.get("to_date")
	if fd or td:
		lines.append(f"{fd or ''} — {td or ''}")
	if filters.get("periodicity"):
		lines.append(str(filters["periodicity"]))
	for key in (extra_keys or []):
		if filters.get(key):
			lines.append(str(filters[key]))
	return lines


def check_report_permission(report_name):
	"""PDF endpoint'и ҳисоботнинг ЎЗИ билан бир хил ҳуқуқни талаб қилсин.

	`@frappe.whitelist()` ўзи фақат "тизимга кирганми" деб текширади. Ҳисобот
	эса Report doctype орқали Accounts Manager / Accounts User / System Manager
	билан чегараланган. Шу текширувсиз ҳар қандай фойдаланувчи (масалан омбор
	ходими) PDF орқали бутун гуруҳнинг фойда-зарарини, эгаларнинг олган пули
	ва дивидендигача кўра оларди."""
	if not frappe.db.exists("Report", report_name):
		frappe.throw(_("Ҳисобот топилмади: {0}").format(report_name))
	if not frappe.get_doc("Report", report_name).is_permitted():
		raise frappe.PermissionError(
			_("Сизда «{0}» ҳисоботини кўриш ҳуқуқи йўқ").format(report_name))
	frappe.has_permission("Report", "read", doc=report_name, throw=True)


def send(filters, execute_fn, title, subtitle, filename_prefix, extra_meta_keys=None,
		 report_name=None):
	"""Ҳисоботни PDF қилиб браузерга юборади (серверда сақланмайди)."""
	if report_name:
		check_report_permission(report_name)

	if isinstance(filters, str):
		filters = json.loads(filters)
	filters = frappe._dict(filters or {})

	columns, data = execute_fn(filters)
	html = build_html(
		title, subtitle, filters, columns, data,
		meta_from_filters(filters, extra_meta_keys),
	)

	frappe.local.response.filename = "%s_%s_%s.pdf" % (
		filename_prefix,
		str(filters.get("from_date") or "")[:10],
		str(filters.get("to_date") or "")[:10],
	)
	frappe.local.response.filecontent = HTML(string=html).write_pdf()
	frappe.local.response.type = "download"
