# hardware/cad: iPad mount

`IPadMount/IPadMount.py` is a parametric Fusion 360 script for the zip-tie mount that holds the KART iPad (iPad Pro 11", 2nd gen, no case) on the cart. The iPad sits in landscape on the shopper's side of the handle, facing the shopper. It covers the middle of the handle, so you push the cart by the handle either side of the screen.

**How it holds:**
- **Two attachment points.** Two mirrored brackets each hang on the handle by a printed arch. An arm from the bottom of each bracket reaches the top-basket wire, where a notched pad sits on top of it.
- **It hangs, and gravity holds it.** The arch and the pad notch both open downward. Push or twist the mount any way and it hits the handle or the wire; the only way off is straight up, and the zip ties stop that. The handle and the wire are two different parts of the cart, so they make a triangle and the screen can't rotate around the handle.
- **Spacer.** A bar behind the iPad fixes the gap between the brackets.
- **Taking the iPad out.** It slides down into the two channels from above; lift it straight out to charge it.
- **No screws:** zip ties are the only hardware.

| Component | What it is | Print |
|---|---|---|
| `Bracket_L`, `Bracket_R` | Channel for one short edge of the iPad, an arch over the handle, an arm and gusset, a notched pad on top of the wire | 1 each, lying on the big flat outer face |
| `Spacer` | Bar behind the iPad; slides into a socket on each bracket and is pinned by a zip tie at each end | 1, lying on its wide face |
| `TEST_Profile` | 4 mm slice of the arch, arm and channel: checks the handle and wire fit and the screen angle | first |
| `TEST_Corner` | Bottom corner of one channel: checks the iPad fit | first |
| `REF_*` | Handle, wire and iPad envelopes for checking clearances | don't print |

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

Add `name="value"` pairs to try other numbers, for example `check.py rim_drop="150 mm" tilt="20 deg"`, or `--script=path` to check another version of the script. It takes about half a minute and checks three things:

1. **The script against a mock of Fusion's API** (`check/adsk/`). Every expression must evaluate and every sketch dimension must match its geometry. The fillet, chamfer and export code paths run too.
2. **The same extrusions rebuilt as real solids:**
   - each part is one solid
   - nothing overlaps the iPad, handle, wire or another part
   - the mount slides over the handle and wire and sits down on them
   - it's captured: nudged in any direction or twisted about the handle or the wire, it hits the cart, except straight up
   - the iPad slides in and out from above
   - both zip-tie loops have room
3. **Preview files:** `hardware/cad/stl/preview_*.stl` and `preview.png`. The previews have no fillets or chamfers, which is fine for the fit-test prints. Fusion's own export is the real print file.

It doesn't test Fusion's own geometry kernel (fillets especially), so run the script in Fusion once before the final print.

## Measurements used

| Parameter | Value | Source |
|---|---|---|
| `ipad_w` × `ipad_h` × `ipad_d` | 247.6 × 178.5 × 5.9 mm | Apple spec, iPad Pro 11" (2nd gen) |
| `ipad_r` (corner radius) | 10 mm | estimate: **measure** |
| `bump_zone`, `bump_relief` (rear camera) | 45 mm, 2 mm | estimate: **measure** |
| `handle_d` | 29 mm | ruler: **calipers** |
| `rim_d` (top-basket wire) | 5.5 mm | ruler: **calipers** |
| `rim_c` (handle centre to wire centre) | 155 mm | ruler |
| `rim_drop` (wire centre below the handle centre) | = `rim_c` (straight below) | from your sketch: **confirm with a plumb line** |

**Checking where the wire is (plumb line):** tie your keys to a string, hold the string against the side of the handle level with the middle of the tube, and let the keys hang past the wire. If the string touches the wire, it's straight below. If not, measure the sideways gap from the string to the wire's middle, and the drop from the handle's middle to the wire's middle. The drop is `rim_drop`; `rim_c` is √(gap² + drop²). The mount stays captured with the wire up to about 25° forward of straight below; past that the popup warns you.

## Parameters you'll touch

Every dimension is a User Parameter (Modify → Change Parameters), with a comment on each. The ones that matter most:

| Parameter | Default | What it does |
|---|---|---|
| `fit` | 0.4 mm | Gap per side around the iPad. Raise it if the iPad binds, lower it if it rattles |
| `pad_t` | 0 | Set to 0.2 if you put a layer of electrical tape on the ledges |
| `tilt` | 0° | Screen lean-back from vertical. 15–20° reads better from standing height |
| `v_h` | 70 mm | Where the handle sits behind the screen (up from the iPad's bottom edge). Raise it and the screen sits lower |
| `handle_fit`, `rim_fit` | 0.5, 0.3 mm | Clearance in the arch and the wire notch |
| `lip_w`, `lip_h` | 6 mm | How far the front lips reach over the bezel (bezel ≈ 9 mm) |
| `win_lo`, `win_hi` | 20, 22 mm | Where the side-wall windows start and stop: they keep the speakers, buttons, port and front camera clear |
| `grip` | 30 mm | How far the ledge and back plate reach under the iPad |
| `arm_h`, `arm_t`, `arm_w`, `sad_t` | 16, 10, 24, 6 mm | Arm, arch and pad sizes |
| `sp_v` | 100 mm | Spacer height; keep it above the arch |
| `fil_big` / `fil_med` / `fil_small`, `bed_ch` | 2 / 1 / 0.4, 0.4 mm | Fillet classes and bed chamfer (CAD rule 3). Set `AUTO_FILLET = False` to skip them |

## Print

- **Material:** PETG if you have it (tougher on bumps, doesn't creep in a warm room), otherwise PLA. Print mating parts on the same printer.
- **Brackets:** lie each one on its big flat outer face. 0.2 mm layers, 4 walls, 30% infill, no supports. At the defaults it fits the P1S rotated about 5° on the plate and the AD5M rotated about 30°; the popup gives the angles for your numbers.
- **Spacer:** lie it on its wide face. 0.2 mm layers, 3 walls, 25% infill. It's about 247 mm long: fine on the P1S, diagonal on the AD5M.
- **Test pieces:** 0.2 mm layers, 2 walls, 15% infill.
- **Zip ties:** 4.8 mm wide, at least 200 mm long. You need 6: per bracket one round the handle and one round the wire, plus one through each spacer socket. Bring spares for the charging cable.

## Fit test (print these first)

1. **TEST_Profile** (a thin slice, the quickest print). Hold it a couple of cm high, slide it toward the cart until the arch is over the handle and the pad is over the wire, and set it down.
   - **Pass:** both seat at once without forcing. The arch sits on the tube with no more than about 1 mm of play (the tie takes up the rest). The arm clears everything between the handle and the wire, including the child-seat flap. Hold the iPad's bottom edge in the slice's channel and check you like the screen angle and height.
   - **Fix:** if the notch misses the wire, correct `rim_c` / `rim_drop` by the miss. Arch loose or tight: `handle_d` / `handle_fit`. Angle or height: `tilt` / `v_h`.
2. **TEST_Corner.** Slide the iPad's bottom corner in from above.
   - **Pass:** it slides in by hand and only wiggles a little front to back. The lips sit on the black bezel, not the screen. The corner rests on the ledge. No button gets pressed. Play audio and check the bottom speakers aren't muffled.
   - **Fix:** binds or rattles: `fit`. Lip on the screen: `lip_w` / `lip_h`. A speaker grille covered: lower `win_lo`.
3. **One bracket.** Hang it on, check it against the iPad, then print the second bracket and the spacer.
4. **Whole mount.**
   - **Assemble:** on a table, slide the spacer into both sockets and pin each end with a zip tie through the socket slot. Hold the frame a couple of cm high on the shopper's side of the handle, slide it toward the cart until the arches are over the handle and the pads over the wire, and set it down.
   - **Tie it:** tie each arch: the tie goes up the tunnel behind the back plate, over the arch, down its cart side and back under the tube. Then tie each wire pad: through the pad just above the notch and round under the wire. Drop the iPad in.
   - **Test:** roll the cart over a doorway threshold and stop hard. The iPad must stay seated without rattling, lifting it out must take one hand, and the charger must plug in through the side window. Zip-tie the cable round the arm.
5. **Cameras.** With the mount on, run `hardware/check_cameras.py` and make sure the mount and iPad aren't in any of the three camera views. The brackets sit about 13 cm either side of the handle centre, well inside the basket corners.

**iPad orientation:** put the iPad in with the **button corner up** (top button, volume buttons and rear camera at the top). The bottom long edge then has no buttons on it, and the USB-C port is on the right.
