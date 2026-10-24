# ENCLOSURE & POWER: Smart Cart

> **Pi-only build.** The box holds a Raspberry Pi 4B and nothing else. Script: `SmartCartEnclosure/SmartCartEnclosure.py` (Fusion 360, Python API). FEA: `clip_fea.png`.

## What the script creates
Three **components**, each with one body, in a new Fusion design. They're modelled in their assembled positions (the lid sits off to the side), so you can add **joints** between them and use them in **Simulation**. **Base is grounded.**

| Component | What it is | Print |
|---|---|---|
| **Base** | Open tray: Pi press-fit pegs (no screws), cable notches open at the rim (webcam USB on the +X end, USB-C power on the front), **two T-slot bosses** on the back wall, zip-tie slots in the floor as a fallback | ×1, upright |
| **Lid** | Press-fit lid with a locating lip, vents, and a cable slot. The LCD tapes **on top** | ×1, plate-down |
| **Clip** | **Separate, replaceable cart clip**, shown installed in slot 1. It slides down into a boss and gravity locks it | **×4** (2 + 2 spares), **lying on its −X face** |

Size: about 95 × 79 × 30 mm including the bosses and clips. Base + lid + 4 clips fit on one A1 mini plate.

**Webcam mounts are not in yet.** Send me the webcam model and I'll add them with the same helpers.

## Running it
1. Unzip `SmartCartEnclosure.zip` and keep the `.py` and `.manifest` together in that folder.
2. In Fusion (Design workspace): **Utilities → Scripts and Add-Ins** (Shift+S).
3. Click **+** → "Script or add-in from device" (or the green + next to *My Scripts* on older versions) → choose the **folder**.
4. Select it → **Run**. A popup reports the box size and any warnings.
5. **To edit:** **Modify → Change Parameters → User Parameters**. Everything is driven from there (`wire_d`, `wall`, `fit`, `leg_t` …). Parameters are design-wide, so one change updates every component.
6. **To export:** in the browser, expand a component → Bodies → right-click the body → **Save As Mesh** → STL.
7. **Joints:** Base is grounded. To lock the clip in its slot, use **Assemble → As-built Joint → Rigid** between Clip and Base, or a **Slider** joint along Z if you want to animate it sliding in.

> **v2.1 fixes the "over constrained" crash.** Fusion auto-aligns sketch points that share an X or Y, so the script now skips any dimension Fusion has already tied (the popup reports how many; no action needed). A failure popup now names the **step** that broke, so send me the whole popup. This version was dry-run end to end against a mock API but hasn't been run in Fusion yet. If the popup says the root fillet failed, add it by hand with **Modify → Fillet**, radius `root_r`, on the 2 inside corners under the hook arm. Don't skip it; that corner is where the peak strain is.

---

## Cart clip design, driven by FEA
**Why not a simple C-clip?** That was v1, and the FEA killed it. In a full-ring C-clip, the part that carries the load is also the part that has to flex. Its arms are short and stiff, so snapping onto a 6 mm wire puts the plastic at **~10–30% strain**. Printed PLA cracks at around **2–3%**. It would have broken the first time.

**v2: J-hook + barbed latch** (the standard approach for brittle plastics):
- A **rigid hook arm** carries the box's weight; it doesn't need to flex.
- A **long, thin latch** with a **rounded barb** (a built-in lead-in) does the snapping. It deflects 0.7 mm as the wire goes past, then springs back under it.
- The clip is a **separate part printed flat**, so it bends *along* the layers, not across them (the weak direction). If one breaks, reprint a 10-minute clip, not the whole box.

**FEA results** (2D plane stress, printed PLA E = 3 GPa, mesh-converged, ~29k elements):

| Check | Result | Allowable |
|---|---|---|
| Snap-on peak strain (at the latch root fillet) | **1.08%** | ≤1.5% repeated use, ≤2.5% one-time |
| Snap-on push force | **~30 N** (about a 3 kg push, easy by hand) | n/a |
| Hanging, 10 N per clip (~4× box weight) | 4.6 MPa von Mises, **safety factor ~10** | yield ~45 MPa |
| Solver check vs. beam theory | −3% error | n/a |
| Mesh convergence | 1.39% → 1.42% strain (2% change) | n/a |

Sweep: 36 designs (latch thickness × barb interference × seat play). Thin latches with big interference snap, and longer latches reduce strain. Chosen design: `leg_t` 2.0, interference 0.7, `seat_play` 3.

**Wire-size tolerance:** a clip built for `wire_d = 6` fits wires from about **5.3 to 6.5 mm**. For other carts, change `wire_d` and reprint just the clips. Below about 5.5 mm the barb barely holds; use zip ties there.

**Caveats (say these if a judge asks):** this is linear elastic, 2D (the clip is a constant-thickness extrusion, so plane stress is a fair model), with a conservative PLA modulus. The real check is physical: **print one clip, snap it on and off 20 times**, then print the rest.

### Cross-check in Fusion Simulation (and get the pitch screenshots)
Two independent methods agreeing makes a strong slide. About 20 minutes:

1. **New study:** workspace dropdown (top-left, "DESIGN") → **SIMULATION** → **Static Stress** → Create Study.
2. **Isolate the clip:** in the study browser under *Model Components*, right-click the **Base** and **Lid** components → **Exclude from Simulation**. Since they're separate components now, this is one click each. If that option isn't there, use the **Simplify** tab to remove them.
3. **Material:** **Materials → Study Materials** → set Clip to **PLA**. If PLA isn't in the library, create a custom material with E = 3.0 GPa, ν = 0.35, yield = 45 MPa, density 1.24 g/cm³.
4. **Fix the clip:** **Constraints → Structural Constraints → Fixed** → select the spine's back face and the T-tab faces (that's what the boss holds).
5. **Load case 1, snap-on:** **Structural Constraints → Prescribed Displacement** → select the **barb's curved face** → set **Uy = +0.7 mm** (pushing the latch away from the spine), leave the other directions free.
6. **Load case 2, hanging:** **Load Case → Create New**, repeat step 4, then **Loads → Structural Loads → Force = 10 N, +Z** on the **underside of the hook arm** (where the wire sits).
7. **Mesh:** **Mesh → Mesh Settings**, about 3% model-based size, enable curved elements. Add **Local Mesh Control** at ~0.15 mm on the two root fillets.
8. **Solve:** Pre-check (green ✓) → **Solve**. Linear static can solve **locally**. Education accounts generally don't pay for cloud solves either, but pick Local if it asks for credits.
9. **Read results:** switch the plot from *Safety Factor* to **Strain → Equivalent** and to **Stress → Von Mises**. Put a **probe** on the latch root fillet. Expect **~1–1.3% strain** for snap-on (3D usually reads a bit different from 2D; within ~20% counts as agreeing) and **safety factor > 5** when hanging.
10. **Pitch assets:** set the deformation scale to *Adjusted*, then **Animate** and screen-record, or screenshot both cases next to our `clip_fea.png`.

**Stretch "wow" version:** *Nonlinear Static Stress* with a 6 mm cylinder as the wire and real contact, which simulates the snap itself. This takes more setup and may use cloud credits. Only do it if everything else is done.

---

## Before printing (printer slots are scarce)
- **Measure the cart wire** and set `wire_d`. If you can't measure the real cart, **use the zip-tie slots** and don't fuss over the clips.
- **Print one test clip first** (about 10 min): check the slide fit in the boss (`sfit`) and the snap on the wire.
- Base/lid slicer settings: **0.28 mm draft, 2 walls, 10–15% infill**. No supports needed; the bosses are short overhangs.
- Clip slicer settings: **lay it on its −X face, 0.2 mm layers, 100% infill** (it's tiny, and solid is stronger).
- Estimate: about 70 g total, **~2–3 h** for base + lid. If the slicer shows more than 3.5 h, print the base and clips and skip the lid.
- **Get in the queue Friday night.** Keep a cardboard + zip-tie fallback ready.

## Power
**A power bank is the right call; don't over-engineer this.** LiPo, boost, or UPS-HAT setups need soldering (not allowed in the venue) and add risk for no demo payoff.

**Power budget at 5 V:**

| Load | Draw |
|---|---|
| Pi 4 under CV load | ~1.0–1.5 A |
| 2× webcams | ~0.25–0.5 A each |
| LCD | <0.1 A |
| **Total** | **~2–2.5 A (~10–12 W)** |

**What to get:**
- A bank that does **5 V / 3 A on USB-C** (most 15 W+ USB-C banks). The Pi 4 doesn't negotiate PD; it just pulls 5 V. Avoid USB-A-only banks capped at 2.4 A.
- **Use a short, thick USB-C cable.** Thin cables are the #1 cause of undervoltage, which shows up as camera dropouts and resets. Check with `vcgencmd get_throttled`: `0x0` means healthy.
- **About 20,000 mAh gives roughly 4–6 h**; 10,000 mAh gives about 2–3 h. **Bring 2 banks** so one can charge while the other runs.
- If cameras drop out: power the webcams from a **powered USB hub**, or move inference off the Pi (laptop / ASUS GX10).

**Mounting:** the bank is velcro-strapped or zip-tied to the cart next to the box, not inside it. Its cable goes in through the USB-C notch.
