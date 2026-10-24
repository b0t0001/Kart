# Kart remembers you: member memory (design)

**Status:** draft for Dylan's review · 2026-10-24
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

**Success means:**
1. In the demo, a member signs in and within ~3 s Kart says something clearly about *them* and about *this week*.
2. Something the shopper says in one trip comes back on the next trip, in the same demo, minutes later.
3. It's warm, not creepy: one or two memories per greeting at most, everything Kart remembers is visible on screen, and one tap forgets it.
4. With the flag off, the stable demo is byte-for-byte unchanged.

## 2. The demo beat (adds ~60 s to the pitch)

Before judging, `backend/members.py seed` loads member **1029, "Maya"**: a household of 4 with ten weeks of believable trips. The seed is relative to the day it runs, so the demo day is always one of her usual shopping days.

1. Welcome screen → **"Member? Sign in"** → type `1029` on the member card. Kart waves: *"Welcome back, Maya!"* and then, from memory: *"Leo's soccer party is tomorrow. Want chips and salsa for twelve? Chips are $1.50 off."*
2. The **For you** card shows three picks, each with its reason:
   - Chips: *Leo's party · $1.50 off*
   - Milk: *every week · last Sat*
   - Tortillas: *your Saturday usual*
   One tap adds a pick to the list.
3. Mid-trip the shopper says *"Hey Kart."* Kart: *"Hey Maya! Any fun plans coming up I can help you shop for?"* Shopper: *"I'm hosting Friendsgiving next Saturday, ten people."* Kart: *"Ooh, fun. I'll remember that. Want me to start a list for it?"* "Sure." The list is saved for next time, and Kart says plainly what the store doesn't carry.
4. Check out → the receipt says *"Saved to Maya's history."*
5. Start again and sign in as 1029 → *"Welcome back, Maya! Friendsgiving's next Saturday. I saved your list: want to shop it today or closer to the day?"*
6. The member chip → **What Kart remembers**: the party, Friendsgiving, "likes Rao's", her usuals. Tap **Forget** on any row; **Forget me** wipes everything.

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
  1. An instant fixed line, *"Welcome back, Maya!"* (or *"Nice to meet you!"*), so there's no wait.
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
- A small **member chip** ("Maya", with an initial avatar) sits in the shopping screen's corner. Tapping it opens a sheet with:
  - **Coming up:** events with dates, and saved lists;
  - **Likes:** preferences;
  - **Usually buys:** the top items with their rhythm ("Milk · every 7 days").
- **Forgetting by touch:** each memory row has **Forget**. The footer has **Sign out** and **Forget me**, which wipes history and memories and asks for confirmation first.
- **Forgetting by voice:** "Kart, forget that" or "forget about Friendsgiving" uses the `forget` tool, one memory at a time. Wiping everything is touch-only and asks for confirmation, so a stray "forget it" can never erase a member.

### 3.7 Receipt
For a member, one extra line: *"Saved to Maya's history."*

## 4. Recommendations: what "this week" means

The backend computes these deterministically (testable, instant). Claude only phrases them.

| Signal | Rule | Reason shown |
|---|---|---|
| **Coming up** | An event memory dated within the next 14 days that has saved items. Its first saved item not yet on the list. (An event with no saved list still shows as the card's event line and in Kart's greeting.) | *"Leo's party tomorrow"* |
| **Due again** | Bought ≥ 3 times; `days since last ≥ 0.85 × median gap` | *"every week · last Sat"* |
| **Your usual today** | Bought on this weekday in ≥ 60% of the member's trips on this weekday | *"your Saturday usual"* |
| **Favorite on deal** | One of their top-5 products has a live deal | *"$1.50 off this week"* |

- **Picks:** up to 3. First the top pick from each signal, in the table's order, so the card shows a mix (one for the event, one that's due, one usual). Then any open slots fill by the same order. Each product appears once. Picks leave out anything already in the cart or on the plan, and anything out of stock.
- **Deals:** a pick's line adds the deal label when there's a live deal.
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
- **`carts` gains** `member_id text null` and `member_rev int default 0`.
- **`receipts` gains** `member_id text null`.
- **Flag:** a `feature_flags` row `member_memory`, seeded **false**. It uses the existing per-cart `set_feature`.
- **RPCs:**
  - `set_member(p_cart_id, p_member_id) → carts row`
    - null signs out;
    - an unknown id creates the member;
    - it raises `feature_off: member_memory` if the cart's flag is off.
  - `member_profile(p_member_id, p_today date default current_date) → jsonb`:
    ```jsonc
    { "member": {"member_id","name","household","since","trips"},
      "today": "2026-10-24", "weekday": "Saturday",
      "picks":   [{"product_id","short_name","kind":"event|due|usual|deal","reason","aisle","deal_label"?,"memory_id"?}],
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
  - **On a new trip:** when `carts.trip_id` changes, `member_id` goes back to null. Every trip starts as a guest, and `reset_cart` is unchanged.
- **Seed:** `backend/members.py seed [--member 1029 --name Maya]` rebuilds that member relative to today and touches nothing else:
  - **Trips:** ten weeks, on today's weekday plus a midweek top-up, using today's catalog ids. The usual-day basket is taco night; milk and bananas weekly, eggs every ~10 days, pasta and Rao's every other week, paper towels every ~5 weeks; chips and salsa are the favorite snack.
  - **Memories:**
    - "Leo's soccer party, bringing snacks for 12", dated tomorrow, with a saved list (chips ×3, salsa ×2);
    - "Likes Rao's, not the store brand".
  - **When to run it:** right before judging, next to `reset-demo`, because "tomorrow" and "last Saturday" are relative to the day it runs.
  - `members.py show 1029` prints the profile.
- **Tests:** member ids starting `it-` are test members, and they never touch 1029.

### 5.2 Agent (`agent/`)
- **New `kart_agent/memory.py`:**
  - turns the profile into a prompt section ("About this shopper, from Kart's memory"), with today's date and weekday;
  - holds the fixed greeting line and the question rotation;
  - has `only_greeting(text)` for a bare "Hey Kart".
- **`trip_context` gains `member_id`** (additive). With it, the agent fetches `member_profile` before greeting and adds the member section to Claude's system prompt; without it, everything behaves exactly as today.
- **New tools, exposed only when a member is signed in:**
  - `remember(kind, text, date?)`
  - `save_for_later(memory_id, items)`
  - `forget(memory_id)`: one memory, required id
  After a write, the agent refreshes the profile.
- **Prompt rules for members:**
  - Use at most one or two memories per turn, naturally.
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
    - `forgetMemory(id:)` and `forgetMember()`.
  - **Mock:** `MockKartBackend` implements all of it with Maya's fixture, so the offline demo mode rehearses the whole beat.
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
  - `WelcomeView`: the secondary pill
  - `TripPanel`: the card and the chip
  - `ReceiptView`: one line
- **Flag:** everything is shown only when `carts.features.member_memory` is on.

## 6. Stability
- **When the flag is off:**
  - `set_member` refuses, so `carts.member_id` stays null;
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

## 8. Error handling
- **Profile fetch fails or is slow (> 1 s):** the agent greets with just the fixed member line plus the normal question, and the iPad hides the For you card. The trip itself never waits on memory.
- **`remember` fails:** Kart doesn't claim it remembered ("Sorry, I couldn't save that").
- **Unknown product in `save_for_later`:** Claude is told, and says the store doesn't carry it.
- **Sign-in tapped while the flag is off** (e.g. it was flipped mid-session): the iPad starts a guest trip.

## 9. Testing
- **Backend (pytest, local Postgres):**
  - each pick rule (event, due, usual, deal), the 3-pick cap, and leaving out items on the plan or out of stock;
  - unknown ids create members;
  - the flag-off refusal;
  - the receipt trigger copies lines once (idempotent checkout);
  - a trip change clears the member;
  - forget one / forget all;
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
  - a UI test of the full beat on the mock backend.
- **End to end:** local Supabase, then hosted on a throwaway cart and `it-` member: sign in → remember an event → checkout → new trip → the profile shows the event and the new purchases.

## 10. Ownership and coordination
- **Recommendation for the manager's call:** this chat builds the whole slice in its **own git worktree** (branch `member-memory`), so it never collides with the iPad and backend chats' live edits in the main checkout.
  - Almost everything is new files. The hooks into shared files are small and listed in §5.
  - Once all tests pass, the manager merges it, bumps the contract to v0.14 (§5 is the proposal), and tells the owners.
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
