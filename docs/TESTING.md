# KART: merge status and test plan

Owned by the manager. The interfaces are in [CONTRACT.md](CONTRACT.md); the live status is in [STATUS.md](STATUS.md).

## Merge status: nothing to merge

Every chat committed straight to `main` in the shared checkout, and the teammate's `hardware/` work came in through GitHub and was merged. **`main` on GitHub (`b0t0001/kart`) is the whole product.** No feature branches are left; the three stale `claude/*` branches pointed at the initial commit and have been deleted.

| To get the latest | Run |
|---|---|
| Dylan's Mac | already current; the manager syncs at each check-in |
| Teammate's laptop | `git pull` |
| The Pi | `bash hardware/sync_pi.sh` from the teammate's laptop, or `git pull` in `~/kart` |

The secrets file (`.env`) is never in git. Each machine has its own, and the Pi's lives at `~/kart/.env`.

## The test ladder

Work top to bottom. Each rung only needs the one above it to pass.

| # | Rung | Needs | Who | Time |
|---|---|---|---|---|
| 1 | Automated suites | nothing (this Mac) | anyone / manager | ~5 min |
| 2 | Whole system on one Mac (local Supabase) | nothing | Dylan | ~15 min |
| 3 | Go live (hosted Supabase) | Supabase project + keys | Dylan | ~15 min |
| 4 | Cameras on the real Pi | rung 3 + `ANTHROPIC_API_KEY` | teammate | ~45 min incl. enrollment |
| 5 | iPad on the device + voice | rung 3 + Cartesia + Apple ID signing | Dylan | ~30 min |
| 6 | Full demo rehearsal, ×3 | rungs 3–5 | whole team | ~20 min |

### Rung 1: automated suites

Run from the repo root. The manager ran all of them on `main` on 2026-10-24 at about 08:00: **316 tests, all green.**

| Suite | Command | Expected | Manager run |
|---|---|---|---|
| CV unit (synthetic two-camera scenes) | `pi/.venv/bin/python -m pytest pi/tests -q` | 80 pass | ✅ 80 passed (2 opt-in skipped), 24 s |
| CV ↔ Supabase end-to-end | `KART_E2E=1 pi/.venv/bin/python -m pytest pi/tests/test_e2e_supabase.py -q` | 2 pass | ✅ 2 passed |
| Backend unit (throwaway Postgres on :54329, see `backend/README.md`) | `backend/.venv/bin/python -m pytest backend/tests -q` | 53 pass | ✅ 53 passed |
| Backend end-to-end (CV events + iPad trip + merchant beat over realtime) | `backend/.venv/bin/python -m pytest backend/e2e -q` | 5 pass | ✅ 5 passed |
| Merchant agent (fake Claude) | `merchant/.venv/bin/python -m pytest merchant/tests -q` | 42 pass | ✅ 42 passed |
| voice-token Edge Function | `deno test -A backend/supabase/functions/voice-token/` | 5 pass | ✅ 5 passed |
| Line voice agent (fakes) | `cd agent && .venv/bin/python -m pytest -q` | 29 pass, 2 skipped | ✅ 29 passed, 2 skipped |
| iPad logic (KartCore) | `cd ios/KartCore && swift test` | 100 pass | ✅ 100 passed |
| iPad UI walkthroughs (Simulator) | `ios/scripts/rehearse.sh` (mock), `ios/scripts/rehearse-live.sh` (local Supabase) | pass + screenshots in `ios/build/shots/` | not rerun (slow); the iPad chat ran both overnight |

### Rung 2: the whole system on one Mac (no keys)

The local Supabase stack is already running (`colima` + `supabase start --workdir backend`), and `.env` holds its local values.
1. **The iPad in the Simulator:** `ios/scripts/make-config.sh`, then `cd ios && xcodegen generate && open Kart.xcodeproj`, then Run on "iPad Pro 13-inch (M5)". A three-finger long press opens the demo controls.
2. **Drive the cart from the laptop** (stand-in for the cameras), with `P=backend/.venv/bin/python`:
   - `$P backend/cart.py reset`, then `$P backend/cart.py plan pasta` → the list and next stop appear.
   - `$P backend/cart.py add barilla-spaghetti` → the total updates, and the Parmesan card pops if the deal exists.
   - `$P backend/cart.py deal kirkland-parmesan 3` → **the live merchant beat**: the card switches with confetti.
   - `$P backend/cart.py remove barilla-spaghetti` → the total drops. Then check out on the iPad and see the receipt.
3. **Merchant console:** `merchant/.venv/bin/python merchant/server.py` → http://localhost:8090. You can watch the live cart, catalog and change log now. The chat itself needs `ANTHROPIC_API_KEY`; until then, `cart.py deal` stands in.
4. **Pass when** every step above shows up on the iPad within about a second, with no manual refresh.

### Rung 3: go live (hosted Supabase)

Follow the checklist at the top of [STATUS.md](STATUS.md):
1. Create the project.
2. Put the six `SUPABASE_*` values and `ANTHROPIC_API_KEY` in `.env`, replacing the `LOCAL SUPABASE` block.
3. Run `backend/go_live.sh` → **PASS**.
4. Open the merchant console and click its four example prompts. **This is the first time the merchant agent meets real Claude.** If its tool choices look sloppy, set `MERCHANT_EFFORT=medium`.
5. Rerun `ios/scripts/make-config.sh` so the iPad points at the hosted project.

### Rung 4: cameras on the real Pi (teammate)

`pi/README.md` → "Milestone checks", rows 1–8, then enroll each demo prop (`tools/enroll.py <product-id>`) and run `tools/gallery_check.py`. Before you start:
- Line the cart floor with a solid mat or cardboard.
- Put `.env` at `~/kart/.env` with the **hosted** Supabase values plus `ANTHROPIC_API_KEY`.

Row 6 is the cross-team check: items dropped in the real cart must show up on the iPad. Commit `pi/gallery/` and push it.

### Rung 5: the iPad on the device, plus voice

`ios/docs/OVERNIGHT.md` has the full list:
1. Sign the `Kart` target with your Apple ID.
2. Turn **Stage Manager off**.
3. Create the Cartesia account and key, then `cartesia init` / `deploy` the Line agent in `agent/`.
4. Put `CARTESIA_API_KEY` and `CARTESIA_AGENT_ID` in `.env` and rerun `backend/deploy_functions.sh`.
5. Launch with `-KartVoice line`.

Things to check:
- Kart's voice pitch. If it sounds chipmunky or slow, change `EngineAudio.outputSampleRate`.
- Chimes vs the mic.
- Response latency: try `KART_MODEL=claude-haiku-5-5` against the default Opus at low effort.

### Rung 6: the demo rehearsal

Follow [backend/docs/DEMO.md](../backend/docs/DEMO.md):
1. Reset with `reset-demo --without-deal d-parm-3off`.
2. The judge says "pasta dinner for my family".
3. Drop the spaghetti into the cart.
4. The "store owner" types "parmesan $3 off" in the console → the cart's card pops.
5. Take an item back out → the total drops.
6. Check out → receipt.

Run it three times, then **drill the failures**:
- the cameras miss an item → fix it on the confirm card or with `cart.py add`;
- the merchant chat is slow → `cart.py deal`;
- the network dies → the iPad's "Use offline demo mode".

## Known never-verified items (highest risk first)

1. **Nothing has run on the real Pi cameras yet** (rung 4). The synthetic tests are thorough, but real lighting, the props and the cart floor are untested.
2. **The merchant agent has never called real Claude** (rung 3, step 4).
3. **Voice has only run against fakes** (rung 5). Cartesia Line's connection details and its audio output format are unconfirmed.
4. The chimes vs voice audio-session fix is build-checked only.
5. The local DB holds throwaway test carts (`cv-e2e-*`, `ios-it-*`, `agent-it-*`, `ipad-live`). They're harmless, and they never reach the hosted project.

## Bugs found while testing

Tell the manager chat what broke and on which rung. It routes the bug to the chat that owns the code (CV `pi/`, iPad `ios/`+`agent/`, backend `backend/`+`merchant/`+`data/`, teammate `hardware/`), so you never have to relay.
