# KART end-to-end demo plan

The single source for **what we buy, how each item is set up in the catalog, and exactly where it appears in the demo.** It covers two shelf-stable meals and nothing that needs a fridge. Owned by the manager; the backend runbook (`backend/docs/DEMO.md`) follows this script.

**Meals:**
- **A. "Pasta night for my family of 4"**: the headline, about 90 s.
- **B. "Game-night nachos for 6"**: the quick second meal, about 30 s, shown if time allows or on request.

---

## 1. The shopping list (~9 items, ~$30–40)

Buy the **exact brands and sizes in the table if you can**. If you substitute, note the brand and size: the cameras need an accurate description of each package. Prefer **cans and plastic jars** over glass, because glass breaks when dropped.

| # | Buy (suggested) | Qty | Catalog id | Mini-store aisle | Role in the demo |
|---|---|---|---|---|---|
| 1 | **Barilla Spaghetti, 1 lb** (blue box) | **3** | `barilla-spaghetti` | A6 Pasta & Sauce | **Meal A:** box 1 = the item that starts the bill; box 2 = the **"too much" nudge** (beta); box 3 = spare, and **counting** clips (2 boxes dropped together) |
| 2 | **Marinara, 24 oz, plastic jar** (e.g. Prego Traditional) | 1 | `rao-marinara` *(id kept; renamed to the jar you buy)* | A6 Pasta & Sauce | **Meal A:** dropping it **triggers the Parmesan deal card** |
| 3 | **Grated Parmesan shaker, 8 oz** (Kraft green can) | 1 | `kirkland-parmesan` *(id kept; becomes the grated shaker)* | A4 Cheese & Deli | **Meal A: the headline deal**, "Parmesan is $1 off in Aisle 4. Want it?" → "yes" → drop it |
| 4 | **Tortilla chips, party-size bag** (e.g. Tostitos Restaurant Style, 13 oz) | 1 | `tostitos-chips` | A7 Snacks & Chips | **Meal B: the second deal card**, "Chips are $1.50 off". Big, light, safe to drop |
| 5 | **Salsa, 15–16 oz jar** (plastic if you can find it, e.g. Pace) | 1 | `tostitos-salsa` *(id kept; renamed to the jar you buy)* | A5 Mexican | **Meal B:** dropping it **triggers the chips deal** |
| 6 | **Salsa con queso dip, 15 oz jar** | 1 | `queso` **(new)** | A5 Mexican | **Meal B:** on the list. Also pairs with the chips deal |
| 7 | **Black beans, 15 oz can** | 1 | `black-beans` **(new)** | A5 Mexican | **Meal B:** on the list. A can: a small, cylindrical, drop-safe item |
| 8 | **Sliced jalapeños, small can** (e.g. La Costeña 12 oz) | 1 | `jalapenos` **(new)** | A5 Mexican | **Meal B:** on the list. Small-item test |
| 9 | *(optional)* Taco seasoning packet | 1 | `taco-seasoning` | A5 Mexican | **Smallest-item** camera test only. Skip it to save money |

**Free, already on hand:**
| Item | Catalog id | Role |
|---|---|---|
| **Apple** | *(not in the catalog)* | **Trust moment:** the cameras see something they can't name → the **"Is this…?"** card → "Not this". Checkout is blocked until it's answered |
| **Tide bottle** | *(not in the catalog)*, or added live as `tide` | **Tall item** (billed after the 3 s stillness check). Optionally added live in the merchant console to show **a new product with zero training** |

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
- **A. "Pasta night for 4"** → **spaghetti ×1, marinara ×1, garlic bread ×1**. The Parmesan is left for the deal card. Basis: "1 lb serves 4".
- **B. "Game-night nachos for 6"** → **chips ×1 (party bag), salsa ×1, queso ×1, black beans ×1, jalapeños ×1, sour cream ×1**.

---

## 3. The demo, step by step (what happens to each item)

**Setup:** cart 7 reset (`reset-demo`, operator only). Quantity nudges on or off as decided. iPad on cart 7. Mini-store aisle signs out: **A4 Cheese, A5 Mexican, A6 Pasta & Sauce, A7 Snacks** (plus A2 Bakery and A8 Dairy for the items we don't buy).

### Meal A: pasta night (headline)
| # | Action | Item | What the cameras do | iPad / bill | Kart says |
|---|---|---|---|---|---|
| 1 | Tap start, say *"Pasta night for my family of 4"* | — | — | List: Spaghetti, Marinara, Garlic Bread; next stop A6 | "Pasta night for four… spaghetti, marinara and garlic bread. Head to Aisle 6." |
| 2 | Drop **spaghetti box 1** | `barilla-spaghetti` | settle → identify (local match, ~1.5 s) → 1 add | Bill: Spaghetti $x; list row ✓ | "Got the spaghetti." |
| 3 | Drop **marinara** | `rao-marinara` | 1 add | Bill +marinara; **Parmesan deal card** | **"Parmesan is $1 off in Aisle 4. Want it?"** |
| 4 | Say *"Yes"*, drop the **Parmesan shaker** | `kirkland-parmesan` | 1 add at the deal price | Bill shows the struck-through price and "saved $1" | "Added the Parmesan." |
| 5 | Drop the **apple** | (unknown) | settle → Claude → "unknown" | **"Is this…?" card**; Pay blocked | "I'm not sure what that is. Can you check the screen?" |
| 6 | Tap **"Not this"**, take the apple out | — | removal resolves it | Card clears | — |
| 7 *(beta)* | Drop **spaghetti box 2** | `barilla-spaghetti` | 1 add (qty 2) | **"Too much" card** | **"That's two boxes of spaghetti, and pasta night for 4 needs one. Keep the extra?"** |
| 8 *(beta)* | Say *"No"*, take box 2 out | — | 1 remove | Total drops; card clears | — |
| 9 | Tap **Check out** | — | — | *(beta)* **"Before you go: you still need garlic bread (Aisle 2)"** | "Before you go: you still need garlic bread for pasta night. Want to grab it?" |
| 10 | Say *"Skip"*, tap **Pay** | — | — | **Receipt:** items, saved $1, time in store | "Paid. Enjoy pasta night!" |

**Without the beta**, skip steps 7–9. The flow still shows the plan, the live bill, the deal at the moment of decision, the unknown-item trust card, and the receipt.

### Meal B: game-night nachos (quick, optional)
| # | Action | Item | Result |
|---|---|---|---|
| 1 | *"Game-night nachos for 6"* | — | List: chips, salsa, queso, black beans, jalapeños, sour cream |
| 2 | Drop **salsa** | `tostitos-salsa` | **"Chips are $1.50 off in Aisle 7. Want it?"** |
| 3 | "Yes", drop **chips** | `tostitos-chips` | Deal price on the bill |
| 4 | Drop **queso, black beans, jalapeños** one at a time | `queso`, `black-beans`, `jalapenos` | Each one billed and ticked off |
| 5 *(beta)* | Check out | — | "Before you go: you still need sour cream" |

### Optional extra moments
- **Tall item:** drop the **Tide** → billed about 4 s later (as an unknown, or as `tide` if added live).
- **New product, zero training:** in the merchant console, *"add Tide detergent, $12.99, household aisle"* → Confirm → drop it on the next trip → recognized from its description alone.
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
6. **Whole team:** rehearse Meal A three times on cart 7. Run `reset-demo` once, right before judging.
