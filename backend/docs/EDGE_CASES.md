# Real-world edge cases: market backend (pricing, deals, stock, routing, checkout, data, merchant)

Each case below was checked against the code as built (2026-10-24), not against intent. Nothing
here is implemented yet; the manager picks. Cost: **S** ≈ under 1 h with tests, **M** ≈ 1–3 h,
**L** = a feature.

## Recommended first (cheap, and they protect the live demo or the trust story)

| # | Scenario | Today | Proposed fix | Cost |
|---|---|---|---|---|
| 1 | **An item is taken out after Pay.** A judge lifts the Parmesan back out once the receipt shows. | **Not handled.** `apply_cart_event` still applies to a `paid` cart, so the cart total drops while the receipt stays the same. The two disagree on screen. | **Freeze paid carts:** while `status = 'paid'`, record vision events as `applied = false` and leave the bill alone. The next `reset_cart` starts clean. A real refund is #8. | **S** |
| 2 | **The owner fat-fingers a price live** ("parmesan $0.19", or $1.99 → $199). | **Partly.** There's a preview, a Confirm, one-click Undo, and a stale-preview guard. Validation stops a deal at or above the price, and prices of $10k or more. But a 90 % price cut passes. Because "the price you saw is the price you pay" (P10), carts that already hold the item **keep the mistaken low price even after Undo**. | (a) **Plausibility warning** in the preview for any change over 50 %, or a price ×3 or more or ÷3 or less: "That's 90 % below today's price. Sure?" (b) **Undo within 10 min counts as a correction:** P10's ratchet doesn't apply, so carts go back to the correct price. | **S** |
| 3 | **A deal ends (or is ended) after the card offered it, before the shopper picks it up.** "Parmesan is $1 off. Want it?" → "Yes" → the deal ends → the Parmesan bills at full price. | **Not handled.** P10 protects items already in the cart, but not an offer that was accepted and not yet picked up. | **Honor what was offered this trip:** when a product with an open `deal_offers` row for this trip goes in, price = min(current price, the offered deal price). | **S** |
| 4 | **Stock runs out mid-trip** (another shopper's checkout, or "we're out of marinara"). | **Partly.** A plan row flips to `in_stock: false`, `next_step` skips it, and deals and nudges skip it. But stock only drops **at checkout**: two carts can both hold the last Parmesan, and both still show it in stock. | (a) **Soft reservation:** available = stock − units in open carts; use it for `in_stock` and suggestions; checkout still decrements. (b) A plan item that goes out of stock gets a line: "Marinara just sold out. Safeway (1.5 mi) might carry it", from `store_info.nearby`, never a stock claim. | **S–M** |
| 5 | **The cart is abandoned mid-trip.** | **Not handled.** The cart stays `shopping` with items, `trips_in_progress` counts it forever, and its offers sit "offered". The next shopper's Start resets it, so there's no stale bill, but analytics stay polluted. The iPad's 10-min "Still shopping?" prompt is UI only. | Add a status `abandoned`, set after 30 min with no events (pg_cron on Supabase, or the iPad's prompt timing out). Analytics exclude it; `reset_cart` from `abandoned` works as usual. | **S** |
| 6 | **"Keep it under $30."** | **Not handled** in the backend; the voice agent could reason about it, but nothing tracks it. | `carts.budget` + `set_budget`. Recompute fills `budget_left` and a beta nudge at 90 % / over ("You're at $28 of $30"). Deal cards skip anything that would push past the budget. A strong Visa "spend control" line. | **S–M** |

## Worth knowing (real, more work)

| # | Scenario | Today | Proposed fix | Cost |
|---|---|---|---|---|
| 7 | **A multipack, or "Buy 2 for $6" across items** (Target's chips + queso). | **Partly.** A multipack is its own product id, which is fine. Deals are per-product `amount_off` / `percent_off` only, so bundles and "2 for $5" aren't modeled. | A deal type `bundle {items, price}` (and `n_for {n, price}`), evaluated across cart lines in recompute, with the discount spread over the lines so receipts and `savings` stay right. | **M** |
| 8 | **A return or refund after paying.** | **Not handled.** The receipt is final; stock has already dropped. | Merchant-console `refund(receipt_id, lines)`: receipt status `partially_refunded` / `refunded`, refund rows, restock, analytics net of refunds. Logged and undoable like other merchant changes. | **M** |
| 9 | **The price changes between planning and pickup** (Kart said "spaghetti's $1.99"; it's $2.29 at pickup). | **Partly.** Items in the cart are protected by P10. Plan items aren't, and nothing records the price Kart quoted. | Record the quoted sale price per plan line (with `plan_joined`, the same ledger as #3); on add, price = min(current, quoted). | **S** (with #3) |
| 10 | **Produce sold by weight** (bananas $0.69/lb). | **Not handled.** Every product has a unit price and integer qty; "Bananas, bunch" is priced per bunch. | `products.unit` (`each` / `lb`) + `price_per_lb` + `avg_weight_lb`. A cart line shows "≈ 2.5 lb, ≈ $1.73" and is marked estimated, and the receipt says "estimated: weighed at the door". No scale hardware. | **M** |
| 11 | **Two shoppers on one cart** (a family, two voices). | **Handled for the bill:** one `carts` row, events serialized with `FOR UPDATE`, idempotent `event_id`s, manual and vision fixes in one order. No attribution or split bill. | Optional `added_by` per event (voice speaker / iPad tap) and a split-bill view at checkout. | **L** (skip for the demo) |
| 12 | **The next shopper drops an item before tapping Start** (cart `idle` or `paid`). | **Partly.** The event lands on the old trip. On an idle cart it's billed to a trip nobody started; on a paid cart see #1. | A vision add on an `idle` / `paid` cart starts a new trip (`reset_cart`, then apply), so the Pi and iPad stay in step. | **S** (pairs with #1) |

## Already handled (so the pitch can say so)

- **A deal ends while the item is in the cart:** the shopper keeps the deal price (P10). Price drops and new deals reach open carts live.
- **CV retries and duplicates:** idempotent on `event_id`. Unknown items need a confirm card, and checkout is blocked until they're answered.
- **Store-owner edits racing each other:** stale previews are refused, and Undo won't overwrite a newer edit.
- **"Through Sunday" deals:** they end at 23:59:59 store time (America/Los_Angeles).
- **Rehearsals polluting the numbers:** test and rehearsal carts are excluded from store insights.
- **The wrong store layout:** a layout switch is one undoable change. A layout that doesn't place every product is refused, and `reset-demo` returns to the mini store.
