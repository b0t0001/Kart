# iPad app and voice agent: overnight build log

Built overnight 2026-10-24, on the manager's relay of Dylan's message: "can you just have remaining claudes build everything they need… then it's ready for review/testing when I come back."

## Morning checklist for Dylan (≈15 minutes)

1. **Look at it:** open `ios/build/shots/` (scenario screenshots) and `ios/build/shots/rehearsal/` (the automated §1.1 rehearsal, the live merchant beat, the failure paths).
2. **Run it in the simulator:** `cd ios && xcodegen generate && open Kart.xcodeproj`, then Run on "iPad Pro 13-inch (M5)". With `ios/Config.xcconfig` present (`ios/scripts/make-config.sh` writes it from the repo `.env`), the app talks to the local Supabase. Without it, it uses the built-in mock. Three-finger long press opens the demo controls.
3. **Create the voice pieces** (nothing secret was created overnight; see "What you need to create" below), then turn on Kart's real voice: demo controls (three-finger long press) → **Use Kart's real voice, Cartesia (relaunch)**, and quit and reopen the app. From Xcode, `-KartVoice line` does the same for one run.
4. **On a real iPad (iPadOS 26):** plug it in and trust the Mac, turn on Developer Mode (Settings → Privacy & Security), pick it as the run destination in Xcode, and Run. `scripts/make-config.sh` fills in your signing team from the keychain (override with `KART_TEAM_ID` in `.env`). If Xcode says `com.kart.app` isn't available, change the bundle id in `project.yml`. For the backend: on the same Wi-Fi as the Mac, use the local Supabase at `http://<Mac name>.local:54321` (the app allows local-network http). Anywhere else, use the hosted project (https) or the offline demo mode.
5. **Say yes or no to the rulings** below; each is a one-line change if you disagree.

## What you need to create

| What | Where | Then |
|---|---|---|
| Anthropic API key | console.anthropic.com | `cd agent && cartesia env set ANTHROPIC_API_KEY=…` |
| Cartesia account + API key | play.cartesia.ai | put `CARTESIA_API_KEY` in the repo `.env`; the backend's `deploy_functions.sh` pushes it to the voice-token function |
| The Line agent | `cd agent && cartesia auth login && cartesia init` (create new: "kart") then `cartesia deploy` | put the printed agent id in `.env` as `CARTESIA_AGENT_ID` and redeploy the function |
| Agent env on Cartesia | `cartesia env set SUPABASE_URL=… SUPABASE_ANON_KEY=… CART_ID=7` (hosted Supabase values) | `KART_MODEL` / `KART_EFFORT` are optional (defaults: `claude-opus-5-5`, `low`) |

Local test of the agent before deploying: `cd agent && .venv/bin/python main.py` (with the env vars set), then `cartesia chat 8000`.

## Decisions made without asking

- **How it was built:** Native, my recommendation at the plan handoff. The manager relayed the choice; Dylan didn't pick it directly.
- **Where:** on `main` in the shared checkout, committing only `ios/` and `agent/` (the contract's rule). No pushes from this chat.
- **Every other ruling** is in the plan ledgers and summarized in the final message of the session.

## Progress

- **Milestone 1 (the whole app on the mock):** done. Thirteen plan tasks, plus an automated rehearsal of the §1.1 demo, the live merchant beat, and the failure paths (`scripts/rehearse.sh`).
- **Milestone 2 (Supabase):** `KartSupabase` (REST, realtime, the backend), wired into the app (`-KartBackend supabase`, the default when `Config.xcconfig` has a URL), with live integration tests and a live rehearsal against the local stack (`scripts/rehearse-live.sh`).
- **Voice (milestone 3, keys pending):** `agent/` (the Line agent with Claude tools, tested with fakes and against the live backend) and `LineVoiceSession` (the iPad side, tested with fakes). It runs for real once the keys and the Line agent exist (checklist above).
- **Final review:** a fresh reviewer read the whole range (iOS and agent). Its one critical finding and seven important ones are fixed, each with a test that failed first:
  - A trip reset from outside the app (laptop, another iPad) now clears Paid and every card, and a reset during payment can't charge the new trip.
  - If confirm or remove fails on the backend, the card stays up instead of vanishing while checkout is still blocked.
  - The Line connection waits for its ack with a timeout, retries a dropped socket 3 times with backoff, then shows offline; a reconnect restores the trip context.
  - The agent never cuts Kart off mid-sentence for a proactive line, waits a beat after an add so the add and its deal come out as one line, doesn't re-greet when the call restarts mid-trip, and never stores an empty assistant turn.
  - An on-device switch to the offline demo (below).
  - The chimes no longer fight the voice for the audio session (build-verified only; check on the first on-device Line run).
  - Lower-priority findings are listed as deferred in the session's final message and in `.superpowers/sdd/2026-10-24-ipad-app-m1/progress.md`.

## Launch switches

| Switch | What it does |
|---|---|
| `-KartBackend mock` / `supabase` | Pick the backend for this launch. The default is Supabase when `Config.xcconfig` has a URL, else the mock. |
| Debug panel → **Use offline demo mode (relaunch)** | The on-device way to drop to the mock if the network dies at the demo; this choice sticks across launches. **Use the live backend (relaunch)** switches back. Quit and reopen the app after tapping. |
| `-KartCartID <id>` | Use another cart row (the live rehearsal uses `ipad-live`). |
| `-KartVoice line` / `mock` | Real voice through Cartesia Line, or the scripted mock (default), for this launch. |
| Debug panel → **Use Kart's real voice, Cartesia (relaunch)** | The same, and it sticks across launches (for an iPad started from the home screen). **Use the scripted voice (relaunch)** switches back. |
| Debug panel → **Hold to talk (for a loud store)** | A big press-and-hold button on the main screen. While it isn't held the iPad sends silence, so store chatter can't reach Kart; letting go ends your turn. Sticks across launches; hands-free is the default. `-KartHoldToTalk YES` does the same for one launch. |
| Debug panel → **Quantity nudges (beta)** | Turns the v0.12 beta on for this cart only (`set_feature`): a nudge card ("Keep it" / "Got it") when the cart has more or fewer than the list, and − / + on each list line for a camera miscount. Off by default; with it off nothing changes. `DemoScenario` `nudge` shows it offline. |
| `cartesia env set KART_BARGE_IN=off` (agent) | Nothing cuts Kart off mid-sentence. The greeting, deal lines and yes/no replies are already uninterruptible, so chatter can't wipe them. |
| `-KartScenario <name>` | Seed a screen for screenshots (always the mock). `talkative` is a long conversation with a deal card; `amounts` shows "2×" lines and "1 of 2". `DEVICE="iPad Pro 11-inch (M5)" scripts/shoot.sh …` shoots the smaller iPad. |
| `-KartStill YES`, `-KartDebugButton YES` | Freeze Kart's idle animation (UI tests); show a corner button for the debug panel. |

## Things worth knowing

- **The suggestion rule follows the backend's SQL (f6e41f3):** nothing is offered for a product already on the list, and a "Yes" (which puts the product on the list) consumes the card, so the next eligible deal pops right away. A deal on a listed product shows as "$3 off" on its list row instead. A store deal created mid-trip on a listed product also gets a one-tap "New deal: … · Got it" note, and Kart says it once. The offline mock follows the same rule. The voice agent plans the basics for a meal (pasta, sauce, bread), so the Parmesan deal card still shows in the demo.
- **Kart's voice format from Line isn't documented.** The iPad assumes 16 kHz mono PCM16, the same as it sends. If Kart sounds chipmunky or slowed on the iPad, change `EngineAudio.outputSampleRate` (24 000 or 44 100).
- **The mock backend's route and suggestion order are simpler than the backend's.** That only affects the offline demo mode.
- **Throwaway test carts:** `ios-it-*`, `agent-it-*`, and `ipad-live` rows exist from the integration runs and rehearsals.
- **Rehearsals reset only their own cart.** `scripts/rehearse-live.sh` resets `ipad-live` with `backend/cart.py reset` and `status idle`, before and after (even on failure), and never touches the store's catalog, deals or merchant log. Never run `backend/db.py reset-demo` on hosted: it re-seeds the catalog and wipes the merchant log for everyone. Only the demo operator runs it, right before judging.
