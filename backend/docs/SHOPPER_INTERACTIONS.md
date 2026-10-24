# Shopper interactions with Kart: what the cart RPCs support today

Dylan's "edge cases" are real shopper conversations, not backend robustness (that list is
`EDGE_CASES.md`, set aside). Each scenario below was checked against the RPCs as built
(2026-10-24), and the key ones were tried on a throwaway cart.

| Scenario | Today | RPC work needed |
|---|---|---|
| **"Actually, make it tacos"** (replan, keeping what's in the cart) | **Supported.** `set_plan` replaces the list. Cart items stay billed and become off-list (no nudges, no deal pressure). Deals already offered aren't repeated. Checked: the spaghetti stays on the $1.99 bill while the list becomes tortillas and beef. | None. The agent can compare `carts.items` with `plan` to ask "keep the spaghetti?" |
| **A second meal on the same trip** ("…and nachos for Saturday") | **Partly.** `set_plan` with both meals works, but (1) there's no per-meal grouping, only the free-text `reason`, and (2) **the same product from two meals isn't merged**: two sour-cream rows each need 1, and ONE tub marks both done ("All done" while 2 are needed). Also, adding a meal means resending the whole list, which can race the iPad's list edits. | **S:** add `plan[].meal`, and have `set_plan` merge duplicate product ids (sum qty, keep each meal's `basis`). **S:** atomic `add_to_plan(p_cart_id, p_items)` / `remove_from_plan(p_cart_id, p_product_ids)` so voice and taps don't overwrite each other. |
| **"It's 6 people now"** (rescale) | **Supported.** `set_plan` with the new `qty` and `basis`; done flags, routing and beta nudges follow. | None. Optional `plan[].servings` would let Kart rescale without recomputing from scratch. |
| **"Keep it under $30"** (budget, running total vs budget) | **Not supported.** No budget anywhere. The running `total` and `savings` exist, but there's no "of $30", no estimated cost of the remaining list, and deal cards don't know about it. | **S–M:** `carts.budget` + `set_budget(p_cart_id, p_amount)`. Recompute fills `budget_left` and `plan_estimate` (Σ sale price × qty still to get), so Kart can say "the list fits: about $24 of $30". Optional: deal cards skip anything that would bust the budget, plus a beta nudge at 90 % / over. |
| **"What's in my cart?"** | **Supported.** The `carts` row has `items` (name, qty, price, deal), `total`, `savings`, `item_count` and the list's done flags. Unconfirmed items are in `cart_events` (`product_id` null, unresolved). | None. |
| **"Skip the Parmesan after all"** (dropping an accepted-deal item from the list) | **Supported.** `set_plan` without it removes the row, and the deal isn't offered again this trip. If it's already in the cart, it stays billed until it comes out (vision removal, or `apply_cart_event('removed', source 'manual')`). | None (an atomic `remove_from_plan` would make this one tap; see the second-meal row). |
| **"Get Prego instead of Rao's"** (brand swap) | **Supported by the RPCs, limited by the catalog.** `set_plan` can swap one product id for another, and `product_catalog` lists same-category options. But the demo catalog has ONE product per category (one marinara, one salsa…), so Kart has nothing to swap to. A brand the store doesn't carry is an unknown item (confirm card) or a "not sold here" (`store_info.nearby`). | **Data, not RPC:** add 1–2 alternates per demo category (e.g. a second marinara and salsa, both shelf-stable) with `vision_hint`s, if we want this moment. |

Also already supported, for the agent's question list:
- **"Where's the X?"**: `product_catalog.aisle`.
- **"Is X on sale?" / "any deals for tacos?"**: `deal_label` and `tags`.
- **"How much have I saved?"**: `carts.savings`.
- **"I'm at aisle 5"**: `set_location`.
- **"No thanks"**: `dismiss_suggestion`.
- **"Keep it" / "ok"** on a nudge: `dismiss_nudge`.

**Built (v0.16):** all three. Duplicate products merge into one line, with `plan[].meal` / `meals`.
`add_to_plan` / `remove_from_plan` make atomic list edits. `set_budget` fills `budget_left` and
`plan_estimate`. See the RPC table in `backend/README.md`.

**Recommended RPC work, in order:** (1) merge duplicate products + `plan[].meal`, (2) atomic
add/remove plan items, (3) budget. All three are small, and nothing else in this list needs RPC changes.
