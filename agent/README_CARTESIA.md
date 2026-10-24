# Kart × Cartesia

KART is a smart shopping cart: cameras see what goes in, an iPad on the handle shows the list and the bill, and **Kart**, its voice, talks the shopper through the trip. You say *"Pasta night for my family of 4"* and Kart builds the list, sends you to the right aisle, offers the deal that goes with it at the shelf, says when you've grabbed one box too many, reminds you what you still need before you pay, and says goodbye when you've paid. Every bit of Kart's voice runs on Cartesia.

This page is for the Cartesia judges. [`README.md`](README.md) has the full developer guide.

## Cartesia features we use

| Feature | How Kart uses it |
|---|---|
| **Line agent** (hosted, `cartesia-line` SDK) | Kart's brain (`main.py`, `kart_agent/`) runs on Cartesia's hosting and is deployed with the Cartesia CLI (`cartesia deploy`, `cartesia env set`, `cartesia status`). The agent is one Python class: Line calls `process` for each event, and our `run_filter` / `cancel_filter` decide which events start a turn and which cut Kart off. |
| **Speech-to-text with turn detection** | The iPad streams its mic (16 kHz PCM16) over one WebSocket. Line's `UserTurnStarted` / `UserTurnEnded` events drive the conversation: each finished turn goes to Claude through the store's tools, or straight to a fixed reply for a plain "yes", "no", "keep it" or "skip". |
| **Sonic text-to-speech, streamed** | Claude's answer streams to Line sentence by sentence, so Kart starts talking on the first words. On the iPad, about 1.5–2 s pass from the end of the shopper's speech to Kart's first audio. Kart's own lines (deals, "Got the spaghetti.", nudges, "Paid. Enjoy pasta night!") are fixed templates, so they're fast and can't invent a price. |
| **Custom events, both ways** | The iPad sends what happened on screen or in the cart (`trip_context`, `cart_changed`, `suggestion`, `nudge`, `card_response`, `ui_action`) as Line `custom` messages, and Kart speaks up on its own. Kart sends `custom` messages back (`deal_digest`, `digest_deal`, `digest_done`) so the iPad shows a matching card for whatever Kart is asking. Voice and touch always stay in step: answer by voice or tap. |
| **Uninterruptible lines** | The greeting, deal offers, nudges and confirmations go out with `interruptible=False`, so store noise can't cut them off halfway. Only Claude's longer answers can be interrupted. |
| **Barge-in** | A new shopper turn (`UserTurnStarted`) cancels Claude's answer, so you can cut Kart off naturally. On a loud floor, `KART_BARGE_IN=off` makes everything Kart says uninterruptible. |
| **Short-lived access tokens** | The iPad never holds a Cartesia API key. Our Supabase edge function `voice-token` (`backend/supabase/functions/voice-token/`) checks the cart id and returns a one-hour Cartesia access token scoped to the agent (`grants: {agent: true}`), plus the WebSocket URL. |
| **Hold-to-talk** (on our side) | For a loud store, a debug switch turns the mic into a press-and-hold button. While it isn't held, the iPad sends silence of the same length, so the stream stays alive but chatter never leaves the device. |

## Setup

You need: a Cartesia account and API key, an Anthropic API key, and the Supabase project (URL and anon key) from the repo's `.env`. Secrets live only in that `.env` (git-ignored) and in the agent's Cartesia environment. None are committed.

1. **Deploy the agent.** Run `agent/scripts/deploy-line.sh` yourself. It installs the Cartesia CLI, signs in, creates the agent, sets exactly four values on it (`ANTHROPIC_API_KEY`, `SUPABASE_URL`, `SUPABASE_ANON_KEY`, `CART_ID`, never the service-role key), deploys, and saves the agent id to `.env` as `CARTESIA_AGENT_ID`. To redeploy after a change: `cd agent && cartesia deploy --agent-id=$CARTESIA_AGENT_ID`.
2. **Token function.** Deploy the backend's `voice-token` edge function (`backend/deploy_functions.sh`) with `CARTESIA_API_KEY` and `CARTESIA_AGENT_ID` set as function secrets.
3. **iPad.** Copy `ios/Config.example.xcconfig` to `ios/Config.xcconfig` (Supabase URL and anon key), build the `Kart` scheme in Xcode, and launch with `-KartVoice line` (or open the demo controls with a three-finger long press and pick **Use Kart's real voice**).
4. **Tests.** `cd agent && .venv/bin/python -m pytest -q` runs the agent's unit tests, with fakes for Claude and the backend. `agent/scripts/voice_smoke.py <test cart> "<a line>"` makes one real call to the deployed agent the way the iPad does and prints the time to Kart's first audio.

## Responsibility: accessibility and privacy

- **Hands-free.** The shopper is pushing a cart, often with a child or a full basket. Everything Kart asks by voice can be answered by voice, and every card on screen can also be tapped.
- **Captions.** Both sides of the conversation show live on the iPad as chat bubbles, which helps shoppers who are hard of hearing and anyone on a loud floor.
- **No audio stored.** Audio streams live to Cartesia for the call and is not saved by us. Our backend stores only the text captions, per trip.
- **Hold-to-talk** sends silence while the button isn't held, so the people around the cart aren't streamed.
- **No keys on the device.** The iPad gets a one-hour, agent-only token. The agent gets only the anon key, and it writes only through the backend's public functions.
- **No invented facts.** Every product, price, deal, aisle and stock number Kart says comes from a tool result or a fixed template filled from the live store. The system prompt forbids anything else.
- **Kart stays quiet when it should.** Fillers ("Um.") and chatter that isn't meant for it get no reply and no caption.

## Known limitations

- **Noisy floors.** Line exposes no VAD or turn-detection settings: the WebSocket `start` config takes only the audio format, voice and delivery pace. In a loud store, Kart can hear other people. Our mitigations:
  - hold-to-talk;
  - uninterruptible lines (and `KART_BARGE_IN=off`);
  - filler and "okay"-only turns are ignored;
  - Claude answers `<quiet>` to speech that clearly isn't meant for Kart.

  Even so, a cart in a busy aisle will sometimes reply to someone else.
- **English only.** The demo, the prompts and the fixed lines are English.
- **Latency.** Most of the 1.5–2 s is Claude thinking with tool calls. Kart says a few words that state no facts ("Pasta night, love it. One sec.") before the tools run, so the shopper hears something right away.
- **Needs a connection.** Kart's voice lives in the cloud. If the call drops, the iPad shows "Voice is offline. Tap to retry." and the screen keeps working by touch. There's no on-device voice.
- **Line SDK end of life.** Cartesia stops hosting Line SDK agents on **December 1, 2026** and recommends Managed Agents for new work. Kart is built on the Line SDK, which is fine for the hackathon. The migration path is below.

## Migrating to Managed Agents

Cartesia's [Managed Agents](https://docs.cartesia.ai/agents/introduction.md) run listening, turn-taking, interruptions and tool calls around a configured LLM, and clients connect over the [Agents WebSocket API](https://docs.cartesia.ai/line/integrations/websocket-api.md). Kart maps onto that model as follows:

1. **Agent config.** Move the system prompt (`kart_agent/brain.py`) and the voice into a Managed Agent, keeping the same `agent_id` flow: `voice-token` already mints agent-scoped tokens.
2. **Tools.** Kart's store tools (`search_catalog`, `get_cart`, `set_plan`, `add_to_plan`, `remove_from_plan`, `get_deals`, `set_location`, `confirm_item`, `dismiss_suggestion`, `dismiss_nudge`, `start_checkout`) become either:
   - **webhook tools**: a small HTTPS endpoint, for example a Supabase edge function wrapping the same RPCs `kart_agent/tools.py` calls today;
   - or **client tools** that the iPad runs. The iPad already calls those RPCs.
3. **The client.** The iPad already speaks the Agents WebSocket protocol (`start`, `media_input`, `custom`, `media_output`) in `ios/KartCore/Sources/KartCore/Voice/LineVoiceSession.swift`, so the app changes little.
4. **The open question: proactive lines.** Kart talks on its own when the cart changes (a deal at the shelf, a nudge, "Paid. Enjoy pasta night!"), from fixed templates in `kart_agent/lines.py`. Under the Line SDK, our code decides what to say for each iPad event. Before migrating, we need to confirm how a Managed Agent can be made to speak a fixed line in response to an app event. We'll check the Managed Agents docs or ask Cartesia.

We are not migrating before the hackathon.
