"""
Inter-company Sales Order avtomatlashtirish ury app'ga ko'chirilgan:
  ury.ury.hooks.sklad_sales_order  (YAGONA manba — double-invoicing oldini olish)

Bu faylda faqat sales_invoice.py (inter-company SI amend) ishlatadigan
ustama-foiz helperi qoldirilgan.
"""

import frappe


def _get_markup_percent(company):
    """Sklad Settings (Single) dan kompaniya uchun ustama foizni olish.

    QATTIQ qoida (SO oqimi bilan izchil): filial company_markups ro'yxatida
    bo'lmasa None qaytadi → SI amend uni skip qiladi. Ro'yxatda bor, lekin
    foiz 0/bo'sh bo'lsa — default_markup_percent.

    Sklad Settings — Single doctype, shuning uchun get_single ishlatiladi."""
    settings = frappe.get_single("Sklad Settings")

    for row in settings.company_markups:
        if row.company == company:
            return row.percent or settings.default_markup_percent or 0

    return None
