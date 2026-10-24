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
  left join products pr on pr.id = e->>'product_id'
  where e->>'product_id' is not null and not member_sensitive(pr.category);
  return new;
end $$;

drop trigger if exists feed_member_history on receipts;
create trigger feed_member_history after insert on receipts for each row
  when (new.status = 'paid') execute function receipts_feed_member_history();

-- Kart never remembers sensitive purchases (§3.9: the Target pregnancy-prediction story).
create or replace function member_sensitive(p_category text)
returns boolean language sql immutable as $$
  select coalesce(p_category in ('pharmacy', 'health', 'medicine', 'personal-care', 'baby', 'pregnancy', 'adult'), false)
$$;

-- The sign-in card's confirm step: is this number a member, and what's their first name? Never creates.
create or replace function member_lookup(p_member_id text)
returns jsonb language sql stable security definer set search_path = public as $$
  select jsonb_build_object('exists', m.member_id is not null, 'name', m.name)
  from (select 1) one left join members m on m.member_id = p_member_id
$$;

-- ── The profile: who they are and what fits "this week" (§4) ──

-- "today", "tomorrow", "Sat" (within the week) or "Oct 31".
create or replace function member_when(p_day date, p_today date)
returns text language sql immutable as $$
  select case when p_day = p_today then 'today'
              when p_day = p_today + 1 then 'tomorrow'
              when p_day between p_today + 2 and p_today + 6 then to_char(p_day, 'Dy')
              else to_char(p_day, 'Mon FMDD') end
$$;

-- A purchase rhythm in words: "every week", "every 2 weeks", "every month", "every 10 days".
create or replace function member_every(p_days int)
returns text language sql immutable as $$
  select case when p_days between 6 and 8 then 'every week'
              when p_days between 13 and 15 then 'every 2 weeks'
              when p_days between 27 and 31 then 'every month'
              else 'every ' || p_days || ' days' end
$$;

-- An event's short label: the text before its first comma, at most 28 characters.
create or replace function member_label(p_text text)
returns text language sql immutable as $$ select left(trim(split_part(p_text, ',', 1)), 28) $$;

-- An undated event stays "coming up" for 30 days after it was saved, then goes stale (§3.9).
create or replace function member_undated_fresh(mm member_memories, p_today date)
returns boolean language sql stable as $$
  select mm.event_date is null and (mm.created_at at time zone member_tz())::date >= p_today - 30
$$;

-- Coming up: a dated event not yet past, a reminder until 3 days after its day, a fresh undated event.
create or replace function member_upcoming(mm member_memories, p_today date)
returns boolean language sql stable as $$
  select case when mm.kind = 'event' and mm.event_date is not null then mm.event_date >= p_today
              when mm.kind = 'event' then member_undated_fresh(mm, p_today)
              when mm.kind = 'reminder' then mm.event_date >= p_today - 3
              else false end
$$;

-- Everything the iPad and the agent know about a member, computed on read (null = unknown member).
-- "today" is p_today, else the cart's demo date, else the store's real date. Purchases dated after
-- "today" (a demo date moved back) are ignored everywhere.
-- Picks: at most 3, one per signal first (event, due, usual), then filled in that order. Never
-- something on the cart's list or in it, out of stock, or on a live deal (deals are the cards' job).
create or replace function member_profile(p_member_id text, p_cart_id text default null, p_today date default null)
returns jsonb language plpgsql stable security definer set search_path = public as $$
declare
  m        members;
  v_today  date;
  v_taken  text[] := '{}';
  v_ok     text[];
  v_cands  jsonb;
  v_picks  jsonb := '[]';
  v_picked text[] := '{}';
  v_kind   text;
  c        jsonb;
begin
  select * into m from members where member_id = p_member_id;
  if not found then
    return null;
  end if;
  v_today := coalesce(p_today, (select demo_date from carts where cart_id = p_cart_id),
                      (now() at time zone member_tz())::date);
  if p_cart_id is not null then
    select coalesce(array_agg(distinct x), '{}') into v_taken from (
      select e->>'product_id' as x from carts, jsonb_array_elements(items) e where cart_id = p_cart_id
      union all
      select e->>'product_id' from carts, jsonb_array_elements(plan) e where cart_id = p_cart_id) t;
  end if;
  select coalesce(array_agg(id), '{}') into v_ok
  from product_catalog where in_stock and deal_label is null and not (id = any(v_taken));

  -- Every candidate, in signal order then rank within the signal.
  with p as (
    select mp.product_id, (mp.bought_at at time zone member_tz())::date as d
    from member_purchases mp left join products pr on pr.id = mp.product_id
    where mp.member_id = p_member_id and (mp.bought_at at time zone member_tz())::date <= v_today
      and not member_sensitive(pr.category)),
  days as (select distinct product_id, d from p),
  stats as (select product_id, count(*) as times, max(d) as last from days group by product_id),
  gaps as (select product_id, d - lag(d) over (partition by product_id order by d) as gap from days),
  med as (select product_id, round(percentile_cont(0.5) within group (order by gap))::int as every_days
          from gaps where gap is not null group by product_id),
  weekday_trips as (select count(distinct d) as n from p where extract(isodow from d) = extract(isodow from v_today)),
  weekday_buys as (select product_id, count(*) as n from days
                   where extract(isodow from d) = extract(isodow from v_today) group by product_id),
  cands as (
    select 1 as k, row_number() over (order by mm.event_date nulls last, mm.id, it.ord) as rank,
           it.item->>'product_id' as product_id,
           member_label(mm.text) || ' · ' ||
             case when mm.kind = 'reminder' then 'reminder'
                  when mm.event_date is null then 'soon'
                  else member_when(mm.event_date, v_today) end as reason,
           mm.id as memory_id, 'event' as kind
    from member_memories mm, jsonb_array_elements(mm.items) with ordinality as it(item, ord)
    where mm.member_id = p_member_id and mm.items is not null
      and ((mm.kind = 'event' and mm.event_date between v_today and v_today + 14)
        or (mm.kind = 'event' and mm.event_date is null and member_undated_fresh(mm, v_today))
        or (mm.kind = 'reminder' and mm.event_date - v_today between -3 and 1))
    union all
    select 2, row_number() over (order by (v_today - s.last)::numeric / md.every_days desc, s.times desc, s.product_id),
           s.product_id,
           member_every(md.every_days) || ' · last ' ||
             case when v_today - s.last <= 7 then to_char(s.last, 'Dy') else to_char(s.last, 'Mon FMDD') end,
           null, 'due'
    from stats s join med md using (product_id)
    where s.times >= 3 and md.every_days > 0 and (v_today - s.last) >= 0.85 * md.every_days
    union all
    select 3, row_number() over (order by wb.n::numeric / wt.n desc, s.times desc, s.product_id),
           wb.product_id, 'your ' || to_char(v_today, 'FMDay') || ' usual', null, 'usual'
    from weekday_buys wb cross join weekday_trips wt join stats s using (product_id)
    where wt.n >= 2 and wb.n::numeric / wt.n >= 0.6)
  select coalesce(jsonb_agg(to_jsonb(cands) order by k, rank), '[]') into v_cands from cands;

  -- First the top pick of each signal, then fill to 3 in the same order (no second item from a saved list).
  foreach v_kind in array array['event', 'due', 'usual'] loop
    select x into c from jsonb_array_elements(v_cands) x
    where x->>'kind' = v_kind and x->>'product_id' = any(v_ok) and not (x->>'product_id' = any(v_picked))
    limit 1;
    if c is not null and jsonb_array_length(v_picks) < 3 then
      v_picks := v_picks || jsonb_build_array(c);
      v_picked := v_picked || (c->>'product_id');
    end if;
    c := null;
  end loop;
  for c in select x from jsonb_array_elements(v_cands) x loop      -- a saved list is one line on the card: not twice
    exit when jsonb_array_length(v_picks) >= 3;
    if c->>'kind' <> 'event' and c->>'product_id' = any(v_ok) and not (c->>'product_id' = any(v_picked)) then
      v_picks := v_picks || jsonb_build_array(c);
      v_picked := v_picked || (c->>'product_id');
    end if;
  end loop;

  return (
    with p as (
      select mp.product_id, mp.qty, mp.price, (mp.bought_at at time zone member_tz())::date as d
      from member_purchases mp left join products pr on pr.id = mp.product_id
      where mp.member_id = p_member_id and (mp.bought_at at time zone member_tz())::date <= v_today
        and not member_sensitive(pr.category)),
    days as (select distinct product_id, d from p),
    stats as (select product_id, count(*) as times, max(d) as last from days group by product_id),
    gaps as (select product_id, d - lag(d) over (partition by product_id order by d) as gap from days),
    med as (select product_id, round(percentile_cont(0.5) within group (order by gap))::int as every_days
            from gaps where gap is not null group by product_id),
    dows as (select product_id, extract(isodow from d) as dow, to_char(min(d), 'FMDay') as day_name, count(*) as n
             from days group by product_id, extract(isodow from d)),
    top_dow as (select distinct on (product_id) product_id, day_name, n from dows order by product_id, n desc, dow),
    last_day as (select max(d) as d from p)
    select jsonb_build_object(
      'member', jsonb_build_object(
        'member_id', m.member_id, 'name', m.name, 'household', m.household,
        'since', to_char((m.created_at at time zone member_tz())::date, 'YYYY-MM-DD'),
        'trips', (select count(distinct d) from p)),
      'today', to_char(v_today, 'YYYY-MM-DD'),
      'weekday', to_char(v_today, 'FMDay'),
      'picks', (select coalesce(jsonb_agg(jsonb_strip_nulls(jsonb_build_object(
                  'product_id', x->>'product_id', 'short_name', coalesce(pc.short_name, pc.name, x->>'product_id'),
                  'kind', x->>'kind', 'reason', x->>'reason', 'aisle', pc.aisle,
                  'memory_id', (x->>'memory_id')::bigint)) order by o), '[]')
                from jsonb_array_elements(v_picks) with ordinality as t(x, o)
                left join product_catalog pc on pc.id = x->>'product_id'),
      'usuals', (select coalesce(jsonb_agg(u order by u_times desc, u_last desc), '[]') from (
                   select jsonb_build_object(
                     'product_id', s.product_id,
                     'short_name', coalesce(pr.short_name, pr.name, s.product_id),
                     'times', s.times, 'every_days', md.every_days,
                     'last', to_char(s.last, 'YYYY-MM-DD'),
                     'weekday', case when td.n::numeric / s.times >= 0.6 then td.day_name end) as u,
                     s.times as u_times, s.last as u_last
                   from stats s left join med md using (product_id) left join top_dow td using (product_id)
                   left join products pr on pr.id = s.product_id
                   where s.times >= 2
                   order by s.times desc, s.last desc limit 6) us),
      'memories', (select coalesce(jsonb_agg(jsonb_build_object(
                     'id', mm.id, 'kind', mm.kind, 'text', mm.text,
                     'event_date', to_char(mm.event_date, 'YYYY-MM-DD'),
                     'days_until', mm.event_date - v_today,
                     'upcoming', member_upcoming(mm, v_today),
                     'items', (select jsonb_agg(jsonb_build_object(
                                 'product_id', it->>'product_id',
                                 'short_name', coalesce(pr.short_name, pr.name, it->>'product_id'),
                                 'qty', coalesce((it->>'qty')::int, 1)) order by o)
                               from jsonb_array_elements(mm.items) with ordinality as x(it, o)
                               left join products pr on pr.id = it->>'product_id'))
                     order by coalesce(member_upcoming(mm, v_today) or mm.event_date - v_today >= -7, false) desc,
                              case when coalesce(member_upcoming(mm, v_today) or mm.event_date - v_today >= -7, false)
                                   then coalesce(mm.event_date, 'infinity'::date) end,
                              mm.created_at desc, mm.id desc), '[]')
                   from member_memories mm where mm.member_id = p_member_id),
      'last_trip', (select case when ld.d is null then null else jsonb_build_object(
                      'date', to_char(ld.d, 'YYYY-MM-DD'),
                      'items', (select jsonb_agg(n order by n) from (
                                  select distinct coalesce(pr.short_name, pr.name, p.product_id) as n
                                  from p left join products pr on pr.id = p.product_id where p.d = ld.d) names),
                      'total', (select sum(price * qty) from p where p.d = ld.d)) end
                    from last_day ld))
  );
end $$;

-- ── What Kart learns in conversation ──

-- Bumps member_rev on every cart this member is signed in on, so the iPad refetches the profile.
create or replace function member_touch(p_member_id text)
returns void language sql security definer set search_path = public as $$
  update carts set member_rev = member_rev + 1 where member_id = p_member_id
$$;

create or replace function member_memory_json(mm member_memories)
returns jsonb language sql stable security definer set search_path = public as $$
  select jsonb_build_object(
    'id', mm.id, 'kind', mm.kind, 'text', mm.text, 'event_date', to_char(mm.event_date, 'YYYY-MM-DD'),
    'items', (select jsonb_agg(jsonb_build_object(
                'product_id', it->>'product_id', 'short_name', coalesce(pr.short_name, pr.name, it->>'product_id'),
                'qty', coalesce((it->>'qty')::int, 1)) order by o)
              from jsonb_array_elements(mm.items) with ordinality as x(it, o)
              left join products pr on pr.id = it->>'product_id'))
$$;

-- Saves something worth knowing next trip. event / reminder / preference / note add a memory
-- (a reminder needs its date); name and household update the member instead.
create or replace function member_remember(p_member_id text, p_kind text, p_text text,
                                           p_event_date date default null, p_trip_id uuid default null)
returns jsonb language plpgsql security definer set search_path = public as $$
declare
  mm member_memories;
  v_text text := trim(coalesce(p_text, ''));
begin
  if not exists (select 1 from members where member_id = p_member_id) then
    raise exception 'unknown member: %', p_member_id;
  end if;
  if v_text = '' then
    raise exception 'text is empty';
  end if;
  if p_kind = 'name' then
    update members set name = left(v_text, 40) where member_id = p_member_id;
    perform member_touch(p_member_id);
    return jsonb_build_object('kind', 'name', 'text', left(v_text, 40));
  elsif p_kind = 'household' then
    if v_text !~ '^\d{1,2}$' then
      raise exception 'household must be a number of people';
    end if;
    update members set household = v_text::int where member_id = p_member_id;
    perform member_touch(p_member_id);
    return jsonb_build_object('kind', 'household', 'text', v_text);
  elsif p_kind not in ('event', 'reminder', 'preference', 'note') or p_kind is null then
    raise exception 'bad kind: %', p_kind;
  elsif p_kind = 'reminder' and p_event_date is null then
    raise exception 'a reminder needs a date';
  end if;
  insert into member_memories (member_id, kind, text, event_date, trip_id)
  values (p_member_id, p_kind, v_text, p_event_date, p_trip_id)
  returning * into mm;
  perform member_touch(p_member_id);
  return jsonb_build_object('id', mm.id, 'kind', mm.kind, 'text', mm.text,
                            'event_date', to_char(mm.event_date, 'YYYY-MM-DD'));
end $$;

-- Puts store products on an event's (or reminder's) saved list, merged by product_id: the new qty wins.
create or replace function member_save_for_later(p_member_id text, p_memory_id bigint, p_items jsonb)
returns jsonb language plpgsql security definer set search_path = public as $$
declare
  mm   member_memories;
  it   jsonb;
  v_items jsonb;
  v_pid text;
begin
  select * into mm from member_memories where id = p_memory_id for update;
  if not found then
    raise exception 'unknown memory: %', p_memory_id;
  elsif mm.member_id is distinct from p_member_id then
    raise exception 'not your memory';
  elsif mm.kind not in ('event', 'reminder') then
    raise exception 'not an event';
  end if;
  v_items := coalesce(mm.items, '[]');
  for it in select * from jsonb_array_elements(coalesce(p_items, '[]')) loop
    v_pid := it->>'product_id';
    if v_pid is null or not exists (select 1 from products where id = v_pid) then
      raise exception 'unknown product: %', coalesce(v_pid, '(none)');
    end if;
    if exists (select 1 from jsonb_array_elements(v_items) x where x->>'product_id' = v_pid) then
      select jsonb_agg(case when x->>'product_id' = v_pid
                            then jsonb_build_object('product_id', v_pid, 'qty', coalesce((it->>'qty')::int, 1))
                            else x end order by o)
      into v_items from jsonb_array_elements(v_items) with ordinality as t(x, o);
    else
      v_items := v_items || jsonb_build_array(jsonb_build_object('product_id', v_pid,
                                                                 'qty', coalesce((it->>'qty')::int, 1)));
    end if;
  end loop;
  update member_memories set items = v_items where id = p_memory_id returning * into mm;
  perform member_touch(p_member_id);
  return member_memory_json(mm);
end $$;

-- Forgets one memory, or (null) everything: history, memories and name. Carts signed in as the
-- member are signed out by the foreign key.
create or replace function member_forget(p_member_id text, p_memory_id bigint default null)
returns jsonb language plpgsql security definer set search_path = public as $$
declare
  n int;
begin
  if p_memory_id is null then
    delete from members where member_id = p_member_id;
    return jsonb_build_object('forgotten', 'all');
  end if;
  delete from member_memories where id = p_memory_id and member_id = p_member_id;
  get diagnostics n = row_count;
  perform member_touch(p_member_id);
  return jsonb_build_object('forgotten', n);
end $$;

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
grant execute on function member_profile(text, text, date) to anon, authenticated, service_role;
grant execute on function member_remember(text, text, text, date, uuid) to anon, authenticated, service_role;
grant execute on function member_save_for_later(text, bigint, jsonb) to anon, authenticated, service_role;
grant execute on function member_forget(text, bigint)      to anon, authenticated, service_role;
revoke execute on function member_touch(text) from public, anon, authenticated;
revoke execute on function member_memory_json(member_memories) from public, anon, authenticated;
grant execute on function member_lookup(text) to anon, authenticated, service_role;
