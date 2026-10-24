-- KART market backend: the iPad's trip RPCs (CONTRACT §5a, accepted in v0.6).
-- P2 set_cart_status · P3 set_location · P6 append_transcript · P8 checkout.
-- Safe to re-run.

-- P2: screen routing. 'paid' is reserved for checkout(), so a receipt always exists for it.
create or replace function set_cart_status(p_cart_id text, p_status text)
returns carts language plpgsql security definer set search_path = public as $$
begin
  if p_status not in ('idle', 'shopping', 'checkout') then
    raise exception 'status must be idle, shopping or checkout (paid comes from checkout()), got %', p_status;
  end if;
  insert into carts (cart_id) values (p_cart_id) on conflict do nothing;
  update carts set status = p_status where cart_id = p_cart_id;
  return recompute_cart(p_cart_id);
end $$;

-- P3: "I'm at aisle 5". Accepts a section id ("A5"), "5", "aisle 5" or a section name.
create or replace function set_location(p_cart_id text, p_section text)
returns carts language plpgsql security definer set search_path = public as $$
declare v_section text;
begin
  select id into v_section from sections
  where lower(id) = lower(trim(p_section))
     or id = 'A' || nullif(regexp_replace(p_section, '\D', '', 'g'), '')
     or lower(name) = lower(trim(p_section))
  order by lower(id) = lower(trim(p_section)) desc
  limit 1;
  if v_section is null then
    raise exception 'unknown section: %', p_section;
  end if;
  insert into carts (cart_id) values (p_cart_id) on conflict do nothing;
  update carts set location = jsonb_build_object('section', v_section, 'source', 'voice', 'at', now())
  where cart_id = p_cart_id;
  return recompute_cart(p_cart_id);
end $$;

-- P6: one caption line, tagged with the cart's current trip.
create or replace function append_transcript(p_cart_id text, p_role text, p_text text)
returns transcript language plpgsql security definer set search_path = public as $$
declare r transcript;
begin
  if p_role not in ('user', 'agent') then
    raise exception 'role must be user or agent, got %', p_role;
  end if;
  insert into carts (cart_id) values (p_cart_id) on conflict do nothing;
  insert into transcript (cart_id, trip_id, role, text)
  values (p_cart_id, (select trip_id from carts where cart_id = p_cart_id), p_role, p_text)
  returning * into r;
  return r;
end $$;

-- P8: pay (simulated in v1). Writes the trip's receipt, takes the units off the shelf
-- stock, and sets status 'paid'. Calling it again for the same trip returns the same
-- receipt. Refuses while an unrecognized item is unresolved (P4), so nothing unbilled
-- leaves the store.
create or replace function checkout(p_cart_id text, p_provider text default 'simulated')
returns receipts language plpgsql security definer set search_path = public as $$
declare
  c     carts;
  r     receipts;
  v_unresolved int;
begin
  select * into c from carts where cart_id = p_cart_id for update;
  if not found then
    raise exception 'unknown cart: %', p_cart_id;
  end if;

  select * into r from receipts where cart_id = p_cart_id and trip_id = c.trip_id;
  if found then
    return r;
  end if;

  select count(*) into v_unresolved from cart_events
  where cart_id = p_cart_id and trip_id = c.trip_id and type = 'added'
    and product_id is null and resolved_at is null;
  if v_unresolved > 0 then
    raise exception 'unresolved_items: % unrecognized item(s) need confirming before checkout', v_unresolved
      using hint = 'resolve them with apply_cart_event(..., p_resolves_event_id)';
  end if;

  c := recompute_cart(p_cart_id);
  insert into receipts (cart_id, trip_id, total, savings, item_count, duration_s, provider, items)
  values (p_cart_id, c.trip_id, c.total, c.savings, c.item_count,
          extract(epoch from now() - c.trip_started_at)::int,
          coalesce(nullif(p_provider, ''), 'simulated'), c.items)
  returning * into r;

  update products p set stock = greatest(p.stock - (e->>'qty')::int, 0)
  from jsonb_array_elements(c.items) e
  where p.id = e->>'product_id';

  update carts set status = 'paid' where cart_id = p_cart_id;
  return r;
end $$;

grant execute on function set_cart_status(text, text)       to anon, authenticated, service_role;
grant execute on function set_location(text, text)          to anon, authenticated, service_role;
grant execute on function append_transcript(text, text, text) to anon, authenticated, service_role;
grant execute on function checkout(text, text)              to anon, authenticated, service_role;
