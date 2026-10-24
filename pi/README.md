# pi/ — KART cart vision

Two webcams look down into the basket. When something goes in or comes out, the cart waits until
motion stops (~1 s), compares each camera's picture with the last still one, figures out what
changed, names the product, and sends **one event per item** to the backend (Supabase
`apply_cart_event`). The iPad shows the live bill from there.

- Design: [`docs/specs/2026-10-24-cv-pipeline-design.md`](docs/specs/2026-10-24-cv-pipeline-design.md)
- Overnight build notes and open decisions: [`docs/OVERNIGHT.md`](docs/OVERNIGHT.md)

**Identification** is on-device first (a gallery of photos of our props, ~50 ms), then Claude
(`claude-haiku-5-5`) only when the cart isn't sure, then "unknown" (the iPad asks the shopper).
Only a crop of the item ever leaves the cart.

---

## On the Pi (hardware teammate: start here)

Install and autostart belong to `hardware/`. See [`hardware/README.md`](../hardware/README.md):
`hardware/setup_pi.sh` (venv + `pi/requirements-pi.txt`) and `hardware/install_service.sh`
(systemd running `pi/main.py live`). CV adds only these one-time steps, from `~/kart`:

```bash
~/venv/bin/python tools/fetch_model.py          # on-device feature model, ~9 MB
cp pi/config.example.json pi/config.json        # camera paths are already the measured USB ports
```

- Create **`~/kart/.env`** on the Pi (see "The Pi's `.env`" below). Without it the cart still
  runs: local matching only, events logged to `pi/state/events.jsonl`.
- **The cart floor needs a solid mat or cardboard.** A wire bottom shows the store floor sliding
  by, which looks like everything changed.
- **Start with the cart empty.** On first start the cart photographs the empty basket as its
  reference. If it started with items inside, empty it and reset (below).
- If the USB cables moved: `~/venv/bin/python tools/snap.py --list` and fix `cameras` in
  `pi/config.json` (use the `-video-index0` paths).

### Tell each camera where the basket floor is (ROI)

The cameras see the mesh walls and the room beyond the cart; when the cart rolls, that moves.
Give each camera a polygon of the basket **floor** so everything outside it is ignored. This is
required on a real cart with open mesh walls.

```bash
~/venv/bin/python tools/snap.py                                   # tools/out/cam0.jpg, cam1.jpg
~/venv/bin/python tools/roi.py tools/out/cam0.jpg --grid          # cam0_grid.jpg: read x,y off the grid
~/venv/bin/python tools/roi.py tools/out/cam0.jpg --cam 0 --points "0.10,0.40 0.90,0.38 0.97,0.98 0.03,0.98" --write
~/venv/bin/python tools/roi.py tools/out/cam1.jpg --cam 1 --points "…" --write
sudo systemctl restart kart-cv
```

Trace the floor just inside the walls (corners in order, any direction). Check `cam0_roi.jpg`: only
the floor should be bright. The debug page outlines each camera's ROI in yellow. Redo it whenever a
camera mount moves. In `pi/config.json` it looks like
`"roi": {"0": [[0.10, 0.40], …], "1": […]}` (normalized 0..1, x right, y down).

### The Pi's `.env`

The Pi needs exactly these four lines in `~/kart/.env` (Dylan has the values; never commit the file):

```
SUPABASE_URL=https://<project-ref>.supabase.co
SUPABASE_ANON_KEY=<the anon / public key>
CART_ID=7
ANTHROPIC_API_KEY=<the Anthropic key>
```

**Do not** put `SUPABASE_SERVICE_ROLE_KEY` or `SUPABASE_DB_URL` on the Pi. Those are admin
credentials for backend scripts only; the cart needs nothing beyond the public anon key. After
editing, restart: `sudo systemctl restart kart-cv`. The log should not say `local-only mode` or
`no Supabase settings`.

### Run it by hand

```bash
sudo systemctl stop kart-cv                      # the service holds the cameras
~/venv/bin/python pi/main.py live --debug-view   # Ctrl-C to stop
```

Open **http://smartcart.local:8080** on the laptop for the debug page. If `smartcart.local` stops
resolving (it can after the hotspot restarts), use the Pi's IP from the hotspot's "Devices connected"
list instead, e.g. **http://192.168.137.127:8080**, and the same IP in every command below (both camera feeds plus
the last events with their crops). Debug view shows full frames, so leave it off for the demo.
Without `--debug-view` you still get `http://smartcart.local:8080/status`.

Reset (cart must be empty): `~/venv/bin/python pi/main.py reset`, or `curl -X POST
http://smartcart.local:8080/reset`. A new trip started on the iPad also resets the cart
automatically (it watches `carts.trip_id`).

Logs from the service: `journalctl -u kart-cv -f`.

### Milestone checks: do this, and you should see that

| # | Do this | You should see |
|---|---|---|
| 1 | `~/venv/bin/python tools/snap.py` | `cam0: OK (720, 1280, 3) …` and `cam1: OK …`; open `tools/out/cam0.jpg` and `cam1.jpg`: both look into the basket |
| 2 | `pi/main.py live`, wave a hand over the basket, then hold it still inside the basket | `MOTION` when you wave, `SETTLED` about 1 s after you stop, `INTRUSION … waiting` while your arm is in, and **no** `ADDED` |
| 3 | Drop one item in, wait, take it out | `ADDED …` then `REMOVED …` (before enrollment and without a key the name is `? "…"`); crops in `pi/state/crops/` |
| 4 | Put `ANTHROPIC_API_KEY` in `~/kart/.env`, restart, drop 5 different props | each prints `ADDED <product-id> (cloud 0.xx)` with the right id |
| 5 | Enroll the props (below), then drop them again | `ADDED <product-id> (local 0.xx)`, instantly, no network needed |
| 6 | With Supabase in `.env`, add/remove items; then turn the hotspot off, add one, turn it back on | the iPad / `carts` row updates; the offline item arrives once Wi-Fi is back (no double count) |
| 7 | From the laptop: `curl http://smartcart.local:8080/status` | JSON with `items`, `state`, `last_events` |
| 8 | `bash hardware/install_service.sh --now`, then unplug and replug the Pi | it starts watching by itself (`journalctl -u kart-cv -f`) |

### Teach it the props (enrollment, ~1 min each)

```bash
sudo systemctl stop kart-cv
~/venv/bin/python tools/enroll.py kirkland-parmesan      # ids: data/store.json, or the tool lists them
```

Cart empty → put the item in → wait for `captured 1/5: take it out` → take it out → repeat with
a different pose (side, upright, label down). Photos land in `pi/gallery/<product-id>/`. Commit
and push `pi/gallery/` so every machine gets them.

Then ask which matcher separates the real props better:

```bash
~/venv/bin/python tools/gallery_check.py     # compares color histogram vs the ONNX CNN, recommends one
```

The default is `"features": "hist"`. Switch `pi/config.json` to `"auto"` (ONNX) only if the check
recommends it. Products the store owner adds live (merchant
agent) need no enrollment: they go to Claude using their `vision_hint`.

### Record and replay (for tuning)

```bash
~/venv/bin/python tools/record.py --seconds 60       # → tools/out/rec-YYYYmmdd-HHMMSS/
~/venv/bin/python pi/main.py replay tools/out/rec-…  # same pipeline, on the recording
```

Record a few real add/remove/hand/bump clips. They become regression tests and the material for
tuning the knobs below.

`replay` is a rehearsal: it uses a scratch state folder (never the live cart's memory) and sends
nothing to the backend, so it's safe to run on the Pi while the cart is set up.

**Sharing clips with the CV chat** (it can't reach the Pi; it works from clips in git):

```bash
~/venv/bin/python tools/record.py --seconds 15 --hz 5 --scale 0.5 --quality 85 --out hardware/clips/<name>
~/venv/bin/python pi/main.py replay hardware/clips/<name> --no-cloud    # note the events it prints
```

Half-size clips are about 4–6 MB per 15 s and replay the same for detection. Commit
`hardware/clips/` with a line per clip saying what actually happened, then push.

### If something looks wrong

| Symptom | Likely cause → fix |
|---|---|
| Items added when nothing happened | Floor visible through the cart, or strong flicker → mat on the floor; raise `change_thresh` (30 → 40) |
| A tall item (upright bottle) is billed ~4 s after it goes in | Expected: anything reaching the edge of the picture is first treated like an arm, then billed once it has stayed still for 3 s (`intrusion_recheck_s`) |
| Real items missed | Item very small or same color as the mat → lower `min_blob_frac` (0.004 → 0.002) or use a contrasting mat |
| Removed items show as added | The empty-basket picture is stale (cart wasn't empty at reset) → empty it, `pi/main.py reset` |
| Wrong product, method `local` | Look-alike props → enroll more poses, run `tools/gallery_check.py`, or raise `local_min_margin` (0.08 → 0.12) so Claude decides |
| Events when a big colored item goes in, or `% of the view changed (lighting?)` warnings | The webcam's auto white balance is shifting → lock it (below) |
| `local-only mode` in the log | No `ANTHROPIC_API_KEY` in `~/kart/.env` |
| `cam1: could not open …` | Cable or port moved → `tools/snap.py --list`, fix `pi/config.json` |

Every knob lives in `pi/config.json` (defaults in `pi/config.example.json`).

**Locking white balance (if colors drift).** The software already cancels most of it; locking it on
the camera removes the rest. Check the control names first, since they vary by kernel and model:

```bash
v4l2-ctl -d /dev/v4l/by-path/…-usb-0:1.1:1.0-video-index0 --list-ctrls     # look for white_balance_*
v4l2-ctl -d /dev/v4l/by-path/…-usb-0:1.1:1.0-video-index0 -c white_balance_automatic=0
```

Repeat for the second camera (`…1.3…`), with the cart lit the way it will be at the demo. This is
untested on the Brio 101: tell the CV chat what `--list-ctrls` prints if the name differs.

---

## On a Mac (development)

```bash
/opt/homebrew/bin/python3.12 -m venv pi/.venv && pi/.venv/bin/pip install -r pi/requirements.txt
pi/.venv/bin/python tools/fetch_model.py
pi/.venv/bin/python -m pytest pi/tests -q        # no camera, network or API key needed
```

The tests drive the real pipeline with synthetic two-camera scenes (`kartcv/synth.py`): items
dropped and taken out by a hand, hands that drop nothing, lighting changes, camera bumps, stacked
items, a camera that's blocked, and restarts.
