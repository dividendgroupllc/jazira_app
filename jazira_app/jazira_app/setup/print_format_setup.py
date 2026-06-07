import frappe

SALES_ORDER_PRINT_FORMAT = "Заказ Jazira"
PURCHASE_ORDER_PRINT_FORMAT = "Харид буюртмаси (Telegram)"


def _upsert_print_format(name, doc_type, html_file):
	"""HTML faylga asoslangan Jinja print formatni yaratadi yoki yangilaydi."""
	path = frappe.get_app_path("jazira_app", "print_formats", html_file)
	with open(path, encoding="utf-8") as f:
		html_content = f.read()

	values = {
		"doc_type": doc_type,
		"module": "Jazira App",
		"custom_format": 1,
		"standard": "No",
		"print_format_for": "DocType",
		"print_format_type": "Jinja",
		"print_format_builder": 0,
		"print_format_builder_beta": 0,
		"raw_printing": 0,
		"disabled": 0,
		"font": "Calibri",
		"font_size": 12,
		"page_number": "Hide",
		"margin_top": 0,
		"margin_bottom": 0,
		"margin_left": 0,
		"margin_right": 0,
		"html": html_content,
	}

	if frappe.db.exists("Print Format", name):
		print_format = frappe.get_doc("Print Format", name)
		print_format.update(values)
		print_format.save(ignore_permissions=True)
	else:
		print_format = frappe.get_doc(
			{"doctype": "Print Format", "name": name, **values}
		)
		print_format.insert(ignore_permissions=True)

	frappe.clear_cache(doctype=doc_type)


def create_sales_order_print_format():
	"""Sales Order uchun 'nakladnaya' uslubidagi Jinja print format."""
	_upsert_print_format(
		SALES_ORDER_PRINT_FORMAT, "Sales Order", "sales_order_nakladnaya.html"
	)


def create_purchase_order_print_format():
	"""Purchase Order uchun Telegram'ga yuboriladigan PDF print format (narxsiz)."""
	_upsert_print_format(
		PURCHASE_ORDER_PRINT_FORMAT, "Purchase Order", "purchase_order_telegram.html"
	)
