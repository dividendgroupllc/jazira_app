# Copyright (c) 2026, Jazira App and contributors
# For license information, please see license.txt

"""
Journal Sheets — Journal Entry uchun "varaq" (sheet) hisoboti.

Prixod Sheets (Purchase Invoice) va Prodaja Sheets (Sales Invoice) bilan bir
xil uslubda: hujjatning HAR BIR QATORI — jadvalning bitta qatori, oxirida
qalin "ЖАМИ".

Journal Entry'ga moslashtirilgan joylari
────────────────────────────────────────
- Sotuv/xarid varaqlarida "tovar, dona, narx" bo'ladi; Journal Entry'da esa
  tovar yo'q — uning o'rniga SCHYOT, DEBET va KREDIT turadi.
- Izoh (`user_remark`) Jazira bazasida deyarli har doim HUJJAT darajasida
  to'ldirilgan (1058/1085), qator darajasida esa kam (20/2428). Shuning
  uchun avval qator izohi olinadi, u bo'sh bo'lsa hujjat izohi ko'rsatiladi.
  Ko'pchilik JE Kassa'dan yaratilgani uchun izohda "Kassa: KASSA-…" turadi —
  shu orqali qaysi kassa hujjatidan kelgani ko'rinadi.
- "Қарши счёт" (against_account) barcha qatorda to'ldirilgan, shuning uchun
  ustun sifatida chiqariladi — yozuvning ikkinchi tomonini darhol ko'rsatadi.
"""

import frappe
from frappe import _
from frappe.utils import flt, getdate


def execute(filters=None):
    filters = filters or {}
    validate_filters(filters)
    columns = get_columns()
    data = get_data(filters)
    return columns, data


def validate_filters(filters):
    if not filters.get("from_date") or not filters.get("to_date"):
        frappe.throw(_("Сана оралиғи мажбурий (from_date / to_date)"))
    if getdate(filters["from_date"]) > getdate(filters["to_date"]):
        frappe.throw(_("Бошланиш санаси тугаш санасидан катта бўлиши мумкин эмас"))


def get_columns():
    return [
        {"fieldname": "posting_date", "label": _("Сана"), "fieldtype": "Date", "width": 95},
        {"fieldname": "journal_entry", "label": _("Ҳужжат"), "fieldtype": "Link",
         "options": "Journal Entry", "width": 160},
        {"fieldname": "voucher_type", "label": _("Ҳужжат тури"), "fieldtype": "Data", "width": 120},
        {"fieldname": "account", "label": _("Счёт"), "fieldtype": "Link",
         "options": "Account", "width": 250},
        {"fieldname": "party", "label": _("Контрагент"), "fieldtype": "Data", "width": 170},
        {"fieldname": "debit", "label": _("Дебет"), "fieldtype": "Currency", "width": 140},
        {"fieldname": "credit", "label": _("Кредит"), "fieldtype": "Currency", "width": 140},
        {"fieldname": "against_account", "label": _("Қарши счёт"), "fieldtype": "Data", "width": 220},
        {"fieldname": "cost_center", "label": _("Харажат маркази"), "fieldtype": "Link",
         "options": "Cost Center", "width": 160},
        {"fieldname": "remarks", "label": _("Изоҳ"), "fieldtype": "Data", "width": 280},
        {"fieldname": "company", "label": _("Компания"), "fieldtype": "Link",
         "options": "Company", "width": 150},
    ]


def get_data(filters):
    conditions = ["je.docstatus = 1", "je.posting_date BETWEEN %(from_date)s AND %(to_date)s"]
    params = {"from_date": filters["from_date"], "to_date": filters["to_date"]}

    if filters.get("company"):
        conditions.append("je.company = %(company)s")
        params["company"] = filters["company"]
    if filters.get("voucher_type"):
        conditions.append("je.voucher_type = %(voucher_type)s")
        params["voucher_type"] = filters["voucher_type"]
    if filters.get("account"):
        conditions.append("jea.account = %(account)s")
        params["account"] = filters["account"]
    if filters.get("party_type"):
        conditions.append("jea.party_type = %(party_type)s")
        params["party_type"] = filters["party_type"]
    if filters.get("party"):
        conditions.append("jea.party = %(party)s")
        params["party"] = filters["party"]
    if filters.get("cost_center"):
        conditions.append("jea.cost_center = %(cost_center)s")
        params["cost_center"] = filters["cost_center"]
    if filters.get("remarks"):
        # Izoh bo'yicha qidiruv — masalan "Kassa" deb yozsangiz, faqat
        # Kassa'dan yaratilgan yozuvlar chiqadi.
        conditions.append(
            "(jea.user_remark LIKE %(remarks)s OR je.user_remark LIKE %(remarks)s)")
        params["remarks"] = "%" + filters["remarks"] + "%"

    where = " AND ".join(conditions)

    rows = frappe.db.sql(f"""
        SELECT
            je.posting_date,
            jea.parent AS journal_entry,
            je.voucher_type,
            je.company,
            jea.account,
            jea.party_type,
            jea.party,
            jea.debit,
            jea.credit,
            jea.against_account,
            jea.cost_center,
            COALESCE(NULLIF(TRIM(jea.user_remark), ''),
                     NULLIF(TRIM(je.user_remark), '')) AS remarks
        FROM `tabJournal Entry Account` jea
        INNER JOIN `tabJournal Entry` je ON je.name = jea.parent
        WHERE {where}
        ORDER BY je.posting_date, jea.parent, jea.idx
    """, params, as_dict=True)

    data = []
    tot_debit = 0
    tot_credit = 0

    for r in rows:
        debit = flt(r.debit)
        credit = flt(r.credit)
        tot_debit += debit
        tot_credit += credit

        data.append({
            "posting_date": r.posting_date,
            "journal_entry": r.journal_entry,
            "voucher_type": r.voucher_type,
            "account": r.account,
            # Kontragent turi bilan birga — "Supplier: IMPORT GOSHT"
            "party": f"{r.party_type}: {r.party}" if r.party else None,
            "debit": debit,
            "credit": credit,
            "against_account": r.against_account,
            "cost_center": r.cost_center,
            "remarks": (r.remarks or "").replace("\n", " ").strip() or None,
            "company": r.company,
        })

    if data:
        data.append({
            "account": _("ЖАМИ"),
            "debit": tot_debit,
            "credit": tot_credit,
            "is_total": 1,
        })

    return data
