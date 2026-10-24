# KART computer vision pipeline: design (v1, "version B")

Status: approved in chat 2026-10-24, awaiting written-spec review · Owner: CV workstream (`pi/`, `tools/`)

## 1. Goal

Two webcams on the cart watch items go **in** and **out**. Each time something is added or removed, the cart emits one event naming the product, so the backend and the iPad can keep a live bill (Uniqlo-style auto checkout).

**Success = the demo:** drop an item in, and the right product is added within ~3 s. Take it out, and it's removed. A hand in the basket, a shadow, or a bump bills nothing. It works with ~10–15 real props.

**Guiding rule:** done > none. Ship the simplest pipeline that works, with clean seams for upgrades.

## 2. Decisions (and why)

| Decision | Choice | Why |
|---|---|---|
| Tracking | **Snapshot-diff**, not in-flight tracking | Compare the basket before and after motion stops. Hands are gone by then; the cart *remembers* items even when a pile hides them; it costs almost no CPU. |
| Two cameras | **Per-camera change detection, one combined decision per settle** ("version B") | No calibration or markers. The second camera adds coverage (piles block views) and a second angle for identification. |
| Identification | **Hybrid**: on-device few-shot matcher first, Claude Haiku when unsure | Fast and offline for enrolled props; Claude covers everything else; works on day one before anything is enrolled. Pitch: recognition happens on the cart, and only a crop of the item leaves, only when needed. |
| Prices | **Not computed by CV** | CV emits `product_id`; the backend owns the catalog and prices (single source of truth). |
| Floor-map fusion ("version A") | **Later, optional** | ~3–5 h, mostly tuning on the real cart. Section 12 describes the seam for it. |

**Not in scope:** training a detector, pose/in-flight tracking, the LCD, faces/people, payment logic.

## 3. Hardware assumptions

- Raspberry Pi 4, Raspberry Pi OS Lite 64-bit (Bookworm, Python 3.11), headless.
- 2× Logitech Brio 100 in **diagonally opposite corners, looking down** into the basket. Requested at **MJPEG 1280×720**. On the Pi, cameras are addressed by `/dev/v4l/by-path/...` (stable per USB port), not `/dev/videoN` (which can swap on reboot).
- **A solid mat or cardboard lines the cart floor.** A wire-mesh bottom shows the store floor sliding by and breaks snapshot comparison.
- Development happens on the Mac first (built-in camera + recordings + synthetic scenes); the same code runs on the Pi.

## 4. Architecture

One Python process. Camera grabbing runs in background threads; everything else runs in the main loop.

```
cam0 ─┐  grab threads: always hold the latest frame
cam1 ─┘        │
               ▼
      motion.py   tiny grayscale frame-to-frame diff → MOTION / SETTLED (both cams still ~1 s)
               │ on SETTLED
               ▼
      changes.py  per camera: settled frame vs reference → blobs (+ "disturbed" / "no change")
               ▼
      decide.py   per blob: added / removed (empty-basket test + cart memory)
                  identify each blob → combine cameras → nudge cancel → final events
               │        ▲
               │        └── identify/  hybrid: local gallery → Claude → unknown
               ▼
      cart.py     cart memory (what's in the cart, where each camera saw it) — persisted
               ▼
      sinks.py    JSONL log (always) + HTTP to backend (outbox + retry)
```

### Layout

```
pi/
  main.py                 CLI: live | replay <dir> | reset
  config.example.json     all tunables, with defaults (copy to config.json)
  requirements.txt        Mac/dev deps; Pi uses apt python3-opencv + these
  kartcv/
    config.py             dataclass config: defaults ← config.json ← CLI flags; loads .env
    sources.py            FrameSource: LiveCamera, VideoFileSource, list-of-frames source
    motion.py             MotionDetector + SettleTracker
    changes.py            change mask → blobs; disturbed / no-change detection
    decide.py             added/removed per blob, multi-camera combine, nudge cancel
    cart.py               CartMemory (items + per-camera boxes + fingerprints), save/load
    catalog.py            load data/store.json (fallback: built-in CONTRACT §2 example)
    events.py             Event dataclass + JSON shape
    sinks.py              JsonlSink, HttpSink (apply_cart_event), Outbox
    identify/
      features.py         crop → fingerprint (ONNX CNN embedding; color-histogram fallback)
      gallery.py          enrolled examples per product; nearest-neighbour scoring
      cloud.py            Claude closed-set identification
      hybrid.py           local → cloud → unknown policy
    server.py             small HTTP server: /status, POST /reset, optional live debug page
    pipeline.py           glue: the main loop
  gallery/                enrolled product crops (committed; product photos only)
  models/                 ONNX model (gitignored; fetched by tools/fetch_model.py)
  state/                  runtime: cart.json, events.jsonl, outbox.jsonl, crops/ (gitignored)
  tests/                  pytest, synthetic two-camera scenes
  docs/specs/             this file
tools/
  snap.py                 save cam0.jpg / cam1.jpg (milestone 1)
  record.py               record both cams to a replay folder
  enroll.py               teach the gallery a product
  fetch_model.py          download/export the ONNX feature model
  synth.py                synthetic-scene generator (shared with tests)
```

## 5. Spotting changes

### 5.1 Motion and settle (`motion.py`)
- Each camera frame is shrunk to **320×180 grayscale**, blurred, and compared with that camera's previous small frame.
- A camera is **in motion** if more than `motion_frac` (default **0.5 %**) of pixels changed by more than `motion_thresh` (default **25**/255).
- **SETTLED** fires once, after motion has happened and **both** cameras have been still for `settle_s` (default **1.0 s**). A camera that is down doesn't block settling.
- The loop runs at ~10 Hz. CPU stays low because only small frames are compared.

### 5.2 Change detection (`changes.py`), on each SETTLED
For each camera, compare the new settled frame (downscaled to **640×360**) with that camera's **reference** (its previous settled frame):
1. Blur both, convert to LAB, and compute per-pixel color distance. Normalize overall brightness first, so a global lighting shift doesn't light up everything.
2. Threshold at `change_thresh` (default **30**), then clean up the mask (open 5 px, close 15 px).
3. Keep connected blobs bigger than `min_blob_frac` (default **0.4 %** of the frame).

Outcomes per camera:
- **No blobs:** the reference becomes the new frame (absorbs slow lighting drift). No events.
- **Disturbed:** more than `disturbed_frac` (default **60 %**) of the frame changed (the cart rolled, a camera got bumped, a big lighting change). The reference becomes the new frame, a warning is logged, and **no events**.
- **Blobs:** passed to `decide.py` with before/after crops cut from the full-resolution frames (box padded 10 %).

### 5.3 Added or removed? (`decide.py`)
Each camera keeps an **empty-basket picture**, taken on reset. For each blob:
1. **After ≈ empty basket** in that box → **removed**. The mat reappeared.
2. **Before ≈ empty basket** → **added**. New stuff on the mat.
3. **Neither** (something on top of something): if the *after* crop matches an item cart memory already has in that camera at an overlapping box, the top item was **removed** (it revealed what was under). Otherwise a new item was **added** on top.

"≈ empty" means the brightness-normalized mean color distance inside the blob is below `empty_thresh` (start at **18**; tuned on the real mat).

### 5.4 Combining both cameras
Each blob is identified (section 6). Then, per settle:
- **Common case (each camera has ≤ 1 blob of a type):** the blobs are treated as the same item. All crops go into **one** joint identification call. Result: one event.
- **General case:** the number of items = **the most blobs any single camera saw** of that type. Candidates are taken by confidence, with at most as many units of a product as the camera that saw the most of it. Remaining slots are filled with `unknown`.
- **Removals can't exceed what's in the cart.** A product can only be removed if cart memory has it.
- **Nudge cancel:** if the same product is both added and removed in one settle, it just moved. Emit nothing; update cart memory to the new box.

Known limit: two identical items dropped touching each other in the same second count as one.

## 6. Identification (`identify/`)

### 6.1 Added items
1. **Local matcher.**
   - A small ImageNet-pretrained CNN (MobileNetV3-Small or MobileNetV2, ONNX, run with `onnxruntime`) turns each crop into an embedding (fingerprint). About 50 ms per crop on a Pi 4.
   - If the model file is missing, an HSV color histogram is used instead, so the pipeline still runs.
   - Each product's score is the mean of its top-3 cosine similarities against that product's gallery examples. Multi-crop calls average across crops.
   - **Accept** if the best score ≥ `local_min_score` (start **0.70**) **and** best − runner-up ≥ `local_min_margin` (start **0.08**). Both get tuned on the real enrollments. Confidence = best score.
2. **Cloud (Claude).**
   - If the local matcher doesn't accept, the crops (both cameras, max 2 per camera, JPEG ≤ 512 px) and the catalog list (`id`, `name`, `vision_hint`) go to `claude-haiku-5-5` (configurable).
   - Claude must return JSON `{"product_id": "<id>|unknown", "confidence": 0–1, "label": "<short description>"}`. A `product_id` outside the catalog is treated as unknown.
   - Accepted if confidence ≥ `cloud_min_conf` (default **0.6**). Timeout: **3 s**.
3. **Unknown.** The event has `product_id: null`, `method: "none"`, and `label` = the best text we have. The iPad asks the shopper to pick.

### 6.2 Removed items
Matched **only against cart memory**: the before-crop's fingerprint is compared against each in-cart item's stored fingerprints, boosted by box overlap in the same camera. No cloud call. `method: "memory"`.

### 6.3 Enrollment (`tools/enroll.py`)
"Put the Parmesan in → wait for the terminal to print `captured` → take it out", about 5 rounds, with the item in different poses each time. It reuses the real pipeline to capture settled crops from both cameras, then saves `pi/gallery/<product_id>/<n>_cam<k>.jpg` and refreshes the fingerprint cache (`pi/gallery/index.npz`, rebuilt automatically if it's stale). Enrollment should be done on the real cart, because angles and lighting matter.

## 7. Cart memory (`cart.py`)

- Holds one entry per physical unit in the cart: `instance_id`, `product_id` (or null), and per camera the pixel box + fingerprint + crop path.
- Saved to `pi/state/cart.json` after every change, so a restart doesn't forget what's inside.
- **Reset** clears memory, takes a new empty-basket picture per camera, and sets the references. Triggered on demand by `python pi/main.py reset` or `POST /reset` (section 9), and **automatically when the iPad starts a new trip**. The iPad calls the backend's `reset_cart`, which sets a new `carts.trip_id`. The Pi polls that value every ~2 s and resets when it changes. The last seen `trip_id` is saved in `pi/state/trip.json`, so a change made while the Pi was off is caught at startup (CONTRACT v0.4). At startup, saved state is loaded and **not** reset, because the cart may not be empty. The one exception is the very first run (no saved state), which resets automatically and logs it.

## 8. Events (what the cart emits)

One event = one unit added or removed (comments are explanation only; the real payload is plain JSON):

```jsonc
{
  "event_id": "5f0c…",            // uuid4
  "cart_id": "7",
  "type": "added",                // "added" | "removed"
  "product_id": "kirkland-parmesan", // null = unknown
  "confidence": 0.93,
  "method": "local",              // "local" | "cloud" | "memory" | "none"
  "label": "Kirkland Parmigiano Reggiano", // catalog name, or raw model text when unknown
  "cameras": [0, 1],              // which cameras saw it
  "crops": ["state/crops/5f0c…_cam0.jpg"], // local paths, for "what the AI saw"
  "ts": "2026-10-24T14:02:11Z"
}
```

**Sinks** (`sinks.py`):
- `JsonlSink`: always on, appends to `pi/state/events.jsonl`.
- `HttpSink`: on when backend settings exist. It calls the Supabase RPC `apply_cart_event(p_cart_id, p_type, p_product_id, p_confidence, p_source="vision", p_label, p_camera=<first camera>, p_event_id, p_method)` per CONTRACT §3. The RPC is idempotent on `p_event_id`, so outbox retries can't double-bill.
  - Failed sends go to `pi/state/outbox.jsonl` and are retried in order (backoff up to 30 s), so no event is lost or reordered.
- Crops stay local in v1. Uploading them for the iPad is a later, separate change.

## 9. Control and debug server (`server.py`)

A small HTTP server on port **8080** (stdlib, one thread):
- `GET /status`: camera health, state (watching/settling/identifying), item count, last 10 events.
- `POST /reset`: reset (section 7).
- `GET /` (only with `--debug-view`): a live page showing both camera feeds, the latest change blobs, and recent events with crops. **Dev only:** it shows full frames, so it stays off at the demo unless needed.

## 10. Failure handling

| Failure | Behavior |
|---|---|
| A camera fails to open or stops returning frames | Log it, keep going on the other camera, retry opening every 5 s |
| Both cameras down | Keep retrying; `/status` reports it; no events |
| No internet / Claude error / Claude slow (> 3 s) | Local result if accepted, otherwise an `unknown` event |
| Backend unreachable | Outbox + retry (section 8) |
| Scene disturbed (> 60 % changed) | New reference, warning, no events |
| Process crash | Cart memory persisted; autostart (systemd) restarts it (milestone 8) |
| Missing `ANTHROPIC_API_KEY` | Local-only mode; uncertain items become `unknown`; warning at startup |

## 11. Configuration and environment

- `pi/config.json` (copied from `config.example.json`): camera sources, resolution, every threshold above, cart id, sink settings, model names. Missing keys fall back to code defaults.
- Secrets come from the shared env file, never the repo: `KART_ENV_FILE` if set, otherwise `<repo root>/.env`. Variables: `ANTHROPIC_API_KEY`, `SUPABASE_URL`, `SUPABASE_ANON_KEY`, `CART_ID`. Names are listed in `pi/.env.example`.
- **Mac:** a venv in `pi/.venv` on Python 3.11+, with `opencv-python-headless`, `numpy`, `onnxruntime`, `anthropic`, `httpx`, `python-dotenv`, `pytest`.
- **Pi:** `~/venv` created with `--system-site-packages` (apt `python3-opencv`), plus the same pip packages minus OpenCV. Code must work on OpenCV ≥ 4.6.
- `pi/.gitignore` ignores `state/`, `models/`, `.venv/`, `config.json`, and test output.

## 12. Upgrade seam for version A (floor map)

`changes.py` returns per-camera blobs, and `decide.py` consumes them. Version A would add an optional `floormap.py` between them: it projects each camera's blobs onto a shared floor map using marker-based calibration and merges them by location, behind `config.fusion = "per_camera" | "floor_map"`. Nothing else changes, and switching back is one setting.

## 13. Testing

- **Synthetic two-camera scenes** (`tools/synth.py`, used by `pi/tests/`). The generator makes a textured "mat" scene, pastes distinct procedurally-patterned item sprites, and renders it through two different perspective warps (the two corners) with sensor noise. It can also script a hand (a skin-colored blob moving in and out), global lighting shifts, and few-pixel camera wobble.
- **Pipeline tests** (no hardware, no network) must show:
  - add 1 → 1 `added`; remove it → 1 `removed`
  - hand in and out with nothing dropped → 0 events
  - lighting shift → 0 events; small wobble → 0 events; big shift → "disturbed", 0 events
  - nudge an item → 0 events
  - add 2 separated items in one settle → 2 `added`
  - item hidden from one camera → still 1 `added`
  - add an item on top of another → 1 `added`; remove the top one → 1 `removed`
  - removed product chosen from cart memory, not the catalog
- **Unit tests:**
  - motion/settle timing
  - gallery scoring and the accept/margin rule
  - hybrid policy with a fake cloud client (accept, low confidence, timeout, invalid id)
  - outbox retry ordering with a fake HTTP server
  - catalog fallback
- **Replay:** `tools/record.py` saves both cams as a folder of timestamped JPEGs. `main.py replay <dir>` runs the pipeline on it. Once hardware is up, real recordings with expected events become regression tests.
- **Mac smoke test:** `main.py live` with the built-in camera as the only camera.

## 14. Milestones (each ends with a check on the real hardware)

| # | Milestone | Check |
|---|---|---|
| 1 | Cameras + `tools/snap.py` | Both cams save a picture looking into the basket |
| 2 | Motion/settle | Wave a hand → `MOTION`, stop → `SETTLED` printed |
| 3 | Change detection + added/removed + cart memory (no AI) | Add/remove an item → correct `added`/`removed` with crops in `pi/state/crops/` |
| 4 | Claude identification | 5 real items named correctly, `method: "cloud"` |
| 5 | Local matcher + enrollment | Enrolled items named in < 0.5 s, `method: "local"` |
| 6 | HTTP sink + outbox | Events show up in the backend; unplug Wi-Fi → they arrive after reconnect |
| 7 | Status/reset/debug server | `/status` works from a laptop; reset clears the cart |
| 8 | Pi install guide (`pi/README.md`); autostart is owned by the hardware chat (`hardware/`), which runs `pi/main.py live` | Power-cycle the Pi → it starts watching with nobody touching it |

Milestones 1–3 and the synthetic tests are built on the Mac before the hardware arrives.

## 15. Needs from other workstreams

- **Backend/iPad chats (answered in CONTRACT v0.4):**
  - Events go to `apply_cart_event`.
  - `product_id` = the `store.json` id.
  - Reset arrives via `carts.trip_id`.
  - No crops in v1. Upload is a later stretch: P9.
- **Dylan:** `ANTHROPIC_API_KEY` in `.env`; Supabase URL/key once the backend exists; the Pi + both Brios set up; a solid mat for the cart floor; the 10–15 demo props for enrollment.
