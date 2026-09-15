# -*- coding: utf-8 -*-
# Copyright (c) 2026, Jazira App
# License: MIT

"""Jazira savdo paneli — server qismi.

Nima uchun: biznes egasi va kunlik nazoratchi uchun standart savdo
ko'rsatkichlari — qaysi tovar zo'r ketyapti, qaysi kunlar kuchli, filiallar
taqqoslashi, tovar aylanmasi. Buxgalteriya tafsilotlari hisobotlarda qoladi.

QOIDA: foyda/marja pl_obshi dvigatelidan olinadi (hisobotlar bilan mos
tushishi uchun); tovar/kun kesimi esa to'g'ridan-to'g'ri Sales Invoice'dan
(chunki dvigatel tovar darajasiga tushmaydi).

Kompaniya semantikasi:
  • Barchasi   — guruhning TASHQI sotuvi (Sklad→filial ichki savdo chiqariladi)
  • Filial     — o'sha filialning tashqi sotuvi
  • Sklad      — Skladning barcha sotuvi (asosan filiallarga yetkazib berish —
                 bu uning biznesi)
"""

import json

import frappe
from frappe import _
from frappe.utils import add_days, add_months, flt, get_first_day, get_last_day, getdate, today

from jazira_app.jazira_app.report.pl_hisoboti.pl_hisoboti import build_period_list
from jazira_app.jazira_app.report.pl_obshi import pl_obshi

PAGE = "jazira-dashboard"
SKLAD = "Jazira Sklad"
CACHE_TTL = 60
MONTHS_BACK = 6

WEEKDAYS = ["Душанба", "Сешанба", "Чоршанба", "Пайшанба", "Жума", "Шанба", "Якшанба"]


# ─────────────────────────────────────────────────────────────────────────────
# Ruxsat va yordamchilar
# ─────────────────────────────────────────────────────────────────────────────

def _require_access():
	"""Sahifaning o'z rollari bo'yicha. @frappe.whitelist() faqat
	"kirganmi"ni tekshiradi — bu yetarli emas."""
	if not frappe.get_doc("Page", PAGE).is_permitted():
		raise frappe.PermissionError(_("Сизда бу саҳифани кўриш ҳуқуқи йўқ"))


def _can_drill(report_name):
	if not frappe.db.exists("Report", report_name):
		return False
	try:
		return bool(frappe.get_doc("Report", report_name).is_permitted())
	except Exception:
		return False


def _parse(value):
	if isinstance(value, str):
		try:
			return json.loads(value)
		except (ValueError, TypeError):
			return None
	return value


def _pct(part, whole):
	whole = flt(whole)
	return (flt(part) / whole * 100.0) if whole else None


def _delta_pct(now, prev):
	"""Manfiy bazada foiz ma'nosini yo'qotadi — None."""
	prev = flt(prev)
	if not prev or prev < 0 or flt(now) < 0:
		return None
	return (flt(now) - prev) / abs(prev) * 100.0


def _whole_months(from_date, to_date):
	f, t = getdate(from_date), getdate(to_date)
	if f != getdate(get_first_day(f)) or t != getdate(get_last_day(t)):
		return None
	return (t.year - f.year) * 12 + (t.month - f.month) + 1


def _prev_range(from_date, to_date):
	"""Butun oylar bo'lsa — shuncha oy orqaga; aks holda shuncha kun orqaga."""
	f, t = getdate(from_date), getdate(to_date)
	months = _whole_months(f, t)
	if months:
		return str(get_first_day(add_months(f, -months))), str(get_last_day(add_months(t, -months)))
	length = (t - f).days + 1
	return str(add_days(f, -length)), str(add_days(f, -1))


def _fmt_range(from_date, to_date):
	f, t = getdate(from_date), getdate(to_date)
	if _whole_months(f, t) == 1:
		return f.strftime("%B %Y")
	return "{0} — {1}".format(f.strftime("%d.%m.%Y"), t.strftime("%d.%m.%Y"))


# ─────────────────────────────────────────────────────────────────────────────
# Kontekst
# ─────────────────────────────────────────────────────────────────────────────

def _last_sale_date(companies):
	"""Oxirgi TASHQI sotuv sanasi (Sklad ichki fakturalari hisobga olinmaydi)."""
	row = frappe.db.sql(
		"""
		SELECT MAX(si.posting_date) FROM `tabSales Invoice` si
		JOIN `tabCustomer` cust ON cust.name = si.customer
		WHERE si.docstatus = 1 AND IFNULL(cust.is_internal_customer, 0) = 0
		  AND si.company IN %(companies)s
		""", {"companies": companies})
	return row[0][0] if row and row[0][0] else None


def _context(filters):
	f = frappe._dict(_parse(filters) or {})
	companies = pl_obshi.get_companies()

	from_date, to_date = f.get("from_date"), f.get("to_date")
	if not (from_date and to_date):
		# Standart: o'tgan kalendar oy — biznes uchun eng tabiiy "to'liq" davr
		last = get_first_day(add_months(getdate(today()), -1))
		from_date, to_date = str(last), str(get_last_day(last))
	if getdate(from_date) > getdate(to_date):
		frappe.throw(_("Давр нотўғри танланган"))

	scope = f.get("scope") or "all"
	if scope in companies:
		scope_companies = [scope]
	else:
		scope = "all"
		scope_companies = list(companies)

	# Sklad tanlansa — uning ichki sotuvi ham "sotuv" (bu uning biznesi).
	# Boshqa hollarda faqat tashqi.
	external_only = scope != SKLAD

	prev_from, prev_to = _prev_range(from_date, to_date)
	ctx = frappe._dict({
		"from_date": str(from_date), "to_date": str(to_date),
		"prev_from": prev_from, "prev_to": prev_to,
		"companies": companies,
		"scope": scope, "scope_companies": scope_companies,
		"external_only": external_only,
		"refresh": int(f.get("refresh") or 0),
	})
	return ctx


def _sales_where(ctx, si="si", cust="cust"):
	"""Qaysi Sales Invoice'lar "sotuv" hisoblanadi — bitta joyda."""
	cond = ["{0}.docstatus = 1".format(si), "{0}.company IN %(companies)s".format(si)]
	if ctx.external_only:
		cond.append("IFNULL({0}.is_internal_customer, 0) = 0".format(cust))
	return " AND ".join(cond)


def _sales_params(ctx, from_date=None, to_date=None):
	return {"companies": ctx.scope_companies,
			"from_date": from_date or ctx.from_date,
			"to_date": to_date or ctx.to_date}


def _pl(ctx, from_date, to_date):
	"""pl_obshi dvigateli orqali tushum va marjinal foyda (hisobotlar bilan mos)."""
	periods = build_period_list(frappe._dict({
		"from_date": from_date, "to_date": to_date, "periodicity": "Monthly"}))
	if not periods:
		return {"revenue": 0.0, "marginal": 0.0}
	pdata = pl_obshi.aggregate(
		periods, ctx.companies,
		pl_obshi.fetch_gl(ctx.companies, from_date, to_date),
		pl_obshi.fetch_internal_sales(ctx.companies, from_date, to_date),
		pl_obshi.fetch_dividends(ctx.companies, from_date, to_date),
		pl_obshi.fetch_owner_draws(ctx.companies, from_date, to_date),
	)
	revenue = marginal = 0.0
	for p in periods:
		d = pdata.get(p["key"]) or {}
		if ctx.scope == "all":
			revenue += flt(pl_obshi._total_revenue(d))
			marginal += flt(pl_obshi._total_marginal(d))
		else:
			cd = (d.get("companies") or {}).get(ctx.scope) or {}
			revenue += flt(cd.get("revenue"))
			marginal += flt(pl_obshi._co_marginal(cd))
	return {"revenue": revenue, "marginal": marginal}


def _qty(ctx, from_date, to_date):
	row = frappe.db.sql(
		"""
		SELECT ROUND(SUM(sii.qty)) FROM `tabSales Invoice Item` sii
		JOIN `tabSales Invoice` si ON si.name = sii.parent
		JOIN `tabCustomer` cust ON cust.name = si.customer
		WHERE {where} AND si.posting_date BETWEEN %(from_date)s AND %(to_date)s
		""".format(where=_sales_where(ctx)), _sales_params(ctx, from_date, to_date))
	return flt(row[0][0]) if row else 0.0


def _days_with_sales(ctx, from_date, to_date):
	row = frappe.db.sql(
		"""
		SELECT COUNT(DISTINCT si.posting_date) FROM `tabSales Invoice` si
		JOIN `tabCustomer` cust ON cust.name = si.customer
		WHERE {where} AND si.posting_date BETWEEN %(from_date)s AND %(to_date)s
		""".format(where=_sales_where(ctx)), _sales_params(ctx, from_date, to_date))
	return int(row[0][0] or 0) if row else 0


# ─────────────────────────────────────────────────────────────────────────────
# 1. KPI
# ─────────────────────────────────────────────────────────────────────────────

def _s_kpi(ctx):
	cur = _pl(ctx, ctx.from_date, ctx.to_date)
	prev = _pl(ctx, ctx.prev_from, ctx.prev_to)
	qty = _qty(ctx, ctx.from_date, ctx.to_date)
	qty_prev = _qty(ctx, ctx.prev_from, ctx.prev_to)
	days = _days_with_sales(ctx, ctx.from_date, ctx.to_date)
	days_prev = _days_with_sales(ctx, ctx.prev_from, ctx.prev_to)
	daily = cur["revenue"] / days if days else 0
	daily_prev = prev["revenue"] / days_prev if days_prev else 0
	margin = _pct(cur["marginal"], cur["revenue"])
	margin_prev = _pct(prev["marginal"], prev["revenue"])

	return {
		"tiles": [
			{"id": "revenue", "label": _("Тушум"), "value": round(cur["revenue"]),
			 "prev": round(prev["revenue"]), "delta_pct": _delta_pct(cur["revenue"], prev["revenue"]),
			 "lead": True},
			{"id": "qty", "label": _("Сотилган дона"), "value": round(qty), "kind": "qty",
			 "prev": round(qty_prev), "delta_pct": _delta_pct(qty, qty_prev)},
			{"id": "marginal", "label": _("Ялпи фойда"), "value": round(cur["marginal"]),
			 "prev": round(prev["marginal"]), "delta_pct": _delta_pct(cur["marginal"], prev["marginal"])},
			{"id": "margin", "label": _("Маржа"), "value": margin, "kind": "pct",
			 "prev": margin_prev,
			 "delta_abs": (margin - margin_prev) if (margin is not None and margin_prev is not None) else None},
			{"id": "daily", "label": _("Кунлик ўртача"), "value": round(daily),
			 "prev": round(daily_prev), "delta_pct": _delta_pct(daily, daily_prev),
			 "sub": _("{0} кун савдо").format(days)},
		],
		"days": days,
		"drill": {"report": "PL Obshi",
				  "filters": {"from_date": ctx.from_date, "to_date": ctx.to_date, "periodicity": "Monthly"}},
	}


# ─────────────────────────────────────────────────────────────────────────────
# 2. Kunlik sotuv
# ─────────────────────────────────────────────────────────────────────────────

def _daily_rows(ctx, from_date, to_date):
	return frappe.db.sql(
		"""
		SELECT si.posting_date AS d, si.company AS company, ROUND(SUM(si.base_net_total)) AS amt
		FROM `tabSales Invoice` si
		JOIN `tabCustomer` cust ON cust.name = si.customer
		WHERE {where} AND si.posting_date BETWEEN %(from_date)s AND %(to_date)s
		GROUP BY si.posting_date, si.company
		""".format(where=_sales_where(ctx)), _sales_params(ctx, from_date, to_date), as_dict=True)


def _s_daily(ctx):
	"""Kunma-kun sotuv. Sotuv bo'lmagan kun — null (nol emas)."""
	rows = _daily_rows(ctx, ctx.from_date, ctx.to_date)
	by_day = {}
	for r in rows:
		by_day.setdefault(str(r.d), {})[r.company] = flt(r.amt)

	days, cursor, end = [], getdate(ctx.from_date), getdate(ctx.to_date)
	while cursor <= end:
		key = str(cursor)
		vals = by_day.get(key) or {}
		days.append({
			"date": key, "weekday": cursor.weekday(),
			"label": cursor.strftime("%d.%m"),
			"total": round(sum(vals.values())) if vals else None,
			"by_company": {co: (round(vals[co]) if co in vals else None)
						   for co in ctx.scope_companies},
		})
		cursor = add_days(cursor, 1)

	# O'tgan davr bilan solishtirish — kunlar mos ravishda (1-kun vs 1-kun)
	prev_rows = _daily_rows(ctx, ctx.prev_from, ctx.prev_to)
	prev_by_day = {}
	for r in prev_rows:
		prev_by_day[str(r.d)] = prev_by_day.get(str(r.d), 0.0) + flt(r.amt)
	prev_series = []
	pc = getdate(ctx.prev_from)
	for _i in range(len(days)):
		v = prev_by_day.get(str(pc))
		prev_series.append(round(v) if v else None)
		pc = add_days(pc, 1)

	with_data = [d for d in days if d["total"] is not None]
	best = max(with_data, key=lambda d: d["total"]) if with_data else None
	worst = min(with_data, key=lambda d: d["total"]) if with_data else None

	return {
		"days": days,
		"prev_series": prev_series,
		"companies": [{"company": c, "label": pl_obshi.company_label(c)} for c in ctx.scope_companies],
		"best": best, "worst": worst,
		"weekday_names": WEEKDAYS,
	}


# ─────────────────────────────────────────────────────────────────────────────
# 3. Filiallar taqqoslashi
# ─────────────────────────────────────────────────────────────────────────────

def _s_companies(ctx):
	"""Har kompaniya: tushum, dona, marja, kunlik o'rtacha, o'zgarish, ulush.

	Bu bo'lim doim BARCHA kompaniyani ko'rsatadi (taqqoslash uchun),
	tanlangan kompaniya ajratib belgilanadi. Har kompaniyaning tushumi —
	uning tashqi sotuvi; Sklad uchun ham tashqi (ichki savdo taqqoslashda
	guruh daromadini ikki marta sanardi).
	"""
	def per_company(from_date, to_date):
		rows = frappe.db.sql(
			"""
			SELECT si.company AS company,
				   ROUND(SUM(si.base_net_total)) AS amt,
				   COUNT(DISTINCT si.posting_date) AS days
			FROM `tabSales Invoice` si
			JOIN `tabCustomer` cust ON cust.name = si.customer
			WHERE si.docstatus = 1 AND si.company IN %(companies)s
			  AND IFNULL(cust.is_internal_customer, 0) = 0
			  AND si.posting_date BETWEEN %(from_date)s AND %(to_date)s
			GROUP BY si.company
			""", {"companies": ctx.companies, "from_date": from_date, "to_date": to_date},
			as_dict=True)
		qty = frappe.db.sql(
			"""
			SELECT si.company AS company, ROUND(SUM(sii.qty)) AS q
			FROM `tabSales Invoice Item` sii
			JOIN `tabSales Invoice` si ON si.name = sii.parent
			JOIN `tabCustomer` cust ON cust.name = si.customer
			WHERE si.docstatus = 1 AND si.company IN %(companies)s
			  AND IFNULL(cust.is_internal_customer, 0) = 0
			  AND si.posting_date BETWEEN %(from_date)s AND %(to_date)s
			GROUP BY si.company
			""", {"companies": ctx.companies, "from_date": from_date, "to_date": to_date},
			as_dict=True)
		out = {r.company: {"amt": flt(r.amt), "days": int(r.days)} for r in rows}
		for r in qty:
			out.setdefault(r.company, {"amt": 0.0, "days": 0})["qty"] = flt(r.q)
		return out

	cur = per_company(ctx.from_date, ctx.to_date)
	prev = per_company(ctx.prev_from, ctx.prev_to)

	# Marja — dvigateldan (kompaniya kesimida)
	periods = build_period_list(frappe._dict({
		"from_date": ctx.from_date, "to_date": ctx.to_date, "periodicity": "Monthly"}))
	pdata = pl_obshi.aggregate(
		periods, ctx.companies,
		pl_obshi.fetch_gl(ctx.companies, ctx.from_date, ctx.to_date),
		pl_obshi.fetch_internal_sales(ctx.companies, ctx.from_date, ctx.to_date),
		pl_obshi.fetch_dividends(ctx.companies, ctx.from_date, ctx.to_date),
		pl_obshi.fetch_owner_draws(ctx.companies, ctx.from_date, ctx.to_date),
	) if periods else {}
	margin_by_co = {}
	for co in ctx.companies:
		rev = mar = 0.0
		for p in periods:
			cd = ((pdata.get(p["key"]) or {}).get("companies") or {}).get(co) or {}
			rev += flt(cd.get("revenue"))
			mar += flt(pl_obshi._co_marginal(cd))
		margin_by_co[co] = _pct(mar, rev)

	total = sum(v["amt"] for v in cur.values()) or 0.0
	rows = []
	for co in ctx.companies:
		c = cur.get(co) or {}
		p = prev.get(co) or {}
		amt = flt(c.get("amt"))
		rows.append({
			"company": co,
			"label": pl_obshi.company_label(co),
			"revenue": round(amt),
			"qty": round(flt(c.get("qty"))),
			"days": int(c.get("days") or 0),
			"daily_avg": round(amt / c["days"]) if c.get("days") else None,
			"margin_pct": margin_by_co.get(co),
			"share": _pct(amt, total),
			"delta_pct": _delta_pct(amt, p.get("amt")),
			"is_sklad": co == SKLAD,
			"selected": co == ctx.scope,
			"has_data": bool(amt),
		})
	rows.sort(key=lambda r: -r["revenue"])
	return {"rows": rows, "total": round(total),
			"drill": {"report": "PL Hisoboti"}}


# ─────────────────────────────────────────────────────────────────────────────
# 4. Tovarlar
# ─────────────────────────────────────────────────────────────────────────────

def _product_rows(ctx, from_date, to_date, companies=None):
	params = _sales_params(ctx, from_date, to_date)
	if companies:
		params["companies"] = companies
	return frappe.db.sql(
		"""
		SELECT sii.item_code AS item_code,
			   MAX(sii.item_name) AS item_name,
			   MAX(it.item_group) AS item_group,
			   ROUND(SUM(sii.qty)) AS qty,
			   ROUND(SUM(sii.base_net_amount)) AS amount,
			   COUNT(DISTINCT si.posting_date) AS days
		FROM `tabSales Invoice Item` sii
		JOIN `tabSales Invoice` si ON si.name = sii.parent
		JOIN `tabCustomer` cust ON cust.name = si.customer
		LEFT JOIN `tabItem` it ON it.name = sii.item_code
		WHERE {where} AND si.posting_date BETWEEN %(from_date)s AND %(to_date)s
		GROUP BY sii.item_code
		HAVING SUM(sii.base_net_amount) <> 0
		""".format(where=_sales_where(ctx)), params, as_dict=True)


def _s_products(ctx):
	"""Top tovarlar, o'sayotgan/tushayotganlar, aylanma (kun boshiga dona).

	Tovar bo'yicha MARJA ko'rsatilmaydi: filiallarda tekshirilmagan
	inventarizatsiyalar va manfiy qoldiqlar bor — tannarx ishonchsiz.
	"""
	cur = _product_rows(ctx, ctx.from_date, ctx.to_date)
	prev = {r.item_code: r for r in _product_rows(ctx, ctx.prev_from, ctx.prev_to)}
	period_days = (getdate(ctx.to_date) - getdate(ctx.from_date)).days + 1
	total = sum(flt(r.amount) for r in cur) or 0.0

	def pack(r):
		p = prev.get(r.item_code)
		return {
			"item": r.item_name or r.item_code,
			"group": r.item_group,
			"qty": flt(r.qty),
			"amount": flt(r.amount),
			"share": _pct(r.amount, total),
			"per_day": round(flt(r.qty) / period_days, 1) if period_days else None,
			"prev_amount": flt(p.amount) if p else 0.0,
			"delta_pct": _delta_pct(r.amount, p.amount if p else 0),
			"delta_abs": round(flt(r.amount) - (flt(p.amount) if p else 0.0)),
		}

	packed = [pack(r) for r in cur]
	by_amount = sorted(packed, key=lambda x: -x["amount"])
	by_qty = sorted(packed, key=lambda x: -x["qty"])

	# O'sayotgan / tushayotgan — absolyut o'zgarish bo'yicha, kichik
	# summalar shovqin bermasin (davr tushumining 0.3% dan katta)
	floor = total * 0.003
	movers = [x for x in packed if abs(x["delta_abs"]) >= floor]
	rising = sorted([x for x in movers if x["delta_abs"] > 0], key=lambda x: -x["delta_abs"])[:6]
	falling = sorted([x for x in movers if x["delta_abs"] < 0], key=lambda x: x["delta_abs"])[:6]

	# Yangi paydo bo'lgan / yo'qolgan tovarlar
	cur_codes = {r.item_code for r in cur}
	gone = [{"item": p.item_name or p.item_code, "prev_amount": flt(p.amount)}
			for c, p in prev.items() if c not in cur_codes and flt(p.amount) > floor]
	gone.sort(key=lambda x: -x["prev_amount"])

	return {
		"total": round(total),
		"count": len(packed),
		"by_amount": by_amount[:15],
		"by_qty": by_qty[:15],
		"rising": rising,
		"falling": falling,
		"gone": gone[:5],
		"turnover": sorted(packed, key=lambda x: -x["qty"])[:25],
		"drill": {"report": "Prodaja Sheets"},
	}


def _s_categories(ctx):
	"""Tovar guruhlari ulushi — pie chart uchun."""
	rows = frappe.db.sql(
		"""
		SELECT IFNULL(it.item_group, 'Прочее') AS grp,
			   ROUND(SUM(sii.base_net_amount)) AS amount,
			   ROUND(SUM(sii.qty)) AS qty
		FROM `tabSales Invoice Item` sii
		JOIN `tabSales Invoice` si ON si.name = sii.parent
		JOIN `tabCustomer` cust ON cust.name = si.customer
		LEFT JOIN `tabItem` it ON it.name = sii.item_code
		WHERE {where} AND si.posting_date BETWEEN %(from_date)s AND %(to_date)s
		GROUP BY grp HAVING SUM(sii.base_net_amount) > 0
		ORDER BY amount DESC
		""".format(where=_sales_where(ctx)), _sales_params(ctx), as_dict=True)
	total = sum(flt(r.amount) for r in rows) or 0.0
	out = [{"group": r.grp, "amount": flt(r.amount), "qty": flt(r.qty),
			"share": _pct(r.amount, total)} for r in rows]
	# Pie chart uchun: eng katta 7 ta + "Boshqa"
	top, rest = out[:7], out[7:]
	if rest:
		top.append({"group": _("Бошқа"), "amount": sum(x["amount"] for x in rest),
					"qty": sum(x["qty"] for x in rest),
					"share": sum(flt(x["share"]) for x in rest)})
	return {"rows": out, "pie": top, "total": round(total)}


def _s_weekdays(ctx):
	"""Hafta kunlari bo'yicha o'rtacha sotuv — qaysi kun kuchli?"""
	rows = frappe.db.sql(
		"""
		SELECT t.d AS d, t.amt AS amt FROM (
			SELECT si.posting_date AS d, SUM(si.base_net_total) AS amt
			FROM `tabSales Invoice` si
			JOIN `tabCustomer` cust ON cust.name = si.customer
			WHERE {where} AND si.posting_date BETWEEN %(from_date)s AND %(to_date)s
			GROUP BY si.posting_date
		) t
		""".format(where=_sales_where(ctx)), _sales_params(ctx), as_dict=True)
	agg = {i: {"sum": 0.0, "n": 0} for i in range(7)}
	for r in rows:
		wd = getdate(r.d).weekday()
		agg[wd]["sum"] += flt(r.amt)
		agg[wd]["n"] += 1
	out = []
	for i in range(7):
		n = agg[i]["n"]
		out.append({"weekday": i, "label": WEEKDAYS[i], "short": WEEKDAYS[i][:3],
					"avg": round(agg[i]["sum"] / n) if n else None,
					"total": round(agg[i]["sum"]), "days": n})
	with_data = [x for x in out if x["avg"]]
	best = max(with_data, key=lambda x: x["avg"]) if with_data else None
	worst = min(with_data, key=lambda x: x["avg"]) if with_data else None
	overall = (sum(x["total"] for x in out) / sum(x["days"] for x in out)) if with_data else 0
	for x in out:
		x["vs_avg_pct"] = _pct(x["avg"] - overall, overall) if (x["avg"] and overall) else None
	return {"rows": out, "best": best, "worst": worst, "overall_avg": round(overall)}


def _s_best_days(ctx):
	"""Eng zo'r va eng zaif kunlar — kompaniya kesimi bilan."""
	rows = _daily_rows(ctx, ctx.from_date, ctx.to_date)
	by_day = {}
	for r in rows:
		d = by_day.setdefault(str(r.d), {"total": 0.0, "by_company": {}})
		d["total"] += flt(r.amt)
		d["by_company"][r.company] = flt(r.amt)
	packed = []
	for key, v in by_day.items():
		dt = getdate(key)
		top_co = max(v["by_company"].items(), key=lambda x: x[1])[0] if v["by_company"] else None
		packed.append({
			"date": key, "label": dt.strftime("%d.%m"), "weekday": WEEKDAYS[dt.weekday()],
			"total": round(v["total"]),
			"top_company": pl_obshi.company_label(top_co) if top_co else None,
			"by_company": {pl_obshi.company_label(c): round(a) for c, a in v["by_company"].items()},
		})
	packed.sort(key=lambda x: -x["total"])
	return {"best": packed[:7], "worst": list(reversed(packed[-5:])) if len(packed) > 5 else []}


def _s_monthly(ctx):
	"""Oylik dinamika — tushum, yalpi foyda, marja, dona (oxirgi 6 oy)."""
	end = getdate(ctx.to_date)
	start = get_first_day(add_months(end, -(MONTHS_BACK - 1)))
	periods = build_period_list(frappe._dict({
		"from_date": str(start), "to_date": str(get_last_day(end)), "periodicity": "Monthly"}))
	if not periods:
		return {"rows": []}
	fd, td = str(periods[0]["from_date"]), str(periods[-1]["to_date"])
	pdata = pl_obshi.aggregate(
		periods, ctx.companies,
		pl_obshi.fetch_gl(ctx.companies, fd, td),
		pl_obshi.fetch_internal_sales(ctx.companies, fd, td),
		pl_obshi.fetch_dividends(ctx.companies, fd, td),
		pl_obshi.fetch_owner_draws(ctx.companies, fd, td),
	)
	qty_rows = frappe.db.sql(
		"""
		SELECT LEFT(si.posting_date, 7) AS ym, ROUND(SUM(sii.qty)) AS q,
			   COUNT(DISTINCT si.posting_date) AS days
		FROM `tabSales Invoice Item` sii
		JOIN `tabSales Invoice` si ON si.name = sii.parent
		JOIN `tabCustomer` cust ON cust.name = si.customer
		WHERE {where} AND si.posting_date BETWEEN %(from_date)s AND %(to_date)s
		GROUP BY ym
		""".format(where=_sales_where(ctx)), _sales_params(ctx, fd, td), as_dict=True)
	qty_by = {r.ym: r for r in qty_rows}

	rows = []
	for p in periods:
		d = pdata.get(p["key"]) or {}
		if ctx.scope == "all":
			rev = flt(pl_obshi._total_revenue(d)); mar = flt(pl_obshi._total_marginal(d))
			pro = flt(pl_obshi._total_profit(d))
		else:
			cd = (d.get("companies") or {}).get(ctx.scope) or {}
			rev = flt(cd.get("revenue")); mar = flt(pl_obshi._co_marginal(cd))
			pro = flt(pl_obshi._co_profit(cd))
		ym = str(p["from_date"])[:7]
		q = qty_by.get(ym)
		in_month = getdate(get_last_day(p["from_date"])).day
		days = int(q.days) if q else 0
		if not (rev or mar or pro):
			continue
		rows.append({
			"key": ym, "label": p["label"], "short": p["label"].split(" ")[0],
			"revenue": round(rev), "marginal": round(mar), "profit": round(pro),
			"margin_pct": _pct(mar, rev), "qty": round(flt(q.q)) if q else 0,
			"days": days, "complete": days >= in_month - 1,
		})
	return {"rows": rows}


def _s_company_products(ctx):
	"""Har filialning o'z top-5 tovari — filiallar bo'limi uchun."""
	out = []
	for co in ctx.companies:
		sub = frappe._dict(ctx); sub.scope_companies = [co]; sub.external_only = (co != SKLAD)
		rows = _product_rows(sub, ctx.from_date, ctx.to_date, companies=[co])
		rows.sort(key=lambda r: -flt(r.amount))
		total = sum(flt(r.amount) for r in rows) or 0.0
		out.append({
			"company": co, "label": pl_obshi.company_label(co), "is_sklad": co == SKLAD,
			"items": [{"item": r.item_name or r.item_code, "qty": flt(r.qty),
					   "amount": flt(r.amount), "share": _pct(r.amount, total)} for r in rows[:5]],
		})
	return {"rows": out}


# ─────────────────────────────────────────────────────────────────────────────
# 5. Moliya — P&L tarkibi va xarajatlar (pl_obshi dvigatelidan)
# ─────────────────────────────────────────────────────────────────────────────

def _merge_company(dst, src):
	for field in ("revenue", "cogs_raw", "cogs_adj", "kassa", "brak", "owner_salary"):
		dst[field] = flt(dst.get(field)) + flt(src.get(field))
	for field in ("adj", "op", "adm", "other"):
		bucket = dst.setdefault(field, {})
		for k, v in (src.get(field) or {}).items():
			bucket[k] = flt(bucket.get(k)) + flt(v)
	return dst


def _merge(pdata, keys):
	"""Bir necha oylik davrni bitta davr lug'atiga jamlaydi (GL yig'indisi
	bo'lgani uchun aniq)."""
	out = {"companies": {}, "internal": 0.0, "dividends": {}, "acc_labels": {},
		   "adm_raw": {}, "owner_taken": {}, "owner_salary": {}}
	for key in keys:
		d = pdata.get(key)
		if not d:
			continue
		for co, cd in (d.get("companies") or {}).items():
			_merge_company(out["companies"].setdefault(co, {}), cd)
		out["internal"] += flt(d.get("internal"))
		for field in ("dividends", "adm_raw", "owner_taken", "owner_salary"):
			for k, v in (d.get(field) or {}).items():
				out[field][k] = flt(out[field].get(k)) + flt(v)
		out["acc_labels"].update(d.get("acc_labels") or {})
	return out


def _pl_merged(ctx, from_date, to_date):
	if ctx.get("_plm_" + from_date):
		return ctx["_plm_" + from_date]
	periods = build_period_list(frappe._dict({
		"from_date": from_date, "to_date": to_date, "periodicity": "Monthly"}))
	if not periods:
		return _merge({}, [])
	pdata = pl_obshi.aggregate(
		periods, ctx.companies,
		pl_obshi.fetch_gl(ctx.companies, from_date, to_date),
		pl_obshi.fetch_internal_sales(ctx.companies, from_date, to_date),
		pl_obshi.fetch_dividends(ctx.companies, from_date, to_date),
		pl_obshi.fetch_owner_draws(ctx.companies, from_date, to_date),
	)
	ctx["_plm_" + from_date] = _merge(pdata, [p["key"] for p in periods])
	return ctx["_plm_" + from_date]


def _pnl_numbers(ctx, D):
	"""Tanlangan qamrov bo'yicha P&L satrlari — dvigatelning o'z formulalari."""
	if ctx.scope == "all":
		cos = D.get("companies") or {}
		cogs_raw = sum(flt(c.get("cogs_raw")) for c in cos.values())
		cogs_adj = sum(flt(c.get("cogs_adj")) for c in cos.values())
		kassa = sum(flt(c.get("kassa")) for c in cos.values())
		brak = sum(flt(c.get("brak")) for c in cos.values())
		return {
			"revenue_gross": sum(flt(c.get("revenue")) for c in cos.values()),
			"internal": flt(D.get("internal")),
			"revenue": flt(pl_obshi._total_revenue(D)),
			"cogs_raw": cogs_raw, "cogs_adj": cogs_adj, "kassa": kassa, "brak": brak,
			"cogs": flt(pl_obshi._total_cogs(D)),
			"marginal": flt(pl_obshi._total_marginal(D)),
			"op": flt(pl_obshi._total_op(D)), "adm": flt(pl_obshi._total_adm(D)),
			"other": flt(pl_obshi._total_other(D)),
			"opex": flt(pl_obshi._total_opex(D)),
			"profit": flt(pl_obshi._total_profit(D)),
		}
	cd = (D.get("companies") or {}).get(ctx.scope) or {}
	return {
		"revenue_gross": flt(cd.get("revenue")), "internal": 0.0,
		"revenue": flt(cd.get("revenue")),
		"cogs_raw": flt(cd.get("cogs_raw")), "cogs_adj": flt(cd.get("cogs_adj")),
		"kassa": flt(cd.get("kassa")), "brak": flt(cd.get("brak")),
		"cogs": flt(pl_obshi._co_cogs(cd)),
		"marginal": flt(pl_obshi._co_marginal(cd)),
		"op": flt(pl_obshi._co_op(cd)), "adm": flt(pl_obshi._co_adm(cd)),
		"other": flt(pl_obshi._co_other(cd)),
		"opex": flt(pl_obshi._co_op(cd)) + flt(pl_obshi._co_adm(cd)) + flt(pl_obshi._co_other(cd)),
		"profit": flt(pl_obshi._co_profit(cd)),
	}


def _s_pnl(ctx):
	cur = _pnl_numbers(ctx, _pl_merged(ctx, ctx.from_date, ctx.to_date))
	prev = _pnl_numbers(ctx, _pl_merged(ctx, ctx.prev_from, ctx.prev_to))

	def line(key, label, kind="", is_cost=False):
		v, p = cur.get(key), prev.get(key)
		return {"key": key, "label": label, "value": round(flt(v)), "prev": round(flt(p)),
				"delta_pct": _delta_pct(v, p), "delta_abs": round(flt(v) - flt(p)),
				"kind": kind, "is_cost": is_cost,
				"pct_of_revenue": _pct(v, cur["revenue"])}

	lines = [
		line("revenue_gross", _("Тушум (жами)"), "sub"),
		line("internal", _("(−) Ички айланма"), "detail", True),
		line("revenue", _("Итого выручка"), "result"),
		line("cogs_raw", _("Хом ашё таннархи"), "detail", True),
		line("cogs_adj", _("Омбор тафовути"), "detail", True),
		line("brak", _("Брак"), "detail", True),
		line("cogs", _("Итого себестоимость"), "sub", True),
		line("marginal", _("Маржинальная прибыль"), "result"),
		line("op", _("Операцион харажатлар"), "detail", True),
		line("adm", _("Маъмурий харажатлар"), "detail", True),
		line("other", _("Бошқа харажатлар"), "detail", True),
		line("opex", _("Итого расходы"), "sub", True),
		line("profit", _("Операционная прибыль"), "result"),
	]
	if ctx.scope != "all":
		lines = [l for l in lines if l["key"] not in ("revenue_gross", "internal")]
	if not cur.get("kassa") and not prev.get("kassa"):
		pass  # kassa farqi hisoblari amalda ishlatilmaydi — qator qo'shilmaydi

	return {
		"lines": lines,
		"margin_pct": _pct(cur["marginal"], cur["revenue"]),
		"profit_pct": _pct(cur["profit"], cur["revenue"]),
		"margin_prev_pct": _pct(prev["marginal"], prev["revenue"]),
		"profit_prev_pct": _pct(prev["profit"], prev["revenue"]),
		"drill": {"report": "PL Obshi" if ctx.scope == "all" else "PL Hisoboti",
				  "filters": ({"from_date": ctx.from_date, "to_date": ctx.to_date, "periodicity": "Monthly"}
							  if ctx.scope == "all" else
							  {"company": ctx.scope, "from_date": ctx.from_date,
							   "to_date": ctx.to_date, "periodicity": "Monthly"})},
	}


def _s_expenses(ctx):
	D = _pl_merged(ctx, ctx.from_date, ctx.to_date)
	P = _pl_merged(ctx, ctx.prev_from, ctx.prev_to)
	labels = dict(D.get("acc_labels") or {}); labels.update(P.get("acc_labels") or {})

	def collect(d, bucket):
		out = {}
		for co, cd in (d.get("companies") or {}).items():
			if co not in ctx.scope_companies:
				continue
			for acc, amt in (cd.get(bucket) or {}).items():
				out[acc] = flt(out.get(acc)) + flt(amt)
		return out

	def rows_of(cur_map, prev_map):
		out = []
		for acc, amt in cur_map.items():
			if not flt(amt):
				continue
			out.append({"account": acc, "label": labels.get(acc, acc), "value": round(flt(amt)),
						"prev": round(flt(prev_map.get(acc))), "delta_pct": _delta_pct(amt, prev_map.get(acc)),
						"delta_abs": round(flt(amt) - flt(prev_map.get(acc)))})
		return sorted(out, key=lambda r: -abs(r["value"]))

	op = rows_of(collect(D, "op"), collect(P, "op"))
	# Ma'muriy — guruh puli (taqsimlashdan oldingi), faqat "Barchasi"da
	show_admin = ctx.scope == "all"
	adm = rows_of(D.get("adm_raw") or {}, P.get("adm_raw") or {}) if show_admin else []
	return {
		"operating": op[:25], "operating_total": round(sum(r["value"] for r in op)),
		"admin": adm[:15], "admin_total": round(sum(r["value"] for r in adm)) if show_admin else None,
		"show_admin": show_admin,
		"drill": {"report": "Expense Analysis",
				  "filters": ({"from_date": ctx.from_date, "to_date": ctx.to_date}
							  if ctx.scope == "all" else
							  {"company": ctx.scope, "from_date": ctx.from_date, "to_date": ctx.to_date})},
	}


# ─────────────────────────────────────────────────────────────────────────────
# 6. Buxgalteriya — kassa, qarz, debitor/kreditor, zaxira (balance_obshi)
# ─────────────────────────────────────────────────────────────────────────────

from jazira_app.jazira_app.report.balance_obshi import balance_obshi  # noqa: E402


def _balance_at(ctx, as_of):
	key = "_bal_" + str(as_of)
	if ctx.get(key):
		return ctx[key]
	period = [{"key": "b", "label": str(as_of), "from_date": str(as_of), "to_date": str(as_of)}]
	ctx[key] = balance_obshi.compute(period, ctx.companies)
	return ctx[key]


def _cash_figures(ctx, as_of):
	"""Kassa, ta'minotchi qarzi, debitor/kreditor, zaxira — qamrov bo'yicha."""
	bal = _balance_at(ctx, as_of)
	cos = set(ctx.scope_companies)
	cash_by_co, cash_by_acc, stock = {}, {}, 0.0
	for (bucket, co), arr in bal["static"].items():
		if co not in cos:
			continue
		if bucket == "cash":
			cash_by_co[co] = cash_by_co.get(co, 0.0) + flt(arr[-1])
		elif bucket == "stock":
			stock += flt(arr[-1])

	supp_credit, by_party, ext_ar, ext_ap = 0.0, {}, 0.0, 0.0
	for (klass, _label, co, party), arr in bal["party"].items():
		if co not in cos:
			continue
		val = flt(arr[-1])
		if klass == "supp" and val < 0:
			supp_credit += -val
			by_party[party] = by_party.get(party, 0.0) + (-val)
		if klass in ("cust", "supp", "emp", "other", "nopar"):
			if val > 0:
				ext_ar += val
			else:
				ext_ap += -val
	return {
		"cash_total": sum(cash_by_co.values()),
		"cash_by_co": cash_by_co,
		"supplier_debt": supp_credit,
		"top_creditors": sorted(by_party.items(), key=lambda x: -x[1])[:10],
		"external_ar": ext_ar, "external_ap": ext_ap,
		"stock": stock,
	}


def _cash_accounts(ctx, as_of):
	"""Kassa hisoblari kesimida (naqd / terminal / karta) — qaysi kanalda pul."""
	rows = frappe.db.sql(
		"""
		SELECT acc.account_name AS name, IFNULL(acc.account_number, '') AS number,
			   ROUND(SUM(gle.debit - gle.credit)) AS bal
		FROM `tabGL Entry` gle
		JOIN `tabAccount` acc ON acc.name = gle.account
		WHERE gle.is_cancelled = 0 AND acc.account_type = 'Cash' AND acc.is_group = 0
		  AND gle.company IN %(companies)s AND gle.posting_date <= %(as_of)s
		GROUP BY acc.account_number, acc.account_name
		HAVING ABS(SUM(gle.debit - gle.credit)) > 0.5
		ORDER BY bal DESC
		""", {"companies": ctx.scope_companies, "as_of": as_of}, as_dict=True)
	return [{"name": r.name, "number": r.number, "value": round(flt(r.bal))} for r in rows]


def _s_cash(ctx):
	cur = _cash_figures(ctx, ctx.to_date)
	prev = _cash_figures(ctx, ctx.prev_to)
	drafts = frappe.db.count("Stock Reconciliation", {"docstatus": 0, "company": ["in", ctx.scope_companies]})
	negative = frappe.db.sql(
		"""SELECT COUNT(*) FROM `tabBin` b JOIN `tabWarehouse` w ON w.name = b.warehouse
		   WHERE b.actual_qty < 0 AND w.company IN %(c)s""", {"c": ctx.scope_companies})[0][0]
	return {
		"cash": {"total": round(cur["cash_total"]), "prev": round(prev["cash_total"]),
				 "delta_pct": _delta_pct(cur["cash_total"], prev["cash_total"]),
				 "by_company": [{"company": co, "label": pl_obshi.company_label(co), "value": round(v)}
								for co, v in sorted(cur["cash_by_co"].items(), key=lambda x: -x[1])],
				 "by_account": _cash_accounts(ctx, ctx.to_date)},
		"supplier_debt": {"total": round(cur["supplier_debt"]), "prev": round(prev["supplier_debt"]),
						  "delta_pct": _delta_pct(cur["supplier_debt"], prev["supplier_debt"]),
						  "coverage_pct": _pct(cur["cash_total"], cur["supplier_debt"]),
						  "top": [{"party": p, "value": round(v)} for p, v in cur["top_creditors"]]},
		"receivable": round(cur["external_ar"]),
		"payable": round(cur["external_ap"]),
		"inventory": {"value": round(cur["stock"]), "prev": round(prev["stock"]),
					  "drafts": drafts, "negative": int(negative or 0)},
		"as_of": ctx.to_date,
		"drill": {"report": "Balance Obshi",
				  "filters": {"from_date": ctx.from_date, "to_date": ctx.to_date, "periodicity": "Monthly"}},
	}


# ─────────────────────────────────────────────────────────────────────────────
# 7. Egalar
# ─────────────────────────────────────────────────────────────────────────────

def _s_owners(ctx):
	"""Foyda ulushi + hisob-varaq. Doim guruh bo'yicha (ulush guruh tushunchasi)."""
	D = _pl_merged(ctx, ctx.from_date, ctx.to_date)
	split = {"akmal": 0.0, "elyor": 0.0, "rows": []}
	for co in ctx.companies:
		cd = (D.get("companies") or {}).get(co)
		if not cd:
			continue
		profit = flt(pl_obshi._co_profit(cd))
		sh = pl_obshi.get_shares(co)
		a, e = profit * flt(sh.get("akmal")), profit * flt(sh.get("elyor"))
		split["akmal"] += a; split["elyor"] += e
		split["rows"].append({"label": pl_obshi.company_label(co), "profit": round(profit),
							  "akmal": round(a), "elyor": round(e),
							  "rule": "100% Акмал" if flt(sh.get("akmal")) == 1 else "50/50"})

	parties = pl_obshi.resolve_owner_parties()
	ledger = {"akmal": {"taken": 0.0, "added": 0.0, "net": 0.0, "cumulative": 0.0},
			  "elyor": {"taken": 0.0, "added": 0.0, "net": 0.0, "cumulative": 0.0}}
	if parties:
		for r in frappe.db.sql(
			"""
			SELECT gle.party AS party,
				   ROUND(SUM(CASE WHEN gle.posting_date BETWEEN %(f)s AND %(t)s THEN gle.debit ELSE 0 END)) AS taken,
				   ROUND(SUM(CASE WHEN gle.posting_date BETWEEN %(f)s AND %(t)s THEN gle.credit ELSE 0 END)) AS added,
				   ROUND(SUM(CASE WHEN gle.posting_date <= %(t)s THEN gle.debit - gle.credit ELSE 0 END)) AS cumulative
			FROM `tabGL Entry` gle
			WHERE gle.is_cancelled = 0 AND gle.party_type IN ('Employee', 'Shareholder')
			  AND gle.party IN %(p)s
			GROUP BY gle.party
			""", {"f": ctx.from_date, "t": ctx.to_date, "p": list(parties.keys())}, as_dict=True):
			o = parties.get(r.party)
			if not o:
				continue
			ledger[o]["taken"] += flt(r.taken); ledger[o]["added"] += flt(r.added)
			ledger[o]["cumulative"] += flt(r.cumulative)
		for o in ledger:
			ledger[o]["net"] = ledger[o]["taken"] - ledger[o]["added"]

	return {
		"owners": [
			{"key": "akmal", "label": "Акмал", "share": round(split["akmal"]),
			 **{k: round(v) for k, v in ledger["akmal"].items()}},
			{"key": "elyor", "label": "Элёр", "share": round(split["elyor"]),
			 **{k: round(v) for k, v in ledger["elyor"].items()}},
		],
		"by_company": split["rows"],
		"rule": _("Смарт — 100% Акмал · қолганлари 50/50 (зарар ҳам)"),
		"drill": {"report": "PL Calculation",
				  "filters": {"from_date": ctx.from_date, "to_date": ctx.to_date, "periodicity": "Monthly"}},
	}


# ─────────────────────────────────────────────────────────────────────────────
# 8. Ma'lumot holati (ixcham)
# ─────────────────────────────────────────────────────────────────────────────

def _s_health(ctx):
	today_d = getdate(today())
	last = {}
	for r in frappe.db.sql(
		"""
		SELECT si.company AS company, MAX(si.posting_date) AS d FROM `tabSales Invoice` si
		JOIN `tabCustomer` cust ON cust.name = si.customer
		WHERE si.docstatus = 1 AND IFNULL(cust.is_internal_customer, 0) = 0
		GROUP BY si.company""", as_dict=True):
		last[r.company] = r.d
	fresh = []
	for co in ctx.companies:
		d = last.get(co)
		fresh.append({"company": co, "label": pl_obshi.company_label(co),
					  "last_date": str(d) if d else None,
					  "days": (today_d - getdate(d)).days if d else None})
	worst = max((x["days"] for x in fresh if x["days"] is not None), default=None)

	alloc = {}
	for r in frappe.get_all("Jazira Expense Allocation", filters={"docstatus": 1}, fields=["name", "from_date"]):
		if r.from_date:
			alloc[str(r.from_date)[:7]] = r.name
	months = []
	c = get_first_day(getdate(ctx.from_date))
	while c <= getdate(ctx.to_date):
		months.append(str(c)[:7]); c = get_first_day(add_months(c, 1))
	missing = [m for m in months if m not in alloc]

	bal = _balance_at(ctx, ctx.to_date)
	gap = sum(flt(v[-1]) for k, v in bal["party"].items() if k[0] in ("fil_ar", "fil_ap"))
	drafts = frappe.db.count("Stock Reconciliation", {"docstatus": 0})
	negative = frappe.db.sql("SELECT COUNT(*) FROM `tabBin` WHERE actual_qty < 0")[0][0]

	chips = [
		{"id": "fresh", "label": _("Сотув маълумоти"),
		 "tone": "ok" if (worst is not None and worst <= 1) else ("warn" if (worst is not None and worst <= 3) else "danger"),
		 "text": (_("охиргиси {0} кун олдин").format(worst) if worst is not None else _("йўқ")),
		 "detail": fresh},
		{"id": "alloc", "label": _("Харажат тақсимоти"),
		 "tone": "ok" if not missing else "warn",
		 "text": _("бажарилган") if not missing else _("{0} — йўқ").format(", ".join(missing)),
		 "route": ["List", "Jazira Expense Allocation"]},
		{"id": "stock", "label": _("Омбор ҳужжатлари"),
		 "tone": "danger" if drafts > 20 else ("warn" if (drafts or negative) else "ok"),
		 "text": _("{0} черновик · {1} манфий").format(drafts, int(negative or 0)),
		 "route": ["List", "Stock Reconciliation", {"docstatus": "0"}]},
		{"id": "inter", "label": _("Филиаллараро"),
		 "tone": "ok" if abs(gap) <= 1000 else ("warn" if abs(gap) <= 5_000_000 else "danger"),
		 "text": _("тафовут {0}").format(round(gap)) if abs(gap) > 1000 else _("мос"),
		 "drill": {"report": "Intercompany Sverka",
				   "filters": {"from_date": ctx.from_date, "to_date": ctx.to_date, "only_differences": 1}}},
	]
	tone = "danger" if any(c["tone"] == "danger" for c in chips) else (
		"warn" if any(c["tone"] == "warn" for c in chips) else "ok")
	return {"tone": tone, "chips": chips, "last_sale": str(_last_sale_date(ctx.companies) or "")}


# ─────────────────────────────────────────────────────────────────────────────
# API
# ─────────────────────────────────────────────────────────────────────────────

_BUILDERS = {
	"kpi": _s_kpi, "daily": _s_daily, "companies": _s_companies,
	"products": _s_products, "categories": _s_categories, "weekdays": _s_weekdays,
	"best_days": _s_best_days, "monthly": _s_monthly, "company_products": _s_company_products,
	"pnl": _s_pnl, "expenses": _s_expenses, "cash": _s_cash, "owners": _s_owners,
	"health": _s_health,
}

DRILL_REPORTS = ("PL Obshi", "PL Calculation", "PL Hisoboti", "Balance Obshi",
				 "Expense Analysis", "DDS", "Intercompany Sverka", "Kontragent Otchet",
				 "Prodaja Sheets", "Material Report")


def _cached(ctx, key, builder):
	"""60 s — yopilgan oylar ham keyin o'zgarishi mumkin (orqaga yozish)."""
	ck = "::".join(str(x) for x in ("jz_dash2", frappe.session.user, key, ctx.scope, ctx.from_date, ctx.to_date))
	if not ctx.refresh:
		v = frappe.cache().get_value(ck)
		if v is not None:
			return v
	v = builder()
	frappe.cache().set_value(ck, v, expires_in_sec=CACHE_TTL)
	return v


@frappe.whitelist()
def get_meta():
	_require_access()
	companies = pl_obshi.get_companies()
	last = get_first_day(add_months(getdate(today()), -1))
	return {
		"companies": [{"name": c, "label": pl_obshi.company_label(c), "is_sklad": c == SKLAD} for c in companies],
		"default": {"from_date": str(last), "to_date": str(get_last_day(last))},
		"last_sale": str(_last_sale_date(companies) or ""),
		"can_drill": {r: _can_drill(r) for r in DRILL_REPORTS},
		"today": str(today()),
	}


@frappe.whitelist()
def get_dashboard(filters=None, sections=None):
	_require_access()
	ctx = _context(filters)
	wanted = _parse(sections)
	if isinstance(wanted, str):
		wanted = [wanted]
	wanted = [s for s in (wanted or list(_BUILDERS)) if s in _BUILDERS]

	out = {"context": {
		"scope": ctx.scope, "from_date": ctx.from_date, "to_date": ctx.to_date,
		"prev_from": ctx.prev_from, "prev_to": ctx.prev_to,
		"label": _fmt_range(ctx.from_date, ctx.to_date),
		"prev_label": _fmt_range(ctx.prev_from, ctx.prev_to),
		"external_only": ctx.external_only,
		"computed_at": frappe.utils.now_datetime().strftime("%Y-%m-%d %H:%M"),
	}}
	for section in wanted:
		try:
			out[section] = _cached(ctx, section, lambda s=section: _BUILDERS[s](ctx))
		except Exception:
			frappe.log_error(title="Jazira dashboard: {0}".format(section), message=frappe.get_traceback())
			out[section] = {"error": _("Бу бўлимни юклашда хатолик юз берди")}
	return out
