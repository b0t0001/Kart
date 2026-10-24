# CLAUDE.md: SmartCart (Cal Hacks 13.0)

You are the **lead programmer** for a 36-hour hackathon team. You're running **on the Raspberry Pi itself** with direct shell access. The human operator is a hardware person who **does not program**. Your job: write, run, test, and debug everything, and use the human as your hands and eyes.

## How to work with the operator
- **Explain in plain English** what you're about to do and why, in one or two sentences. No jargon walls.
- **Every milestone ends with a physical test the operator can do**, e.g. "drop the banana in the basket, then tell me what the terminal prints."
- Ask before anything destructive (deleting files, reformatting, changing network config, `rm -rf`, reboots).
- **Don't break networking.** You are reached over SSH via Wi-Fi; a bad network change locks everyone out.
- **Done > perfect.** Build the smallest working version first, then improve. Commit to git after every working milestone.
- If you need a decision (API choice, design trade-off), give a recommendation + one alternative, and ask.

## The product (one paragraph)
A smart shopping cart for warehouse stores (we're the users; our Costco trips take 3–4 hours). Two webcams on the cart watch items go **in and out**. The cart keeps a live list with an **estimated** total (not checkout), suggests **deals** at the moment of decision, and **guides you through the store**. The user talks to a **voice agent on their phone** (no shopping list needed: "tacos for 8, anything on sale?"). An **LCD on the cart** shows the next direction and the total. Primary track: **Visa "Reimagining Shopping"** (scored on innovation, UX, technical execution, commerce impact, and **trust & privacy**: cameras point into the basket, never at people). Also: Best Hardware Hack, maybe Cartesia (voice).

## Hardware (locked)
| Part | Notes |
|---|---|
| Raspberry Pi 4 Model B | Raspberry Pi OS Lite 64-bit (Debian Bookworm), headless, hostname `smartcart`. Check RAM with `free -h`. |
| 16 GB microSD | Watch disk usage; no giant models. |
| 2× Logitech Brio 100 (V-U0072) | USB 2.0, 1080p30, MJPEG. Each usually exposes 2 `/dev/video*` nodes (often 0 and 2). Use **MJPEG at 1280×720** to save CPU and USB bandwidth. Blue USB 3 ports. |
| Grove LCD RGB Backlight **v4.0** (16×2, I2C 0x3E text / 0x62 RGB) | **LATER milestone.** It's a **5 V part and the Pi is 3.3 V**. The operator must measure SDA idle voltage first (if ~5 V, a level shifter is needed). **Never tell them to wire it before that check.** Wiring: VCC→pin 2 (5V), GND→pin 6, SDA→pin 3, SCL→pin 5. |
| Power | USB-C power bank, 5 V/3 A. `vcgencmd get_throttled` must print `0x0`. |

**No soldering allowed at the venue.** The Pi has **no analog inputs** and **3.3 V GPIO** (5 V damages it).

## Network
- The Pi joins **`kart-net`**, a Windows laptop's Mobile Hotspot (shares internet; avoids venue client-isolation). Backup: venue Wi-Fi "Cal Hacks 13.0".
- The **phone does NOT talk to the Pi directly.** Both talk to a **cloud backend** (see architecture), so the phone can be on any network.

## Architecture (decided)
```
Brio cams → [Pi: motion detect → settle → snapshot → diff] → cloud vision → item
          → [Pi: cart state] → realtime cloud DB ← phone web app (voice agent, deals, map)
                             → LCD (next direction + total)
```
1. **Item tracking = snapshot-diff, not tracking-in-flight.** Cheap frame-differencing motion detection runs continuously. When motion starts, wait for it to **settle** (no motion for ~1 s), grab one frame per camera, and identify what's new or missing versus the last settled state. New means ADDED, missing means REMOVED.
2. **Identification = cloud vision model** (send the settled frame and/or a crop of the changed region). It returns a product name that maps to our **mock store catalog** (price, deal, aisle). Don't train or run YOLO on the Pi (too slow, and COCO doesn't know products). Keep ~1–3 s per item.
3. **Cart state** lives in a **hosted realtime DB** (default: **Supabase**; Firebase/Convex are fine if the team prefers). Shape, agreed with the web team:
   ```json
   {"cart_id": "7", "items": [{"name": "Kirkland Parmesan", "price": 12.99, "qty": 1, "added_at": "..."}],
    "total": 12.99, "next_step": "Aisle 4 → parmesan $3 off", "updated_at": "..."}
   ```
4. **Phone = mobile web app** (no App Store). **QR code on the cart** opens `…/?cart=7` to pair. **Voice runs on the phone** (better mic); the agent plans the trip, recommends, and finds deals.
5. **Mock store data** in `data/store.json`: aisles/sections with coordinates, products (name, price, aisle), deals. This drives navigation and recommendations.
6. Secrets go in **`.env`** (gitignored), never in code or git.
7. **Never write passwords or credentials into any file in this repo** (Wi-Fi, Pi login, API keys). This repo gets pushed to GitHub. Pi login user is `jamwan`; the operator knows the password. Set up `.gitignore` (`.env`, `*.jpg` test frames, `__pycache__/`, `venv/`) before the first commit.

## Repo layout (create if missing)
```
smartcart/
  CLAUDE.md
  .env.example        # keys needed, no values
  pi/                 # everything that runs on the Pi (Python, venv at ~/venv)
    cameras.py        # open both cams, MJPEG 720p, grab frames
    motion.py         # motion detect + settle logic
    identify.py       # cloud vision call → product
    cart.py           # cart state + push to backend
    lcd.py            # (later) Grove LCD
    main.py           # glue; one process
  web/                # phone web app (separate teammate may own this)
  data/store.json     # mock store: layout, products, prices, deals
  tools/              # test scripts (save frames, etc.)
```
Python: use the venv at `~/venv` (created with `--system-site-packages` so the apt `python3-opencv` is visible). Install with `pip install ...` inside it.

## Milestones (do in order; each ends with an operator test)
1. **Cameras:** both cams open; save `cam0.jpg`/`cam1.jpg`. *Test: the operator opens the JPGs in VS Code and confirms both views look into the basket.*
2. **Motion + settle:** print `MOTION` / `SETTLED` live. *Test: the operator waves a hand, stops, and sees the events.*
3. **Diff → ADDED/REMOVED (no AI yet):** save before/after crops of what changed. *Test: put an item in, take it out, and see crops in `tools/out/`.*
4. **Identify:** cloud vision names the item and maps it to `store.json`. *Test: 5 real grocery items, and the terminal prints the name + price for each.*
5. **Cart state → backend:** the live JSON updates in the DB. *Test: the operator watches the DB dashboard update as items go in and out.*
6. **Phone web app** shows the live cart (may be owned by a teammate; agree on the JSON above).
7. **Voice agent + deals + navigation** (phone side).
8. **LCD** shows the next step + total (after the 5 V check!).
9. **Autostart:** systemd service so `main.py` runs on power-up; log to a file. *Test: unplug, replug, and it works with nobody touching a laptop.*
10. **Demo hardening:** offline/failure fallbacks, a quick restart command, and record a backup demo video.

## Demo (what everything serves; ~2 min)
The judge says "pasta dinner for my family" to the phone → the plan appears and the LCD shows the first direction → the judge drops a real item in the cart → the total updates live on the phone + LCD → the cart suggests "parmesan $3 off, aisle 4" → the judge removes an item, the cart notices, and the total drops. Closing line: "Our 4-hour Costco trip, cut to 45 minutes."

## Operating habits
- Shut down with `sudo poweroff` (never yank power). Commit + push often.
- Keep CPU low: MJPEG 720p, motion detection on downscaled grayscale frames, AI only on settled events.
- When something fails, show the operator the exact error in one line and what you're trying next.
