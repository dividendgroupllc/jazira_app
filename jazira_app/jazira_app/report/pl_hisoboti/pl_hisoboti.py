# Copyright (c) 2026, Jazira App and contributors
# For license information, please see license.txt

"""
PL Hisoboti — Jazira uchun P&L (foyda-zarar) hisoboti.

Dvigatel (davrlarga bo'lish, GL asosidagi P&L matematikasi, ota-hisob guruhi
bo'yicha avtomatik yig'ish, daraxt-qator dizayni) Pokiza ilovasining
pl_hisoboti reportidan olingan — u umuman Pokiza'ning hisoblar rejasiga
qattiq bog'lanmagan, faqat root_type/account_type va ota-hisob raqami bo'yicha
ishlaydi. Jazira uchun moslashtirilgan qism:

  - Xarajat guruhlari: Pokiza'da 6 ta (Ишлаб чиқариш/Реализация/Админ/Прочие/
    Молия/Солиқ), Jazira'da haqiqiy Chart of Accounts'da faqat 2 ta guruh bor:
    "52001 - Операционный" va "52002 - Адм". Shu ikkisi + "5200 - Indirect
    Expenses"ning bevosita farzand (guruhsiz) hisoblari + boshqa hech qaysi
    toifaga tushmagan Expense hisoblar uchun "Бошқа харажатлар" (yo'qotib
    qo'ymaslik uchun qopqoq toifa) — 4 ta bo'lim.
  - "кг сотилган ҳажм" o'rniga — "Sotuvlar soni (chek)" (submit qilingan
    Sales Invoice soni) va "O'rtacha chek" (Revenue / chek soni), chunki
    Jazira turli o'lchov birligida (dona/kg/litr) mahsulot sotadi — ularni
    bittalab qo'shish ma'nosiz bo'lardi.
"""

import frappe
from frappe import _
from frappe.utils import flt, getdate
from datetime import date, timedelta


CARD_COLORS = ["#2563EB", "#059669", "#7C3AED", "#DC2626", "#0891B2", "#D97706", "#BE185D"]


# ─── Entry point ─────────────────────────────────────────────────────────────

def execute(filters=None):
	filters = frappe._dict(filters or {})
	company = filters.get("company")
	if not company:
		frappe.throw(_("Аввал компанияни танланг"))

	period_list = build_period_list(filters)
	if not period_list:
		return [], []

	from_date = str(period_list[0]["from_date"])
	to_date = str(period_list[-1]["to_date"])

	gl_rows = fetch_gl(company, from_date, to_date)
	order_rows = fetch_order_counts(company, from_date, to_date)
	group_paths = resolve_group_paths(company)
	opex_accounts = {
		"operational": fetch_group_accounts(company, group_paths.get("52001")),
		"admin": fetch_group_accounts(company, group_paths.get("52002")),
		"other_indirect": fetch_direct_children(company, group_paths.get("5200"), exclude_prefixes=("52001", "52002")),
	}
	pdata = aggregate(period_list, gl_rows, order_rows, group_paths)

	columns = get_columns(period_list)
	data = build_rows(period_list, pdata, opex_accounts)
	summary_html = get_summary_html(company, filters, period_list, pdata)

	return columns, data, summary_html


# ─── Period list (Pokiza bilan bir xil dvigatel) ────────────────────────────

def build_period_list(filters):
	today = date.today()
	from_date = getdate(filters.get("from_date") or date(today.year, 1, 1))
	to_date = getdate(filters.get("to_date") or today)
	periodicity = filters.get("periodicity") or "Yearly"

	periods = []
	current = from_date

	while current <= to_date:
		y, m = current.year, current.month

		if periodicity == "Monthly":
			p_start = date(y, m, 1)
			nm = m + 1
			p_end = (date(y, nm, 1) - timedelta(days=1)) if nm <= 12 else date(y, 12, 31)
			label = p_start.strftime("%b %Y")
			next_cur = date(y, nm, 1) if nm <= 12 else date(y + 1, 1, 1)

		elif periodicity == "Quarterly":
			q = (m - 1) // 3
			qs, qe = q * 3 + 1, q * 3 + 3
			p_start = date(y, qs, 1)
			p_end = (date(y, qe + 1, 1) - timedelta(days=1)) if qe < 12 else date(y, 12, 31)
			label = f"Q{q + 1} {y}"
			nqs = qe + 1
			next_cur = date(y, nqs, 1) if nqs <= 12 else date(y + 1, 1, 1)

		elif periodicity == "Half-Yearly":
			if m <= 6:
				p_start, p_end, label = date(y, 1, 1), date(y, 6, 30), f"H1 {y}"
				next_cur = date(y, 7, 1)
			else:
				p_start, p_end, label = date(y, 7, 1), date(y, 12, 31), f"H2 {y}"
				next_cur = date(y + 1, 1, 1)

		else:  # Yearly
			p_start, p_end, label = date(y, 1, 1), date(y, 12, 31), str(y)
			next_cur = date(y + 1, 1, 1)

		actual_start = max(p_start, from_date)
		actual_end = min(p_end, to_date)
		if actual_start <= actual_end:
			periods.append({
				"key": label,
				"label": label,
				"from_date": actual_start,
				"to_date": actual_end,
			})
		current = next_cur

	return periods


# ─── Data fetching ────────────────────────────────────────────────────────────

def fetch_gl(company, from_date, to_date):
	return frappe.db.sql("""
		SELECT
			gle.posting_date,
			TRIM(IFNULL(acc.account_number, '')) AS account_number,
			TRIM(IFNULL(parent_acc.account_number, '')) AS parent_number,
			acc.parent_account,
			acc.account_name,
			acc.root_type,
			acc.account_type,
			SUM(gle.debit) AS debit,
			SUM(gle.credit) AS credit
		FROM `tabGL Entry` gle
		JOIN `tabAccount` acc ON acc.name = gle.account
		LEFT JOIN `tabAccount` parent_acc ON parent_acc.name = acc.parent_account
		WHERE gle.company = %s
		  AND gle.is_cancelled = 0
		  AND gle.posting_date BETWEEN %s AND %s
		  AND acc.root_type IN ('Income', 'Expense')
		GROUP BY gle.posting_date, gle.account
		ORDER BY gle.posting_date
	""", (company, from_date, to_date), as_dict=True)


def fetch_order_counts(company, from_date, to_date):
	"""Sotuvlar soni (chek) — Sales Invoice soni, o'lchov birligidan qat'iy
	nazar (Jazira dona/kg/litr aralash sotadi, shuning uchun kg-hajm o'rniga
	'nechta chek yozilgan' universal ko'rsatkich sifatida ishlatiladi)."""
	return frappe.db.sql("""
		SELECT posting_date, COUNT(*) AS cnt
		FROM `tabSales Invoice`
		WHERE company = %s
		  AND docstatus = 1
		  AND posting_date BETWEEN %s AND %s
		GROUP BY posting_date
	""", (company, from_date, to_date), as_dict=True)


def resolve_group_paths(company):
	"""'52001'/'52002'/'5200' account raqamlariga mos to'liq hisob nomini
	(docname) shu kompaniya uchun topadi. Guruh mavjud bo'lmasa None."""
	result = {}
	for num in ("52001", "52002", "5200"):
		result[num] = frappe.db.get_value(
			"Account",
			{"company": company, "account_number": num, "root_type": "Expense"},
			"name",
		)
	return result


def fetch_group_accounts(company, parent_account_name):
	"""Berilgan (to'liq nomli) ota-hisobning barcha farzand (leaf) hisoblari."""
	if not parent_account_name:
		return []
	accounts = frappe.db.sql("""
		SELECT TRIM(IFNULL(account_number, '')) AS acc_num, account_name
		FROM `tabAccount`
		WHERE company = %s AND parent_account = %s AND is_group = 0
		ORDER BY account_number, account_name
	""", (company, parent_account_name), as_dict=True)
	return [(a.account_name, a.acc_num or a.account_name) for a in accounts]


def fetch_direct_children(company, parent_account_name, exclude_prefixes=()):
	"""fetch_group_accounts kabi, lekin ostidagi raqamli sub-guruhlar
	(masalan 52001/52002)ning o'zini chiqarib tashlaydi — faqat to'g'ridan-to'g'ri
	guruhsiz farzand hisoblarni qaytaradi (masalan 5200 ning o'zига tegishli,
	52001/52002 ostiga tushmagan hisoblar)."""
	if not parent_account_name:
		return []
	accounts = frappe.db.sql("""
		SELECT TRIM(IFNULL(account_number, '')) AS acc_num, account_name, is_group
		FROM `tabAccount`
		WHERE company = %s AND parent_account = %s
		ORDER BY account_number, account_name
	""", (company, parent_account_name), as_dict=True)
	out = []
	for a in accounts:
		if a.is_group:
			continue
		num = a.acc_num or ""
		if any(num.startswith(p) for p in exclude_prefixes):
			continue
		out.append((a.account_name, num or a.account_name))
	return out


# ─── Aggregation ─────────────────────────────────────────────────────────────

def _period_key(posting_date, period_list):
	for p in period_list:
		if p["from_date"] <= posting_date <= p["to_date"]:
			return p["key"]
	return None


def _fk(period_key):
	return "v_" + period_key.replace(" ", "_").replace("-", "_")


def aggregate(period_list, gl_rows, order_rows, group_paths):
	def empty():
		return dict(revenue=0, cogs=0, operational={}, admin={},
					other_indirect={}, other_uncategorized={}, orders=0)

	pdata = {p["key"]: empty() for p in period_list}

	op_path = group_paths.get("52001")
	adm_path = group_paths.get("52002")
	ind_path = group_paths.get("5200")

	for r in gl_rows:
		pk = _period_key(r.posting_date, period_list)
		if not pk:
			continue
		d = pdata[pk]
		net = flt(r.debit) - flt(r.credit)
		num = r.account_number or ""
		name = r.account_name or ""
		key = num or name

		if r.root_type == "Income":
			d["revenue"] += flt(r.credit) - flt(r.debit)

		elif r.account_type in ("Cost of Goods Sold", "Stock Adjustment"):
			d["cogs"] += net

		elif op_path and r.parent_account == op_path:
			d["operational"][key] = d["operational"].get(key, 0) + net

		elif adm_path and r.parent_account == adm_path:
			d["admin"][key] = d["admin"].get(key, 0) + net

		elif ind_path and r.parent_account == ind_path:
			d["other_indirect"][key] = d["other_indirect"].get(key, 0) + net

		else:
			# Hech qaysi ma'lum toifaga tushmagan Expense hisob — yo'qotib
			# qo'ymaslik uchun "Бошқа харажатлар"ga tushadi.
			d["other_uncategorized"][key] = d["other_uncategorized"].get(key, 0) + net

	for r in order_rows:
		pk = _period_key(r.posting_date, period_list)
		if pk:
			pdata[pk]["orders"] += int(r.cnt or 0)

	return pdata


# ─── Columns ─────────────────────────────────────────────────────────────────

def get_columns(period_list):
	cols = [{"fieldname": "label", "label": _("Кўрсаткич"), "fieldtype": "Data", "width": 310}]
	for p in period_list:
		cols.append({
			"fieldname": _fk(p["key"]),
			"label": p["label"],
			"fieldtype": "Currency",
			"options": "currency",
			"width": 160,
		})
	return cols


# ─── Row builder ─────────────────────────────────────────────────────────────

def build_rows(period_list, pdata, opex_accounts=None):
	opex_accounts = opex_accounts or {}
	fkeys = [_fk(p["key"]) for p in period_list]

	def mk(label, getter=None, value_map=None, row_type="detail", level=0,
		   is_percent=False, is_ratio=False, is_cost=False, is_qty=False, indent=None):
		r = {
			"label": label,
			"row_type": row_type,
			"indent_level": level,
			"is_percent": 1 if is_percent else 0,
			"is_ratio": 1 if is_ratio else 0,
			"is_cost": 1 if is_cost else 0,
			"is_qty": 1 if is_qty else 0,
		}
		if indent is not None:
			r["indent"] = indent
		if value_map is None and getter is not None:
			value_map = {_fk(p["key"]): getter(pdata[p["key"]]) for p in period_list}
		r.update(value_map or {})
		return r

	def divider():
		r = {"label": "", "row_type": "divider", "indent_level": 0}
		for fk in fkeys:
			r[fk] = None
		return r

	def per_period(fn):
		return {_fk(p["key"]): fn(pdata[p["key"]]) for p in period_list}

	rows = []

	# ── Sotuvlar soni (chek) ────────────────────────────────────────────────
	rows.append(mk("Sotuvlar soni (чек)", getter=lambda d: d["orders"], row_type="root", is_qty=True))
	rows.append(divider())

	# ── Выручка ──────────────────────────────────────────────────────────────
	rows.append(mk("Выручка от реализации", getter=lambda d: d["revenue"], row_type="root"))
	rows.append(mk("ўртача чек",
		value_map=per_period(lambda d: d["revenue"] / d["orders"] if d["orders"] else 0),
		row_type="ratio", level=1, is_ratio=True))
	rows.append(divider())

	# ── Себестоимость (faqat xomashyo/сырьё — account_type asosida) ─────────
	cogs_total = per_period(lambda d: d["cogs"])
	rows.append(mk("Себестоимость реализации", value_map=cogs_total, row_type="root", is_cost=True))

	marginal = per_period(lambda d: d["revenue"] - d["cogs"])
	rows.append(mk("Маржинальная прибыль", value_map=marginal, row_type="result"))
	rows.append(mk("маржа",
		value_map=per_period(lambda d: (d["revenue"] - d["cogs"]) / d["revenue"] * 100 if d["revenue"] else 0),
		row_type="percent", level=1, is_percent=True))
	rows.append(divider())

	# ── Операционные расходы (52001) ─────────────────────────────────────────
	op_total = per_period(lambda d: sum(d["operational"].values()))
	rows.append(mk("Операционные расходы", value_map=op_total, row_type="sub", level=1, is_cost=True, indent=0))
	for acc_name, acc_key in opex_accounts.get("operational", []):
		arow = {_fk(p["key"]): pdata[p["key"]]["operational"].get(acc_key, 0) for p in period_list}
		if all(not v for v in arow.values()):
			continue
		rows.append(mk(acc_name, value_map=arow, row_type="detail", level=2, is_cost=True, indent=1))
	rows.append(divider())

	gp = per_period(lambda d: d["revenue"] - d["cogs"] - sum(d["operational"].values()))
	rows.append(mk("Валовая прибыль", value_map=gp, row_type="result"))
	rows.append(mk("маржа",
		value_map=per_period(lambda d: (d["revenue"] - d["cogs"] - sum(d["operational"].values())) / d["revenue"] * 100 if d["revenue"] else 0),
		row_type="percent", level=1, is_percent=True))
	rows.append(divider())

	# ── Расходы с прибыли: Админ + Бошқа бевосита + Бошқа ────────────────────
	def _opex(d):
		return (sum(d["admin"].values()) + sum(d["other_indirect"].values())
				+ sum(d["other_uncategorized"].values()))

	opex_total = per_period(_opex)
	rows.append(mk("Расходы с прибыли", value_map=opex_total, row_type="root", is_cost=True))
	for section_label, key in [
		("Административные расходы", "admin"),
		("Бошқа бевосита харажатлар", "other_indirect"),
		("Бошқа харажатлар", "other_uncategorized"),
	]:
		svals = {_fk(p["key"]): sum(pdata[p["key"]][key].values()) for p in period_list}
		# Bo'lim to'liq bo'sh bo'lsa (hech qanday davrda summasi yo'q), qatorni
		# umuman ko'rsatmaymiz — "Бошқа харажатлар" ko'pincha 0 bo'ladi.
		if all(not v for v in svals.values()):
			continue
		rows.append(mk(section_label, value_map=svals, row_type="sub", level=1, is_cost=True, indent=0))
		for acc_name, acc_key in opex_accounts.get(key, []):
			arow = {_fk(p["key"]): pdata[p["key"]][key].get(acc_key, 0) for p in period_list}
			if all(not v for v in arow.values()):
				continue
			rows.append(mk(acc_name, value_map=arow, row_type="detail", level=2, is_cost=True, indent=1))
	rows.append(divider())

	def _net(d):
		gross = d["revenue"] - d["cogs"] - sum(d["operational"].values())
		return gross - _opex(d)

	rows.append(mk("Чистая прибыль", value_map=per_period(_net), row_type="result"))
	rows.append(mk("рентабельность",
		value_map=per_period(lambda d: _net(d) / d["revenue"] * 100 if d["revenue"] else 0),
		row_type="percent", level=1, is_percent=True))

	return rows


# ─── Summary HTML (dizayn paneli) ────────────────────────────────────────────

def _fmt(val):
	v = abs(flt(val))
	if v >= 1_000_000_000:
		return f"{v / 1_000_000_000:.2f}B"
	elif v >= 1_000_000:
		return f"{v / 1_000_000:.1f}M"
	elif v >= 1_000:
		return f"{v / 1_000:.0f}K"
	return f"{v:,.0f}"


def _bar(pct, color, bg):
	w = min(max(flt(pct), 0), 100)
	return f"""
		<div style="background:{bg};height:6px;border-radius:3px;overflow:hidden;margin-top:4px;">
		  <div style="background:{color};height:100%;width:{w:.1f}%;border-radius:3px;"></div>
		</div>"""


def get_summary_html(company, filters, period_list, pdata):
	from_date = filters.get("from_date", "")
	to_date = filters.get("to_date", "")
	periodicity = filters.get("periodicity", "Yearly")
	currency = frappe.get_cached_value("Company", company, "default_currency") or "UZS"

	header = f"""
	<div style="background:linear-gradient(135deg,#0f2942 0%,#1e3a5f 60%,#1a4f72 100%);
				color:white;padding:20px 24px;border-radius:12px;margin-bottom:16px;
				display:flex;align-items:center;justify-content:space-between;flex-wrap:wrap;gap:8px;">
	  <div>
		<div style="font-size:10px;letter-spacing:2.5px;text-transform:uppercase;
					opacity:0.6;margin-bottom:4px;">ФОЙДА — ЗАРАР ҲИСОБОТИ</div>
		<div style="font-size:20px;font-weight:700;letter-spacing:-0.3px;">{frappe.utils.escape_html(company)} &nbsp;·&nbsp; P&amp;L Report</div>
	  </div>
	  <div style="text-align:right;opacity:0.75;font-size:12px;line-height:1.6;">
		<div>{from_date} — {to_date}</div>
		<div style="font-size:10px;opacity:0.7;margin-top:2px;">{periodicity}</div>
	  </div>
	</div>"""

	cards_html = ""
	for i, p in enumerate(period_list):
		d = pdata[p["key"]]
		gp = d["revenue"] - d["cogs"] - sum(d["operational"].values())
		opex = sum(d["admin"].values()) + sum(d["other_indirect"].values()) + sum(d["other_uncategorized"].values())
		np = gp - opex

		gm_pct = (gp / d["revenue"] * 100) if d["revenue"] else 0
		nm_pct = (np / d["revenue"] * 100) if d["revenue"] else 0
		color = CARD_COLORS[i % len(CARD_COLORS)]

		if i > 0:
			prev_rev = pdata[period_list[i - 1]["key"]]["revenue"]
			delta = d["revenue"] - prev_rev
			if prev_rev:
				trend_pct = delta / prev_rev * 100
				trend_ico = "▲" if delta >= 0 else "▼"
				trend_clr = "#10b981" if delta >= 0 else "#ef4444"
				trend_str = f'<span style="color:{trend_clr};font-size:10px;font-weight:600;">{trend_ico} {abs(trend_pct):.1f}%</span>'
			else:
				trend_str = ""
		else:
			trend_str = ""

		gm_bar = _bar(gm_pct, "#10b981", "#ecfdf5")
		nm_bar = _bar(nm_pct, color, "#eff6ff")

		cards_html += f"""
		<div style="flex:1;min-width:180px;background:white;border-radius:10px;
					box-shadow:0 1px 8px rgba(0,0,0,0.07);overflow:hidden;
					border:1px solid #f0f0f0;">
		  <div style="background:{color};padding:10px 14px;
					  display:flex;align-items:center;justify-content:space-between;">
			<span style="color:white;font-size:13px;font-weight:700;">{p['label']}</span>
			{trend_str}
		  </div>
		  <div style="padding:14px 16px;">
			<div style="margin-bottom:14px;padding-bottom:12px;border-bottom:1px solid #f5f5f5;">
			  <div style="font-size:9px;color:#aaa;text-transform:uppercase;
						  letter-spacing:1px;margin-bottom:2px;">Выручка</div>
			  <div style="font-size:22px;font-weight:800;color:#111;line-height:1.1;">
				{_fmt(d['revenue'])}
			  </div>
			  <div style="font-size:10px;color:#aaa;margin-top:1px;">{currency}</div>
			</div>

			<div style="margin-bottom:10px;">
			  <div style="display:flex;justify-content:space-between;align-items:center;">
				<span style="font-size:10px;color:#777;">Yalpi foyda</span>
				<span style="font-size:11px;font-weight:700;color:#10b981;">{gm_pct:.1f}%</span>
			  </div>
			  {gm_bar}
			  <div style="font-size:9px;color:#bbb;margin-top:2px;">{_fmt(gp)} {currency}</div>
			</div>

			<div>
			  <div style="display:flex;justify-content:space-between;align-items:center;">
				<span style="font-size:10px;color:#777;">Sof foyda</span>
				<span style="font-size:11px;font-weight:700;color:{color};">{nm_pct:.1f}%</span>
			  </div>
			  {nm_bar}
			  <div style="font-size:9px;color:#bbb;margin-top:2px;">{_fmt(np)} {currency}</div>
			</div>
		  </div>
		</div>"""

	cards_section = f"""
	<div style="display:flex;gap:12px;flex-wrap:wrap;margin-bottom:16px;">
	  {cards_html}
	</div>"""

	cost_bars = ""
	for i, p in enumerate(period_list):
		d = pdata[p["key"]]
		rev = d["revenue"]
		if not rev:
			continue
		cogs_pct = d["cogs"] / rev * 100
		op_pct = sum(d["operational"].values()) / rev * 100
		adm_pct = sum(d["admin"].values()) / rev * 100
		oth_pct = (sum(d["other_indirect"].values()) + sum(d["other_uncategorized"].values())) / rev * 100
		profit_pct = max(100 - cogs_pct - op_pct - adm_pct - oth_pct, 0)
		color = CARD_COLORS[i % len(CARD_COLORS)]

		cost_bars += f"""
		<div style="margin-bottom:12px;">
		  <div style="display:flex;justify-content:space-between;
					  align-items:center;margin-bottom:5px;">
			<span style="font-size:11px;font-weight:600;color:#333;">{p['label']}</span>
			<span style="font-size:10px;color:#888;">{_fmt(rev)} {currency}</span>
		  </div>
		  <div style="display:flex;height:18px;border-radius:6px;overflow:hidden;gap:1px;">
			<div style="flex:{cogs_pct:.1f};background:#ef4444;" title="COGS {cogs_pct:.1f}%"></div>
			<div style="flex:{op_pct:.1f};background:#f97316;" title="Операционный {op_pct:.1f}%"></div>
			<div style="flex:{adm_pct:.1f};background:#8b5cf6;" title="Адм. {adm_pct:.1f}%"></div>
			<div style="flex:{oth_pct:.1f};background:#6b7280;" title="Прочие {oth_pct:.1f}%"></div>
			<div style="flex:{profit_pct:.1f};background:#10b981;" title="Foyda {profit_pct:.1f}%"></div>
		  </div>
		  <div style="display:flex;gap:10px;margin-top:4px;flex-wrap:wrap;">
			<span style="font-size:9px;color:#ef4444;">■ COGS {cogs_pct:.0f}%</span>
			<span style="font-size:9px;color:#f97316;">■ Операционный {op_pct:.0f}%</span>
			<span style="font-size:9px;color:#8b5cf6;">■ Адм. {adm_pct:.0f}%</span>
			<span style="font-size:9px;color:#6b7280;">■ Прочие {oth_pct:.0f}%</span>
			<span style="font-size:9px;color:#10b981;">■ Foyda {profit_pct:.0f}%</span>
		  </div>
		</div>"""

	structure_section = ""
	if cost_bars:
		structure_section = f"""
		<div style="background:white;border-radius:10px;padding:16px 20px;
					box-shadow:0 1px 8px rgba(0,0,0,0.07);border:1px solid #f0f0f0;">
		  <div style="font-size:11px;font-weight:700;color:#333;
					  text-transform:uppercase;letter-spacing:1px;margin-bottom:14px;">
			Даромаддан тузилиши
		  </div>
		  {cost_bars}
		</div>"""

	return f"""
	<div style="margin:20px 0;font-family:'Segoe UI',Arial,sans-serif;">
	  {header}
	  {cards_section}
	  {structure_section}
	</div>"""
