# Copyright (c) 2026, Jazira App and contributors
# For license information, please see license.txt

"""
PL Obshi — Jazira guruhi bo'yicha UMUMIY (konsolidatsiyalangan) P&L.

"PL Hisoboti" bitta kompaniyani ko'rsatadi; bu hisobot esa barcha ishchi
kompaniyalarni BITTA korxona sifatida birlashtiradi va har qatorni kompaniya
kesimida yoyish imkonini beradi.

Ichki айланмани чиқариб ташлаш (elimination)
────────────────────────────────────────────
Sklad tovarni filiallarga sotadi — bu Sklad uchun Выручка, filial uchun
Себестоимость. Guruh darajasida bu pul tashqariga chiqmagan, faqat
"чўнтакдан чўнтакка" o'tgan. Jazira'da bu juda katta: masalan 2026-iyunda
Skladning 692 mln даромадининг 667 млн'и (96%) — филиалларга сотув.

Shuning uchun ichki sotuv summasi HAM даромаддан, HAM таннархдан бир хил
миқдорда чиқариб ташланади:

    Даромад  = Σ(барча компания даромади) − ички сотув
    Таннарх  = Σ(барча компания таннархи)  − ички сотув

Bir xil miqdor ikkala tomondan chiqarilgani uchun МАРЖИНАЛ ФОЙДА o'zgarmaydi
va u ayni paytda har bir kompaniya marjinal foydasining yig'indisiga teng
bo'lib qoladi — ya'ni tekshirish oson. (Yagona nazariy noaniqlik — ой охирида
филиал омборида ётиб қолган, ҳали сотилмаган товардаги ички фойда; уни
чиқариш учун ҳар бир қолдиқ товарнинг ички устамасини ҳисоблаш керак,
бу алоҳида масала.)

Ма'мурий (Адм, 52002) харажатлар
────────────────────────────────
Jazira Expense Allocation Skladning ma'muriy xarajatini filiallarga
tarqatadi va SHU BILAN BIRGA Sklad tomonidan yopiladi (reversal). Shuning
uchun barcha kompaniyalarning 52002 yig'indisi — aynan bir marta hisoblangan
umumiy ma'muriy xarajat (икки марта саналмайди). Tekshirildi: 2026-iyun
23 759 839 + 91 303 245 + 57 312 700 = 172 375 784 = ойлик ҳовуз.
"""

import frappe
from frappe import _
from frappe.utils import flt

from jazira_app.jazira_app.report.pl_hisoboti.pl_hisoboti import (
	build_period_list,
	_fk,
	_period_key,
)


# Hisobotdagi kompaniya tartibi va ko'rinadigan nomi. Ro'yxatda yo'q
# kompaniyalar oxiriga alifbo tartibida qo'shiladi (yangi filial ochilsa
# kod o'zgartirmasdan chiqaveradi).
COMPANY_ORDER = ["Jazira Smart", "Jazira Saripul", "Jazira Xalq Banki", "Jazira Sklad"]
COMPANY_LABELS = {
	"Jazira Smart": "Смарт",
	"Jazira Saripul": "Сарипул",
	"Jazira Xalq Banki": "Халк Банки",
	"Jazira Sklad": "База (Склад)",
}

DIVIDEND_ACCOUNTS = {"3200": "Дивиденд Акмал", "3201": "Дивиденд Элёр"}

OP_GROUP = "52001"
ADM_GROUP = "52002"
INDIRECT_GROUP = "5200"


# ─── Себестоимость таркиби ───────────────────────────────────────────────────
#
# Таннарх 4 та таркибий қисмга ажратиб кўрсатилади:
#
#   Сырьевая себестоимость   — account_type "Cost of Goods Sold" (5111).
#                              Сотилган товарнинг хом ашё таннархи; Sales
#                              Invoice ва Purchase Invoice'дан келади.
#   Убыток от себестоимости  — account_type "Stock Adjustment" (5119).
#                              Омбор тафовути; Stock Entry ва Stock
#                              Reconciliation'дан келади.
#   Foyda/Zarar Kassa        — филиал кассасининг фойда-зарар фарқи
#                              (5246 Smart Foydasi, 5248 Saripul Foydasi,
#                              5249 Xalq Banki Foydasi, 5213 Kassa Farq).
#   Brak                     — яроқсиз/нобуд товар.
#
# Охирги иккитаси харажат счётлари орасида турибди, лекин моҳияти бўйича
# таннарх. Шунинг учун улар Себестоимость ичига олинади ВА операцион
# харажатлардан чиқарилади — акс ҳолда икки марта саналиб, маржинал фойда
# бузилар эди.
#
# ДИҚҚАТ: бу счётлар ҳар хил гуруҳда туриши мумкин. Масалан жонли базада
# "5246/5248/5249 ... Foydasi" — 52001 остида, "5213 Kassa Farq" эса
# "5200 Indirect Expenses" остида. Шунинг учун тоифалаш ота-гуруҳга
# БОҒЛАНМАГАН: счёт рақами ёки номи бўйича топилади.
#
# Эслатма: "Brak" счёти ҳозирча счётлар режасида ЙЎҚ. Яратилса (номида
# "brak"/"брак" бўлса) қатор ўзи пайдо бўлади, кодга тегиш шарт эмас.
KASSA_PL_ACCOUNT_NUMBERS = {"5213", "5246", "5248", "5249"}
KASSA_PL_NAME_PATTERNS = ("foydasi", "kassa farq", "kassa farqi")
BRAK_NAME_PATTERNS = ("brak", "брак")

# ── БРАК қаердан олинади ─────────────────────────────────────────────────────
#
# Жазирада брак (нобуд товар) АЛОҲИДА счёт ёки ҳужжат тури билан эмас,
# оддий Stock Entry / "Material Issue" орқали ҳисобдан чиқарилади ва
# 5119 Stock Adjustment'га тушади.
#
# Material Issue ичида бракни бошқа нарсадан ажратадиган белги ЙЎҚ:
# изоҳ (remarks) 206 ҳужжатнинг ҳаммасида бўш, омбор битта, Item Group эса
# аралаш (Сырьё ичида ҳам помидор, ҳам қўлқоп/латта/ёқилғи бор). Шунинг
# учун Material Issue'нинг ҲАММАСИ брак деб олинади — у ҳар ҳолда даромад
# келтирмасдан ҳисобдан чиққан товар.
#
# Келажакда алоҳида "Brak" номли Stock Entry Type очилса, у ҳам шу қаторга
# тушади (adj_kind = 'brak').
BRAK_ADJ_KINDS = {"brak", "writeoff"}

# "Убыток от себестоимости" (5119) ичида БРАКДАН ташқари қолган сабаблар.
ADJ_KIND_LABELS = [
	("recon", "инвентаризация фарқи (Stock Reconciliation)"),
	("mfg", "ишлаб чиқариш фарқи (Manufacture)"),
	("other", "бошқа омбор тафовути"),
]


def _classify_cost_bucket(account_number, account_name):
	"""Счёт аслида таннарх таркибими? Ҳа бўлса — қайси қисми (kassa/brak).

	Ота-гуруҳдан қатъи назар ишлайди — счёт 52001'да ҳам, 5200'да ҳам
	турган бўлиши мумкин."""
	name = (account_name or "").strip().lower()
	if any(p in name for p in BRAK_NAME_PATTERNS):
		return "brak"
	if account_number in KASSA_PL_ACCOUNT_NUMBERS:
		return "kassa"
	if any(p in name for p in KASSA_PL_NAME_PATTERNS):
		return "kassa"
	return None


# ─── Эгалар (дивиденд оладиганлар) ───────────────────────────────────────────
#
# Ҳақиқий дивиденд йилда бир марта 3200/3201 счётларидан тўланади. Лекин йил
# давомида ҳар иккала эга пулни Employee сифатида (Payment Entry, наqд касса)
# олиб туради — бу аслида дивиденд АВАНСИ. Шунинг учун ҳисобот:
#   улуш  −  йил давомида олингани  =  қолдиқ
# кўринишида ҳисоблайди.
#
# Тақсимот қоидаси (эгалар томонидан белгиланган):
#   Смарт      — 100% Акмал
#   қолганлари — 50/50 (фойда ҳам, ЗАРАР ҳам)
OWNERS = [
	{"key": "akmal", "label": "Акмал", "account": "3200", "employee": "Akmal aka shef"},
	{"key": "elyor", "label": "Элёр", "account": "3201", "employee": "Elyor Aka Sheff"},
]
COMPANY_SHARES = {
	"Jazira Smart": {"akmal": 1.0, "elyor": 0.0},
}
DEFAULT_SHARES = {"akmal": 0.5, "elyor": 0.5}


def get_shares(company):
	return COMPANY_SHARES.get(company, DEFAULT_SHARES)


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

	eliminate = filters.get("eliminate_internal")
	eliminate = 1 if eliminate in (None, "") else int(eliminate)

	gl_rows = fetch_gl(companies, from_date, to_date)
	internal_rows = fetch_internal_sales(companies, from_date, to_date) if eliminate else []
	dividend_rows = fetch_dividends(companies, from_date, to_date)
	owner_rows = fetch_owner_draws(companies, from_date, to_date)

	pdata = aggregate(period_list, companies, gl_rows, internal_rows, dividend_rows, owner_rows)

	columns = get_columns(period_list)
	data = build_rows(period_list, companies, pdata, eliminate)

	return columns, data


def get_companies():
	"""Barcha ishchi (guruh bo'lmagan) kompaniyalar, hisobot tartibida.

	Bu UMUMIY (консолидация) hisobot — kompaniya tanlash yo'q, doim to'liq
	guruh ko'rsatiladi. Yangi filial ochilsa o'zi qo'shilib chiqadi."""
	all_companies = frappe.get_all(
		"Company", filters={"is_group": 0}, pluck="name", order_by="name"
	)
	ordered = [c for c in COMPANY_ORDER if c in all_companies]
	ordered += sorted(c for c in all_companies if c not in ordered)
	return ordered


def company_label(company):
	if company in COMPANY_LABELS:
		return COMPANY_LABELS[company]
	short = company.replace("Jazira", "").strip()
	return short or company


# ─── Data fetching ────────────────────────────────────────────────────────────

def fetch_gl(companies, from_date, to_date):
	"""Barcha kompaniyalarning Income/Expense GL harakati, hisob va ota-hisob
	raqami bilan birga (toifalarga ajratish shu raqamlar asosida)."""
	return frappe.db.sql(
		"""
		SELECT
			gle.company,
			gle.posting_date,
			acc.account_name,
			TRIM(IFNULL(acc.account_number, '')) AS account_number,
			TRIM(IFNULL(parent_acc.account_number, '')) AS parent_number,
			acc.root_type,
			acc.account_type,
			CASE
				WHEN acc.account_type != 'Stock Adjustment' THEN ''
				WHEN LOWER(IFNULL(se.stock_entry_type, '')) LIKE '%%brak%%'
				  OR LOWER(IFNULL(se.stock_entry_type, '')) LIKE '%%брак%%' THEN 'brak'
				WHEN gle.voucher_type = 'Stock Reconciliation' THEN 'recon'
				WHEN se.purpose = 'Material Issue' THEN 'writeoff'
				WHEN se.purpose = 'Manufacture' THEN 'mfg'
				ELSE 'other'
			END AS adj_kind,
			CASE WHEN IFNULL(alloc_je.custom_jazira_expense_allocation, '') != ''
				THEN 1 ELSE 0 END AS is_allocation,
			SUM(gle.debit) AS debit,
			SUM(gle.credit) AS credit
		FROM `tabGL Entry` gle
		JOIN `tabAccount` acc ON acc.name = gle.account
		LEFT JOIN `tabAccount` parent_acc ON parent_acc.name = acc.parent_account
		LEFT JOIN `tabStock Entry` se
			ON se.name = gle.voucher_no AND gle.voucher_type = 'Stock Entry'
		LEFT JOIN `tabJournal Entry` alloc_je
			ON alloc_je.name = gle.voucher_no AND gle.voucher_type = 'Journal Entry'
		WHERE gle.company IN %(companies)s
		  AND gle.is_cancelled = 0
		  AND gle.posting_date BETWEEN %(from_date)s AND %(to_date)s
		  AND gle.voucher_type != 'Period Closing Voucher'
		  AND acc.root_type IN ('Income', 'Expense')
		GROUP BY gle.company, gle.posting_date, gle.account, adj_kind, is_allocation
		""",
		{"companies": tuple(companies), "from_date": from_date, "to_date": to_date},
		as_dict=True,
	)


def fetch_internal_sales(companies, from_date, to_date):
	"""Guruh ichidagi sotuv — ichki mijozga yozilgan Sales Invoice'ning
	daromad qatorlari. Har ikkala tomoni ham guruh ichida bo'lishi shart."""
	return frappe.db.sql(
		"""
		SELECT gle.posting_date, SUM(gle.credit - gle.debit) AS amount
		FROM `tabGL Entry` gle
		JOIN `tabAccount` acc ON acc.name = gle.account
		JOIN `tabSales Invoice` si ON si.name = gle.voucher_no
		JOIN `tabCustomer` cust ON cust.name = si.customer
		WHERE gle.voucher_type = 'Sales Invoice'
		  AND gle.company IN %(companies)s
		  AND gle.is_cancelled = 0
		  -- Бекор қилинган ҳужжатнинг тирик қолиб кетган GL қаторлари
		  -- элиминацияни шишириб, таннархни камайтириб юборарди
		  -- (ACC-SINV-2026-00046-1: 6 305 876 сўм).
		  AND si.docstatus = 1
		  AND gle.posting_date BETWEEN %(from_date)s AND %(to_date)s
		  AND acc.root_type = 'Income'
		  AND cust.is_internal_customer = 1
		  AND cust.represents_company IN %(companies)s
		GROUP BY gle.posting_date
		""",
		{"companies": tuple(companies), "from_date": from_date, "to_date": to_date},
		as_dict=True,
	)


def fetch_owner_draws(companies, from_date, to_date):
	"""Эгаларнинг Employee сифатидаги ҳаракати.

	debit  — наqд олгани (дивиденд аванси)
	credit — "маош" ҳисобланиши (5201 Ish haqqi -> 52002 Адм га тушади)

	credit тарафи керак, чунки у ҳозир ХАРАЖАТ сифатида турибди ва Expense
	Allocation орқали филиалларга тарқаляпти. Тақсимланадиган фойдани
	ҳисоблашда уни харажатдан қайтариб қўшиш керак — акс ҳолда эгалар ўз
	олган пули ҳисобига ўз дивидендини камайтириб юборади.
	"""
	employees = [o["employee"] for o in OWNERS]
	return frappe.db.sql(
		"""
		SELECT gle.company, gle.party, gle.posting_date,
			   SUM(gle.debit) AS taken, SUM(gle.credit) AS accrued
		FROM `tabGL Entry` gle
		WHERE gle.party_type = 'Employee'
		  AND gle.party IN %(employees)s
		  AND gle.company IN %(companies)s
		  AND gle.is_cancelled = 0
		  AND gle.posting_date BETWEEN %(from_date)s AND %(to_date)s
		GROUP BY gle.company, gle.party, gle.posting_date
		""",
		{
			"employees": tuple(employees),
			"companies": tuple(companies),
			"from_date": from_date,
			"to_date": to_date,
		},
		as_dict=True,
	)


def fetch_dividends(companies, from_date, to_date):
	"""Divident hisoblari (3200/3201) — Equity, shuning uchun to'lov debet
	tomonda turadi va hisobotda manfiy ko'rsatiladi."""
	return frappe.db.sql(
		"""
		SELECT gle.posting_date,
			   TRIM(IFNULL(acc.account_number, '')) AS account_number,
			   SUM(gle.debit - gle.credit) AS amount
		FROM `tabGL Entry` gle
		JOIN `tabAccount` acc ON acc.name = gle.account
		WHERE gle.company IN %(companies)s
		  AND gle.is_cancelled = 0
		  AND gle.posting_date BETWEEN %(from_date)s AND %(to_date)s
		  AND TRIM(IFNULL(acc.account_number, '')) IN %(numbers)s
		GROUP BY gle.posting_date, acc.account_number
		""",
		{
			"companies": tuple(companies),
			"from_date": from_date,
			"to_date": to_date,
			"numbers": tuple(DIVIDEND_ACCOUNTS),
		},
		as_dict=True,
	)


# ─── Aggregation ─────────────────────────────────────────────────────────────

def aggregate(period_list, companies, gl_rows, internal_rows, dividend_rows, owner_rows):
	def empty_company():
		return {"revenue": 0, "cogs_raw": 0, "cogs_adj": 0, "kassa": 0, "brak": 0,
				"adj": {}, "op": {}, "adm": {}, "other": {}, "owner_salary": 0}

	def empty_period():
		return {
			"companies": {c: empty_company() for c in companies},
			"internal": 0,
			"dividends": {num: 0 for num in DIVIDEND_ACCOUNTS},
			"acc_labels": {},   # счёт рақами -> кўринадиган ном
			# Ма'мурий харажат ТАҚСИМЛАШДАН ОЛДИНГИ ҳолати: Jazira Expense
			# Allocation яратган JE'лар (тескари ёзув + филиалларга қайта
			# ёзиш) чиқарилса, харажат қаерда бўлса ўша ерда — яъни
			# дастлабки ҳолида қолади. Жами ўзгармайди, фақат тақсимот йўқ.
			"adm_raw": {},
			"owner_taken": {o["key"]: 0 for o in OWNERS},
			"owner_salary": {o["key"]: 0 for o in OWNERS},
		}

	pdata = {p["key"]: empty_period() for p in period_list}

	for r in gl_rows:
		pk = _period_key(r.posting_date, period_list)
		if not pk:
			continue
		cd = pdata[pk]["companies"].get(r.company)
		if cd is None:
			continue

		net = flt(r.debit) - flt(r.credit)
		# Калит РАҚАМ бўйича: бир компанияда бир хил номли иккита счёт бор
		# (масалан 5201 ва 5281 — иккаласи ҳам "Ish haqqi"), ном бўйича
		# калитласак улар жимгина битта қаторга қўшилиб кетарди.
		key = r.account_number or r.account_name or "?"
		label = r.account_name or r.account_number or "?"

		# Касса фойда-зарар / брак счётими? Текшириш ота-гуруҳдан ОЛДИН
		# қилинади — изоҳ қуйида, cost_bucket ишлатилган жойда.
		cost_bucket = _classify_cost_bucket(r.account_number, r.account_name)

		if r.root_type == "Income":
			cd["revenue"] += flt(r.credit) - flt(r.debit)
		elif r.account_type == "Cost of Goods Sold":
			cd["cogs_raw"] += net
		elif r.account_type == "Stock Adjustment":
			# Омбор тафовути ҳаммаси битта счётга (5119) тушади, лекин сабаби
			# ҳар хил: нобуд/списание, инвентаризация, ишлаб чиқариш фарқи.
			# Ҳужжат турига қараб ажратилади. Алоҳида "Brak" номли Stock Entry
			# Type очилса — тўғридан-тўғри Брак қаторига тушади.
			kind = r.get("adj_kind") or "other"
			if kind in BRAK_ADJ_KINDS:
				cd["brak"] += net
			else:
				cd["cogs_adj"] += net
				cd["adj"][kind] = cd["adj"].get(kind, 0) + net
		elif cost_bucket:
			# Касса фойда-зарар ва брак — моҳияти бўйича таннарх, шунинг учун
			# Себестоимость ичига олинади.
			#
			# Текшириш ота-гуруҳдан ОЛДИН қилинади (аввал фақат 52001 остида
			# қараларди). Сабаби: "5213 Kassa Farq" ишчи компанияларда 52001
			# эмас, "5200 Indirect Expenses" остида турибди — эски тартибда у
			# 5200 шохи билан бирга ташлаб юбориларди ва унга ёзилган ҳар
			# қандай сумма ҳисоботдан жимгина йўқоларди.
			cd[cost_bucket] += net
		elif r.parent_number == OP_GROUP:
			cd["op"][key] = cd["op"].get(key, 0) + net
			pdata[pk]["acc_labels"][key] = label
		elif r.parent_number == ADM_GROUP:
			cd["adm"][key] = cd["adm"].get(key, 0) + net
			pdata[pk]["acc_labels"][key] = label
			if not r.get("is_allocation"):
				d_raw = pdata[pk]["adm_raw"]
				d_raw[key] = d_raw.get(key, 0) + net
		elif r.parent_number == INDIRECT_GROUP:
			# "5200 - Indirect Expenses" ostidagi guruhsiz eski hisoblar —
			# PL Hisoboti bilan bir xil: hisobotga kiritilmaydi.
			continue
		else:
			cd["other"][key] = cd["other"].get(key, 0) + net
			pdata[pk]["acc_labels"][key] = label

	for r in internal_rows:
		pk = _period_key(r.posting_date, period_list)
		if pk:
			pdata[pk]["internal"] += flt(r.amount)

	for r in dividend_rows:
		pk = _period_key(r.posting_date, period_list)
		if pk and r.account_number in pdata[pk]["dividends"]:
			pdata[pk]["dividends"][r.account_number] += flt(r.amount)

	by_employee = {o["employee"]: o["key"] for o in OWNERS}
	for r in owner_rows:
		pk = _period_key(r.posting_date, period_list)
		key = by_employee.get(r.party)
		if not pk or not key:
			continue
		pdata[pk]["owner_taken"][key] += flt(r.taken)
		pdata[pk]["owner_salary"][key] += flt(r.accrued)
		cd = pdata[pk]["companies"].get(r.company)
		if cd is not None:
			# Маош қайси компания китобида турганини эслаб қоламиз — уни
			# ўша компания фойдасига қайтариб қўшамиз.
			cd["owner_salary"] += flt(r.accrued)

	return pdata


# ─── Hisoblash yordamchilari ─────────────────────────────────────────────────

def _co_op(cd):
	return sum(cd["op"].values())


def _co_adm(cd):
	return sum(cd["adm"].values())


def _co_other(cd):
	return sum(cd["other"].values())


def _co_cogs(cd):
	"""Компаниянинг тўлиқ таннархи — тўртала таркибий қисми билан."""
	return (flt(cd["cogs_raw"]) + flt(cd["cogs_adj"])
			+ flt(cd["kassa"]) + flt(cd["brak"]))


def _co_marginal(cd):
	return cd["revenue"] - _co_cogs(cd)


def _co_profit(cd):
	"""Kompaniyaning o'z operatsion foydasi — ichki айланма чиқарилмайди,
	чунки филиал учун Складдан олинган товар ҳақиқий таннарх."""
	return _co_marginal(cd) - _co_op(cd) - _co_adm(cd) - _co_other(cd)


def _total_revenue(d):
	return sum(c["revenue"] for c in d["companies"].values()) - d["internal"]


def _total_cogs(d):
	return sum(_co_cogs(c) for c in d["companies"].values()) - d["internal"]


def _total_marginal(d):
	return _total_revenue(d) - _total_cogs(d)


def _total_op(d):
	return sum(_co_op(c) for c in d["companies"].values())


def _total_adm(d):
	return sum(_co_adm(c) for c in d["companies"].values())


def _total_other(d):
	return sum(_co_other(c) for c in d["companies"].values())


def _total_opex(d):
	return _total_op(d) + _total_adm(d) + _total_other(d)


def _total_profit(d):
	return _total_marginal(d) - _total_opex(d)


# ─── Columns ─────────────────────────────────────────────────────────────────

def get_columns(period_list):
	cols = [{"fieldname": "label", "label": _("Кўрсаткич"), "fieldtype": "Data", "width": 330}]
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

def build_rows(period_list, companies, pdata, eliminate=1):
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

	rows = []

	# ── ИТОГО ВЫРУЧКА ────────────────────────────────────────────────────────
	rows.append(mk("Итого выручка", per_period(_total_revenue), "root", 0))
	for co in companies:
		vm = per_period(lambda d, c=co: d["companies"][c]["revenue"])
		if all_zero(vm):
			continue
		rows.append(mk(f"Выручка {company_label(co)}", vm, "detail", 1))
	if eliminate:
		vm = per_period(lambda d: -d["internal"])
		if not all_zero(vm):
			rows.append(mk("(−) Ички айланма (гуруҳ ичидаги сотув)", vm, "detail", 1))

	# ── ИТОГО СЕБЕСТОИМОСТЬ ──────────────────────────────────────────────────
	# Ҳар бир таркибий қисм алоҳида кўрсатилади: аввал турлар бўйича
	# (хом ашё / омбор тафовути / касса фойда-зарар / брак), кейин ҳар турнинг
	# ичида компаниялар.
	rows.append(mk("Итого себестоимость", per_period(_total_cogs), "root", 0, is_cost=True))
	for bucket, bucket_label in [
		("cogs_raw", "Сырьевая себестоимость"),
		("cogs_adj", "Убыток от себестоимости"),
		("kassa", "Foyda/Zarar Kassa"),
		("brak", "Брак (нобуд товар)"),
	]:
		bvm = per_period(lambda d, b=bucket: sum(
			flt(cd[b]) for cd in d["companies"].values()))
		if all_zero(bvm):
			continue
		rows.append(mk(bucket_label, bvm, "sub", 1, is_cost=True))

		# "Убыток от себестоимости" ичида — сабаб бўйича ажратма. Ҳаммаси
		# битта счётга (5119) тушгани учун фақат ҳужжат туридан билинади.
		if bucket == "cogs_adj":
			for kind, kind_label in ADJ_KIND_LABELS:
				kvm = per_period(lambda d, k=kind: sum(
					flt(cd["adj"].get(k, 0)) for cd in d["companies"].values()))
				if all_zero(kvm):
					continue
				rows.append(mk(kind_label, kvm, "detail", 2, is_cost=True))

		for co in companies:
			cvm = per_period(lambda d, b=bucket, c=co: flt(d["companies"][c][b]))
			if all_zero(cvm):
				continue
			rows.append(mk(f"{bucket_label} {company_label(co)}", cvm, "detail", 2, is_cost=True))
	if eliminate:
		vm = per_period(lambda d: -d["internal"])
		if not all_zero(vm):
			rows.append(mk("(−) Ички айланма (гуруҳ ичидаги харид)", vm, "detail", 1, is_cost=True))

	# ── МАРЖИНАЛЬНАЯ ПРИБЫЛЬ ─────────────────────────────────────────────────
	rows.append(mk("Маржинальная прибыль", per_period(_total_marginal), "result", 0))
	rows.append(mk(
		"маржа",
		per_period(lambda d: _total_marginal(d) / _total_revenue(d) * 100 if _total_revenue(d) else 0),
		"percent", 1,
	))
	for co in companies:
		vm = per_period(lambda d, c=co: _co_marginal(d["companies"][c]))
		if all_zero(vm):
			continue
		rows.append(mk(f"Маржинальная прибыль {company_label(co)}", vm, "detail", 1))
		rows.append(mk(
			f"рентабельность % {company_label(co)}",
			per_period(lambda d, c=co: (
				_co_marginal(d["companies"][c]) / d["companies"][c]["revenue"] * 100
				if d["companies"][c]["revenue"] else 0
			)),
			"percent", 2,
		))
	rows.append(divider())

	# ── ИТОГО ОПЕРАЦИОННЫЕ РАСХОДЫ ───────────────────────────────────────────
	rows.append(mk("Итого операционные расходы", per_period(_total_opex), "root", 0, is_cost=True))

	# Har bir kompaniyaning O'Z operatsion (52001) xarajati — ichида ҳисоблар
	for co in companies:
		vm = per_period(lambda d, c=co: _co_op(d["companies"][c]))
		if all_zero(vm):
			continue
		rows.append(mk(f"Операционные расходы {company_label(co)}", vm, "sub", 1, is_cost=True))
		for acc_label, acc_vm in _account_rows(period_list, pdata, "op", [co]):
			rows.append(mk(acc_label, acc_vm, "detail", 2, is_cost=True))

	# Ма'мурий (52002) — барча компания бўйича БИРГА (Expense Allocation уни
	# аллақачон бир марта тақсимлаб бўлган, шунинг учун икки марта саналмайди)
	adm_vm = per_period(_total_adm)
	if not all_zero(adm_vm):
		rows.append(mk("Операционные расходы Административ", adm_vm, "sub", 1, is_cost=True))
		for acc_label, acc_vm in _account_rows(period_list, pdata, "adm", companies):
			rows.append(mk(acc_label, acc_vm, "detail", 2, is_cost=True))

	other_vm = per_period(_total_other)
	if not all_zero(other_vm):
		rows.append(mk("Бошқа харажатлар", other_vm, "sub", 1, is_cost=True))
		for acc_label, acc_vm in _account_rows(period_list, pdata, "other", companies):
			rows.append(mk(acc_label, acc_vm, "detail", 2, is_cost=True))

	# ── ОПЕРАЦИОННЫЙ ПРИБЫЛЬ ─────────────────────────────────────────────────
	rows.append(mk("Операционный прибыль", per_period(_total_profit), "result", 0))
	rows.append(mk(
		"Рентабельность по операционной прибыли",
		per_period(lambda d: _total_profit(d) / _total_revenue(d) * 100 if _total_revenue(d) else 0),
		"percent", 1,
	))
	rows.append(divider())

	# ── КОМПАНИЯЛАР КЕСИМИДА ОПЕРАЦИОН ФОЙДА ─────────────────────────────────
	rows.append(mk(
		"Операционный прибыль (филиаллар кесимида)",
		per_period(lambda d: sum(_co_profit(c) for c in d["companies"].values())),
		"root", 0,
	))
	for co in companies:
		vm = per_period(lambda d, c=co: _co_profit(d["companies"][c]))
		if all_zero(vm):
			continue
		rows.append(mk(f"Операционный прибыль {company_label(co)}", vm, "detail", 1))

	# ── АДМ РАСХОД (ТАҚСИМЛАШДАН ОЛДИНГИ ҲОЛАТ) ──────────────────────────────
	#
	# Юқоридаги "Операционные расходы Административ" — Jazira Expense
	# Allocation филиалларга ТАРҚАТГАНДАН КЕЙИНГИ ҳолат (Склад 23.7 млн,
	# Сарипул 91.3 млн, Халк Банки 57.3 млн). Бу ерда эса ўша харажат
	# ДАСТЛАБКИ ҳолида — қаерда юзага келган бўлса ўша ерда, счётма-счёт.
	# Жами иккалада ҳам бир хил (2026-июнь: 172 375 784).
	rows.append(divider())
	raw_total = per_period(lambda d: sum(
		flt(v) for v in d["adm_raw"].values()))
	if not all_zero(raw_total):
		rows.append(mk("Адм расход (тақсимлашдан олдин)", raw_total, "root", 0, is_cost=True))

		# Счётлар — умумий суммаси бўйича каттадан кичикка
		totals = {}
		for p in period_list:
			for acc, amt in pdata[p["key"]]["adm_raw"].items():
				totals[acc] = totals.get(acc, 0) + flt(amt)
		labels = {}
		for p in period_list:
			labels.update(pdata[p["key"]].get("acc_labels") or {})

		for acc in sorted(totals, key=lambda a: -abs(totals[a])):
			if not flt(totals[acc]):
				continue
			avm = per_period(lambda d, a=acc: flt(d["adm_raw"].get(a, 0)))
			rows.append(mk(labels.get(acc, acc), avm, "detail", 1, is_cost=True))


	return rows


def _account_rows(period_list, pdata, bucket, companies):
	"""Berilgan toifadagi (op/adm/other) hisoblarni kompaniyalar bo'yicha
	qo'shib, kattadan kichikka tartiblab qaytaradi."""
	totals = {}
	for p in period_list:
		for co in companies:
			cd = pdata[p["key"]]["companies"].get(co)
			if not cd:
				continue
			for acc, amt in cd[bucket].items():
				totals[acc] = totals.get(acc, 0) + flt(amt)

	# Рақам -> ном (счёт рақами калит, лекин экранда ном кўринади)
	labels = {}
	for p in period_list:
		labels.update(pdata[p["key"]].get("acc_labels") or {})

	result = []
	for acc in sorted(totals, key=lambda a: -abs(totals[a])):
		if not flt(totals[acc]):
			continue
		vm = {}
		for p in period_list:
			total = 0
			for co in companies:
				cd = pdata[p["key"]]["companies"].get(co)
				if cd:
					total += flt(cd[bucket].get(acc, 0))
			vm[_fk(p["key"])] = total
		result.append((labels.get(acc, acc), vm))
	return result
