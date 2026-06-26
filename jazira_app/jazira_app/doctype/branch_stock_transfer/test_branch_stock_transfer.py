# Copyright (c) 2026, Jazira App and contributors
# See license.txt

"""
Branch Stock Transfer uchun minimal qabul testlari.

Bu testlar MAVJUD ma'lumotlarga (kompaniyalar, omborlar, internal customer/supplier,
stok) tayanadi. Agar shartlar topilmasa, test SKIP qilinadi — shuning uchun ular
to'liq sozlangan saytda (mas. jazira.local2) ishlaydi.

Ishga tushirish:
    bench --site jazira.local2 run-tests --module \
        "jazira_app.jazira_app.doctype.branch_stock_transfer.test_branch_stock_transfer"
"""

import unittest

import frappe
from frappe.utils import flt, today

FROM_COMPANY = "Jazira Xalq Banki"
TO_COMPANY = "Jazira Saripul"
FROM_WAREHOUSE = "Sklad Xalq Bank - JXB"
TO_WAREHOUSE = "Sklad Saripul - JSaripul"


def _prereqs_ok():
    """Test uchun zarur ma'lumotlar bormi?"""
    for c in (FROM_COMPANY, TO_COMPANY):
        if not frappe.db.exists("Company", c):
            return False
    for w in (FROM_WAREHOUSE, TO_WAREHOUSE):
        if not frappe.db.exists("Warehouse", w):
            return False
    if not frappe.db.exists(
        "Customer", {"is_internal_customer": 1, "represents_company": TO_COMPANY}
    ):
        return False
    if not frappe.db.exists(
        "Supplier", {"is_internal_supplier": 1, "represents_company": FROM_COMPANY}
    ):
        return False
    return True


def _stocked_item():
    """from_warehouse'da valuation va musbat qoldig'i bor itemni topadi."""
    row = frappe.db.sql(
        """
        SELECT item_code FROM `tabBin`
        WHERE warehouse = %s AND actual_qty > 0 AND valuation_rate > 0
        ORDER BY actual_qty DESC LIMIT 1
        """,
        FROM_WAREHOUSE,
    )
    return row[0][0] if row else None


@unittest.skipUnless(_prereqs_ok(), "Inter-company sozlamasi yoki kompaniyalar topilmadi")
class TestBranchStockTransfer(unittest.TestCase):
    def setUp(self):
        frappe.set_user("Administrator")

    def _new_transfer(self):
        doc = frappe.new_doc("Branch Stock Transfer")
        doc.posting_date = today()
        doc.from_company = FROM_COMPANY
        doc.to_company = TO_COMPANY
        doc.from_warehouse = FROM_WAREHOUSE
        doc.to_warehouse = TO_WAREHOUSE
        doc.price_basis = "Valuation Rate"
        return doc

    # 2 + 3) Oddiy item o'tkazma + tan narx tengligi
    def test_simple_item_transfer_at_cost(self):
        item = _stocked_item()
        if not item:
            self.skipTest("from_warehouse'da stokli item yo'q")

        doc = self._new_transfer()
        doc.append("items", {"source_type": "Item", "item_code": item, "qty": 1})
        doc.insert()
        doc.submit()

        self.assertTrue(doc.sales_invoice)
        self.assertTrue(doc.purchase_invoice)
        self.assertEqual(doc.status, "Completed")

        si = frappe.get_doc("Sales Invoice", doc.sales_invoice)
        pi = frappe.get_doc("Purchase Invoice", doc.purchase_invoice)

        # Tan narx tengligi (ustamasiz): SI va PI summalari teng
        self.assertAlmostEqual(flt(si.items[0].rate), flt(pi.items[0].rate), places=2)
        self.assertAlmostEqual(flt(si.total), flt(pi.total), places=2)

        # update_stock va to'g'ri omborlar
        self.assertEqual(si.update_stock, 1)
        self.assertEqual(pi.update_stock, 1)
        self.assertEqual(pi.items[0].warehouse, TO_WAREHOUSE)

        # 4) Cancel — avval PI, keyin SI
        doc.cancel()
        self.assertEqual(doc.status, "Cancelled")
        self.assertEqual(frappe.db.get_value("Sales Invoice", doc.sales_invoice, "docstatus"), 2)
        self.assertEqual(frappe.db.get_value("Purchase Invoice", doc.purchase_invoice, "docstatus"), 2)

    # 5) Validatsiya — bir xil from/to kompaniya
    def test_same_company_rejected(self):
        doc = self._new_transfer()
        doc.to_company = FROM_COMPANY
        doc.append("items", {"source_type": "Item", "item_code": _stocked_item() or "x", "qty": 1})
        self.assertRaises(frappe.ValidationError, doc.insert)

    # 1) BOM o'tkazma — portlash
    def test_bom_explosion(self):
        bom = frappe.db.get_value(
            "BOM", {"is_active": 1, "docstatus": 1}, "name", order_by="creation desc"
        )
        if not bom:
            self.skipTest("Aktiv BOM topilmadi")

        n_components = frappe.db.count("BOM Item", {"parent": bom})
        doc = self._new_transfer()
        doc.append("items", {"source_type": "BOM", "bom": bom, "bom_qty": 1})
        doc.insert()  # validate portlatadi

        # BOM qatori komponentlarga yoyilgan bo'lishi kerak
        self.assertEqual(len(doc.items), n_components)
        for r in doc.items:
            self.assertEqual(r.source_type, "Item")
            self.assertEqual(r.from_bom, bom)
