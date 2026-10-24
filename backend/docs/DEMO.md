# KART demo runbook: backend and merchant console

Follows `docs/DEMO_PLAN.md` §3, which the manager owns; read it for the whole script. This page
covers the backend side: what each step does to the cart row, the commands, and the fallbacks. All
commands run from the repo root. `P=backend/.venv/bin/python` is shorthand below.

## Before judging

1. **The database:** use the hosted project. If the venue Wi-Fi or hosted fails, use the local stack
   (see "If something fails" below).
2. **The merchant console** on the laptop: `merchant/.venv/bin/python merchant/server.py`, then open
   http://localhost:8090.
3. **The nudge beta** (if it's on for the demo): `$P backend/cart.py feature quantity_nudges on` (cart
   7), or use the iPad's demo switch.
4. **Pre-judging, demo operator only, once, right before judging:** `backend/pre_judging.sh`
   (add `--members` if the member-memory beta ships). It asks you to type `judging`, then runs, in
   order:
   1. `db.py sync-catalog --with-stock`: the real stock counts from `store.json`;
   2. `db.py reset-demo`: re-seeds the catalog (stock included, so step 1 is belt and braces), clears
      the merchant change log, and sets cart 7 to idle. The iPad goes to Welcome, and the Pi clears
      its memory;
   3. `members.py seed`, with `--members` only.

   It affects every team, so nobody else runs it or `reset-demo` on hosted. Rehearsals reset only
   their own cart: `$P backend/cart.py reset --cart <id>`.

## After the receipt (Dylan's actual purchases)

Edit `data/store.json` with the exact names, sizes, shelf prices and camera descriptions, and set
`stock` to the counts bought. Then apply the names and prices **without** the counts:
`$P backend/db.py sync-catalog`. Through rehearsals, live stock stays at the placeholder 20, because
every paid rehearsal checkout takes items off stock. The real counts go in at pre-judging (step 4).
`sync-catalog` changes things in place: no deletes, and carts and the change log are untouched.

## Meal A: pasta night for 4 (headline)

The voice agent lists **Spaghetti ×1, Marinara ×1, Garlic Bread ×1**. Parmesan is left off the list
on purpose: **cards only show for items not on the list.**

| # | Step | What the backend does | Cart row the iPad shows |
|---|---|---|---|
| 1 | "Pasta night for my family of 4" | `reset_cart`, then `set_plan` (with `basis`) | plan in walking order; `next_step` "Aisle 2 → Garlic Bread, $1 off" from the entrance |
| 2 | Drop **spaghetti** | `apply_cart_event` (vision) | Spaghetti $1.99 · **suggestion "Parmesan is $1 off in Aisle 4. Want it?"** (pairs with spaghetti *or* marinara, so it doesn't matter which is dropped first) |
| 3 | Drop **marinara** | add | Marinara on the bill; the Parmesan card stays until it's answered |
| 4 | "Yes", drop the **Parmesan** | add at the deal price | $4.99 struck through, now $3.99; `savings` $1.00 |
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

## Health check (safe on the shared hosted project)

```bash
backend/.venv/bin/python -m pytest -q backend/e2e     # REST + realtime + merchant beat + nudges, on throwaway carts
merchant/.venv/bin/python merchant/smoke.py           # real Claude: 4 prompts + the live deal beat (a few cents)
```
`simulate_demo.py` drives cart `7`, so on hosted run it only as the operator, or pass `--cart <test id>`.
