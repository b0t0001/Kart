# hardware/cad: iPad mount

`IPadMount/IPadMount.py` is a parametric Fusion 360 script for the bolted mount that holds the KART iPad (iPad Pro 11", 2nd gen, no case) on the cart. The iPad sits in landscape on the shopper's side of the handle, facing the shopper and leaning back at 40° to the ground. It covers the middle of the handle, so you push the cart by the handle either side of the screen.

**How it holds:**
- **An L, a brace and a cap per side.** The L is one print: one leg is the channel that holds a short edge of the iPad, the other is a straight leg from the bottom of the channel down to a foot that sits on the wire. A curved arch on the back of the channel hangs on the handle, and an upper strut ties the top of the channel to the arch. The **brace** is a separate flat bar bolted across the corner of the L: that's the triangle. The **cap** is a small strap bolted to the foot under the wire. `check.py` draws all three as `profile.png`.
- **Nothing can move once the cap is on.** The foot and the cap hold the wire on every side, and the arch's two sides stop the bracket swinging about the wire. `check.py` nudges it 3 mm every way and turns it 3° about the handle and the wire: every move hits the cart. The only slack is the fit clearance (0.5 mm in the arch, 0.3 mm round the wire), which lets the top of the screen shift about 1 mm.
- **It goes on without forcing anything.** Hold the L about 2 cm high, slide it toward the cart until the arch is over the handle and the foot over the wire, and set it down. The arch and the foot both open downward, so nothing has to flex. The cap then goes straight up under the wire. Nothing passes through the basket mesh.
- **Bolts, not zip ties.** 10-32 × ½" bolts and 10-32 nuts: two per brace, two per cap, 8 of each in all. Each nut drops into a slot in the L that stops it turning, so you only turn the bolt. One zip tie between the two upper struts, behind the iPad, stops the brackets spreading along the handle (see "Along the handle" below).
- **30 mm wide against twisting.** The arch, the strut and the leg are 30 mm wide along the handle. The foot stays 17 mm wide, because it has to fit between the vertical mesh wires.
- **No spacer.** The iPad sets the gap between the brackets.
- **Taking the iPad out.** It slides down into the two channels from above; lift it straight out to charge it.

| Component | What it is | Print |
|---|---|---|
| `Bracket_L`, `Bracket_R` | The L: channel, arch, upper strut, back rib, leg, foot on the wire, two bosses for the brace, nut slots | 1 each, lying on the big flat outer face (about 104 cm³ each) |
| `Brace_L`, `Brace_R` | Flat bar across the L's corner, a bolt at each end (the two are the same part) | 1 each, flat (7 cm³) |
| `Cap_L`, `Cap_R` | Strap under the wire, a bolt either side of it (the two are the same part) | 1 each, flat (3 cm³) |
| `TEST_Profile` | 4 mm slice of the whole L: checks the handle and wire fit, the bar clearance and the screen angle | first |
| `TEST_Corner` | Bottom corner of one channel: checks the iPad fit | first |
| `REF_*` | Handle, wire, middle bars, slanted mesh wires and iPad envelopes for checking clearances | don't print |

## Run it in Fusion

1. In Fusion (Design workspace): **Utilities → Scripts and Add-Ins** (Shift+S).
2. Click **+** → **Script or add-in from device**, and pick the `hardware/cad/IPadMount` folder (it holds the `.py` and the `.manifest`).
3. Select **IPadMount** → **Run**.
   - Each run makes a new design and doesn't touch any open document.
   - A popup lists the parts, which printer beds they fit, the parameters still marked MEASURE, and how many edges got filleted.
   - If it fails, the popup names the step that broke: send the whole popup.
4. STLs export automatically to `hardware/cad/stl/ipadmount_*.stl` (the folder is gitignored). To change the folder, set `STL_DIR` at the top of the script (`''` skips the export).
5. **To change a size:** edit `PARAMS` in the script and re-run, which also re-exports the STLs. Or use **Modify → Change Parameters** in Fusion, then export by hand (right-click the body → **Save As Mesh**).

Layout: X runs along the handle, Y points forward into the cart, Z is up, and the origin is the handle centre.

## Test it without Fusion

```bash
uv run --with manifold3d --with numpy --with matplotlib hardware/cad/check/check.py
```

Add `name="value"` pairs to try other numbers, for example `check.py drop_tops="150 mm" screen_angle="35 deg"`, or `--script=path` to check another version of the script. It takes a minute or two and checks four things:

1. **The script against a mock of Fusion's API** (`check/adsk/`). Every expression must evaluate with the right units (the mock rejects a unit mix-up, or a parameter used before it's defined, the way Fusion does) and every sketch dimension must match its geometry. The fillet, chamfer and export code paths run too.
2. **The same extrusions rebuilt as real solids:**
   - each part is one solid, and every cut actually removes material (Fusion rejects a cut that touches nothing)
   - nothing overlaps the iPad, handle, wire, middle bars, mesh wires or another part
   - the L with its brace bolted on goes on (2 cm high, slide toward the cart, set down) clear of the middle bars and the mesh wires, and the cap goes straight up under the wire past everything
   - every bolt head clears the cart, a driver reaches the cap bolts from outside the cart, and a ½" bolt reaches through each nut (about 1 mm past it)
   - with the cap on, every 3 mm nudge and every 3° turn about the handle or the wire hits the cart
   - the iPad slides in and out from above
3. **Hand calcs** (below): fails if any factor of safety is under 2.
4. **Preview files:** `hardware/cad/stl/preview_*.stl`, `preview.png` (3D) and `profile.png` (the side profile of the L, the brace and the cap with the cart, the iPad and the clearances). The previews have no fillets or chamfers, which is fine for the fit-test prints. Fusion's own export is the real print file.

It doesn't test Fusion's own geometry kernel (fillets especially), so run the script in Fusion once before the final print.

## Hand calcs

`check.py` works these out from first principles for one bracket in the side view, from the solids it just built:
- **Masses.** Half the iPad (473 g) per bracket, at its centre. The bracket, brace and cap are taken as solid PLA (140 g), which is conservative.
- **Supports.** The handle can push the arch any way from the basket side round to the arch's end, never down. The wire can push the foot and cap any way.
- **The weight split.** One bracket is indeterminate by one: load along the handle-to-wire line can go to either support. Both limits are worked out, and each member is checked at its worse one.

| Load case (one bracket) | Handle (N) | Wire (N) | Cap pull (N) | Brace (N) |
|---|---|---|---|---|
| Gravity | 3.7 | 3.8 | 0 | 7 |
| Bump, 3 g | 11.2 | 11.4 | 0 | 21 |
| Finger push 10 N on the top edge (75 % on this bracket) | 13.3 | 6.2 | 0 | 26 |
| Pull 10 N on the top edge | 10.3 | 5.8 | 1.1 | 24 |
| Hand resting on the top edge, 20 N | 23.9 | 21.3 | 0 | 71 |
| Hard stop or jerk, 1 g fore or aft | 5.5 | 3.8 | 0 | 6 |
| Someone lifts the cart by the channel top, 30 N | 9.7 | 28.0 | 24.3 | 100 |

The allowables are for PLA as printed, kept on the low side: 30 MPa for tension, bending and bolt bearing. Every load path stays in the print plane: each part prints lying on its side, so the side view is the layer plane. Steel bolts are taken at 300 MPa in shear. Each line below is the worst case over all the loads.

| Check | Model | FoS |
|---|---|---|
| Arch | the whole handle reaction at the far end of a cantilevered band | 12 |
| Brace, axial | the leg pinned at the corner and held only by the brace (so the brace carries everything) | 22 |
| Brace, buckling | pinned ends, about its thin direction | 18 |
| Brace bolts, bearing in the L | only the 2.5 mm skin next to the nut | 3.6 |
| Back plate and web, brace top to the arch | bending + axial along the section | 5.8 |
| Leg, brace joint to the foot | a cantilever off the brace joint | 6.9 |
| Upper strut | axial and buckling | 89 and 504 |
| Channel above the handle | strut acting | 7.0 |
| Cap | bends between its two bolts | 6.5 |
| Cap bolts | shear, and bearing in the cap and in the foot | 30+ |

So stress isn't what limits this mount: fit, stiffness and the way it goes on are. Two lines show what the triangles buy. With the brace left off, the leg at the corner would still reach FoS 6.4. With the upper strut left off, the channel above the handle would drop to FoS 2.0.

Every FoS stays at 2 or above across screen angles from 35° to 45° and handle heights (`v_h`) from 60 to 80 mm. The tightest corner is 35° with `v_h` at 60 mm, where the back plate and web come down to 2.2.

## Measurements used

Side view of the cart, measured with horizontal and vertical lines (your drawing). All eyeballed, with some parallax.

| Parameter | Value | What it is |
|---|---|---|
| `ipad_w` × `ipad_h` × `ipad_d` | 247.6 × 178.5 × 5.9 mm | Apple spec, iPad Pro 11" (2nd gen) |
| `ipad_g` | 473 g | Apple spec, for the hand calcs |
| `ipad_r`, `bump_zone`, `bump_relief` | 10, 45, 2 mm | estimates (corner radius, rear camera) |
| `handle_d` | 29 mm | handle tube |
| `rim_d` | 5.5 mm | the wire the foot sits on |
| `drop_tops` | 155 mm | top of handle straight down to top of the wire |
| `gap_edges` | 36 mm | horizontal, handle edge to the same-side edge of the wire |
| `rim_side` | 1 | wire is offset toward the basket (assumed; −1 = toward the shopper, not supported) |
| `bar1_drop`, `bar1_w` × `bar1_h` | 63 mm, 8 × 3.5 mm | upper middle bar: really two wires side by side, modelled as a block |
| `bar2_drop`, `bar2_d` | 110 mm, 3.5 mm | lower middle bar |
| `mesh_x0`, `mesh_pitch`, `mesh_d` | 60, 43, 3.5 mm | slanted mesh wires in the handle-wire plane: the first 60 mm from the handle centre, then every 43 mm, mirrored each side |

From these the script works out the wire's centre: **24 mm toward the basket and 143 mm below the handle's centre**, 145 mm apart and about 10° off vertical. The middle bars are assumed to sit on the line between the handle and the wire.

**How accurate do these need to be?** The L clears the middle bars by 22 mm or more (see `profile.png`), so those numbers can be well off. Each foot sits between the mesh wires at 103 and 146 mm from the handle centre: about 6.4 mm clear of the inner one, and the cap's bolt heads 5.2 mm clear of the outer one. If the mesh is really more than ~5 mm off those numbers, they touch: the popup warns, and changing `hook_w` buys room. (The arch sits on top of the handle and the leg and brace stay on your side of the mesh, so their 30 mm width doesn't matter there.) On the way in, the top of the foot passes about 9 mm under the lower middle bar, so lift the L only as much as the arch needs to clear the handle (about 2 cm). If the gap between that bar and the wire is really 9 mm or more smaller than measured, the foot catches it (`check.py` fails at `drop_tops="145 mm"`). The handle-to-wire spacing (`drop_tops`, `gap_edges`) has to be right within about 1 mm, because the arch and the foot are both rigid. Print `TEST_Profile` first: if the foot misses the wire, correct `drop_tops` / `gap_edges` by the miss and re-run.

**Along the handle**, only friction holds each bracket, and the mesh wires either side of its foot stop the slide: about 6 mm in and 5 mm out. The side lips cover 5.6 mm of bezel. So one bracket slid all the way out still leaves the lip on, but both slid out with the iPad pushed to one side would not. The zip tie between the upper struts stops that.

## Parameters you'll touch

Every dimension is a User Parameter (Modify → Change Parameters), with a comment on each. The ones that matter most:

| Parameter | Default | What it does |
|---|---|---|
| `fit` | 0.4 mm | Gap per side around the iPad. Raise it if the iPad binds, lower it if it rattles |
| `pad_t` | 0 | Set to 0.2 if you put a layer of electrical tape on the ledges |
| `screen_angle` | 40° | Screen angle to the ground (90° = vertical). 35–45° reads well standing at the cart; `tilt` follows from it |
| `v_h` | 70 mm | Where the handle sits behind the screen (up from the iPad's bottom edge). Raise it and the screen sits lower |
| `handle_fit`, `rim_fit` | 0.5, 0.3 mm | Clearance in the arch, and round the wire in the foot and cap |
| `lip_w`, `lip_h` | 6 mm | How far the front lips reach over the bezel (bezel ≈ 9 mm) |
| `win_lo`, `win_hi` | 20, 22 mm | Where the side-wall windows start and stop: they keep the speakers, buttons, port and front camera clear |
| `grip` | 30 mm | How far the ledge and back plate reach under the iPad |
| `arm_w`, `strut_t` | 30, 30 mm | Arch, strut and leg width along the handle (twist resistance) |
| `strut_w`, `rib_d` | 12, 8 mm | Strut and leg width in the side view; back rib depth at the channel bottom |
| `top_v`, `top_a0`, `top_a1` | iPad height − 25 mm, 25°, 70° | Where the upper strut meets the channel and lands on the arch |
| `j_drop`, `leg_f` | 4 mm, 0.5 | Brace ends: the top joint this far below the handle centre (up the screen), the bottom one this fraction down the leg |
| `brace_t`, `brace_w`, `boss_d` | 6, 12, 18 mm | Brace thickness and width, and the boss round each brace bolt |
| `hook_w` | 17 mm | Foot width: has to fit between the mesh wires (the popup warns if it doesn't) |
| `cap_t`, `cap_wall`, `cb_dz` | 6, 5, 8.5 mm | Cap thickness, cap material under the wire, cap bolts' height above the wire |
| `bolt_len`, `nut_af`, `nut_t`, `nut_s` | 12.7, 9.53, 3.18, 2.5 mm | Hardware. `brace_t` (or `cap_t`) + `nut_s` + `nut_t` has to leave about 0.8 mm of bolt past the nut: the popup and `check.py` both check it |
| `sad_t` | 6 mm | Arch wall |
| `fil_big` / `fil_med` / `fil_small`, `bed_ch` | 2 / 1 / 0.4, 0.4 mm | Fillet classes and bed chamfer (CAD rule 3). Set `AUTO_FILLET = False` to skip them |

## Print

- **Material:** PETG if you have it (tougher on bumps, doesn't creep in a warm room), otherwise PLA. Print mating parts on the same printer.
- **The L (`Bracket_L`, `Bracket_R`):** lie each one on its big flat outer face. 0.2 mm layers, 4 walls, 20–30% infill, no supports. The nut slots are small bridges, and they print fine without support. It fits the P1S as is, and the AD5M rotated about 36° on the plate (the popup gives the angle for your numbers).
- **Brace and cap:** lie them flat. 0.2 mm layers, 4 walls, 40% infill: they're small and the bolts bear on them.
- **Test pieces:** 0.2 mm layers, 2 walls, 15% infill.
- **Hardware:** 8 × 10-32 × ½" bolts (socket or pan head), 8 × 10-32 hex nuts (⅜" across flats), 1 zip tie (4.8 mm wide, 200 mm+) for between the upper struts, plus spares for the charging cable.

## Fit test (print these first)

1. **TEST_Profile** (a thin slice, the quickest print). Hold it 2 cm above its spot, slide it toward the cart until the arch is over the handle and the foot over the wire, and set it down.
   - **Pass:** it seats on both without forcing and hangs there by itself. The arch sits on the tube with no more than about 1 mm of play. The foot straddles the wire. It clears the two middle bars and anything else between the handle and the wire. Hold the iPad's bottom edge in the slice's channel and check you like the screen angle and height.
   - **Fix:** if the foot misses the wire, correct `drop_tops` / `gap_edges` by the miss. If it touches a middle bar, correct `bar1_drop` / `bar2_drop`. Arch loose or tight: `handle_d` / `handle_fit`. Angle or height: `screen_angle` / `v_h`.
2. **TEST_Corner.** Slide the iPad's bottom corner in from above.
   - **Pass:** it slides in by hand and only wiggles a little front to back. The lips sit on the black bezel, not the screen. The corner rests on the ledge. No button gets pressed. Play audio and check the bottom speakers aren't muffled.
   - **Fix:** binds or rattles: `fit`. Lip on the screen: `lip_w` / `lip_h`. A speaker grille covered: lower `win_lo`.
3. **One bracket set** (L + brace + cap). Assemble and hang it as below, check it against the iPad, then print the second set.
4. **Whole mount.**
   - **At the bench:** drop a nut into each of the L's four slots (the two by the brace bosses and the two on top of the foot). Lay the brace on the L's outer face and bolt it on (bolt heads on the brace). Snug, not tight: about a quarter turn after it seats.
   - **Hang it:** hold the L 2 cm high, about 13 cm from the handle's centre, slide it toward the cart until the arch is over the handle and the foot is over the wire, and set it down. The foot's nut slots open upward, so their nuts stay put.
   - **Cap it:** push the cap up under the wire, against the outside of the foot, and bolt it on (heads outside). Do the other side, drop the iPad in from above (it sets the spacing), and zip-tie the two upper struts together behind the iPad, snug.
   - **Test:** roll the cart over a doorway threshold and stop hard. The iPad must stay seated without rattling, lifting it out must take one hand, and the charger must plug in through the side window. Zip-tie the cable to the leg.
5. **Cameras.** With the mount on, run `hardware/check_cameras.py` and make sure the mount and iPad aren't in any of the three camera views. The brackets sit about 13 cm either side of the handle centre, well inside the basket corners.

**iPad orientation:** put the iPad in with the **button corner up** (top button, volume buttons and rear camera at the top). The bottom long edge then has no buttons on it, and the USB-C port is on the right.
