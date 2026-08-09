import frappe
from frappe import _
from frappe.model.document import Document

from jazira_app.jazira_app.utils.validators import validate_warehouse_company, ValidationError


class JaziraAppDailySalesImport(Document):
    """
    Restaurant Daily Sales Import Document.
    
    Workflow:
    1. User uploads Excel file
    2. Preview shows items with BOM status
    3. Process Import creates:
       - Manufacture Stock Entries (for BOM items)
       - Sales Invoice (for all items)
    """
    
    def validate(self):
        """Validate document before save."""
        self._validate_warehouse()
    
    def _validate_warehouse(self):
        """Ensure warehouse belongs to company."""
        if self.source_warehouse and self.company:
            try:
                validate_warehouse_company(self.source_warehouse, self.company)
            except ValidationError as e:
                frappe.throw(str(e))
    
    def before_submit(self):
        """Prevent manual submission."""
        frappe.throw(
            _("This document cannot be submitted. Use 'Process Import' button.")
        )
    
    def on_trash(self):
        """Hujjat o'chirilganda u yaratgan Sales Invoice va Stock Entry'larni
        ham bekor qiladi.

        Avval faqat "Processed" statusni o'chirish bloklanardi. Lekin import
        har bir sanani alohida commit qiladi — 11 kundan 5-chisida xato bo'lsa,
        birinchi 4 kunning SI'si allaqachon submit bo'lgan holda status
        "Failed" bo'lib qolardi va bunday hujjatni o'chirish mumkin edi.
        Natijada tizimda egasiz (hech qaysi importga bog'lanmagan) submit
        qilingan hujjatlar qolib ketardi. Endi status'idan qat'iy nazar,
        bog'langan hujjatlar avval bekor qilinadi.
        """
        from jazira_app.jazira_app.services import invoice_service, stock_service

        # Tartib muhim: avval SI (sotilgan mahsulotni omborga qaytaradi),
        # keyin SE (ishlab chiqarishni orqaga qaytaradi) — cancel_import
        # bilan bir xil tartib.
        cancelled_si = []
        if self.sales_invoice:
            for si_name in [s.strip() for s in self.sales_invoice.split(",") if s.strip()]:
                if invoice_service.cancel_invoice(si_name):
                    cancelled_si.append(si_name)

        cancelled_se = 0
        if self.stock_entry:
            se_names = [s.strip() for s in self.stock_entry.split(",") if s.strip()]
            cancelled_se = stock_service.cancel_stock_entries(se_names)

        if cancelled_si or cancelled_se:
            frappe.msgprint(
                _("Import o'chirildi. Bekor qilindi: {0} ta Sales Invoice, {1} ta Stock Entry.").format(
                    len(cancelled_si), cancelled_se
                ),
                indicator="orange",
                alert=True,
            )


# =============================================================================
# WHITELISTED METHODS (Delegated to API module)
# =============================================================================
# 
# All whitelisted methods are in:
# jazira_app/api/daily_sales_import.py
#
# Client Script calls:
#   frappe.call({
#       method: 'jazira_app.api.daily_sales_import.process_import',
#       args: { doc_name: frm.doc.name }
#   });
#
# =============================================================================
