-- KART market backend: tables, realtime, row-level security.
-- Safe to re-run. CONTRACT §2 (catalog) and §3 (carts, cart_events).

create extension if not exists pgcrypto;

-- ── Catalog (seeded from data/store.json; the merchant agent edits it live) ──

create table if not exists store_info (
  id          int primary key default 1 check (id = 1),
  name        text not null,
  width       int  not null,
  height      int  not null,
  entrance_x  int  not null,
  entrance_y  int  not null
);

create table if not exists sections (
  id    text primary key,              -- "A4"
  name  text not null,                 -- "Aisle 4 · Cheese & Deli"
  x     int  not null,
  y     int  not null,
  w     int  not null,
  h     int  not null
);

create table if not exists products (
  id           text primary key,       -- kebab-case slug, THE join key everywhere
  name         text not null,
  short_name   text not null check (char_length(short_name) <= 11),
  price        numeric(10,2) not null check (price >= 0),   -- list price, USD
  section      text not null references sections(id),
  category     text not null default '',
  tags         text[] not null default '{}',
  stock        int  not null default 0 check (stock >= 0),
  vision_hint  text not null default '',
  active       boolean not null default true,               -- false = delisted
  sort         int  not null default 1000,                  -- order in store.json
  updated_at   timestamptz not null default now()
);

create table if not exists deals (
  id          text primary key,        -- "d-parm-3off"
  product_id  text not null references products(id),
  type        text not null check (type in ('amount_off', 'percent_off')),
  value       numeric(10,2) not null check (value > 0),
  label       text not null,           -- "$3 off" / "20% off"
  pairs_with  text[] not null default '{}',   -- suggest when one of these is in the cart
  starts_at   timestamptz,
  ends_at     timestamptz,
  active      boolean not null default true,  -- end_deal sets false
  sort        int not null default 1000,      -- tie-break between deals created together
  created_at  timestamptz not null default now(),
  updated_at  timestamptz not null default now(),
  check (type <> 'percent_off' or value <= 100)
);

-- ── Live carts ──

create table if not exists carts (
  cart_id          text primary key,                  -- demo cart "7"
  trip_id          uuid not null default gen_random_uuid(),   -- changes on reset_cart; the Pi watches it
  items            jsonb not null default '[]',       -- [{product_id,name,short_name,price,list_price,qty,deal_label?,deal_id?,section,added_at,last_added_at}]
  total            numeric(10,2) not null default 0,  -- Σ price × qty, after deals (estimate)
  savings          numeric(10,2) not null default 0,  -- Σ (list_price − price) × qty
  item_count       int not null default 0,            -- Σ qty
  plan             jsonb not null default '[]',       -- [{product_id,reason,qty,done,name,section,aisle,in_stock,deal_label?}] in route order
  next_step        text,                              -- "Aisle 4 → Parmesan, $3 off"
  lcd_line1        text check (lcd_line1 is null or char_length(lcd_line1) <= 16),
  suggestion       jsonb,                             -- {product_id,deal_id,text,deal_label,aisle,section,price,sale_price}
  suggested_deals  text[] not null default '{}',      -- deals already offered this trip (offered once each)
  updated_at       timestamptz not null default now()
);

create table if not exists cart_events (
  id            bigserial primary key,
  event_id      uuid unique,                          -- CV's uuid; repeats are ignored
  cart_id       text not null references carts(cart_id),
  trip_id       uuid,                                 -- the cart's trip when the event arrived
  type          text not null check (type in ('added', 'removed')),
  product_id    text,                                 -- null = unrecognized
  confidence    real,
  source        text not null check (source in ('vision', 'manual')),
  method        text check (method in ('local', 'cloud', 'memory', 'none', 'manual')),
  camera        int,
  label         text,                                 -- raw model answer / catalog name
  snapshot_url  text,
  applied       boolean not null default false,       -- did it change the cart?
  created_at    timestamptz not null default now()
);
create index if not exists cart_events_cart_trip on cart_events (cart_id, trip_id, id);

insert into carts (cart_id) values ('7') on conflict do nothing;

-- ── Realtime (Supabase publishes changes on these tables) ──

do $$
declare t text;
begin
  foreach t in array array['carts', 'cart_events', 'products', 'deals', 'sections'] loop
    if not exists (select 1 from pg_publication_tables
                   where pubname = 'supabase_realtime' and schemaname = 'public' and tablename = t) then
      execute format('alter publication supabase_realtime add table public.%I', t);
    end if;
  end loop;
end $$;

-- ── Row-level security: everyone can read; nobody writes tables directly ──
-- Writes go through SECURITY DEFINER functions (02_cart.sql, 03_merchant.sql).

do $$
declare t text;
begin
  foreach t in array array['store_info', 'sections', 'products', 'deals', 'carts', 'cart_events'] loop
    execute format('alter table public.%I enable row level security', t);
    execute format('drop policy if exists read_all on public.%I', t);
    execute format('create policy read_all on public.%I for select using (true)', t);
    -- Supabase grants anon ALL on new tables by default; take writes away explicitly.
    execute format('revoke insert, update, delete, truncate on public.%I from anon, authenticated', t);
    execute format('grant select on public.%I to anon, authenticated', t);
    execute format('grant all on public.%I to service_role', t);
  end loop;
end $$;
