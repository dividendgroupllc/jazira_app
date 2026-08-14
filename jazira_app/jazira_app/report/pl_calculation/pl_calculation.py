# Copyright (c) 2026, Jazira App and contributors
# For license information, please see license.txt

"""
PL Calculation — «Отчёт для расчёта общий».

Иккита қисмдан иборат, иккаласи ҳам БИТТА саҳифада (Бўлим фильтри билан
ажратиб олиш мумкин):

1) ФИЛИАЛЛАР P&L — ҳар бир компания учун тўлиқ фойда-зарар ҳисоботи, кетма-кет:
       Выручка
       Себестоимость            (яйилади: хом ашё / омбор / касса / брак)
       Маржинальная прибыль     + рентабельность %
       Операционные расходы     (яйилади: счётма-счёт)
       Операционная прибыль     + рентабельность %
       Адм Расход               (яйилади: счётма-счёт)
       Чистая прибыль           + рентабельность %

   Компания фильтри ЙЎҚ — барча филиал битта саҳифада чиқади.

2) ШЕРИКЛАР ҲИСОБИ — соф фойданинг эгалар ўртасида тақсимланиши ва
   ҳар бир эга бўйича ҳисоб-китоб:

       қолдиқ = улуш + ойлик − олинган пул − дивиденд

   "Ойлик" қўшилади, чунки у харажат сифатида фойдадан аллақачон
   айирилган (яъни иккала шерик 50/50 кўтарган), лекин у аслида ўша
   эганинг ўзига тегишли — шунинг учун унинг ҳисобига қайтарилади.
   Формула Google Sheet билан рақамма-рақам текширилди (2025-июль:
   156 527 859 + 306 250 000 − 332 070 000 = 130 707 859 ✓).

   "Тақ. фойда" — ўсиб борувчи (нарастающий) қолдиқ: ҳар давр қолдиғи
   олдингиларига қўшилиб боради.

Ҳисоблаш дигатели (GL ўқиш, счёт тоифалаш, эгалар маълумоти) PL Obshi
ҳисоботидан олинади — иккала ҳисобот бир хил рақамни кўрсатиши учун
манба битта бўлиши шарт.
"""

import frappe
from frappe import _
from frappe.utils import add_days, flt, getdate

from jazira_app.jazira_app.report.pl_hisoboti.pl_hisoboti import build_period_list, _fk
from jazira_app.jazira_app.report.pl_obshi.pl_obshi import (
	OWNERS,
	aggregate,
	company_label,
	fetch_dividends,
	fetch_gl,
	fetch_owner_draws,
	get_companies,
	get_shares,
	_account_rows,
	_co_adm,
	_co_cogs,
	_co_marginal,
	_co_op,
	_co_other,
	_co_profit,
)

SECTION_ALL = "Ҳаммаси"
SECTION_BRANCHES = "Филиаллар P&L"
SECTION_PARTNERS = "Шериклар ҳисоби"


# ─── Entry point ─────────────────────────────────────────────────────────────

def execute(filters=None):
	filters = frappe._dict(filters or {})

	period_list = build_period_list(filters)
	if not period_list:
		return [], []

	from_date = str(period_list[0]["from_date"])
	to_date = str(period_list[-1]["to_date"])

	companies = get_companies()
	if not companies:
		frappe.throw(_("Ишчи компания топилмади"))

	section = filters.get("section") or SECTION_ALL

	pdata = aggregate(
		period_list,
		companies,
		fetch_gl(companies, from_date, to_date),
		[],  # ички айланма чиқарилмайди — бу ҳисобот ҳар компанияни АЛОҲИДА кўрсатади
		fetch_dividends(companies, from_date, to_date),
		fetch_owner_draws(companies, from_date, to_date),
	)

	opening = get_opening_balances(companies, from_date)

	return get_columns(period_list), build_rows(
		period_list, companies, pdata, section, opening)


def get_opening_balances(companies, from_date):
	"""Ҳисобот бошлангунга ҚАДАР тўпланган қолдиқ (эга бўйича).

	"Тақ. фойда" — бизнес бошидан бери ўсиб борувчи қолдиқ. Агар уни фақат
	фильтрдаги биринчи ойдан бошласак, масалан фақат августни танлаганда
	олдинги ойлар унутилиб, рақам нотўғри чиқарди. Шунинг учун from_date'гача
	бўлган БАРЧА давр бир "очилиш" даври сифатида ҳисобланиб, ўсиш ўшандан
	бошланади."""
	opening_to = add_days(getdate(from_date), -1)
	opening_from = getdate("1900-01-01")
	if opening_to < opening_from:
		return {o["key"]: 0 for o in OWNERS}

	period = [{
		"key": "opening",
		"label": "opening",
		"from_date": opening_from,
		"to_date": opening_to,
	}]
	f, t = str(opening_from), str(opening_to)

	pdata = aggregate(
		period,
		companies,
		fetch_gl(companies, f, t),
		[],
		fetch_dividends(companies, f, t),
		fetch_owner_draws(companies, f, t),
	)
	d = pdata["opening"]
	return {o["key"]: owner_balance(d, o, companies) for o in OWNERS}


def get_columns(period_list):
	cols = [{"fieldname": "label", "label": _("Кўрсаткич"), "fieldtype": "Data", "width": 340}]
	for p in period_list:
		cols.append({
			"fieldname": _fk(p["key"]),
			"label": p["label"],
			"fieldtype": "Currency",
			"options": "currency",
			"width": 150,
		})
	return cols


# ─── Шериклар ҳисоби формулалари ─────────────────────────────────────────────

def owner_branch_profit(d, company, owner_key):
	"""Эганинг шу филиалдаги соф фойда улуши (Смарт 100% Акмал, қолгани 50/50;
	зарар ҳам худди шундай бўлинади)."""
	return _co_profit(d["companies"][company]) * get_shares(company).get(owner_key, 0)


def owner_total_profit(d, owner_key, companies):
	return sum(owner_branch_profit(d, co, owner_key) for co in companies)


def owner_balance(d, owner, companies):
	"""қолдиқ = улуш + ойлик − олинган пул − дивиденд"""
	return (
		owner_total_profit(d, owner["key"], companies)
		+ flt(d["owner_salary"].get(owner["key"], 0))
		- flt(d["owner_taken"].get(owner["key"], 0))
		- flt(d["dividends"].get(owner["account"], 0))
	)


# ─── Row builder ─────────────────────────────────────────────────────────────

def build_rows(period_list, companies, pdata, section, opening=None):
	fkeys = [_fk(p["key"]) for p in period_list]

	def per_period(fn):
		return {_fk(p["key"]): fn(pdata[p["key"]]) for p in period_list}

	def mk(label, value_map, row_type="detail", indent=0, is_cost=False):
		r = {
			"label": label,
			"row_type": row_type,
			"indent": indent,
			"indent_level": indent,
			"is_percent": 1 if row_type == "percent" else 0,
			"is_cost": 1 if is_cost else 0,
		}
		r.update(value_map)
		return r

	def divider():
		r = {"label": "", "row_type": "divider", "indent": 0, "indent_level": 0}
		for fk in fkeys:
			r[fk] = None
		return r

	def all_zero(value_map):
		return all(not flt(v) for v in value_map.values())

	def pct(numer, denom):
		return per_period(lambda d: (numer(d) / denom(d) * 100) if denom(d) else 0)

	rows = []

	# ══ 1-ҚИСМ: ҲАР БИР ФИЛИАЛНИНГ ТЎЛИҚ P&L'и ═══════════════════════════════
	if section in (SECTION_ALL, SECTION_BRANCHES):
		for co in companies:
			def cd_of(d, c=co):
				return d["companies"][c]

			revenue = per_period(lambda d, c=co: cd_of(d, c)["revenue"])
			cogs = per_period(lambda d, c=co: _co_cogs(cd_of(d, c)))
			marginal = per_period(lambda d, c=co: _co_marginal(cd_of(d, c)))
			opex = per_period(lambda d, c=co: _co_op(cd_of(d, c)) + _co_other(cd_of(d, c)))
			adm = per_period(lambda d, c=co: _co_adm(cd_of(d, c)))
			op_profit = per_period(
				lambda d, c=co: _co_marginal(cd_of(d, c)) - _co_op(cd_of(d, c)) - _co_other(cd_of(d, c)))
			net = per_period(lambda d, c=co: _co_profit(cd_of(d, c)))

			rows.append(mk(f"Отчет о прибылях и убытках {company_label(co)}", {}, "root", 0))
			rows.append(mk("Выручка от реализации продукции", revenue, "sub", 1))

			# ── Себестоимость (таркиби билан) ────────────────────────────────
			rows.append(mk("Себестоимость", cogs, "sub", 1, is_cost=True))
			for bucket, blabel in [
				("cogs_raw", "Сырьевая себестоимость"),
				("cogs_adj", "Убыток от себестоимости"),
				("kassa", "Foyda/Zarar Kassa"),
				("brak", "Брак"),
			]:
				bvm = per_period(lambda d, c=co, b=bucket: flt(cd_of(d, c)[b]))
				if all_zero(bvm):
					continue
				rows.append(mk(blabel, bvm, "detail", 2, is_cost=True))

			rows.append(mk("Маржинальная прибыль", marginal, "result", 1))
			rows.append(mk(
				"Рентабельность по маржинальному доходу, %",
				pct(lambda d, c=co: _co_marginal(cd_of(d, c)),
					lambda d, c=co: cd_of(d, c)["revenue"]),
				"percent", 2,
			))

			# ── Операционные расходы (счётма-счёт) ───────────────────────────
			rows.append(mk("Операционные расходы", opex, "sub", 1, is_cost=True))
			for acc_label, acc_vm in _account_rows(period_list, pdata, "op", [co]):
				rows.append(mk(acc_label, acc_vm, "detail", 2, is_cost=True))
			for acc_label, acc_vm in _account_rows(period_list, pdata, "other", [co]):
				rows.append(mk(acc_label, acc_vm, "detail", 2, is_cost=True))

			rows.append(mk("Операционная прибыль", op_profit, "result", 1))
			rows.append(mk(
				"Рентабельность по операционной прибыли, %",
				pct(lambda d, c=co: (_co_marginal(cd_of(d, c)) - _co_op(cd_of(d, c))
									 - _co_other(cd_of(d, c))),
					lambda d, c=co: cd_of(d, c)["revenue"]),
				"percent", 2,
			))

			# ── Адм Расход (счётма-счёт) ─────────────────────────────────────
			rows.append(mk("Адм Расход", adm, "sub", 1, is_cost=True))
			for acc_label, acc_vm in _account_rows(period_list, pdata, "adm", [co]):
				rows.append(mk(acc_label, acc_vm, "detail", 2, is_cost=True))

			rows.append(mk("Чистая прибыль", net, "result", 1))
			rows.append(mk(
				"Рентабельность по чистой прибыли, %",
				pct(lambda d, c=co: _co_profit(cd_of(d, c)),
					lambda d, c=co: cd_of(d, c)["revenue"]),
				"percent", 2,
			))
			rows.append(divider())

	# ══ 2-ҚИСМ: ШЕРИКЛАР ҲИСОБИ ══════════════════════════════════════════════
	if section in (SECTION_ALL, SECTION_PARTNERS):
		total_net = per_period(
			lambda d: sum(_co_profit(cd) for cd in d["companies"].values()))

		# ── Foyda Filiallar ──────────────────────────────────────────────────
		rows.append(mk("Foyda Filiallar", total_net, "root", 0))
		for co in companies:
			vm = per_period(lambda d, c=co: _co_profit(d["companies"][c]))
			if all_zero(vm):
				continue
			rows.append(mk(f"Foyda {company_label(co)}", vm, "detail", 1))
		rows.append(mk(
			"Рентабельность, %",
			pct(lambda d: sum(_co_profit(cd) for cd in d["companies"].values()),
				lambda d: sum(cd["revenue"] for cd in d["companies"].values())),
			"percent", 1,
		))

		# ── Sheriklar Ulushi ─────────────────────────────────────────────────
		rows.append(mk("Sheriklar Ulushi", total_net, "root", 0))
		for co in companies:
			for owner in OWNERS:
				vm = per_period(lambda d, c=co, k=owner["key"]: owner_branch_profit(d, c, k))
				if all_zero(vm):
					continue
				rows.append(mk(
					f"Foyda {company_label(co)} {owner['label']} Aka", vm, "detail", 1))

		# ── Ҳар бир эга бўйича ҳисоб-китоб ───────────────────────────────────
		rows.append(divider())
		for owner in OWNERS:
			name = f"{owner['label']} Aka"
			share = per_period(lambda d, k=owner["key"]: owner_total_profit(d, k, companies))
			salary = per_period(lambda d, k=owner["key"]: flt(d["owner_salary"].get(k, 0)))
			taken = per_period(lambda d, k=owner["key"]: -flt(d["owner_taken"].get(k, 0)))
			dividend = per_period(lambda d, a=owner["account"]: -flt(d["dividends"].get(a, 0)))
			balance = per_period(lambda d, o=owner: owner_balance(d, o, companies))

			rows.append(mk(f"{name} — ҳисоб-китоб", balance, "root", 0))
			rows.append(mk(f"Jami Foyda {name}", share, "sub", 1))
			if not all_zero(salary):
				rows.append(mk(f"{name} Sheff oylik", salary, "detail", 1))
			if not all_zero(taken):
				rows.append(mk(f"{name} Sheff olingan pul", taken, "detail", 1, is_cost=True))
			if not all_zero(dividend):
				rows.append(mk(f"Dividend {name}", dividend, "detail", 1, is_cost=True))
			rows.append(mk(f"{name} Sheff qoldiq", balance, "result", 1))

		# ── Тақ. фойда (ўсиб борувчи қолдиқ) ─────────────────────────────────
		rows.append(divider())
		opening = opening or {}
		cum_total = {}
		cum_rows = []
		opening_vm = {}
		for owner in OWNERS:
			# Ҳисобот бошлангунга қадар тўпланган қолдиқдан бошланади.
			running = flt(opening.get(owner["key"], 0))
			opening_vm[owner["key"]] = running
			vm = {}
			for p in period_list:
				running += owner_balance(pdata[p["key"]], owner, companies)
				vm[_fk(p["key"])] = running
				cum_total[_fk(p["key"])] = cum_total.get(_fk(p["key"]), 0) + running
			cum_rows.append(mk(f"Taq. Foyda {owner['label']} Aka", vm, "detail", 1))
		rows.append(mk("Taq. Foyda (ўсиб борувчи қолдиқ)", cum_total, "root", 0))
		rows.extend(cum_rows)

		# Очилиш қолдиғи бор бўлса — қаердан бошланганини кўрсатиб қўямиз,
		# акс ҳолда рақам "осмондан тушган"дек кўринарди.
		if any(round(flt(v)) for v in opening_vm.values()):
			first_fk = _fk(period_list[0]["key"])
			for owner in OWNERS:
				val = flt(opening_vm[owner["key"]])
				if not round(val):
					continue
				rows.append(mk(
					f"    ундан: {period_list[0]['label']} гача тўпланган — {owner['label']} Aka",
					{fk: (val if fk == first_fk else None) for fk in fkeys},
					"detail", 2,
				))

	return rows
