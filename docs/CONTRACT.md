# KART integration contract — v0.20 (DRAFT)

> **Draft status:** this was written before the manager knew about the two existing chats. Their design decisions win; the manager folds them in here. Known change pending: the cart's screen is an **iPad app mounted on the cart** (voice agent, navigation, auto-checkout), which replaces the phone web app (§5) and probably the LCD. §5 will be rewritten from the iPad chat's design.

**Owner: the manager session.** This file is the single source of truth for how the three workstreams fit together. It lives at
`<repo>/docs/CONTRACT.md` (the main checkout). **Read it by that absolute path; never copy or edit it in your worktree.** To change it, see §8.

Product background: `project_context/claude_CLAUDE.md` and `project_context/claude_SCOPE.md`. North star = the 2-minute demo in those docs.

```
 Brio cams ─▶ [CV · pi/]  ── apply_cart_event ──▶  [Supabase · backend/]  ◀── realtime subscribe ── [Mobile · web/]
               reads data/store.json                 carts, cart_events,      ── set_plan / manual fix ─▶
               reads carts.lcd_line1 + total → LCD    products, deals           reads data/store.json
```

## 1. Ownership

| Path | Owner | Notes |
|---|---|---|
| `pi/`, `tools/` | **CV** chat | Runs on the Raspberry Pi in the end; develop on the Mac first |
| `ios/`, `agent/` | **iPad app** chat | Cart-mounted SwiftUI iPad app + Cartesia Line voice agent: navigation, cart, auto-checkout |
| `backend/`, `data/`, `merchant/` | **Market backend** chat (Dylan is starting it) | Catalog, DB schema, RPCs, deal/route logic, and the merchant admin agent; publish `data/store.json` early, since CV needs it |
| `hardware/` | **Hardware teammate's** chat (on his own computer, synced through GitHub) | Pi setup, autostart, camera/wiring checks; runs `pi/` on the real hardware and reports bugs |
| `pi/tests/clips/` | **Hardware** chat writes, **CV** owns (v0.11) | Real half-size regression clips: 640×360, quality 80, 5 Hz, ≤ 3 MB each, ≤ 25 MB for the first batch, each with an `expected.json`. Full-res clips stay out of git |
| `docs/CONTRACT.md`, root `.gitignore` | **Manager** | Propose changes, don't edit |

**Hardware lane handoff from CV (v0.7):** CV ships no systemd unit; `hardware/` owns autostart.
- Command, run from the repo root with restart-on-exit: `~/venv/bin/python pi/main.py live`.
- Install steps will be in `pi/README.md`: a venv with `--system-site-packages` plus apt `python3-opencv`; `pip install -r pi/requirements-pi.txt`; `tools/fetch_model.py`; camera paths from `tools/snap.py --list` written into `pi/config.json`.
- Reset: the Pi polls `carts.trip_id` every 2 s and persists the last value it saw, so a reset made while the Pi was off is caught at boot.
- CV's plan is `pi/docs/plans/2026-10-24-cv-pipeline.md`.

**Final camera layout (v0.13, locked by Dylan; v0.18: cam1 is now on USB port `usb-0:1.3`, and the floor liner is a black T-shirt):**
- **cam0** = Brio 101 (`usb-0:1.1`), mid-front, looking back down the basket.
- **cam1** = Aoozi QS-WB-202PRO wide-angle (`usb-0:1.3`; port 1.2 is loose), high at the top-basket end, looking down.
- 15 fps. Together they pass the 4-corner test.
- No 3rd cam: three 720p MJPEG streams on the Pi's single USB 2.0 bus corrupt frames.

**Hardware lane, as built (`230d259`, `6ea03d4`, v0.9):** `hardware/setup_pi.sh`, `sync_pi.sh`, `check_cameras.py`, `kart-cv.service` + `install_service.sh`. Real Pi: Debian 13 trixie, **Python 3.13.5**, 3.7 GB RAM. Cameras: **Brio 101**; use the stable `/dev/v4l/by-path/…` paths in `hardware/README.md`. Don't set `CAP_PROP_BUFFERSIZE=1`, since it halves the fps.

**Sync:** the teammate's machine syncs through GitHub (`b0t0001/kart`, `main`). Pull before you work, push right after you commit; if a push is rejected, run `git pull --rebase` and push again. On Dylan's Mac, the manager pushes and pulls `main`.

Stay inside your paths. Put ignore rules in a `.gitignore` **inside your own directory** (avoids merge conflicts). Commit only your own paths (`git commit -- <your dir>`); the manager coordinates anything that spans workstreams with the user.

## 2. Store catalog — `data/store.json` (backend owns)

```jsonc
{
  "store":    { "name": "Kart Demo Warehouse", "width": 20, "height": 12 },   // grid units for the map
  "entrance": { "x": 0, "y": 6 },
  "sections": [
    { "id": "A4", "name": "Aisle 4 · Cheese & Deli", "x": 4, "y": 1, "w": 1, "h": 8 }
  ],
  "products": [
    {
      "id": "kirkland-parmesan",                 // kebab-case slug: THE join key everywhere
      "name": "Kirkland Parmigiano Reggiano",
      "price": 12.99,                            // list price, USD
      "section": "A4",
      "category": "cheese",
      "tags": ["pasta", "italian"],              // used by the voice agent for planning
      "vision_hint": "wedge of hard pale-yellow cheese in clear wrap, red/white Kirkland label"  // used in the CV prompt
    }
  ],
  "deals": [
    { "id": "d-parm-3off", "product_id": "kirkland-parmesan", "type": "amount_off", "value": 3.00,
      "label": "$3 off", "pairs_with": ["barilla-spaghetti", "rao-marinara"] }   // suggest this deal when a pairs_with item is added
  ]
}
```

Rules: every physical demo prop (~10–15 real items at the table) has exactly one product. `id`s never change once published.

**Published (v0.4):** `data/store.json` v1 is on `main` (commit `e44879c`): 18 products, 5 deals, aisles `A1`–`A9` plus checkout zone `CK`. **Use it instead of the example above.** It adds these fields; all are additive, so ignoring them breaks nothing:
- top-level `version` (int)
- `products[].short_name` (e.g. `"Parmesan"`): use it for `next_step` and spoken lines. **v0.13: it's a natural spoken name, ≤ 16 chars** (e.g. `"Taco Seasoning"`). `lcd_line1` truncates on its own, and the LCD is deferred anyway.
- `products[].stock` (int)
- `deals[].ends_at` (ISO timestamp or null)
- `deals[].type` can also be `"percent_off"` (`value` = percent). Only the backend does price math; readers display `label`.

**Source of truth (v0.4):** once the merchant agent is live, the Supabase `products` / `deals` tables are authoritative, and `store.json` is the seed plus CV's catalog.
- **iPad:** read prices, deals and stock from Supabase (realtime on `products` and `deals`), not from the static file. That's what makes "owner says parmesan $3 off → the cart shows it within seconds" work.
- **CV:** keep reading `store.json` (`id`, `name`, `vision_hint`). The backend re-exports it whenever the merchant adds a product.

## 3. Database — Supabase (backend owns the schema)

**`carts`** (realtime ON) — one row per cart; demo cart is `"7"`.

| column | type | meaning |
|---|---|---|
| `cart_id` | text PK | `"7"` |
| `items` | jsonb | `[{ "product_id", "name", "price", "qty", "deal_label"?, "added_at" }]` — `price` is after any deal |
| `total` | numeric | Σ price × qty (an **estimate**, not checkout) |
| `plan` | jsonb | `[{ "product_id", "reason", "done" }]` written by the voice agent, in route order |
| `next_step` | text | human sentence for the phone, e.g. `"Aisle 4 → Parmesan, $3 off"` |
| `lcd_line1` | text | **≤ 16 chars**, line 1 of the cart LCD, e.g. `"A4 Parmesan -$3"` |
| `suggestion` | jsonb \| null | `{ "product_id", "deal_id", "text" }` — the deal offered at the moment of decision |
| `updated_at` | timestamptz | |

**`cart_events`** (realtime ON, append-only) — the audit trail; also powers "what the AI saw".

`id` bigserial · `cart_id` · `type` (`added` \| `removed`) · `product_id` (null = unrecognized) · `confidence` real · `source` (`vision` \| `manual`) · `camera` int null · `label` text (raw model answer) · `snapshot_url` text null · `created_at`

**`products`, `deals`** — seeded from `data/store.json` by a backend script.

### RPCs (Postgres functions, called via `POST {SUPABASE_URL}/rest/v1/rpc/<name>` / `client.rpc(...)`)

Writers **only** use these; nobody writes `carts.items` directly.

- `apply_cart_event(p_cart_id text, p_type text, p_product_id text, p_confidence real, p_source text, p_label text, p_camera int default null, p_snapshot_url text default null, p_event_id uuid default null, p_method text default null) → carts row`
  Inserts the event; on `added` qty+1 (or appends), on `removed` qty−1 (drop at 0); recomputes `total`, plan `done` flags, `next_step`, `lcd_line1`, `suggestion`. A null `product_id` records the event but doesn't touch the cart.
  **Idempotent on `p_event_id`** (v0.3): CV retries failed sends from a disk outbox, so a repeated `event_id` must return the current cart without applying the event again. `cart_events` gets `event_id uuid unique` and `method text` (`local` \| `cloud` \| `memory` \| `none` \| `manual`).
- `set_plan(p_cart_id text, p_plan jsonb) → carts row` — voice agent writes the trip plan; recomputes `next_step` / `lcd_line1`.
- `reset_cart(p_cart_id text) → carts row` — clears items/plan/suggestion **and sets a new `carts.trip_id` (uuid)**. For new trips and demo resets.

### Quantity nudges, "right amount for the meal" (v0.12): **ON BY DEFAULT since v0.18 (Dylan approved)**; mid-trip under nudges stay off

**Stability rule:** with the feature off, nothing changes. `carts.nudge` stays `null`, the iPad shows no nudge UI, the agent says nothing new, and CV counts exactly as before. The stable rollback point is git tag `stable-pre-nudges`. Once Dylan has tested it and says it's good, the default flips to on.

- **Flag (backend):** feature `quantity_nudges`.
  - A global default lives in a `feature_flags(name, enabled_default)` table, seeded **false**.
  - Per-cart overrides live in `carts.features jsonb` (e.g. `{"quantity_nudges": true}`).
  - RPC `set_feature(p_cart_id text, p_feature text, p_on boolean) → carts row`.
  - `carts.features` is readable by anon, so the iPad knows whether to show the beta UI.
- **Plan lines:** `plan[].basis` (text, additive) holds the agent's reasoning for the amount, e.g. `"8 people × 2 tacos ≈ 16 tortillas → 2 packs of 10"`.
- **`carts.nudge` jsonb | null:** `{product_id, name, kind: "under"|"over", have, need, basis, text, savings?, aisle?, at}`.
  - **over:** set right after an applied `added` takes cart qty above plan qty. Text: *"That's your 3rd bag of avocados. One covers taco night for 4. Keep it?"*, plus `savings` = the price of the extra units.
  - **under:** set when the shopper moves on from that item's aisle (`location` passes it on the route) or on `set_cart_status('checkout')`. Text: *"Before you go: you're one pack of tortillas short for 8 people. It's in Aisle 2."*
  - **Rules:** only for plan items (impulse buys are never nudged), once per product per direction per trip (`carts.nudged text[]`), and a pending deal suggestion takes priority.
  - It clears itself when the counts match (`have == need`).
- **RPC `dismiss_nudge(p_cart_id text, p_action text) → carts row`:**
  - `keep` (over): raises the plan qty to `have`, so the nudge stops.
  - `ok`: acknowledges it; that product/direction isn't re-nudged this trip.
- **iPad:**
  - A nudge card, styled like the deal card, with "Keep it" / "Got it" buttons; Kart says `text` once.
  - **+ / −** on each list line (`apply_cart_event`, `source: "manual"`).
  - A demo-controls switch "Quantity nudges (beta)" that calls `set_feature` for its own cart.
  - All of this is shown only when the flag is on for the cart.
- **Agent:**
  - Always writes `basis` when planning; it's harmless when the flag is off.
  - Speaks `nudge.text` once when it changes.
  - Maps spoken "keep it" / "ok" to `dismiss_nudge`.
- **CV:** config `"claude_count": false` (default) in `pi/config.json`.
  - When it's true, Claude's closed-set answer includes `count` (1–6), and one blob holding N identical items emits **N events**, each with its own `event_id`.
  - A blob much bigger than the product's enrolled crops goes to Claude for the count.
  - The event shape is unchanged.

### Member memory (v0.14): BETA, OFF BY DEFAULT. **Merged to `main` in v0.19** (rollback tag `stable-pre-memory`)

Spec: `docs/specs/2026-10-24-member-memory-design.md`. Flag: `member_memory`. Rollback tag: `stable-pre-memory`, created by the manager on `main` right before the merge.

**Stability rule:** with the flag off, `set_member` and `set_demo_date` raise `feature_off: member_memory`, so no cart ever has a member or a demo date, and the agent, iPad and backend behave byte-for-byte as before (snapshot-checked at merge). The read/write RPCs take a member id directly (demo-grade, no auth). Known gap: `set_member(cart, null)` also refuses with the flag off, so turning the flag off mid-trip doesn't sign the member out.

- **DB** (`backend/db/07_members.sql`, additive):
  - Tables `members`, `member_purchases` (filled from paid receipts by a trigger) and `member_memories` (`event` | `preference` | `note`). RLS is on, with **no anon read and no realtime**; access is only through security-definer RPCs.
  - `carts.member_id`, `carts.member_rev` (bumped on memory writes, so the iPad refetches), `carts.demo_date` (null = real today); `receipts.member_id`.
  - A `trip_id` change sets `member_id := null`: every trip starts as a guest.
- **RPCs** (anon-callable, demo-grade, no auth):
  - `set_member(p_cart_id, p_member_id)`
  - `set_demo_date(p_cart_id, p_date)`
  - `member_profile(p_member_id, p_cart_id?, p_today?) → {member, today, weekday, picks[≤3 with reason], usuals, memories, last_trip}`
  - `member_remember(...)`
  - `member_save_for_later(...)`
  - `member_forget(p_member_id, p_memory_id?)`: null forgets everything.
- **Seed (CLI):** `backend/members.py seed --member 1029 --name Dylan` rebuilds only that member: ten weeks of history relative to today, **no party** (in the demo Dylan tells Kart about Leo's party live, in Act 1). `--with-party` adds "Leo's soccer team party, pasta for 12" (next Saturday; Spaghetti ×3, Marinara ×2) for rehearsals that skip Act 1. Run it right before judging, through `backend/pre_judging.sh --members`.
  - Preference seeded on `rao-marinara` as "Likes the {short_name} here".
  - The seed looks everything up by product id.
- **Picks** never include a product with a live deal, so deals stay with the deal cards. Kinds are `event` | `due` | `usual`.
- `member_forget` returns `{"forgotten": n | "all"}`.
- **Edge-case additions (spec §3.9):**
  - RPC `member_lookup(p_member_id) → {exists, name}`, which never creates anything (used for the "Dylan N.? That's me / Not me" confirmation).
  - iPad→agent events `{"type":"member_forgotten"}`, `{"type":"member_forget_failed"}` (v0.20: Kart says "Sorry, I couldn't do that just now.") and `{"type":"member_idle"}`; agent→iPad `{"type":"show_memories"}` (tool `show_memories`).
  - Sensitive categories (pharmacy, health, medicine, personal-care, baby, pregnancy, adult) are never copied into member history.
  - Undated events expire 30 days after they were saved.
  - Conversational moments:
    - `member_memories.kind` gains `reminder` (dated): it surfaces from the day before until 3 days after, and its items become picks ("batteries · reminder").
    - New agent tool `sign_out`, which calls `set_member(cart, null)`, for "that's not me".
    - "Don't remember that" → forget the memory just saved.
    - "What did I buy last time?" → answered from `last_trip`.
- **Agent tool `shop_saved_list(memory_id)`:** puts a saved list on today's plan in one `set_plan`, keeping what's already there. Greeting example (Act 2): *"Welcome back, Dylan!" / "Leo's soccer team party is tomorrow. Want the list you saved?"* → "Yes." → *"Done, it's on your list. First stop: Aisle 6 → Spaghetti."* (fixed lines, no Claude round). Existing plan lines keep their own reason and meal; only the saved items get the event's name (an item-level `meal` in `set_plan` wins over the turn's meal). On an empty trip, the event becomes the trip's meal, so a nudge names the party ("Leo's soccer team party needs three").
- **Agent:**
  - `trip_context.member_id` (additive). When it's present, Kart fetches the profile before greeting ("Welcome back, Dylan!").
  - The tools `remember` / `save_for_later` / `forget` are offered only to signed-in members.
  - A new iPad→agent event `{"type":"lull"}` asks Kart's one question for the trip.
- **iPad:** reads `member_id`, `member_rev`, `demo_date` and `features.member_memory`. The member UI is shown only when the flag is on.
- **Privacy** (Visa trust): demo IDs only, guest by default, sign-in lasts one trip, a "What Kart remembers" sheet with a one-tap Forget per memory, and **Forget me** (touch-only, with a confirmation).

### "That's mine" / personal items: REMOVED
Out of scope (Dylan). The backend dropped `mark_personal` and `cart_events.resolution` from hosted and local (`d833002`). CV's watcher code exists but never runs unless `personal_items` is on (off by default); its hosted E2E test must be skipped. `edge_privacy` is off.

### Shopper-interaction RPCs (v0.17, backend `14932e6`, live on hosted)
- **`set_plan(p_cart_id, p_plan)`**: same signature. Items are `{product_id, reason?, qty?, basis?, meal?}`. Duplicate products merge into one line (qty summed, `meals` lists all). Plan rows carry `meal`.
- **`add_to_plan(p_cart_id, p_product_id, p_qty default 1, p_basis?, p_meal?)`**: atomic. A negative qty lowers the amount, and the line drops at 0. Raises `unknown product: X`.
- **`remove_from_plan(p_cart_id, p_product_id)`**: atomic; a no-op if the line is absent.
- **`set_budget(p_cart_id, p_amount)`**: null clears it; `reset_cart` clears it. New columns `carts.budget`, `carts.budget_left`, `carts.plan_estimate` (the rest of the list at today's sale prices).
- **`store_info.nearby`**: `[{name, address, distance_mi, kind, good_for}]` (4 real Berkeley stores).
- **Mini layout:** Aisle 2 = Dairy & Eggs, Aisle 8 = Bakery & Tortillas (by checkout). Pasta night's first stop is **Aisle 6 → Spaghetti**.

### Shared hosted project rules (v0.11)

- **Only the demo operator runs `db.py reset-demo` on hosted**, right before judging. It re-seeds the catalog, wipes the merchant change log, and resets cart 7 for everyone.
- Tests and rehearsals use **throwaway carts** (`cv-e2e-*`, `ios-it-*`, `agent-it-*`, `ipad-live`), never cart `7`. They reset only their own cart: `backend/.venv/bin/python backend/cart.py reset --cart <id>`.
- Never put the service-role key, DB URL or access token on the Pi or the iPad.
- **Automated tests and rehearsals on hosted never call `checkout`.** It lowers `products.stock` for everyone (marinara and Parmesan sold out on 2026-10-24). If stock drifts, restore it with `backend/db.py sync-catalog --with-stock`.

### 3a. As built (backend `1955f3c`, v0.7): additive fields, nothing renamed

28 pytest cases pass against a local Postgres. **Not deployed yet**: that waits on Dylan's Supabase project plus `SUPABASE_DB_URL` in `.env`, then `backend/.venv/bin/python backend/db.py apply`.
- **RLS:** anon can read every table, and every direct table write raises an error. All writes go through the RPCs.
- **Realtime:** on for `carts`, `cart_events`, `products`, `deals` and `sections`.
- `carts`: `item_count` (Σ qty), `suggested_deals text[]` (deals already offered this trip), `savings`.
- `items[]`: `short_name`, `list_price`, `deal_id`, `section`, `last_added_at`.
- `plan[]`: `qty` (the agent may send it; default 1), `name`, `section`, `aisle` (`"Aisle 4"`), `in_stock`, `deal_label`. `done` = cart qty ≥ plan qty. **The backend orders the plan by route**: done items first, then the rest in walking order from the current aisle. The agent can send any order.
- `next_step` = the first remaining in-stock item (`"Aisle 4 → Parmesan, $3 off"`), or `"All done → Checkout"` when the plan is complete.
- `suggestion`: also `name`, `deal_label`, `aisle`, `section`, `price`, `sale_price`; `text` = `"Parmesan is $3 off in Aisle 4. Want it?"`.
- `cart_events`: `trip_id` (filter to the current trip) and `applied` (false for a null or unknown `product_id`).
- **View `product_catalog`:** each active product with its best live deal (`sale_price`, `deal_label`, `aisle`, `in_stock`). The iPad and agent query it instead of joining. Views don't fire realtime, so subscribe to `products` / `deals` and refetch it.
- Built early: P5 `dismiss_suggestion`; P8 partially (`savings`, `list_price`); P10 (every write to products, deals or sections recomputes all open carts).
- Routing starts from `carts.location` (P3).

**All of P2–P8 and P10 are built (backend `4feb9ba`, v0.8):** 46 pytest and 5 deno tests pass. Not deployed yet.
- **P2:** `reset_cart` sets status `shopping` and `trip_started_at = now()`. `set_cart_status` accepts `idle` \| `shopping` \| `checkout`; `paid` is rejected because only `checkout()` sets it, so a paid cart always has a receipt. `db.py reset-demo` leaves the cart `idle` (the iPad shows Welcome).
- **P3:** every applied add sets `location`. `set_location` accepts `"A5"`, `"5"`, `"aisle 5"` or a section name, and raises on an unknown aisle. Reset clears it.
- **P4:** the old `apply_cart_event` overload is dropped (no PostgREST ambiguity), and CV's calls are unchanged. Every event gets an `event_id`; manual events get a generated one. **Confirm-card "Remove"** = `apply_cart_event(type 'removed', product_id null, source 'manual', p_resolves_event_id)`.
- **P6:** `append_transcript` returns the row tagged with the current `trip_id`; `reset_cart` deletes the cart's lines.
- **P8:** `checkout(p_cart_id, p_provider default 'simulated')` **returns the `receipts` row, not the carts row.**
  - Idempotent per trip (unique `cart_id` + `trip_id`); sets status `paid`; realtime is on for `receipts`.
  - Additive fields: `receipts.items` (the bill as paid) and `receipts.status` (`paid` \| `failed`).
  - It takes the units off `products.stock`, so the merchant sees the sale live; `reset-demo` restores stock.
  - It raises **`unresolved_items: N …`** (PostgREST 400) while an added unknown item is unresolved. That's the server-side half of the iPad's checkout block.
- **P7:** `backend/supabase/functions/voice-token`, in exactly the iPad's shape; deployed with `backend/deploy_functions.sh`.

**Merchant admin agent (backend `d5d3c2b`, v0.9):** 47 backend, 40 merchant and 5 Edge Function tests pass. It has not yet run against real Claude, which needs `ANTHROPIC_API_KEY`.
- `merchant/server.py` serves a console: chat, a live view of cart 7, the live catalog, and a change log.
- Claude (`claude-opus-5-5`) gets typed tools only: `search_products`, `list_deals`, `recent_changes`, `update_price`, `move_product`, `set_stock`, `add_product`, `create_deal`, `end_deal`, `undo_change`.
- Write tools only **stage** a change with a plain-English preview. Only the owner's **Confirm** click applies it (`merchant_apply`, service role only). Every change is logged before and after, with one-click undo. Undo won't clobber a newer edit, and a preview that went stale before Confirm is refused. *Claude can propose but never apply.*
- `merchant_changes` is service-role only: no anon read, no realtime.
- **`carts.suggestion.offered_at`** (additive). A deal the store creates **after** the current suggestion was offered replaces it. **iPad: a changed `suggestion.deal_id` = a new card** (and Kart says it).
- **Catalog for CV (decided):** CV fetches `id` / `name` / `vision_hint` from the Supabase **`product_catalog` view**, or from `products` filtered on `active = true`, since undoing an add delists the product rather than deleting it. Anon read, at startup and on every `trip_id` change, falling back to `data/store.json` when offline. So a product the owner adds live is identifiable on the next trip. `add_product` must always set a `vision_hint`; the agent writes one from the owner's description if they don't give one.
- **Demo option:** `db.py reset-demo --without-deal d-parm-3off` starts the pitch without the Parmesan deal. The owner creates it live in the console, and the shopper's cart pops it within a second.

**New trip / reset (v0.3; accepted by the backend in v0.4):** the iPad calls `reset_cart`. The Pi watches `carts.trip_id` (polling every ~2 s or over realtime) and clears its in-cart memory when the value changes. That way the iPad never has to reach the Pi over the network. The Pi's `POST :8080/reset` stays as a local fallback.

## 4. CV → backend

**Settled with Dylan.** Full spec: `pi/docs/specs/2026-10-24-cv-pipeline-design.md` (§8 events, §15 open questions).

- Snapshot-diff: once motion stops (~1 s), each cam is compared against its last still picture. One combined decision per settle gives one event per unit. No calibration markers.
- Identification is hybrid: the on-device few-shot matcher (enrolled prop photos) runs first, then `claude-haiku-5-5` with the catalog list (`id`, `name`, `vision_hint`) when unsure, else unknown. Removals are matched only against what CV remembers is in the cart.
- CV does **not** compute prices. It emits `product_id`, and the backend joins the price.
- Event, one per unit (also always appended to `pi/state/events.jsonl` on the Pi):
  ```json
  {"event_id": "uuid4", "cart_id": "7", "type": "added|removed", "product_id": "<store.json id>|null",
   "confidence": 0.93, "method": "local|cloud|memory|none", "label": "catalog name or raw model text",
   "cameras": [0, 1], "crops": ["state/crops/<event_id>_cam0.jpg"], "ts": "ISO8601 UTC"}
  ```
  It maps to `apply_cart_event` as `p_event_id`, `p_type`, `p_product_id`, `p_confidence`, `p_source="vision"`, `p_label`, `p_camera=cameras[0]`, `p_method` and `p_resolves_event_id`.
- **`resolves_event_id` (v0.10, additive):** `null` | `"<uuid>"`. When vision removes a unit it had billed as unknown (`product_id: null`), the removal event carries that add's `event_id`, and the sink passes it as `p_resolves_event_id`. That sets `resolved_at`, so an unknown that leaves the cart (usually a hand) no longer blocks checkout, and its iPad confirm card clears on its own. Every CV call sends `p_resolves_event_id`, which is null unless it's resolving something. This is verified end to end against local Supabase.
- **As built overnight (CV, 80 tests):**
  - The default on-device matcher is the colour histogram (`"features": "hist"`). ONNX is opt-in, after `tools/gallery_check.py` runs on the real enrolled props.
  - The Claude fallback times out after 6 s and sends at most 2 crops.
  - Arms reaching over the basket edge are ignored, and the cart re-judges once they leave. Crops stay on the Pi in v1. Stretch goal, only if the iPad wants "what the AI saw": the Pi uploads to Storage `snapshots/{cart_id}/{event_id}.jpg` and passes `p_snapshot_url`, which the backend already stores.
- **Backend's answers to CV §15 (v0.4)**, provisional until Dylan confirms Supabase: events go to the `apply_cart_event` RPC; `product_id` = the `store.json` id, which never changes; reset via `trip_id` as above; no crops in v1.
- Cart floor needs a solid mat or cardboard, because a wire-mesh bottom breaks the diff.
- Unrecognized / low confidence → send the event with `product_id: null` and the raw `label`; the phone asks the user to fix it.
- LCD (later milestone): poll or subscribe to `carts` for `lcd_line1` (line 1) and format line 2 from `total` + item count, e.g. `"$42.17   3 items"`.
- Trust & privacy: cameras point into the basket only; send crops of the changed region, never full frames with people; snapshots (optional, stretch) go to Supabase Storage bucket `snapshots/{cart_id}/{event_id}.jpg`.

## 5. iPad app ↔ backend (v0.6)

Spec: `ios/docs/specs/2026-10-24-ipad-app-design.md`. This replaces the phone web app.

- A native **SwiftUI** app on a cart-mounted iPad (landscape). There's no QR pairing; the iPad is configured with `CART_ID`.
- Voice: a **Cartesia Line** hosted agent (Python, in `agent/`) with Claude inside. Hands-free. Keys never ship on the iPad: it gets a short-lived Line token from a server function (P7).
- The iPad subscribes to the `carts` row and `cart_events` over Supabase realtime (anon key). It **never computes totals, deals or routes itself**; it shows what the backend computed.
- **Catalog rule (resolves a conflict with §2):** bundling `data/store.json` is fine for the **map layout** and as an offline fallback. But **product names, prices, deals and stock must come from Supabase `products` / `deals`** (realtime on the iPad, queried live by the agent's `search_catalog` / `get_deals` tools). Otherwise a merchant-agent change ("parmesan $3 off", a new product) never reaches the cart, and the voice agent quotes stale deals.
- Manual fixes ("that was the Barilla") call `apply_cart_event` with `source: "manual"` (plus `p_resolves_event_id`, P4).
- **The LCD is deferred:** the iPad is the cart's screen and ignores `lcd_line1`. The backend can keep computing it (it's cheap), and CV should treat the Grove LCD milestone as optional/last.

### 5a. iPad chat's changes (P1–P10): ACCEPTED in v0.6

All additive; nothing already built breaks. **Accepted at the contract level (v0.6)**, so the backend builds them after the core tables and RPCs that unblock the iPad's milestone 2. P9 stays a v2 nice-to-have. Dylan has approved the iPad spec (`ios/docs/specs/2026-10-24-ipad-app-design.md`, on `main`), so these are final.

| # | Change | Why |
|---|---|---|
| P1 | The iPad chat owns `ios/` and `agent/` | ownership |
| P2 | `carts.status` (`idle`\|`shopping`\|`checkout`\|`paid`) + `carts.trip_started_at`, both set by `reset_cart`; RPC `set_cart_status(p_cart_id, p_status)` | screen routing, voice-started checkout, trip time on the receipt |
| P3 | `carts.location` jsonb `{section, source: "item"\|"voice", at}`; `apply_cart_event` sets it to the added product's section; RPC `set_location(p_cart_id, p_section)` | "you are here"; feeds `next_step` routing |
| P4 | `cart_events.resolved_at`; `apply_cart_event(..., p_resolves_event_id uuid default null)`; a manual fix that names an unrecognized event marks it resolved | confirm cards clear; checkout blocks on unresolved items |
| P5 | RPC `dismiss_suggestion(p_cart_id, p_quiet boolean default true)`: clears the suggestion and doesn't re-offer that deal this trip. **v0.20: a shopper's "No thanks" (p_quiet true) sets `carts.deals_quiet`, so no unprompted deal card appears for the rest of the trip, including deals the store creates later** (Kart takes no for an answer; asking still works, and a list row shows its deal). Automatic dismissals the shopper never heard (an avoided item's card) pass `p_quiet: false`. `reset_cart` clears it | the "No thanks" button |
| P6 | Table `transcript` (`id`, `cart_id`, `trip_id`, `role` user\|agent, `text`, `created_at`; realtime ON) + RPC `append_transcript`; `reset_cart` deletes the old trip's rows | live captions; privacy story |
| P7 | Supabase Edge Function `voice-token`: uses `CARTESIA_API_KEY` to return a short-lived Line token. **The backend writes it** (it owns the Supabase project); the iPad chat specifies the request and response | keeps the key off the iPad |
| P8 | `carts.savings` + per-item `list_price`; RPC `checkout(p_cart_id, p_provider)` writes a `receipts` row (`cart_id`, `trip_id`, `total`, `savings`, `item_count`, `duration_s`, `provider`, `status`) and sets status `paid`. Payment is simulated in v1 | "saved $x", strikethrough prices, receipt |
| P9 | (nice to have, CV, v2) upload each event's crop to `snapshots/{cart_id}/{event_id}.jpg` and set `snapshot_url` | photos on confirm cards and at checkout (Visa trust story) |
| P10 | When the merchant changes a price or deal, the backend recomputes affected open carts (item prices, `deal_label`, `total`, `savings`, `suggestion`). Manager's suggested default: **new deals and price drops apply to items already in the cart; price increases apply only to items added after the change.** The shopper never sees the bill rise for something already in the cart. **Agreed with the iPad (extension):** a deal that ends (its `ends_at` passes) or is removed counts as a price increase, so items added while it was live keep it. One rule: *the price you saw is the price you pay.* Implementation hint: each cart line keeps the effective price at the moment it was added, and recompute sets `price = min(price at add, current effective price)` | the bill updates live, not just the catalog; shopper trust (Visa pitch line) |

**iPad read/write summary (v0.5):**
- **Reads (all realtime, anon):** the `carts` row; `cart_events` (null `product_id` → "Is this X?" cards); `products` (`id`, `name`, `short_name`, `price`, `section`, `category`, `tags`, `stock`); `deals` (`id`, `product_id`, `type`, `label`, `pairs_with`, `ends_at`); a bundled `store.json` for the map only.
- **Writes:** `reset_cart` (new trip), `apply_cart_event` (`source: "manual"`), `set_plan` (voice agent, plus "Yes" on a deal card), and P2/P3/P5/P6/P8 once accepted.
- The iPad follows the §5 catalog rule (live products/deals) as of its v0.4 update.

## 6. Secrets & env

One shared env file: **`<repo>/.env`** (gitignored, main checkout). Load it by that absolute path from your worktree; never copy secrets into tracked files. Each owner adds the variable *names* they need to a `.env.example` in their own directory.

| var | used by |
|---|---|
| `SUPABASE_URL`, `SUPABASE_ANON_KEY` | pi, web |
| `SUPABASE_SERVICE_ROLE_KEY` | backend scripts only |
| `SUPABASE_DB_URL` | backend scripts only (Postgres connection string for migrations and seeding; v0.4) |
| `ANTHROPIC_API_KEY` | pi (vision), web server routes (agent) |
| `CARTESIA_API_KEY` | web server routes |
| `CART_ID` (= `7`) | pi, iPad |
| `CARTESIA_AGENT_ID` | iPad / `agent/` / `voice-token` function (`"pending"` until the Line agent exists). The one name for it (v0.8 replaces `CARTESIA_LINE_AGENT_ID`) |
| `SUPABASE_PROJECT_REF`, `SUPABASE_ACCESS_TOKEN` | backend deploy only (Edge Functions and their secrets). The access token is a Supabase **personal access token**, which is account-wide, so revoke it after the hackathon |

`CARTESIA_API_KEY` reaches the `voice-token` function as a Supabase function secret. The backend sets it from `.env` through `deploy_functions.sh`, so nobody pastes it anywhere.

Note (v0.5): the Line agent runs on Cartesia's hosting, so `ANTHROPIC_API_KEY` and the Supabase values are also entered in the Line agent's own env settings. Dylan does that; no chat enters keys anywhere.

Keys are created by the user (no session creates accounts). Until they exist, work against stubs/fixtures and say what you need.

## 7. Session directory

Use the id in the **SendMessage `to`** column.

| Workstream | SendMessage `to` | Branch | Status |
|---|---|---|---|
| Manager | `local_…` | `main` (owns this file) | live |
| CV: "Smart cart computer vision algorithms" | `local_…` | main checkout | designing |
| iPad app: "Smart shopping cart iPad app" | `local_…` | main checkout | designing |
| Market backend + merchant agent: "KART market backend setup" | `local_…` | main checkout | started; `data/store.json` due first |

| Member sign-in + recommendations (design, beta): "Demo sign-in with personalized recommendations" | `local_…` | main checkout | designing with Dylan; it sends its proposal to the manager |
| Hardware: "KART hardware (James's PC)" | `bridge:session_…` (Remote Control, cross-machine) | GitHub `main` | Pi at `192.168.137.127` (`smartcart.local` can drop when the hotspot restarts) |

From James's PC, the Mac chats are reachable **by session name** over Remote Control. The manager is "Multi-feature project management".

All three feature chats work in the **same main checkout**, so stay inside your own directories and don't commit or stage another chat's files.

## 8. How we talk

- **Contract change** (a field, an RPC signature, a file shape): message the **manager** with the exact proposed change and why. The manager updates this file, bumps the version, and tells the other two. Don't build on a change until it shows up here.
- **Quick clarifying question to a peer** (no contract change): message that session directly (`SendMessage` to its id in §7).
- **Need something from the human** (API keys, a Supabase project, plugging in hardware, a product decision): tell the manager; the manager batches questions to the user. Don't ask the user for secrets in chat — they go in `.env`.
- **Milestones:** end each turn with a one-line status (`done / next / blocked on`). Commit to your own branch at every working milestone.

## Changelog
- v0 — initial contract from manager.
- v0.1 — marked as draft; directory now points at the two existing chats; iPad replaces the phone web app (pending); the iPad app chat owns the market backend (`backend/`, `data/`), as Dylan decided.
- v0.2 — market backend moves to its own chat, which adds a merchant admin agent (`merchant/`). The iPad chat no longer owns `backend/` or `data/`.
- v0.3 — §4 rewritten from CV's settled spec. `apply_cart_event` gains `p_event_id` (idempotent retries) and `p_method`. Proposed: reset via `carts.trip_id`.
- v0.4 — `data/store.json` v1 published (`e44879c`). Additive §2 fields: `version`, `short_name`, `stock`, `ends_at`, `percent_off`. Supabase becomes the source of truth for prices and deals (the iPad reads it live). Backend accepted the `trip_id` reset and answered CV's questions. Added `SUPABASE_DB_URL`.
- v0.5 — §5 rewritten for the native iPad app and the Cartesia Line agent. Catalog rule: names, prices, deals and stock come live from Supabase; the bundled `store.json` covers only the map and offline fallback. LCD deferred. iPad proposals P1–P9 recorded in §5a, pending Dylan's approval of the iPad spec. Added P10 (open carts get recomputed on merchant changes), the iPad read/write summary, and the `hardware/` lane plus GitHub sync rules for the teammate's machine.
- v0.6 — P1–P10 accepted (P9 stays v2). P10's rule, agreed with the iPad: the price you saw is the price you pay, which covers ended deals too. The manager now pushes and pulls `main` at each check-in.
- v0.7 — Dylan approved the iPad spec. §3a records the backend as built (`1955f3c`): additive fields, the `product_catalog` view, route-ordered plan, P5/P8-partial/P10 done. Hardware-lane handoff from CV (autostart command, install steps).
- v0.8 — All of P2–P8 and P10 are built (`4feb9ba`). `checkout` returns the receipt and blocks on unresolved items. Env var name unified to `CARTESIA_AGENT_ID`; added `SUPABASE_PROJECT_REF` and `SUPABASE_ACCESS_TOKEN`.
- v0.9 — Merchant agent built (`d5d3c2b`): it stages changes, the owner confirms, and every change has an audit log and undo. `suggestion.offered_at`: a newer store deal replaces the current suggestion. CV reads the catalog from Supabase at startup and on each trip change, with `store.json` as the fallback. Live-deal demo option added.
- v0.10 — CV events gain `resolves_event_id`: a vision removal of an unknown unit resolves it, so checkout isn't blocked by a stray hand. Overnight as-built notes for CV.
- v0.11 — Hosted is live (`go_live.sh` PASS). Shared hosted rules: only the demo operator runs `reset-demo`, and tests and rehearsals use throwaway carts. The merchant agent passed its real-Claude smoke test (`merchant/smoke.py`).
- v0.12 — Quantity nudges (beta, behind the `quantity_nudges` flag, off by default): `carts.nudge`, `plan[].basis`, `dismiss_nudge`, `set_feature`, `carts.features`; CV `claude_count` (off by default). The stable rollback point is tag `stable-pre-nudges`.
- v0.13 — short_name becomes a natural spoken name (≤ 16 chars). Quantity nudges pass the on-device voice test (beta, still off by default); a combined checkout nudge is in progress.
- v0.14 — Member memory (beta, flag `member_memory`, off by default) recorded from the member chat's proposal. It's built on branch `member-memory` and merged by the manager.
- v0.15 — "That's mine": `cart_events.resolution`, RPC `mark_personal`, an iPad button and voice phrase, and the CV watcher. CV flags `personal_items` (off) and `edge_privacy` (on).
- v0.16 — "That's mine" DROPPED (out of scope per Dylan). `edge_privacy` goes back to off by default.
- v0.17 — The backend fully removed the personal-items pieces. Shopper-interaction RPCs are live: `add_to_plan`, `remove_from_plan`, `set_budget`, `plan.meal`, duplicate merging. Nearby stores are on hosted. The mini store puts bakery last.
- v0.18 — Quantity nudges ON by default (over + checkout list). Demo props: one each, plus 3 spaghetti boxes; kids' scissors replace the chocolate. cam1 moves to USB port 1.3.
- v0.19 — Member memory MERGED to main (flag still off by default; tag `stable-pre-memory`). Seed has no party by default (Act 1 captures it live). The stability-rule wording is corrected: only `set_member`/`set_demo_date` check the flag. With both betas together, a saved list's quantities count as the plan, so 3 spaghetti for a party of 12 isn't "too much".
- v0.20 — Member follow-up merged: `member_forget_failed` event, failed lookups offer try again or shop as guest, saved lists keep today's labels, set_plan items carry their own `meal`. Deal policy: one "No thanks" quiets unprompted deal cards for the trip (backend).
