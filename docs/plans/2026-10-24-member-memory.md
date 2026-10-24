# Member Memory Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** a demo member sign-in. Kart remembers each member's purchases and the plans they mention, recommends what fits "this week", asks one question per trip, and recalls events after a demo fast-forward. All of it sits behind the default-off flag `member_memory`.

**Architecture:**
- **Backend:** one new migration (`07_members.sql`) holds the tables, the flag, RPCs and triggers. The "this week" picks are computed deterministically in `member_profile`.
- **Voice agent:** a new `kart_agent/memory.py` holds the member logic. `agent.py` and `brain.py` get small hooks.
- **iPad:** KartCore gets member models, backend methods and AppModel rules. The views go in a new `Features/Member/`.

**Tech stack:** Postgres/Supabase (plpgsql) with pytest + psycopg; Python 3 agent on Cartesia Line with pytest-asyncio fakes; SwiftUI + the KartCore Swift package (`swift test`), plus XCUITest.

**Spec:** `docs/specs/2026-10-24-member-memory-design.md`. Read it first: section numbers below (§3.4 etc.) refer to it.

## Global Constraints

- **The flag:** `member_memory`, a `feature_flags` row seeded **false** (`on conflict do nothing`); per cart through `carts.features` and the existing `set_feature`. With it off, every existing test passes unchanged and cart outputs match `main`.
- **Additive only:** never rename or drop a column, RPC or contract field. Don't edit existing migration files `01`–`06` (the only exception is `kartdb.py`'s `OUR_TABLES` and `RPC_PARAM_TYPES`).
- **Store timezone:** `America/Los_Angeles`. "Today", a purchase's date and the weekday are always computed in that zone, never in UTC.
- **Demo member:** `1029`, name `Dylan`, household 4. Test members start with `it-`. Tests never touch `1029` or cart `7` on hosted.
- **Fixed lines** (exact copy):
  - welcome: `"Welcome back, {name}!"`; `"Welcome back!"` when there's no name; `"Nice to meet you!"` for a member with no trips and no memories
  - profile failed: `"Welcome back! What are we shopping for today?"`
  - questions: `"By the way, what should I call you?"` when there's no name; otherwise the rotation `["Any fun plans coming up I can help you shop for?", "Anyone coming over soon?", "Got anything coming up, like a party or a holiday?"]`
  - receipt: `"Saved to {name}'s history."`, or `"Saved to your history."` with no name
- **Picks:** at most 3; signal order `event`, `due`, `usual`, `deal`; first one per signal, then fill.
- **Lull:** 40 s with no activity, while shopping, signed in, with no visible card. Once per trip, shared with the "Hey Kart" trigger.
- **Hosted:** apply additive migrations only, never run `reset-demo`, and test on throwaway carts (`it-mem-*`) and `it-` members.
- **Branch:** work in the worktree `.claude/worktrees/member-memory`, on branch `member-memory`. Merge `main` into it before each part (backend, agent, iPad) and before the end, never rebase. Commit only on this branch.
- **Env and venvs:** export `KART_ENV_FILE=/Users/dylan/Documents/GitHub/kart/.env`. The venvs live in the main checkout: `/Users/dylan/Documents/GitHub/kart/backend/.venv/bin/python` and `/Users/dylan/Documents/GitHub/kart/agent/.venv/bin/python`. The test Postgres runs at `KART_TEST_PG=postgresql://postgres@localhost:54329/postgres`, which is already up.

## Review Focus

1. **Evening demo, UTC rollover.** At 6 pm Pacific on a Saturday it's already Sunday in UTC, but "today" must still be Saturday. Pinned in Task 2: `test_today_uses_store_timezone`.
2. **Demo date moved back to today after future-dated purchases.** History "from the future" must not count: no negative days, no crash. Pinned in Task 2: `test_future_purchases_ignored`.
3. **Kart mishears "forget it" (as in "never mind").** The voice `forget` tool needs a memory id and can't wipe everything. Pinned in Task 6: `test_forget_requires_memory_id`.
4. **Profile RPC slow or failing at the greeting.** The trip must never wait more than 1 s on memory. Pinned in Task 7: `test_profile_timeout_falls_back`.
5. **Signing in on a cart whose flag is off** (e.g. flipped mid-demo). It must start a guest trip, with no error screen. Pinned in Task 11: `testSignInWithFlagOffStartsGuestTrip`.

---

## Part A: Backend (`backend/`)

### Task 0: Worktree

- [ ] **Step 1: Create the worktree.** From `/Users/dylan/Documents/GitHub/kart`, run `git worktree add .claude/worktrees/member-memory -b member-memory main`. Then work in it.
- [ ] **Step 2: Check the baseline.**
  - Run `KART_TEST_PG=postgresql://postgres@localhost:54329/postgres /Users/dylan/Documents/GitHub/kart/backend/.venv/bin/python -m pytest backend/tests -q`.
  - Expected: all pass. Record the count.

### Task 1: Schema, flag, `set_member`, `set_demo_date`, triggers

**Files:**
- Create: `backend/db/07_members.sql`
- Modify: `backend/kartdb.py` (put `"member_memories", "member_purchases", "members"` at the **front** of `OUR_TABLES`, and add to `RPC_PARAM_TYPES`: `p_member_id text`, `p_date date`, `p_today date`, `p_kind text`, `p_event_date date`, `p_trip_id uuid`, `p_memory_id bigint`, `p_items jsonb`)
- Test: `backend/tests/test_members.py`

**Interfaces:**
- Produces:
  - **Tables:**
    - `members(member_id text pk, name text, household int, created_at timestamptz default now())`
    - `member_purchases(id bigserial pk, member_id text not null references members on delete cascade, product_id text not null, qty int not null, price numeric(10,2) not null, bought_at timestamptz not null, trip_id uuid, source text check in ('seed','checkout'))`
    - `member_memories(id bigserial pk, member_id text not null references members on delete cascade, kind text check in ('event','preference','note'), text text not null, event_date date, items jsonb, trip_id uuid, created_at timestamptz default now())`
  - **Columns** added with `add column if not exists`:
    - `carts.member_id text references members(member_id) on delete set null`
    - `carts.member_rev int not null default 0`
    - `carts.demo_date date`
    - `receipts.member_id text`
  - **Functions:**
    - `member_tz() returns text` (immutable) → `'America/Los_Angeles'`
    - `member_today(p_cart_id text) returns date`: the cart's `demo_date`, else `(now() at time zone member_tz())::date`
  - **RPCs:**
    - `set_member(p_cart_id text, p_member_id text) returns carts`
    - `set_demo_date(p_cart_id text, p_date date) returns carts`
  - **Errors:**
    - `'feature_off: member_memory'` when `feature_enabled(features, 'member_memory')` is false
    - `'unknown cart: %'`
    - `'bad member id'` unless it matches `^[A-Za-z0-9-]{1,32}$`
  - **Triggers:**
    - `before update on carts` when `old.trip_id is distinct from new.trip_id` → `new.member_id := null`
    - `after insert on receipts` when `new.status = 'paid'` → copy items into `member_purchases`, with `bought_at = now() + (coalesce(demo_date, today) - today) * interval '1 day'` (today in the store zone), `source 'checkout'`; and set `receipts.member_id`
  - **Access:**
    - RLS on the 3 tables, with no policies
    - `revoke all … from anon, authenticated`
    - grant `service_role`, including the sequences
    - `grant execute` on both RPCs to `anon, authenticated, service_role`
    - not in the realtime publication

- [ ] **Step 1: Write failing tests** in `test_members.py`, with a fixture `member_cart(cart)` that does `cart("set_feature", p_feature="member_memory", p_on=True)`. Tests:
  - `test_flag_seeded_off_and_set_member_refuses`: the flag default is `False`; `set_member` on cart 7 raises a `psycopg.errors.RaiseException` matching `feature_off: member_memory`.
  - `test_set_member_creates_unknown_member`: `set_member(p_member_id="it-1")` returns a row with `member_id == "it-1"`, and `members` has `it-1` with `name is None`.
  - `test_bad_member_id_rejected`: `"it 1; drop"` raises.
  - `test_new_trip_clears_member_keeps_demo_date`: set the member and `set_demo_date(p_date="2026-10-30")`, then `reset_cart`. Now `member_id is None` and `demo_date == "2026-10-30"`.
  - `test_checkout_copies_purchases_once_with_demo_date`:
    - add spaghetti ×2 and milk; set the demo date 6 days ahead; `checkout` twice.
    - `member_purchases` has exactly 2 rows (qty 2 and 1, source `checkout`); `bought_at` in the store zone is 6 days after today; `receipts.member_id == "it-1"`; `receipts.created_at` is today.
  - `test_guest_checkout_writes_no_purchases`: with the flag on but no member, `member_purchases` is empty after checkout.
- [ ] **Step 2: Run** `pytest backend/tests/test_members.py -q`. Expected: FAIL (`set_member` doesn't exist).
- [ ] **Step 3: Implement `07_members.sql` and the `kartdb.py` additions.** Copy the grant and RLS style from `06_analytics.sql`, and the flag insert from `01_schema.sql`.
- [ ] **Step 4: Run** `pytest backend/tests -q`. Expected: the new tests pass, plus every earlier test.
- [ ] **Step 5: Commit** `backend: member memory schema, set_member, demo date (beta, flag off)`.

### Task 2: `member_profile` (the "this week" picks)

**Files:**
- Modify: `backend/db/07_members.sql`
- Test: `backend/tests/test_members.py`

**Interfaces:**
- Consumes: Task 1.
- Produces: `member_profile(p_member_id text, p_cart_id text default null, p_today date default null) returns jsonb`. The shape is spec §5.1.
  - "today" is `coalesce(p_today, member_today(p_cart_id), (now() at time zone member_tz())::date)`.
  - `"weekday"` is a full English name.
  - `memories[].event_date` and `last_trip.date` are `YYYY-MM-DD`.
  - Unknown member → `null`.
  - Grant execute to anon.

**Rules** (purchases with a store-zone date after "today" are ignored everywhere):
- **A trip** is one distinct purchase date.
- **Product stats:**
  - `times` = the number of trips it was bought on;
  - `last` = its latest date;
  - `every_days` = the median gap between its dates, rounded (null if `times < 2`).
- **Taken:** a product on the cart's `items` or `plan` (when `p_cart_id` is given). Picks skip taken products and anything not `in_stock` in `product_catalog`.
- **Candidates by kind:**
  - **event:** memories of kind `event` with `event_date` in `[today, today+14]` and saved items, nearest date first. The candidate is each saved item in order. Each pick carries `memory_id`.
  - **due:** `times >= 3` and `today - last >= 0.85 * every_days`, ordered by `(today-last)/every_days` descending.
  - **usual:** today's weekday has `>= 2` member trips, and the product was bought on `>= 60%` of them. Ordered by share, then `times`.
  - **deal:** among the top 5 by `times` (ties: later `last`), those with a non-null `deal_label` in `product_catalog`.
- **Selection:**
  1. Take the first untaken candidate of each kind, in the order event, due, usual, deal.
  2. Fill up to 3 by repeating that kind order over the remaining candidates.
  3. A product appears once.
- **`reason` text:**
  - **event:** `"{label} · {when}"`.
    - `label` = the part of the memory text before the first comma, at most 28 chars.
    - `when`: 0 days → `today`; 1 → `tomorrow`; 2–6 → a weekday abbreviation such as `Sat`; otherwise `Oct 31`.
  - **due:** `"{every} · last {when}"`.
    - `every`: 6–8 days → `every week`; 13–15 → `every 2 weeks`; 27–31 → `every month`; otherwise `every N days`.
    - `when`: 7 days ago or fewer → a weekday abbreviation; otherwise `Oct 17`.
  - **usual:** `"your {Weekday} usual"`.
  - **deal:** `"a favorite"`.
  - Any pick with a live deal appends `" · {deal_label}"`.
- **`usuals`:** the top 6 by `times` with `times >= 2`. `weekday` is the product's most common weekday if that weekday holds ≥ 60% of its trips, else null.
- **`memories`:**
  - All rows, each with `days_until` (null for non-events) and `items` expanded with `short_name`.
  - Upcoming and recent events (`days_until >= -7`) come first, by date, then the rest by `created_at` descending.
- **`last_trip`:** the latest date's items as `short_name`s, plus `total` = Σ price × qty. Null when there are no trips.
- **`member`:** `since` = `created_at` as a date; `trips` = the number of trips.

- [ ] **Step 1: Write failing tests.** Use a helper `buy(conn, member, product_id, days_ago, qty=1, today=TODAY)` that inserts a purchase at noon store time. Set `TODAY = date(2026, 10, 24)` (a Saturday) and pass it as `p_today`. Tests:
  - `test_due_pick_weekly_milk`: milk bought 7, 14, 21 and 28 days ago → a pick `{"product_id": "whole-milk", "kind": "due", "reason": "every week · last Sat"}`.
  - `test_usual_pick_on_weekday`: tortillas on 3 of 3 Saturdays → kind `usual`, reason `"your Saturday usual"`.
  - `test_event_pick_with_deal_label`: memory `"Leo's soccer party, bringing snacks for 12"`, dated TODAY+1, items `[{"product_id": "tostitos-chips", "qty": 3}]` → the first pick has reason `"Leo's soccer party · tomorrow · $1.50 off"` and its `memory_id`.
  - `test_mix_one_per_signal_then_cap_3`: event + 2 due + 1 usual → kinds `["event", "due", "usual"]`.
  - `test_picks_skip_plan_and_cart_and_out_of_stock`.
  - `test_today_uses_store_timezone`:
    - Insert a purchase at `2026-10-25 01:30+00`, which is 6:30 pm Saturday Pacific, and call the profile with `p_today="2026-10-24"`.
    - Expect `last_trip.date == "2026-10-24"` and `member.trips == 1`.
    - Bucketing in UTC would date it the 25th and drop it as "future".
  - `test_future_purchases_ignored`: a purchase at TODAY+3 doesn't change `last` or `trips`.
  - `test_demo_date_moves_today`: set the cart's demo date to TODAY+6 → `profile.today == "2026-10-30"`, and the event dated TODAY+7 shows `days_until == 1`.
  - `test_recent_past_event_listed_first`: an event 2 days ago comes before preferences, with `days_until == -2`.
  - `test_unknown_member_is_null`.
- [ ] **Step 2: Run** them. Expected: FAIL.
- [ ] **Step 3: Implement `member_profile`** in plpgsql, using CTEs per stat. Format dates with `to_char(d, 'Dy')`, `to_char(d, 'FMDay')` and `to_char(d, 'Mon FMDD')`.
- [ ] **Step 4: Run** `pytest backend/tests -q`. Expected: all pass.
- [ ] **Step 5: Commit** `backend: member_profile, this week's picks (beta)`.

### Task 3: `member_remember`, `member_save_for_later`, `member_forget`

**Files:**
- Modify: `backend/db/07_members.sql`
- Test: `backend/tests/test_members.py`

**Interfaces:**
- Produces:
  - `member_remember(p_member_id text, p_kind text, p_text text, p_event_date date default null, p_trip_id uuid default null) returns jsonb`
    - **Row kinds** `event`, `preference` and `note` return `{id, kind, text, event_date}`.
    - **`name`** sets `members.name` (trimmed, ≤ 40 chars). **`household`** expects digits and sets `members.household`. Both return `{kind, text}`.
    - **Errors:** an unknown kind raises `bad kind`; an empty text raises; an unknown member raises `unknown member`.
  - `member_save_for_later(p_member_id text, p_memory_id bigint, p_items jsonb) returns jsonb`
    - Items are `[{product_id, qty}]` and merge into `items` by `product_id` (the new qty wins).
    - It returns the memory in profile shape, with items carrying `short_name`.
    - **Errors:** `unknown product: %`, `not your memory` (wrong member), `not an event`.
  - `member_forget(p_member_id text, p_memory_id bigint default null) returns jsonb`
    - With an id it deletes that memory and returns `{"forgotten": 1}` (0 if it wasn't found).
    - With null it deletes the member row (which cascades) and returns `{"forgotten": "all"}`.
  - **Side effect:** each of the three bumps `carts.member_rev` on carts with that `member_id`. Forgetting everything leaves those carts at `member_id = null` through the foreign key.
  - **Access:** grant execute to anon.

- [ ] **Step 1: Write failing tests:**
  - `test_remember_event_then_profile_lists_it`
  - `test_remember_name_and_household_update_member`
  - `test_save_for_later_merges_and_rejects_unknown`
  - `test_save_for_later_rejects_other_members_memory`
  - `test_forget_one`
  - `test_forget_all_signs_cart_out`
  - `test_writes_bump_member_rev`
- [ ] **Step 2: Run.** Expected: FAIL.
- [ ] **Step 3: Implement** the three RPCs.
- [ ] **Step 4: Run** `pytest backend/tests -q`. Expected: all pass.
- [ ] **Step 5: Commit** `backend: remember, save for later, forget (beta)`.

### Task 4: Demo seed CLI and docs

**Files:**
- Create: `backend/members.py`
- Modify: `backend/README.md` (a "Member memory (BETA)" section, like the nudges one)
- Modify: `backend/docs/DEMO.md` (the seed step and the fast-forward beat from spec §2)
- Test: `backend/tests/test_members.py`

**Interfaces:**
- Produces:
  - **CLI:**
    - `python backend/members.py seed [--member 1029] [--name Dylan] [--household 4] [--today YYYY-MM-DD]`
    - `python backend/members.py show <member_id> [--cart 7]`
  - **Library:** `seed_member(conn, member_id: str, name: str, household: int, today: date) -> dict` (counts).

**What the seed holds:**
- It deletes and recreates only that member. No other rows change.
- **Trips:** 10 weeks of trips on `today`'s weekday (offsets 7, 14, …, 70 days), plus midweek top-ups 3 days after every other trip. All at 11:00 store time. Uses `random.Random(1029)`.
- **The usual-day basket** (each line's chance per trip):
  - `mission-tortillas` 1.0, `ground-beef` ×2 at 0.9, `tillamook-mexican-cheese` 0.8, `tostitos-salsa` 0.9, `tostitos-chips` 0.9, `avocados` 0.7, `daisy-sour-cream` 0.6
  - plus `whole-milk` and `bananas` on every trip
- **Every ~10 days:** `large-eggs`.
- **Top-ups, alternating:** `barilla-spaghetti` + `rao-marinara` on the first, `french-baguette` on the next.
- **Every 35 days:** `kirkland-paper-towels`.
- **Prices:** today's `products.price`.
- **Memories:**
  - event `"Leo's soccer party, bringing snacks for 12"`, dated today+1, with items `[{"product_id":"tostitos-chips","qty":3},{"product_id":"tostitos-salsa","qty":2}]`
  - preference `"Likes Rao's sauce, not the store brand"`
- **Missing products:** any product id not in `products` is skipped, with a warning (the catalog is churning).

- [ ] **Step 1: Write a failing test,** `test_seed_member_makes_the_demo_profile`: `seed_member(conn, "it-seed", "Dylan", 4, TODAY)`, then `member_profile(p_today=TODAY)`. Expect:
  - `member.name == "Dylan"` and `member.trips >= 15`;
  - pick kinds include `event` (chips, "tomorrow") and `due` (`whole-milk`);
  - at least one `usual`;
  - re-running the seed leaves the counts unchanged.
- [ ] **Step 2: Run.** Expected: FAIL.
- [ ] **Step 3: Implement** `members.py` (argparse with `--db-url`, plus `kartdb.load_env`/`db_url`/`connect`, as in `db.py`) and both docs.
- [ ] **Step 4: Run** `pytest backend/tests -q`, then:
  ```bash
  python backend/members.py seed --member it-local --today 2026-10-24 --db-url postgresql://postgres@localhost:54329/kart_test && python backend/members.py show it-local --db-url postgresql://postgres@localhost:54329/kart_test
  ```
  Expected: tests pass, and `show` prints three picks.
- [ ] **Step 5: Commit** `backend: members.py demo seed (Dylan, 1029) and docs`.

### Task 5: Flag-off proof

**Files:**
- Create: `backend/tests/snapshot_trip.py`. A script, not collected by pytest: it applies the migrations to a fresh database (named by an argument), runs a fixed RPC sequence on cart `snap`, and prints each returned cart row as sorted JSON, with `trip_id`, `*_at`, `updated_at`, `event_id` and `id` removed, and the keys `member_id`, `member_rev` and `demo_date` dropped.
- **The RPC sequence:** `reset_cart`, `set_plan` (tacos for 4), adding 6 items including a duplicate, `remove`, `set_location A9`, `set_cart_status checkout`, `checkout`.

- **Arguments:** the script takes `--backend <dir>` (whose `db/` to apply) and `--db <name>`, and creates the database through `KART_TEST_PG`.
- [ ] **Step 1: Run on `main`.** Make a temporary worktree of `main` in the session scratchpad (`git worktree add <scratch>/kart-main main`). Run the script with `--backend <scratch>/kart-main/backend --db kart_snap_main` and save the output to `<scratch>/snap-main.json`.
- [ ] **Step 2: Run on this branch.** Run it with `--backend backend --db kart_snap_branch` and save to `<scratch>/snap-branch.json`.
- [ ] **Step 3: Compare.** Run `diff <scratch>/snap-main.json <scratch>/snap-branch.json`. Expected: empty. Then run `git worktree remove <scratch>/kart-main`.
- [ ] **Step 4: Commit** `backend: flag-off snapshot script (member memory)`.

## Part B: Voice agent (`agent/`)

Merge `main` into the branch first. `agent.py`, `brain.py` and the tests change often.

### Task 6: `kart_agent/memory.py`

**Files:**
- Create: `agent/kart_agent/memory.py`
- Modify: `agent/kart_agent/tools.py`: at the top of `_dispatch`, `if name in MEMBER_TOOL_NAMES: return await member_dispatch(name, args, ctx)`
- Test: `agent/tests/test_memory.py`

**Interfaces:**
- Produces, in `memory.py`:
  - **`MEMBER_TOOLS: list[dict]`**, built with `tools._tool`, eager streaming:
    - `remember(kind: enum[event, preference, note, name, household], text: str, date?: str YYYY-MM-DD)`: "Save something worth knowing on future trips: a coming event (with its date), a lasting preference, their name, how many people are in the household. Not small talk."
    - `save_for_later(memory_id: int, items: [{product_id, qty}])`: "Put store products on a saved list for a coming event, not on today's list."
    - `forget(memory_id: int)`: "Forget one memory the shopper asked you to forget."
  - **`MEMBER_TOOL_NAMES = {"remember", "save_for_later", "forget"}`**
  - **`async member_dispatch(name, args, ctx) -> dict`.** `ctx` holds `backend`, `member_id`, `trip_id` and `cart_id`.
    - It calls the RPCs `member_remember` (`p_event_date` from `date`), `member_save_for_later` and `member_forget`.
    - **`forget`** raises `ValueError("'memory_id' must be an integer")` when the id is missing.
    - **Errors:** a missing `member_id` raises `ValueError("no member is signed in")`.
    - **Success:** it sets `ctx["memory_changed"] = True`.
  - **`member_section(profile: dict) -> str`**: one text block, starting `"About this shopper, from Kart's memory (today is {weekday}, {today}):"`. It covers:
    - the name and household;
    - upcoming events (with dates, `days_until`, saved items and memory ids);
    - recent past events (with "you may ask how it went");
    - preferences;
    - usuals (with "every N days, usually {weekday}");
    - this week's picks with their reasons;
    - the last trip.
    It is followed by `MEMBER_RULES`.
  - **`MEMBER_RULES: str`**: the spec §5.2 prompt rules, plus:
    - work dates out from today above;
    - when they share a future plan, call `remember` with its date, then offer to start a list and use `save_for_later` (never `set_plan`) for it;
    - say plainly what the store doesn't carry;
    - if a memory tool returns an error, say you couldn't save it, and never claim you'll remember;
    - "shop my Friendsgiving list" = `add_to_plan` for each saved item.
  - **`welcome_line(profile: dict | None) -> str`:** the fixed lines in Global Constraints.
  - **`GREETING_TURN: str`:** `'(The shopper just signed in, and Kart already said "{welcome}". Add at most two short sentences that use the most relevant memory, then ask what they\'re shopping for. Don\'t welcome them again.)'`
  - **`question(profile: dict | None, n: int) -> str`:** the fixed questions; `n` picks from the rotation.
  - **`only_greeting(text: str) -> bool`:**
    - True for "hey kart", "hi kart", "hey cart", "hello kart", "hey", "hi", "hello", "kart", "hey there", in any case, with trailing punctuation.
    - False for "hey kart where's the milk".

- [ ] **Step 1: Write failing tests:**
  - `test_member_section_mentions_events_and_today`
  - `test_welcome_lines` (all 3 cases + None)
  - `test_question_asks_name_first_then_rotates`
  - `test_only_greeting` (a table of positives and negatives)
  - `test_remember_calls_rpc_with_member` (via `FakeBackend.calls`)
  - `test_forget_requires_memory_id`
  - `test_member_tools_need_a_member`
- [ ] **Step 2: Run** `/Users/dylan/Documents/GitHub/kart/agent/.venv/bin/python -m pytest tests/test_memory.py -q` from `agent/`. Expected: FAIL.
- [ ] **Step 3: Implement** `memory.py` and the dispatch line.
- [ ] **Step 4: Run** the whole agent suite. Expected: all pass.
- [ ] **Step 5: Commit** `agent: member memory helpers and tools (beta)`.

### Task 7: Wire members into the agent and brain

**Files:**
- Modify: `agent/kart_agent/brain.py`
  - `respond` streams with `tools=self.tools`.
  - Add `self.tools = TOOLS` and `set_member(section: str | None)`, which recomposes the system prompt as `base + catalog text + (section or "")` and sets `tools = TOOLS + MEMBER_TOOLS` when there's a section, else `TOOLS`.
  - `set_catalog` keeps the member part.
- Modify: `agent/kart_agent/agent.py`, small hooks only (as follows).
- Test: `agent/tests/test_agent_member.py`, plus one case in `agent/tests/test_ipad_contract.py`.

**Interfaces:**
- **Consumes:** Task 6.
- **iPad events, read by the agent:**
  - `trip_context` may carry `member_id`.
  - New custom event `{"type": "lull"}`.
- **State in `KartAgent`:**
  - `member_id: str | None`
  - `_profile: dict | None`
  - `_asked: bool`
  - `_questions: int`
  - `_question: str | None`, the asked-but-unanswered lull question
  - A new trip id resets `_profile`, `_asked` and `_question`. A `trip_context` without `member_id` sets `member_id = None`.
- **`async _load_profile() -> None`:**
  - `backend.rpc("member_profile", p_member_id=…, p_cart_id=cart_id)`, with `asyncio.wait_for` at **1.0 s**.
  - On success: `brain.set_member(member_section(profile))`.
  - On a failure or timeout: `_profile = None`, and `brain.set_member` gets just a short "a member is signed in" section with no facts.

**Hooks:**
- **`CallStarted`:**
  - Guest: unchanged.
  - Member, when there's no plan or items yet:
    1. load the profile;
    2. say `welcome_line(profile)` with `interruptible=False` (or the profile-failed line, and stop there);
    3. stream `brain.respond(GREETING_TURN.format(welcome=…), ctx)` through `_say` without captioning the user side, with `interruptible=self.barge_in`.
- **`UserTurnEnded`, member and nothing asked:**
  - **A bare "Hey Kart"** (`only_greeting`) and not `_asked`:
    1. caption the user line;
    2. say `question(profile, _questions)`;
    3. `brain.remember(text, q)`;
    4. `_asked = True`.
  - **Otherwise, a pending `_question`:** prefix the text as `(Kart just asked: "{q}") {text}` and clear `_question`.
  - **On every Claude turn:**
    - `ctx` gains `member_id`;
    - after it, if `ctx.get("memory_changed")`, reload the profile.
- **Lull (`run_filter`):**
  - Returns True only for a member who hasn't been asked, while Kart isn't speaking and there's no open offer, nudge or digest. Otherwise False.
  - `process` then says the question (`interruptible=False`) and sets `_asked = True` and `_question = q`.

- [ ] **Step 1: Write failing tests.** Use a `MemberBackend(FakeBackend)` subclass whose `rpc` answers `member_profile` with a fixture (and an optional delay), and records member RPCs. Tests:
  - `test_guest_greeting_unchanged` (no `member_id` → `[GREETING]`)
  - `test_member_greeting_fixed_line_then_claude` (the first said line is `"Welcome back, Dylan!"`; the LLM request's system has `"About this shopper"`; its tools include `remember`)
  - `test_profile_timeout_falls_back` (a 2 s delay → said `["Welcome back! What are we shopping for today?"]`, in under 1.5 s)
  - `test_hey_kart_asks_once_per_trip` (the second "hey kart" goes to Claude)
  - `test_lull_asks_when_idle_and_prefixes_answer` (the LLM's last user message starts with `(Kart just asked: "Any fun plans`)
  - `test_lull_ignored_for_guest_or_after_asked`
  - `test_memory_write_reloads_profile` (Claude calls `remember` → `member_profile` fetched again)
  - `test_new_trip_resets_question_budget`
  - In `test_ipad_contract.py`: `trip_context` with `member_id`, and `lull`.
- [ ] **Step 2: Run.** Expected: FAIL.
- [ ] **Step 3: Implement** the hooks in `brain.py` and `agent.py`.
- [ ] **Step 4: Run** the whole agent suite. Expected: every earlier test is unchanged and passes, along with the new ones.
- [ ] **Step 5: Commit** `agent: members, a personal greeting, one question per trip, lull (beta)`.

## Part C: iPad (`ios/`)

Merge `main` into the branch first. Run `cd ios && xcodegen generate` after merging.

### Task 8: Contract models and voice events

**Files:**
- Create: `ios/KartCore/Sources/KartCore/Models/Member.swift`
- Modify: `ios/KartCore/Sources/KartCore/Models/Cart.swift`
  - `CartState` gains `memberId: String?`, `memberRev: Int` (default 0) and `demoDate: String?` (`YYYY-MM-DD`), plus `memberMemoryOn: Bool { features["member_memory"] == true }`.
  - Decode them with `decodeIfPresent`, with defaults.
- Modify: `ios/KartCore/Sources/KartCore/Voice/VoiceSession.swift`
  - `case tripContext(cartId: String, tripId: UUID, memberId: String? = nil)`
  - new `case lull`
- Modify: `ios/KartCore/Sources/KartCore/Voice/LineVoiceSession.swift`
  - The `metadata` for `tripContext` adds `"member_id"` only when it's non-nil.
  - `lull` → `["type": "lull"]`.
  - Fix every `.tripContext` pattern match: `MockAgentBrain`, `MockVoiceSession` and the tests.
- Test: `ios/KartCore/Tests/KartCoreTests/MemberTests.swift`, `LineVoiceSessionTests.swift`

**Interfaces:**
- **Produces** (`Codable, Sendable, Equatable`, decoded with `KartJSON.decoder()`):
  - `MemberProfile { member: MemberInfo; today: String; weekday: String; picks: [MemberPick]; usuals: [MemberUsual]; memories: [MemberMemory]; lastTrip: LastTrip? }`
  - `MemberInfo { memberId: String; name: String?; household: Int?; since: String; trips: Int }`
  - `MemberPick: Identifiable { productId; shortName; kind: Kind (event, due, usual, deal); reason; aisle: String?; dealLabel: String?; memoryId: Int? }`
  - `MemberUsual { productId; shortName; times: Int; everyDays: Int?; last: String; weekday: String? }`
  - `MemberMemory: Identifiable { id: Int; kind: String; text: String; eventDate: String?; daysUntil: Int?; items: [SavedItem]? }`
  - `SavedItem { productId; shortName; qty: Int }`
  - `LastTrip { date: String; items: [String]; total: Decimal }`
  - **Helpers:** `MemberMemory.isUpcoming` (`daysUntil ≥ 0`), `MemberMemory.isPast`, `MemberMemory.title` (the text before the first comma).

- [ ] **Step 1: Write failing tests:**
  - `testProfileDecodesBackendJSON`: a JSON fixture copied from a real `members.py show` output in Task 4, pasted into `Fixtures.swift` as `memberProfileJSON`.
  - `testCartDecodesMemberFields`, with defaults when the fields are absent.
  - `testTripContextMetadataIncludesMemberOnlyWhenSet`.
  - `testLullMetadata`.
- [ ] **Step 2: Run** `cd ios/KartCore && swift test --filter MemberTests`. Expected: FAIL (it doesn't compile).
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** `swift test`. Expected: the whole suite passes.
- [ ] **Step 5: Commit** `ios: member models, member_id in trip_context, lull event`.

### Task 9: Backend protocol and the mock backend

**Files:**
- Modify: `ios/KartCore/Sources/KartCore/Backend/KartBackend.swift`
- Create: `ios/KartCore/Sources/KartCore/Backend/MockMembers.swift`
- Modify: `ios/KartCore/Sources/KartCore/Backend/MockKartBackend.swift`
- Test: `ios/KartCore/Tests/KartCoreTests/MemberTests.swift`

**Interfaces:**
- **Produces, added to `KartBackend`:**
  - `var memberProfile: MemberProfile? { get }`
  - `func signIn(memberId: String) async throws`: `set_member`, then fetch the profile. Throws `KartBackendError.featureOff` when the backend says `feature_off`.
  - `func signOut() async throws`
  - `func refreshMemberProfile() async`: never throws. On failure it leaves `memberProfile` as `nil`.
  - `func forgetMemory(id: Int) async throws`
  - `func forgetMember() async throws`
  - `func setDemoDate(_ date: String?) async throws`
  - `func remember(kind: String, text: String, eventDate: String?, items: [PlanItem]) async throws`: **mock only**, used by the scripted voice in Task 13. Put it on `MockKartBackend` itself, not on the protocol.
- **`MockMembers`:**
  - `static func dylan(today: Date) -> MockMemberStore` holds memories and history. The fixture matches the Task 4 seed in miniature: milk weekly, Saturday tacos, and Leo's party tomorrow with chips ×3 and salsa ×2.
  - `func profile(today: Date, taken: Set<String>, catalog: Catalog) -> MemberProfile` applies the same pick rules and reason strings as Task 2 to its in-memory history. Copy the rules; keep them small.
- **Mock behavior:**
  - Any id other than `1029` signs in as a new, empty member: no name, no history, and an empty profile. It's kept in memory for the session.
  - The member is cleared on `startTrip`.
  - Checkout appends purchases dated at the demo date.
  - `setDemoDate` moves "today".
  - `featureOff` is thrown when `cart.features["member_memory"] != true`.

- [ ] **Step 1: Write failing tests:**
  - `testMockSignInNeedsFlag`
  - `testMockProfilePicksForDylan` (kinds `[event, due, usual]` with exact reasons, e.g. `"Leo's soccer party · tomorrow · $1.50 off"` when the chips deal is live)
  - `testMockStartTripClearsMember`
  - `testMockFastForwardShowsSavedEventAndDueMilk` (remember Friendsgiving at +7 with items, check out with milk, set the demo date to +6, sign in → the first pick is a Friendsgiving item reading "tomorrow", and milk is due with reason `"every week · last Sat"`)
  - `testMockForgetAllSignsOut`
- [ ] **Step 2: Run.** Expected: FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** `swift test`. Expected: pass.
- [ ] **Step 5: Commit** `ios: member memory in the backend protocol and mock`.

### Task 10: Supabase backend

**Files:**
- Modify: `ios/KartCore/Sources/KartSupabase/SupabaseKartBackend.swift`
- Test: `ios/KartCore/Tests/KartSupabaseTests/` (a request-shape test like the existing PostgREST tests), plus a case in `SupabaseKartBackendIT.swift` (runs only with the env it already uses)

**Interfaces:**
- **Consumes:** the Task 9 protocol and the Task 1–3 RPCs.
- **Calls:**
  - `signIn` → `rpc set_member {p_cart_id, p_member_id}`. A PostgREST 400 whose message contains `feature_off` → `.featureOff`.
  - Profile → `rpc member_profile {p_member_id, p_cart_id}`.
  - `setDemoDate` → `rpc set_demo_date`.
  - Forget → `rpc member_forget`.
- **Refetching:** when an applied carts update changes `memberId`, `memberRev` or `demoDate`, call `refreshMemberProfile()`. A null `memberId` clears `memberProfile`.

- [ ] **Step 1: Write failing tests:** `testSignInPostsSetMember`, `testFeatureOffMapsToError`, `testMemberRevChangeRefetchesProfile`.
- [ ] **Step 2: Run.** Expected: FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** `swift test`. Expected: pass.
- [ ] **Step 5: Commit** `ios: member memory over Supabase`.

### Task 11: AppModel rules

**Files:**
- Modify: `ios/KartCore/Sources/KartCore/App/AppModel.swift`
- Test: `ios/KartCore/Tests/KartCoreTests/MemberTests.swift`

**Interfaces:**
- **Produces:**
  - `public func startTrip(memberId: String? = nil) async`
    1. reset (as now);
    2. if `memberId` and `cart.memberMemoryOn`, `try await backend.signIn`; on `.featureOff`, carry on as a guest;
    3. `voice.start`, then `.tripContext(…, memberId: backend.cart.memberId)`.
    The existing no-argument call sites keep working.
  - `retryVoice()` also passes `memberId`.
  - `public var member: MemberProfile?`: the backend's profile, only while `cart.memberMemoryOn && cart.memberId != nil`.
  - `public var forYouPicks: [MemberPick]`: the profile's picks minus anything now on the plan or in the cart. Empty after `dismissForYou()` this trip.
  - `public var savedEvent: MemberMemory?`: the nearest upcoming event with items that aren't all on the plan.
  - `public func addPick(_ pick: MemberPick) async`: reuse the private `addToPlan`, with reason `"for you"`.
  - `public func shopSavedList(_ memory: MemberMemory) async`: append each saved item not on the plan, with its qty and reason `memory.title`, in one `setPlan`.
  - `public func dismissForYou()`
  - `public func lullDue(now: Date) -> Bool`, true when all of these hold:
    - a member is signed in;
    - `status == .shopping`;
    - `visibleCard == nil`;
    - the lull isn't sent yet this trip;
    - `now - lastActivity >= 40`.
  - `public func sendLullIfDue(now: Date)`: sends `.lull` once.
  - `public var demoDateLabel: String?`: `"Fri, Oct 30 · demo date"` when `cart.demoDate` is set, else nil.
  - `public func jumpDemoDate(to target: DemoJump) async`, where `DemoJump` is `.today`, `.plusDays(Int)` or `.dayBeforeNextEvent`. The base date is the current demo date, else the real store-zone today. `.dayBeforeNextEvent` is unavailable (nil target) when no upcoming event is ≥ 2 days away.
  - `public var dayBeforeNextEventAvailable: Bool`
  - `resetLocalTripState` resets the lull-sent and For-you-dismissed flags.

- [ ] **Step 1: Write failing tests** (a mock backend plus `MockVoiceSession` recording sent events):
  - `testSignInThenTripContextCarriesMember` (order: reset, `set_member`, `tripContext(memberId: "1029")`)
  - `testSignInWithFlagOffStartsGuestTrip` (no throw, `tripContext` `memberId` nil, `screen != .welcome`)
  - `testLullOnceAfter40sNotWithCard`
  - `testForYouHidesPicksOnPlanAndAfterDismiss`
  - `testShopSavedListAppendsItems`
  - `testDemoJumpDayBeforeNextEvent`
  - `testDemoDateLabel`
- [ ] **Step 2: Run.** Expected: FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** `swift test`. Expected: pass.
- [ ] **Step 5: Commit** `ios: AppModel sign-in, For you, lull, demo date`.

### Task 12: Views

**Files:**
- Create in `ios/Kart/Features/Member/`:
  - `MemberSignInView.swift`
  - `ForYouCard.swift`
  - `MemberChip.swift`
  - `MemoryView.swift`
  - `DemoDateChip.swift`
- Modify:
  - `ios/Kart/Features/Welcome/WelcomeView.swift`
  - `ios/Kart/Features/Shopping/TripPanel.swift`
  - `ios/Kart/Features/Receipt/ReceiptView.swift`
  - `ios/Kart/Debug/DebugPanel.swift`
  - `ios/Kart/Features/Shopping/ShoppingView.swift` (add a `.task` loop every 5 s calling `model.sendLullIfDue(now: .now)`)

**What each view does** (follow `Theme`, `CardView` styles and spec §3; every control gets an `accessibilityIdentifier` as listed):
- **`WelcomeView`:**
  - When `model.backend.cart.memberMemoryOn`, a secondary capsule `"Member? Sign in"` (`welcome.signIn`) sits under the existing text and presents `MemberSignInView` as a sheet. The whole-screen tap stays "Start shopping".
  - `DemoDateChip` sits at the top when `demoDateLabel != nil`.
- **`MemberSignInView`:**
  - A rounded card with the store name, "Member", the 4 digit slots and "Demo sign-in" in the caption, with a 3×4 keypad (`member.key.0`–`member.key.9`, `member.delete`).
  - The 4th digit calls `startTrip(memberId:)` and dismisses the sheet.
  - `"Shop as guest"` (`member.guest`) is the alternative.
- **`MemberChip`:** an initial-in-a-circle avatar plus the name (`member.chip`). It opens `MemoryView`.
- **`MemoryView`** (a sheet, `memory.sheet`):
  - Sections: "Coming up" (upcoming events with relative dates and saved items), "Likes", "Usually buys" (`reason`-style text built from the usuals) and "Earlier" (past events, dimmed).
  - Each memory row has Forget (`memory.forget.<id>`).
  - The footer has "Sign out" and "Forget me" (`memory.forgetMe`), with a confirmation dialog.
- **`ForYouCard`** (`foryou.card`), at the top of `TripPanel` while `!forYouPicks.isEmpty || savedEvent != nil`:
  - an event line with "Shop it" (`foryou.shopIt`);
  - one row per pick with its reason and a + button (`foryou.add.<productId>`);
  - "Not today" (`foryou.dismiss`).
  - It animates with `Theme.spring`.
- **`TripPanel`:** `MemberChip` and `DemoDateChip` in the header, when present.
- **`ReceiptView`:** the receipt line from Global Constraints, when `member != nil`.
- **`DebugPanel`:**
  - a `Toggle("Member memory (beta)")` next to the nudges toggle, calling `setFeature("member_memory", on:)`;
  - a `Section("Demo date")` with the buttons Today, +1 day, +1 week and "Day before <event title>" (the last shown only when available). Identifiers `debug.date.today`, `debug.date.plus1`, `debug.date.plus7`, `debug.date.beforeEvent`.
- **`DemoDateChip`:** a calendar SF Symbol plus `demoDateLabel`, with a `.contentTransition(.numericText())` flip on change.

- [ ] **Step 1: Build** with `cd ios && xcodegen generate && xcodebuild -scheme Kart -destination 'platform=iOS Simulator,name=iPad Pro 13-inch (M4)' build`. Expected: BUILD SUCCEEDED.
- [ ] **Step 2: Take screenshots** with `scripts/shoot.sh welcome,shopping` using a new scenario `member` (add it to `DemoScenario.swift`: flag on, signed in as Dylan, mock). Check the PNGs in `build/shots/`: the sign-in pill, the For you card and the chip are visible, and nothing overlaps.
- [ ] **Step 3: Commit** `ios: member sign-in, For you card, memory sheet, demo date controls`.

### Task 13: Offline rehearsal (scripted voice) and UI test

**Files:**
- Modify: `ios/KartCore/Sources/KartCore/Voice/MockAgentBrain.swift`
  - With a member in `tripContext`, the greeting is `"Welcome back, Dylan! Leo's soccer party is tomorrow. Want chips and salsa for twelve?"`. After a fast-forward it uses the nearest upcoming event instead: `"Welcome back, Dylan! Friendsgiving's tomorrow, and your list is ready. Want to shop it now?"`.
  - `"hey kart"` → the first question line.
  - `"I'm hosting Friendsgiving next Saturday, ten people"` calls `MockKartBackend.remember(kind: "event", text: "Friendsgiving for 10", eventDate: <today+7>, items: [spaghetti ×3, rao-marinara ×3, french-baguette ×2])` and answers `"Ooh, fun. I'll remember that, and I started a list for it."`.
- Modify: `ios/Kart/Debug/DebugPanel.swift`: add the two utterances to "You say".
- Create: `ios/KartUITests/MemberMemoryTests.swift`
- Test: `MockAgentBrainTests.swift` cases for the three lines.

- [ ] **Step 1: Write the failing UI test** `testMemberBeatOffline`, using the existing `DemoControls` helpers:
  1. Turn the flag on.
  2. `welcome.signIn`, then keys 1, 0, 2, 9 → `foryou.card` exists, and `member.chip` shows "Dylan".
  3. You say "hey kart", then the Friendsgiving line; check out and pay.
  4. Demo date → before the event; sign in again → the `foryou.shopIt` label contains "Friendsgiving".
  5. `member.chip` → `memory.sheet` lists "Leo's soccer party" under Earlier.
- [ ] **Step 2: Run** `xcodebuild test -only-testing:KartUITests/MemberMemoryTests …`. Expected: FAIL.
- [ ] **Step 3: Implement** the scripted lines.
- [ ] **Step 4: Run** the UI test and `swift test`, then `scripts/rehearse.sh`, which must still pass with the flag off. Expected: all PASS.
- [ ] **Step 5: Commit** `ios: offline rehearsal of the member beat`.

## Part D: End to end and handoff

### Task 14: Local Supabase, then hosted, then report

- [ ] **Step 1: Merge `main` into the branch,** then rerun every suite:
  - backend pytest;
  - `merchant/` tests (they share the DB);
  - the agent suite;
  - `swift test`;
  - the Kart UI tests (rehearsal + member);
  - `backend/tests/snapshot_trip.py` against `main` (Task 5).
  Record the counts.
- [ ] **Step 2: Local Supabase.** Run `backend/db.py apply` against local Supabase (`.env`'s LOCAL block, via `--db-url`), then `members.py seed --member it-e2e`. Then:
  - turn the flag on for cart `it-mem-local`;
  - from the iPad Simulator pointed at local Supabase (as in `ios/docs/OVERNIGHT.md`), with `CART_ID` `it-mem-local`, sign in as `it-e2e`;
  - remember an event (`KART_IT=1` agent live test, or the RPC directly);
  - check out, fast-forward, sign in again;
  - check `members.py show it-e2e` shows the event with `days_until 1` and the new purchases.
- [ ] **Step 3: Hosted.** Run `backend/db.py apply` (additive; no `reset-demo`), then `members.py seed --member it-hosted`, then the same check on cart `it-mem-hosted`.
  - **Leave the flag off globally**, and don't seed `1029` (the demo operator does that before judging).
  - Delete `it-hosted` afterwards with `member_forget`.
- [ ] **Step 4: Report to the manager** (SendMessage to `local_9709c9d7-0b42-465c-83b4-9f3afef31131`):
  - the branch `member-memory`;
  - a summary;
  - test counts per suite;
  - the flag-off snapshot diff (empty);
  - the steps Dylan needs: the agent redeploy (`agent/scripts/deploy-line.sh`), plus `members.py seed` and turning the flag on for the demo cart;
  - the final RPC signatures, including `member_forget` returning jsonb.
