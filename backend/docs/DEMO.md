# KART demo runbook: backend and merchant console

Follows `docs/DEMO_PLAN.md` §3, which the manager owns; read it for the whole script. This page
covers the backend side: what each step does to the cart row, the commands, and the fallbacks. All
commands run from the repo root. `P=backend/.venv/bin/python` is shorthand below.

## Before judging

1. **The database:** use the hosted project. If the venue Wi-Fi or hosted fails, use the local stack
   (see "If something fails" below).
2. **The merchant console** on the laptop: `merchant/.venv/bin/python merchant/server.py`, then open
   http://localhost:8090.
3. **Quantity nudges are a MAIN feature** (on by default since 2026-10-24): dropping a 2nd spaghetti
   box on a "pasta night for 4" list gets "That's 2 Spaghetti in the cart, and your list needs 1…
   Keep the extra 1?"; checkout gets the one "Before you go" list. The mid-trip sub-option stays
   off. **Rollback:** a cart opts out with `$P backend/cart.py feature quantity_nudges off` (or the
   iPad switch); everyone with `update feature_flags set enabled_default = false where name =
   'quantity_nudges'`; the code with tag `stable-pre-nudges`.
4. **Pre-judging, demo operator only, before EACH judge group:** `backend/pre_judging.sh` (add
   `--members` if the member-memory beta ships). It asks you to type `judging`, then runs, in order:
   1. `db.py sync-catalog --with-stock`;
   2. `db.py reset-demo`: re-seeds the catalog, clears the merchant change log, and sets cart 7 to
      idle. The iPad goes to Welcome, and the Pi clears its memory;
   3. `db.py judging-stock`: stock = the props Dylan bought (`data/judging_stock.json`): **3
      spaghetti boxes** (one starts the bill, one triggers the "too much for your meal" nudge, one
      spare), and **1 each** of marinara, Parmesan and kids' scissors. A paid trip sells those out, and a
      sold-out Parmesan gets no deal card, so this runs **before every group**. Until pre-judging,
      live stock stays at `store.json`'s placeholders (20);
   4. with `--members` (the member-memory demo): `members.py seed`, and cart 7's `member_memory`
      switch on.

   It ends with one line to eyeball, e.g. `summary · stock: Spaghetti 3, Marinara 1, Parmesan 1, Kids'
   Scissors 1 · cart 7: member_memory on, quantity_nudges on, quantity_nudges_midtrip off · idle,
   layout mini`. Run the summary alone at any time with `$P backend/db.py judging-summary`.

   It affects every team, so nobody else runs it or `reset-demo` on hosted. Rehearsals reset only
   their own cart: `$P backend/cart.py reset --cart <id>`.

## Member memory beat (BETA, only if it ships)

Spec §2. It needs `pre_judging.sh --members`, which seeds member 1029, "Dylan", with ten weeks of history and
no party, and the flag on for cart 7: `$P backend/cart.py feature member_memory on`, or the iPad's demo switch.

**Act 1: memory, made live.** Signed in as Dylan, mid-trip:
1. On Welcome, tap **Member? Sign in** → `1029` → **That's me**.
2. Say: "Oh, next Saturday is Leo's soccer team party, we'll need pasta for 12."
   Kart: "Got it, I'll remember Leo's party on Saturday. Want me to save a list for it?"
3. Say: "Yes." Kart: "Saved: three boxes of spaghetti and two jars of marinara for Leo's soccer team party."
   The Parmesan stays off the list, so its deal card still fires.

**Act 2: the fast-forward.**
1. Open the demo controls (three-finger long press) and tap **Fast-forward to <the day before the party>**. The
   cart's date moves, the trip ends, and the iPad goes back to Welcome, signed out.
2. Sign in as 1029 again. Kart: "Welcome back, Dylan!" and then "Leo's soccer team party is tomorrow. Want the
   list you saved?"
3. Say: "Yes." Kart: "Done, it's on your list. First stop: …" From here the pasta demo carries on as usual.
4. Optional: say "What do you know about me?" to open the memory sheet, where any memory can be forgotten.

Afterwards: **Demo date → Today**. Rehearsals that skip Act 1: `members.py seed --with-party`.

## After the receipt (Dylan's actual purchases)

Edit `data/store.json` with the exact names, sizes, shelf prices and camera descriptions, and set
`stock` to the counts bought. Then apply the names and prices **without** the counts:
`$P backend/db.py sync-catalog`. Through rehearsals, live stock stays at the placeholder 20, because
every paid rehearsal checkout takes items off stock. The real counts go in at pre-judging (step 4).
`sync-catalog` changes things in place: no deletes, and carts and the change log are untouched.

## The final script's route (DEMO_PLAN, top)

The list is Spaghetti, Marinara and Garlic Bread. Garlic Bread is removed by voice; taking it off the
list also means its deal card isn't offered this trip. **Kids' Scissors** (Aisle 9 · Household &
School, the far aisle) is added by voice, and the Parmesan comes from the deal card. Routing always
goes to the **nearest** aisle next (ahead wins a tie). Next stop through the script (tested in
`test_trip.py::test_final_script_route`):

1. Plan → **"Aisle 6 → Spaghetti"**.
2. Spaghetti in → card **"Parmesan is $1 off in Aisle 4. Want it?"**.
3. "Yes" → **"Aisle 6 → Marinara"** (finish this aisle first).
4. Marinara in → **"Aisle 4 → Parmesan, $1 off"** (4 is nearer than 9).
5. 2nd spaghetti box in → "too much" nudge; "No." and the box goes back out: next stop unchanged.
6. Parmesan in → **"Aisle 9 → Kids' Scissors"**.
7. Scissors in → **"All done → Checkout"**; taken back out ("changing your mind") → "Aisle 9 → Kids' Scissors".

So the walk is 6 → 4 → 9. "Where the shopper is" is the aisle of the last item **added** (or "I'm at
aisle 5"); removals, nudge answers and list edits don't move it. The Hershey's bar stays in the catalog (Aisle 7) but is out of the demo.

## Meal A: pasta night for 4 (headline)

The voice agent lists **Spaghetti ×1, Marinara ×1, Garlic Bread ×1**. Parmesan is left off the list
on purpose: **cards only show for items not on the list.**

| # | Step | What the backend does | Cart row the iPad shows |
|---|---|---|---|
| 1 | "Pasta night for my family of 4" | `reset_cart`, then `set_plan` (with `basis`) | plan in walking order; `next_step` **"Aisle 6 → Spaghetti"** (Bakery is the last aisle, Aisle 8, so pasta comes first) |
| 2 | Drop **spaghetti** | `apply_cart_event` (vision) | Spaghetti $1.99 · **suggestion "Parmesan is $1 off in Aisle 4. Want it?"** (pairs with spaghetti *or* marinara, so it doesn't matter which is dropped first) |
| 3 | Drop **marinara** | add | Marinara on the bill; the Parmesan card stays until it's answered |
| 4 | "Yes", drop the **Parmesan** | add at the deal price | $4.19 struck through, now $3.19; `savings` $1.00 |
| 5 | Drop the **apple** | add with `product_id` null, `applied=false` | "Is this…?" card. `checkout` would raise `unresolved_items: 1` |
| 6 | "Not this", apple out | the CV removal carries `p_resolves_event_id` | card clears |
| 7 | *(beta)* spaghetti box 2 | add (qty 2 > plan 1) | `nudge` over: "That's 2 Spaghetti in the cart… Keep the extra 1?" |
| 8 | *(beta)* "No", box 2 out | remove | `nudge` clears on its own (counts match) |
| 9 | **Check out** | `set_cart_status('checkout')` | *(beta)* one combined `nudge`: "Before you go: you still need Garlic Bread." |
| 10 | "Skip", **Pay** | `dismiss_nudge('skip')`, then `checkout` | receipt: items, saved $1.00, trip time |

## Meal B: game-night nachos for 6 (optional, about 30 s)

| # | Step | Result |
|---|---|---|
| 1 | "Game-night nachos for 6" | list: **Salsa, Queso, Black Beans, Jalapeños, Sour Cream**. The chips are left to the deal card (`cart.py plan nachos` matches) |
| 2 | Drop **salsa** (or queso) | **"Tortilla Chips are $1.50 off in Aisle 7. Want them?"** |
| 3 | "Yes", drop the **chips** | deal price on the bill |
| 4 | Drop **queso, black beans, jalapeños** | each billed and ticked off |
| 5 | *(beta)* Check out | "Before you go: you still need Sour Cream." |

## The video shoot (Target Berkeley Central)

1. After the trip, fill `data/layouts/target-berkeley.json`:
   - the real aisle for each product, with the section list to match (ids like `G23`, names like
     `"Aisle G23 · Pasta & Sauce"`, `x` in walking order);
   - the shelf prices paid, under `prices`;
   - `"placeholder": false`.
2. `$P backend/db.py layout target-berkeley`: the cart now guides to the real aisles.
3. After the shoot: Undo that change in the merchant console, or `$P backend/db.py layout mini`. The
   pre-judging reset returns to `mini` anyway.

The iPad's map draws sections from its bundled `store.json`, so it needs to load `sections` and
`store_info` live to show Target's aisles. The text on the iPad (Next stop, aisles on list rows,
cards) already follows the active layout.

## Optional moments

- **New product with zero training:** in the console, "Add Tide detergent, $12.99, household aisle",
  then Confirm. The cameras identify it on the next trip from its description, because CV reads
  `product_catalog`.
- **Live store change:** "Queso $1 off", then Confirm. A cart holding a pairing item gets the card
  within about a second. If queso is already on that shopper's list, the row shows "$1 off" and the
  iPad shows its "New deal" note instead.
- **Analytics:** the console's Store insights shows trips, average basket, and deals taken when
  offered. Test carts are excluded.

## "Not sold here"

`store_info.nearby` (anon-readable) lists Trader Joe's (1885 University Ave, ~1 mi), Berkeley Bowl
(2020 Oregon St, ~1.5 mi), Safeway (1444 Shattuck Pl, ~1.5 mi) and Walgreens (2310 Telegraph Ave,
~0.6 mi). Each has `kind` and `good_for` tags. Kart says a nearby store "might carry it" and never
claims their stock. The same list applies in both layouts.

## If something fails

| Symptom | Do this |
|---|---|
| The cameras miss an item, or bill the wrong one | Fix it on the iPad confirm card, or from the laptop: `$P backend/cart.py add kirkland-parmesan` / `remove …` |
| The merchant chat is slow, errors, or has no API key | `$P backend/cart.py deal queso 1`, the same beat without Claude (logged, can be undone in the console) |
| Checkout says "unresolved items" | Answer the confirm card (Yes / Not this) |
| No deal card | Each deal shows at most once per trip, only when its product is in stock, not in the cart, and **not on the list**. Run `$P backend/cart.py reset` and retry |
| A deal card is missing after rehearsals | **Stock:** checkout takes paid items off stock. With stock = counts bought (1 Parmesan), one paid rehearsal makes it out of stock, and out-of-stock items get no card. Run `reset-demo` (operator) to restore it |
| Prices look odd after the owner's edits | `$P backend/db.py reset-demo` (operator), or Undo in the console |
| Hosted is down or the Wi-Fi is bad | Local stack: `colima start`, then `supabase start --workdir backend`, then `$P backend/db.py apply`. Put the local values in `.env` (see `backend/docs/LOCAL_SUPABASE.md`) and point the iPad and Pi at `http://<laptop LAN IP>:54321` |
| The voice token fails (502) | Check the `CARTESIA_API_KEY` function secret (`backend/deploy_functions.sh`). The iPad's mock voice is the fallback |

## Health check

```bash
merchant/.venv/bin/python merchant/smoke.py           # real Claude: 4 prompts + the live deal beat (a few cents); safe on hosted
backend/.venv/bin/python -m pytest -q backend/e2e     # REST + realtime + merchant beat + nudges, LOCAL stack only
```
**Automated runs on hosted never check out** (that takes items off shared stock). `backend/e2e` and
`simulate_demo.py` refuse a non-local database unless you pass `--allow-hosted`. Only `go_live.sh`
does that, and it ends with `sync-catalog --with-stock` to put the stock back.
