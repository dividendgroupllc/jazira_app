# Copyright (c) 2026, Jazira App and contributors
# For license information, please see license.txt

"""
Intercompany Sverka — Склад ↔ филиал ўртасидаги СОТУВ ва ХАРИДни солиштириш.

Склад филиалларга товар сотади: сотувчи китобида Sales Invoice, олувчи
китобида Purchase Invoice юзага келади. Иккови ҳамиша тенг бўлиши керак.
Тенг бўлмаса — бир томонда ҳужжат тушиб қолган ёки бекор қилинган.

Ҳужжатлар қандай жуфтланади
───────────────────────────
ERPNext'нинг `inter_company_invoice_reference` майдони бу базада ишончсиз:
304 та ички ҳаридан фақат 43 тасида, сотувнинг эса 7 тасида тўлдирилган.
Шунинг учун жуфтлаш ЙЎНАЛИШ + САНА + СУММА бўйича қилинади:

    (сотувчи -> олувчи, posting_date, round(summa))

Жуфти топилмаган ҳужжат "фақат сотувда" ёки "фақат харидда" деб алоҳида
чиқади — фарқнинг айнан қайси ҳужжатдан келгани шу ерда кўринади.
"""

import frappe
from frappe import _
from frappe.utils import flt, getdate


def execute(filters=None):
	filters = frappe._dict(filters or {})
	validate_filters(filters)

	sales = fetch_sales(filters)
	purchases = fetch_purchases(filters)

	return get_columns(), build_rows(sales, purchases, filters)


def validate_filters(filters):
	if not filters.get("from_date") or not filters.get("to_date"):
		frappe.throw(_("Сана оралиғи мажбурий"))
	if getdate(filters["from_date"]) > getdate(filters["to_date"]):
		frappe.throw(_("Бошланиш санаси тугаш санасидан катта бўлиши мумкин эмас"))


# ─── Ma'lumot ────────────────────────────────────────────────────────────────

def _extra_conditions(filters, seller_field, buyer_field):
	cond, params = [], {}
	if filters.get("seller"):
		cond.append(f"{seller_field} = %(seller)s")
		params["seller"] = filters["seller"]
	if filters.get("buyer"):
		cond.append(f"{buyer_field} = %(buyer)s")
		params["buyer"] = filters["buyer"]
	return (" AND " + " AND ".join(cond) if cond else ""), params


def fetch_sales(filters):
	"""Ички мижозга ёзилган Sales Invoice — сотувчи томони."""
	extra, extra_params = _extra_conditions(filters, "si.company", "c.represents_company")
	return frappe.db.sql(
		f"""
		SELECT si.name, si.posting_date, si.company AS seller,
			   c.represents_company AS buyer, si.base_net_total AS amount
		FROM `tabSales Invoice` si
		JOIN `tabCustomer` c ON c.name = si.customer
		WHERE si.docstatus = 1
		  AND c.is_internal_customer = 1
		  AND IFNULL(c.represents_company, '') != ''
		  AND si.posting_date BETWEEN %(from_date)s AND %(to_date)s
		  {extra}
		ORDER BY si.posting_date, si.name
		""",
		dict(from_date=filters["from_date"], to_date=filters["to_date"], **extra_params),
		as_dict=True,
	)


def fetch_purchases(filters):
	"""Ички таъминотчидан олинган Purchase Invoice — олувчи томони."""
	extra, extra_params = _extra_conditions(filters, "s.represents_company", "pi.company")
	return frappe.db.sql(
		f"""
		SELECT pi.name, pi.posting_date, s.represents_company AS seller,
			   pi.company AS buyer, pi.base_net_total AS amount
		FROM `tabPurchase Invoice` pi
		JOIN `tabSupplier` s ON s.name = pi.supplier
		WHERE pi.docstatus = 1
		  AND s.is_internal_supplier = 1
		  AND IFNULL(s.represents_company, '') != ''
		  AND pi.posting_date BETWEEN %(from_date)s AND %(to_date)s
		  {extra}
		ORDER BY pi.posting_date, pi.name
		""",
		dict(from_date=filters["from_date"], to_date=filters["to_date"], **extra_params),
		as_dict=True,
	)


# ─── Ustunlar ────────────────────────────────────────────────────────────────

def get_columns():
	return [
		{"fieldname": "label", "label": _("Йўналиш / сана"),
		 "fieldtype": "Data", "width": 260},
		{"fieldname": "sales_invoice", "label": _("Сотув ҳужжати"),
		 "fieldtype": "Data", "width": 195},
		{"fieldname": "sale_amount", "label": _("Сотув суммаси"),
		 "fieldtype": "Currency", "width": 155},
		{"fieldname": "purchase_invoice", "label": _("Харид ҳужжати"),
		 "fieldtype": "Data", "width": 195},
		{"fieldname": "purchase_amount", "label": _("Харид суммаси"),
		 "fieldtype": "Currency", "width": 155},
		{"fieldname": "diff", "label": _("ФАРҚ"), "fieldtype": "Currency", "width": 140},
	]


# ─── Jufтlash ────────────────────────────────────────────────────────────────

def _match(sale_rows, purchase_rows):
	"""Сана+сумма бўйича жуфтлайди.

	Қайтаради: (жуфтлар [(сотув, харид)], жуфтсиз сотувлар, жуфтсиз харидлар).
	"""
	pool = {}
	for p in purchase_rows:
		pool.setdefault((str(p.posting_date), round(flt(p.amount), 2)), []).append(p)

	pairs = []
	unmatched_sales = []
	for s in sale_rows:
		key = (str(s.posting_date), round(flt(s.amount), 2))
		if pool.get(key):
			pairs.append((s, pool[key].pop()))
		else:
			unmatched_sales.append(s)

	unmatched_purchases = [p for lst in pool.values() for p in lst]
	return pairs, unmatched_sales, unmatched_purchases


def _month(d):
	return str(d)[:7]


# ─── Qatorlar ────────────────────────────────────────────────────────────────

def build_rows(sales, purchases, filters):
	only_diff = int(filters.get("only_differences") or 0)

	directions = sorted(
		{(r.seller, r.buyer) for r in sales} | {(r.seller, r.buyer) for r in purchases}
	)

	def mk(label, row_type, indent, s_cnt=0, s_amt=0, p_cnt=0, p_amt=0,
		   si_doc=None, pi_doc=None):
		# Гуруҳ қаторида (йўналиш/ой/жами) invoice устунида ҲУЖЖАТ СОНИ
		# кўринади, ҳужжат қаторида — ҳужжатнинг ўзи (JS ҳавола қилади).
		return {
			"label": label, "row_type": row_type, "indent": indent, "indent_level": indent,
			"sales_invoice": si_doc or (f"{s_cnt} та" if s_cnt else None),
			"sale_amount": s_amt or None,
			"purchase_invoice": pi_doc or (f"{p_cnt} та" if p_cnt else None),
			"purchase_amount": p_amt or None,
			"diff": flt(s_amt) - flt(p_amt),
			# JS formatter shu maydonlardan bosiladigan havola yasaydi
			"si_doc": si_doc, "pi_doc": pi_doc,
		}

	rows = []
	t_sc = t_sa = t_pc = t_pa = 0

	for seller, buyer in directions:
		d_sales = [r for r in sales if r.seller == seller and r.buyer == buyer]
		d_purch = [r for r in purchases if r.seller == seller and r.buyer == buyer]

		s_amt = sum(flt(r.amount) for r in d_sales)
		p_amt = sum(flt(r.amount) for r in d_purch)
		t_sc += len(d_sales); t_sa += s_amt
		t_pc += len(d_purch); t_pa += p_amt

		if only_diff and abs(s_amt - p_amt) < 0.01:
			continue

		rows.append(mk(f"{seller}  →  {buyer}", "root", 0,
					   len(d_sales), s_amt, len(d_purch), p_amt))

		# ── Ойлар ────────────────────────────────────────────────────────────
		months = sorted({_month(r.posting_date) for r in d_sales} |
						{_month(r.posting_date) for r in d_purch})
		for m in months:
			m_sales = [r for r in d_sales if _month(r.posting_date) == m]
			m_purch = [r for r in d_purch if _month(r.posting_date) == m]
			ms = sum(flt(r.amount) for r in m_sales)
			mp = sum(flt(r.amount) for r in m_purch)
			if only_diff and abs(ms - mp) < 0.01:
				continue
			rows.append(mk(m, "sub", 1, len(m_sales), ms, len(m_purch), mp))

			pairs, u_sales, u_purch = _match(m_sales, m_purch)

			# ── Ҳужжатлар: SI ⇆ PI жуфтлари ─────────────────────────────────
			# "Фақат фарқлар" режимида тенг жуфтлар кўрсатилмайди — фақат
			# муаммоли (жуфтсиз) ҳужжатлар қолади.
			if not only_diff:
				for sd, pd_ in sorted(pairs, key=lambda x: (str(x[0].posting_date), x[0].name)):
					rows.append(mk(
						str(sd.posting_date),
						"detail", 2, 1, flt(sd.amount), 1, flt(pd_.amount),
						si_doc=sd.name, pi_doc=pd_.name))

			# ── Жуфтсиз ҳужжатлар ────────────────────────────────────────────
			for r in u_sales:
				rows.append(mk(f"⚠ {r.posting_date} · жуфти йўқ", "warn", 2,
							   1, flt(r.amount), 0, 0, si_doc=r.name))
			for r in u_purch:
				rows.append(mk(f"⚠ {r.posting_date} · жуфти йўқ", "warn", 2,
							   0, 0, 1, flt(r.amount), pi_doc=r.name))

	if rows:
		rows.append({"label": "", "row_type": "divider", "indent": 0, "indent_level": 0})
	rows.append(mk(_("ЖАМИ"), "result", 0, t_sc, t_sa, t_pc, t_pa))

	return rows
