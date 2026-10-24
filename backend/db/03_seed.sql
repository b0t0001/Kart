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

revoke execute on function seed_catalog(jsonb) from public, anon, authenticated;
grant execute on function seed_catalog(jsonb) to service_role;
