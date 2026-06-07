"""Purchase Order submit/cancel bo'lganda company guruhiga Telegram xabari yuboradi.

Har bir company (filial) uchun alohida guruh. Mapping site_config.json da:
	"telegram_po_chat_ids": {
		"Jazira Saripul": "-1001111111111",
		"Jazira Sklad":   "-1002222222222"
	}

Submit'da guruhga PO ning PDF si yuboriladi; uning message_id si PO ning custom
maydonida saqlanadi. Cancel bo'lganda "бекор қилинди" xabari o'sha PDF ga reply
qilib yuboriladi.
"""

import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields
from frappe.utils import escape_html, get_fullname

from jazira_app.jazira_app.integrations.telegram import send_document, send_message

# Submit PDF xabarining message_id si shu maydonda saqlanadi (cancel'da reply uchun)
MSG_ID_FIELD = "custom_telegram_message_id"

_TASK = "jazira_app.jazira_app.overrides.purchase_order.send_notification"


def on_submit(doc, method=None):
	if not _get_chat_id(doc.company):
		return
	frappe.enqueue(
		_TASK,
		queue="short",
		enqueue_after_commit=True,
		po_name=doc.name,
		action="submit",
	)


def on_cancel(doc, method=None):
	if not _get_chat_id(doc.company):
		return
	frappe.enqueue(
		_TASK,
		queue="short",
		enqueue_after_commit=True,
		po_name=doc.name,
		action="cancel",
	)


def send_notification(po_name, action):
	"""Background task — PO bo'yicha submit (PDF) yoki cancel (reply) xabarini yuboradi."""
	doc = frappe.get_doc("Purchase Order", po_name)
	chat_id = _get_chat_id(doc.company)
	if not chat_id:
		return

	if action == "submit":
		pdf = _generate_pdf(doc)
		result = send_document(
			chat_id,
			pdf,
			filename=f"{po_name}.pdf",
			caption=_build_caption(doc),
		)
		message_id = (result or {}).get("message_id")
		if message_id:
			frappe.db.set_value(
				"Purchase Order",
				po_name,
				MSG_ID_FIELD,
				str(message_id),
				update_modified=False,
			)
			frappe.db.commit()
	elif action == "cancel":
		reply_to = doc.get(MSG_ID_FIELD)
		send_message(
			chat_id, _build_cancel_message(doc), reply_to_message_id=reply_to
		)


def _get_chat_id(company):
	mapping = frappe.conf.get("telegram_po_chat_ids") or {}
	return mapping.get(company)


def _generate_pdf(doc):
	"""PO ni PDF ga aylantiradi. Print formatning HTML shabloni to'liq inline
	uslubga ega — shuning uchun tashqi resurs (sayt hosti/asset) talab qilmaydi."""
	from frappe.utils.pdf import get_pdf

	template_path = frappe.get_app_path(
		"jazira_app", "print_formats", "purchase_order_telegram.html"
	)
	with open(template_path, encoding="utf-8") as f:
		template = f.read()

	body = frappe.render_template(template, {"doc": doc})
	html = (
		"<!DOCTYPE html><html><head><meta charset='utf-8'></head>"
		"<body class='print-format'>" + body + "</body></html>"
	)
	return get_pdf(html)


def _build_caption(doc):
	"""PDF ga qisqa izoh (caption) — guruhda o'qish uchun."""
	lines = [
		"🧾 <b>Янги харид буюртмаси</b>",
		f"🏢 <b>Компания:</b> {escape_html(doc.company)}",
		f"🔢 <b>Рақам:</b> {escape_html(doc.name)}",
		f"🚚 <b>Таъминотчи:</b> {escape_html(doc.supplier_name or doc.supplier)}",
		f"👤 <b>Яратди:</b> {escape_html(get_fullname(doc.owner))}",
	]
	return "\n".join(lines)


def _build_cancel_message(doc):
	cancelled_by = get_fullname(doc.modified_by)
	lines = [
		"❌ <b>Харид буюртмаси БЕКОР ҚИЛИНДИ</b>",
		"",
		f"🏢 <b>Компания:</b> {escape_html(doc.company)}",
		f"🔢 <b>Рақам:</b> {escape_html(doc.name)}",
		f"🚚 <b>Таъминотчи:</b> {escape_html(doc.supplier_name or doc.supplier)}",
		f"👤 <b>Бекор қилди:</b> {escape_html(cancelled_by)}",
	]
	return "\n".join(lines)


def ensure_custom_fields():
	"""message_id saqlash uchun yashirin custom maydonni yaratadi (idempotent)."""
	create_custom_fields(
		{
			"Purchase Order": [
				{
					"fieldname": MSG_ID_FIELD,
					"label": "Telegram Message ID",
					"fieldtype": "Data",
					"read_only": 1,
					"hidden": 1,
					"no_copy": 1,
					"print_hide": 1,
					"translatable": 0,
				}
			]
		},
		ignore_validate=True,
	)
