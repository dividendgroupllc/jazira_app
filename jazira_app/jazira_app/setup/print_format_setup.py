import frappe

SALES_ORDER_PRINT_FORMAT = "Заказ Jazira"


def create_sales_order_print_format():
	"""Sales Order uchun 'nakladnaya' uslubidagi Jinja print format yaratadi/yangilaydi."""
	html = frappe.get_app_path(
		"jazira_app", "print_formats", "sales_order_nakladnaya.html"
	)
	with open(html, encoding="utf-8") as f:
		html_content = f.read()

	values = {
		"doc_type": "Sales Order",
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

	if frappe.db.exists("Print Format", SALES_ORDER_PRINT_FORMAT):
		print_format = frappe.get_doc("Print Format", SALES_ORDER_PRINT_FORMAT)
		print_format.update(values)
		print_format.save(ignore_permissions=True)
	else:
		print_format = frappe.get_doc(
			{
				"doctype": "Print Format",
				"name": SALES_ORDER_PRINT_FORMAT,
				**values,
			}
		)
		print_format.insert(ignore_permissions=True)

	frappe.clear_cache(doctype="Sales Order")
