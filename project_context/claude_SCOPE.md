# SCOPE: Smart Shopping Cart (working title)

> Cal Hacks 13.0 · living doc, revise as we go · tracks: **Visa (Reimagining Shopping)**, **Best Hardware Hack**, maybe **Cartesia**

## One-liner
A cart that knows the store. You tell it what you're there for, it watches what goes in, keeps a running total, points out the deals worth grabbing, and walks you to them aisle by aisle.

**Not in scope:** self-checkout, payment, or exact pricing. It's a shopping companion, not a register.

HOWEVER we will implement this "not in scope" stuff if time permits because it woul db really cool and make the entire shopping experience as seamless and "futuristic" as possible (think like uniqlo how much time is saved for the business and consumer via the auto detection of items, and allowing like auto)

---

## The problem (we are the user)
We go to Costco with family and stay **3–4 hours** every time. Part of that is fun (samples, finding deals), but most of it is wandering: hunting for deals you only hear about after the fact, doubling back across the warehouse, and having no idea what the cart total is until checkout.

Nobody walks in with a prepared list, so list apps don't help. The shopping happens in the moment, inside the store.

## Why brick and mortar still matters (pitch stats)
- **About 84% of US retail sales still happen offline.** E-commerce was 16.2% of retail in Q1 2025 (US Census, via [Fit Small Business](https://fitsmallbusiness.com/online-shopping-statistics/?ssrid=ssr)).
- **About 80% of US grocery spending is in-store.** Online is "about one-fifth," per NielsenIQ ([Talk Business, Aug 2026](https://talkbusiness.net/2026/08/the-supply-side-annual-e-grocery-sales-expected-to-top-363-billion-up-4/)).
- **Grocery is still "primarily store-led."** 93% of grocery shoppers bought both online and in-store in 2025 (FMI/NIQ, via [Chain Store Age](https://chainstoreage.com/study-93-grocery-shoppers-purchased-both-online-and-store-2025)). People already shop with their phones in hand inside the store.
- **Preference for in-person shopping rises with age:** Gen X 51%, Boomers 60%. Gen Z leans hybrid (36%). Millennials lean most online. (2025 Prose Media data, via [Fit Small Business](https://fitsmallbusiness.com/online-shopping-statistics/?ssrid=ssr))

**Correction on segmentation:** the hunch that older, wealthier shoppers prefer stores is half right. Older shoppers do prefer stores, but **the Costco shopper is getting younger *and* richer** ([CNBC / Coresight](https://www.cnbc.com/2023/02/09/the-costco-customer-is-younger-and-richer-than-everheres-why.html)). The better framing for the pitch:
- **Primary user:** families doing big warehouse-club trips (high basket value, long trips, multiple decision-makers). That's us.
- **Secondary user:** older shoppers who prefer stores but find big-box stores tiring to navigate. Voice-first and an on-cart screen make the tool accessible without needing to be good with a phone.
- **The merchant (Visa scores this):** the store gets a channel to push real-time deals at the exact moment of decision, plus anonymous in-store path and basket data. Online stores already have this; physical stores don't.

---

## What we're building

### 1. The cart (Raspberry Pi: real-world layer)
- **Hardware decision: Raspberry Pi 4 only, no Arduino.** The Pi runs the cameras, the LCD (I2C), and any GPIO extras. That means one board, one power bank, one enclosure (see ENCLOSURE.md).
- **2 webcams** on the cart watch items **going in and coming out**.
- Object recognition identifies the item, and the cart keeps a **running cart list + estimated total** (the total doesn't need to be exact).
- **On-cart LCD** shows the next step ("Aisle 12 →, Kirkland batteries $4 off"), the running total, and alerts.
- Talks to the phone in real time.

### 2. The phone app (user layer)
- **Voice-first agent.** Just talk: *"We're doing tacos for 8 and need diapers. Anything good on sale?"*
- Builds the plan on the fly: items, recommendations, deals, and a route.
- Shows the live cart and total from the Pi.
- Pushes recommendations as you shop. For example, you add salsa and it says *"chips are on deal two aisles over."*

### 3. Store brain (data layer)
- **Store layout map** (aisles and sections → coordinates) and a **deals feed** (product, price, discount, location).
- **Real-time navigation:** the route updates as items get added, shown on both the phone and the LCD.
- For the demo, this is **our own mock store**, set up at the venue table (see Demo).

---

## The demo (this decides whether we win)
The demo has to be **hands-on and physical**, so judges don't come away thinking "AI SaaS." The target flow, in about 2 minutes:
1. A judge talks to the phone: *"I'm making a pasta dinner for my family."*
2. The agent builds a plan, and the **LCD lights up with the first direction**.
3. The judge drops a real item into the cart. **The cameras catch it, and the total updates live** on the phone and LCD.
4. The cart says: *"Parmesan is $3 off in Aisle 4, want it?"* (a deal at the moment of decision).
5. The judge takes an item back out, and the cart notices and the total drops.
6. Closing line: *"Our 4-hour Costco trip, cut to 45 minutes."*

Props: a real cart if we can get one (or a basket or box on wheels), ~10–15 real grocery items, and printed aisle signs to make a mini-store at our table.

---

## Track alignment

**Visa: Reimagining Shopping ($5,000)** is the primary track. Here's how we cover each criterion:

| Criterion | Weight | How we hit it |
|---|---|---|
| Innovation | 25% | Bringing the online-shopping experience (recommendations, live cart, deals) into a physical cart |
| User experience | 25% | Voice-first, no list needed, glanceable LCD, and it just works when you drop an item in |
| Technical execution | 20% | Two-camera in/out tracking, live sync between Pi and phone, agent planning plus routing |
| Commerce impact | 15% | Bigger baskets from deals offered at the moment of decision, shorter trips, merchant analytics |
| Trust & responsibility | 15% | **Cameras point into the cart, not at people.** Process on-device where possible, show the user what the AI saw, store no faces. *Say this in the pitch; cameras on a cart will raise the question.* |

**Best Hardware Hack** (Bambu A1 Mini) comes with the physical cart.

**Cartesia (maybe)** only counts if voice is the main way people use the product, not a feature. The agent talks back and you can interrupt it while your hands are full pushing a cart. If voice ends up as just a mic button, we drop this track.

---

## Non-goals (for now)
- Payment, checkout, or loss prevention
- Exact prices or real retailer data integration (mock store data is fine, but say so in the pitch)
- Indoor positioning hardware. Location can come from which items you've added or from manual check-ins at first

## Open questions / risks (for the feasibility pass)
- **Can the Pi run two webcams plus recognition fast enough?** We may need to offload inference to a laptop or a cloud vision model, or use the rentable ASUS GX10.
- **Detecting items going in vs. coming out** is the hardest technical piece. **Decision: snapshot-diff, no beam break.** The cameras stream continuously with cheap motion detection. When motion starts, wait for it to settle, run object detection once, and diff against the last snapshot: a new item means *added*, a missing one means *removed*. No in-flight tracking, hands don't cause false adds, and the Pi only runs recognition a couple of times per item. *(Dropped the IR break-beam: a single beam can't cover a whole cart opening. The IR parts are optional demo flair only.)*
- **How does the cart know where it is?** The answer decides whether real-time navigation is real or scripted.
- **Phone ↔ Pi connection:** venue WiFi, a local hotspot, or a cloud relay?
- **Mic placement:** the voice agent has to work in a loud hackathon hall.
- **Native app vs. mobile web app:** a web app is much faster to ship.
- **No soldering** is allowed in the venue, so the mounting and wiring plan has to work without it.
- **Power:** a USB-C power bank (5 V / 3 A), with 2 banks for the demo. See ENCLOSURE.md.

## Engineering proof points (for the pitch)
- **The cart clip was designed with FEA in under an hour:** a custom plane-stress solver checked against beam theory (−3%), mesh-converged, and a 36-design sweep. It showed the first C-clip design would have snapped (~10%+ strain) and picked a J-hook + barbed latch at about 1.1% strain with a safety factor of about 10. To be cross-checked in Fusion Simulation. Plots: `clip_fea.png`.
- **The CAD is fully parametric and generated from a script.** Change the cart wire diameter and the whole model rebuilds.
