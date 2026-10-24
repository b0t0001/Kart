# Cal Hacks 13.0: Bill of Materials

> **Hardware decision: Raspberry Pi 4 only.** No Arduino. The Pi runs the webcams, the LCD (I2C via jumper wires), and any GPIO extras. Section 1 is the build list; everything after it is what's *available* if plans change.

## Hard constraints
- **No soldering in the venue, and no irons provided.** Everything has to be breadboard, jumper, Grove, or screw-terminal. Pick parts with headers already attached.
- Rental booth opens **Fri 6 PM** (after Opening Ceremony). **Everything goes back by Sun 2 PM.** Go early, since popular parts run out.
- 3D prints are **capped at 3.5 hrs** and there's a queue across 5 printers. Get the enclosure into the queue early.
- Specific requests: **Hardware Request Form** (linked in the guide). Full inventory will be listed in the Hackathons @ Berkeley app.

---

## 1. BUILD LIST (what we're actually using)
> 🔒 **Locked components.** CAD reference geometry, sources, and the measurement checklist are in **PARTS.md**.

| Role | Part (exact model) | Source | Status |
|---|---|---|---|
| Brain | 🔒 **Raspberry Pi 4 Model B** (PCB "© 2018") | Acquired | ✅ |
| Storage | 🔒 **16 GB microSD** (64-bit Raspberry Pi OS) | Acquired | ✅ |
| Cameras | 🔒 **2× Logitech Brio 100 (V-U0072)**: 1080p30, USB-A, built-in clip, no tripod thread | Acquired | ✅ |
| On-cart display | 🔒 **Seeed Grove LCD RGB Backlight v4.0** (16×2, I2C 0x3E/0x62, **5 V part**; check SDA voltage before wiring, see PARTS.md) | Acquired (OLED ran out) | ✅ |
| HAT (spare) | Seeed HAT (likely Grove Base Hat). **Not planned**; it would collide with the lid | Acquired | n/a |
| Setup cables | micro-HDMI → HDMI (first boot only, or go headless over SSH) | MLH Lab / booth | ☐ |
| Voice I/O | Webcam mic + **JBL Go 3** speaker, or just the phone | MLH Lab | ☐ |
| Power | **USB-C power bank, 5 V / 3 A**, ×2 (one charging) + short thick USB-C cable | Ours | ☐ |
| Enclosure | 3D-printed Base + Lid + **4 clips** (PLA) | Print station | ☐ |
| Mounting fallback | Zip ties, velcro straps (for the power bank), double-sided tape (LCD) | Ours | ☐ |
| Wiring | Grove → female jumper cable (or Grove cable + 4 F/F jumpers) for the LCD → Pi pins 2/3/5/6 | MLH Lab | ☐ |
| Tools | Multimeter (LCD 5 V check), ruler (PARTS.md measurements) | MLH Lab | ☐ |
| Maybe | Logic-level shifter (only if the LCD's SDA idles at ~5 V) | Booth / mentors | ☐ |
| Demo props | Cart / basket on wheels, 10–15 real grocery items, printed aisle signs | Ours | ☐ |

Not in the build: the Arduino kit. The IR emitter/receiver are **optional demo flair** only, wired to Pi GPIO if used. Item tracking uses camera snapshot-diff, not a beam break (see SCOPE.md).

## 2. Our own kit (available, not in the core build)
| Part | Notes |
|---|---|
| Arduino kit (board + misc. components) | Not used, since we're Pi-only |
| IR emitter (LED) + IR receiver | Optional. Can work on the Pi via GPIO (`ir-keytable` / gpio-ir overlay) |

## 3. Cal Hacks Hardware Rental Booth
| Part | Notes |
|---|---|
| Arduino Uno kits | Not needed |
| Raspberry Pi (incl. HDMI cable + microSD) | The model isn't listed; we need a **Pi 4** (the enclosure is sized for it) |
| Raspberry Pi Pico | |
| ESP32 | |
| MPU6050 | 6-axis IMU (I2C). Could detect cart motion/bumps |
| Assorted common sensor modules | The exact list will be in the app |

## 4. MLH Hardware Lab
**Compute / peripherals:** Raspberry Pi 4B kits · Arduinos + Grove Base Shields · Logitech webcams (built-in mics) · Google Nest Mini · JBL Go 3 speaker · *Mentioned in the guide but not on the MLH list:* SenseCAP Indicator, Echo Show, Echo Dot

**Grove modules (no soldering; on the Pi use jumpers or a Grove HAT if available)**
| Input / sensing | Output / actuation |
|---|---|
| Touch sensor | Buzzer |
| Button | LED socket kit |
| Micro switch | LCD screen |
| Rotary angle sensor | 7-segment alphanumeric display |
| Thumb joystick | Servo |
| Sound sensor | Stepper motor |
| Light sensor | Stepper + driver |
| UV sensor | Motor/servo driver board |
| Temperature + barometer | |
| Moisture sensor | |
| Air quality sensor | |
| 3-axis digital accelerometer | |
| I2C color sensor | |
| Ultrasonic distance sensor | |
| Infrared reflective sensor | |
| NFC/RFID tag board | |

**Other:** brushless DC motors, Grove cables · **Passives & wiring:** jumper wires (F/F, M/F, M/M), ceramic capacitors, resistor kit, breadboards · **Tools:** wire stripper, wire cutter, tweezers, multimeter, needle-nose pliers

## 5. Special hardware
| Item | Availability |
|---|---|
| ASUS Ascent GX10 (×30) | Rent at the ASUS table. Fallback for offloading vision inference if the Pi is too slow |
| Seeed reBot robot arm | Application closed Thu 10/22, so assume it's unavailable |
| 3D printers (×5, PLA) | Queue form; 3.5 hr max per print |
