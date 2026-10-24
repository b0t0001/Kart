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

### Cross-team candidates (emerging)
- **Personal items** (a phone, bag or jacket placed in the basket): on the "Is this…?" card, add **"That's mine, ignore it"** → never billed, and the camera ignores that spot until it's removed (CV + iPad + backend).
- **Cart health on the iPad:** the Pi writes a heartbeat (last frame age, camera status, power status) to Supabase every few seconds, and the iPad debug panel shows it (CV + backend + iPad). A dead camera is then visible without SSH.
