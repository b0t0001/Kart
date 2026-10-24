# hardware/

Scripts that only make sense on the real cart (Raspberry Pi + 2 Brios). The CV code itself lives in `pi/`.

| File | Run where | What it does |
|---|---|---|
| `setup_pi.sh` | Pi (or `ssh jamwan@smartcart.local 'bash -s' < hardware/setup_pi.sh`) | apt OpenCV/NumPy, `~/venv` (`--system-site-packages`), `pi/requirements-pi.txt` + pytest, clones the repo to `~/kart`. Re-runnable; run again when `pi/requirements-pi.txt` changes. |
| `sync_pi.sh` | laptop | `git pull` here, then fast-forward `~/kart` on the Pi |
| `check_cameras.py` | Pi | Streams both cams at once (MJPEG 1280×720), prints fps / brightness / sharpness, saves `hardware/out/cam0.jpg`, `cam1.jpg` |
| `kart-cv.service`, `install_service.sh` | Pi | systemd autostart for `pi/main.py live` (`--now` to start immediately; logs: `journalctl -u kart-cv -f`) |

## The real Pi (measured 2026-10-24)

The spec assumed Bookworm / Python 3.11; the Pi actually runs:

- Debian 13 **trixie**, 64-bit, desktop image (boots to `graphical.target`), kernel 6.18, **Python 3.13.5**
- hostname `smartcart`, user `jamwan`, on `kart-net` (laptop hotspot); SSH key login from the laptop works
- 3.7 GB RAM, 16 GB SD (≈6 GB free), `vcgencmd get_throttled` = `0x0`

## Cameras

Both are **Logitech Brio 101** (`046d:094d`, USB 2.0). MJPEG supports 1280×720 and 1920×1080 at 30 fps.
Use these stable paths (they follow the USB port, not the `/dev/videoN` number):

| cam | USB port | path |
|---|---|---|
| cam0 | 1.1 | `/dev/v4l/by-path/platform-fd500000.pcie-pci-0000:01:00.0-usb-0:1.1:1.0-video-index0` |
| cam1 | 1.3 | `/dev/v4l/by-path/platform-fd500000.pcie-pci-0000:01:00.0-usb-0:1.3:1.0-video-index0` |

Moving a camera to a different USB port changes its path; keep them plugged in where they are.

`check_cameras.py` on 2026-10-24 (both streaming at once, dim room at night): **13–15 fps each**, no read failures, sharp, well exposed. Both cams share the Pi's USB 2.0 bus without bandwidth trouble.

## `pi/` on the real Pi (2026-10-24, commit `c07cf85`)

- `pytest pi/tests`: **80 passed, 2 skipped** (the opt-in Supabase end-to-end tests) in 3 min 12 s.
- `tools/snap.py`: both cams OK. `pi/main.py live`: starts, takes the empty-basket picture after the 3 s warm-up, `/status` answers from the laptop, Ctrl-C stops it cleanly.
- Idle CPU: about 72 % of one core (≈18 % of the Pi), mostly decoding two MJPEG streams. Temp 48 °C.
- If `smartcart.local` doesn't resolve from the laptop, use the IP from the hotspot page: `KART_PI=jamwan@192.168.137.127 bash hardware/sync_pi.sh`.

## Notes for `pi/` (camera code)

- **Don't set `CAP_PROP_BUFFERSIZE=1`.** On this V4L2 driver it halves the frame rate (7.5 vs 15 fps measured). Keep the default buffers and let a grab thread read continuously and keep the latest frame.
- In dim light the Brio's auto exposure stretches frames (`exposure_dynamic_framerate=1`), capping it at ~15 fps; bright light gives 30. Either is enough for the 10 Hz loop.
- The first few seconds after opening a camera are slow and dark while auto exposure settles; don't take the empty-basket reference in that window.
- `~/venv` versions: Python 3.13.5, OpenCV 4.10.0 (apt), numpy 2.2.4 (apt), onnxruntime 1.31.0, anthropic 2.3.0, httpx 0.28.1, pytest 9.1.1.
