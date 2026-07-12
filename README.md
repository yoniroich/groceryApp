# Smart Family Grocery

A mobile-first shopping list web app backed by Supabase, with a Telegram
bot that turns pasted recipes into reviewable ingredient lists and posts
the live shopping list to your family group.

## Architecture

```
┌─────────────────┐        ┌──────────────────────┐        ┌─────────────┐
│  index.html      │  REST  │   FastAPI backend     │  SQL   │  Supabase    │
│  (Tailwind+Alpine)│◄──────►│   main.py              │◄──────►│  Postgres    │
└─────────────────┘        │   database.py          │        └─────────────┘
                            │   telegram_bot.py      │
        Telegram ◄──────────┤   recipe_parser.py     │
        (webhook + DM)      └──────────────────────┘
                                       │
                                  Anthropic API
                                (recipe → JSON)
```

- **Web app** (`frontend/index.html`) — single file, no build step. Browse
  the master catalog by category, tap items onto the active list with a
  quantity stepper, add brand-new products permanently, review recipe
  ingredients, and push the list to Telegram.
- **Backend** (`backend/`) — FastAPI service exposing a small REST API for
  the web app and a single webhook endpoint for Telegram.
- **Database** (`supabase/schema.sql`) — four tables: `master_products`,
  `shopping_lists`, `list_items`, plus `recipe_sessions` (temporary holding
  area for parsed recipe ingredients pending review).

## Setup

### 1. Supabase
1. Create a project at supabase.com.
2. Open the SQL editor and run `supabase/schema.sql`.
3. Import your Excel catalog into `master_products` (Table Editor → Import
   data from CSV — export your Excel sheet to CSV first with `name,category`
   columns).
4. Copy your project URL and `service_role` key into `backend/.env`.

### 2. Telegram bot
1. Create a bot with [@BotFather](https://t.me/BotFather), grab the token.
2. Add the bot to your family group and get the group's chat ID (e.g. via
   `getUpdates` after posting once, or a helper bot like @RawDataBot).
3. Fill in `TELEGRAM_BOT_TOKEN`, `TELEGRAM_GROUP_CHAT_ID`,
   `TELEGRAM_WEBHOOK_SECRET` in `backend/.env`.
4. After deploying the backend, register the webhook once:
   ```python
   import asyncio, telegram_bot as tg
   asyncio.run(tg.set_webhook("https://your-api.example.com/api/telegram/webhook", "your-webhook-secret"))
   ```

### 3. Backend
```bash
cd backend
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # fill in the real values
uvicorn main:app --reload
```

### 4. Frontend
Open `frontend/index.html` and set `API_BASE` at the top of the `<script>`
block to your deployed API URL, then host the file anywhere static
(Vercel, Netlify, Supabase Storage, GitHub Pages...). `WEBAPP_BASE_URL`
in `.env` should point to wherever it ends up.

## How the recipe flow works

1. A family member DMs the bot a recipe (text or link).
2. `recipe_parser.parse_recipe_text()` sends it to Claude with a strict
   JSON-only system prompt and gets back `[{name, quantity, category}]`.
3. Those items are saved to `recipe_sessions` (not the shopping list yet).
4. The bot DMs back a link: `index.html?recipe_session=<id>`.
5. The web app's Recipe Validation Area loads that session, shows every
   ingredient pre-checked, lets the user uncheck/adjust, then merges the
   survivors into the active `shopping_lists` row.

## How the Telegram sync works

- **Update Family Telegram Group** (floating button) → `POST
  /api/telegram/send-list` → builds a Markdown message grouped by
  category → sends it the first time, **edits the same message** on every
  later tap (via the stored `telegram_message_id`) so the group isn't
  spammed with duplicates.
- The message carries an inline **🛒 Done Shopping** button. Tapping it
  fires a `callback_query` webhook, which closes the list
  (`status → completed`) and edits the message to a checkmark summary.
