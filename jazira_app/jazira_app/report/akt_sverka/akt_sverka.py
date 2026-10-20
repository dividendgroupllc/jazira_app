# -*- coding: utf-8 -*-
# Copyright (c) 2026, Jazira App
# License: MIT

"""
Akt Sverka (Kontragent Sverka) Report
"""

import frappe
from frappe import _
from frappe.utils import flt, getdate


def execute(filters=None):
    if not filters:
        filters = {}
    
    validate_filters(filters)
    
    columns = get_columns()
    data, summary = get_data(filters)
    message = get_summary_table(summary, filters)
    report_summary = get_report_summary(summary)
    
    return columns, data, message, None, report_summary


def validate_filters(filters):
    if not filters.get("from_date"):
        frappe.throw(_("'Boshlanish sanasi' majburiy"))
    if not filters.get("to_date"):
        frappe.throw(_("'Tugash sanasi' majburiy"))
    if not filters.get("party_type"):
        frappe.throw(_("'Kontragent turi' majburiy"))
    if not filters.get("party"):
        frappe.throw(_("'Kontragent' majburiy"))
    if getdate(filters.get("from_date")) > getdate(filters.get("to_date")):
        frappe.throw(_("Boshlanish sanasi tugash sanasidan katta bo'lishi mumkin emas"))


def get_columns():
    return [
        {"label": _("Sana"), "fieldname": "posting_date", "fieldtype": "Date", "width": 100},
        {"label": _("Hujjat turi"), "fieldname": "voucher_type_label", "fieldtype": "Data", "width": 140},
        {"label": _("Hujjat №"), "fieldname": "voucher_no", "fieldtype": "Dynamic Link", "options": "voucher_type", "width": 150},
        {"label": _("Izoh"), "fieldname": "remarks", "fieldtype": "Data", "width": 200},
        {"label": _("Debet"), "fieldname": "debit", "fieldtype": "Currency", "width": 130},
        {"label": _("Kredit"), "fieldname": "credit", "fieldtype": "Currency", "width": 130},
        {"label": _("Qoldiq"), "fieldname": "balance", "fieldtype": "Currency", "width": 140}
    ]


def get_data(filters):
    data = []
    summary = {
        "opening_debit": 0, 
        "opening_credit": 0, 
        "by_voucher_type": {}, 
        "total_debit": 0,
        "total_credit": 0,
        "closing_balance": 0
    }
    
    from_date = filters.get("from_date")

    # 1. BOSHLANG'ICH QOLDIQ
    opening = get_opening_balance(filters)

    opening_debit = flt(opening) if opening > 0 else 0
    opening_credit = abs(flt(opening)) if opening < 0 else 0
    
    summary["opening_debit"] = opening_debit
    summary["opening_credit"] = opening_credit
    summary["total_debit"] = opening_debit
    summary["total_credit"] = opening_credit
    
    data.append({
        "posting_date": from_date,
        "voucher_type": "",
        "voucher_type_label": "Boshlang'ich qoldiq",
        "voucher_no": "",
        "remarks": "",
        "debit": opening_debit,
        "credit": opening_credit,
        "balance": flt(opening),
        "is_opening": 1
    })

    # 2. TRANZAKSIYALAR
    entries = get_gl_entries(filters)
    remarks_map = get_remarks_map(entries)
    running_balance = flt(opening)
    
    for e in entries:
        debit = flt(e.debit)
        credit = flt(e.credit)
        running_balance += (debit - credit)
        
        summary["total_debit"] += debit
        summary["total_credit"] += credit
        
        vt = e.voucher_type
        if vt not in summary["by_voucher_type"]:
            summary["by_voucher_type"][vt] = {"debit": 0, "credit": 0}
        summary["by_voucher_type"][vt]["debit"] += debit
        summary["by_voucher_type"][vt]["credit"] += credit
        
        data.append({
            "posting_date": e.posting_date,
            "voucher_type": e.voucher_type,
            "voucher_type_label": get_label(e.voucher_type),
            "voucher_no": e.voucher_no,
            "remarks": remarks_map.get((e.voucher_type, e.voucher_no), ""),
            "debit": debit,
            "credit": credit,
            "balance": running_balance
        })
    
    summary["closing_balance"] = running_balance
    
    return data, summary


def _build_scope(filters):
    """GL Entry uchun party asosidagi shartni (sanasiz) qaytaradi."""
    params = {
        "party_type": filters.get("party_type"),
        "party": filters.get("party"),
    }
    conds = ["is_cancelled = 0", "party_type = %(party_type)s", "party = %(party)s"]

    company = filters.get("company")
    if company:
        conds.append("company = %(company)s")
        params["company"] = company

    return " AND ".join(conds), params


def get_opening_balance(filters):
    where_sql, params = _build_scope(filters)
    params = dict(params, from_date=filters.get("from_date"))
    result = frappe.db.sql(f"""
        SELECT SUM(debit) - SUM(credit) as balance
        FROM `tabGL Entry`
        WHERE {where_sql} AND posting_date < %(from_date)s
    """, params, as_dict=True)

    return flt(result[0].balance) if result and result[0].balance else 0


def get_gl_entries(filters):
    where_sql, params = _build_scope(filters)
    params = dict(params, from_date=filters.get("from_date"), to_date=filters.get("to_date"))
    return frappe.db.sql(f"""
        SELECT posting_date, voucher_type, voucher_no, debit, credit
        FROM `tabGL Entry`
        WHERE {where_sql} AND posting_date BETWEEN %(from_date)s AND %(to_date)s
        ORDER BY posting_date, creation
    """, params, as_dict=True)


def get_remarks_map(entries):
    """Izoh ustuni uchun barcha hujjat izohlarini bitta marta oladi.

    Tartib:
    1. Kassa.primechaniya — Kassada yozilgan haqiqiy izoh (ustuvor). Kassa'dan
       yaratilgan PE/JE'da izoh o'rnida shablon matn ("Kassa: KASSA-… - Расход")
       turadi, shu sababli dds va expense_analysis reportlarida ham Kassa izohi
       birinchi o'rinda turadi.
    2. Bo'lmasa — hujjat turiga qarab: faktura tovarlari, to'lov usuli,
       JE user_remark.

    Qaytaradi: {(voucher_type, voucher_no): izoh}
    """
    by_type = {}
    for e in entries:
        if e.voucher_type and e.voucher_no:
            by_type.setdefault(e.voucher_type, set()).add(e.voucher_no)

    # Kassa faqat PE/JE yaratadi — izohni shular uchun qidiramiz
    kassa_vouchers = by_type.get("Payment Entry", set()) | by_type.get("Journal Entry", set())
    kassa_remarks = get_kassa_remarks(kassa_vouchers)

    remarks = {}
    for vt, vouchers in by_type.items():
        if vt == "Sales Invoice":
            fallback = get_invoice_item_names("Sales Invoice Item", vouchers)
        elif vt == "Purchase Invoice":
            fallback = get_invoice_item_names("Purchase Invoice Item", vouchers)
        elif vt == "Payment Entry":
            fallback = get_field_map("Payment Entry", "mode_of_payment", vouchers)
        elif vt == "Journal Entry":
            fallback = get_field_map("Journal Entry", "user_remark", vouchers)
        else:
            fallback = {}

        for v in vouchers:
            remarks[(vt, v)] = kassa_remarks.get(v) or fallback.get(v, "")

    return remarks


def get_kassa_remarks(voucher_nos):
    """Kassa hujjatidagi izohni (primechaniya) shu Kassa yaratgan PE/JE
    voucher_no'siga bog'lab qaytaradi ({voucher_no: izoh}).

    Kassa bir nechta link maydoniga ega: journal_entry, payment_entry,
    payment_entry_receive, payment_entry_supplier.
    """
    if not voucher_nos:
        return {}

    rows = frappe.db.sql("""
        SELECT payment_entry, payment_entry_receive, payment_entry_supplier,
               journal_entry, primechaniya
        FROM `tabKassa`
        WHERE docstatus = 1
          AND primechaniya IS NOT NULL AND primechaniya != ''
          AND (
              payment_entry IN %(vouchers)s
              OR payment_entry_receive IN %(vouchers)s
              OR payment_entry_supplier IN %(vouchers)s
              OR journal_entry IN %(vouchers)s
          )
    """, {"vouchers": list(voucher_nos)}, as_dict=True)

    result = {}
    for r in rows:
        for field in ("payment_entry", "payment_entry_receive",
                      "payment_entry_supplier", "journal_entry"):
            voucher = r.get(field)
            if voucher and voucher in voucher_nos:
                result[voucher] = r.primechaniya
    return result


def get_invoice_item_names(item_doctype, voucher_nos):
    """Faktura izohi o'rnida — har hujjatning birinchi 2 tovari."""
    if not voucher_nos:
        return {}

    rows = frappe.db.sql(f"""
        SELECT parent, item_name
        FROM `tab{item_doctype}`
        WHERE parent IN %(vouchers)s
        ORDER BY parent, idx
    """, {"vouchers": list(voucher_nos)}, as_dict=True)

    names = {}
    for r in rows:
        if not r.item_name:
            continue
        items = names.setdefault(r.parent, [])
        if len(items) < 2:
            items.append(r.item_name)

    return {parent: ", ".join(items) for parent, items in names.items()}


def get_field_map(doctype, fieldname, voucher_nos):
    """{hujjat nomi: maydon qiymati} — bitta so'rovda."""
    if not voucher_nos:
        return {}

    rows = frappe.db.sql(f"""
        SELECT name, `{fieldname}` AS value
        FROM `tab{doctype}`
        WHERE name IN %(vouchers)s
    """, {"vouchers": list(voucher_nos)}, as_dict=True)

    return {r.name: (r.value or "") for r in rows}


def get_label(voucher_type):
    labels = {
        "Sales Invoice": "Sotuv fakturasi",
        "Purchase Invoice": "Xarid fakturasi",
        "Payment Entry": "To'lov",
        "Journal Entry": "Jurnal yozuvi"
    }
    return labels.get(voucher_type, voucher_type)


def fmt(val):
    """Valyuta formati."""
    if not val:
        return "0,00"
    return "{:,.2f}".format(flt(val)).replace(",", " ").replace(".", ",")


def get_report_summary(summary):
    """Pastdagi summary kartalar."""
    return [
        {
            "value": summary.get("total_debit", 0),
            "label": _("Jami Debet"),
            "datatype": "Currency",
            "indicator": "blue"
        },
        {
            "value": summary.get("total_credit", 0),
            "label": _("Jami Kredit"),
            "datatype": "Currency",
            "indicator": "orange"
        },
        {
            "value": summary.get("closing_balance", 0),
            "label": _("Yakuniy qoldiq"),
            "datatype": "Currency",
            "indicator": "red" if summary.get("closing_balance", 0) < 0 else "green"
        }
    ]


def get_summary_table(summary, filters):
    """1-Jadval - Voucher Type bo'yicha."""
    party = filters.get("party", "")
    from_date = filters.get("from_date", "")
    to_date = filters.get("to_date", "")
    
    opening_debit = summary.get("opening_debit", 0)
    opening_credit = summary.get("opening_credit", 0)
    closing = summary.get("closing_balance", 0)
    
    rows = ""
    by_vt = summary.get("by_voucher_type", {})
    
    vt_order = ["Purchase Invoice", "Sales Invoice", "Payment Entry", "Journal Entry"]
    
    for vt in vt_order:
        if vt in by_vt:
            d, c = by_vt[vt]["debit"], by_vt[vt]["credit"]
            rows += f'<tr><td style="padding-left:20px;">{get_label(vt)}</td><td style="text-align:right;">{fmt(d)}</td><td style="text-align:right;">{fmt(c)}</td></tr>'
    
    for vt, amounts in by_vt.items():
        if vt not in vt_order:
            d, c = amounts["debit"], amounts["credit"]
            rows += f'<tr><td style="padding-left:20px;">{get_label(vt)}</td><td style="text-align:right;">{fmt(d)}</td><td style="text-align:right;">{fmt(c)}</td></tr>'
    
    closing_debit = closing if closing > 0 else 0
    closing_credit = abs(closing) if closing < 0 else 0
    
    return f"""
    <div class="akt-sverka-summary" style="margin-bottom:20px;">
        <style>
            /* Rangli qatorlar och fonli — dark rejimda ham o'qilishi uchun to'q matn majburlaymiz */
            .akt-sverka-summary tr.akt-hl td,
            .akt-sverka-summary tr.akt-hl th {{ color:#1f2937 !important; }}
        </style>
        <p><strong>Kontragent:</strong> {party} | <strong>Davr:</strong> {from_date} — {to_date}</p>
        <table class="table table-bordered" style="width:auto;min-width:450px;">
            <thead>
                <tr class="akt-hl" style="background:#fffacd;">
                    <th>Hujjat turi</th>
                    <th style="text-align:right;width:140px;">Debet</th>
                    <th style="text-align:right;width:140px;">Kredit</th>
                </tr>
            </thead>
            <tbody>
                <tr class="akt-hl" style="background:#e6f7ff;">
                    <td><strong>Boshlang'ich qoldiq</strong></td>
                    <td style="text-align:right;">{fmt(opening_debit)}</td>
                    <td style="text-align:right;">{fmt(opening_credit)}</td>
                </tr>
                {rows}
                <tr class="akt-hl" style="background:#d4edda;font-weight:bold;">
                    <td>JAMI</td>
                    <td style="text-align:right;">{fmt(summary.get("total_debit", 0))}</td>
                    <td style="text-align:right;">{fmt(summary.get("total_credit", 0))}</td>
                </tr>
                <tr class="akt-hl" style="background:#fff3cd;font-weight:bold;">
                    <td>Yakuniy qoldiq</td>
                    <td style="text-align:right;">{fmt(closing_debit)}</td>
                    <td style="text-align:right;">{fmt(closing_credit)}</td>
                </tr>
            </tbody>
        </table>
    </div>
    """