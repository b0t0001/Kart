-- KART market backend: member memory (CONTRACT v0.14, BETA, feature member_memory, off by default).
-- A demo sign-in with a store member number. Kart remembers what a member buys and the plans they
-- mention, and suggests what fits "this week". Member tables have no anon read and no realtime:
-- the iPad and the agent reach them only through the SECURITY DEFINER functions below.
-- Additive only, and safe to re-run.

-- ── Flag ──

insert into feature_flags (name, enabled_default, description)
values ('member_memory', false, 'BETA: member sign-in, purchase memory and "this week" picks (CONTRACT: Member memory)')
on conflict (name) do nothing;

-- ── Tables ──

create table if not exists members (
  member_id   text primary key,                       -- the number on the member card, e.g. "1029"
  name        text,                                   -- what Kart calls them; null until they say
  household   int,
  created_at  timestamptz not null default now()
);

create table if not exists member_purchases (
  id          bigserial primary key,
  member_id   text not null references members(member_id) on delete cascade,
  product_id  text not null,
  qty         int not null,
  price       numeric(10,2) not null,
  bought_at   timestamptz not null,                   -- the demo date's day when one is set (§3.8)
  trip_id     uuid,
  source      text not null check (source in ('seed', 'checkout'))
);
create index if not exists member_purchases_member on member_purchases (member_id, bought_at);

create table if not exists member_memories (
  id          bigserial primary key,
  member_id   text not null references members(member_id) on delete cascade,
  kind        text not null check (kind in ('event', 'reminder', 'preference', 'note')),
  text        text not null,
  event_date  date,                                   -- events and reminders
  items       jsonb,                                  -- a saved list: [{product_id, qty}]
  trip_id     uuid,
  created_at  timestamptz not null default now()
);
create index if not exists member_memories_member on member_memories (member_id);

alter table carts add column if not exists member_id text references members(member_id) on delete set null;
alter table carts add column if not exists member_rev int not null default 0;   -- bumped on memory writes
alter table carts add column if not exists demo_date date;                      -- null = real today
alter table receipts add column if not exists member_id text;

-- ── Time: the store's day, never UTC's ──

create or replace function member_tz()
returns text language sql immutable as $$ select 'America/Los_Angeles'::text $$;

-- The cart's "today": its demo date when one is set, else the store's real date.
create or replace function member_today(p_cart_id text)
returns date language sql stable security definer set search_path = public as $$
  select coalesce((select demo_date from carts where cart_id = p_cart_id),
                  (now() at time zone member_tz())::date)
$$;

create or replace function member_require_flag(c carts)
returns void language plpgsql stable as $$
begin
  if not feature_enabled(c.features, 'member_memory') then
    raise exception 'feature_off: member_memory';
  end if;
end $$;

-- ── Sign-in and the demo date ──

-- Signs a member in on this cart for the rest of the trip (null signs out). An unknown number
-- becomes a new, empty member.
create or replace function set_member(p_cart_id text, p_member_id text)
returns carts language plpgsql security definer set search_path = public as $$
declare
  c carts;
begin
  select * into c from carts where cart_id = p_cart_id for update;
  if not found then
    raise exception 'unknown cart: %', p_cart_id;
  end if;
  perform member_require_flag(c);
  if p_member_id is not null then
    if p_member_id !~ '^[A-Za-z0-9-]{1,32}$' then
      raise exception 'bad member id';
    end if;
    insert into members (member_id) values (p_member_id) on conflict do nothing;
  end if;
  update carts set member_id = p_member_id where cart_id = p_cart_id returning * into c;
  return c;
end $$;

-- The demo fast-forward (§3.8): the cart's "today" for member features only. Null = real today.
create or replace function set_demo_date(p_cart_id text, p_date date)
returns carts language plpgsql security definer set search_path = public as $$
declare
  c carts;
begin
  select * into c from carts where cart_id = p_cart_id for update;
  if not found then
    raise exception 'unknown cart: %', p_cart_id;
  end if;
  perform member_require_flag(c);
  update carts set demo_date = p_date where cart_id = p_cart_id returning * into c;
  return c;
end $$;

-- ── Triggers ──

-- Every trip starts as a guest; the demo date carries over (reset_cart itself is unchanged).
create or replace function carts_new_trip_signs_out()
returns trigger language plpgsql as $$
begin
  new.member_id := null;
  return new;
end $$;

drop trigger if exists new_trip_signs_out on carts;
create trigger new_trip_signs_out before update on carts for each row
  when (old.trip_id is distinct from new.trip_id) execute function carts_new_trip_signs_out();

-- A paid receipt on a member's cart becomes that member's history, dated on the demo date's day
-- when one is set. The receipt's own created_at stays real (store analytics never move).
create or replace function receipts_feed_member_history()
returns trigger language plpgsql security definer set search_path = public as $$
declare
  c carts;
  v_today date := (now() at time zone member_tz())::date;
begin
  select * into c from carts where cart_id = new.cart_id;
  if c.member_id is null then
    return new;
  end if;
  update receipts set member_id = c.member_id where id = new.id;
  insert into member_purchases (member_id, product_id, qty, price, bought_at, trip_id, source)
  select c.member_id, e->>'product_id', (e->>'qty')::int, (e->>'price')::numeric,
         now() + (coalesce(c.demo_date, v_today) - v_today) * interval '1 day', new.trip_id, 'checkout'
  from jsonb_array_elements(new.items) e
  where e->>'product_id' is not null;
  return new;
end $$;

drop trigger if exists feed_member_history on receipts;
create trigger feed_member_history after insert on receipts for each row
  when (new.status = 'paid') execute function receipts_feed_member_history();

-- ── Access: members are never readable directly ──

alter table members enable row level security;           -- no policies: anon sees nothing
alter table member_purchases enable row level security;
alter table member_memories enable row level security;
revoke all on members, member_purchases, member_memories from anon, authenticated;
grant all on members, member_purchases, member_memories to service_role;
grant usage on sequence member_purchases_id_seq, member_memories_id_seq to service_role;

revoke execute on function member_today(text) from public, anon, authenticated;
grant execute on function set_member(text, text)      to anon, authenticated, service_role;
grant execute on function set_demo_date(text, date)   to anon, authenticated, service_role;
