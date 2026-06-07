"""Purchase Order submit bo'lganda company guruhiga Telegram xabari yuboradi.

Har bir company (filial) uchun alohida guruh. Mapping site_config.json da:
	"telegram_po_chat_ids": {
		"Jazira Saripul": "-1001111111111",
		"Jazira Sklad":   "-1002222222222"
	}
"""

import frappe
from frappe.utils import escape_html, flt, fmt_money, format_date, get_fullname

# Telegram bitta xabar uchun ~4096 belgi cheklovi bor — ko'p bo'lsa qisqartiramiz
MAX_ITEMS = 50


def on_submit(doc, method=None):
	chat_id = _get_chat_id(doc.company)
	if not chat_id:
		# Bu company uchun guruh sozlanmagan — jim o'tamiz
		return

	text = _build_message(doc)

	# Submit jarayonini sekinlashtirmaslik uchun fon (background) da yuboramiz
	frappe.enqueue(
		"jazira_app.jazira_app.integrations.telegram.send_message",
		queue="short",
		chat_id=chat_id,
		text=text,
	)


def _get_chat_id(company):
	mapping = frappe.conf.get("telegram_po_chat_ids") or {}
	return mapping.get(company)


def _qty(value):
	value = flt(value)
	return ("%f" % value).rstrip("0").rstrip(".") if value else "0"


def _build_message(doc):
	currency = doc.currency
	supplier = doc.supplier_name or doc.supplier
	created_by = get_fullname(doc.owner)

	lines = [
		"🧾 <b>Янги харид буюртмаси</b>",
		"",
		f"🏢 <b>Компания:</b> {escape_html(doc.company)}",
		f"🔢 <b>Рақам:</b> {escape_html(doc.name)}",
		f"📅 <b>Сана:</b> {escape_html(format_date(doc.transaction_date))}",
		f"🚚 <b>Таъминотчи:</b> {escape_html(supplier)}",
	]

	if doc.get("schedule_date"):
		lines.append(
			f"📦 <b>Етказиб бериш:</b> {escape_html(format_date(doc.schedule_date))}"
		)

	lines.append(f"👤 <b>Яратди:</b> {escape_html(created_by)}")
	lines.append("")
	lines.append("📋 <b>Маҳсулотлар:</b>")

	items = doc.items or []
	for i, item in enumerate(items[:MAX_ITEMS], start=1):
		name = escape_html(item.item_name or item.item_code)
		uom = escape_html(item.uom or item.stock_uom or "")
		qty = _qty(item.qty)
		rate = fmt_money(item.rate, currency=currency)
		amount = fmt_money(item.amount, currency=currency)
		lines.append(f"{i}. {name} — {qty} {uom} × {rate} = {amount}")

	if len(items) > MAX_ITEMS:
		lines.append(f"… ва яна {len(items) - MAX_ITEMS} та маҳсулот")

	lines.append("")
	lines.append(f"💰 <b>Жами:</b> {fmt_money(doc.grand_total, currency=currency)}")

	return "\n".join(lines)
