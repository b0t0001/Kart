# KART market backend

Supabase (Postgres) holds the live catalog and the carts. CV and the iPad only call the RPCs below;
everything derived (prices after deals, totals, route order, next step, the deal suggestion) is
computed here, in SQL, so every client sees the same numbers. Contract: `docs/CONTRACT.md` §2–§3.

```
db/01_schema.sql   tables, realtime, row-level security (read for everyone, writes only via RPCs)
db/02_cart.sql     pricing, recompute_cart, apply_cart_event / set_plan / reset_cart / dismiss_suggestion
db/03_seed.sql     seed_catalog(store.json)
db/04_trip.sql     iPad trip RPCs: set_cart_status, set_location, append_transcript, checkout
db/05_merchant.sql merchant change log: merchant_apply / merchant_undo / merchant_cancel (service role only)
db/06_analytics.sql anonymous store_insights / deal_performance views over receipts + deal_offers
supabase/functions/voice-token   P7 Edge Function: short-lived Cartesia token for the iPad
db.py              apply migrations, seed, reset the demo
deploy_functions.sh  deploy the Edge Function and push its Cartesia secrets
go_live.sh         morning go-live against the hosted project: migrate, seed, deploy, simulate, e2e, reset
cart.py            demo levers: add/remove items, plan, reset, deals from the laptop
e2e/               end-to-end tests against a running Supabase (REST + realtime, anon key)
docs/              DEMO.md (runbook), LOCAL_SUPABASE.md (local stack), OVERNIGHT.md (decisions log)
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
`data/store.json` (undoing merchant edits), clears the merchant change log and resets cart 7 to idle.
`--without-deal d-parm-3off` leaves that deal off, so the owner can create it live in the pitch.

## What the clients call

| RPC | Who | Notes |
|---|---|---|
| `apply_cart_event(p_cart_id, p_type, p_product_id, p_confidence, p_source, p_label, p_camera, p_snapshot_url, p_event_id, p_method, p_resolves_event_id)` | CV, iPad manual fix | Repeated `p_event_id` is a no-op. Unknown/null product: recorded, cart untouched. `p_resolves_event_id` clears a confirm card (P4). |
| `set_plan(p_cart_id, p_plan)` | voice agent | `[{product_id, reason?, qty?, basis?, meal?}]`; the same product listed twice becomes one line (qty summed, `meal` + `meals`); the backend orders it by route. |
| `add_to_plan(p_cart_id, p_product_id, p_qty default 1, p_basis default null, p_meal default null)` | voice agent | Atomic list edit: adds to the line (negative lowers it; 0 drops it). Raises on an unknown product. |
| `remove_from_plan(p_cart_id, p_product_id)` | voice agent | Atomic: drops that line (no-op if it isn't there). |
| `set_budget(p_cart_id, p_amount)` | voice agent | "Under $30": recompute fills `budget_left` (budget − total) and `plan_estimate` (what's left on the list at today's sale prices). `null` clears it; reset clears it. |
| `reset_cart(p_cart_id)` | iPad | New `trip_id`; the Pi watches it and clears its memory. |
| `dismiss_suggestion(p_cart_id, p_quiet default true)` | iPad / voice "No thanks" | That deal isn't offered again this trip, and (v0.20) no other unprompted card either: `carts.deals_quiet` until `reset_cart`. Asking still works. `p_quiet false` only clears the card (the agent skipping an item the shopper avoids). |
| `set_cart_status(p_cart_id, p_status)` | iPad, agent | `idle` / `shopping` / `checkout`; `reset_cart` sets `shopping`, `checkout()` sets `paid`. |
| `set_location(p_cart_id, p_section)` | agent ("I'm at aisle 5") | Accepts `A5`, `5`, `aisle 5`. Adds set it too. Drives the route. |
| `append_transcript(p_cart_id, p_role, p_text)` | agent | Captions; `reset_cart` deletes the cart's lines. |
| `checkout(p_cart_id, p_provider)` | iPad Pay | Returns the `receipts` row (same one if called twice). Refuses while an unrecognized item is unresolved; resolve with `apply_cart_event(..., p_resolves_event_id)`. |
| `set_feature(p_cart_id, p_feature, p_on)` | iPad demo switch | Per-cart override of a feature flag (`p_on` null = back to the default). |
| `dismiss_nudge(p_cart_id, p_action)` | iPad, agent | `keep` (over: plan qty := what's in the cart), `ok` / `skip` (acknowledged), or `shop` ("go get them": checkout → shopping). |
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
  not in the cart, offered once per trip; the most recently added pairing wins. A deal the store
  creates after the current suggestion was offered replaces it, so new deals reach shoppers at once.

## Store layouts

`data/layouts/<name>.json` holds a layout's sections (aisles on a rough grid, in walking order by
`x`), a product → section map and optional shelf prices. There are two:
- `mini`: the table-top store, mirroring `data/store.json`.
- `target-berkeley`: Target Berkeley Central, for the video. Its aisles are **placeholders** until the
  shopping trip.

Commands:
- `db.py layout <name>` switches in place. It's one undoable merchant change (`set_layout`); carts and
  deals are untouched, and routing, `next_step`, aisle labels and the LCD follow the new sections.
- `db.py layout --show` prints the active layout.

Rules:
- A layout must place every active product; otherwise nothing changes.
- Undo refuses if products were moved or repriced after the switch.
- `reset-demo` always returns to `mini`, and `sync-catalog` keeps another active layout's placement.
- A placeholder layout won't apply to the hosted project without `--force`.

## Quantity nudges (main feature, on by default)

Feature `quantity_nudges` (CONTRACT v0.12; approved as a main feature 2026-10-24). The global default
lives in `feature_flags`, seeded **true**; `carts.features` overrides it per cart (rollback: per cart
with `set_feature`, globally by setting the default false, or the code tag `stable-pre-nudges`). With it off, cart outputs are identical to tag
`stable-pre-nudges` (checked snapshot by snapshot). With it on, `carts.nudge` works like this:
- It only nudges plan items. It's `over` when the cart has more than the plan's qty (with `savings`
  = price × extra), and `under` at checkout (one combined list).
- Mid-trip `under` nudges, which fire one at a time as the shopper walks past an aisle, sit behind the
  sub-option `quantity_nudges_midtrip`, seeded **false**. When it's on, an item counts as passed only
  once the shopper has moved to another aisle beyond it **after** it joined the plan
  (`carts.plan_joined`, kept only while nudges are on).
- At checkout, every short item goes into **one** nudge with an `items` list, in walking order from
  the shopper; the first item's fields fill `product_id`/`have`/`need` for compatibility. The list
  shrinks as items are fixed. Going to checkout upgrades a mid-trip under nudge to the full list.
- Answers: `ok` / `skip` are final for the trip (`done:<id>` in `carts.nudged`). `shop` ("go get
  them") is a promise (`shop:<id>`): no one-at-a-time nudges for those items while shopping, but the
  next checkout lists whatever is still short. After two promises, the third checkout records the
  item done instead of listing it again.
- One nudge shows at a time, and only when no deal card is up. Each product is nudged at most once
  per direction per trip (`carts.nudged`), and a nudge clears itself when the counts match.
- Plan lines carry the agent's `basis` either way.
- To flip it for everyone: `update feature_flags set enabled_default = true where name = 'quantity_nudges'`.

## Member memory (BETA, off by default)

Feature `member_memory` (CONTRACT v0.14; spec `docs/specs/2026-10-24-member-memory-design.md`). It's off
by default; turn it on per cart with `set_feature`. With it off, `set_member` and `set_demo_date` refuse,
so no cart ever has a member and nothing below happens.
- **Tables:** `members`, `member_purchases` and `member_memories` (`07_members.sql`). They have no anon
  read and no realtime; the iPad and the agent use the RPCs.
- **Signing in:** `set_member(cart, id)` signs a member in for one trip. An unknown id becomes a new
  member, and a new trip signs out. `member_lookup` checks a number without creating anything.
- **History:** a paid receipt on a member's cart is copied into `member_purchases`.
- **The demo date:** `set_demo_date(cart, date)` is the demo fast-forward. It moves "today" for member
  features only; receipts and analytics stay real.
- **The profile:** `member_profile(member, cart)` returns the member, `picks` ("this week": the event's
  saved list, what's due by purchase rhythm, and the usual for this weekday; at most 3, never anything
  on a live deal), `usuals`, `memories` and `last_trip`. Dates use the store's time zone
  (America/Los_Angeles).
- **Memory writes:** `member_remember`, `member_save_for_later` and `member_forget` bump
  `carts.member_rev`, so the iPad refetches.
- **The demo member:** `python backend/members.py seed` (1029, Dylan) builds ten weeks of history and no party:
  in the demo Dylan tells Kart about Leo's party live. `--with-party` adds it (next Saturday, spaghetti ×3,
  marinara ×2) for rehearsals that skip that step. Run it right before judging (`pre_judging.sh --members`).
  `members.py show 1029 [--cart 7]` prints the profile.

## Tests

```bash
LC_ALL=en_US.UTF-8 pg_ctl -D /tmp/kartpg -o "-p 54329" start   # after: initdb -D /tmp/kartpg -U postgres --auth=trust
backend/.venv/bin/python -m pytest backend/tests
deno test backend/supabase/functions/voice-token/
backend/.venv/bin/python -m pytest backend/e2e      # needs a running LOCAL Supabase + .env; refuses hosted
                                                    # unless --allow-hosted (its checkouts drain shared stock)
```
