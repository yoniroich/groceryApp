"""
database.py
Thin data-access layer over Supabase (PostgreSQL). Keeping every
query in one place makes it easy to swap the client later or add
caching without touching route/bot logic.
"""

import os
from datetime import datetime, timezone
from typing import Optional

from dotenv import load_dotenv
from supabase import create_client, Client

load_dotenv()

SUPABASE_URL = os.environ["SUPABASE_URL"]
SUPABASE_SERVICE_ROLE_KEY = os.environ["SUPABASE_SERVICE_ROLE_KEY"]

supabase: Client = create_client(SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY)


# ---------------------------------------------------------------
# master_products
# ---------------------------------------------------------------
def get_master_products_grouped() -> dict[str, list[dict]]:
    """Returns {category: [product, ...]} sorted by category then name."""
    res = (
        supabase.table("master_products")
        .select("*")
        .order("category")
        .order("name")
        .execute()
    )
    grouped: dict[str, list[dict]] = {}
    for product in res.data:
        grouped.setdefault(product["category"], []).append(product)
    return grouped


def add_master_product(name: str, category: str) -> dict:
    """Upsert so re-adding an existing product name doesn't error out."""
    res = (
        supabase.table("master_products")
        .upsert({"name": name.strip(), "category": category.strip()}, on_conflict="name")
        .execute()
    )
    return res.data[0]


# ---------------------------------------------------------------
# shopping_lists
# ---------------------------------------------------------------
def get_or_create_active_list() -> dict:
    res = (
        supabase.table("shopping_lists")
        .select("*")
        .eq("status", "active")
        .limit(1)
        .execute()
    )
    if res.data:
        return res.data[0]

    created = supabase.table("shopping_lists").insert({"status": "active"}).execute()
    return created.data[0]


def get_list_with_items(list_id: str) -> dict:
    list_res = supabase.table("shopping_lists").select("*").eq("id", list_id).single().execute()
    items_res = (
        supabase.table("list_items")
        .select("*")
        .eq("list_id", list_id)
        .order("category")
        .order("created_at")
        .execute()
    )
    return {**list_res.data, "items": items_res.data}


def set_list_telegram_message(list_id: str, chat_id: int, message_id: int) -> None:
    supabase.table("shopping_lists").update(
        {"telegram_chat_id": chat_id, "telegram_message_id": message_id}
    ).eq("id", list_id).execute()


def close_list(list_id: str) -> dict:
    """
    סוגרת את הרשימה הנוכחית.
    מצרכים שסומנו (is_bought=True) נשארים ברשימה הנגמרת.
    מצרכים שלא סומנו (is_bought=False) מועברים אוטומטית לרשימה פעילה חדשה.
    """
    # 1. שליפת כל המצרכים ברשימה הנוכחית
    res = supabase.table("list_items").select("*").eq("list_id", list_id).execute()
    all_items = res.data or []

    bought_items = [item for item in all_items if item.get("is_bought") is True]
    unbought_items = [item for item in all_items if not item.get("is_bought")]

    # 2. סגירת הרשימה הנוכחית בסטטוס completed
    completed_res = (
        supabase.table("shopping_lists")
        .update({"status": "completed", "completed_at": datetime.now(timezone.utc).isoformat()})
        .eq("id", list_id)
        .execute()
    )

    # 3. אם נשארו מוצרים שלא נקנו - פותחים רשימה חדשה ומעבירים אותם אליה
    new_list_id = None
    if unbought_items:
        new_list_res = supabase.table("shopping_lists").insert({"status": "active"}).execute()
        new_list_id = new_list_res.data[0]["id"]

        new_rows = [
            {
                "list_id": new_list_id,
                "product_name": item["product_name"],
                "category": item["category"],
                "quantity": item.get("quantity", "1"),
                "is_bought": False,
                "source": item.get("source", "manual")
            }
            for item in unbought_items
        ]
        supabase.table("list_items").insert(new_rows).execute()

    return {
        "closed_list": completed_res.data[0] if completed_res.data else {},
        "new_list_id": new_list_id,
        "remaining_count": len(unbought_items)
    }


# ---------------------------------------------------------------
# list_items
# ---------------------------------------------------------------
def add_list_items(list_id: str, items: list[dict], source: str = "manual") -> list[dict]:
    """items: [{product_name, category, quantity}]"""
    rows = [
        {
            "list_id": list_id,
            "product_name": item["product_name"],
            "category": item["category"],
            "quantity": str(item.get("quantity", "1")),
            "source": source,
        }
        for item in items
    ]
    if not rows:
        return []
    res = supabase.table("list_items").insert(rows).execute()
    return res.data


def update_list_item(item_id: str, quantity: Optional[str] = None, is_bought: Optional[bool] = None) -> dict:
    patch = {}
    if quantity is not None:
        patch["quantity"] = quantity
    if is_bought is not None:
        patch["is_bought"] = is_bought
    res = supabase.table("list_items").update(patch).eq("id", item_id).execute()
    return res.data[0]


def delete_list_item(item_id: str) -> None:
    supabase.table("list_items").delete().eq("id", item_id).execute()


# ---------------------------------------------------------------
# recipe_sessions
# ---------------------------------------------------------------
def create_recipe_session(telegram_user_id: int, telegram_chat_id: int, source_text: str, items: list[dict]) -> dict:
    # default every parsed ingredient to "checked" per spec
    for item in items:
        item.setdefault("checked", True)
    res = (
        supabase.table("recipe_sessions")
        .insert(
            {
                "telegram_user_id": telegram_user_id,
                "telegram_chat_id": telegram_chat_id,
                "source_text": source_text,
                "items": items,
            }
        )
        .execute()
    )
    return res.data[0]


def get_recipe_session(session_id: str) -> dict:
    res = supabase.table("recipe_sessions").select("*").eq("id", session_id).single().execute()
    return res.data


def mark_recipe_session_merged(session_id: str) -> None:
    supabase.table("recipe_sessions").update({"status": "merged"}).eq("id", session_id).execute()