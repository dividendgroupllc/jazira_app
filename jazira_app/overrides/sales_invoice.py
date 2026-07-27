import frappe


def on_validate(doc, method=None):
	"""
	SI amended bo'lganda yangi valuation_rate × markup bilan narxlarni yangilaydi.
	Faqat inter-company amended SI lar uchun ishlaydi.
	"""
	if not doc.amended_from:
		return

	if not _is_inter_company_si(doc):
		return

	_recalculate_rates(doc)


def on_submit(doc, method=None):
	"""
	SI amended va submit bo'lganda linked PI ni ham amend qilib submit qiladi.
	"""
	if not doc.amended_from:
		return

	if not _is_inter_company_si(doc):
		return

	try:
		pi = _amend_and_submit_purchase_invoice(doc)
		if pi:
			frappe.msgprint(
				f"Purchase Invoice <b>{pi.name}</b> ham yangilandi va submit qilindi",
				alert=True,
				indicator="green",
			)
	except Exception:
		frappe.log_error(frappe.get_traceback(), "Inter Company PI Amend Error")
		frappe.msgprint(
			"Purchase Invoice amend qilishda xato. Loglarni tekshiring.",
			indicator="orange",
		)


def _is_inter_company_si(doc):
	"""SI inter-company ekanligini tekshiradi."""
	if not doc.customer:
		return False
	return bool(frappe.db.get_value("Customer", doc.customer, "is_internal_customer"))


def _historical_valuation_rate(item_code, warehouse, as_of_date):
	"""as_of_date holatidagi oxirgi Stock Ledger Entry'dan valuation_rate.

	Topilmasa (yoki as_of_date bo'lmasa) — joriy Bin valuation_rate'ga qaytadi.
	Eski (masalan iyun) SI amend qilinganda bugungi emas, o'sha davr tannarxi
	ishlatilishi uchun kerak — xuddi ury.ury.hooks.sklad_sales_order dagidek.
	"""
	if as_of_date:
		rate = frappe.db.get_value(
			"Stock Ledger Entry",
			{
				"item_code": item_code,
				"warehouse": warehouse,
				"posting_date": ["<=", as_of_date],
				"is_cancelled": 0,
			},
			"valuation_rate",
			order_by="posting_date desc, posting_time desc, creation desc",
		)
		if rate:
			return rate

	return frappe.db.get_value(
		"Bin", {"item_code": item_code, "warehouse": warehouse}, "valuation_rate"
	) or 0


def _recalculate_rates(doc):
	"""SI sanasidagi (posting_date) valuation_rate × markup bilan narxlarni yangilaydi."""
	branch_company = frappe.db.get_value("Customer", doc.customer, "represents_company")
	if not branch_company:
		return

	from jazira_app.overrides.sales_order import _get_markup_percent
	markup_percent = _get_markup_percent(branch_company)
	if not markup_percent:
		return

	# Sklad Settings (Single) dan main_warehouse (amend uchun valuation_rate bazasi)
	main_warehouse = frappe.db.get_single_value("Sklad Settings", "main_warehouse")
	if not main_warehouse:
		frappe.throw("Sklad Settings da 'Main Warehouse' belgilanmagan — SI amend uchun kerak.")

	# Asl (bekor qilingan) hujjatning o'z incoming_rate'i — ERPNext aynan shu
	# operatsiya uchun hisoblab qo'ygan haqiqiy tannarx (Prodaja Sheets ham
	# shundan o'qiydi). зг/yarim tayyor mahsulotlarda kun ichida bir necha marta
	# tannarx o'zgargani uchun "sana bo'yicha eng oxirgi SLE" qidiruvi (pastdagi
	# fallback) boshqa partiyaning qiymatini tanlab qo'yishi mumkin — asl
	# hujjatning o'zidagi qiymat esa aynan shu qatorga tegishli.
	original_rates = {}
	if doc.amended_from:
		original_rates = {
			row.item_code: row.incoming_rate
			for row in frappe.get_all(
				"Sales Invoice Item",
				filters={"parent": doc.amended_from},
				fields=["item_code", "incoming_rate"],
			)
			if row.incoming_rate
		}

	multiplier = 1 + (markup_percent / 100)
	for item in doc.items:
		valuation_rate = original_rates.get(item.item_code) or _historical_valuation_rate(
			item.item_code, main_warehouse, doc.posting_date
		)

		if not valuation_rate:
			continue

		item.rate = round(float(valuation_rate) * multiplier, 2)
		item.price_list_rate = item.rate
		item.amount = round(item.rate * item.qty, 2)

	doc.run_method("calculate_taxes_and_totals")


def _amend_and_submit_purchase_invoice(si_doc):
	"""Asl PI ni topib, amend qilib, yangi SI narxlari bilan submit qiladi."""
	original_si_name = si_doc.amended_from

	# Avval cancelled (docstatus=2) PI ni qidiramiz — to'g'ri holat
	original_pi_name = frappe.db.get_value(
		"Purchase Invoice",
		{"inter_company_invoice_reference": original_si_name, "docstatus": 2},
		"name",
	)

	if not original_pi_name:
		# Cancelled topilmasa — submitted yoki draft PI ni olmaymiz,
		# chunki ular qayta submit qilinishi xato beradi.
		frappe.msgprint(
			f"Cancelled Purchase Invoice topilmadi ({original_si_name} uchun). "
			f"PI ni avval cancel qiling, keyin SI ni amend qiling.",
			indicator="orange",
			title="PI Amend",
		)
		return None

	original_pi = frappe.get_doc("Purchase Invoice", original_pi_name)

	# Amended PI yaratish
	amended_pi = frappe.copy_doc(original_pi)
	amended_pi.amended_from = original_pi_name
	amended_pi.docstatus = 0
	amended_pi.inter_company_invoice_reference = si_doc.name
	amended_pi.update_stock = 1

	# SI dan yangilangan narxlarni PI ga ko'chirish
	si_items = {item.item_code: item for item in si_doc.items}
	for pi_item in amended_pi.items:
		if pi_item.item_code in si_items:
			pi_item.rate = si_items[pi_item.item_code].rate
			pi_item.amount = round(pi_item.rate * pi_item.qty, 2)

	amended_pi.flags.ignore_permissions = True
	amended_pi.insert(ignore_permissions=True)
	amended_pi.run_method("calculate_taxes_and_totals")
	amended_pi.submit()
	frappe.db.commit()

	return amended_pi
