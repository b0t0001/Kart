# Local Supabase (overnight, 2026-10-24)

**For the CV and iPad chats.** A full local Supabase stack runs on Dylan's Mac (colima +
`supabase start` in `backend/`). It has the whole contract v0.9 schema, seeded from `data/store.json`
and tested end to end. The values are in `/Users/dylan/Documents/GitHub/kart/.env` under the contract
names: `SUPABASE_URL=http://127.0.0.1:54321`, `SUPABASE_ANON_KEY` (the legacy anon JWT),
`SUPABASE_SERVICE_ROLE_KEY`, `SUPABASE_DB_URL`, `CART_ID=7`. These are the standard local-dev keys. In
the morning Dylan replaces them with the hosted project and runs `backend/go_live.sh`; no client
code changes.

## Working examples

`backend/e2e/test_e2e.py` drives every client flow the way the Pi and the iPad will. It uses REST
with the anon key, plus a realtime subscription in `backend/e2e/realtime.py` (about 50 lines,
Phoenix protocol).

## CV (Pi)

- **Events:** `POST {SUPABASE_URL}/rest/v1/rpc/apply_cart_event` with headers `apikey: <anon>` and
  `Authorization: Bearer <anon>`. The body is your §8 mapping (`p_event_id`, `p_type`, `p_product_id`,
  `p_confidence`, `p_source: "vision"`, `p_label`, `p_camera`, `p_method`). A repeated `event_id` is
  a no-op. A null or unknown `product_id` is recorded with `applied=false`. `cv_event()` and
  `cv_to_rpc()` in the e2e test replay your exact JSON.
- **New trip:** poll `GET /rest/v1/carts?cart_id=eq.7&select=trip_id` (about every 2 s), or subscribe to
  realtime at `ws://127.0.0.1:54321/realtime/v1/websocket?apikey=<anon>&vsn=1.0.0`, with
  `postgres_changes` on `public.carts` and filter `cart_id=eq.7`.
- **Live catalog** (contract option b): `GET /rest/v1/product_catalog?select=id,name,short_name,vision_hint`.
  This view already excludes delisted products. If you read `/products` instead, add `active=is.true`.

## iPad

- **iOS Simulator:** it shares the Mac's network, so `http://127.0.0.1:54321` works, and realtime is
  `ws://127.0.0.1:54321/realtime/v1`. If App Transport Security blocks plain http, add
  `NSAppTransportSecurity › NSAllowsLocalNetworking = YES` (or an exception for 127.0.0.1) to the
  debug Info.plist.
- **Voice token:** `voice-token` is served locally at `{SUPABASE_URL}/functions/v1/voice-token`. It
  returns 400 for an unknown cart, and 502 `cartesia token failed` until a real `CARTESIA_API_KEY` is
  set. `verify_jwt` works with the anon JWT.

## Real devices (the Pi, a physical iPad)

The API is published on all of the Mac's interfaces, so devices reach it at
`http://<Mac LAN IP>:54321`. The IP was `10.1.203.39` overnight, and it changes with the Wi-Fi. The
macOS firewall may prompt once. A physical iPad needs an ATS exception for that IP, or the hosted
https project.

## Handy

| What | Where |
|---|---|
| Studio (browse tables) | http://127.0.0.1:54323 |
| Demo reset (catalog restored, cart 7 idle) | `backend/.venv/bin/python backend/db.py reset-demo` |
| Stop / start the stack | `supabase stop --workdir backend` / `colima start && supabase start --workdir backend` |
| Re-apply the schema after a restart | `backend/.venv/bin/python backend/db.py apply` |
