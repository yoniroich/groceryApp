"""
main.py - Fixed Static HTML Routing with Direct Item Lookup and Multi-column Layout
"""

import os
import httpx
from fastapi import FastAPI, HTTPException, Header, Request
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv
from bs4 import BeautifulSoup

import database as db
import telegram_bot as tg
from models import (
    NewMasterProduct,
    AddItemsRequest,
    UpdateListItemRequest,
    MergeRecipeSessionRequest,
)
import recipe_parser as parser

load_dotenv()

WEBHOOK_SECRET = os.environ["TELEGRAM_WEBHOOK_SECRET"]
TELEGRAM_BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]

app = FastAPI(title="Smart Family Grocery API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

async def scrape_url(url: str) -> str:
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(url, headers={"User-Agent": "Mozilla/5.0"})
            if response.status_code == 200:
                soup = BeautifulSoup(response.text, "html.parser")
                for script in soup(["script", "style"]):
                    script.extract()
                return soup.get_text(separator="\n", strip=True)
    except Exception as e:
        print(f"Failed to scrape URL {url}: {e}")
    return ""

# =================================================================
# Serve Static Frontend
# =================================================================
@app.get("/")
def serve_frontend(session_id: str | None = None):
    return FileResponse("index.html")

# =================================================================
# Master product catalog
# =================================================================
@app.get("/api/master-products")
def list_master_products():
    return db.get_master_products_grouped()

@app.post("/api/master-products")
def create_master_product(payload: NewMasterProduct):
    return db.add_master_product(payload.name, payload.category)

# =================================================================
# Active shopping list
# =================================================================
@app.get("/api/active-list")
def get_active_list():
    active = db.get_or_create_active_list()
    return db.get_list_with_items(active["id"])

@app.post("/api/active-list/items")
def add_items_to_active_list(payload: AddItemsRequest):
    active = db.get_or_create_active_list()
    items = [item.model_dump() for item in payload.items]
    return db.add_list_items(active["id"], items, source="manual")

@app.patch("/api/list-items/{item_id}")
def update_item(item_id: str, payload: UpdateListItemRequest):
    return db.update_list_item(item_id, quantity=payload.quantity, is_bought=payload.is_bought)

@app.delete("/api/list-items/{item_id}")
def remove_item(item_id: str):
    db.delete_list_item(item_id)
    return {"deleted": True}

# =================================================================
# Recipe validation area
# =================================================================
@app.get("/api/recipe-session/{session_id}")
def get_recipe_session(session_id: str):
    session = db.get_recipe_session(session_id)
    if not session:
        raise HTTPException(404, "Recipe session not found or already merged")
    return session

@app.post("/api/recipe-session/{session_id}/merge")
def merge_recipe_session(session_id: str, payload: MergeRecipeSessionRequest):
    active = db.get_or_create_active_list()
    items = [item.model_dump() for item in payload.items]
    created = db.add_list_items(active["id"], items, source="recipe")
    db.mark_recipe_session_merged(session_id)
    return {"merged_count": len(created), "list_id": active["id"]}

# =================================================================
# Update Family Telegram Group
# =================================================================
@app.post("/api/telegram/send-list")
async def send_list_to_telegram():
    active = db.get_or_create_active_list()
    full = db.get_list_with_items(active["id"])
    message_id = await tg.send_or_update_list_message(
        list_id=full["id"],
        items=full["items"],
        existing_message_id=full.get("telegram_message_id"),
    )
    if message_id:
        db.set_list_telegram_message(full["id"], tg.GROUP_CHAT_ID, message_id)
    return {"telegram_message_id": message_id}

# =================================================================
# Telegram webhook
# =================================================================
@app.post("/api/telegram/webhook")
async def telegram_webhook(request: Request, x_telegram_bot_api_secret_token: str | None = Header(None)):
    if x_telegram_bot_api_secret_token != WEBHOOK_SECRET:
        raise HTTPException(401, "Invalid webhook secret")

    update = await request.json()

    if "callback_query" in update:
        cq = update["callback_query"]
        data = cq.get("data", "")

        # 1. סימון מוצר ישירות לפי item_id ב-DB
        if data.startswith("t:"):
            item_id = data.split(":", 1)[1]
            
            res = db.supabase.table("list_items").select("*").eq("id", item_id).execute()
            if res.data:
                item = res.data[0]
                list_id = item["list_id"]
                new_status = not item.get("is_bought", False)
                db.update_list_item(item_id, is_bought=new_status)

                updated_list = db.get_list_with_items(list_id)
                msg_id = cq["message"]["message_id"]
                await tg.send_or_update_list_message(list_id, updated_list["items"], existing_message_id=msg_id)

                feedback = "סומן כנקנה ✅" if new_status else "הוחזר לרשימה ⬜"
                await tg.answer_callback_query(cq["id"], feedback)
            else:
                await tg.answer_callback_query(cq["id"], "מוצר לא נמצא")
            return {"ok": True}

        # 2. סיום קנייה
        if data.startswith("done:"):
            list_id = data.split(":", 1)[1]
            
            res_summary = db.close_list(list_id)
            remaining = res_summary.get("remaining_count", 0)
            msg_id = cq["message"]["message_id"]
            
            await tg.mark_message_completed(msg_id)
            
            if remaining > 0:
                answer_msg = f"🛒 הקנייה הסתיימה! {remaining} מוצרים שלא סומנו הועברו לרשימה הבאה."
                new_list_id = res_summary.get("new_list_id")
                if new_list_id:
                    new_list = db.get_list_with_items(new_list_id)
                    new_msg_id = await tg.send_or_update_list_message(new_list_id, new_list["items"], None)
                    if new_msg_id:
                        db.set_list_telegram_message(new_list_id, tg.GROUP_CHAT_ID, new_msg_id)
            else:
                answer_msg = "🎉 כל הכבוד! כל המוצרים סומנו והקנייה נסגרה לחלוטין."

            await tg.answer_callback_query(cq["id"], answer_msg)
            return {"ok": True}

        return {"ok": True}

    if "message" in update:
        msg = update["message"]
        chat_id = msg["chat"]["id"]
        user_id = msg["from"]["id"]
        
        parsed_items = []
        raw_source_text = ""

        if "text" in msg:
            text_content = msg["text"].strip()

            if text_content.startswith("/start"):
                await tg.send_dm(
                    chat_id,
                    "👋 שלום! שלחו לי מתכון (טקסט, קישור, או תמונה) ואחלץ ממנו את המצרכים עבורכם.",
                )
                return {"ok": True}

            if text_content.startswith("http://") or text_content.startswith("https://"):
                await tg.send_dm(chat_id, "🔍 אני קורא ומנתח את המתכון מתוך הקישור, רגע אחד...")
                raw_source_text = await scrape_url(text_content)
                if not raw_source_text:
                    await tg.send_dm(chat_id, "❌ לא הצלחתי לקרוא את תוכן האתר. נסו להעתיק את הטקסט ידנית.")
                    return {"ok": True}
            else:
                raw_source_text = text_content

            parsed_items = await parser.parse_recipe_text(raw_source_text)

        elif "photo" in msg:
            await tg.send_dm(chat_id, "📸 קיבלתי תמונה! אני מפעיל את ג'מיני כדי לחלץ את המצרכים...")
            photo_sizes = msg["photo"]
            best_photo = photo_sizes[-1]
            file_id = best_photo["file_id"]
            
            async with httpx.AsyncClient(timeout=15.0) as client:
                file_info_res = await client.get(f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/getFile?file_id={file_id}")
                file_path = file_info_res.json()["result"]["file_path"]
                image_res = await client.get(f"https://api.telegram.org/file/bot{TELEGRAM_BOT_TOKEN}/{file_path}")
                image_bytes = image_res.content
                
            raw_source_text = f"Image Recipe: {file_path}"
            parsed_items = await parser.parse_recipe_image(image_bytes, mime_type="image/jpeg")

        if parsed_items:
            session = db.create_recipe_session(
                telegram_user_id=user_id,
                telegram_chat_id=chat_id,
                source_text=raw_source_text[:1000],
                items=parsed_items,
            )
            
            magic_link = f"{os.environ['WEBAPP_BASE_URL']}/?session_id={session['id']}"
            message_text = f"🍽 נמצאו {len(parsed_items)} מצרכים במתכון!\nלחצו על הקישור הבא כדי לאשר ולעדכן את הרשימה המשפחתית:\n\n{magic_link}"
            
            async with httpx.AsyncClient() as client:
                telegram_url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
                await client.post(telegram_url, json={"chat_id": chat_id, "text": message_text})
        else:
            if "text" in msg and not msg["text"].startswith("/"):
                async with httpx.AsyncClient() as client:
                    telegram_url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
                    await client.post(telegram_url, json={"chat_id": chat_id, "text": "😕 לא הצלחתי למצוא מצרכים ברורים בקלט ששלחתם. נסו שוב."})

        return {"ok": True}

    return {"ok": True}

@app.get("/health")
def health():
    return {"status": "ok"}