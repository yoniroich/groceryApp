"""
telegram_bot.py
Thin wrapper around the raw Telegram Bot API (via httpx) — no heavy
framework needed since we only send/edit messages and handle a
webhook FastAPI already receives. Keeps formatting logic in one place
so the "beautifully formatted" group message has a single source of truth.
"""

import os

import httpx

BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
GROUP_CHAT_ID = int(os.environ["TELEGRAM_GROUP_CHAT_ID"])
WEBAPP_BASE_URL = os.environ["WEBAPP_BASE_URL"]

API_URL = f"https://api.telegram.org/bot{BOT_TOKEN}"

CATEGORY_EMOJI = {
    "Dairy": "🥛",
    "Vegetables": "🥦",
    "Fruits": "🍎",
    "Meat & Poultry": "🍗",
    "Fish & Seafood": "🐟",
    "Bakery": "🍞",
    "Grains & Pasta": "🍝",
    "Canned & Jarred": "🥫",
    "Spices & Condiments": "🧂",
    "Frozen": "🧊",
    "Beverages": "🧃",
    "Household": "🧽",
    "Other": "🛒",
}


def format_list_message(items: list[dict]) -> str:
    """Builds the family-facing message, grouped by category, with
    bought items struck through so progress is visible at a glance."""
    if not items:
        return "🛒 *Family Shopping List*\n\n_The list is empty right now._"

    grouped: dict[str, list[dict]] = {}
    for item in items:
        grouped.setdefault(item["category"], []).append(item)

    lines = ["🛒 *Family Shopping List*", ""]
    for category in sorted(grouped):
        emoji = CATEGORY_EMOJI.get(category, "🛒")
        lines.append(f"{emoji} *{category}*")
        for item in grouped[category]:
            box = "✅" if item["is_bought"] else "▫️"
            name = item["product_name"]
            qty = item["quantity"]
            if item["is_bought"]:
                lines.append(f"{box} ~{name} — {qty}~")
            else:
                lines.append(f"{box} {name} — {qty}")
        lines.append("")

    bought = sum(1 for i in items if i["is_bought"])
    lines.append(f"_{bought}/{len(items)} items in the cart_")
    return "\n".join(lines)


def _done_shopping_keyboard(list_id: str) -> dict:
    return {
        "inline_keyboard": [
            [{"text": "🛒 Done Shopping", "callback_data": f"done_shopping:{list_id}"}]
        ]
    }


async def send_or_update_list_message(list_id: str, items: list[dict], existing_message_id: int | None) -> int:
    """Sends a new message the first time, edits it on every later
    'Update Family Telegram Group' tap so the group isn't spammed."""
    text = format_list_message(items)
    keyboard = _done_shopping_keyboard(list_id)

    async with httpx.AsyncClient() as client:
        if existing_message_id:
            resp = await client.post(
                f"{API_URL}/editMessageText",
                json={
                    "chat_id": GROUP_CHAT_ID,
                    "message_id": existing_message_id,
                    "text": text,
                    "parse_mode": "Markdown",
                    "reply_markup": keyboard,
                },
            )
            data = resp.json()
            if data.get("ok"):
                return existing_message_id
            # message may have been deleted in the group — fall through and send a new one

        resp = await client.post(
            f"{API_URL}/sendMessage",
            json={
                "chat_id": GROUP_CHAT_ID,
                "text": text,
                "parse_mode": "Markdown",
                "reply_markup": keyboard,
            },
        )
        data = resp.json()
        return data["result"]["message_id"]


async def mark_message_completed(message_id: int) -> None:
    async with httpx.AsyncClient() as client:
        await client.post(
            f"{API_URL}/editMessageText",
            json={
                "chat_id": GROUP_CHAT_ID,
                "message_id": message_id,
                "text": "✅ *Shopping complete!* Great job, team.",
                "parse_mode": "Markdown",
            },
        )


async def answer_callback_query(callback_query_id: str, text: str) -> None:
    async with httpx.AsyncClient() as client:
        await client.post(
            f"{API_URL}/answerCallbackQuery",
            json={"callback_query_id": callback_query_id, "text": text},
        )


async def send_dm(chat_id: int, text: str, reply_markup: dict | None = None) -> None:
    payload = {"chat_id": chat_id, "text": text, "parse_mode": "Markdown"}
    if reply_markup:
        payload["reply_markup"] = reply_markup
    async with httpx.AsyncClient() as client:
        await client.post(f"{API_URL}/sendMessage", json=payload)


def validation_link(session_id: str) -> str:
    return f"{WEBAPP_BASE_URL}/?recipe_session={session_id}"


async def set_webhook(webhook_url: str, secret_token: str) -> dict:
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"{API_URL}/setWebhook",
            json={"url": webhook_url, "secret_token": secret_token},
        )
        return resp.json()
