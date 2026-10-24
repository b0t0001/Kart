# PI_SETUP: Raspberry Pi 4 headless setup (no monitor, no VNC, no phone hotspot)

**The plan:** flash the SD card from a laptop with everything preconfigured (Wi-Fi, SSH, username), boot the Pi with no screen, then **program it from your laptop over SSH using VS Code Remote-SSH**. It feels like editing local files, but the code runs on the Pi.

**Order:** network → flash → boot → SSH → setup → **webcams** → (later) LCD.

## What you need
- Laptop with **Windows** + microSD reader ✅
- 16 GB microSD, Pi 4, **USB-C power** (5 V / 3 A)

## Network: make the LAPTOP the hotspot
Hackathon Wi-Fi often blocks devices from talking to each other (client isolation), so your laptop may not be able to reach the Pi on it. Fix: **the Windows laptop hosts its own hotspot** and shares its internet with it.
- The Pi still gets internet (for installs and AI APIs), through the laptop.
- The laptop shows the Pi's IP directly, so there's no guessing.
- The **phone can join the same hotspot for the demo**, so the phone app can reach the Pi.

**Set it up (Windows 10/11):** Settings → **Network & internet → Mobile hotspot**
1. *Share my internet connection from:* **Wi-Fi** (the venue Wi-Fi the laptop is on).
2. **Edit / Properties:** name `kart-net`, set a password (8+ characters), and set **Band: 2.4 GHz** if that option exists.
3. Toggle **Mobile hotspot → On**. The page has a **"Devices connected"** list with IP addresses; that's where the Pi will show up.

> If the toggle is greyed out or won't turn on, your Wi-Fi adapter can't host a hotspot while connected. Fallbacks, in order:
> - **(a)** Put the **venue Wi-Fi** in Imager instead (SSID **Cal Hacks 13.0**, password **hackers!**) and try SSH. It might just work.
> - **(b)** Use an **Ethernet cable from the laptop straight to the Pi** (a USB-Ethernet adapter works if the laptop has no port). Then `ssh jamwan@smartcart.local` works with no Wi-Fi at all. That's good for setup, but the Pi has no internet that way.
> - **(c)** A teammate's phone hotspot.

## Step 1: Flash the SD card (~10 min)
1. On the laptop, install **Raspberry Pi Imager** from raspberrypi.com/software.
2. Insert the SD card → open Imager.
3. **Device:** Raspberry Pi 4.
4. **OS:** Raspberry Pi OS (other) → **Raspberry Pi OS Lite (64-bit)**. Lite has no desktop, which leaves more CPU for computer vision.
5. **Storage:** your SD card (double-check it's not another drive).
6. When it asks to **customise / "Edit settings"** (older Imager: a popup after Next; newer: wizard steps), set:
   - **Hostname:** `smartcart`
   - **Username:** `jamwan` (password: ask the team, it is deliberately not written in any file)
   - **Wi-Fi:** `kart-net` + the hotspot password (not written here), **Wi-Fi country: US**
   - **Locale/timezone:** America/Los_Angeles
   - **Services → Enable SSH → use password authentication**
7. Write → wait → eject.

## Step 2: First boot (~3 min)
1. Laptop hotspot **on**. SD card in the Pi, plug in power. No monitor or keyboard needed.
2. Wait **2–3 minutes** (the first boot resizes the disk and reboots once).
3. Watch **Mobile hotspot → Devices connected** for `smartcart`, and note its **IP address**.

## Step 3: Connect (PowerShell on the laptop)
```powershell
ssh jamwan@smartcart.local      # or: ssh jamwan@<IP from the hotspot page>
```
Type `yes` to trust it, then your password. You're in.
- **Pi never shows up after 5 min?** Usually a Wi-Fi name/password typo. Re-flash and retype them carefully.

## Step 4: One-time setup on the Pi (~10–15 min, mostly waiting)
```bash
sudo apt update && sudo apt full-upgrade -y
sudo apt install -y git python3-venv python3-opencv v4l-utils
python3 -m venv --system-site-packages ~/venv        # Pi OS requires venvs for pip installs
echo 'source ~/venv/bin/activate' >> ~/.bashrc && source ~/.bashrc
```
Add the venue Wi-Fi as a backup network (the Pi picks whichever is available):
```bash
sudo nmcli dev wifi connect "Cal Hacks 13.0" password "hackers!"
```

## Step 5: Program it from your laptop (VS Code Remote-SSH)
1. Install **VS Code** + the **Remote - SSH** extension.
2. Click the **><** button (bottom-left) → **Connect to Host** → `jamwan@smartcart.local` (or `jamwan@<IP>`) → password.
3. **Open Folder** → `/home/jamwan`. Now you edit files on the Pi, and the VS Code terminal runs **on the Pi**.
4. Code lives in a **GitHub repo**: `git clone` it on the Pi, and push/pull between teammates.

## Step 6: Webcams (first hardware milestone)
Plug both Brio 100s into the **blue USB 3.0 ports**, then:
```bash
v4l2-ctl --list-devices          # should list 2 cameras (each usually has 2 /dev/video nodes)
```
```bash
python3 -c "
import cv2
for i in (0, 2):
    cap = cv2.VideoCapture(i)
    cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*'MJPG'))
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1280); cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)
    ok, img = cap.read(); print('cam', i, 'OK' if ok else 'FAIL', img.shape if ok else '')
    if ok: cv2.imwrite(f'cam{i}.jpg', img)
"
```
Then click `cam0.jpg` / `cam2.jpg` in VS Code's file tree to see the frames, no monitor needed. If a camera says FAIL, try index 1 or 3, whatever `v4l2-ctl` showed.

## Later: LCD (after the webcams work)
1. **First** do the 5 V SDA voltage check in PARTS.md. Don't plug it into the Pi before that.
2. Then: `sudo raspi-config nonint do_i2c 0 && sudo apt install -y i2c-tools`, wire it (PARTS.md pinout), and run `i2cdetect -y 1`. You should see **3e** and **62**.

## Habits that save the demo
- **Shut down properly:** `sudo poweroff`, wait for the green LED to stop, *then* unplug.
- **Undervoltage check:** `vcgencmd get_throttled` should print `0x0`.
- **Push code to GitHub often**, at least once it works on Saturday night.
- **Demo-day network:** laptop hotspot on, Pi and phone both on `kart-net`. Test this exact setup before judging.
