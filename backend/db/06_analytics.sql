-- KART market backend: anonymous store analytics for the merchant console (Visa: commerce impact).
-- Aggregates only: no shopper identity exists anywhere in the schema, and nothing here is per person.
-- Service role only. Safe to re-run.

alter table deal_offers enable row level security;          -- no policies: anon sees nothing
revoke all on deal_offers from anon, authenticated;
grant all on deal_offers to service_role;

-- One row: how trips are going.
create or replace view store_insights as
with paid as (select * from receipts where status = 'paid'),
     offers as (select * from deal_offers)
select
  (select count(*) from paid)                                        as trips,
  (select count(*) from carts where status in ('shopping', 'checkout')) as trips_in_progress,
  (select round(avg(total), 2) from paid)                            as avg_basket,
  (select round(avg(item_count), 1) from paid)                       as avg_items,
  (select round(avg(savings), 2) from paid)                          as avg_savings,
  (select round(avg(duration_s)) from paid)                          as avg_trip_s,
  (select coalesce(sum(total), 0) from paid)                         as revenue,
  (select count(*) from offers)                                      as deals_offered,
  (select count(*) from offers where accepted_at is not null)        as deals_accepted,
  (select count(*) from offers where dismissed_at is not null)       as deals_dismissed,
  (select round(100.0 * count(*) filter (where accepted_at is not null) / nullif(count(*), 0))
     from offers)                                                    as deal_conversion_pct,
  -- what deal-bought items added to baskets, at the price shoppers paid
  (select coalesce(sum((i->>'price')::numeric * (i->>'qty')::int), 0)
     from paid, jsonb_array_elements(paid.items) i where i ? 'deal_id') as deal_revenue;

-- One row per deal: offered at the moment of decision → taken → sold.
create or replace view deal_performance as
select
  d.id                                   as deal_id,
  p.short_name                           as product,
  d.label,
  d.id in (select id from live_deals)    as live,
  count(distinct o.id)                                               as offered,
  count(distinct o.id) filter (where o.accepted_at is not null)      as accepted,
  count(distinct o.id) filter (where o.dismissed_at is not null)     as dismissed,
  round(100.0 * count(distinct o.id) filter (where o.accepted_at is not null)
        / nullif(count(distinct o.id), 0))                           as conversion_pct,
  coalesce((select sum((i->>'qty')::int) from receipts r, jsonb_array_elements(r.items) i
            where r.status = 'paid' and i->>'deal_id' = d.id), 0)    as units_sold
from deals d
join products p on p.id = d.product_id
left join deal_offers o on o.deal_id = d.id
group by d.id, p.short_name, d.label, d.created_at
order by count(distinct o.id) desc, d.created_at desc;

revoke all on store_insights, deal_performance from anon, authenticated;
grant select on store_insights, deal_performance to service_role;
