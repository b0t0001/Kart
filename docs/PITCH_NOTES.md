# KART pitch notes

Talking points for the pitch, the Devpost write-up and judge Q&A. Owned by the manager; add to it as the demo firms up.

## The CV moat: "no training, no tags"

**One line:** *The cart learns a new product in a minute, or from a sentence, with no retraining and no tags on the product.*

- **Uniqlo-style checkout without the RFID.** Uniqlo tags every item with a chip. KART uses two cameras looking into the basket, so the store tags nothing and keeps its existing products and shelves.
- **Two jobs, two tools.**
  - **Detection** uses picture-to-picture comparison. Once the basket settles, the Pi compares each camera against its last calm picture: something new means added, something gone means removed.
  - **Identification** is learned, not trained.
  - So hands, shadows, a lean over the cart, a bumped camera or a nudged item don't get billed. Each of those is a test case.
- **Identification without training a model:**
  1. *On-device, few-shot:* drop a product in about 5 times (about 1 minute). The Pi stores those views and matches new items locally, with no network needed.
  2. *Claude as the fallback:* when the local match isn't confident, Claude picks from the store's own catalog using each product's short visual description. It answers "unknown" rather than guessing.
- **Why that beats training YOLO:** trained recognizers must be retrained whenever the catalog changes. With KART, a store owner tells the merchant agent "add fresh basil, $2.49, produce aisle", and the next cart can recognize it, with **zero photos and zero retraining.**
- **Built for a Raspberry Pi 4.** Detection runs at 10 Hz on downscaled frames, and the cameras use about 18% of the Pi's CPU. Claude is called only when a settled change needs it.
- **Two cameras, one decision.** The diagonal corners cover each other's blind spots, and one item seen by both counts once.

**Numbers to fill in after hardware testing** (from `tools/gallery_check.py` and `tools/cloud_smoke.py --gallery`):
- local match accuracy on real props: ___
- Claude accuracy on real props: ___ (12/12 on printed-name test crops, median 1.6 s)
- drop → iPad latency: ___ (expected ~1.5 s local, ~3 s with Claude)

## Trust: where the AI could be wrong, and what we did about it
*(Anthropic asks this directly; Visa scores "trust & responsibility" at 15%.)*
- **Cameras point into the basket, never at people.** Only crops of the changed region go to Claude, and no faces are stored.
- **Unsure means ask.** An unrecognized item becomes an "Is this…?" card on the iPad, fixed in one tap.
- **Checkout is blocked** while any item is unresolved, so nobody pays for a guess.
- **The price you saw is the price you pay.** Price drops and new deals apply to items already in the cart; increases and ended deals don't.
- **The merchant agent proposes; the owner confirms.** Claude can only stage a change with a plain-English preview. Nothing applies without a click, every change is logged, and any change can be undone in one click.
- **Every charge is traceable** to a camera event.

## The demo beat (≈2 min)
1. The judge says "pasta dinner for my family" → Kart plans the trip and routes it.
2. The judge drops the spaghetti into the cart → the total updates live on the iPad.
3. The store owner types "parmesan $3 off" in the merchant console and clicks Confirm → the cart pops "Parmesan is $3 off in Aisle 4. Want it?" within a second.
4. The judge takes an item back out → the total drops.
5. Check out → receipt with savings and time in store.
6. Close: *"Our 4-hour Costco trip, cut to 45 minutes."*

**Run it:** `backend/docs/DEMO.md` (reset with `--without-deal d-parm-3off`).
