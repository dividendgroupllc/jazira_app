"""Telegram bot orqali xabar yuborish (umumiy yordamchi).

Sozlamalar site_config.json da saqlanadi (kodda emas):
	telegram_bot_token   - @BotFather bergan bot token
	telegram_po_chat_ids - {"Company nomi": "guruh chat id", ...}
"""

import frappe
import requests

API_URL = "https://api.telegram.org/bot{token}/sendMessage"
DOC_API_URL = "https://api.telegram.org/bot{token}/sendDocument"
TIMEOUT = 30


def get_bot_token():
	return frappe.conf.get("telegram_bot_token")


def send_message(chat_id, text, parse_mode="HTML", reply_to_message_id=None):
	"""Berilgan chat_id (guruh) ga xabar yuboradi.

	Muvaffaqiyatli bo'lsa Telegram natija (result) lug'atini qaytaradi
	(ichida message_id bor), aks holda None. Xatolar log qilinadi, ko'tarilmaydi.
	"""
	token = get_bot_token()
	if not token:
		frappe.log_error(
			"site_config.json da 'telegram_bot_token' sozlanmagan", "Telegram"
		)
		return None
	if not chat_id:
		return None

	payload = {
		"chat_id": chat_id,
		"text": text,
		"parse_mode": parse_mode,
		"disable_web_page_preview": True,
	}
	if reply_to_message_id:
		payload["reply_to_message_id"] = reply_to_message_id
		# Asl xabar o'chirilgan bo'lsa ham xabar baribir yuborilsin
		payload["allow_sending_without_reply"] = True

	try:
		resp = requests.post(
			API_URL.format(token=token), json=payload, timeout=TIMEOUT
		)
		data = resp.json()
		if not data.get("ok"):
			frappe.log_error(
				f"Telegram javobi {resp.status_code}: {resp.text}", "Telegram"
			)
			return None
		return data.get("result")
	except Exception:
		frappe.log_error(frappe.get_traceback(), "Telegram yuborishda xato")
		return None


def send_document(
	chat_id, file_content, filename, caption=None, parse_mode="HTML",
	reply_to_message_id=None
):
	"""Guruhga fayl (PDF) yuboradi. Muvaffaqiyatli bo'lsa result lug'atini qaytaradi."""
	token = get_bot_token()
	if not token:
		frappe.log_error(
			"site_config.json da 'telegram_bot_token' sozlanmagan", "Telegram"
		)
		return None
	if not chat_id:
		return None

	data = {"chat_id": chat_id}
	if caption:
		data["caption"] = caption
		data["parse_mode"] = parse_mode
	if reply_to_message_id:
		data["reply_to_message_id"] = reply_to_message_id
		data["allow_sending_without_reply"] = True

	files = {"document": (filename, file_content, "application/pdf")}

	try:
		resp = requests.post(
			DOC_API_URL.format(token=token),
			data=data,
			files=files,
			timeout=TIMEOUT,
		)
		result = resp.json()
		if not result.get("ok"):
			frappe.log_error(
				f"Telegram (document) javobi {resp.status_code}: {resp.text}",
				"Telegram",
			)
			return None
		return result.get("result")
	except Exception:
		frappe.log_error(frappe.get_traceback(), "Telegram fayl yuborishda xato")
		return None
