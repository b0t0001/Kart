# Overnight log: market backend (2026-10-24)

Dylan asked, via the manager, for every buildable piece to be finished and ready for review in the
morning, without questions. This page lists what got built, every judgment call, and what's left
for you.

## Morning checklist (about 15 minutes)

1. **Hosted Supabase.** Create the project, then put its values in `/Users/dylan/Documents/GitHub/kart/.env`.
   Replace the LOCAL block at the top: `SUPABASE_URL`, `SUPABASE_ANON_KEY`, `SUPABASE_SERVICE_ROLE_KEY`,
   `SUPABASE_DB_URL`. Add `SUPABASE_PROJECT_REF` and `SUPABASE_ACCESS_TOKEN`, which is a personal
   access token; revoke it after the hackathon.
2. Add `ANTHROPIC_API_KEY`, `CARTESIA_API_KEY`, and `CARTESIA_AGENT_ID` once the iPad chat has
   deployed its Line agent. Until then the deploy uses the placeholder "pending".
3. Run `backend/go_live.sh`. It applies the migrations, seeds the catalog, deploys voice-token and
   its secrets, runs the demo simulation over REST, runs the end-to-end test, and resets the demo.
   Look for **PASS**. It refuses to run while `.env` still holds the local URL.
4. **The first real-Claude test of the merchant agent.** Run
   `merchant/.venv/bin/python merchant/server.py`, open http://localhost:8090, and click the four
   example prompts. **This has never run against the real API**: the agent loop is tested only with a
   scripted fake. If tool choices look sloppy, set `MERCHANT_EFFORT=medium` in `.env` (the default is
   `low`, chosen for speed).
5. **Decide the demo opening** (see Decisions, item 7), then follow `backend/docs/DEMO.md`.

## Built tonight

| Piece | Where | Verified |
|---|---|---|
| Local Supabase stack (colima, then `supabase start`), migrated and seeded | `backend/supabase/`, `.env` | `simulate_demo.py` over REST with the anon key; voice-token served (502 until a Cartesia key exists) |
| Local values in `.env` (the standard local-dev keys, under a "LOCAL SUPABASE" header) | `.env` (gitignored, mode 600) | |
| Handoff for the CV and iPad chats | `backend/docs/LOCAL_SUPABASE.md` | see Decisions, item 2 |
| `go_live.sh`: one command for the morning | `backend/go_live.sh` | rehearsed with `--allow-local`: PASS (voice-token skipped: no token yet) |
| End-to-end test: CV's §8 JSON, the iPad flows, realtime, and the merchant beat | `backend/e2e/` | 4/4 pass against local Supabase |
| Anonymous store analytics: deal offers, takes and dismissals; baskets; time in store | `db/06_analytics.sql`, the `deal_offers` table, the console's "Store insights" panel, the agent's `store_insights` tool | unit and merchant tests; checked on screen |
| Demo levers for when a live piece fails | `backend/cart.py` | run against local Supabase |
| Demo runbook | `backend/docs/DEMO.md` | |

Test counts: backend unit 53, merchant 42, Edge Function 5, end-to-end 5. All pass.

## Decisions I made (please review)

1. **Which local keys go in `.env`.** `SUPABASE_ANON_KEY` is the legacy anon **JWT**, not the new
   `sb_publishable_` key. It works with voice-token's `verify_jwt` and with supabase-swift.
2. **The CV and iPad chats were not messaged.** After 10 messages in a row with no input from you,
   the app paused this session's cross-session messages. I didn't route around that pause. Instead
   I wrote everything they need into `backend/docs/LOCAL_SUPABASE.md` and pointed the commit message
   at it. **Please tell the CV and iPad chats (or the manager) to read that file.** It covers
   endpoints, realtime, the iOS Simulator, ATS, and the LAN IP for real devices.
3. **The stack keeps running overnight.** The colima VM uses 4 CPUs and 6 GB. To free it:
   `supabase stop --workdir backend && colima stop`.
4. **No made-up analytics.** The insights panel counts only real trips. The local stack has a few
   rehearsal trips; the hosted project starts at zero and fills as you rehearse. If you want a
   "this week" story for Visa, it would need clearly labeled simulated history, which I didn't
   build.
5. **What deal conversion means.** An offer counts as taken if its product goes into the cart later
   in the same trip, even after a "No thanks". Dismissals are counted separately.
6. **Function deploy uses `--use-api`,** which bundles server-side, so the morning deploy doesn't
   need Docker. `verify_jwt` stays on. If the hosted project only gives you an `sb_publishable_` key,
   redeploy with `backend/deploy_functions.sh --no-verify-jwt`.
7. **The demo opening is yours to decide.** The manager recommends `reset-demo --without-deal
   d-parm-3off`: the owner creates "Parmesan $3 off" live and the shopper's card switches to it. The
   default reset still keeps the seeded deal. `DEMO.md` is written for the live-deal version, and
   the flag is a one-word change.
8. **`cart.py deal` writes a merchant change directly**, with no Claude preview and no Confirm. It's
   the emergency path, labelled `request = "cart.py fallback"` in the log and undoable in the console.

## Follow-up from the iPad's overnight review (its rulings 24 and 30)

A "Yes" on a deal card puts the product on the shopping list (`set_plan`). Before this change, the
backend kept that card in its single suggestion slot until the item was physically in the cart. The
iPad hides cards for listed items, so after a Yes no other deal could pop.

- **Now:** a suggestion is consumed as soon as its product is on the plan, so the next eligible deal
  is offered right away. New suggestions are never offered for products already on the plan (or in
  the cart). The other rules are unchanged: each deal at most once per trip, and a deal the store
  creates later still replaces the current card.
- **Analytics are unchanged:** an offer still counts as "taken" only when the product goes into the cart.
- **Demo impact:** a deal on something already on the list shows on that list row ("$3 off"), not
  as a card. The simulator and `cart.py plan pasta` now plan the basics (spaghetti, sauce, bread), so
  the Parmesan card still pops after the spaghetti. **For the iPad chat:** if its agent plans
  Parmesan for "pasta dinner", the merchant beat shows on the list row instead of as a card.
- **Tests:** 3 new unit tests (53 backend in total), plus a "Yes" step in the end-to-end trip and a
  REST test that the next deal surfaces (5 end-to-end in total). All pass on local Supabase, which
  has the new SQL applied.

## Not done / known gaps

- Hosted deploy, real Claude, and real Cartesia are untested; they need your keys (checklist steps 1–4).
- P9 (camera crops uploaded for "what the AI saw") is still v2.
- A physical iPad on plain http needs an ATS exception. The hosted https project avoids that.
- A product the owner adds is visible to the cameras only once the CV chat ships its live-catalog
  fetch (contract option b). The merchant side is ready: every new product gets a vision_hint.
