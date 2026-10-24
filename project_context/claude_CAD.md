# CAD.md: CAD rules & parked to-dos

> ⏸️ **PARKED (Fri night):** the enclosure is optional. Pick this back up only after the core demo works. **Do NOT print the v2.1 clips** (see bug #1 below).

## Rules the team set (apply to every part)
1. **Every part is its own component** (not a loose body), so joints/mates and Simulation work. Ground the main part.
2. **Fully parametric, script-generated** (`SmartCartEnclosure.py`). Every dimension is a User Parameter (Modify → Change Parameters). Units: mm.
3. **Fillet every corner, sized to the corner:** big corners get big fillets, small features get small ones (rule of thumb r ≈ 0.2 × the smaller adjacent face width; concave one size smaller than convex). Mating corners: **male radius ≥ female radius** so parts nest. *Exception:* edges on the build plate get a **0.4 mm chamfer / elephant-foot compensation**, not a fillet (a fillet there is an overhang).
4. **Lid = real press fit:** about **0.1 mm total interference** (0.05 per side) at the lip root, with a **3° lead-in draft** on the lip.
5. **Clips attach to the enclosure with a wedge snap:** a tapered key with **3° draft** driven into a downward-opening pocket. 3° is self-locking (friction angle for PLA on PLA is ~11–19°), so the box's weight drives it tighter and vibration won't back it out. The *snap onto the cart wire* stays the FEA-validated J-hook + barbed latch (about 1.1% strain).
6. **Simulation-backed snap fits:** keep strain ≤1.5% for repeated use and ≤2.5% one-time (printed PLA). Re-run the FEA if `leg_t`, `barb_d`, `seat_play`, or `wire_d` change.
7. **Print orientation:** flex members bend *along* layers (clip lies on its −X face). Avoid unsupported overhangs; prefer features that start on the bed.

## Printers & fits
| Printer | Build volume | XY tolerance to design for |
|---|---|---|
| **Bambu Lab P1S** | 256 × 256 × 256 mm | ~±0.1 mm *(TODO: confirm; Bambu doesn't publish a figure, so check with a test coupon)* |
| **Flashforge Adventurer 5M** (TODO: confirm the "5S" is the 5M or 5M Pro) | 220 × 220 × 220 mm | ~±0.1–0.2 mm *(TODO: confirm with a test coupon)* |

**Print mating parts on the same printer.** Starting fit table (per side), to be tuned with a coupon:

| Fit | Per side | Used for |
|---|---|---|
| Loose / moving | +0.3 mm | n/a |
| Slide | +0.2 mm | clip spine ↔ boss face (`sfit`) |
| Wedge (3° taper) | −0.05 mm nominal; the taper absorbs ±0.15 mm of printer error by changing seat height | clip key ↔ pocket |
| Press | −0.05 mm (0.1 total) | lid lip ↔ box |
| Snap | 0.7 mm barb interference (FEA) | clip latch ↔ cart wire |

## 🐛 Known bugs / redesign queued
1. **v2.1 clip slots are upside-down for hanging.** The slot opens at the top with a floor at the bottom, so the box's weight slides it *off* the clips. **Fix (designed, not yet coded):** move the bosses to the **bottom** of the back wall and give each a **pocket that opens downward** (it prints on the bed face, so no overhang). The clip gets a **foot + tapered key (3°)** under the box. Hang the clips on the cart, then lower the box onto them. Draft params: `key_w 6, key_d 4, key_h 6, key_margin 3, roof_t 2, seat_gap 1.5, foot_t 2.4, pocket_wall 1.6, draft 3°, key_interf 0.05`. Hand calc: max interference when fully seated is about 0.13 mm per side, giving roughly 1% wall strain.
2. Fusion's taper-angle sign convention is unverified. The plan is to **probe it in the script** (extrude a test block, compare face areas, then delete it) rather than guess.
3. Fillet-everything isn't coded yet. Plan: explicit params for assembly-critical corners (box/lid/lip) + an auto-fillet pass (size-classified, convex/concave via `pointContainment`, skipping tangent and bed edges, try/except per group).

## 📏 Measurements & checks still needed (see PARTS.md)
- [ ] **Cart wire diameter** → `wire_d`
- [ ] **Grove LCD v4.0:** width, thickness, mount holes, Grove socket position
- [ ] **Brio 100:** clip grip range (min/max), lens height above the clip
- [ ] **⚡ LCD SDA idle voltage** with the LCD on 5 V. If it's ~5 V, use a level shifter. **Do this before wiring it to the Pi.**
- [ ] Official Pi 4 **DXF** → attach it so I can verify the Pi dimensions
- [ ] One **fit test coupon** per printer (press / slide / wedge) before the real print
