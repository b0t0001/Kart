# KART market backend

Supabase (Postgres) holds the live catalog and the carts. CV and the iPad only call the RPCs below;
everything derived (prices after deals, totals, route order, next step, the deal suggestion) is
computed here, in SQL, so every client sees the same numbers. Contract: `docs/CONTRACT.md` §2–§3.

```
db/01_schema.sql   tables, realtime, row-level security (read for everyone, writes only via RPCs)
db/02_cart.sql     pricing, recompute_cart, apply_cart_event / set_plan / reset_cart / dismiss_suggestion
db/03_seed.sql     seed_catalog(store.json)
db.py              apply migrations, seed, reset the demo
simulate_demo.py   plays the 2-minute demo as CV + the iPad would
tests/             pytest against a throwaway local Postgres
```

## Setup

```bash
python3 -m venv backend/.venv && backend/.venv/bin/pip install -r backend/requirements.txt
backend/.venv/bin/python backend/db.py apply          # Supabase: SUPABASE_DB_URL from the repo .env
backend/.venv/bin/python backend/simulate_demo.py     # REST + anon key, same path as the Pi/iPad
```

Between demo runs: `backend/.venv/bin/python backend/db.py reset-demo` restores the catalog from
`data/store.json` (undoing merchant edits) and resets cart 7.

## What the clients call

| RPC | Who | Notes |
|---|---|---|
| `apply_cart_event(p_cart_id, p_type, p_product_id, p_confidence, p_source, p_label, p_camera, p_snapshot_url, p_event_id, p_method)` | CV, iPad manual fix | Repeated `p_event_id` is a no-op. Unknown/null product: recorded, cart untouched. |
| `set_plan(p_cart_id, p_plan)` | voice agent | `[{product_id, reason, qty?}]`; the backend orders it by route. |
| `reset_cart(p_cart_id)` | iPad | New `trip_id`; the Pi watches it and clears its memory. |
| `dismiss_suggestion(p_cart_id)` | iPad "No thanks" | That deal isn't offered again this trip. |

Read with the anon key (realtime on `carts`, `cart_events`, `products`, `deals`, `sections`). The view
`product_catalog` gives each product with its best live deal (`sale_price`, `deal_label`, `aisle`).

## Rules worth knowing

- **Price you saw is the price you pay** (CONTRACT P10): price drops and new deals reach items already
  in a cart; price increases and ended deals don't.
- **Route:** plan items in walking order from the shopper's last aisle (ahead first, then back);
  `next_step` is the first one not yet in the cart and in stock.
- **Suggestion:** a live deal whose `pairs_with` matches something in the cart, product in stock and
  not in the cart, offered once per trip; the most recently added pairing wins.

## Tests

```bash
LC_ALL=en_US.UTF-8 pg_ctl -D /tmp/kartpg -o "-p 54329" start   # after: initdb -D /tmp/kartpg -U postgres --auth=trust
backend/.venv/bin/python -m pytest backend/tests
```
