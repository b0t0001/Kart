# KART end-to-end demo plan

> **FINAL SCRIPT (2026-10-24): one natural trip. This supersedes §3 Meal A below.**
>
> **Props (bought 2026-10-24, one of each):** Barilla spaghetti, Good & Gather marinara, Market Pantry grated Parmesan, up&up kids' scissors. Not bought: garlic bread (removed by voice) and olive oil (not sold at Target Berkeley Central, and not in our catalog).
>
> | # | Shopper | Kart / cart | Shows |
> |---|---|---|---|
> | 0 | *(member beta)* Sign in as **Dylan** | "Welcome back, Dylan!" | Member sign-in (one trip) |
> | 1 | "Pasta night for my family of 4." → "Not now." | Lists spaghetti, marinara, garlic bread; "First stop is Aisle 6 for the spaghetti." → "One deal goes with your list. Want to hear it?" → "I'll tell you at the shelf." | Voice planning |
> | 2 | "We've got garlic bread at home, take it off." | "Took garlic bread off your list." | Remove by voice |
> | 3 | "Oh, and Leo needs kids' scissors for school." | "Added kids' scissors, Aisle 9." (across the store, routed after the pasta) | Add by voice, a non-food item, **navigation across the store** |
> | 4 | Drop **spaghetti** → "Yes" → drop the **Parmesan** | "Got the Spaghetti. Parmesan is $1 off in Aisle 4. Want it?" → bill shows "saved $1" | Live bill + deal at the moment of decision |
> | 5 | Drop the **marinara**. "Add olive oil too." | "Got the Marinara." → "We don't carry olive oil here. Trader Joe's, about a mile away, might have it." (exact store per Kart) | Honest "not sold here" |
> | 5b | *(member beta)* "Oh, next Saturday is Leo's soccer team party, we'll need pasta for 12." → "Yes." | "Got it, I'll remember Leo's party on Saturday. Want me to save a list for it?" → "Saved: three boxes of spaghetti and two jars of marinara for Leo's party." | **Memory created by conversation** |
> | 6 | Walk to Aisle 9, drop the **scissors** → "Actually, the school has some" → **take them back out** | "Got the Kids' Scissors." → "Took the Kids' Scissors off your bill. Take them off the list too?" → "Yes." | Changing your mind |
> | 7 | Tap **Check out** → **Pay** | Receipt with savings and time in store → "Paid. Enjoy pasta night!" | Uniqlo-style checkout |
>
> **ACT 2: fast-forward (member beta, ~30 s, no extra props)**
> | # | Shopper | Kart / cart | Shows |
> |---|---|---|---|
> | 8 | Demo controls → **"Fast-forward to Friday"** (new trip, the date jumps ahead) → sign in as **Dylan** | **"Welcome back, Dylan! Leo's soccer party is tomorrow. Want the list you saved?"** | Memory kept across trips |
> | 9 | "Yes." | The saved list goes on today's plan with the first stop | A ready-made list from memory |
> | 10 *(optional)* | "What do you know about me?" | The memory sheet opens on the iPad, with **Forget** buttons | Privacy and control |
>
> Leo's party is **not** pre-seeded: it's created live in step 5b. Only the background purchase history is seeded.
>
> **Q&A only:** drop a water bottle → the "Is this…?" card (what happens if the camera is unsure).

> **2026-10-24 — ONE end-to-end demo: Meal A (pasta night for 4) only.** Meal B (nachos) is **dropped from the demo**. Kart still plans it if a judge asks, but we don't buy or rehearse it. Shopping list = spaghetti ×3, marinara ×1, Parmesan shaker ×1 (~$12 at Target, all in Aisle A12). See [TARGET_SHOPPING_CHECKLIST.md](TARGET_SHOPPING_CHECKLIST.md).


The single source for **what we buy, how each item is set up in the catalog, and exactly where it appears in the demo.** It covers two shelf-stable meals and nothing that needs a fridge. Owned by the manager; the backend runbook (`backend/docs/DEMO.md`) follows this script.

**Meals:**
- **A. "Pasta night for my family of 4"**: the headline, about 90 s.
- **B. "Game-night nachos for 6"**: the quick second meal, about 30 s, shown if time allows or on request.

---

## 1. The shopping list (~9 items, ~$29 at Target Berkeley Central; all in stock per target.com, 2026-10-24)

The exact Target products, with their **real Target aisle** (for the demo video) and **mini-store aisle** (for the live table demo). The in-store checklist is in [TARGET_SHOPPING_CHECKLIST.md](TARGET_SHOPPING_CHECKLIST.md). If you substitute, note the brand and size: the cameras need an accurate description of each package.

| # | Buy at Target | Qty | Catalog id | Target aisle / Mini aisle | Role in the demo |
|---|---|---|---|---|---|
| 1 | **Barilla Spaghetti Pasta, 16 oz** ($1.99) | **3** | `barilla-spaghetti` | **A12** / A6 Pasta & Sauce | **Meal A:** box 1 = the item that starts the bill; box 2 = the **"too much" nudge** (beta); box 3 = spare, and **counting** clips (2 boxes dropped together) |
| 2 | **Good & Gather Marinara Pasta Sauce, 23 oz** ($2.19; glass, so place it) | 1 | `rao-marinara` *(id kept)* | **A12** / A6 Pasta & Sauce | **Meal A:** on the list (spaghetti or marinara, whichever goes in first, triggers the Parmesan card) |
| 3 | **Market Pantry Grated Parmesan Cheese, 8 oz shaker** ($4.19) | 1 | `kirkland-parmesan` *(id kept)* | **A12** / A4 Cheese & Deli | **Meal A: the headline deal**, "Parmesan is $1 off in Aisle 4. Want it?" → "yes" → drop it |
| 4 | **Tostitos Original Restaurant Style Tortilla Chips, 12 oz** ($4.59) | 1 | `tostitos-chips` | **A6** / A7 Snacks & Chips | **Meal B: the second deal card**, "Chips are $1.50 off". Big, light, safe to drop |
| 5 | **Good & Gather Mild Restaurant Style Salsa, 16 oz** ($2.99; only 1 left, backup: G&G Mild Chunky 24 oz) | 1 | `tostitos-salsa` *(id kept)* | **A12** / A5 Mexican | **Meal B:** dropping it **triggers the chips deal** |
| 6 | **Tostitos Salsa Con Queso Medium Dip, 15 oz** ($5.19) | 1 | `queso` **(new)** | **A6** / A5 Mexican | **Meal B:** on the list. Also pairs with the chips deal |
| 7 | **Good & Gather Black Beans, 15.5 oz can** ($0.99) | 1 | `black-beans` **(new)** | **A12** / A5 Mexican | **Meal B:** on the list. A can: a small, cylindrical, drop-safe item |
| 8 | **Market Pantry Hot Sliced Jalapeño, 12 oz** ($2.29) | 1 | `jalapenos` **(new)** | **A12** / A5 Mexican | **Meal B:** on the list. Small-item test |
| 9 | *(optional)* **Old El Paso Taco Seasoning, Original, 1 oz** ($0.99) | 1 | `taco-seasoning` | **A12** / A5 Mexican | **Smallest-item** camera test only. Skip it to save money |

**Not used in the demo:** the apple and the Tide (Dylan, 2026-10-24). The trust moment (an unknown item → "Is this…?") is optional, using any non-catalog item you have on hand.

**Planned by Kart but deliberately NOT bought.** They trigger the **"Before you go: you still need…"** checkout reminder (beta):
| Item | Catalog id | Meal |
|---|---|---|
| Garlic bread / French baguette | `french-baguette` | A |
| Sour cream | `daisy-sour-cream` | B |

Everything else already in the catalog (tacos, breakfast, household) **stays**, so if a judge asks Kart for another meal it still plans sensibly. Those items just never go in the cart.

---

## 2. What the catalog must say (backend sets this up; Dylan confirms after shopping)

| Catalog id | Name (from what you bought) | Spoken name | Price (= shelf price you paid) | Stock (= count bought) | Camera description |
|---|---|---|---|---|---|
| `barilla-spaghetti` | Barilla Spaghetti, 1 lb | Spaghetti | shelf | **3** | blue Barilla box, rectangular, white "Spaghetti" text |
| `rao-marinara` | *(brand)* Marinara, 24 oz | Marinara | shelf | **1** | from the jar you bought |
| `kirkland-parmesan` | Grated Parmesan, 8 oz shaker | Parmesan | shelf | **1** | green cylindrical shaker can, yellow/red label |
| `tostitos-chips` | Tortilla Chips, party size | Tortilla Chips | shelf | **1** | large crinkly bag |
| `tostitos-salsa` | *(brand)* Salsa, 15–16 oz | Salsa | shelf | **1** | from the jar you bought |
| `queso` | Salsa con Queso, 15 oz | Queso | shelf | **1** | from the jar you bought |
| `black-beans` | Black Beans, 15 oz can | Black Beans | shelf | **1** | short metal can, label photo of beans |
| `jalapenos` | Sliced Jalapeños, can | Jalapeños | shelf | **1** | small can, green label |
| `french-baguette` | French Baguette | Garlic Bread | 2.99 | 25 (not bought; stock stays so it's plannable) | — |
| `daisy-sour-cream` | Sour Cream, 16 oz | Sour Cream | 2.99 | 30 (not bought) | — |

**Deals:**
| Deal | On | Shown when these go in | Demo role |
|---|---|---|---|
| `d-parm-3off` *(id kept)* | Parmesan shaker, **$1 off** *(scaled to a ~$5 item)* | spaghetti or marinara | **The headline card (Meal A)** |
| `d-chips-150off` | Chips, $1.50 off | salsa or queso | **Card (Meal B)** |
| `d-baguette-1off` | Garlic bread, $1 off | spaghetti, marinara | Shows on the list row; never bought |

**Kart's lists** (the voice agent is tuned to produce exactly these):
- **A. "Pasta night for 4"** → **spaghetti ×1, marinara ×1, garlic bread ×1** (verified 3/3 runs with the real model). The Parmesan is left for the deal card. Basis: "1 lb serves 4".
- **B. "Game-night nachos for 6"** → **salsa ×1, queso ×1, black beans ×1, jalapeños ×1, sour cream ×1**. The chips are left OFF the list on purpose: cards never show for listed items, so the chips deal card offers them when the salsa or queso goes in.

---

## 3. The demo, step by step (what happens to each item)

**Setup:** cart 7 reset (`reset-demo`, operator only). Quantity nudges on or off as decided. iPad on cart 7. Mini-store aisle signs out: **A4 Cheese, A5 Mexican, A6 Pasta & Sauce, A7 Snacks** (plus A2 Bakery and A8 Dairy for the items we don't buy).

### Meal A: pasta night (headline)
| # | Action | Item | What the cameras do | iPad / bill | Kart says |
|---|---|---|---|---|---|
| 1 | Tap start, say *"Pasta night for my family of 4"* | — | — | List: Spaghetti, Marinara, Garlic Bread; next stop A6 | "Pasta night for four… spaghetti, marinara and garlic bread. First stop is aisle 2 for the garlic bread." (The presenter heads to pasta in Aisle 6; garlic bread is deliberately skipped) |
| 1b | Kart asks *"By the way, one deal goes with your list. Want to hear it?"* → say **"Not now"** | — | — | — | Skips the deal walk-through. **The deal is still spoken at the shelf** (step 3) — Dylan's rule: "not now" = tell me at the shelf |
| 2 | Drop **spaghetti box 1** | `barilla-spaghetti` | settle → identify (local match, ~1.5 s) → 1 add | Bill: Spaghetti $x; list row ✓; **Parmesan deal card** | "Got the spaghetti." then **"Parmesan is $1 off in Aisle 4. Want it?"** |
| 3 | Say *"Yes"*, drop **marinara** | `rao-marinara` | 1 add | Bill +marinara; Parmesan joins the list with $1 off | "Added Parmesan to your list." |
| 4 | Drop the **Parmesan shaker** | `kirkland-parmesan` | 1 add at the deal price | Bill shows the struck-through price and "saved $1" | "Added the Parmesan." |
| 5 *(optional)* | Drop any **non-catalog item** you have on hand (e.g. a water bottle) | (unknown) | settle → Claude → "unknown" | **"Is this…?" card**; Pay blocked | "I'm not sure what that is. Can you check the screen?" |
| 6 *(optional)* | Tap **"Not this"**, take it out | — | removal resolves it | Card clears | — |
| 7 *(beta)* | Drop **spaghetti box 2** | `barilla-spaghetti` | 1 add (qty 2) | **"Too much" card** | **"That's two boxes of spaghetti in the cart, and pasta night for 4 needs one. Keep the extra?"** |
| 8 *(beta)* | Say *"No"*, take box 2 out | — | 1 remove | Total drops; card clears | "Took the Spaghetti off your bill." |
| 9 | Tap **Check out** | — | — | *(beta)* **"Before you go: you still need garlic bread (Aisle 2)"** | "Before you go: you still need garlic bread for pasta night. Want to grab it?" |
| 10 | Say *"Skip"*, tap **Pay** | — | — | **Receipt:** items, saved $1, time in store | "Paid. Enjoy pasta night!" |

**Without the beta**, skip steps 7–9. The flow still shows the plan, the live bill, the deal at the moment of decision, the unknown-item trust card, and the receipt.

### Meal B: game-night nachos (quick, optional)
| # | Action | Item | Result |
|---|---|---|---|
| 1 | *"Game-night nachos for 6"* | — | List: chips, salsa, queso, black beans, jalapeños, sour cream |
| 1b | Deal offer → **"Not now"** | — | The chips deal is spoken when the salsa goes in (step 2) |
| 2 | Drop **salsa** | `tostitos-salsa` | **"Tortilla Chips are $1.50 off in Aisle 7. Want them?"** |
| 3 | "Yes", drop **chips** | `tostitos-chips` | Deal price on the bill |
| 4 | Drop **queso, black beans, jalapeños** one at a time | `queso`, `black-beans`, `jalapenos` | Each one billed and ticked off |
| 5 *(beta)* | Check out | — | "Before you go: you still need sour cream" |

### Optional extra moments
- **Live store change:** *"queso $1 off"* in the console → a cart holding chips gets the card within a second.

---

## 4. After shopping (in order)

1. **Dylan → manager:** the exact items bought (brand, size, shelf price, count), or a photo of the receipt.
2. **Backend:** sets the catalog to §2 (**ids never change**: only names, sizes and descriptions; 3 new products, the Parmesan shaker, prices, stock = counts, camera descriptions, deals). Applied to hosted without `reset-demo`, and `data/store.json` is updated.
3. **Voice agent / iPad chat:** tunes Kart so §2's two lists come out exactly. Rehearses both meals on a test cart.
4. **James (Pi):**
   - enroll each bought item: `tools/enroll.py <catalog id>`, about 1 minute each, 8 items → about 10 minutes;
   - run `tools/gallery_check.py`;
   - record the identical-spaghetti counting clips.
5. **CV:** replays the clips and reports recognition accuracy for each bought item.
6. **Whole team:** rehearse Meal A three times, on cart 7 or a test cart. Rehearsals use placeholder stock (20).
7. **Right before judging (operator):** one command, `backend/pre_judging.sh` (add `--members` if the member beta ships). It shows the target database and asks you to type `judging`, then sets the real stock counts, resets the demo and seeds the member. See `backend/docs/DEMO.md`.


> **Beta nudges (2026-10-24):** only "Keep the extra?" (too much) and the single "Before you go" checkout list fire. Mid-trip "you're short" nudges are off.

> **Rehearsed with real voice on hosted (2026-10-24, throwaway cart):** Meal A with the beta off and Meal B with the beta on run clean, line for line. Meal A with the beta on is being rerun now that mid-trip nudges are off.
