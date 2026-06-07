"""Telegram bot orqali xabar yuborish (umumiy yordamchi).

Sozlamalar site_config.json da saqlanadi (kodda emas):
	telegram_bot_token   - @BotFather bergan bot token
	telegram_po_chat_ids - {"Company nomi": "guruh chat id", ...}
"""

import frappe
import requests

API_URL = "https://api.telegram.org/bot{token}/sendMessage"
TIMEOUT = 10


def get_bot_token():
	return frappe.conf.get("telegram_bot_token")


def send_message(chat_id, text, parse_mode="HTML"):
	"""Berilgan chat_id (guruh) ga xabar yuboradi. Xatolar log qilinadi, ko'tarilmaydi."""
	token = get_bot_token()
	if not token:
		frappe.log_error(
			"site_config.json da 'telegram_bot_token' sozlanmagan", "Telegram"
		)
		return
	if not chat_id:
		return

	try:
		resp = requests.post(
			API_URL.format(token=token),
			json={
				"chat_id": chat_id,
				"text": text,
				"parse_mode": parse_mode,
				"disable_web_page_preview": True,
			},
			timeout=TIMEOUT,
		)
		if resp.status_code != 200:
			frappe.log_error(
				f"Telegram javobi {resp.status_code}: {resp.text}", "Telegram"
			)
	except Exception:
		frappe.log_error(frappe.get_traceback(), "Telegram yuborishda xato")
