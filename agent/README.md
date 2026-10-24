# Kart: the voice agent

*For the Cartesia prize write-up (features used, setup, limitations, the Managed Agents path) see [README_CARTESIA.md](README_CARTESIA.md).*

Kart's voice runs on **Cartesia Line**: Cartesia handles speech-to-text, text-to-speech, turn-taking, and barge-in, and this folder is the agent's brain. The iPad streams mic audio to the hosted agent over one WebSocket and plays Kart's voice back (`ios/KartCore/Sources/KartCore/Voice/LineVoiceSession.swift`).

## What it does

- **Greets** when a call starts: "Hi, I'm Kart. What are we shopping for today?"
- **Answers the shopper** with Claude (`claude-opus-5-5` at `effort: low`, streamed so speech starts on the first words, with server-side refusal fallbacks). Claude works through store tools that read and write the live Supabase backend: `search_catalog`, `get_cart`, `set_plan`, `add_to_plan`, `get_deals`, `set_location`, `dismiss_suggestion`, `confirm_item`, `start_checkout`. Every product, price, deal and aisle Kart says comes from a tool result; the system prompt forbids inventing them.
- **Speaks up on its own** when the iPad tells it something changed (Line `custom` events): a deal suggestion, a store-created deal, a price drop, an item added or removed, a quantity nudge (beta), an item the cameras couldn't identify (`ui_action: unknown_item`), and payment (`ui_action: paid`). These lines are fixed templates (`kart_agent/lines.py`): fast, and they can't invent a price. Silent events (`trip_context`, `card_response`, `ui_action: checkout_tapped`) update state without cutting Kart off.
- **Captions** both sides into the backend's `transcript` table, which the iPad shows live.
- **Barge-in:** a new user turn cancels Claude's answers (Line's `UserTurnStarted`). The greeting, deal lines and yes/no replies are sent `interruptible=False`, so store chatter can't wipe them. For a loud floor, `cartesia env set KART_BARGE_IN=off` makes everything Kart says uninterruptible. Line has no turn-detection or VAD settings (its WebSocket takes only the audio format, voice and delivery pace), so these are the levers, plus hold-to-talk on the iPad.
- **Chatter:** a filler alone ("Um.") gets nothing. For speech that clearly isn't meant for Kart, Claude answers `<quiet>`: Kart says nothing, and neither side is captioned.
- **Deals by voice:** a plain "yes" or "no" to the open deal is handled without Claude.
- **Amounts:** plan lines count packages as sold ("three avocados" is one 5-count bag). Amounts never go above stock, and Kart says so ("Only 2 Parmesan in stock"). "Make it three" and "take the salsa off" edit the list.

## Layout

| Path | What |
|---|---|
| `main.py` | Line entry point: `get_agent` returns `(KartAgent, run_filter, cancel_filter)`. |
| `kart_agent/agent.py` | The Line agent (`process`), the run/cancel filters, captions. |
| `kart_agent/brain.py` | The Claude conversation and tool loop (system prompt here). |
| `kart_agent/llm.py` | The official `anthropic` SDK adapter (streaming, fallbacks; `KART_MODEL`, `KART_EFFORT`). |
| `kart_agent/tools.py` | Tool schemas and handlers. |
| `kart_agent/backend.py` | Supabase REST with the anon key; writes only through the contract's RPCs. |
| `kart_agent/lines.py` | What Kart says on its own. |
| `tests/` | Fakes for Claude and the backend (`fakes.py`), unit tests, the iPad event contract, and live tests against Supabase (`KART_IT=1`). |

## Run the tests

```bash
cd agent && python3 -m venv .venv && .venv/bin/pip install cartesia-line==0.2.19 anthropic==2.3.0 httpx pytest pytest-asyncio
```
```bash
cd agent && .venv/bin/python -m pytest -q
```

Live checks against the local Supabase (`backend/docs/LOCAL_SUPABASE.md`): export `SUPABASE_URL` and `SUPABASE_ANON_KEY` from the repo `.env`, then run `KART_IT=1 .venv/bin/python -m pytest -q`.

## Deploy (needs your keys)

`agent/scripts/deploy-line.sh` does steps 2–6 for you: run it yourself, since it signs in with your key and accepts Cartesia's terms. The steps, by hand:

1. Create a Cartesia API key at play.cartesia.ai/keys (pick your organization) and put it in the repo `.env` as `CARTESIA_API_KEY`.
2. Install the Cartesia CLI: `curl -fsSL https://cartesia.sh | sh`. Running it accepts Cartesia's terms.
3. `cd agent && cartesia auth login`, and paste the same API key when it asks.
4. `cartesia init`: create a new agent named `kart` in your organization.
5. Give the agent only what it needs. Don't use `cartesia env set --from ../.env`: that would upload the service-role key too.

   ```bash
   set -a && . ../.env && set +a && cartesia env set ANTHROPIC_API_KEY="$ANTHROPIC_API_KEY" SUPABASE_URL="$SUPABASE_URL" SUPABASE_ANON_KEY="$SUPABASE_ANON_KEY" CART_ID=7
   ```
6. `cartesia deploy`, then `cartesia status` prints the agent id. Put it in the repo `.env` as `CARTESIA_AGENT_ID`, and redeploy the backend's `voice-token` function (`backend/deploy_functions.sh`), so the iPad can get a token.
7. On the iPad: demo controls (three-finger long press) → **Use Kart's real voice, Cartesia (relaunch)**, then quit and reopen the app. From Xcode, `-KartVoice line` does the same for one run.

Try it locally first: run `.venv/bin/python main.py` with the same env vars plus `PORT=8000`, then `cartesia chat 8000`.

## Tuning voice latency

Cartesia's judges weigh latency. Measure the time from the end of speech to Kart's first audio with the default model and with `KART_MODEL=claude-haiku-5-5`, using the same scripted turns, before the demo. Which one ships is a team call.
