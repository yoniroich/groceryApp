"""
telegram_bot.py
Thin wrapper around the raw Telegram Bot API (via httpx).
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
    """Header and summary text for the shopping message."""
    if not items:
        return "🛒 *Family Shopping List*\n\n_הרשימה ריקה כרגע._"

    bought = sum(1 for i in items if i.get("is_bought"))
    lines = [
        "🛒 *Family Shopping List*",
        f"📊 נאספו לעגלה: *{bought}/{len(items)}*",
        "",
        "_לחצו על מוצר כדי לסמן/לבטל V בסופר:_"
    ]
    return "\n".join(lines)


def build_shopping_keyboard(list_id: str, items: list[dict]) -> dict:
    """
    Creates an interactive inline keyboard where each item has its own toggle button,
    followed by the final 'Done Shopping' button.
    """
    keyboard = []

    sorted_items = sorted(items, key=lambda x: (x.get("category", ""), x.get("product_name", "")))

    for item in sorted_items:
        is_bought = item.get("is_bought", False)
        icon = "✅" if is_bought else "⬜"
        item_name = item["product_name"]
        qty = item.get("quantity", "1")
        cat_emoji = CATEGORY_EMOJI.get(item.get("category", ""), "🛒")

        button_text = f"{icon} {cat_emoji} {item_name} ({qty})"

        keyboard.append([
            {
                "text": button_text,
                "callback_data": f"toggle_item:{list_id}:{item['id']}"
            }
        ])

    keyboard.append([
        {"text": "🏁 סיימתי קנייה (סגירה והעברה)", "callback_data": f"done_shopping:{list_id}"}
    ])

    return {"inline_keyboard": keyboard}


async def send_or_update_list_message(list_id: str, items: list[dict], existing_message_id: int | None) -> int | None:
    """Sends or edits the interactive shopping message."""
    text = format_list_message(items)
    keyboard = build_shopping_keyboard(list_id, items)

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
        if not data.get("ok"):
            print(f"Telegram API Error: {data}")
            return None
            
        return data["result"]["message_id"]


async def mark_message_completed(message_id: int) -> None:
    async with httpx.AsyncClient() as client:
        await client.post(
            f"{API_URL}/editMessageText",
            json={
                "chat_id": GROUP_CHAT_ID,
                "message_id": message_id,
                "text": "🎉 *הקנייה הסתיימה בהצלחה!* כל הכבוד.",
                "parse_mode": "Markdown",
            },
        )


async def answer_callback_query(callback_query_id: str, text: str = "") -> None:
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