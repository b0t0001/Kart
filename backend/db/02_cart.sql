-- KART market backend: pricing, cart recompute, and the cart RPCs.
-- CONTRACT §3: apply_cart_event, set_plan, reset_cart (+ dismiss_suggestion).
-- Safe to re-run.

-- ── Pricing helpers ──

create or replace function deal_price(p_price numeric, p_type text, p_value numeric)
returns numeric language sql immutable as $$
  select case p_type
    when 'amount_off'  then greatest(p_price - p_value, 0)
    when 'percent_off' then round(p_price * (1 - p_value / 100.0), 2)
    else p_price
  end
$$;

-- "$3", "$1.50"
create or replace function fmt_money(p numeric)
returns text language sql immutable as $$
  select '$' || case when p = trunc(p) then trunc(p)::text else to_char(p, 'FM999990.00') end
$$;

-- "-$3" / "-20%" for the 16-char LCD
create or replace function fmt_deal_short(p_type text, p_value numeric)
returns text language sql immutable as $$
  select case p_type
    when 'amount_off'  then '-' || fmt_money(p_value)
    when 'percent_off' then '-' || trunc(p_value)::text || '%'
    else '' end
$$;

-- "A4 Parmesan -$3": ASCII only, at most 16 chars; the name gets truncated to fit.
create or replace function fmt_lcd(p_section text, p_short text, p_suffix text)
returns text language sql immutable as $$
  select left(trim(concat_ws(' ',
           p_section,
           left(p_short, greatest(16 - char_length(coalesce(p_section, '')) - 1
                                    - case when coalesce(p_suffix, '') = '' then 0
                                           else char_length(p_suffix) + 1 end, 1)),
           nullif(p_suffix, ''))), 16)
$$;

create or replace view live_deals with (security_invoker = true) as
  select d.* from deals d
  where d.active
    and (d.starts_at is null or d.starts_at <= now())
    and (d.ends_at   is null or d.ends_at   >  now());

-- One row per active product, joined with its best live deal. What the iPad and the
-- merchant console read: refetch it on any realtime change to products or deals.
create or replace view product_catalog with (security_invoker = true) as
  select p.id, p.name, p.short_name, p.price, p.section, p.category, p.tags, p.stock,
         p.stock > 0 as in_stock, p.vision_hint, p.sort, p.updated_at,
         s.name as section_name,
         split_part(s.name, ' · ', 1) as aisle,        -- "Aisle 4"
         s.x as section_x, s.y as section_y,
         d.id as deal_id, d.type as deal_type, d.value as deal_value,
         d.label as deal_label, d.ends_at as deal_ends_at,
         coalesce(deal_price(p.price, d.type, d.value), p.price) as sale_price
  from products p
  join sections s on s.id = p.section
  left join lateral (
    select ld.* from live_deals ld
    where ld.product_id = p.id
    order by deal_price(p.price, ld.type, ld.value), ld.created_at desc, ld.sort
    limit 1
  ) d on true
  where p.active;

grant select on live_deals, product_catalog to anon, authenticated, service_role;

-- ── Feature flags (v0.12) ──

-- A cart's override wins; otherwise the global default; unknown features are off.
create or replace function feature_enabled(p_features jsonb, p_feature text)
returns boolean language sql stable as $$
  select coalesce((p_features->>p_feature)::boolean,
                  (select enabled_default from feature_flags where name = p_feature),
                  false)
$$;

-- "A", "A and B", "A, B and C"
create or replace function fmt_list(p_items text[])
returns text language sql immutable as $$
  select case coalesce(array_length(p_items, 1), 0)
    when 0 then ''
    when 1 then p_items[1]
    else array_to_string(p_items[1:array_length(p_items, 1) - 1], ', ') || ' and ' || p_items[array_length(p_items, 1)]
  end
$$;

-- Quantity nudges (BETA): markers in carts.nudged. over:<id> / under:<id> = that single nudge was
-- shown (once per trip); done:<id> = answered final (ok / skip, or the loop guard); shop:<id> = the
-- shopper said "go get them" (one marker per time). A checkout list may hold an item unless it's
-- done or was already promised twice: the 3rd checkout records it done instead (loop guard).
create or replace function nudge_listable(p_nudged text[], p_pid text)
returns boolean language sql immutable as $$
  select not ('done:' || p_pid = any(p_nudged))
     and (select count(*) from unnest(p_nudged) m where m = 'shop:' || p_pid) < 2
$$;

-- Quantity nudges (BETA): one row per plan line with what the cart has against what the plan needs.
create or replace function nudge_lines(p_items jsonb, p_plan jsonb)
returns table (pid text, need int, have int, basis text, price numeric, got_at timestamptz,
               short_name text, aisle text, section_x int, in_stock boolean, ord bigint)
language sql stable as $$
  select e->>'product_id', greatest(coalesce((e->>'qty')::int, 1), 1),
         coalesce((i->>'qty')::int, 0), e->>'basis', (i->>'price')::numeric,
         (i->>'last_added_at')::timestamptz, pc.short_name, pc.aisle, pc.section_x,
         coalesce(pc.in_stock, false), t.ord
  from jsonb_array_elements(p_plan) with ordinality as t(e, ord)
  join product_catalog pc on pc.id = e->>'product_id'
  left join lateral (select x as i from jsonb_array_elements(p_items) x
                     where x->>'product_id' = e->>'product_id' limit 1) it on true
$$;

-- ── Recompute: everything derived on a cart row ──
-- Reprices items from the live catalog, then totals, plan (done flags, route order),
-- next_step, lcd_line1 and the moment-of-decision suggestion.

create or replace function recompute_cart(p_cart_id text)
returns carts language plpgsql security definer set search_path = public as $$
declare
  c        carts;
  v_items  jsonb;
  v_plan   jsonb;
  v_pos_x  int;
  v_next   record;
  v_sugg   jsonb;
  v_cand   record;
  v_cur    record;
  v_keep   boolean;
  v_line   record;
  v_kind   text;
  v_at     timestamptz;
  v_pos    int;
  v_nudge  jsonb;
  v_nudged text[];
  v_batch  jsonb;
  v_offered timestamptz;
  v_suggested text[];
begin
  select * into c from carts where cart_id = p_cart_id for update;
  if not found then
    return null;
  end if;

  -- Items, repriced by "the price you saw is the price you pay" (CONTRACT P10): a line
  -- takes the current price only when it is lower than what it already has, so new deals
  -- and price drops reach the cart, while increases and ended deals never raise the bill.
  -- A delisted product keeps its last known values.
  select coalesce(jsonb_agg(jsonb_strip_nulls(jsonb_build_object(
           'product_id',    i.product_id,
           'name',          coalesce(pc.name, i.name),
           'short_name',    coalesce(pc.short_name, i.short_name),
           'price',         case when cheaper then pc.sale_price else coalesce(i.price, 0) end,
           'list_price',    case when cheaper then pc.price else coalesce(i.list_price, i.price, 0) end,
           'qty',           i.qty,
           'deal_label',    case when cheaper then pc.deal_label else i.deal_label end,
           'deal_id',       case when cheaper then pc.deal_id else i.deal_id end,
           'section',       coalesce(pc.section, i.section),
           'added_at',      i.added_at,
           'last_added_at', coalesce(i.last_added_at, i.added_at)))
         order by i.added_at, i.product_id), '[]'::jsonb)
    into v_items
  from jsonb_to_recordset(c.items) as i(product_id text, name text, short_name text,
         price numeric, list_price numeric, qty int, deal_label text, deal_id text,
         section text, added_at timestamptz, last_added_at timestamptz)
  left join product_catalog pc on pc.id = i.product_id
  cross join lateral (select pc.id is not null
                             and (i.price is null or pc.sale_price < i.price) as cheaper) k
  where i.qty > 0;

  select coalesce(sum((e->>'price')::numeric * (e->>'qty')::int), 0),
         coalesce(sum(((e->>'list_price')::numeric - (e->>'price')::numeric) * (e->>'qty')::int), 0),
         coalesce(sum((e->>'qty')::int), 0)
    into c.total, c.savings, c.item_count
  from jsonb_array_elements(v_items) e;
  c.items := v_items;

  -- Where the shopper is (P3): carts.location (set by the last add, or "I'm at aisle 5"),
  -- else the aisle of the last thing they added, else the entrance.
  select x into v_pos_x from sections where id = c.location->>'section';
  if v_pos_x is null then
    select pc.section_x into v_pos_x
    from jsonb_array_elements(v_items) e
    join product_catalog pc on pc.id = e->>'product_id'
    order by (e->>'last_added_at')::timestamptz desc
    limit 1;
  end if;
  v_pos_x := coalesce(v_pos_x, (select entrance_x from store_info where id = 1), 0);

  -- Plan: done items first (as they were picked up), then the rest in walking order:
  -- aisles ahead of the shopper left to right, then the ones behind on the way back.
  with p as (
    select elem, ord,
           greatest(coalesce((elem->>'qty')::int, 1), 1) as want,
           pc.short_name, pc.section, pc.aisle, pc.section_x, pc.section_y,
           pc.in_stock, pc.deal_label,
           (select (e->>'qty')::int from jsonb_array_elements(v_items) e
             where e->>'product_id' = elem->>'product_id') as have,
           (select (e->>'last_added_at')::timestamptz from jsonb_array_elements(v_items) e
             where e->>'product_id' = elem->>'product_id') as got_at
    from jsonb_array_elements(c.plan) with ordinality as t(elem, ord)
    left join product_catalog pc on pc.id = elem->>'product_id'
  )
  select coalesce(jsonb_agg(jsonb_strip_nulls(jsonb_build_object(
           'product_id', elem->>'product_id',
           'reason',     elem->>'reason',
           'basis',      elem->>'basis',
           'qty',        want,
           'done',       coalesce(have, 0) >= want,
           'name',       coalesce(short_name, elem->>'name'),
           'section',    section,
           'aisle',      aisle,
           'in_stock',   coalesce(in_stock, false),
           'deal_label', deal_label))
         order by
           (coalesce(have, 0) >= want) desc,
           case when coalesce(have, 0) >= want then got_at end,
           case when section_x is null then 2 when section_x >= v_pos_x then 0 else 1 end,
           case when section_x >= v_pos_x then section_x else -section_x end,
           section_y, ord), '[]'::jsonb)
    into v_plan
  from p;
  c.plan := v_plan;

  -- Next step: first plan item not yet in the cart and in stock.
  select e->>'product_id' as product_id, e->>'name' as name, e->>'aisle' as aisle,
         e->>'section' as section, pc.deal_type, pc.deal_value, pc.deal_label
    into v_next
  from jsonb_array_elements(v_plan) e
  left join product_catalog pc on pc.id = e->>'product_id'
  where not (e->>'done')::boolean and (e->>'in_stock')::boolean
  limit 1;

  -- Suggestion: a live deal on something not in the cart whose pairs_with is, product in
  -- stock and not already on the shopper's plan, each deal offered once per trip. The current
  -- one stays while it is still valid, unless the store created a deal after it was offered
  -- (fresh deals reach shoppers now). A "Yes" puts the product on the plan, which consumes the
  -- suggestion, so the next eligible deal can be offered right away.
  v_suggested := c.suggested_deals;
  v_sugg := null;
  v_keep := false;
  if c.suggestion is not null then
    select pc.* into v_cur from product_catalog pc
    where pc.id = c.suggestion->>'product_id'
      and pc.deal_id = c.suggestion->>'deal_id'
      and pc.in_stock
      and not exists (select 1 from jsonb_array_elements(v_items) e where e->>'product_id' = pc.id)
      and not exists (select 1 from jsonb_array_elements(v_plan) e where e->>'product_id' = pc.id);
    v_keep := found;
  end if;
  select pc.*, d.created_at as deal_created_at into v_cand
  from product_catalog pc
  join deals d on d.id = pc.deal_id
  where pc.deal_id is not null
    and pc.in_stock
    and not (pc.deal_id = any(c.suggested_deals))
    and not exists (select 1 from jsonb_array_elements(v_items) e where e->>'product_id' = pc.id)
    and not exists (select 1 from jsonb_array_elements(v_plan) e where e->>'product_id' = pc.id)
    and exists (select 1 from jsonb_array_elements(v_items) e where e->>'product_id' = any(d.pairs_with))
  order by (select max((e->>'last_added_at')::timestamptz) from jsonb_array_elements(v_items) e
             where e->>'product_id' = any(d.pairs_with)) desc,
           d.created_at desc, d.sort
  limit 1;
  -- >= because now() is fixed per transaction: merchant_apply ends the old deal (which can
  -- re-offer another one) and creates the new deal in the same instant; the new deal wins.
  if found and (not v_keep or v_cand.deal_created_at
                >= coalesce((c.suggestion->>'offered_at')::timestamptz, '-infinity')) then
    v_suggested := array_append(v_suggested, v_cand.deal_id);
    v_offered := now();
    insert into deal_offers (cart_id, trip_id, deal_id, product_id)
    values (p_cart_id, c.trip_id, v_cand.deal_id, v_cand.id);
    v_sugg := jsonb_build_object('product_id', v_cand.id, 'deal_id', v_cand.deal_id);
  elsif v_keep then
    v_cand := v_cur;
    v_offered := coalesce((c.suggestion->>'offered_at')::timestamptz, now());
    v_sugg := jsonb_build_object('product_id', v_cand.id, 'deal_id', v_cand.deal_id);
  end if;
  if v_sugg is not null then
    -- v_cand now holds the suggested product's catalog row
    v_sugg := v_sugg || jsonb_build_object(
      'text',       format('%s is %s in %s. Want it?', v_cand.short_name, v_cand.deal_label, v_cand.aisle),
      'deal_label', v_cand.deal_label,
      'aisle',      v_cand.aisle,
      'section',    v_cand.section,
      'name',       v_cand.short_name,
      'price',      v_cand.price,
      'sale_price', v_cand.sale_price,
      'offered_at', v_offered);
  end if;
  c.suggestion := v_sugg;
  c.suggested_deals := v_suggested;

  -- Quantity nudges (BETA, feature quantity_nudges, off by default). With the flag off, nothing
  -- below runs: nudge stays null and nudged untouched. Only plan items are nudged. The current
  -- nudge stays while its condition holds (it clears itself when the counts match); a new one is
  -- picked only when no deal card is up, at most once per product per direction per trip.
  v_nudge := null;
  v_nudged := c.nudged;
  if feature_enabled(c.features, 'quantity_nudges') then
    select x into v_pos from sections where id = c.location->>'section';
    v_kind := null;
    if c.nudge ? 'items' then
      select jsonb_agg(jsonb_build_object('product_id', l.pid, 'name', l.short_name, 'have', l.have,
                                          'need', l.need, 'aisle', l.aisle, 'basis', l.basis) order by l.ord)
        into v_batch
      from nudge_lines(v_items, v_plan) l
      where l.have < l.need
        and l.pid in (select x->>'product_id' from jsonb_array_elements(c.nudge->'items') x);
      if v_batch is not null then
        v_kind := 'checkout';
        v_at := (c.nudge->>'at')::timestamptz;
      end if;
    elsif c.nudge->>'kind' = 'under' and c.status = 'checkout' then
      -- going to checkout upgrades a mid-trip under nudge to the full list
      select jsonb_agg(jsonb_build_object('product_id', l.pid, 'name', l.short_name, 'have', l.have,
                                          'need', l.need, 'aisle', l.aisle, 'basis', l.basis) order by l.ord)
        into v_batch
      from nudge_lines(v_items, v_plan) l
      where l.have < l.need and l.in_stock and nudge_listable(c.nudged, l.pid);
      if v_batch is not null then
        v_kind := 'checkout';
        v_at := now();
      end if;
    elsif c.nudge is not null then
      select * into v_line from nudge_lines(v_items, v_plan) l
      where l.pid = c.nudge->>'product_id'
        and ((c.nudge->>'kind' = 'over' and l.have > l.need)
             or (c.nudge->>'kind' = 'under' and l.have < l.need));
      if found then
        v_kind := c.nudge->>'kind';
        v_at := (c.nudge->>'at')::timestamptz;
      end if;
    end if;
    if v_kind is null and v_sugg is null then
      -- over: more in the cart than the plan needs (the most recent add first)
      select * into v_line from nudge_lines(v_items, v_plan) l
      where l.have > l.need and not ('over:' || l.pid = any(c.nudged))
      order by l.got_at desc nulls last limit 1;
      if found then
        v_kind := 'over';
      elsif c.status = 'checkout' then
        -- under at checkout: every short plan item in ONE nudge, answered once
        select jsonb_agg(jsonb_build_object('product_id', l.pid, 'name', l.short_name, 'have', l.have,
                                            'need', l.need, 'aisle', l.aisle, 'basis', l.basis) order by l.ord)
          into v_batch
        from nudge_lines(v_items, v_plan) l
        where l.have < l.need and l.in_stock and nudge_listable(c.nudged, l.pid);
        if v_batch is not null then
          v_kind := 'checkout';
        end if;
        -- loop guard: still short after two "go get them": record it done, don't list it again
        v_nudged := v_nudged || array(
          select 'done:' || l.pid from nudge_lines(v_items, v_plan) l
          where l.have < l.need and not nudge_listable(c.nudged, l.pid)
            and not ('done:' || l.pid = any(c.nudged)));
      else
        -- under mid-trip: short, and the shopper has moved past its aisle (one at a time)
        select * into v_line from nudge_lines(v_items, v_plan) l
        where l.have < l.need and l.in_stock and not ('under:' || l.pid = any(c.nudged))
          and not ('shop:' || l.pid = any(c.nudged)) and not ('done:' || l.pid = any(c.nudged))
          and v_pos is not null and v_pos > l.section_x
        order by l.ord limit 1;
        if found then
          v_kind := 'under';
        end if;
      end if;
      if v_kind = 'checkout' then
        v_at := now();
      elsif v_kind is not null then
        v_at := now();
        v_nudged := array_append(v_nudged, v_kind || ':' || v_line.pid);
      end if;
    end if;
    if v_kind = 'over' then
      v_nudge := jsonb_strip_nulls(jsonb_build_object(
        'product_id', v_line.pid, 'name', v_line.short_name, 'kind', 'over',
        'have', v_line.have, 'need', v_line.need, 'basis', v_line.basis,
        'text', format('That''s %s %s in the cart, and your list needs %s%s. Keep the extra %s?',
                       v_line.have, v_line.short_name, v_line.need,
                       coalesce(' (' || v_line.basis || ')', ''), v_line.have - v_line.need),
        'savings', round(coalesce(v_line.price, 0) * (v_line.have - v_line.need), 2),
        'aisle', v_line.aisle, 'at', v_at));
    elsif v_kind = 'under' then
      v_nudge := jsonb_strip_nulls(jsonb_build_object(
        'product_id', v_line.pid, 'name', v_line.short_name, 'kind', 'under',
        'have', v_line.have, 'need', v_line.need, 'basis', v_line.basis,
        'text', format('Before you go: you''re %s %s short%s. It''s in %s.',
                       v_line.need - v_line.have, v_line.short_name,
                       coalesce(' (' || v_line.basis || ')', ''), v_line.aisle),
        'aisle', v_line.aisle, 'at', v_at));
    elsif v_kind = 'checkout' then
      v_nudge := jsonb_strip_nulls(jsonb_build_object(
        'product_id', v_batch->0->>'product_id', 'name', v_batch->0->>'name', 'kind', 'under',
        'have', (v_batch->0->>'have')::int, 'need', (v_batch->0->>'need')::int,
        'basis', v_batch->0->>'basis', 'aisle', v_batch->0->>'aisle',
        'items', (select jsonb_agg(x - 'basis') from jsonb_array_elements(v_batch) x),
        'text', format('Before you go: you still need %s.',
                       fmt_list(array(select x->>'name' from jsonb_array_elements(v_batch) x))),
        'at', v_at));
    end if;
  end if;
  c.nudge := v_nudge;
  c.nudged := v_nudged;

  -- Human line for the iPad, and line 1 of the LCD (suggestion wins on the LCD).
  if v_next.product_id is not null then
    c.next_step := v_next.aisle || ' → ' || v_next.name
                   || coalesce(', ' || v_next.deal_label, '');
  elsif jsonb_array_length(v_plan) > 0 then
    c.next_step := 'All done → Checkout';
  else
    c.next_step := null;
  end if;

  if v_sugg is not null then
    c.lcd_line1 := fmt_lcd(v_cand.section, v_cand.short_name, fmt_deal_short(v_cand.deal_type, v_cand.deal_value));
  elsif v_next.product_id is not null then
    c.lcd_line1 := fmt_lcd(v_next.section, v_next.name, fmt_deal_short(v_next.deal_type, v_next.deal_value));
  elsif jsonb_array_length(v_plan) > 0 then
    c.lcd_line1 := 'Done -> Checkout';
  else
    c.lcd_line1 := 'KART ready';
  end if;

  update carts set
    items = c.items, total = c.total, savings = c.savings, item_count = c.item_count,
    plan = c.plan, next_step = c.next_step, lcd_line1 = c.lcd_line1,
    suggestion = c.suggestion, suggested_deals = c.suggested_deals,
    nudge = c.nudge, nudged = c.nudged, updated_at = now()
  where cart_id = p_cart_id
  returning * into c;
  return c;
end $$;

-- ── RPCs (writers only use these; CONTRACT §3) ──

-- The pre-P4 signature; without this drop, a re-run would leave two overloads and
-- PostgREST would reject calls as ambiguous.
drop function if exists apply_cart_event(text, text, text, real, text, text, int, text, uuid, text);

create or replace function apply_cart_event(
  p_cart_id      text,
  p_type         text,
  p_product_id   text,
  p_confidence   real,
  p_source       text,
  p_label        text,
  p_camera       int  default null,
  p_snapshot_url text default null,
  p_event_id     uuid default null,
  p_method       text default null,
  p_resolves_event_id uuid default null     -- P4: this manual fix answers that unrecognized event
) returns carts language plpgsql security definer set search_path = public as $$
declare
  c        carts;
  v_section text;
  v_pid    text := nullif(trim(p_product_id), '');
  v_label  text := p_label;
  v_ev     bigint;
  v_items  jsonb;
  v_idx    int;
  v_qty    int;
  v_applied boolean := false;
begin
  if p_type not in ('added', 'removed') then
    raise exception 'p_type must be added or removed, got %', p_type;
  end if;

  insert into carts (cart_id) values (p_cart_id) on conflict do nothing;
  select * into c from carts where cart_id = p_cart_id for update;

  -- Idempotent retries: a repeated event_id returns the cart untouched.
  if p_event_id is not null and exists (select 1 from cart_events where event_id = p_event_id) then
    return c;
  end if;

  -- An id that isn't in the catalog is treated as unrecognized (and kept in the label).
  if v_pid is not null and not exists (select 1 from products where id = v_pid) then
    v_label := concat_ws(' ', v_label, '[unknown id: ' || v_pid || ']');
    v_pid := null;
  end if;

  -- Every event gets an event_id, so the iPad can name any of them in p_resolves_event_id.
  -- Lenient on source/method so a typo can't wedge CV's retry outbox.
  insert into cart_events (event_id, cart_id, trip_id, type, product_id, confidence,
                           source, method, camera, label, snapshot_url)
  values (coalesce(p_event_id, gen_random_uuid()), p_cart_id, c.trip_id, p_type, v_pid, p_confidence,
          case when p_source = 'manual' then 'manual' else 'vision' end,
          case when p_method in ('local', 'cloud', 'memory', 'none', 'manual') then p_method
               when p_source = 'manual' then 'manual' end,
          p_camera, v_label, p_snapshot_url)
  returning id into v_ev;

  if v_pid is not null then
    v_items := c.items;
    select (ord - 1)::int, (elem->>'qty')::int into v_idx, v_qty
    from jsonb_array_elements(v_items) with ordinality as t(elem, ord)
    where elem->>'product_id' = v_pid
    limit 1;

    if p_type = 'added' then
      if v_idx is null then
        v_items := v_items || jsonb_build_array(jsonb_build_object(
          'product_id', v_pid, 'qty', 1, 'added_at', now(), 'last_added_at', now()));
      else
        v_items := jsonb_set(v_items, array[v_idx::text],
          (v_items->v_idx) || jsonb_build_object('qty', v_qty + 1, 'last_added_at', now()));
      end if;
      v_applied := true;
    elsif v_idx is not null then          -- removed, and we had it
      if v_qty <= 1 then
        v_items := v_items - v_idx;
      else
        v_items := jsonb_set(v_items, array[v_idx::text, 'qty'], to_jsonb(v_qty - 1));
      end if;
      v_applied := true;
    end if;

    if v_applied then
      update carts set items = v_items where cart_id = p_cart_id;
      update cart_events set applied = true where id = v_ev;
    end if;

    -- P3: an add tells us where the shopper is. Analytics: an add of an offered product converts.
    if v_applied and p_type = 'added' then
      update deal_offers set accepted_at = now()
      where cart_id = p_cart_id and trip_id = c.trip_id and product_id = v_pid and accepted_at is null;
      select section into v_section from products where id = v_pid;
      update carts set location = jsonb_build_object('section', v_section, 'source', 'item', 'at', now())
      where cart_id = p_cart_id;
    end if;
  end if;

  if p_resolves_event_id is not null then
    update cart_events set resolved_at = now()
    where event_id = p_resolves_event_id and cart_id = p_cart_id and resolved_at is null;
  end if;

  return recompute_cart(p_cart_id);
end $$;

-- Voice agent writes the trip plan: [{ "product_id", "reason", "qty"? }].
-- The backend orders it by route and fills done / aisle / in_stock / deal_label.
create or replace function set_plan(p_cart_id text, p_plan jsonb)
returns carts language plpgsql security definer set search_path = public as $$
declare v_plan jsonb;
begin
  if jsonb_typeof(coalesce(p_plan, '[]'::jsonb)) <> 'array' then
    raise exception 'p_plan must be a JSON array';
  end if;
  select coalesce(jsonb_agg(jsonb_strip_nulls(jsonb_build_object(
           'product_id', elem->>'product_id',
           'reason',     elem->>'reason',
           'qty',        elem->'qty',
           'basis',      elem->>'basis',
           'name',       elem->>'name')) order by ord), '[]'::jsonb)
    into v_plan
  from jsonb_array_elements(coalesce(p_plan, '[]'::jsonb)) with ordinality as t(elem, ord)
  where jsonb_typeof(elem) = 'object';

  insert into carts (cart_id) values (p_cart_id) on conflict do nothing;
  update carts set plan = v_plan where cart_id = p_cart_id;
  return recompute_cart(p_cart_id);
end $$;

-- New trip (the iPad's Welcome tap): empties the cart, issues a new trip_id (the Pi
-- watches it), status → shopping (P2), forgets location (P3) and captions (P6).
create or replace function reset_cart(p_cart_id text)
returns carts language plpgsql security definer set search_path = public as $$
begin
  insert into carts (cart_id) values (p_cart_id) on conflict do nothing;
  delete from transcript where cart_id = p_cart_id;
  update carts set items = '[]', plan = '[]', suggestion = null, suggested_deals = '{}',
                   trip_id = gen_random_uuid(), status = 'shopping', trip_started_at = now(),
                   location = null, nudge = null, nudged = '{}'
  where cart_id = p_cart_id;
  return recompute_cart(p_cart_id);
end $$;

-- Shopper said "no thanks": drop the suggestion; that deal isn't offered again this trip.
create or replace function dismiss_suggestion(p_cart_id text)
returns carts language plpgsql security definer set search_path = public as $$
begin
  update deal_offers o set dismissed_at = now()
  from carts c
  where c.cart_id = p_cart_id and o.cart_id = c.cart_id and o.trip_id = c.trip_id
    and o.deal_id = c.suggestion->>'deal_id' and o.dismissed_at is null;
  update carts set suggestion = null where cart_id = p_cart_id;
  return recompute_cart(p_cart_id);
end $$;

-- Feature switch for one cart (the iPad's demo control). p_on null removes the override.
create or replace function set_feature(p_cart_id text, p_feature text, p_on boolean)
returns carts language plpgsql security definer set search_path = public as $$
begin
  if not exists (select 1 from feature_flags where name = p_feature) then
    raise exception 'unknown feature: %', p_feature;
  end if;
  insert into carts (cart_id) values (p_cart_id) on conflict do nothing;
  update carts set features = case when p_on is null then features - p_feature
                                   else features || jsonb_build_object(p_feature, p_on) end
  where cart_id = p_cart_id;
  return recompute_cart(p_cart_id);
end $$;

-- The shopper answers a quantity nudge. keep (over): the plan now wants what's in the cart.
-- ok / skip: acknowledged and final for the trip (done:<id>). shop ("go get them"): back to
-- shopping, and a promise (shop:<id>): the next checkout lists whatever is still short.
create or replace function dismiss_nudge(p_cart_id text, p_action text)
returns carts language plpgsql security definer set search_path = public as $$
declare c carts;
begin
  if p_action not in ('keep', 'ok', 'skip', 'shop') then
    raise exception 'action must be keep, ok, skip or shop, got %', p_action;
  end if;
  select * into c from carts where cart_id = p_cart_id for update;
  if not found then
    raise exception 'unknown cart: %', p_cart_id;
  end if;
  if c.nudge is not null then
    update carts set nudged = nudged || array(
      select (case when p_action = 'shop' then 'shop:' else 'done:' end) || pid
      from (select x->>'product_id' as pid from jsonb_array_elements(coalesce(c.nudge->'items',
              case when c.nudge->>'kind' = 'under' then jsonb_build_array(c.nudge) end)) x) i)
    where cart_id = p_cart_id;
  end if;
  if c.nudge is not null and p_action = 'keep' and c.nudge->>'kind' = 'over' then
    update carts set plan = (
      select jsonb_agg(case when e->>'product_id' = c.nudge->>'product_id'
                            then e || jsonb_build_object('qty', (c.nudge->>'have')::int) else e end
                       order by ord)
      from jsonb_array_elements(c.plan) with ordinality as t(e, ord))
    where cart_id = p_cart_id;
  end if;
  update carts set nudge = null,
                   status = case when p_action = 'shop' and status = 'checkout' then 'shopping' else status end
  where cart_id = p_cart_id;
  return recompute_cart(p_cart_id);
end $$;

-- ── Catalog changes flow live into every cart ──

create or replace function recompute_all_carts()
returns trigger language plpgsql security definer set search_path = public as $$
declare r record;
begin
  for r in select cart_id from carts loop
    perform recompute_cart(r.cart_id);
  end loop;
  return null;
end $$;

do $$
declare t text;
begin
  foreach t in array array['products', 'deals', 'sections'] loop
    execute format('drop trigger if exists recompute_carts on public.%I', t);
    execute format('create trigger recompute_carts after insert or update or delete on public.%I
                    for each statement execute function recompute_all_carts()', t);
  end loop;
end $$;

create or replace function touch_updated_at()
returns trigger language plpgsql as $$
begin
  new.updated_at := now();
  return new;
end $$;

drop trigger if exists touch on products;
create trigger touch before update on products for each row execute function touch_updated_at();
drop trigger if exists touch on deals;
create trigger touch before update on deals for each row execute function touch_updated_at();

-- ── Who may call what ──
-- Postgres (and Supabase's defaults) let everyone execute new functions; lock it down.

revoke execute on function recompute_cart(text)  from public, anon, authenticated;
revoke execute on function recompute_all_carts() from public, anon, authenticated;

grant execute on function apply_cart_event(text, text, text, real, text, text, int, text, uuid, text, uuid)
  to anon, authenticated, service_role;
grant execute on function set_plan(text, jsonb)          to anon, authenticated, service_role;
grant execute on function reset_cart(text)               to anon, authenticated, service_role;
grant execute on function dismiss_suggestion(text)       to anon, authenticated, service_role;
grant execute on function set_feature(text, text, boolean)  to anon, authenticated, service_role;
grant execute on function dismiss_nudge(text, text)         to anon, authenticated, service_role;
