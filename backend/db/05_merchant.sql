-- KART market backend: the merchant agent's audit log, apply and undo.
-- The agent (merchant/) can only INSERT a 'pending' row with a plain-English summary.
-- A change touches the catalog only when the owner confirms it (merchant_apply), and
-- every applied change can be undone (merchant_undo). Catalog triggers from 02_cart.sql
-- recompute open carts, so confirmed changes reach the iPad within a second.
-- Service role only: anon can't read or call any of this. Safe to re-run.

create table if not exists merchant_changes (
  id          bigserial primary key,
  created_at  timestamptz not null default now(),
  tool        text not null check (tool in ('update_price', 'move_product', 'set_stock',
                                            'add_product', 'create_deal', 'end_deal', 'undo')),
  args        jsonb not null,          -- validated tool input (+ "expect": values the preview showed)
  summary     text not null,           -- the plain-English preview the owner confirmed
  request     text,                    -- what the owner said
  status      text not null default 'pending'
              check (status in ('pending', 'applied', 'cancelled', 'undone')),
  decided_at  timestamptz,
  before      jsonb,                   -- catalog row(s) before, captured when applied
  after       jsonb,                   -- catalog row(s) after
  undo_of     bigint references merchant_changes(id)
);
create index if not exists merchant_changes_recent on merchant_changes (id desc);

alter table merchant_changes enable row level security;     -- no policies: anon sees nothing
revoke all on merchant_changes from anon, authenticated;
grant all on merchant_changes to service_role;
grant usage on sequence merchant_changes_id_seq to service_role;

-- The preview showed a value; if the catalog moved since, refuse rather than surprise.
create or replace function merchant_expect(p_row jsonb, p_expect jsonb, p_what text)
returns void language plpgsql as $$
declare k text;
begin
  for k in select jsonb_object_keys(coalesce(p_expect, '{}'::jsonb)) loop
    if (p_row->k) is distinct from (p_expect->k)
       and not (jsonb_typeof(p_row->k) = 'number' and (p_row->>k)::numeric = (p_expect->>k)::numeric) then
      raise exception 'stale: % % is now %, not % as previewed; ask again', p_what, k, p_row->k, p_expect->k;
    end if;
  end loop;
end $$;

-- Reverse one applied change. Returns {before, after} of what the reversal touched.
create or replace function merchant_reverse(ch merchant_changes)
returns jsonb language plpgsql security definer set search_path = public as $$
declare cur jsonb; r jsonb;
begin
  if ch.tool in ('update_price', 'move_product', 'set_stock') then
    select to_jsonb(p) into cur from products p where id = ch.after->>'id' for update;
    -- only if nothing changed it since; otherwise undo would clobber the newer change
    perform merchant_expect(cur, jsonb_build_object(
      case ch.tool when 'update_price' then 'price' when 'move_product' then 'section' else 'stock' end,
      ch.after->case ch.tool when 'update_price' then 'price' when 'move_product' then 'section' else 'stock' end),
      'product ' || (ch.after->>'id'));
    update products set
      price   = case when ch.tool = 'update_price' then (ch.before->>'price')::numeric else price end,
      section = case when ch.tool = 'move_product' then ch.before->>'section' else section end,
      stock   = case when ch.tool = 'set_stock' then (ch.before->>'stock')::int else stock end
    where id = ch.after->>'id'
    returning to_jsonb(products.*) into r;

  elsif ch.tool = 'add_product' then
    -- delist rather than delete: carts and history may reference it
    update products set active = false where id = ch.after->>'id' returning to_jsonb(products.*) into r;

  elsif ch.tool = 'create_deal' then
    update deals set active = false where id = ch.after->>'id' returning to_jsonb(deals.*) into r;
    update deals set active = true
    where id in (select d->>'id' from jsonb_array_elements(coalesce(ch.before->'ended_deals', '[]')) d);

  elsif ch.tool = 'end_deal' then
    update deals set active = true where id = ch.before->>'id' returning to_jsonb(deals.*) into r;

  else
    raise exception 'change % (%) cannot be undone', ch.id, ch.tool;
  end if;
  return jsonb_build_object('before', ch.after, 'after', r);
end $$;

-- The owner clicked Confirm.
create or replace function merchant_apply(p_change_id bigint)
returns merchant_changes language plpgsql security definer set search_path = public as $$
declare
  ch  merchant_changes;
  a   jsonb;
  b   jsonb;
  r   jsonb;
  tgt merchant_changes;
begin
  select * into ch from merchant_changes where id = p_change_id for update;
  if not found then
    raise exception 'unknown change %', p_change_id;
  end if;
  if ch.status <> 'pending' then
    raise exception 'change % is already %', p_change_id, ch.status;
  end if;
  a := ch.args;

  if ch.tool in ('update_price', 'move_product', 'set_stock') then
    select to_jsonb(p) into b from products p where id = a->>'product_id' and active for update;
    if b is null then
      raise exception 'unknown product %', a->>'product_id';
    end if;
    perform merchant_expect(b, a->'expect', 'product ' || (a->>'product_id'));
    update products set
      price   = case when ch.tool = 'update_price' then (a->>'price')::numeric else price end,
      section = case when ch.tool = 'move_product' then a->>'section' else section end,
      stock   = case when ch.tool = 'set_stock' then (a->>'stock')::int else stock end
    where id = a->>'product_id'
    returning to_jsonb(products.*) into r;

  elsif ch.tool = 'add_product' then
    insert into products (id, name, short_name, price, section, category, tags, stock, vision_hint, sort)
    values (a->>'id', a->>'name', a->>'short_name', (a->>'price')::numeric, a->>'section',
            a->>'category', array(select jsonb_array_elements_text(a->'tags')), (a->>'stock')::int,
            a->>'vision_hint', (select coalesce(max(sort), 0) + 1 from products))
    returning to_jsonb(products.*) into r;

  elsif ch.tool = 'create_deal' then
    -- one live deal per product: the new one replaces whatever was running
    select coalesce(jsonb_agg(to_jsonb(d)), '[]') into b
    from deals d where d.product_id = a->>'product_id' and d.active;
    update deals set active = false where product_id = a->>'product_id' and active;
    insert into deals (id, product_id, type, value, label, pairs_with, ends_at)
    values (a->>'deal_id', a->>'product_id', a->>'type', (a->>'value')::numeric, a->>'label',
            array(select jsonb_array_elements_text(a->'pairs_with')), (a->>'ends_at')::timestamptz)
    returning to_jsonb(deals.*) into r;
    b := jsonb_build_object('ended_deals', b);

  elsif ch.tool = 'end_deal' then
    select to_jsonb(d) into b from deals d where id = a->>'deal_id' and active for update;
    if b is null then
      raise exception 'deal % is not running', a->>'deal_id';
    end if;
    update deals set active = false where id = a->>'deal_id' returning to_jsonb(deals.*) into r;

  elsif ch.tool = 'undo' then
    select * into tgt from merchant_changes where id = (a->>'change_id')::bigint for update;
    if not found or tgt.status <> 'applied' or tgt.tool = 'undo' then
      raise exception 'change % can''t be undone (it is %)', a->>'change_id', coalesce(tgt.status, 'missing');
    end if;
    r := merchant_reverse(tgt);
    b := r->'before';
    r := r->'after';
    update merchant_changes set status = 'undone' where id = tgt.id;
    ch.undo_of := tgt.id;
  end if;

  update merchant_changes
  set status = 'applied', decided_at = now(), before = b, after = r, undo_of = ch.undo_of
  where id = p_change_id
  returning * into ch;
  return ch;
end $$;

-- One-click Undo in the change log: logs an 'undo' change and applies it right away.
create or replace function merchant_undo(p_change_id bigint)
returns merchant_changes language plpgsql security definer set search_path = public as $$
declare v_id bigint;
begin
  insert into merchant_changes (tool, args, summary, request)
  select 'undo', jsonb_build_object('change_id', id), 'Undo #' || id || ': ' || summary, 'Undo button'
  from merchant_changes where id = p_change_id
  returning id into v_id;
  if v_id is null then
    raise exception 'unknown change %', p_change_id;
  end if;
  return merchant_apply(v_id);
end $$;

create or replace function merchant_cancel(p_change_id bigint)
returns merchant_changes language plpgsql security definer set search_path = public as $$
declare ch merchant_changes;
begin
  update merchant_changes set status = 'cancelled', decided_at = now()
  where id = p_change_id and status = 'pending'
  returning * into ch;
  if not found then
    raise exception 'change % is not pending', p_change_id;
  end if;
  return ch;
end $$;

revoke execute on function merchant_expect(jsonb, jsonb, text)    from public, anon, authenticated;
revoke execute on function merchant_reverse(merchant_changes)     from public, anon, authenticated;
revoke execute on function merchant_apply(bigint)                  from public, anon, authenticated;
revoke execute on function merchant_undo(bigint)                   from public, anon, authenticated;
revoke execute on function merchant_cancel(bigint)                 from public, anon, authenticated;
grant execute on function merchant_apply(bigint), merchant_undo(bigint), merchant_cancel(bigint)
  to service_role;
