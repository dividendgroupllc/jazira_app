# Copyright (c) 2026, Jazira App and contributors
# License: MIT

"""
Balance Calculation — ҲАР КОМПАНИЯ учун АЛОҲИДА баланс, кетма-кет bloklar.

Google Sheet'даги "Баланс" varag'ining ko'chirmasi: har kompaniya uchun
Активы (Запасы/Пул/Дебиторка) → Итого → Капитал → Кредиторка → Итого →
Разница. Ustunlar — davr OXIRI holatiga.

Dvigatel Balance Obshi bilan BITTA (compute o'sha yerdan olinadi) —
ikkala hisobot doim bir xil raqamni ko'rsatadi; bu yerda faqat
kompaniya kesimida chiqariladi.

"Разница" har kompaniyada 0 — kafolatlangan: har kompaniyaning GL'i
o'z ichida balanslangan (har hujjatda debet = kredit).
"""

import frappe
from frappe import _
from frappe.utils import flt

from jazira_app.jazira_app.report.pl_hisoboti.pl_hisoboti import build_period_list, _fk
from jazira_app.jazira_app.report.pl_obshi.pl_obshi import company_label, get_companies
from jazira_app.jazira_app.report.balance_obshi.balance_obshi import compute


def execute(filters=None):
	filters = frappe._dict(filters or {})
	period_list = build_period_list(filters)
	if not period_list:
		return [], []

	companies = get_companies()
	if not companies:
		frappe.throw(_("Ишчи компания топилмади"))

	data = compute(period_list, companies)
	return get_columns(period_list), build_rows(period_list, companies, data)


def get_columns(period_list):
	cols = [{"fieldname": "label", "label": _("Кўрсаткич"), "fieldtype": "Data", "width": 300}]
	for p in period_list:
		cols.append({
			"fieldname": _fk(p["key"]),
			"label": str(p["to_date"]),  # balans — davr OXIRI holatiga
			"fieldtype": "Currency",
			"options": "currency",
			"width": 155,
		})
	return cols


AR_LABELS = {
	"cust": "Клиент",
	"emp": "Сотрудник",
	"other": "Прочие",
	"supp": "Поставщик (аванс)",
	"fil_ar": "Филиал",
	"fil_ap": "Филиал (аванс)",
	"nopar": "Бошқа (партиясиз)",
}
AP_LABELS = {
	"supp": "Поставщик",
	"emp": "Сотрудник",
	"cust": "Клиент (аванс)",
	"other": "Прочие",
	"fil_ap": "Филиал",
	"fil_ar": "Филиал (аванс)",
	"nopar": "Бошқа (партиясиз)",
}


def build_rows(period_list, companies, data):
	n = data["n"]
	fkeys = [_fk(p["key"]) for p in period_list]
	static = data["static"]
	party = data["party"]

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

	def zeros():
		return [0.0] * n

	def sum_arrays(arrs):
		out = zeros()
		for a in arrs:
			for i in range(n):
				out[i] += a[i]
		return out

	def line_label(labels, klass, label_key):
		base = labels.get(klass, klass)
		if klass in ("fil_ar", "fil_ap"):
			return f"{base} {company_label(label_key)}" if label_key else base
		return base

	rows = []

	for co in companies:
		# ── Shu kompaniyaning partiya qoldiqlari: ishoraga qarab ikki tomon ──
		ar_lines, ap_lines = {}, {}
		for (klass, label_key, company, _party), arr in party.items():
			if company != co:
				continue
			line = (klass, label_key)
			ar = ar_lines.setdefault(line, zeros())
			ap = ap_lines.setdefault(line, zeros())
			for i in range(n):
				if arr[i] > 0:
					ar[i] += arr[i]
				elif arr[i] < 0:
					ap[i] += -arr[i]

		def collect(side_lines, labels):
			items = [(line_label(labels, k, lk), a)
					 for (k, lk), a in side_lines.items() if not all_zero(a)]
			items.sort(key=lambda x: -abs(x[1][-1]))
			return items

		ar_items = collect(ar_lines, AR_LABELS)
		ap_items = collect(ap_lines, AP_LABELS)

		def stat(bucket, flip=False):
			arr = static.get((bucket, co))
			if not arr:
				return zeros()
			return [(-v if flip else v) for v in arr]

		stock = stat("stock")
		cash = stat("cash")
		fixed = stat("fixed")
		other_asset = stat("other_asset")
		other_liab = stat("other_liab", flip=True)
		equity = stat("equity", flip=True)
		dividend = stat("dividend", flip=True)

		prior = data["prior_profit"].get(co, zeros())
		cur = data["cur_profit"].get(co, zeros())

		ar_t = sum_arrays([a for _l, a in ar_items])
		ap_t = sum_arrays([a for _l, a in ap_items])
		kredit_t = sum_arrays([ap_t, other_liab])
		assets_t = sum_arrays([stock, cash, fixed, other_asset, ar_t])
		capital_t = sum_arrays([equity, dividend, prior, cur])
		passives_t = sum_arrays([kredit_t, capital_t])
		diff = [assets_t[i] - passives_t[i] for i in range(n)]

		# ── Blok qatorlari (sheet tartibida) ─────────────────────────────
		rows.append(mk(f"БАЛАНС {company_label(co)}", vm(assets_t), "root", 0))

		if not all_zero(fixed):
			rows.append(mk("Основные средства", vm(fixed), "sub", 1))
		rows.append(mk("Запасы (Продукция)", vm(stock), "sub", 1))
		rows.append(mk("Денежные средства (все счета)", vm(cash), "sub", 1))

		rows.append(mk("Дебиторская задолженность", vm(ar_t), "sub", 1))
		for lb, arr in ar_items:
			rows.append(mk(lb, vm(arr), "detail", 2))
		if not all_zero(other_asset):
			rows.append(mk("Прочие активы (1910 ва бошқ.)", vm(other_asset), "sub", 1))

		rows.append(mk("Итого активы", vm(assets_t), "result", 1))

		rows.append(mk("Капитал", vm(capital_t), "sub", 1))
		if not all_zero(equity):
			rows.append(mk("Уставный ва бошқа капитал", vm(equity), "detail", 2))
		rows.append(mk("Накопл. прибыль — прошлых периодов", vm(prior), "detail", 2))
		rows.append(mk("— текущих периодов", vm(cur), "detail", 2))
		# Dividend qatori DOIM ko'rinadi — 0 bo'lsa ham (egalar talabi,
		# PL Calculation'dagi bilan bir xil qoida).
		rows.append(mk("Дивиденды", vm(dividend), "detail", 2))

		rows.append(mk("Кредиторская задолженность", vm(kredit_t), "sub", 1, is_cost=True))
		for lb, arr in ap_items:
			rows.append(mk(lb, vm(arr), "detail", 2, is_cost=True))
		if not all_zero(other_liab):
			rows.append(mk("Бошқа мажбурият", vm(other_liab), "detail", 2, is_cost=True))

		rows.append(mk("Итого пассивы", vm(passives_t), "result", 1))
		rows.append(mk(f"РАЗНИЦА (назорат) {company_label(co)}", vm(diff), "result", 1))
		rows.append(divider())

	return rows
