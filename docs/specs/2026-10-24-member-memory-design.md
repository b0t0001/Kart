# Kart remembers you: member memory (design)

**Status:** approved by Dylan with changes (the member is Dylan; demo fast-forward added) · 2026-10-24
**Built by:** the "member memory" chat, which reports to the manager (contract §8)
**Flag:** `member_memory`, **off by default**. With it off, nothing changes. The rollback tag is `stable-pre-memory`.

## 1. What and why

**Dylan's ask:**
- A demo sign-in with a store member ID. It's a visual step, not real authentication.
- Kart keeps a memory of each member: what they buy, their patterns, their favorite snacks and drinks, and when they buy them.
- Kart recommends items for *this week* from that history.
- As they shop, Kart asks the occasional question about what's coming up ("any fun events coming up?") and remembers the answer. Next visit it greets them with that memory ("Thanksgiving's Thursday, want to shop for it?") and can plan for it ahead of time.
- The demo uses one member, but the design remembers every member, so it scales to many stores and many people.
- It should feel intimate.
- **In the pitch** Dylan schedules a future event with Kart, then fast-forwards the cart's clock and shows that Kart brings it up when that day comes. The demo member is Dylan himself. Leo's soccer party stays as a memory he already has.

**Success means:**
1. In the demo, a member signs in and within ~3 s Kart says something clearly about *them* and about *this week*.
2. Something the shopper says in one trip comes back on a later trip in the same demo, minutes later: after a fast-forward, on the day it matters.
3. It's warm, not creepy: one or two memories per greeting at most, everything Kart remembers is visible on screen, and one tap forgets it.
4. With the flag off, the stable demo is byte-for-byte unchanged.

## 2. The demo beat (adds ~75 s to the pitch)

Before judging, `backend/members.py seed` loads member **1029, "Dylan"**: a household of 4 with ten weeks of believable trips, plus Leo's soccer party tomorrow. The seed is relative to the day it runs, so the demo day is always one of his usual shopping days.

1. Welcome screen → **"Member? Sign in"** → type `1029` on the member card. Kart waves: *"Welcome back, Dylan!"* and then, from memory: *"Leo's soccer party is tomorrow. Want the nachos list?"* "Yes" puts the saved nachos list on today's plan, and that flows straight into Meal B (`docs/DEMO_PLAN.md`). The chips stay off the list, so the chips deal card still fires.
2. The **For you** card shows three picks, each with its reason:
   - Salsa: *Leo's soccer party · tomorrow*
   - Milk: *every week · last Sat*
   - Tortillas: *your Saturday usual*
   One tap adds a pick to the list.
3. Mid-trip the shopper says *"Hey Kart."* Kart: *"Hey Dylan! Any fun plans coming up I can help you shop for?"* Shopper: *"I'm hosting Friendsgiving next Saturday, ten people."* Kart: *"Ooh, fun. I'll remember that. Want me to start a list for it?"* "Sure." The list is saved for next time, and Kart says plainly what the store doesn't carry.
4. Check out → the receipt says *"Saved to Dylan's history."*
5. **Fast-forward.** In the demo controls (three-finger long press), tap **Jump to the day before Friendsgiving**.
   - The Welcome screen's date chip flips to *"Friday, Oct 30 · demo date"*.
   - From then on the cart's "today" is that date for everything memory touches: picks, how many days until an event, Kart's date math, and the purchase dates of a member checkout.
6. Sign in again as 1029 → *"Welcome back, Dylan! Friendsgiving's tomorrow, and your list is ready. Want to shop it now?"*
   - The For you card leads with the Friendsgiving list.
   - Milk is due again: it was last bought in step 4, "a week ago".
   - Kart may ask how Leo's party went.
7. The member chip → **What Kart remembers**: Friendsgiving, Leo's party (past), "likes the marinara here", his usuals. Tap **Forget** on any row; **Forget me** wipes everything.
8. After the pitch: demo controls → **Back to today**.

## 3. Experience

Principles from the iPad spec §3.1 still hold: glanceable, one primary action, voice = touch, spring motion, never silently wrong.

### 3.1 Sign-in (visual)
- Welcome keeps **"Tap to start shopping"** as the one primary action. With the flag on, a quiet secondary pill underneath reads **"Member? Sign in"**.
- That pill opens a member card: a store-card look with a big 4-digit keypad. The 4th digit submits. There's no password; the card says *"Demo sign-in"*.
- **A known number** signs in as that member and starts the trip; Kart reacts with a wave.
- **An unknown number** creates a new, empty member: *"Nice to meet you!"* Kart's first question that trip is *"What should I call you?"* This is how "remembers each user" scales: anyone can become a member at the cart.
- Sign-in lasts one trip. A new trip starts as a guest.

### 3.2 Greeting
- **Guest:** unchanged ("Hi, I'm Kart. What are we shopping for today?").
- **Member:**
  1. An instant fixed line, *"Welcome back, Dylan!"* (or *"Nice to meet you!"*), so there's no wait.
  2. Then Claude, with the member's profile in its prompt, adds at most two short sentences that use the most relevant memory (an upcoming event, a saved list, something due) and asks what they're shopping for.
  3. The fixed line covers Claude's ~1.5 s.

### 3.3 For you card
- On the shopping screen, at the top of the trip panel. It's styled like the deal card but in the member's accent color.
- Up to **3 picks**, each with a one-line reason and a **+** that adds it to the list, the same path as Yes on a deal card.
- If an upcoming event has a saved list, its first line reads *"Friendsgiving · Sat · 5 items saved"* with **Shop it**, which adds the saved list to today's plan and keeps what's already on it.
- It hides once every pick is on the list, or on **Not today**. It never returns that trip.

### 3.4 Kart's occasional question
- **At most one per trip,** asked at one of two moments:
  - **"Hey Kart" with nothing else** (a bare greeting), or
  - **a lull:** the iPad notices 40 s with no activity while shopping, with no card or nudge open, and tells the agent.
- **What it asks,** chosen in code, not by Claude, so it's predictable:
  - a nameless member → *"What should I call you?"*;
  - otherwise one of a short rotation: *"Any fun plans coming up I can help you shop for?"*, *"Anyone coming over soon?"*, *"Got anything coming up, like a party or a holiday?"*
- **The answer goes to Claude,** which knows what Kart just asked. Claude saves anything worth keeping with `remember`, such as an event and its date, a lasting preference ("we're vegetarian now"), household size, or their name. Claude replies like a friend ("Ooh, fun. I'll remember that.").
- Small talk that isn't about future shopping isn't saved.

### 3.5 Planning ahead
- **Creating the list.** For an event, Kart offers to start a list. On yes, Claude picks the store's products, sized for the guest count, and saves them on that memory (`save_for_later`) without touching today's plan.
- **Adding mid-trip.** "Add cranberry sauce to my Friendsgiving list" works the same way.
- **Things the store doesn't carry.** Kart says so ("I don't see turkey here") and keeps the event note.
- **Next trip.** The greeting and the For you card offer the saved list. "Shop it" puts it on the plan.

### 3.6 What Kart remembers (the trust story)
- A small **member chip** ("Dylan", with an initial avatar) sits in the shopping screen's corner. Tapping it opens a sheet with:
  - **Coming up:** events with dates, and saved lists;
  - **Likes:** preferences;
  - **Usually buys:** the top items with their rhythm ("Milk · every 7 days").
- **Forgetting by touch:** each memory row has **Forget**. The footer has **Sign out** and **Forget me**, which wipes history and memories and asks for confirmation first.
- **Forgetting by voice:** "Kart, forget that" or "forget about Friendsgiving" uses the `forget` tool, one memory at a time. Wiping everything is touch-only and asks for confirmation, so a stray "forget it" can never erase a member.

### 3.7 Receipt
For a member, one extra line: *"Saved to Dylan's history."*

### 3.8 Demo date (fast-forward)
- **The controls.** The demo controls get a **Demo date** row:
  - **Today**
  - **+1 day**
  - **+1 week**
  - **Day before the next event**: the member's nearest upcoming event. It's hidden when there's none.
- **Where it's stored.** The date belongs to the cart (`carts.demo_date`). It survives new trips, so you can fast-forward between trips.
- **Showing it honestly.** While it's set, a small calendar chip shows the date ("Fri, Oct 30 · demo date") on Welcome and in the shopping screen's corner. Changing it plays a quick page-flip on that chip.
- **What it changes.** Only the member features:
  - the profile's "today";
  - the date Kart uses for "tomorrow" and "next Saturday";
  - the date stamped on a member checkout's purchase history.
- **What it never changes.** Store receipts, analytics, deals and trip times stay real.
- **Past events.** Once its date passes, an event drops out of "coming up". For 7 days it's a *recent past* memory, and Kart may ask how it went. In the memory sheet it shows dimmed under **Earlier**.

### 3.9 Edge cases (manager decision, 2026-10-24; full list in `docs/EDGE_CASES.md`)
- **Confirm who's signing in.** After the 4th digit the card asks first; Kart greets only after "That's me".
  - **A known number** shows the first name only: *"Dylan?"* with **That's me** / **Not me**.
  - **An unknown number** asks *"We don't know 1092. Start a new membership?"*: Yes creates the member, No goes back to the keypad.
  - Nothing is created by a typo.
- **"Forget me" mid-trip takes effect at once.** The iPad tells the agent (`member_forgotten`). The agent drops the profile, the member prompt and the memory tools, and says *"Done. I've forgotten everything about you."* Kart can't mention a forgotten memory afterwards.
- **Forget one memory, or sign out.** Forgetting one memory from the sheet re-sends `trip_context`, so the agent reloads the profile. Signing out re-sends it without `member_id`, and the agent drops the member silently.
- **Walking away while signed in.** After 3 min with no activity, Kart asks *"Still shopping, Dylan?"*, and a small banner offers **Still here** / **Sign out**. At 5 min the cart signs out; the trip and cart are kept, and only the member is cleared.
- **Sensitive things are never remembered.**
  - **Purchases:** products in sensitive categories (`pharmacy`, `health`, `medicine`, `personal-care`, `baby`, `pregnancy`, `adult`) are never copied into member history, so they can't feed picks, usuals or speech.
  - **Memories:** Kart never saves health, pregnancy, religion, sexuality, finances or details about children beyond what the plan needs. It saves the event, not the reason ("dinner on Saturday", not why).
- **Stale events.**
  - An undated event expires from "coming up" 30 days after it was saved.
  - `members.py seed` prints Leo's party's date.
  - `backend/pre_judging.sh --members` reseeds right before judging.
- **"What do you know about me?"** Kart opens the memory sheet on the iPad and gives a one-line summary. Everything is visible, and anything can be forgotten.

## 4. Recommendations: what "this week" means

The backend computes these deterministically (testable, instant). Claude only phrases them.

| Signal | Rule | Reason shown |
|---|---|---|
| **Coming up** | An event memory dated within the next 14 days that has saved items. Its first saved item not yet on the list. (An event with no saved list still shows as the card's event line and in Kart's greeting.) | *"Leo's party tomorrow"* |
| **Due again** | Bought ≥ 3 times; `days since last ≥ 0.85 × median gap` | *"every week · last Sat"* |
| **Your usual today** | Bought on this weekday in ≥ 60% of the member's trips on this weekday | *"your Saturday usual"* |

- **Picks:** up to 3. First the top pick from each signal, in the table's order, so the card shows a mix (one for the event, one that's due, one usual). Then any open slots fill by the same order. Each product appears once. Picks leave out anything already in the cart or on the plan, and anything out of stock.
- **Deals stay with the deal cards:** a product with a live deal is never a pick, and Kart doesn't pitch deals from memory. The store's deal moments, the Parmesan and chips cards, fire exactly as before (a card never shows for something already on the list).
- **Profile data for Claude:** the rhythms (every N days, usual weekday), favorites, the last trip, and the memories.

## 5. Architecture

```
 iPad ── reset_cart → set_member(cart, 1029) ──▶ carts.member_id
   │  member_profile(1029) ◀── picks, usuals, memories (RPC, recomputed on read)
   │  trip_context {cart_id, trip_id, member_id} ──▶ agent ── member_profile ──▶ prompt
   │  lull ─────────────────────────────────────────▶ agent: one question per trip
   │                                       agent ── member_remember / save_for_later / forget
   │  carts.member_rev bumps ◀─────────────────────── (iPad refetches the profile)
 checkout() ── receipts insert ── trigger ──▶ member_purchases (history grows)
```

### 5.1 Backend: new file `backend/db/07_members.sql`, additive only
- **Tables.** RLS is on, with **no anon read and no realtime**; access goes only through `security definer` RPCs.
  - `members(member_id text pk, name text null, household int null, created_at)`
  - `member_purchases(id, member_id, product_id, qty, price, bought_at, trip_id null, source 'seed'|'checkout')`
    - Real trips still come from `receipts`: the receipt trigger below copies each paid bill's lines in.
    - It's a separate table only so the ten-week demo seed never shows up as store trips or revenue in `store_insights`, which counts `receipts`.
  - `member_memories(id bigserial, member_id, kind 'event'|'preference'|'note', text, event_date date null, items jsonb null [{product_id, qty}], trip_id null, created_at)`. Forgetting deletes the row.
- **`carts` gains** `member_id text null`, `member_rev int default 0`, and `demo_date date null` (null means real today; §3.8).
- **`receipts` gains** `member_id text null`.
- **Flag:** a `feature_flags` row `member_memory`, seeded **false**. It uses the existing per-cart `set_feature`.
- **RPCs:**
  - `set_member(p_cart_id, p_member_id) → carts row`
    - null signs out;
    - an unknown id creates the member;
    - it raises `feature_off: member_memory` if the cart's flag is off.
  - `set_demo_date(p_cart_id, p_date date) → carts row`
    - null goes back to real today.
    - It raises `feature_off: member_memory` when the cart's flag is off.
    - `reset_cart` leaves it alone.
  - `member_profile(p_member_id, p_cart_id default null, p_today date default null) → jsonb`:
    - "today" is `p_today`, else that cart's `demo_date`, else `current_date`.
    - Tests pass `p_today`. The iPad and the agent pass their cart.
    ```jsonc
    { "member": {"member_id","name","household","since","trips"},
      "today": "2026-10-24", "weekday": "Saturday",
      "picks":   [{"product_id","short_name","kind":"event|due|usual","reason","aisle","memory_id"?}],
      "usuals":  [{"product_id","short_name","times","every_days","last","weekday"?}],
      "memories":[{"id","kind","text","event_date","days_until","items":[{"product_id","short_name","qty"}]}],
      "last_trip": {"date","items":["Chips","Milk",…],"total"} }
    ```
  - `member_remember(p_member_id, p_kind, p_text, p_event_date default null, p_trip_id default null) → memory`
    - `p_kind` is `event`, `preference` or `note`, which add a row.
    - Or it's `name` or `household`, which update `members` instead.
    - It bumps `member_rev` on any cart signed in as that member.
  - `member_save_for_later(p_member_id, p_memory_id, p_items jsonb) → memory`
    - Merges by `product_id`; the last qty wins.
    - Unknown products raise.
  - `member_forget(p_member_id, p_memory_id default null)`
    - null means forget everything: purchases, memories and name. Any cart signed in as that member is signed out.
- **Triggers:**
  - **On a paid receipt:** if the cart has a `member_id`, set `receipts.member_id` and copy the bill's lines into `member_purchases`.
    - `bought_at` is the cart's `demo_date`, at the current time of day, when one is set; otherwise `now()`.
    - The receipt's own `created_at` stays real.
  - **On a new trip:** when `carts.trip_id` changes, `member_id` goes back to null. Every trip starts as a guest, and `reset_cart` is unchanged.
- **Seed:** `backend/members.py seed [--member 1029 --name Dylan]` rebuilds that member relative to today and touches nothing else:
  - **Trips:** ten weeks, on today's weekday plus a midweek top-up, using today's catalog ids. The usual-day basket is taco night; milk and bananas weekly, eggs every ~10 days, pasta and marinara every other week, paper towels every ~5 weeks; chips and salsa are the favorite snack.
  - **Memories:**
    - "Leo's soccer party, nachos for the team", dated tomorrow, with a saved list: Meal B without the chips, one each of `tostitos-salsa`, `queso`, `black-beans`, `jalapenos` and `daisy-sour-cream`;
    - the preference "Likes the {short_name} here" for `rao-marinara`, using its live short_name, because the brand is changing to a generic jar.
  - **By product id:** the seed looks up names and prices by product id at run time and skips missing ids with a warning, since the catalog is changing for the demo meals.
  - **When to run it:** right before judging, next to `reset-demo`, because "tomorrow" and "last Saturday" are relative to the day it runs.
  - `members.py show 1029` prints the profile.
- **Tests:** member ids starting `it-` are test members, and they never touch 1029.

### 5.2 Agent (`agent/`)
- **New `kart_agent/memory.py`:**
  - turns the profile into a prompt section ("About this shopper, from Kart's memory"), with the profile's today and weekday. With a demo date set, that is the demo date. Claude works out "tomorrow" and "next Saturday" from it. The section lists upcoming events, recent past events ("you may ask how it went") and preferences;
  - holds the fixed greeting line and the question rotation;
  - has `only_greeting(text)` for a bare "Hey Kart".
- **`trip_context` gains `member_id`** (additive). With it, the agent fetches `member_profile` before greeting and adds the member section to Claude's system prompt; without it, everything behaves exactly as today.
- **New tools, exposed only when a member is signed in:**
  - `remember(kind, text, date?)`
  - `save_for_later(memory_id, items)`
  - `shop_saved_list(memory_id)`: puts a saved event list on today's plan in one `set_plan` and keeps what's there ("Yes" to "want the nachos list?")
  - `forget(memory_id)`: one memory, required id
  After a write, the agent refreshes the profile.
- **Prompt rules for members:**
  - Use at most one or two memories per turn, naturally.
  - Leave deals to the cart's deal cards; don't pitch them from memory.
  - Never recite their history or what they paid.
  - Only state memories that are in the profile.
  - When they share future plans, save them and offer a list.
  - "Forget that" uses `forget`.
- **A new custom event, `lull`,** triggers the one question if it hasn't been asked this trip and nothing is pending. The question goes into Claude's history, so the answer has context.

### 5.3 iPad (`ios/`)
- **KartCore:**
  - `MemberProfile` models.
  - `KartBackend` gains:
    - `signIn(memberId:)` and `signOut()`;
    - `memberProfile` (observable, refetched when `cart.memberRev` changes);
    - `forgetMemory(id:)` and `forgetMember()`;
    - `setDemoDate(_:)`, with `cart.demoDate` decoded from the carts row.
  - **Mock:** `MockKartBackend` implements all of it with Dylan's fixture, so the offline demo mode rehearses the whole beat.
  - **Supabase:** `SupabaseKartBackend` implements it over REST.
- **AppModel:**
  - `startTrip(memberId:)`: reset, then `set_member`, then `trip_context` with `member_id`.
  - It sends `lull` once per trip, under the §3.4 rule.
  - A pick's **+** and **Shop it** go through the existing `setPlan` path.
- **Views:** new `Features/Member/`:
  - `MemberSignInView` (card + keypad)
  - `ForYouCard`
  - `MemberChip`
  - `MemoryView` (the sheet)
- **Small hooks:**
  - `WelcomeView`: the secondary pill and the demo-date chip
  - `TripPanel`: the card, the member chip and the demo-date chip
  - `ReceiptView`: one line
  - the demo controls: the **Demo date** row (§3.8)
- **Flag:** everything is shown only when `carts.features.member_memory` is on.

## 6. Stability
- **When the flag is off:**
  - `set_member` and `set_demo_date` refuse, so `carts.member_id` and `carts.demo_date` stay null;
  - the iPad shows no member UI;
  - `trip_context` has no `member_id`, so the agent is unchanged;
  - the receipts trigger does nothing.
- **Proving it:** with the flag off, the backend's existing cart snapshot tests (the nudges pattern) must still match exactly. The tag `stable-pre-memory` marks `main` just before the merge.
- **Turning it on:** first on Dylan's test cart (`ipad-live`), then on cart 7 when he says it's good.

## 7. Privacy (pitch lines)
- **Opt-in:** guest is the default; signing in is one deliberate tap and lasts one trip.
- **Transparent:** everything Kart remembers is on one screen, and each item can be forgotten in one tap or by voice. "Forget me" wipes it all.
- **Shopping memory only:** Kart saves future plans and preferences, never small talk. Transcripts are still deleted on every new trip.
- **Demo-grade honesty:** anyone with the anon key and a member number can read that profile. A real version uses store-issued sign-in tokens (Supabase Auth). Out of scope here, and we say so.
- **Production sign-in (pitch line):** a QR code or passkey from the shopper's phone, not a typed number.
- **Never remembered:** sensitive purchases and sensitive personal details (§3.9).

## 8. Error handling
- **Profile fetch fails or is slow (> 1 s):** the agent greets with just the fixed member line plus the normal question, and the iPad hides the For you card. The trip itself never waits on memory.
- **`remember` fails:** Kart doesn't claim it remembered ("Sorry, I couldn't save that").
- **Unknown product in `save_for_later`:** Claude is told, and says the store doesn't carry it.
- **Sign-in tapped while the flag is off** (e.g. it was flipped mid-session): the iPad starts a guest trip.

## 9. Testing
- **Backend (pytest, local Postgres):**
  - each pick rule (event, due, usual), live-deal products never picked, the 3-pick cap, and leaving out items on the plan or out of stock;
  - unknown ids create members;
  - the flag-off refusal;
  - the receipt trigger copies lines once (idempotent checkout);
  - a trip change clears the member;
  - forget one / forget all;
  - the demo date: it moves the profile's today, survives `reset_cart`, makes an event "tomorrow" and then "recent past", and stamps member purchases while receipts stay real;
  - flag-off snapshots unchanged.
- **Agent (fakes):**
  - the member prompt section;
  - the guest greeting unchanged;
  - the member greeting order (fixed line, then Claude);
  - one question per trip across "Hey Kart" + lull;
  - `remember`, `save_for_later` and `forget` call the right RPCs;
  - no member tools for guests.
- **iPad:**
  - KartCore unit tests for profile decoding, sign-in → trip start order, the lull rule (once, not while a card is open), and the For you card hiding rules;
  - a UI test of the full beat on the mock backend, including the fast-forward and the second sign-in.
- **End to end:** local Supabase, then hosted on a throwaway cart and `it-` member: sign in → remember an event → checkout → new trip → the profile shows the event and the new purchases.

## 10. Ownership and coordination
- **Decided by the manager:** this chat builds the whole slice in its **own git worktree** (branch `member-memory`), so it never collides with the iPad and backend chats' live edits in the main checkout.
  - Almost everything is new files. The hooks into shared files are small and listed in §5.
  - Merge `main` into the branch often, never rebase. Expect churn in `data/store.json` (demo-meal products) and the agent's prompt.
  - On hosted, apply additive migrations only, never run `reset-demo`, and test only on throwaway carts and `it-` members.
  - Once everything is green, send the manager the branch, a summary and the test results. The manager tags `stable-pre-memory`, merges, bumps the contract to v0.14 (§5 is the proposal), and tells the owners.
  - After the merge, the backend and iPad chats own their parts as usual.
- **Optional catalog ask, routed through the manager to the backend chat:**
  - **Products:** a drink or two (e.g. sparkling water) plus a few seasonal products (turkey, stuffing mix, cranberry sauce, pumpkin pie), so "favorite drink" and event lists have real items.
  - **Not physical props:** they're for lists only. CV's catalog grows, but these are never dropped in the cart.
  - **Without them:** the feature still works with today's 18 products.

## 11. Not now
- Real authentication or tokens.
- Members on the merchant console.
- Aisle-aware "grab it now for Friendsgiving?" nudges (a natural next step).
- Cross-store sync.
- Learning from items removed from the cart.
