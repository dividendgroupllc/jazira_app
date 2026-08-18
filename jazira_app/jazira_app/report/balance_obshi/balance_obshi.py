# Copyright (c) 2026, Jazira App and contributors
# License: MIT

"""
Balance Obshi — Jazira guruhi bo'yicha JAMLANGAN BALANS.

Google Sheet'dagi "Баланс общий" varag'ining ERPNext ko'chirmasi:
har ustun — davr OXIRI holatiga qoldiq, qatorlar tabiat bo'yicha
(Запасы / Денежные средства / Дебиторка / Кредиторка / Капитал),
ichida kompaniya va kontragent turi kesimida.

Sheet'dan tekshirib olingan qoidalar:
  · "Накопленная прибыль — прошлых периодов" = ustun davri BOSHIGACHA
    yig'ilgan guruh foydasi; "прибыль <ko>" = shu davr ichidagi foyda.
    (yanvar: 507 107 464 + yanvar foydalari = fevral 815 108 188 ✓)
  · "Рабочий капитал" = Итого активы − Кредиторская задолженность
    (yanvar: 1 522 840 914 − 898 823 581 = 624 017 333 ✓)

Kontragent qoldiqlari HAR PARTIYA bo'yicha nettolanadi va ISHORASIGA
qarab tomonga qo'yiladi: debet qoldiq — aktiv (Дебиторка), kredit —
passiv (Кредиторка). Shuning uchun bitta xodim bir oy aktivda, keyingi
oy passivda chiqishi mumkin — sheet'dagi kabi.

"Разница" doim 0 bo'lishi KAFOLATLANGAN: har bir GL yozuvi aynan bitta
katakka tushadi, ikki yoqlama yozuvda esa jami debet = jami kredit.
"""

import frappe
from frappe import _
from frappe.utils import flt, getdate

from jazira_app.jazira_app.report.pl_hisoboti.pl_hisoboti import build_period_list, _fk
from jazira_app.jazira_app.report.pl_obshi.pl_obshi import company_label, get_companies


def execute(filters=None):
	filters = frappe._dict(filters or {})
	period_list = build_period_list(filters)
	if not period_list:
		return [], []

	# Guruh (ildiz) kompaniyalar — masalan "Jazira" — hisobotga KIRMAYDI:
	# ular daraxt ildizi xolos, ulardagi adashib yozilgan ma'lumotlar
	# e'tiborga olinmaydi. Har kompaniya GL'i o'z ichida balanslangani
	# uchun РАЗНИЦА bunda ham 0 bo'lib qolaveradi.
	companies = get_companies()
	if not companies:
		frappe.throw(_("Ишчи компания топилмади"))

	data = compute(period_list, companies)
	return get_columns(period_list), build_rows(period_list, data)


def get_columns(period_list):
	cols = [{"fieldname": "label", "label": _("Кўрсаткич"), "fieldtype": "Data", "width": 320}]
	for p in period_list:
		cols.append({
			"fieldname": _fk(p["key"]),
			"label": str(p["to_date"]),  # balans — davr OXIRI holatiga
			"fieldtype": "Currency",
			"options": "currency",
			"width": 155,
		})
	return cols


# ─── Ma'lumot yig'ish ────────────────────────────────────────────────────────

def fetch_gl(max_date, companies):
	return frappe.db.sql(
		"""
		SELECT
			g.company,
			g.posting_date,
			a.root_type,
			IFNULL(a.account_type, '') AS account_type,
			TRIM(IFNULL(a.account_number, '')) AS account_number,
			IFNULL(g.party_type, '') AS party_type,
			IFNULL(g.party, '') AS party,
			SUM(g.debit - g.credit) AS net
		FROM `tabGL Entry` g
		INNER JOIN `tabAccount` a ON a.name = g.account
		WHERE g.is_cancelled = 0
		  AND g.company IN %(companies)s
		  AND g.posting_date <= %(max_date)s
		  AND g.voucher_type != 'Period Closing Voucher'
		GROUP BY g.company, g.posting_date, a.root_type, a.account_type,
				 a.account_number, g.party_type, g.party
		""",
		{"max_date": max_date, "companies": tuple(companies)},
		as_dict=True,
	)


def get_internal_parties():
	cust = dict(frappe.get_all(
		"Customer", filters={"is_internal_customer": 1},
		fields=["name", "represents_company"], as_list=True))
	sup = dict(frappe.get_all(
		"Supplier", filters={"is_internal_supplier": 1},
		fields=["name", "represents_company"], as_list=True))
	return cust, sup


DIVIDEND_NUMBERS = {"3200", "3201"}
FIXED_TYPES = {"Fixed Asset", "Accumulated Depreciation", "Capital Work in Progress"}


def compute(period_list, companies):
	"""Har ustun (davr oxiri) uchun barcha kataklarni yig'adi."""
	ends = [getdate(p["to_date"]) for p in period_list]
	starts = [getdate(p["from_date"]) for p in period_list]
	n = len(period_list)

	rows = fetch_gl(str(ends[-1]), companies)
	internal_cust, internal_sup = get_internal_parties()

	def zeros():
		return [0.0] * n

	static = {}       # (bucket, company) -> [col balans]
	party = {}        # (klass, label_key, company, party) -> [col balans]
	prior_profit = {}               # company -> [davr boshigacha foyda (kredit+)]
	cur_profit = {}                 # company -> [davr ichidagi foyda]

	def add(dct, key, idxs, val):
		arr = dct.setdefault(key, zeros())
		for i in idxs:
			arr[i] += val

	for r in rows:
		d = getdate(r.posting_date)
		cum_idx = [i for i in range(n) if d <= ends[i]]
		if not cum_idx and r.root_type not in ("Income", "Expense"):
			continue
		net = flt(r.net)

		# ── Foyda (P&L) — kapitalning "Накопленная прибыль" qismi ────────
		if r.root_type in ("Income", "Expense"):
			profit = -net  # kredit+ = foyda
			for i in range(n):
				if d < starts[i]:
					add(prior_profit, r.company, [i], profit)
				elif d <= ends[i]:
					add(cur_profit, r.company, [i], profit)
			continue

		# ── Balans schetlari ─────────────────────────────────────────────
		at = r.account_type
		if at in ("Receivable", "Payable"):
			# Kalit: (klass, ko'rinadigan yorliq kaliti, KITOB EGASI kompaniya,
			# party). Kompaniya alohida saqlanadi — har-kompaniya balans
			# hisoboti (Balance Calculation) shu kesimdan foydalanadi.
			if r.party_type == "Customer":
				rep = internal_cust.get(r.party)
				key = (("fil_ar", rep, r.company, r.party) if rep
					   else ("cust", r.company, r.company, r.party))
			elif r.party_type == "Supplier":
				rep = internal_sup.get(r.party)
				key = (("fil_ap", rep, r.company, r.party) if rep
					   else ("supp", "", r.company, r.party))
			elif r.party_type == "Employee":
				key = ("emp", r.company, r.company, r.party)
			elif r.party_type:
				key = ("other", r.company, r.company, r.party)
			else:
				key = ("nopar", r.company, r.company, at)
			add(party, key, cum_idx, net)
		elif at == "Stock":
			add(static, ("stock", r.company), cum_idx, net)
		elif at in ("Cash", "Bank"):
			add(static, ("cash", r.company), cum_idx, net)
		elif at in FIXED_TYPES:
			add(static, ("fixed", r.company), cum_idx, net)
		elif r.root_type == "Asset":
			add(static, ("other_asset", r.company), cum_idx, net)
		elif r.root_type == "Liability":
			add(static, ("other_liab", r.company), cum_idx, net)
		elif r.root_type == "Equity":
			bucket = "dividend" if r.account_number in DIVIDEND_NUMBERS else "equity"
			add(static, (bucket, r.company), cum_idx, net)

	return {
		"static": static,
		"party": party,
		"prior_profit": prior_profit,
		"cur_profit": cur_profit,
		"n": n,
	}


# ─── Qatorlar ────────────────────────────────────────────────────────────────

# Ҳар klass IKKALA томонда ҳам учраши mumkin: масалан ички таъминотчи
# (fil_ap) одатда кредитда, лекин филиал ортиқча тўлаган ойда дебетга
# ўтади — шунинг учун иккала луғат ҳам ТЎЛИҚ бўлиши шарт.
PARTY_AR_LABELS = {
	"cust": "Клиент",
	"emp": "Сотрудник",
	"other": "Прочие лицо",
	"supp": "Поставщик (аванслар)",
	"fil_ar": "Филиал",
	"fil_ap": "Филиал (аванс)",
	"nopar": "Бошқа (партиясиз)",
}
PARTY_AP_LABELS = {
	"supp": "Поставщик",
	"emp": "Сотрудник",
	"cust": "Клиент (аванслар)",
	"other": "Прочие лицо",
	"fil_ap": "Филиал",
	"fil_ar": "Филиал (аванс)",
	"nopar": "Бошқа (партиясиз)",
}


def build_rows(period_list, data):
	n = data["n"]
	fkeys = [_fk(p["key"]) for p in period_list]

	def vm(arr, flip=False):
		return {fk: (-v if flip else v) for fk, v in zip(fkeys, arr)}

	def mk(label, value_map, row_type="detail", indent=0, is_cost=False):
		r = {"label": label, "row_type": row_type, "indent": indent,
			 "indent_level": indent, "is_cost": 1 if is_cost else 0}
		r.update(value_map)
		return r

	def divider():
		r = {"label": "", "row_type": "divider", "indent": 0, "indent_level": 0}
		for fk in fkeys:
			r[fk] = None
		return r

	def all_zero(arr):
		return all(abs(flt(v)) < 0.5 for v in arr)

	def sum_arrays(arrs):
		out = [0.0] * n
		for a in arrs:
			for i in range(n):
				out[i] += a[i]
		return out

	static = data["static"]
	party = data["party"]

	# ── Partiyalarni ustun bo'yicha ISHORAGA qarab ikki tomonga ajratish ──
	# (klass, label_key) -> {"ar": [..debet qoldiq..], "ap": [..kredit..]}
	ar_lines, ap_lines = {}, {}
	for (klass, label_key, _company, _party_name), arr in party.items():
		ar = ar_lines.setdefault((klass, label_key), [0.0] * n)
		ap = ap_lines.setdefault((klass, label_key), [0.0] * n)
		for i in range(n):
			if arr[i] > 0:
				ar[i] += arr[i]
			elif arr[i] < 0:
				ap[i] += -arr[i]

	def line_label(side_labels, klass, label_key):
		base = side_labels.get(klass, klass)
		if klass in ("fil_ar", "fil_ap"):
			return f"{base} {company_label(label_key)}" if label_key else base
		if klass in ("supp", "nopar"):
			return base
		return f"{base} {company_label(label_key)}"

	def collect(side_lines, side_labels):
		items = []
		for (klass, label_key), arr in side_lines.items():
			if all_zero(arr):
				continue
			items.append((line_label(side_labels, klass, label_key), arr))
		items.sort(key=lambda x: -abs(x[1][-1]))
		return items

	ar_items = collect(ar_lines, PARTY_AR_LABELS)
	ap_items = collect(ap_lines, PARTY_AP_LABELS)

	def static_items(bucket, flip=False):
		items = []
		for (b, company), arr in static.items():
			if b != bucket or all_zero(arr):
				continue
			items.append((company_label(company), [(-v if flip else v) for v in arr]))
		items.sort(key=lambda x: -abs(x[1][-1]))
		return items

	stock_items = static_items("stock")
	cash_items = static_items("cash")
	fixed_items = static_items("fixed")
	oa_items = static_items("other_asset")
	ol_items = static_items("other_liab", flip=True)
	eq_items = static_items("equity", flip=True)
	div_items = static_items("dividend", flip=True)

	stock_t = sum_arrays([a for _l, a in stock_items])
	cash_t = sum_arrays([a for _l, a in cash_items])
	fixed_t = sum_arrays([a for _l, a in fixed_items])
	oa_t = sum_arrays([a for _l, a in oa_items])
	ar_t = sum_arrays([a for _l, a in ar_items])
	ap_t = sum_arrays([a for _l, a in ap_items])
	ol_t = sum_arrays([a for _l, a in ol_items])
	eq_t = sum_arrays([a for _l, a in eq_items])
	div_t = sum_arrays([a for _l, a in div_items])

	prior = sum_arrays(list(data["prior_profit"].values())) if data["prior_profit"] else [0.0] * n
	cur_items = sorted(
		((company_label(c), arr) for c, arr in data["cur_profit"].items()
		 if not all_zero(arr)),
		key=lambda x: -abs(x[1][-1]))
	cur_t = sum_arrays([a for _l, a in cur_items])

	assets_t = sum_arrays([stock_t, cash_t, fixed_t, oa_t, ar_t])
	kredit_t = sum_arrays([ap_t, ol_t])
	capital_t = sum_arrays([eq_t, div_t, prior, cur_t])
	passives_t = sum_arrays([kredit_t, capital_t])
	diff = [assets_t[i] - passives_t[i] for i in range(n)]
	working = [assets_t[i] - kredit_t[i] for i in range(n)]

	rows = []

	# ══ АКТИВЫ ═══════════════════════════════════════════════════════════
	rows.append(mk("АКТИВЫ", vm(assets_t), "root", 0))
	if not all_zero(fixed_t):
		rows.append(mk("Основные средства", vm(fixed_t), "sub", 1))
		for lb, arr in fixed_items:
			rows.append(mk(f"ОС {lb}", vm(arr), "detail", 2))

	rows.append(mk("Запасы", vm(stock_t), "sub", 1))
	for lb, arr in stock_items:
		rows.append(mk(f"Склад {lb}", vm(arr), "detail", 2))

	rows.append(mk("Денежные средства", vm(cash_t), "sub", 1))
	for lb, arr in cash_items:
		rows.append(mk(f"Касса {lb}", vm(arr), "detail", 2))

	rows.append(mk("Дебиторская задолженность", vm(ar_t), "sub", 1))
	for lb, arr in ar_items:
		rows.append(mk(lb, vm(arr), "detail", 2))

	if not all_zero(oa_t):
		rows.append(mk("Прочие активы (1910 ва бошқ.)", vm(oa_t), "sub", 1))
		for lb, arr in oa_items:
			rows.append(mk(f"Прочие {lb}", vm(arr), "detail", 2))

	rows.append(mk("ИТОГО АКТИВЫ", vm(assets_t), "result", 0))
	rows.append(divider())

	# ══ ПАССИВЫ ══════════════════════════════════════════════════════════
	rows.append(mk("ПАССИВЫ", vm(passives_t), "root", 0))

	rows.append(mk("Капитал", vm(capital_t), "sub", 1))
	for lb, arr in eq_items:
		rows.append(mk(f"Уставный ва бошқа капитал {lb}", vm(arr), "detail", 2))
	rows.append(mk("Накопл. прибыль — прошлых периодов", vm(prior), "detail", 2))
	for lb, arr in cur_items:
		rows.append(mk(f"Прибыль {lb} (давр ичида)", vm(arr), "detail", 2))
	for lb, arr in div_items:
		rows.append(mk(f"Дивиденды {lb}", vm(arr), "detail", 2))

	rows.append(mk("Кредиторская задолженность", vm(kredit_t), "sub", 1, is_cost=True))
	for lb, arr in ap_items:
		rows.append(mk(lb, vm(arr), "detail", 2, is_cost=True))
	for lb, arr in ol_items:
		rows.append(mk(f"Бошқа мажбурият {lb}", vm(arr), "detail", 2, is_cost=True))

	rows.append(mk("ИТОГО ПАССИВЫ", vm(passives_t), "result", 0))
	rows.append(mk("РАЗНИЦА (назорат)", vm(diff), "result", 0))
	rows.append(divider())
	rows.append(mk("Рабочий капитал (Активы − Кредиторка)", vm(working), "sub", 0))

	return rows
