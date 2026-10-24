# PARTS: CAD reference geometry (locked components)

This file is the **source of truth for every dimension the CAD uses.** Each number has a source and a confidence level:
🟢 **Official** (manufacturer drawing) · 🟡 **Vendor spec** (retail listing, usually right) · 🔴 **Measure** (needs a ruler on the real part before it drives a print).

All of these are already **parameters in `SmartCartEnclosure.py`** (Modify → Change Parameters), so updating a measurement there updates the model. The script also builds grey **`REF_` envelope components** (Pi board, USB/Ethernet block, GPIO header) inside the enclosure for collision checks. Don't print those.

---

## 1. Raspberry Pi 4 Model B
*"© Raspberry Pi 2018" on the silkscreen is normal for the Pi 4; the PCB design date is 2018, and it launched in 2019.* Storage: 16 GB microSD (fine for 64-bit Raspberry Pi OS + OpenCV).

| Feature | Value | Param | Conf. |
|---|---|---|---|
| PCB outline | 85 × 56 mm | `pi_l`, `pi_w` | 🟢 |
| Mount holes | 4× Ø2.7 mm (M2.5), 3.5 mm from the edges, 58 × 49 mm spacing | `pi_hole_*` | 🟢 |
| USB-C power centre | 11.2 mm from the −X edge (3.5 + 7.7) | `usbc_x` | 🟢 |
| PCB thickness | ~1.5 mm | `pi_pcb_t` | 🟡 |
| USB/Ethernet stack | ~16 mm above PCB, ~21 mm deep, overhangs the edge ~2.5 mm | `pi_port_*` | 🟡 conservative envelope |
| GPIO header | 2×20, ~8.5 mm above PCB, along the +Y edge | `pi_gpio_h` | 🟡 |

**Clearance check (from the script's geometry):** USB stack top 24.5 mm vs. lid lip 26.0 mm, so **1.5 mm** to spare. Port overhang ends at 91.5 mm vs. the inner wall at 93.0 mm, so **1.5 mm** there too.

**Sources (please check):**
- Official drawing (DXF + PDF): [Raspberry Pi Product Information Portal: Pi 4 Model B](https://pip.raspberrypi.com/categories/545). The DXF is [RP-008342 mechanical drawing](https://pip-assets.raspberrypi.com/categories/545-raspberry-pi-4-model-b/documents/RP-008342-DS-1-raspberry-pi-4-mechanical-drawing.dxf). **No official STEP exists.**
  → **Do this:** download the DXF and attach it here. I'll parse it and check every Pi number above against the real drawing. You can also drop it in Fusion (**Insert → Insert DXF**) on the base floor plane as an overlay.
- 3D model for visuals (community): [Printables: "Raspberry Pi 4B Models and Template" by kaje](https://printables.com/model/252088-raspberry-pi-4b-models-and-template). The author says V2B/V3 are "exact" to external specs, and it includes Onshape links you can export to STEP. Alternative: [GrabCAD: Raspberry Pi 4 Model B](https://cad.grabcad.com/library/raspberry-pi-4-model-b-3) (login required).
  → In Fusion: **Insert → Insert Mesh / Upload STEP**, then a **Rigid joint** from a mount hole to a peg.

## 2. Grove LCD RGB Backlight **v4.0** (16×2, I2C)
| Feature | Value | Param | Conf. |
|---|---|---|---|
| Module size | 80 × 40 × 13.5 mm (an older datasheet says 80 × 36) | `lcd_l/w/h` | 🔴 **measure width + thickness** |
| Mount holes | unknown | n/a | 🔴 **measure: count, Ø, positions** |
| Grove socket position | unknown (on the back) | n/a | 🔴 measure, since the cable slot in the lid has to line up |
| I2C addresses | LCD **0x3E**, RGB backlight **0x62** (v4.0; v5.0 moved it to 0x30) | n/a | 🟢 Seeed wiki |
| Supply | **5 V** (3.3 V support only arrived in v5.0) | n/a | 🟢 Seeed wiki |

⚠️ **Electrical gotcha: v4.0 is a 5 V part and the Pi's I2C pins are 3.3 V only.**
1. Wire **VCC → Pi pin 2 (5 V)**, **GND → pin 6**, **SDA (white) → pin 3**, **SCL (yellow) → pin 5**.
2. **Before connecting SDA/SCL,** power the LCD from 5 V alone and use the MLH **multimeter** to measure SDA→GND.
   - **~0 V or floating:** no 5 V pull-ups, so it's safe to connect directly.
   - **≈5 V:** it has pull-ups to 5 V, which would push 5 V into the Pi. **Use a logic-level shifter** (ask the hardware booth) or have a mentor check it. Don't risk the only Pi.
3. Check it with `i2cdetect -y 1`. You should see **3e** and **62**.

Sources: [Seeed wiki: Grove LCD RGB Backlight](https://wiki.seeedstudio.com/Grove-LCD_RGB_Backlight/) (versions, addresses, voltage) · [Seeed 16×2 family sheet, 80×40×13 mm](https://cdn.ozdisan.com/ETicaret_Dosya/729674_861002.pdf) · [Dexter forum, 80×36×13.5 vs. a caliper reading of 80×40](https://forum.dexterindustries.com/t/rgb-lcd-module-dimensions-and-or-drawing/1536). **No official 3D model found**, so the measured envelope it is.

## 3. Logitech **V-U0072 = Brio 100** webcam (×2)
| Feature | Value | Param | Conf. |
|---|---|---|---|
| Body | 72.9 W × 31.9 H × 66.6 D mm (D includes the folded clip) | `cam_w/h/d` | 🟡 vendor |
| Weight | 75 g | n/a | 🟡 |
| Mount | **Built-in monitor clip, non-removable. NO tripod thread.** | n/a | 🟢 review |
| Video | 1080p30, 58° diagonal FOV, USB-A (USB 2.0), 1.5 m cable | n/a | 🟡 |
| Clip grip range (min–max thickness it clamps) | unknown | n/a | 🔴 **measure** |
| Lens centre height above the clip hinge | unknown | n/a | 🔴 measure |

**Mount strategy:** since there's no thread, **don't model the camera at all.** Print a bracket that clips onto the cart and has a **"fake monitor edge" fin**. The camera's own clip grabs the fin, and its hinge sets the downward tilt. That's robust, tool-free, and only needs the clip grip range measured.

Sources: [V-U0072 = Brio 100 (retailer listing)](https://www.pcsepeti.com/logitech-960-001585-v-u0072-brio-100-full-hd-1080p-gizlilik-kapakli-mikrofonlu-siyah-web-kamerasi-pmu31412) · [SHI spec sheet: dimensions, weight, FOV](https://www.shi.com/Product/46592007) · [TrustedReviews: no tripod thread, integrated clip](https://www.trustedreviews.com/reviews/logitech-brio-100). **No 3D model found.**

**Software notes:** request **MJPEG at 720p** from both cameras to save Pi CPU and USB bandwidth. Plug them into the two **blue USB 3.0 ports**, which run on a separate controller from the USB 2.0 pair.

## 4. Seeed HAT (on hand, not planned)
Probably the *Grove Base Hat for Raspberry Pi* (confirm). **If it ever gets used:** it sits on the GPIO header and adds roughly 10+ mm, which **collides with the lid** at the current `inner_h`. Raise `inner_h` by about 8 mm. It does **not** level-shift I2C, so it doesn't fix the LCD 5 V issue above.

---

## 📏 Measurement checklist (≈10 min with a ruler; the MLH lab has no calipers)
Send me these and I'll update the 🔴 rows and the parameters:
1. **LCD:** width, thickness (glass face → back of the Grove socket), mount holes (count, Ø, centre positions from one corner), Grove socket position.
2. **Brio 100:** the clip's **min and max** grip thickness (clamp it on a book edge and measure the gap), and the lens centre height above the clip.
3. **Cart wire diameter** → `wire_d` (still needed for the clips).
4. **LCD SDA voltage** test (see section 2), before plugging it into the Pi.
