# Kart iPad App: Design Spec

> Cal Hacks 13.0 · 2026-10-24 · Status: **draft for review** · Owner: the iPad app chat ("Smart shopping cart iPad app")
> This is the cart-mounted iPad app and its voice agent. It plugs into the shared integration contract at `<repo>/docs/CONTRACT.md` (v0.5): the market backend chat owns Supabase and `data/store.json`, and the CV chat owns `pi/`. Anything this app needs beyond the contract's accepted shapes is listed as a **contract proposal** in §9 (mirrored in contract §5a as "pending Dylan's approval") and is not built until it's accepted.

---

## 1. Purpose and success criteria

**What we're building.** Every cart has an iPad mounted on the handle, running our app. It is the shopper's one way to talk to the cart: a voice-first AI companion ("Kart") that greets them, turns "pasta dinner for four" into a list, walks them aisle to aisle, points out deals at the moment of decision, keeps a live bill built from what the basket cameras see, and checks them out with no register.

**Who it's for.** Families on long warehouse-club trips (us: 3–4 hour Costco runs), and older shoppers who prefer stores but find big-box navigation tiring. Voice plus a big, simple screen serves both.

**Success means:**
1. The 2-minute demo (§1.1) runs end to end on the real iPad, reliably, in a loud hall.
2. A first-time user understands every screen within ~3 seconds without being told what to do.
3. It looks and feels beautiful: smooth motion, a warm character, nothing cluttered.
4. The app is demoable from milestone 1 (mock data) and never waits on the Pi or the backend being ready.

### 1.1 Demo script (what everything serves)
Products and deals are from the published `data/store.json` v1.
1. The judge walks up. Kart is smiling on screen: "Tap to start." Tap: Kart waves. *"Hi, I'm Kart. What are we shopping for today?"*
2. Judge: *"Pasta dinner for my family, four people."* The list builds itself on screen (spaghetti, marinara, baguette, Caesar kit); the Next stop card shows the first aisle on the walking route (the backend orders the list by route).
3. The judge drops a real box of Barilla spaghetti in the cart. A soft chime; it slides into the cart, the list item checks off, the total counts up. Kart: *"Nice. Rao's is right beside it, and parmesan's $3 off in aisle 4."*
4. A deal card appears. The judge says "yes," and parmesan joins the list.
   - *(Merchant beat.)* The pitch starts without the parmesan deal, so the spaghetti first offers the baguette deal. A teammate playing the store owner creates "parmesan $3 off" in the merchant console. Within a second the deal card swaps to Parmesan with a pop, Kart bounces and says it once, and every price on screen updates live.
5. The judge drops an item the cameras aren't sure about: an amber card asks "Is this the Rao's marinara?" "Yes."
6. The judge takes an item back out. Kart notices; the total drops.
7. *"I'm done."* Checkout lists every item (with the camera's photo when available) and the savings. Tap the card to pay, then the receipt: "You saved $3.00 · 4-minute trip." Closing line: *"Our 4-hour Costco trip, cut to 45 minutes."*

### 1.2 Sponsor tracks
| Tier | Tracks | What it means for the build |
|---|---|---|
| Design-driving | **Anthropic** (Claude is the brain), **Cartesia** (voice is the core interaction, via Cartesia Line), **Visa** (auto-billing, checkout, trust) | Shapes architecture and UX |
| Free with the build | Best Hardware Hack, Best People-First Hack (framing) | Nothing extra to build |
| Pitch only | Microsoft "Built for the Real World" | Path-to-production story; no Azure unless the live site requires it |
| Skipped | Convex (the contract standardizes on Supabase), Fetch.ai, Factory, Moss, Spacetime | Not worth the dependency |

---

## 2. Scope

**This chat owns:** `ios/` (the Xcode project, this spec, app tooling) and `agent/` (the Cartesia Line voice agent). Ownership of `agent/` is contract proposal P1.

**In scope:**
- The iPad app: every screen, the avatar, voice, the debug panel, simulated payment.
- The Line voice agent (Python) with Claude and its tools, calling the backend's RPCs.
- A mock backend inside the app, so the UI is built and demoed before Supabase exists.

**Out of scope (owned elsewhere or later):**
- The Supabase schema, RPCs, seeding, and deal/route logic → market backend chat.
- The vision pipeline and the LCD → CV chat. The iPad replaces the phone web app; whether the LCD is still wanted is the CV chat's and manager's call.
- Real payment. A `PaymentProvider` seam lets a Visa-supported plugin drop in if one exists at kickoff.
- Sensor-based location (GPS, IMU). Location is inferred (§3.6).
- Lists from photos or a phone, multiple languages, user accounts.

---

## 3. Experience design

### 3.1 Principles: simple, intuitive, beautiful
Every screen is checked against these before it ships.

1. **Glanceable at arm's length.** The shopper is ~0.7–1 m away, pushing a cart. The total and next stop read at a glance: body text ≥ 20 pt, key numbers ≥ 40 pt, nothing smaller than 17 pt.
2. **One obvious action per moment.** Each screen has at most one primary button. If two things compete, one goes.
3. **Voice and touch are equals.** Everything you can say, you can tap, and the reverse. Captions are always on.
4. **Calm, physical motion.** Every state change animates with springs: items slide into the cart, the total counts up, cards rise in and settle. Nothing pops or jumps. Motion explains what changed.
5. **Never silently wrong.** When the cart is unsure, it asks (amber, with the photo when there is one). The bill is something you can trust.
6. **Warm, not childish.** Kart has personality in its face and voice, but the UI around it stays clean and adult.
7. **Quiet by default.** No badges, spinners, or chrome that doesn't earn its place. Empty space is part of the design.

### 3.2 Visual language
- **Orientation:** landscape only (confirm the mount with the CAD teammate).
- **Type:** SF Pro Rounded for UI and numbers (friendly, highly legible); captions of Kart's speech in a slightly larger, softer style so "who's talking" reads instantly.
- **Color:** a warm off-white canvas and one brand color (teal) carried by Kart and its accents. Amber means "needs your OK," green means "done/saved." Light mode only: stores are brightly lit.
- **Product tiles:** the catalog has no product images, so every product shows a rounded tile with its category's icon and color (cheese, pasta, produce, …). The camera's photo replaces the tile wherever a snapshot exists.
- **Names and prices:** `short_name` ("Parmesan") everywhere space is tight and in everything Kart says; the full `name` only on the checkout bill. Deals display their `label` ("$3 off") as given; the app never does price math.
- **Touch targets:** ≥ 64 pt (a moving cart and a distracted shopper make for imprecise taps).
- **Sound:** a soft chime when an item is added, a lower tone when one is removed, a gentle two-note sound when a card appears. All subtle, all short.

### 3.3 Kart, the avatar
A rounded, friendly face (eyes and mouth) with four moods, driven by the voice session state and the live loudness of its speech:

| Mood | When | Look |
|---|---|---|
| Idle | Welcome screen, or quiet during shopping | Slow breathing scale, natural blinks |
| Listening | The mic hears the shopper | Eyes widen slightly; the "Listening" pill glows |
| Thinking | Between the end of the shopper's speech and Kart's first audio | Eyes glance up and aside |
| Speaking | Kart's audio is playing | Mouth opens with the loudness of the audio; eyes soften |

Plus one-shot reactions: **wave** (greeting), **happy bounce** (an item from the list is added, a deal accepted), **curious tilt** (an unsure item), **celebrate** (payment complete).

**Implementation:** drawn in SwiftUI (shapes, `Canvas`, `TimelineView`, spring animations), so it reacts with no lag and needs no art files. It sits behind one interface, `AvatarView(mood:level:reaction:)`, so a **Rive** character (`RiveRuntime`; its moods and loudness map onto Rive state-machine inputs) can replace it later if we find or design one we like better. **Lottie** (`lottie-ios`, free LottieFiles animations, license checked per file) is allowed for one-off celebration moments such as receipt confetti. Every third-party package is pinned to an exact version.

### 3.4 Screens and flow

```
Welcome ──tap──▶ Greeting ──first exchange──▶ Shopping ──"I'm done" / tap──▶ Checkout ──pay──▶ Receipt ──30 s / Done──▶ Welcome
```

1. **Welcome (cart parked).** Big Kart, breathing and blinking. One line, "Tap to start shopping." The mic is **off** here (privacy) and the screen says so in small type.
2. **Greeting.** The tap starts a new trip (`reset_cart`). Kart waves and speaks its introduction; captions show it. Within one exchange the layout glides into Shopping (the avatar shrinks into the left panel rather than cutting to a new screen).
3. **Shopping (main).** A two-panel landscape layout:
   - **Left, Kart:** the avatar, the Listening/Muted pill (tap to mute), the last 2–3 caption lines, and **one card at a time** (§3.5).
   - **Right, the trip:** a Next stop card (mini aisle map drawn from `store.json` sections, the route, "you're in Aisle 1 · Produce"); below it, **Your list** (from `carts.plan`; items check off as `done` flips) beside **In your cart** (from `carts.items`; unconfirmed detections amber with "?"); a sticky footer with the large estimated total, "saved $x.xx," and the one primary button, **Check out**.
4. **Checkout.** An itemized bill (photo or product tile per line), savings, and total. Unconfirmed detections must be resolved with one tap each before paying (they're grouped at the top). One primary action: **Pay**. A card-tap sheet with a tap animation (simulated); success triggers Kart's celebrate reaction.
5. **Receipt.** "You saved $8.40 · 23-minute trip" (trip time and savings feed the pitch), the item count, and **Done**. Auto-returns to Welcome after 30 s.

### 3.5 Cards
Cards are how the cart shows things that need attention or a decision. One is visible at a time; others queue. All are derived from backend state, so they survive an app restart.

| Kind | Source | Example | Actions |
|---|---|---|---|
| `deal` | `carts.suggestion` (a deal the store creates after the current one was offered replaces it; a changed `deal_id` always enters as a new card with a pop, and Kart says it) | "Parmesan is $3 off in Aisle 4. Want it?" | Yes (adds it to the plan with `set_plan`: the agent does it when you say it, the iPad when you tap) / No thanks (P5) |
| `newDeal` | a live `deals` change (new or improved) on a product in the plan or cart, or one that `pairs_with` them | "New deal: Chips $1.50 off" | Add it / Got it |
| `confirmItem` | a vision `cart_events` row with `product_id = null` that isn't resolved (P4) | Photo + "Is this the Rao's marinara?" (best catalog match for the event's `label`) | Yes / Something else (pick from the 3 closest matches or search) / Remove |
| `offline` | the app's own connection state | "Voice is offline. Tap to retry." | Retry |

The shopper can answer any card by voice ("yes," "no thanks") or by tap. `confirmItem` cards outrank deals. A confirmed item is sent as `apply_cart_event(type 'added', product_id, source 'manual')`, which links back to the unrecognized event (P4).

### 3.6 Voice, lists, and navigation
- **Hands-free.** After the greeting, Kart listens continuously; the shopper can interrupt it mid-sentence. The mute pill is always one tap away.
- **Kart's voice style:** ≤ 2 short sentences per turn, warm and specific; mentions prices only for deals or when asked; never invents products, prices, or deals (only catalog and tool results).
- **Shopping lists by voice.** "I need eggs, milk, and stuff for tacos." Kart maps it to catalog products, writes the plan with `set_plan`, and confirms it back briefly ("Got it: eggs, milk, and taco night. Want me to route you?"). Items not in the catalog are said plainly ("I don't see cilantro here"). Kart doesn't plan products with `stock` 0; if one sells out mid-trip, its list row reads "Out of stock" and Kart offers an alternative.
- **Navigation (inferred location).** "You are here" = the section of the last item added, or what the shopper says ("I'm at aisle 5") (P3). The Next stop card shows `carts.next_step`, which the backend computes from the plan and the store layout; the iPad only draws it.

### 3.7 Trip lifecycle
A trip runs from the Welcome tap (`reset_cart`, which issues a new `trip_id`) through checkout to Receipt → Done. Status is `idle → shopping → checkout → paid → idle` (P2). If a trip has no cart activity and no speech for 10 minutes, the screen asks "Still shopping?"; the debug panel can force-reset at any time.

---

## 4. Architecture

```
 ┌──────────── iPad on the cart (SwiftUI) ────────────┐
 │  Screens: Welcome → Shopping → Checkout → Receipt  │
 │  KartBackend ── Supabase realtime: carts row,      │
 │      cart_events, products, deals, transcript; RPCs│
 │  VoiceSession ── mic/speaker ⇄ Line WebSocket      │
 │  Store map (bundled store.json) · Payment (sim)    │
 └───────┬───────────────────────────────┬────────────┘
         │ realtime + RPCs (anon key)     │ audio up/down, `custom` events
         ▼                               ▼
 ┌──── Supabase (backend chat) ───┐   ┌──── Cartesia Line (hosted) ────┐
 │ carts · cart_events · products │◀──│ Python agent "Kart" (agent/)   │
 │ deals · transcript (P6)        │   │ Claude + tools (§4.3)          │
 │ RPCs: apply_cart_event,        │   │ writes plan and captions       │
 │ set_plan, reset_cart, …        │   └────────────────────────────────┘
 │ voice-token function (P7)      │
 └───────────────▲────────────────┘
                 │ apply_cart_event (vision)
        Raspberry Pi CV pipeline (pi/)
```

**Core rule:** the backend is the single source of truth. The iPad renders `carts` and `cart_events` and sends intents through RPCs; it never computes totals, deals, or routes itself. That is why it behaves identically with the mock backend and the real one.

### 4.1 iPad app (`ios/Kart/`)
- **Stack:** iPadOS 26, Swift 6, SwiftUI, Observation (`@Observable`), Swift Testing. Landscape only.
- **Folders:** `App/` (entry, routing on trip status), `Features/{Welcome,Greeting,Shopping,Checkout,Receipt}/`, `Avatar/`, `Cards/`, `DesignSystem/` (colors, type, spacing, motion, sounds, product tiles), `Services/{Backend,Voice,Audio,Payment,Catalog}/`, `Debug/`.
- **Catalog, two sources (contract v0.4 §2):** an Xcode build phase copies `../data/store.json` into the app bundle for the **store layout** (`store`, `entrance`, `sections`) and as the offline/mock catalog. **Prices, deals, stock, and names come live** from the Supabase `products` and `deals` tables (realtime), because the merchant agent edits them mid-demo. Bill lines come from `carts.items`.
- **Seams (Swift protocols), each with a real and a mock implementation:**
  - `KartBackend`: live streams of the cart (the `carts` row decoded per contract §3), the catalog (`products` + `deals`), recent `cart_events`, and recent transcript lines; intents `startTrip` (`reset_cart`), `confirmItem`/`fixItem`/`removeItem` (`apply_cart_event` with `source: "manual"`), `dismissSuggestion` (P5), `startCheckout`/`completeCheckout` (P2, P8), `endTrip`. Implementations: `SupabaseKartBackend` (`supabase-swift`), `MockKartBackend` (in memory, scriptable, and reimplementing just enough of the backend rules to run the demo).
  - `VoiceSession`: `start(cartId:tripId:)`, `stop()`, `setMuted(_:)`, `send(_ event:)`; publishes `state` (idle, connecting, listening, userSpeaking, thinking, agentSpeaking, offline) and `outputLevel` (0–1, drives the mouth). Implementations: `LineVoiceSession`, `MockVoiceSession` (scripted lines with synthetic loudness). Fallback if Line fails us: `DirectVoiceSession` (Cartesia speech-to-text and text-to-speech directly, Claude through a server function).
  - `PaymentProvider`: `pay(amount:tripId:) async throws -> PaymentResult`. Implementation: `SimulatedPaymentProvider` (realistic delay; failure can be forced from the debug panel).
- **Audio:** `AVAudioSession` `.playAndRecord`, mode `.voiceChat`, `.defaultToSpeaker`; `AVAudioEngine` with voice processing on the input node (echo cancellation, so Kart doesn't hear itself); 16 kHz mono PCM16 sent in ~40 ms chunks; playback through `AVAudioPlayerNode`; on Line's `clear` event, flush queued audio immediately (barge-in).
- **Config:** `ios/Config.xcconfig` (gitignored in `ios/.gitignore`; `Config.example.xcconfig` committed) holds `SUPABASE_URL`, `SUPABASE_ANON_KEY` (public by design), and `CART_ID`, filled from the shared `<repo>/.env` by a small script. **No secret keys on the device:** the Cartesia access token is short-lived and fetched per trip (P7).
- **Debug panel** (three-finger long-press anywhere): fire any catalog item as an added/removed vision event (with a confidence slider and an "unrecognized" option), reset the trip, force a payment failure, switch to **offline demo mode** (`MockKartBackend` + `MockVoiceSession` running a scripted pasta-dinner conversation).
- **Third-party packages:** `supabase-swift` (required); `RiveRuntime` and `lottie-ios` (optional, §3.3). Exact versions pinned.

### 4.2 What the iPad uses from the backend (contract v0.4)
- **`carts` row** (realtime): `items` (price after deal, `deal_label`), `total`, `plan` (`product_id`, `reason`, `done`, in route order), `next_step`, `suggestion`, `trip_id`, `updated_at`. The iPad ignores `lcd_line1`.
- **`products`** (realtime): `id`, `name`, `short_name`, `price`, `section`, `category`, `tags`, `stock`. **`deals`** (realtime): `id`, `product_id`, `type`, `label`, `pairs_with`, `ends_at`. (`vision_hint` and `value` are unused; all price math is the backend's.)
- **`cart_events`** (realtime, append-only): the "what the AI saw" trail; null-`product_id` vision events become `confirmItem` cards; `snapshot_url` is shown when present.
- **RPCs:** `apply_cart_event` (manual fixes and debug-panel events), `set_plan` (agent), `reset_cart` (new trip).

### 4.3 Voice agent (`agent/`, Python on Cartesia Line)
- **Hosting:** Cartesia Line managed runtime, deployed with the Line CLI. The iPad connects to `wss://api.cartesia.ai/agents/stream/{agent_id}` with a short-lived access token, `input_format: pcm_16000`.
- **Brain:** Claude Opus 5.5 at `effort: "low"` for fast voice turns, streaming, with server-side refusal fallbacks enabled (`fallbacks: "default"`). The model and effort are agent config (`KART_MODEL`, `KART_EFFORT` env vars), not code. Cartesia judges weigh voice latency, so milestone 3 measures time-to-first-audio per turn for Opus 5.5 at low effort against Haiku 5.5 on the same scripted turns; which one ships is a team decision. The plan's first step checks whether Line lets us run a custom handler with the official `anthropic` Python SDK (preferred) or only its built-in LLM wrapper.
- **Secrets:** `ANTHROPIC_API_KEY`, `SUPABASE_URL`, and `SUPABASE_ANON_KEY` live in Line's environment settings, copied from the shared `.env`; never in the repo.
- **Tools:**
  - `search_catalog(query)` (live `products`: names, `short_name`, price, section, stock), `get_cart()` (reads the `carts` row)
  - `set_plan(items[])` (RPC), `get_deals(for_products?)` (live `deals`, including `pairs_with`)
  - `set_location(section)` (P3), `dismiss_suggestion()` (P5), `confirm_item(event_id, product_id)` (`apply_cart_event`, manual)
  - `start_checkout()` (P2)
- **Events from the iPad** (Line `custom` events): `trip_context` {cartId, tripId} right after `ack`; `cart_changed` {added or removed, product_id, short_name}; `suggestion` {the new `carts.suggestion`} and `deal_changed` {deal id, short_name, label}, so Kart can say deals out loud; `card_response` {kind, action}; `ui_action` {e.g. checkout tapped}.
- **Captions:** the agent writes each shopper utterance (from Line's speech-to-text) and its own reply text to `transcript` (P6); the iPad renders captions from realtime.
- **Reconnects:** on `trip_context`, the agent reloads the cart, plan, and recent transcript, so a dropped socket resumes the same conversation.
- **Guardrails:** products, prices, and deals come only from the catalog and tool results; the system prompt forbids inventing them. Unclear speech → a short re-ask, not a guess.
- **Key risk, checked first:** whether Line lets the agent *start* speaking on a `custom` event (proactive deal suggestions). If not, the deal shows as a card with the card sound, and Kart mentions it on its next turn.

---

## 5. Privacy and trust (pitch-ready)
- **The mic is off** until the shopper taps Start, and it's always visibly marked when on.
- **Cameras point into the basket only** (on the Pi). The iPad's cameras are never used.
- **"What the AI saw":** checkout shows the photo behind each line when the Pi uploads one (P9), and every line traces to a `cart_events` row.
- **No accounts, no personal data.** Transcripts are cleared when the next trip starts (P6).
- **Where Claude could fail us, and what we did:** misidentified items → confirm cards plus a checkout block on unresolved items; invented deals or prices → catalog/tool-only facts; bad routes → the backend's deterministic routing.

---

## 6. Error handling and resilience
| Failure | Behavior |
|---|---|
| Network drops | Supabase realtime reconnects; a slim "Reconnecting…" banner; the screen keeps the last cart state; taps that fail show a retry |
| Line socket drops | Reconnect with backoff (1 s, 2 s, 4 s); then the `offline` card; everything stays tappable; `trip_context` is re-sent on reconnect |
| Mic permission denied | The Welcome screen explains; the trip runs tap-only |
| Unrecognized item | `confirmItem` card; checkout is blocked until it's resolved (one tap each) |
| Claude error, timeout, or refusal | The agent says a short fallback line ("Sorry, say that again?"); refusals use server-side fallback first |
| Loud room | Mute pill; a hold-to-talk mode in the debug panel as backup |
| Payment fails (forceable) | "Payment didn't go through. Try again." with retry |
| Everything is down at demo time | Offline demo mode runs the full scripted flow with no network |

---

## 7. Testing
- **iPad:** Swift Testing unit tests for the trip router, card derivation and queue (deal vs. confirm priority, unresolved-event detection), label → catalog matching, totals formatting, and contract decoding (fixtures copied from contract §3), against `MockKartBackend`/`MockVoiceSession`. A screenshot of every screen in the iPad simulator, checked against the §3.1 principles. Audio (echo cancellation, barge-in, loudness → mouth) can only be validated **on the real iPad**, so each voice milestone ends with an on-device check.
- **Agent:** pytest for each tool against a fake Supabase, plus a short scripted text conversation against Claude (costs cents) to check tool use and the voice style rules.
- **Integration:** once the backend is live, the debug panel replays the §1.1 cart events through real `apply_cart_event` calls; a rehearsal checklist for the live demo.

---

## 8. Build order (each milestone is demoable)
1. **App shell and design system:** all five screens, Kart's avatar and reactions, cards, the debug panel, on `MockKartBackend` + `MockVoiceSession`. *Demo: the full flow tapped through with fake items and a scripted voice.*
2. **Supabase hookup:** `SupabaseKartBackend` against the backend chat's schema (as soon as `carts` and the RPCs exist). *Demo: debug-panel events from the iPad, or real CV events, update the screen live.*
3. **Voice:** check the Line risks first (custom handler with the official SDK, proactive speech), then the Line agent (text-tested), then `LineVoiceSession` on the real iPad, then the latency comparison (Opus 5.5 low vs. Haiku 5.5, time from end of speech to first audio). *Demo: a hands-free greeting and conversation with interruption.*
4. **Agent features:** voice list → `set_plan`, spoken deal suggestions, Next stop narration, "I'm done" → checkout.
5. **Checkout polish:** bill with photos or tiles, the pay sheet, the receipt, trip reset, offline demo mode.
6. **Demo hardening and rehearsal** with the real Pi and props.

---

## 9. Contract proposals (sent to the manager; not built until they're in the contract)
| # | Proposal | Why the iPad needs it |
|---|---|---|
| P1 | Ownership: the iPad chat owns `ios/` and `agent/`. Rewrite §5 for the cart-mounted iPad: no QR pairing; the iPad is configured with `CART_ID`; it replaces the phone web app | Clear paths; §5 is still the phone design |
| P2 | `carts.status` (`idle`, `shopping`, `checkout`, `paid`) and `carts.trip_started_at`, set by `reset_cart`; RPC `set_cart_status(p_cart_id, p_status)` | Screen routing; the agent can start checkout; trip time for the receipt |
| P3 | `carts.location` jsonb `{section, source: "item" \| "voice", at}`: `apply_cart_event` sets it to the added product's section; RPC `set_location(p_cart_id, p_section)` for "I'm at aisle 5" | "You are here" on the map; better `next_step` routing |
| P4 | `cart_events.resolved_at` plus `apply_cart_event(..., p_resolves_event_id uuid default null)`; a manual fix that names an unrecognized event marks it resolved | So confirm cards disappear once answered, and checkout can check for unresolved items |
| P5 | RPC `dismiss_suggestion(p_cart_id)`, which clears `suggestion` and doesn't re-offer that deal this trip | The "No thanks" button |
| P6 | Table `transcript` (`id`, `cart_id`, `trip_id`, `role` user\|agent, `text`, `created_at`; realtime ON) with RPC `append_transcript`; `reset_cart` deletes the old trip's rows | Live captions; the privacy story |
| P7 | A Supabase Edge Function `voice-token`, written by the backend chat (it owns the project). `POST /functions/v1/voice-token {cart_id}` → calls Cartesia `POST /access-token` with `{"grants": {"agent": true}, "expires_in": 3600}` → returns `{token, expires_at, agent_id, ws_url, cartesia_version}`. Shape sent to the backend chat directly | Keeps the Cartesia key off the iPad |
| P8 | `carts.savings` (Σ deal discounts) and a `list_price` per item; RPC `checkout(p_cart_id, p_provider)` that writes a `receipts` row (`cart_id`, `trip_id`, `total`, `savings`, `item_count`, `duration_s`, `provider`, `status`) and sets status `paid` | "Saved $x," the strikethrough price, the receipt |
| P9 | (Nice to have, for CV) upload the event crop to `snapshots/{cart_id}/{event_id}.jpg` and set `snapshot_url` | Photos on confirm cards and at checkout (the Visa trust story); product tiles cover it if not |
| P10 | When a merchant changes a price or deal, the backend recomputes the affected open carts (`items` prices, `deal_label`, `total`, `savings`, `suggestion`), so the bill updates live too. Rule (agreed with the manager): new deals and price drops also apply to items already in the cart; increases, and deals that end or are removed, apply only to items added afterward | The "owner changes a deal → the cart updates in seconds" moment covers the bill, not just the catalog; "the price you saw is the price you pay" is the trust story. When a drop lands on an item already in the cart, the iPad celebrates it ("Parmesan just dropped $3, you saved") |

---

## 10. Risks and open questions
- **Cartesia Line:** proactive speech on `custom` events; whether custom handlers can use the official `anthropic` SDK; pricing and hackathon credits (ask Cartesia at the venue). Fallback: `DirectVoiceSession`.
- **Voice latency** with Opus 5.5 at low effort; measured in milestone 3; changing the model is the team's call.
- **Backend timing:** milestone 2 waits on the backend chat's schema; `MockKartBackend` keeps the UI moving meanwhile.
- **The physical iPad:** confirm the model and the landscape mount with the CAD teammate. Free Apple ID signing expires after 7 days, so reinstall the app the day before judging.
- **Venue noise:** test hands-free in the hall early; hold-to-talk is the backup.
- **Sponsor criteria:** re-check Visa (any payment plugin) after the opening ceremony.
