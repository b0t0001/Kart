# KART edge-case catalog

**Why this exists:** our moat is handling the messy real world seamlessly. This catalog collects real-world scenarios from every workstream (cameras, voice and iPad, backend, member memory, hardware), with what happens today and the fix. It doubles as **judge Q&A prep**: "what happens if…?" should always have an answer here.

Owned by the manager. Status: **handled** · **partly** · **not yet**. Cost: S / M / L.

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

## In progress
| Scenario | Plan | Owner |
|---|---|---|
| "Add X" where X isn't sold here | An in-store substitute first, then a nearby store ("might carry it"); never claims stock | Voice + backend |
| "Add X" where X is sold out | "Sold out today" + an in-store substitute | Voice |
| Voice list editing (add / remove / quantity / swap) | Read back briefly, list updates live | Voice |

## Proposed by each workstream
*(Filled in as replies arrive: CV, voice/iPad, backend, member memory, hardware.)*
