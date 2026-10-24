# KART integration contract — v0.5 (DRAFT)

> **Draft status:** this was written before the manager knew about the two existing chats. Their design decisions win; the manager folds them in here. Known change pending: the cart's screen is an **iPad app mounted on the cart** (voice agent, navigation, auto-checkout), which replaces the phone web app (§5) and probably the LCD. §5 will be rewritten from the iPad chat's design.

**Owner: the manager session.** This file is the single source of truth for how the three workstreams fit together. It lives at
`/Users/dylan/Documents/GitHub/kart/docs/CONTRACT.md` (the main checkout). **Read it by that absolute path; never copy or edit it in your worktree.** To change it, see §8.

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
| `docs/CONTRACT.md`, root `.gitignore` | **Manager** | Propose changes, don't edit |

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
- `products[].short_name` (≤ 11 chars, e.g. `"Parmesan"`): use it for `lcd_line1`, `next_step` and spoken lines
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
  It maps to `apply_cart_event` as `p_event_id`, `p_type`, `p_product_id`, `p_confidence`, `p_source="vision"`, `p_label`, `p_camera=cameras[0]` and `p_method`. Crops stay on the Pi in v1. Stretch goal, only if the iPad wants "what the AI saw": the Pi uploads to Storage `snapshots/{cart_id}/{event_id}.jpg` and passes `p_snapshot_url`, which the backend already stores.
- **Backend's answers to CV §15 (v0.4)**, provisional until Dylan confirms Supabase: events go to the `apply_cart_event` RPC; `product_id` = the `store.json` id, which never changes; reset via `trip_id` as above; no crops in v1.
- Cart floor needs a solid mat or cardboard, because a wire-mesh bottom breaks the diff.
- Unrecognized / low confidence → send the event with `product_id: null` and the raw `label`; the phone asks the user to fix it.
- LCD (later milestone): poll or subscribe to `carts` for `lcd_line1` (line 1) and format line 2 from `total` + item count, e.g. `"$42.17   3 items"`.
- Trust & privacy: cameras point into the basket only; send crops of the changed region, never full frames with people; snapshots (optional, stretch) go to Supabase Storage bucket `snapshots/{cart_id}/{event_id}.jpg`.

## 5. iPad app ↔ backend (v0.5; pending Dylan's approval of the iPad spec)

Spec: `ios/docs/specs/2026-10-24-ipad-app-design.md`. This replaces the phone web app.

- A native **SwiftUI** app on a cart-mounted iPad (landscape). There's no QR pairing; the iPad is configured with `CART_ID`.
- Voice: a **Cartesia Line** hosted agent (Python, in `agent/`) with Claude inside. Hands-free. Keys never ship on the iPad: it gets a short-lived Line token from a server function (P7).
- The iPad subscribes to the `carts` row and `cart_events` over Supabase realtime (anon key). It **never computes totals, deals or routes itself**; it shows what the backend computed.
- **Catalog rule (resolves a conflict with §2):** bundling `data/store.json` is fine for the **map layout** and as an offline fallback. But **product names, prices, deals and stock must come from Supabase `products` / `deals`** (realtime on the iPad, queried live by the agent's `search_catalog` / `get_deals` tools). Otherwise a merchant-agent change ("parmesan $3 off", a new product) never reaches the cart, and the voice agent quotes stale deals.
- Manual fixes ("that was the Barilla") call `apply_cart_event` with `source: "manual"` (plus `p_resolves_event_id`, P4).
- **The LCD is deferred:** the iPad is the cart's screen and ignores `lcd_line1`. The backend can keep computing it (it's cheap), and CV should treat the Grove LCD milestone as optional/last.

### 5a. Proposed by the iPad chat (P1–P9): pending Dylan's approval of the iPad spec

All additive; nothing already built breaks. The backend can design its schema to fit them, but should only build them once the manager marks them accepted here.

| # | Change | Why |
|---|---|---|
| P1 | The iPad chat owns `ios/` and `agent/` | ownership |
| P2 | `carts.status` (`idle`\|`shopping`\|`checkout`\|`paid`) + `carts.trip_started_at`, both set by `reset_cart`; RPC `set_cart_status(p_cart_id, p_status)` | screen routing, voice-started checkout, trip time on the receipt |
| P3 | `carts.location` jsonb `{section, source: "item"\|"voice", at}`; `apply_cart_event` sets it to the added product's section; RPC `set_location(p_cart_id, p_section)` | "you are here"; feeds `next_step` routing |
| P4 | `cart_events.resolved_at`; `apply_cart_event(..., p_resolves_event_id uuid default null)`; a manual fix that names an unrecognized event marks it resolved | confirm cards clear; checkout blocks on unresolved items |
| P5 | RPC `dismiss_suggestion(p_cart_id)`: clears the suggestion and doesn't re-offer that deal this trip | the "No thanks" button |
| P6 | Table `transcript` (`id`, `cart_id`, `trip_id`, `role` user\|agent, `text`, `created_at`; realtime ON) + RPC `append_transcript`; `reset_cart` deletes the old trip's rows | live captions; privacy story |
| P7 | Supabase Edge Function `voice-token`: uses `CARTESIA_API_KEY` to return a short-lived Line token. **The backend writes it** (it owns the Supabase project); the iPad chat specifies the request and response | keeps the key off the iPad |
| P8 | `carts.savings` + per-item `list_price`; RPC `checkout(p_cart_id, p_provider)` writes a `receipts` row (`cart_id`, `trip_id`, `total`, `savings`, `item_count`, `duration_s`, `provider`, `status`) and sets status `paid`. Payment is simulated in v1 | "saved $x", strikethrough prices, receipt |
| P9 | (nice to have, CV, v2) upload each event's crop to `snapshots/{cart_id}/{event_id}.jpg` and set `snapshot_url` | photos on confirm cards and at checkout (Visa trust story) |

## 6. Secrets & env

One shared env file: **`/Users/dylan/Documents/GitHub/kart/.env`** (gitignored, main checkout). Load it by that absolute path from your worktree; never copy secrets into tracked files. Each owner adds the variable *names* they need to a `.env.example` in their own directory.

| var | used by |
|---|---|
| `SUPABASE_URL`, `SUPABASE_ANON_KEY` | pi, web |
| `SUPABASE_SERVICE_ROLE_KEY` | backend scripts only |
| `SUPABASE_DB_URL` | backend scripts only (Postgres connection string for migrations and seeding; v0.4) |
| `ANTHROPIC_API_KEY` | pi (vision), web server routes (agent) |
| `CARTESIA_API_KEY` | web server routes |
| `CART_ID` (= `7`) | pi, iPad |
| `CARTESIA_LINE_AGENT_ID` | iPad / `agent/` (v0.5) |

Note (v0.5): the Line agent runs on Cartesia's hosting, so `ANTHROPIC_API_KEY` and the Supabase values are also entered in the Line agent's own env settings. Dylan does that; no chat enters keys anywhere.

Keys are created by the user (no session creates accounts). Until they exist, work against stubs/fixtures and say what you need.

## 7. Session directory

Use the id in the **SendMessage `to`** column.

| Workstream | SendMessage `to` | Branch | Status |
|---|---|---|---|
| Manager | `local_9709c9d7-0b42-465c-83b4-9f3afef31131` | `main` (owns this file) | live |
| CV: "Smart cart computer vision algorithms" | `local_29c5fd35-ed9b-489b-afd7-0d9218b68080` | main checkout | designing |
| iPad app: "Smart shopping cart iPad app" | `local_2d2c60e6-9a47-4c86-843c-3422096c55ea` | main checkout | designing |
| Market backend + merchant agent: "KART market backend setup" | `local_b3d0cb4c-d827-42fe-8bdc-d43c97941c95` | main checkout | started; `data/store.json` due first |

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
- v0.5 — §5 rewritten for the native iPad app and the Cartesia Line agent. Catalog rule: names, prices, deals and stock come live from Supabase; the bundled `store.json` covers only the map and offline fallback. LCD deferred. iPad proposals P1–P9 recorded in §5a, pending Dylan's approval of the iPad spec.
