# hardware/cad: iPad mount

`IPadMount/IPadMount.py` is a parametric Fusion 360 script for the zip-tie mount that holds the KART iPad (iPad Pro 11", 2nd gen, no case) on the cart. The iPad sits in landscape on the shopper's side of the handle, facing the shopper and leaning back at 40° to the ground. It covers the middle of the handle, so you push the cart by the handle either side of the screen.

**How it holds:**
- **Two attachment points.** Two mirrored brackets each hang on the handle by a printed arch that opens downward. Below it, a web runs down beside the two bars between the handle and the wire (staying on your side of them), and a leg reaches a hook that wraps the wire from your side, opening toward the basket. A brace ties the bottom of the iPad channel to the arch. Nothing passes through the basket mesh.
- **30 mm wide against twisting.** The arch and the web are 30 mm wide along the handle; the web has a lightening window, so it's a stiff frame rather than a slab. The hook stays 17 mm wide, because it has to fit between the vertical mesh wires.
- **Gravity puts it on and holds it.** Hang the arch on the handle with the bottom swung toward you and let go: the screen's weight swings the hook onto the wire. After that the hook's jaws stop it lifting and the arch stops it sliding. The only free move is swinging the screen up toward you, which lifts the weight, so gravity holds it; the zip ties back it up. The handle and the wire are two different parts of the cart, so they make a triangle and the screen can't rotate around the handle.
- **No spacer needed.** The iPad sets the gap between the brackets, and a zip tie chained between the two socket slots behind it stops them spreading. (A printed spacer is still there if you want it: `BUILD_SPACER = True`.)
- **Taking the iPad out.** It slides down into the two channels from above; lift it straight out to charge it.
- **No screws:** zip ties are the only hardware.

| Component | What it is | Print |
|---|---|---|
| `Bracket_L`, `Bracket_R` | Channel for one short edge of the iPad, an arch over the handle, a web and leg that stay clear of the middle bars, a hook round the wire | 1 each, lying on the big flat outer face |
| `Spacer` | Optional (`BUILD_SPACER`): bar between the two sockets | only if you want it, lying flat |
| `TEST_Profile` | 4 mm slice of the arch, web, leg and channel: checks the handle and wire fit, the bar clearance and the screen angle | first |
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

Add `name="value"` pairs to try other numbers, for example `check.py drop_tops="150 mm" tilt="20 deg"`, or `--script=path` to check another version of the script. It takes about half a minute and checks three things:

1. **The script against a mock of Fusion's API** (`check/adsk/`). Every expression must evaluate with the right units (the mock rejects a unit mix-up the way Fusion does) and every sketch dimension must match its geometry. The fillet, chamfer and export code paths run too.
2. **The same extrusions rebuilt as real solids:**
   - each part is one solid, and every cut actually removes material (Fusion rejects a cut that touches nothing)
   - nothing overlaps the iPad, handle, wire, middle bars, mesh wires or another part
   - the arch goes over the handle and the hook swings onto the wire, clear of the middle bars and mesh wires
   - it's captured: nudged 3 mm any way or turned 3° about the handle or the wire, it either hits the cart or lifts the weight (so gravity holds it)
   - the iPad slides in and out from above
   - both zip-tie loops have room
3. **Preview files:** `hardware/cad/stl/preview_*.stl` and `preview.png`. The previews have no fillets or chamfers, which is fine for the fit-test prints. Fusion's own export is the real print file.

It doesn't test Fusion's own geometry kernel (fillets especially), so run the script in Fusion once before the final print.

## Measurements used

Side view of the cart, measured with horizontal and vertical lines (your drawing). All eyeballed, with some parallax.

| Parameter | Value | What it is |
|---|---|---|
| `ipad_w` × `ipad_h` × `ipad_d` | 247.6 × 178.5 × 5.9 mm | Apple spec, iPad Pro 11" (2nd gen) |
| `ipad_r`, `bump_zone`, `bump_relief` | 10, 45, 2 mm | estimates (corner radius, rear camera) |
| `handle_d` | 29 mm | handle tube |
| `rim_d` | 5.5 mm | the wire the pad sits on |
| `drop_tops` | 155 mm | top of handle straight down to top of the wire |
| `gap_edges` | 36 mm | horizontal, handle edge to the same-side edge of the wire |
| `rim_side` | 1 | wire is offset toward the basket (assumed; −1 = toward the shopper, not supported) |
| `bar1_drop`, `bar1_w` × `bar1_h` | 63 mm, 8 × 3.5 mm | upper middle bar: really two wires side by side, modelled as a block |
| `bar2_drop`, `bar2_d` | 110 mm, 3.5 mm | lower middle bar |
| `mesh_x0`, `mesh_pitch`, `mesh_d` | 60, 43, 3.5 mm | slanted mesh wires in the handle-wire plane: the first 60 mm from the handle centre, then every 43 mm, mirrored each side |

From these the script works out the wire's centre: **24 mm toward the basket and 143 mm below the handle's centre**, 145 mm apart and about 10° off vertical. The middle bars are assumed to sit on the line between the handle and the wire.

**How accurate do these need to be?** The bracket keeps `bar_clear` (6 mm) away from the middle bars, so those can be off by a few mm. Each bracket's wire hook sits between the mesh wires at 103 and 146 mm from the handle centre, about 6.5 mm clear of the inner one and 16 mm clear of the outer one. If the first mesh wire is really more than ~65 mm out, they touch: the popup warns, and narrowing `hook_w` buys room. (The arch sits on top of the handle and the web stays on your side of the mesh, so their 30 mm width doesn't matter there.) The handle-to-wire spacing (`drop_tops`, `gap_edges`) has to be right within about 1 mm, because the arch and the hook are both rigid. Print `TEST_Profile` first: if the hook misses the wire, correct `drop_tops` / `gap_edges` by the miss and re-run.

## Parameters you'll touch

Every dimension is a User Parameter (Modify → Change Parameters), with a comment on each. The ones that matter most:

| Parameter | Default | What it does |
|---|---|---|
| `fit` | 0.4 mm | Gap per side around the iPad. Raise it if the iPad binds, lower it if it rattles |
| `pad_t` | 0 | Set to 0.2 if you put a layer of electrical tape on the ledges |
| `screen_angle` | 40° | Screen angle to the ground (90° = vertical). 35–45° reads well standing at the cart; `tilt` follows from it |
| `v_h` | 70 mm | Where the handle sits behind the screen (up from the iPad's bottom edge). Raise it and the screen sits lower |
| `handle_fit`, `rim_fit` | 0.5, 0.3 mm | Clearance in the arch and the wire notch |
| `bar_clear` | 6 mm | Gap kept between the bracket and the middle bars |
| `lip_w`, `lip_h` | 6 mm | How far the front lips reach over the bezel (bezel ≈ 9 mm) |
| `win_lo`, `win_hi` | 20, 22 mm | Where the side-wall windows start and stop: they keep the speakers, buttons, port and front camera clear |
| `grip` | 30 mm | How far the ledge and back plate reach under the iPad |
| `arm_w`, `web_t` | 30, 30 mm | Arch and web width along the handle (twist resistance) |
| `hook_w` | 17 mm | Wire hook width: has to fit between the mesh wires (the popup warns if it doesn't) |
| `arm_t`, `arm_h`, `sad_t` | 8, 16, 6 mm | Leg and brace width, leg height, arch wall |
| `web_hole` | 0.7 | Lightening window in the web, as a fraction of its size (0 = solid) |
| `sp_v` | 100 mm | Socket (zip-tie anchor) height; keep it above the arch |
| `fil_big` / `fil_med` / `fil_small`, `bed_ch` | 2 / 1 / 0.4, 0.4 mm | Fillet classes and bed chamfer (CAD rule 3). Set `AUTO_FILLET = False` to skip them |

## Print

- **Material:** PETG if you have it (tougher on bumps, doesn't creep in a warm room), otherwise PLA. Print mating parts on the same printer.
- **Brackets:** lie each one on its big flat outer face. 0.2 mm layers, 4 walls, 20–30% infill, no supports. At the defaults it fits the P1S as is and the AD5M rotated about 66° on the plate; the popup gives the angles for your numbers. Each is about 180 cm³ of solid (roughly 100 g at those settings), mostly the 30 mm web: raise `web_hole` or lower `web_t` for a faster print.
- **Test pieces:** 0.2 mm layers, 2 walls, 15% infill.
- **Zip ties:** 4.8 mm wide, at least 200 mm long. You need 5–6: per bracket one round the handle and one round the wire, plus one or two chained between the socket slots behind the iPad (about 260 mm apart). Bring spares for the charging cable.

## Fit test (print these first)

1. **TEST_Profile** (a thin slice, the quickest print). Hang the arch on the handle with the bottom swung toward you, then let it swing in until the hook takes the wire.
   - **Pass:** the hook seats on the wire without forcing, and the slice hangs there by itself. The arch sits on the tube with no more than about 1 mm of play (the tie takes up the rest). The web and leg clear the two middle bars and anything else between the handle and the wire. Hold the iPad's bottom edge in the slice's channel and check you like the screen angle and height.
   - **Fix:** if the hook misses the wire, correct `drop_tops` / `gap_edges` by the miss. If it touches a middle bar, correct `bar1_drop` / `bar2_drop` or raise `bar_clear`. Arch loose or tight: `handle_d` / `handle_fit`. Angle or height: `tilt` / `v_h`.
2. **TEST_Corner.** Slide the iPad's bottom corner in from above.
   - **Pass:** it slides in by hand and only wiggles a little front to back. The lips sit on the black bezel, not the screen. The corner rests on the ledge. No button gets pressed. Play audio and check the bottom speakers aren't muffled.
   - **Fix:** binds or rattles: `fit`. Lip on the screen: `lip_w` / `lip_h`. A speaker grille covered: lower `win_lo`.
3. **One bracket.** Hang it on, check it against the iPad, then print the second bracket.
4. **Whole mount.**
   - **Hang them:** hang each bracket's arch on the handle with its bottom swung toward you, about 13 cm either side of the handle's centre, and let it swing in onto the wire. Drop the iPad in from above: it sets the spacing.
   - **Tie it:** tie each arch: up the tunnel behind the back plate, over the arch, down its cart side and back under the tube. Tie each hook: through the hook behind the wire and round the wire's basket side. Chain a zip tie (or two) between the two socket slots behind the iPad and pull it snug, not tight.
   - **Test:** roll the cart over a doorway threshold and stop hard. The iPad must stay seated without rattling, lifting it out must take one hand, and the charger must plug in through the side window. Zip-tie the cable round the leg.
5. **Cameras.** With the mount on, run `hardware/check_cameras.py` and make sure the mount and iPad aren't in any of the three camera views. The brackets sit about 13 cm either side of the handle centre, well inside the basket corners.

**iPad orientation:** put the iPad in with the **button corner up** (top button, volume buttons and rear camera at the top). The bottom long edge then has no buttons on it, and the USB-C port is on the right.
