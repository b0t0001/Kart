# Demo shopping list

> **FINAL PLAN: see [DEMO_PLAN.md](DEMO_PLAN.md).** It has the shopping list for the two shelf-stable meals (pasta night and game-night nachos), with each item's catalog id, aisle, deal and demo step. The lists below are earlier drafts.

## LEAN LIST (recommended): 7 shelf-stable items, ~$35–40, nothing to refrigerate

| Buy | Qty | ~Cost | Covers |
|---|---|---|---|
| Barilla Spaghetti, 1 lb (blue box) | **3** | $6 | Pasta scenario, add/remove, **the "too much" nudge** (the 3rd box), **counting identical items** |
| Marinara, jar (any brand; a plastic jar is safer than glass) | 1 | $4–9 | Pasta. **Triggers the Parmesan deal** |
| Grated Parmesan shaker (e.g. the Kraft green can; shelf-stable) | 1 | $4 | **The headline deal card:** "Parmesan is $3 off" |
| Tortilla chips, big bag | 1 | $5 | **A second deal card** (chips $1.50 off), a big and light item that's safe to drop |
| Salsa, jar | 1 | $4 | Triggers the chips deal |
| Taco seasoning packet | 1 | $1.50 | The **small-item** test |
| Flour tortillas, soft taco pack *(optional)* | 2 | $8 | Taco scenario plus a second identical pair |

**Free, already on hand:**
- **apple:** not in the catalog, so it shows the **"Is this…?"** card (the trust story);
- **Tide bottle:** the **tall item**, either as an unknown or added live in the merchant console to show a new product with zero training.

**Don't buy, on purpose:**
- **ground beef, cheese, sour cream, avocados, milk, eggs, bananas.** Kart still plans them ("taco night for 4" → beef, cheese, sour cream…), and leaving them out is **exactly what triggers the "Before you go: you still need ground beef and sour cream" checkout reminder.**

**How every feature is still covered:**
| Feature | Shown with |
|---|---|
| Voice planning, routing, captions | Any request ("pasta night for 4") |
| Add → live bill; remove → total drops | Spaghetti, chips |
| Deal at the moment of decision | Marinara → **Parmesan $3 off**; salsa → **chips $1.50 off** |
| Unknown item → "Is this…?" → checkout blocked until it's answered | The apple |
| Tall item (billed after a 3 s stillness check) | The Tide bottle |
| Small item | The taco seasoning packet |
| "Too much" nudge (beta) | The 3rd spaghetti box |
| "Still short" checkout reminder (beta) | Everything you didn't buy |
| Counting identical items (beta) | 2–3 spaghetti boxes dropped together |
| Merchant console (housekeeping) | Live price/aisle/deal edits, adding the Tide as a product |

**Skipped from the full list, with what you'd lose:** a big-item test (the chips bag is close enough), produce with no package (bananas), and a few staples. None of these are demo features.

After shopping, send the manager the exact items. The backend then changes `kirkland-parmesan` into the grated shaker (name, size, price, camera description) and sets stock to how many you bought.

---

## Full list (original, for reference)

These props cover three demo scenarios plus the camera and quantity tests. Every item maps to a product already in the catalog (`data/store.json`), so its deals and aisles already work. **Buy normal grocery sizes.** After shopping, send the manager the exact items, and the backend updates names, sizes, shelf prices, camera descriptions and **stock = how many you bought**.

## The list

| # | Buy | Qty | ~Cost | Scenario / why |
|---|---|---|---|---|
| 1 | Barilla Spaghetti, 1 lb (blue box) | **3** | $6 | Pasta (headline). The 3 identical boxes are for the "too much" nudge and the counting tests |
| 2 | Rao's Marinara, 24 oz (**glass**, so place it gently, don't drop) | 1 | $9 | Pasta |
| 3 | Parmesan wedge (any brand, in a wedge in wrap) | 1 | $8–13 | **The deal card:** "Parmesan is $3 off". It pairs with spaghetti and Rao's |
| 4 | French baguette (buy the morning of the demo) | 1 | $3 | Pasta. The $1 off deal. Long, oddly shaped item |
| 5 | Caesar salad kit (bag) | 1 | $5 | Pasta side; pairs with the baguette deal |
| 6 | Flour tortillas, soft taco pack (same brand and size ×3) | **3** | $12 | Tacos. The 3 identical packs are for nudges and the counting tests |
| 7 | Taco seasoning packet | 2 | $3 | Tacos. A **small** item, which tests the cameras' size limits. Pairs with the sour cream deal |
| 8 | Chunky salsa jar (glass, so place it) | 1 | $5 | Tacos. Triggers the chips deal |
| 9 | Tortilla chips, big bag | 1 | $5 | **The deal card:** "Chips are $1.50 off". Light and safe to drop |
| 10 | Avocados, 5-count bag | **2** | $12 | Tacos ("I need three avocados" → 1 bag). The 2 identical bags are for the counting tests |
| 11 | Sour cream, 16 oz tub | 1 | $3 | Tacos. The 20%-off deal |
| 12 | Shredded Mexican cheese, bag | 1 | $5–8 | Tacos |
| 13 | Bananas, one bunch (loose, no package) | 1 | $2 | Staples. A package-free item, which tests the cameras on produce |
| 14 | Milk, half gallon (carton or jug) | 1 | $5 | Staples. The **tall item** test (it's billed about 4 s after it settles) |
| 15 | Paper towels, 6–12 roll pack | 1 | $10–24 | Household. The **big item** test (it covers most of the floor). Pairs with the batteries deal |
| 16 | AA batteries pack *(optional)* | 1 | $10–16 | Household. "$4 off" when paper towels go in |

**About $100–130 in total.** Skip the batteries and buy a 6-roll pack of paper towels for about $95.

**Don't buy:**
- **Raw ground beef.** It's a hygiene problem at a demo table. Kart still plans it for tacos and pasta, and leaving it out is *how you demo the "you're 1 lb ground beef short" nudge* (beta).
- **Eggs.** They break when dropped.

**Already on hand:** the Tide bottle and an apple. They're not in the catalog. Drop the apple to show the **"Is this…?"** card, which is the trust story. Or add "apples" live in the merchant console to show *a new product with zero training*.

## What each scenario shows

1. **Pasta dinner for 4 (the headline):**
   - "Pasta dinner for my family" → Kart lists spaghetti, Rao's and the baguette ($1 off).
   - Drop the spaghetti → the **Parmesan $3 off** card → "yes" → drop the Parmesan.
   - Take the baguette out → the total drops → check out → receipt.
2. **Tacos for 4:**
   - "Taco night for four, I need three avocados" → tortillas, seasoning, salsa, avocados, cheese, sour cream.
   - Drop the salsa → the **chips deal**.
   - *Quantity nudges beta:* drop a 3rd tortilla pack → "taco night for 4 needs one, keep the extra?". Head to checkout → "you're 1 lb ground beef short".
3. **Trust and edge cases:** drop the apple → "Is this…?". Drop the milk (tall). Drop the paper towels (big). Hand resting in the basket → nothing billed.

## After shopping (about 30 minutes in total)

1. **Send the manager the exact items:** brand, size, the shelf price you paid, and the count. Photos work too. The backend updates `data/store.json` (names, sizes, prices, camera descriptions, stock = count bought). The aisles stay as they are unless you want the saved layouts.
2. **James enrolls each prop on the Pi** (`tools/enroll.py <product-id>`, about 1 minute each), then runs `tools/gallery_check.py`.
3. **The identical-item clips** (spaghetti, tortillas, avocado bags) for CV's counting test.
4. **Right before judging:** `backend/.venv/bin/python backend/db.py reset-demo` (the demo operator only).
