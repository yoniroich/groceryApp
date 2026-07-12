-- =========================================================
-- Smart Family Grocery — Supabase schema
-- Run this in the Supabase SQL editor (or via `supabase db push`)
-- =========================================================

create extension if not exists "pgcrypto"; -- for gen_random_uuid()

-- ---------------------------------------------------------
-- master_products
-- The permanent catalog of products your family buys.
-- Seeded once from your Excel file, then grown over time
-- via the "Add New Product" form.
-- ---------------------------------------------------------
create table if not exists master_products (
    id          uuid primary key default gen_random_uuid(),
    name        text not null,
    category    text not null,
    created_at  timestamptz not null default now(),
    constraint master_products_name_unique unique (name)
);

create index if not exists idx_master_products_category on master_products (category);

-- ---------------------------------------------------------
-- shopping_lists
-- Only one list should be 'active' at a time — the app
-- enforces this at the application layer (see database.py).
-- ---------------------------------------------------------
create table if not exists shopping_lists (
    id                  uuid primary key default gen_random_uuid(),
    status              text not null default 'active'
                            check (status in ('active', 'completed')),
    telegram_message_id bigint,          -- id of the pinned/edited group message
    telegram_chat_id    bigint,          -- which group chat it lives in
    created_at          timestamptz not null default now(),
    completed_at        timestamptz
);

create index if not exists idx_shopping_lists_status on shopping_lists (status);

-- ---------------------------------------------------------
-- list_items
-- Line items on a shopping list. product_name/category are
-- denormalized (copied) from master_products at add-time so
-- a list still reads correctly even if the catalog changes later.
-- ---------------------------------------------------------
create table if not exists list_items (
    id           uuid primary key default gen_random_uuid(),
    list_id      uuid not null references shopping_lists(id) on delete cascade,
    product_name text not null,
    category     text not null,
    quantity     text not null default '1',
    is_bought    boolean not null default false,
    source       text not null default 'manual'
                    check (source in ('manual', 'recipe')),
    created_at   timestamptz not null default now()
);

create index if not exists idx_list_items_list_id on list_items (list_id);

-- ---------------------------------------------------------
-- recipe_sessions
-- Temporary holding area for LLM-parsed recipe ingredients,
-- created by the Telegram bot, reviewed in the Web App's
-- "Recipe Validation Area", then merged into an active list.
-- Not explicitly requested in the spec, but required to make
-- "save to temp state + send a validation link" actually work.
-- ---------------------------------------------------------
create table if not exists recipe_sessions (
    id               uuid primary key default gen_random_uuid(),
    telegram_user_id bigint not null,
    telegram_chat_id bigint,
    source_text      text,                 -- original recipe text/link, for reference
    items            jsonb not null,       -- [{name, quantity, category, checked}]
    status           text not null default 'pending'
                        check (status in ('pending', 'merged', 'discarded')),
    created_at       timestamptz not null default now()
);

create index if not exists idx_recipe_sessions_status on recipe_sessions (status);

-- =========================================================
-- Row Level Security
-- This app talks to Supabase using the service_role key from
-- a trusted backend, so RLS can stay locked down by default.
-- If you ever call Supabase directly from the browser with the
-- anon key, write real policies here instead of leaving this open.
-- =========================================================
alter table master_products enable row level security;
alter table shopping_lists  enable row level security;
alter table list_items      enable row level security;
alter table recipe_sessions enable row level security;

-- service_role bypasses RLS automatically, so no policy is
-- strictly required for the backend to work. Nothing else is
-- granted access, which is the safe default for a family app.
