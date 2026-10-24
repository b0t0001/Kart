# KART market backend

Supabase (Postgres) holds the live catalog and the carts. CV and the iPad only call the RPCs below;
everything derived (prices after deals, totals, route order, next step, the deal suggestion) is
computed here, in SQL, so every client sees the same numbers. Contract: `docs/CONTRACT.md` §2–§3.

```
db/01_schema.sql   tables, realtime, row-level security (read for everyone, writes only via RPCs)
db/02_cart.sql     pricing, recompute_cart, apply_cart_event / set_plan / reset_cart / dismiss_suggestion
db/03_seed.sql     seed_catalog(store.json)
db/04_trip.sql     iPad trip RPCs: set_cart_status, set_location, append_transcript, checkout
supabase/functions/voice-token   P7 Edge Function: short-lived Cartesia token for the iPad
db.py              apply migrations, seed, reset the demo
deploy_functions.sh  deploy the Edge Function and push its Cartesia secrets
simulate_demo.py   plays the 2-minute demo as CV + the iPad would
tests/             pytest against a throwaway local Postgres
```

## Setup

```bash
python3 -m venv backend/.venv && backend/.venv/bin/pip install -r backend/requirements.txt
backend/.venv/bin/python backend/db.py apply          # Supabase: SUPABASE_DB_URL from the repo .env
backend/.venv/bin/python backend/simulate_demo.py     # REST + anon key, same path as the Pi/iPad
backend/deploy_functions.sh                           # needs the Supabase CLI (brew install supabase/tap/supabase)
```

Between demo runs: `backend/.venv/bin/python backend/db.py reset-demo` restores the catalog from
`data/store.json` (undoing merchant edits) and resets cart 7.

## What the clients call

| RPC | Who | Notes |
|---|---|---|
| `apply_cart_event(p_cart_id, p_type, p_product_id, p_confidence, p_source, p_label, p_camera, p_snapshot_url, p_event_id, p_method, p_resolves_event_id)` | CV, iPad manual fix | Repeated `p_event_id` is a no-op. Unknown/null product: recorded, cart untouched. `p_resolves_event_id` clears a confirm card (P4). |
| `set_plan(p_cart_id, p_plan)` | voice agent | `[{product_id, reason, qty?}]`; the backend orders it by route. |
| `reset_cart(p_cart_id)` | iPad | New `trip_id`; the Pi watches it and clears its memory. |
| `dismiss_suggestion(p_cart_id)` | iPad "No thanks" | That deal isn't offered again this trip. |
| `set_cart_status(p_cart_id, p_status)` | iPad, agent | `idle` / `shopping` / `checkout`; `reset_cart` sets `shopping`, `checkout()` sets `paid`. |
| `set_location(p_cart_id, p_section)` | agent ("I'm at aisle 5") | Accepts `A5`, `5`, `aisle 5`. Adds set it too. Drives the route. |
| `append_transcript(p_cart_id, p_role, p_text)` | agent | Captions; `reset_cart` deletes the cart's lines. |
| `checkout(p_cart_id, p_provider)` | iPad Pay | Returns the `receipts` row (same one if called twice). Refuses while an unrecognized item is unresolved; resolve with `apply_cart_event(..., p_resolves_event_id)`. |
| `POST /functions/v1/voice-token {cart_id}` | iPad | `{token, expires_at, agent_id, ws_url, cartesia_version}`; 400 unknown cart, 502 upstream. |

Read with the anon key (realtime on `carts`, `cart_events`, `products`, `deals`, `sections`,
`transcript`, `receipts`). The view
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
deno test backend/supabase/functions/voice-token/
```
