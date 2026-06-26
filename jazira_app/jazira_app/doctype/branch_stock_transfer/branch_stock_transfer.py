# Copyright (c) 2026, Jazira App and contributors
# For license information, please see license.txt

"""
Branch Stock Transfer (Filial Tovar O'tkazmasi)
================================================

Filial KOMPANIYALAR o'rtasida tovarni TAN NARXDA (ustamasiz) ko'chiradi va
orqada inter-company hujjatlarni avtomatik yaratadi:

  Submit:
    1. Sales Invoice   (manba kompaniya — sotuvchi, update_stock=1) → ombordan CHIQIM
    2. Purchase Invoice (maqsad kompaniya — xaridor, update_stock=1) → omborga KIRIM
       (make_inter_company_purchase_invoice orqali SI ga bog'lanadi)

  Cancel:
    teskari tartibda — avval PI, keyin SI bekor qilinadi.

Bu DocType FAQAT filial→filial o'tkazmalari uchun. Markaziy
"Jazira Sklad → filial" (15% ustamali) oqimi bu yerga kirmaydi —
u ury.ury.hooks.sklad_sales_order da alohida boshqariladi.

Narx: doimo valuation rate (tan narx), USTAMASIZ. SI va PI summalari teng.
"""

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt, nowtime

from erpnext.stock.utils import validate_warehouse_company


class BranchStockTransfer(Document):
    # ------------------------------------------------------------------ #
    #  VALIDATE
    # ------------------------------------------------------------------ #
    def validate(self):
        self._set_status()
        self._validate_companies()
        self._validate_warehouses()
        self._explode_and_rate()
        self._compute_totals()

    def _set_status(self):
        if self.docstatus == 0:
            self.status = "Draft"
        elif self.docstatus == 1:
            self.status = "Completed"
        elif self.docstatus == 2:
            self.status = "Cancelled"

    def _validate_companies(self):
        if not self.from_company or not self.to_company:
            return
        if self.from_company == self.to_company:
            frappe.throw(
                _("Manba va maqsad kompaniya bir xil bo'lishi mumkin emas ({0}).").format(
                    self.from_company
                )
            )

    def _validate_warehouses(self):
        """Har bir ombor o'z kompaniyasiga tegishli bo'lishi shart."""
        if self.from_warehouse and self.from_company:
            validate_warehouse_company(self.from_warehouse, self.from_company)
        if self.to_warehouse and self.to_company:
            validate_warehouse_company(self.to_warehouse, self.to_company)

    # ------------------------------------------------------------------ #
    #  BOM EXPLOSION + RATE
    # ------------------------------------------------------------------ #
    def _explode_and_rate(self):
        """source_type='BOM' qatorlarni komponentlariga (bir pog'onali) yoyadi
        va har qatorga tan narx (valuation) o'rnatadi. Idempotent — portlatilgan
        qator endi 'Item' bo'lib qoladi, qayta yoyilmaydi."""
        new_rows = []
        for row in self.items:
            if row.source_type == "BOM":
                if not row.reference:
                    frappe.throw(_("BOM qatorida BOM tanlanmagan ({0}-qator).").format(row.idx))
                if flt(row.qty) <= 0:
                    frappe.throw(
                        _("BOM {0} uchun miqdor 0 dan katta bo'lishi kerak.").format(row.reference)
                    )
                new_rows.extend(self._explode_bom(row.reference, flt(row.qty)))
            else:
                item = row.reference or row.item_code
                new_rows.append(
                    {
                        "source_type": "Item",
                        "reference": item,
                        "item_code": item,
                        "item_name": row.item_name,
                        "qty": flt(row.qty),
                        "uom": row.uom,
                        "from_bom": row.from_bom,
                    }
                )

        # rate (tan narx) ni har qatorga o'rnatamiz
        for r in new_rows:
            if not r.get("item_code"):
                frappe.throw(_("Tovar tanlanmagan qator bor."))
            if not r.get("uom"):
                r["uom"] = frappe.get_cached_value("Item", r["item_code"], "stock_uom")
            rate = self._get_rate(r["item_code"], flt(r["qty"]))
            r["rate"] = rate
            r["amount"] = flt(r["qty"]) * flt(rate)

        self.set("items", new_rows)

    def _explode_bom(self, bom_no, bom_qty):
        """BOM ni bir pog'onali portlatadi (sub-assembly'larni rekursiv yoymaydi).
        component_qty = bom_qty * (component.qty / bom.quantity)."""
        bom = frappe.get_doc("BOM", bom_no)
        base_qty = flt(bom.quantity) or 1.0
        rows = []
        for c in bom.items:
            rows.append(
                {
                    "source_type": "Item",
                    "reference": c.item_code,
                    "item_code": c.item_code,
                    "item_name": c.item_name,
                    "qty": flt(bom_qty) * flt(c.qty) / base_qty,
                    "uom": c.stock_uom or c.uom,
                    "from_bom": bom_no,
                }
            )
        return rows

    def _get_rate(self, item_code, qty):
        """price_basis bo'yicha tan narx. Doimo ustamasiz."""
        basis = self.price_basis or "Valuation Rate"

        if basis == "Manual":
            # mavjud qator rate'ini saqlash uchun — _explode_and_rate Manual'da
            # rate'ni qayta yozmasligi kerak, lekin bu yerga kelsa 0 qaytaramiz
            return 0.0

        if basis == "Last Purchase Rate":
            return flt(frappe.db.get_value("Item", item_code, "last_purchase_rate"))

        # Valuation Rate (default) — from_warehouse dagi tan narx
        return self._get_valuation_rate(item_code, qty)

    def _get_valuation_rate(self, item_code, qty):
        """from_warehouse dagi joriy valuation rate (moving average).
        Avval Bin, bo'lmasa get_incoming_rate (outgoing)."""
        rate = frappe.db.get_value(
            "Bin", {"item_code": item_code, "warehouse": self.from_warehouse}, "valuation_rate"
        )
        if flt(rate) > 0:
            return flt(rate)

        try:
            from erpnext.stock.utils import get_incoming_rate

            rate = get_incoming_rate(
                {
                    "item_code": item_code,
                    "warehouse": self.from_warehouse,
                    "posting_date": self.posting_date,
                    "posting_time": nowtime(),
                    "qty": -1 * flt(qty),
                    "company": self.from_company,
                    "voucher_type": "Sales Invoice",
                    "serial_and_batch_bundle": None,
                },
                raise_error_if_no_rate=False,
            )
        except Exception:
            rate = 0

        if flt(rate) <= 0:
            frappe.msgprint(
                _("{0} uchun {1} omborida tan narx (valuation) topilmadi — 0 olindi.").format(
                    item_code, self.from_warehouse
                ),
                indicator="orange",
                alert=True,
            )
        return flt(rate)

    def _compute_totals(self):
        self.total_qty = sum(flt(r.qty) for r in self.items)
        self.total_amount = sum(flt(r.amount) for r in self.items)

    # ------------------------------------------------------------------ #
    #  ON SUBMIT — inter-company SI + PI
    # ------------------------------------------------------------------ #
    def on_submit(self):
        # Idempotentlik: ikki marta yaratmaymiz
        if self.sales_invoice:
            return

        internal_customer = _get_internal_customer(self.to_company)
        internal_supplier = _get_internal_supplier(self.from_company)

        # Atomik: commit chaqirilmaydi — xato bo'lsa Frappe butun so'rovni rollback qiladi
        si = self._create_sales_invoice(internal_customer)
        pi = self._create_purchase_invoice(si, internal_supplier)

        self.db_set("sales_invoice", si.name)
        self.db_set("purchase_invoice", pi.name)
        self.db_set("status", "Completed")

        frappe.msgprint(
            _("Sales Invoice <b>{0}</b> va Purchase Invoice <b>{1}</b> yaratildi (tan narxda).").format(
                frappe.utils.get_link_to_form("Sales Invoice", si.name),
                frappe.utils.get_link_to_form("Purchase Invoice", pi.name),
            ),
            indicator="green",
            alert=True,
        )

    def _create_sales_invoice(self, internal_customer):
        """Manba kompaniya — Sales Invoice (update_stock=1 → from_warehouse'dan chiqim).
        Narx = tan narx (qatordagi rate), ustamasiz, soliqsiz."""
        si = frappe.new_doc("Sales Invoice")
        si.company = self.from_company
        si.customer = internal_customer
        si.posting_date = self.posting_date
        si.set_posting_time = 1
        si.due_date = self.posting_date
        si.update_stock = 1
        si.set_warehouse = self.from_warehouse
        si.ignore_pricing_rule = 1
        si.taxes_and_charges = None
        si.selling_price_list = None

        for line in self.items:
            si.append(
                "items",
                {
                    "item_code": line.item_code,
                    "qty": flt(line.qty),
                    "uom": line.uom,
                    "conversion_factor": 1,
                    "rate": flt(line.rate),
                    "price_list_rate": flt(line.rate),
                    "warehouse": self.from_warehouse,
                    # tan narx 0 bo'lsa to'xtatmaymiz (prompt: warn, don't stop)
                    "allow_zero_valuation_rate": 1,
                },
            )

        si.flags.ignore_permissions = True
        si.flags.ignore_mandatory = True
        si.run_method("calculate_taxes_and_totals")
        si.insert(ignore_permissions=True)
        si.submit()
        return si

    def _create_purchase_invoice(self, si_doc, internal_supplier):
        """Maqsad kompaniya — inter-company Purchase Invoice (update_stock=1 → to_warehouse'ga kirim).

        PI ni QO'LDA tuzamiz (mapper o'rniga): omborni oldindan to_warehouse qilib
        qo'yamiz, shunda get_item_details uni item'ning default ombori (manba sklad)
        bilan almashtirmaydi. inter_company_invoice_reference orqali SI ga bog'lanadi."""
        inventory_account = frappe.db.get_value(
            "Company", self.to_company, "default_inventory_account"
        )

        pi = frappe.new_doc("Purchase Invoice")
        pi.company = self.to_company
        pi.supplier = internal_supplier
        pi.is_internal_supplier = 1
        pi.represents_company = self.to_company
        pi.inter_company_invoice_reference = si_doc.name
        pi.bill_no = si_doc.name
        pi.posting_date = self.posting_date
        pi.set_posting_time = 1
        pi.bill_date = self.posting_date
        pi.due_date = self.posting_date
        pi.update_stock = 1
        pi.set_warehouse = self.to_warehouse
        pi.ignore_pricing_rule = 1
        pi.buying_price_list = None
        pi.taxes_and_charges = None

        # SI qatorlari bilan bir tartibda (bog'lash uchun sales_invoice_item)
        for si_item, line in zip(si_doc.items, self.items):
            row = {
                "item_code": line.item_code,
                "qty": flt(line.qty),
                "uom": line.uom,
                "conversion_factor": 1,
                "rate": flt(line.rate),
                "price_list_rate": flt(line.rate),
                "warehouse": self.to_warehouse,
                "sales_invoice_item": si_item.name,
                "allow_zero_valuation_rate": 1,
            }
            if inventory_account:
                row["expense_account"] = inventory_account
            pi.append("items", row)

        pi.flags.ignore_permissions = True
        pi.flags.ignore_mandatory = True
        pi.run_method("calculate_taxes_and_totals")
        pi.insert(ignore_permissions=True)
        pi.submit()
        return pi

    # ------------------------------------------------------------------ #
    #  ON CANCEL — teskari tartibda
    # ------------------------------------------------------------------ #
    def on_cancel(self):
        # Avval PI (xaridor), keyin SI (sotuvchi) — bog'lanish tartibi shuni talab qiladi
        _cancel_if_submitted("Purchase Invoice", self.purchase_invoice)
        _cancel_if_submitted("Sales Invoice", self.sales_invoice)
        self.db_set("status", "Cancelled")


# ====================================================================== #
#  MODULE-LEVEL HELPERS
# ====================================================================== #
def _get_internal_customer(company):
    """company'ni ifodalovchi Internal Customer."""
    name = frappe.db.get_value(
        "Customer", {"is_internal_customer": 1, "represents_company": company}, "name"
    )
    if not name:
        frappe.throw(
            _("{0} kompaniyasi uchun Internal Customer topilmadi "
              "(is_internal_customer=1, represents_company={0}).").format(company)
        )
    return name


def _get_internal_supplier(company):
    """company'ni ifodalovchi Internal Supplier."""
    name = frappe.db.get_value(
        "Supplier", {"is_internal_supplier": 1, "represents_company": company}, "name"
    )
    if not name:
        frappe.throw(
            _("{0} kompaniyasi uchun Internal Supplier topilmadi "
              "(is_internal_supplier=1, represents_company={0}).").format(company)
        )
    return name


def _cancel_if_submitted(doctype, name):
    if not name or not frappe.db.exists(doctype, name):
        return
    doc = frappe.get_doc(doctype, name)
    if doc.docstatus == 1:
        doc.flags.ignore_permissions = True
        doc.cancel()


# ====================================================================== #
#  WHITELISTED API (client tugmalari uchun)
# ====================================================================== #
@frappe.whitelist()
def explode_boms(docname=None, doc=None):
    """BOM qatorlarni portlatib, narxlab, jadvalni qaytaradi (submitdan oldin ko'rish uchun)."""
    if doc:
        d = frappe.get_doc(json_loads(doc))
    else:
        d = frappe.get_doc("Branch Stock Transfer", docname)
    d._validate_companies()
    d._validate_warehouses()
    d._explode_and_rate()
    d._compute_totals()
    return {
        "items": [r.as_dict() for r in d.items],
        "total_qty": d.total_qty,
        "total_amount": d.total_amount,
    }


@frappe.whitelist()
def get_item_rate(item_code, from_warehouse, from_company, price_basis="Valuation Rate", qty=1, posting_date=None):
    """Bitta tovar uchun tan narx (frontend dan chaqiriladi)."""
    if not item_code:
        return {"rate": 0, "uom": None}
    tmp = frappe.new_doc("Branch Stock Transfer")
    tmp.from_warehouse = from_warehouse
    tmp.from_company = from_company
    tmp.price_basis = price_basis
    tmp.posting_date = posting_date or frappe.utils.today()
    rate = tmp._get_rate(item_code, flt(qty))
    return {"rate": rate, "uom": frappe.get_cached_value("Item", item_code, "stock_uom")}


def json_loads(value):
    import json

    return json.loads(value) if isinstance(value, str) else value
