# KART edge-case catalog

**Focus (Dylan, 2026-10-24): real-world SHOPPER INTERACTIONS with Kart, i.e. conversations only.** Physical edge cases (bags, personal items, camera quirks) are OUT of scope. Editing the list Kart makes, changing plans, constraints, questions mid-trip, and fixing mistakes, all handled seamlessly. That's the moat, and it doubles as **judge Q&A prep** ("what if I say…?"). The technical robustness work is in the appendix.

Owned by the manager. Status: **good** · **weak** · **broken** · **building**. Cost: S / M / L.

## 1. Shopper interaction scenarios (main focus)
The voice chat is running each scenario against the real model and recording Kart's actual reply. Results go here.

| Group | Scenarios | Status |
|---|---|---|
| **List editing** | add · remove · "make it two" · swap brand ("no, I prefer Rao's") · not sold here → in-store substitute, then a nearby store · sold out → substitute · already on the list or in the cart · remove an item after accepting its deal | **building** |
| **Changing plans** | "actually make it tacos" (keep what's in the cart) · "and breakfast for tomorrow" · "it's 6 people now" · "skip the garlic bread, we have some" | testing |
| **Constraints** | gluten-free / vegetarian / no dairy · "keep it under $30" · "what's cheapest?" | testing |
| **Questions mid-trip** | where is X · what's next · how much is X · what's on sale · what's in my cart · my total · did you get the chips · quick recipe help | testing |
| **Conversation control** | say that again · slower · stop talking / be quiet · off-topic question · mumbled request · Spanish | testing |
| **Cart mismatches** | "that's the wrong salsa" · "I put that back" · "I'm not buying that anymore" | testing |
| **Member moments** (beta) | "not me" after the greeting · "forget me" · "don't remember that" · "what did I buy last time?" · "what do you know about me?" | building (member chat) |

### Results: 52 scenarios run against the real model (voice chat, 2026-10-24)
**Good as is (highlights):**
- **List editing:** add with aisle; remove; "make it two"; "no, I prefer Rao's" (honest that only one marinara is carried); cilantro → "not carried; Berkeley Bowl, about 1.5 miles away, might have it fresh"; sold out; already on the list or in the cart; "undo that"; "I'm not buying the marinara anymore" → "…it's still in your cart".
- **Changing plans:** "skip the garlic bread, we have some"; "just me tonight". **Constraints:** vegetarian tacos; "what's cheapest?".
- **Questions:** what's next, how much is the queso, what's on sale, what's in my cart, my total, did you get the chips, a one-sentence recipe.
- **Conversation control:** say that again, stop talking, an off-topic question (redirected), "can you add the, um" → "add what?", Spanish questions answered in Spanish, "hold on", "check me out", and a kid's "Mom, can we get candy?" ignored.

**Broken → being fixed:**
| # | Scenario | Problem | Fix (batch) |
|---|---|---|---|
| 1 | "Keep it under $30" | Promises to track the budget; nothing does | Budget via the backend's new RPCs; warn when an edit crosses it (2) |
| 2 | "No dairy" | Then offers the Parmesan deal | Remember diet for the trip; skip conflicting deals (2) |
| 3 | "Actually make it tacos" with spaghetti in the cart | Spaghetti stays billed, unmentioned | "The spaghetti's still in your cart. Keep it or put it back?" (1) |

**Weak → being fixed (batch 1):** "be quiet" (real quiet mode) · "what was that deal again?" · "and breakfast for tomorrow" (adds, doesn't ask) · "make it two" with no "it" (asks "two of what?") · package read-back ("one bag of avocados") · "it's 6 people now" (rescale) · "thanks" → "You're welcome!" · combined read-backs · diet answers only from product names (no invented claims) · "talk slower" (honest line).
**Batch 3 (polish):** faster answers (live cart summary each turn; today 3–7 s); "take it off the list too?"; "how much is this?"; reconnect; pause the voice call when it's quiet.
**Skipped:** Spanish templates for Kart's fixed lines.

---

# Appendix: robustness (already covered or in progress)

## Already handled (proven by tests, clips or rehearsals)
| Scenario | How KART handles it | Evidence |
|---|---|---|
| A hand resting in the basket | Not billed if it moves on within 3 s. If it rests longer, it's billed as an unknown and auto-resolved when it leaves | CV tests, real clips |
| Rolling the cart past shelves and people | The camera only watches the basket floor (ROI); the room behind the mesh is ignored | Real-cart fix, regression clip |
| Tall item reaching the frame edge | Billed after a 3 s stillness check | Real Tide clip |
| Sun stripe or shadow | Light and shadow aren't counted as change | Real clips |
| Item the camera can't name | An **"Is this…?"** card; checkout is blocked until it's answered | E2E + rehearsal |
| Wi-Fi drops | Events queue on the Pi and arrive in order; a retry never double-bills | E2E |
| The price you saw is the price you pay | Price drops apply to items in the cart; increases and ended deals don't | Backend tests |
| Too much for the meal (beta) | "That's two boxes… Keep the extra?" | Rehearsal |
| Forgot an item (beta) | One "Before you go" list at checkout | Rehearsal |
| Loud demo floor | Hold-to-talk; Kart stays quiet on chatter; deal and nudge lines can't be cut off | On-device test |
| Deals said too often | Ask first; "not now" = tell me at the shelf; each deal at most once per trip | Rehearsal |
| A store owner's mistake | Every console change is previewed, confirmed, logged and undoable | Merchant smoke test |
| A soft bag slumps after it's dropped | Counts as the same item settling in place, not billed again | Real four-corners clip |
| Identical boxes side by side, overlapping, or pushed together | Each one is counted | CV tests |
| A box stacked exactly on an identical box | **Known limit:** reads as settling, so it isn't counted (never a double charge). In the demo, lay boxes side by side. Revisit with the deliberate-stack clip | CV tests; stack clip pending |

## In progress
| Scenario | Plan | Owner |
|---|---|---|
| "Add X" where X isn't sold here | An in-store substitute first, then a nearby store ("might carry it"); never claims stock | Voice + backend |
| "Add X" where X is sold out | "Sold out today" + an in-store substitute | Voice |
| Voice list editing (add / remove / quantity / swap) | Read back briefly, list updates live | Voice |

## Proposed by each workstream
*(Filled in as replies arrive: CV, voice/iPad, backend, member memory, hardware.)*

### Hardware: physical world (James's chat; "seen" = happened today)
| # | Scenario | Today | Fix | Cost | Decision |
|---|---|---|---|---|---|
| H1 | **The Pi reboots or power blips** (seen) | Nothing runs until someone starts it by hand; cart memory survives | Install `kart-cv.service` (restarts on its own); show camera health / last-frame age on the iPad debug panel | S | **Go** (service now). The health signal needs a Pi→Supabase heartbeat; see cross-team |
| H2 | **The hotspot drops or the laptop sleeps** (seen) | Events queue and arrive later; trip resets stall; `.local` names fail | A second Wi-Fi profile on the Pi (venue Wi-Fi or a phone hotspot); turn off the hotspot's idle auto-off; use the IP | S | **Go** |
| H3 | **A camera is bumped or its mount shifts** (seen) | A big shift = "disturbed" (no corruption), but the floor outline is then wrong | Rigid mounts plus printed anti-rotation shells; a pre-demo **aim-check** script (live frame vs reference) | S/M | **Go** (aim check) |
| H4 | **A USB unplug, port swap, or bandwidth limit** (seen) | 2 cams at 15 fps is clean; a dropped cam reconnects; **swapping ports swaps cam0/cam1** | Strain-relief loops, labelled ports, cables routed along the frame | S | **Go** |
| H5 | **The power bank sags or dies** (expected) | Shows as camera dropouts, then a reboot | 5 V/3 A bank with a short cable; show power status in `/status`; carry a spare bank | S | **Go** |
| H6 | **A judge pushes the cart fast** (seen before the fix) | Fixed by the floor ROI; untested on the final layout | Record the "roll" clip now; keep the solid floor liner | S | **Go** |
| H7 | **Venue lighting, glare, white balance** (seen) | Real clips pass | Test under the venue lights; lock the Brio's white balance if colours drift | S/M | Before judging |
| H8 | **A judge's phone or bag set INSIDE the basket** (expected) | **It's a real add**, so it gets an "Is this…?" card | Choreography (drop, hand out); the marked drop zone; **cross-team: a "That's mine" action** | S | See cross-team |
| H9 | **The iPad mount drops on a bump** | Not printed or fit-tested yet | Fit test, a zip-tie backup, a charging cable path | M | Before the video |

### Member memory and privacy (member chat; beta, flag off by default)
| # | Scenario | Design today | Fix | Cost | Decision |
|---|---|---|---|---|---|
| M1 | **"Forget me" mid-trip** | **Gap:** the agent keeps the profile in its prompt and can still mention Leo's party | Forget → new trip_context without the member; the agent drops the profile and tools at once: "Done, I've forgotten everything." | S | **Build** |
| M2 | **Mistyped member number** | An unknown id silently creates a member; a typo can land on a real one | Confirm card: "Dylan N.? That's me / Not me"; an unknown id → "Start a new membership?" | S | **Build** |
| M3 | **Someone else's number; memories said aloud on a public floor** | Demo-grade, no PIN | Demo: optional PIN. Production: a QR code or passkey from the shopper's phone (pitch note) | S / L | Defer (pitch note) |
| M4 | **Forgot to sign out / walked away** | Signed in until the next reset | "Still shopping, Dylan?" at 3 min; sign-out at 5 min (the trip is kept) | S | **Build** |
| M5 | **Sensitive purchases** (the Target pregnancy story) | Nothing prevents it | Sensitive categories (pharmacy, personal care, baby) never feed picks, usuals or speech; Claude saves the event, not the reason | S | **Build**: a strong trust line |
| M6 | **Stale events; the seed not rerun** | Undated events never expire; "party tomorrow" can be in the past | Undated events expire after 30 days; the seed prints the date; it runs in `pre_judging.sh --members` | S | **Build** |
| M7 | **One-off event shopping skews the usuals** | Partly handled (counts trips, with thresholds) | Tag saved-list purchases and leave them out of the stats | M | Defer |
| M8 | **A pick or saved item now out of stock or discontinued** | Picks skip it; the prompt may still mention it | `available` flag; offer the nearest in-stock substitute | S–M | Defer |
| M9 | **"What do you know about me?"** | — | Kart opens the memory sheet on the iPad with a one-line summary | S | **Build** |

### Cross-team candidates (emerging)
- **Personal items** (a phone, bag or jacket placed in the basket): on the "Is this…?" card, add **"That's mine, ignore it"** → never billed, and the camera ignores that spot until it's removed (CV + iPad + backend).
- **Cart health on the iPad:** the Pi writes a heartbeat (last frame age, camera status, power status) to Supabase every few seconds, and the iPad debug panel shows it (CV + backend + iPad). A dead camera is then visible without SSH.
