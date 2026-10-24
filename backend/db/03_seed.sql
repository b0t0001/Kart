-- KART market backend: load data/store.json into the catalog tables.
-- Also the demo reset for the catalog: re-seeding restores every product and deal
-- in the file, delists products that aren't in it, and deletes deals that aren't.
-- Called by backend/scripts/db.py seed (service role only). Safe to re-run.

create or replace function seed_catalog(p_store jsonb)
returns jsonb language plpgsql security definer set search_path = public as $$
declare v_products int; v_deals int;
begin
  insert into store_info (id, name, width, height, entrance_x, entrance_y)
  values (1, p_store->'store'->>'name', (p_store->'store'->>'width')::int,
          (p_store->'store'->>'height')::int, (p_store->'entrance'->>'x')::int,
          (p_store->'entrance'->>'y')::int)
  on conflict (id) do update set name = excluded.name, width = excluded.width,
    height = excluded.height, entrance_x = excluded.entrance_x, entrance_y = excluded.entrance_y;

  insert into sections (id, name, x, y, w, h)
  select s->>'id', s->>'name', (s->>'x')::int, (s->>'y')::int, (s->>'w')::int, (s->>'h')::int
  from jsonb_array_elements(p_store->'sections') s
  on conflict (id) do update set name = excluded.name, x = excluded.x, y = excluded.y,
    w = excluded.w, h = excluded.h;

  insert into products (id, name, short_name, price, section, category, tags, stock,
                        vision_hint, active, sort)
  select p->>'id', p->>'name', coalesce(p->>'short_name', left(p->>'name', 16)),
         (p->>'price')::numeric, p->>'section', coalesce(p->>'category', ''),
         coalesce(array(select jsonb_array_elements_text(p->'tags')), '{}'),
         coalesce((p->>'stock')::int, 0), coalesce(p->>'vision_hint', ''), true, ord::int
  from jsonb_array_elements(p_store->'products') with ordinality as t(p, ord)
  on conflict (id) do update set name = excluded.name, short_name = excluded.short_name,
    price = excluded.price, section = excluded.section, category = excluded.category,
    tags = excluded.tags, stock = excluded.stock, vision_hint = excluded.vision_hint,
    active = true, sort = excluded.sort;
  get diagnostics v_products = row_count;

  update products set active = false
  where active and id not in (select p->>'id' from jsonb_array_elements(p_store->'products') p);

  -- store.json is the mini layout: drop any other layout's sections (delisted products follow along)
  update products set section = p_store->'sections'->0->>'id'
  where section not in (select s->>'id' from jsonb_array_elements(p_store->'sections') s);
  delete from sections where id not in (select s->>'id' from jsonb_array_elements(p_store->'sections') s);
  update store_info set layout = coalesce(p_store->>'layout', 'mini') where id = 1;

  delete from deals
  where id not in (select d->>'id' from jsonb_array_elements(p_store->'deals') d);

  insert into deals (id, product_id, type, value, label, pairs_with, starts_at, ends_at, active, sort)
  select d->>'id', d->>'product_id', d->>'type', (d->>'value')::numeric, d->>'label',
         coalesce(array(select jsonb_array_elements_text(d->'pairs_with')), '{}'),
         (d->>'starts_at')::timestamptz, (d->>'ends_at')::timestamptz, true, ord::int
  from jsonb_array_elements(p_store->'deals') with ordinality as t(d, ord)
  on conflict (id) do update set product_id = excluded.product_id, type = excluded.type,
    value = excluded.value, label = excluded.label, pairs_with = excluded.pairs_with,
    starts_at = excluded.starts_at, ends_at = excluded.ends_at, active = true, sort = excluded.sort;
  get diagnostics v_deals = row_count;

  return jsonb_build_object('products', v_products, 'deals', v_deals);
end $$;

-- ── Store layouts (v0.15): data/layouts/<name>.json, switched in place by db.py layout ──

-- The live layout in the same shape as a layout file (also what undo restores).
create or replace function layout_snapshot()
returns jsonb language sql stable security definer set search_path = public as $$
  select jsonb_build_object(
    'name',     (select layout from store_info where id = 1),
    'store',    (select jsonb_build_object('name', name, 'width', width, 'height', height) from store_info where id = 1),
    'entrance', (select jsonb_build_object('x', entrance_x, 'y', entrance_y) from store_info where id = 1),
    'sections', (select coalesce(jsonb_agg(jsonb_build_object('id', id, 'name', name, 'x', x, 'y', y, 'w', w, 'h', h)
                                           order by x, y, id), '[]') from sections),
    'products', (select coalesce(jsonb_object_agg(id, section), '{}') from products),
    'prices',   (select coalesce(jsonb_object_agg(id, price), '{}') from products))
$$;

-- Switch sections + product placement (+ optional prices) in place. Deals and carts are untouched
-- (carts recompute: next_step and aisles follow). All or nothing: every active product must land
-- in one of the layout's sections.
create or replace function apply_layout(p jsonb)
returns void language plpgsql security definer set search_path = public as $$
declare
  v_ids     text[];
  v_missing text[];
begin
  if jsonb_typeof(p->'sections') is distinct from 'array' or jsonb_array_length(p->'sections') = 0 then
    raise exception 'layout % has no sections', p->>'name';
  end if;
  v_ids := array(select s->>'id' from jsonb_array_elements(p->'sections') s);
  select array_agg(m.key) into v_missing
  from jsonb_each_text(coalesce(p->'products', '{}')) m where not (m.value = any(v_ids));
  if v_missing is not null then
    raise exception 'layout % puts products in sections it doesn''t have: %', p->>'name', v_missing;
  end if;

  update store_info set
    layout     = coalesce(p->>'name', layout),
    name       = coalesce(p->'store'->>'name', name),
    width      = coalesce((p->'store'->>'width')::int, width),
    height     = coalesce((p->'store'->>'height')::int, height),
    entrance_x = coalesce((p->'entrance'->>'x')::int, entrance_x),
    entrance_y = coalesce((p->'entrance'->>'y')::int, entrance_y)
  where id = 1;

  insert into sections (id, name, x, y, w, h)
  select s->>'id', s->>'name', (s->>'x')::int, (s->>'y')::int, (s->>'w')::int, (s->>'h')::int
  from jsonb_array_elements(p->'sections') s
  on conflict (id) do update set name = excluded.name, x = excluded.x, y = excluded.y, w = excluded.w, h = excluded.h;

  update products pr set section = m.value from jsonb_each_text(coalesce(p->'products', '{}')) m where pr.id = m.key;
  update products pr set price = m.value::numeric from jsonb_each_text(coalesce(p->'prices', '{}')) m where pr.id = m.key;

  select array_agg(id) into v_missing from products where active and not (section = any(v_ids));
  if v_missing is not null then
    raise exception 'layout % doesn''t place these products: %', p->>'name', v_missing;
  end if;
  update products set section = v_ids[1] where not active and not (section = any(v_ids));
  delete from sections where not (id = any(v_ids));
end $$;

revoke execute on function layout_snapshot() from public, anon, authenticated;
revoke execute on function apply_layout(jsonb) from public, anon, authenticated;
grant execute on function layout_snapshot(), apply_layout(jsonb) to service_role;

revoke execute on function seed_catalog(jsonb) from public, anon, authenticated;
grant execute on function seed_catalog(jsonb) to service_role;
