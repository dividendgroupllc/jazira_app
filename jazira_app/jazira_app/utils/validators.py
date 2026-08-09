from typing import Dict, List, Optional
import frappe
from frappe import _

class ValidationError(Exception):
    """Custom exception for validation errors."""
    pass

# Hardcoded mapping for known misspellings or common variations
ITEM_MAPPING = {
    'Картошка чипс 100 гр': 'Картошка чипс зг',
    'Ок соус (собой)': 'Ок соус (стол)',
    'Пицца гуштли катта': 'Пицца гуштли',
    'Кизил соус (собой)': 'Кизил соус (стол)',

    'Фанта 2л (товар)': 'Фанта 2л',
    'Пизза Пеперони': 'Пицца Пеперони',
    'Пизза Пеперони кичик': 'Пицца Пеперони кичик',
    'Бардак чой чойнак': 'Бардак чой',
    'гошт 100 гр': 'гошт 50 гр', # Closest match if 100 is not there
    'Хот-дог булочкали (15000)': 'Хот-дог',
}

def validate_import_prerequisites(
    company: str,
    source_warehouse: str,
    posting_date: str,
    customer: str = ""
) -> Dict:
    """Validate all prerequisites before import."""
    errors = []
    if not company: errors.append(_("Company tanlanmagan"))
    if not source_warehouse: errors.append(_("Ombor tanlanmagan"))
    if not posting_date: errors.append(_("Sana tanlanmagan"))
    if not customer: errors.append(_("Mijoz tanlanmagan"))

    if company and source_warehouse:
        wh_company = frappe.db.get_value("Warehouse", source_warehouse, "company")
        if wh_company and wh_company != company:
            errors.append(_("Warehouse '{0}' kompaniyaga tegishli emas: {1}").format(source_warehouse, company))

    if customer and not frappe.db.exists("Customer", customer):
        errors.append(_("'{0}' nomli mijoz topilmadi").format(customer))

    return {"success": len(errors) == 0, "message": "\n".join(errors), "errors": errors}

def validate_warehouse_company(warehouse: str, company: str):
    """Validate that warehouse belongs to the given company."""
    wh_company = frappe.db.get_value("Warehouse", warehouse, "company")
    if wh_company and wh_company != company:
        raise ValidationError(
            _("Warehouse '{0}' kompaniyaga tegishli emas: {1}").format(warehouse, company)
        )

def validate_items_exist(items: List[Dict]) -> Dict:
    """Validate that all items exist in ERPNext, with mapping support."""
    valid_items = []
    errors = []
    
    # Cache for found items to speed up 11k rows
    item_cache = {}
    
    for item in items:
        original_name = item.get("item_name", "").strip()
        row_num = item.get("row_num", 0)
        
        if not original_name:
            continue

        if original_name in item_cache:
            item_code = item_cache[original_name]
        else:
            # 1. Apply mapping
            search_name = ITEM_MAPPING.get(original_name, original_name)
            
            # 2. Try exact match on name (Item Code)
            item_code = frappe.db.get_value("Item", {"name": search_name}, "name")
            
            # 3. Try exact match on item_name
            if not item_code:
                item_code = frappe.db.get_value("Item", {"item_name": search_name}, "name")
            
            # 4. Try partial match if still not found
            if not item_code:
                item_code = frappe.db.get_value("Item", {"item_name": ["like", f"%{search_name}%"]}, "name")
            
            item_cache[original_name] = item_code

        if item_code:
            item["item_code"] = item_code
            item["found"] = True
            valid_items.append(item)
        else:
            errors.append({
                "row": row_num,
                "item_name": original_name,
                "error": _("Item topilmadi: '{0}'").format(original_name)
            })
    
    return {
        "valid_items": valid_items,
        "errors": errors,
        "success": len(errors) == 0
    }

def check_duplicate_import(excel_hash: str, current_doc_name: str) -> Dict:
    """Check if this Excel file was already imported."""
    if not excel_hash:
        return {"is_duplicate": False, "existing_doc": None}
    
    existing = frappe.db.exists(
        "Jazira App Daily Sales Import",
        {
            "external_ref": excel_hash,
            "name": ["!=", current_doc_name],
            "status": "Processed"
        }
    )
    return {"is_duplicate": bool(existing), "existing_doc": existing}


def check_duplicate_dates(company: str, dates, current_doc_name: str) -> Dict:
    """Bu sanalar shu kompaniya uchun allaqachon import qilinganmi?

    check_duplicate_import() faqat Excel faylning hash'ini solishtiradi —
    fayl qayta eksport qilinsa yoki bitta katak o'zgartirilsa, hash boshqacha
    bo'lib, ayni kunni ikkinchi marta import qilish mumkin edi (amalda bir kun
    3 martagacha import qilingan holatlar bo'lgan).

    Bu tekshiruv esa sana darajasida ishlaydi: boshqa importga tegishli va
    hali SUBMIT holatida turgan Sales Invoice bor sanalarni bloklaydi.
    BEKOR QILINGAN (cancelled) SI to'sqinlik qilmaydi — ya'ni xato importni
    bekor qilib, o'sha kunni qayta yuklash bemalol mumkin.
    """
    dates = {str(d) for d in (dates or []) if d}
    if not dates or not company:
        return {"has_conflict": False, "conflicts": []}

    other_imports = frappe.get_all(
        "Jazira App Daily Sales Import",
        filters={"company": company, "name": ["!=", current_doc_name]},
        fields=["name", "sales_invoice"],
    )

    # Sales Invoice nomi -> uni yaratgan import hujjati
    si_owner = {}
    for imp in other_imports:
        if not imp.sales_invoice:
            continue
        for si_name in [s.strip() for s in imp.sales_invoice.split(",") if s.strip()]:
            si_owner.setdefault(si_name, imp.name)

    if not si_owner:
        return {"has_conflict": False, "conflicts": []}

    submitted = frappe.get_all(
        "Sales Invoice",
        filters={"name": ["in", list(si_owner.keys())], "docstatus": 1},
        fields=["name", "posting_date"],
    )

    conflicts = []
    seen_dates = set()
    for si in submitted:
        posting_date = str(si.posting_date)
        if posting_date in dates and posting_date not in seen_dates:
            seen_dates.add(posting_date)
            conflicts.append({
                "date": posting_date,
                "import_doc": si_owner[si.name],
                "sales_invoice": si.name,
            })

    conflicts.sort(key=lambda c: c["date"])
    return {"has_conflict": bool(conflicts), "conflicts": conflicts}
