# KART CV Pipeline Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A single Python process on the cart's Raspberry Pi that watches two webcams, decides each time an item is added to or removed from the basket, names the product, and emits one event per unit to a local log and the backend.

**Architecture:** Snapshot-diff ("version B"). Cheap motion detection waits until both cameras have been still for 1 s. Then each camera compares its frame with its previous still frame and finds changed blobs, and one combined decision is made per settle. Added items are identified by an on-device few-shot gallery (CNN embeddings), with Claude Haiku as the fallback. Removed items are matched against the cart's own memory. Everything is driven tick by tick (`Pipeline.step(frames)`), so live cameras, recordings, and synthetic test scenes all run the same code.

**Tech Stack:** Python ≥ 3.11, OpenCV ≥ 4.6, NumPy, onnxruntime (+ `onnx` for the one-time model fetch), `anthropic` SDK, python-dotenv, pytest. The server uses the stdlib `http.server`, and the backend HTTP calls use stdlib `urllib`.

**Spec:** `pi/docs/specs/2026-10-24-cv-pipeline-design.md`

## Global Constraints

- **Python and OpenCV:** code must run on **Python 3.11** (Pi OS Bookworm), so use no 3.12-only syntax. Every module starts with `from __future__ import annotations`. The Mac dev venv is `/opt/homebrew/bin/python3.12 -m venv pi/.venv`. Use only OpenCV ≥ 4.6 core APIs (no contrib modules).
- **Git:** only create, edit, or commit files under `pi/` and `tools/`. The checkout is shared with another session on `main`, so commit with explicit paths (`git add <paths> && git commit -m "..." -- <paths>`) and never `git add -A`/`.`. End every commit message with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
- **Secrets** come only from the env file `KART_ENV_FILE` or `<repo>/.env`, never from tracked files. Variable names: `ANTHROPIC_API_KEY`, `SUPABASE_URL`, `SUPABASE_ANON_KEY`, `CART_ID`.
- **`tools/*.py` are thin CLIs.** Logic lives in `pi/kartcv/`. Each tool starts with `sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "pi"))`.
- **Tests:** run from the repo root with `pi/.venv/bin/python -m pytest pi/tests -q`. They need no camera, no network, and no API key.
- **Spec defaults (verbatim):**
  - Motion: frames 320×180, `motion_thresh` 25, `motion_frac` 0.005, `settle_s` 1.0.
  - Change detection: diff frames 640×360, `change_thresh` 30, `min_blob_frac` 0.004, `disturbed_frac` 0.60, `empty_thresh` 18, crop pad 0.10.
  - Identification: `local_min_score` 0.70, `local_min_margin` 0.08, `cloud_model` `"claude-haiku-5-5"`, `cloud_min_conf` 0.6, `cloud_timeout_s` 3.0.
  - Runtime: `server_port` 8080, camera reopen every 5 s, outbox backoff capped at 30 s, camera capture MJPEG 1280×720.
  - Plan addition: `max_shift_px` 4.0 (camera-bump detection, Task 5).
- **Event JSON keys (exact):** `event_id, cart_id, type, product_id, confidence, method, label, cameras, crops, ts`. `type` ∈ `added|removed`; `method` ∈ `local|cloud|memory|none`.
- **Privacy:** only item crops ever leave the Pi (to Claude). Full frames never leave; the debug page is local and off by default.
- **Claude call:** `client.with_options(timeout=cfg.cloud_timeout_s, max_retries=0).messages.create(...)` with `output_config={"effort": "low", "format": {"type": "json_schema", ...}}`. Check `stop_reason` before reading `content`. No `temperature`/`top_p`, no prefill, no `thinking` param (Haiku 5.5 default adaptive).

## Review Focus

1. **Hand resting still in the basket for > 1 s, then withdrawn:** the cart must end with nothing billed (net zero). Test in Task 11.
2. **A big item fills one camera (> 60 % → "disturbed") while the other camera sees a normal blob:** still exactly 1 `added`. Test in Task 9.
3. **Soft partial shadow (half the frame darkens 25 %, e.g. someone leaning over):** no change blobs. Test in Task 5.
4. **Lighting drifts after reset (brightness ×1.2), then an item is removed:** it is still classified `removed`, not `added`. Test in Task 11.
5. **The Claude call times out or errors:** `identify` returns `unknown` without raising, and the client is configured with `timeout=3.0, max_retries=0`, so the loop can't stall for minutes. Test in Task 8.

## File Map

```
pi/
  pyproject.toml            pytest config only (testpaths, pythonpath ".")
  requirements.txt          Mac/dev deps        requirements-pi.txt   Pi deps (no OpenCV/NumPy)
  .gitignore  .env.example  config.example.json
  main.py                   CLI: live | replay | reset
  kartcv/
    __init__.py
    config.py               Config dataclass, load_config, load_env, REPO_ROOT
    http.py                 tiny urllib get/post helpers + Supabase headers
    catalog.py              Product, Catalog, load_catalog (+ fallback example), fetch_catalog (Supabase)
    events.py               Event
    sources.py              Frame, LiveCamera, FrameListSource, save_tick, load_recording, snap_all
    synth.py                synthetic two-camera scenes + Script timeline (tests & demos)
    motion.py               MotionDetector, SettleTracker
    changes.py              Blob, ChangeResult, detect_changes, lab_distance, match_gain, translate
    cart.py                 View, Instance, CartMemory
    identify/__init__.py
    identify/features.py    HistogramFeatures, OnnxFeatures, load_features, fetch_model
    identify/gallery.py     Gallery
    identify/cloud.py       CloudAnswer, CloudIdentifier
    identify/hybrid.py      Identification, HybridIdentifier
    decide.py               Decision, classify_blob, decide, apply_decision
    sinks.py                JsonlSink, ConsoleSink, MemorySink, HttpSink
    pipeline.py             Pipeline
    server.py               ControlServer
    trip.py                 TripWatcher (reset when carts.trip_id changes)
    enroll.py               run_enrollment
  README.md                 how to run CV on the Pi + milestone checks (autostart itself is the hardware chat's)
  tests/                    one test file per module + helpers.py
tools/  snap.py  record.py  enroll.py  fetch_model.py
```

Deviation from spec §4 layout: the synthetic generator lives in `pi/kartcv/synth.py` (importable by tests) instead of `tools/synth.py`.

---

### Task 1: Scaffold, config, catalog, events

**Files:**
- Create: `pi/pyproject.toml`, `pi/requirements.txt`, `pi/requirements-pi.txt`, `pi/.gitignore`, `pi/.env.example`, `pi/config.example.json`, `pi/kartcv/__init__.py`, `pi/kartcv/config.py`, `pi/kartcv/http.py`, `pi/kartcv/catalog.py`, `pi/kartcv/events.py`
- Test: `pi/tests/test_config.py`, `pi/tests/test_catalog.py`, `pi/tests/test_events.py`

**Interfaces:**
- Produces:
  - `REPO_ROOT: Path` (= `Path(__file__).resolve().parents[2]`).
  - `Config` dataclass. Fields and defaults are in Global Constraints, plus:
    - `cart_id="7"`, `cameras: list[int | str] = [0]`, `width=1280`, `height=720`, `fps=30`
    - `catalog_path="data/store.json"`, `state_dir="pi/state"`, `gallery_dir="pi/gallery"`, `model_path="pi/models/features.onnx"` (all relative to `REPO_ROOT` unless absolute)
    - `debug_view=False`, `max_shift_px=4.0`
    - `features="auto"`: `"auto"` = ONNX if the model file exists, otherwise the histogram; `"hist"` = always the histogram. Tests use `"hist"` so results don't depend on whether the model was downloaded.
    - `Config.path(name) -> Path` resolves one of the path fields.
  - `load_config(path: Path | None = None, overrides: dict | None = None) -> Config`. Precedence: defaults < JSON file < overrides. Unknown keys are ignored with a `logging` warning; tuple fields accept JSON lists.
  - `load_env() -> dict[str, str]`: loads `KART_ENV_FILE` or `REPO_ROOT/.env` into `os.environ` (python-dotenv, no override of already-set vars). Returns the four known vars that are set. A missing file is fine.
  - `http.py`, used by the catalog, sinks and trip watcher:
    - `get(url, headers, timeout=5.0) -> tuple[int, bytes]`.
    - `post_json(url, headers, body: dict, timeout=5.0) -> int`.
    - Both use stdlib `urllib`. Both return the status for HTTP error responses and raise `OSError` on network failure.
  - `supabase_headers(anon_key) -> dict`: `apikey`, `Authorization: Bearer <key>`, `Content-Type: application/json`.
  - `Product(id, name, price=0.0, vision_hint="", short_name="")` (frozen dataclass).
  - `Catalog(products: dict[str, Product])`:
    - `.ids() -> list[str]` (sorted), `.name(pid) -> str` (falls back to `pid`), `.get(pid) -> Product | None`.
    - `.prompt_lines() -> str`: one `id | name | vision_hint` line per product.
    - `.replace_with(other: Catalog)`: swaps in `other`'s products dict in one assignment, so everything holding this `Catalog` object sees the new products.
  - `fetch_catalog(base_url, anon_key, get=http.get) -> Catalog | None` (CONTRACT v0.9 §3a): GETs `f"{base_url.rstrip('/')}/rest/v1/products?select=id,name,short_name,price,vision_hint"`. It returns `None` on `OSError`, non-200, bad JSON, or an empty list.
  - `load_catalog(path: Path) -> Catalog`. If the file is missing, it returns the built-in `FALLBACK_CATALOG` (`kirkland-parmesan` "Kirkland Parmigiano Reggiano" 12.99, `barilla-spaghetti` "Barilla Spaghetti" 1.99, `rao-marinara` "Rao's Marinara" 6.99, with short vision hints) and logs a warning.
  - `Event` dataclass with exactly the Global Constraints keys; `Event.new(**fields_except_id_and_ts) -> Event`; `.to_json() -> dict`. `ts` is UTC ISO8601 ending in `Z`, seconds precision.

- [ ] **Step 1: Create the venv and dependency files**

`pi/requirements.txt`: `opencv-python-headless`, `numpy`, `onnxruntime`, `onnx`, `anthropic`, `python-dotenv`, `pytest`. `pi/requirements-pi.txt`: the same minus `opencv-python-headless`, `numpy`, `pytest` (the Pi uses apt `python3-opencv`/`python3-numpy`). `pi/.gitignore`: `state/ models/ .venv/ config.json __pycache__/ tests/out/`. `pi/.env.example` lists the four variable names with empty values. `pi/pyproject.toml`:

```toml
[tool.pytest.ini_options]
testpaths = ["tests"]
pythonpath = ["."]
```

Run: `/opt/homebrew/bin/python3.12 -m venv pi/.venv && pi/.venv/bin/pip install -q -r pi/requirements.txt && pi/.venv/bin/python -c "import cv2, onnxruntime, anthropic; print(cv2.__version__)"`
Expected: prints an OpenCV version, no ImportError.

- [ ] **Step 2: Write the failing tests**

```python
# pi/tests/test_config.py
from kartcv.config import Config, load_config, load_env

def test_defaults_match_spec():
    c = Config()
    assert (c.motion_size, c.motion_thresh, c.motion_frac, c.settle_s) == ((320, 180), 25, 0.005, 1.0)
    assert (c.diff_size, c.change_thresh, c.min_blob_frac, c.disturbed_frac) == ((640, 360), 30.0, 0.004, 0.60)
    assert (c.empty_thresh, c.crop_pad, c.local_min_score, c.local_min_margin) == (18.0, 0.10, 0.70, 0.08)
    assert (c.cloud_model, c.cloud_min_conf, c.cloud_timeout_s, c.server_port) == ("claude-haiku-5-5", 0.6, 3.0, 8080)

def test_json_file_then_overrides(tmp_path):
    p = tmp_path / "c.json"
    p.write_text('{"settle_s": 1.5, "cameras": ["/dev/v4l/by-path/a"], "diff_size": [320, 180], "bogus": 1}')
    c = load_config(p)
    assert c.settle_s == 1.5 and c.cameras == ["/dev/v4l/by-path/a"] and c.diff_size == (320, 180)
    assert load_config(p, {"settle_s": 2.0}).settle_s == 2.0

def test_load_env(tmp_path, monkeypatch):
    f = tmp_path / ".env"; f.write_text("ANTHROPIC_API_KEY=sk-test\nCART_ID=9\n")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False); monkeypatch.delenv("CART_ID", raising=False)
    monkeypatch.setenv("KART_ENV_FILE", str(f))
    assert load_env() == {"ANTHROPIC_API_KEY": "sk-test", "CART_ID": "9"}
    monkeypatch.setenv("KART_ENV_FILE", str(tmp_path / "missing"))
    load_env()  # no exception
```

```python
# pi/tests/test_catalog.py
import json
from kartcv.catalog import load_catalog

def test_load_store_json(tmp_path):
    p = tmp_path / "store.json"
    p.write_text(json.dumps({"products": [{"id": "kirkland-parmesan", "name": "Kirkland Parmigiano Reggiano",
        "price": 12.99, "section": "A4", "category": "cheese", "tags": [], "vision_hint": "wedge"}]}))
    cat = load_catalog(p)
    assert cat.ids() == ["kirkland-parmesan"] and cat.name("kirkland-parmesan") == "Kirkland Parmigiano Reggiano"
    assert "kirkland-parmesan | Kirkland Parmigiano Reggiano | wedge" in cat.prompt_lines()

def test_missing_hint_and_missing_file(tmp_path):
    p = tmp_path / "s.json"; p.write_text('{"products": [{"id": "a", "name": "A", "price": 1}]}')
    assert load_catalog(p).get("a").vision_hint == ""
    assert "kirkland-parmesan" in load_catalog(tmp_path / "nope.json").ids()

def test_fetch_catalog_from_supabase_and_failures():
    rows = [{"id": "new-thing", "name": "New Thing", "short_name": "New", "price": 3.5, "vision_hint": "green box"}]
    calls = []
    def get(url, headers): calls.append((url, headers)); return 200, json.dumps(rows).encode()
    cat = fetch_catalog("https://x.supabase.co/", "k", get=get)
    assert cat.ids() == ["new-thing"] and cat.get("new-thing").vision_hint == "green box"
    assert calls[0][0] == "https://x.supabase.co/rest/v1/products?select=id,name,short_name,price,vision_hint"
    assert calls[0][1]["apikey"] == "k"
    def offline(url, headers): raise OSError("offline")
    assert fetch_catalog("https://x", "k", get=offline) is None
    assert fetch_catalog("https://x", "k", get=lambda u, h: (500, b"")) is None
    assert fetch_catalog("https://x", "k", get=lambda u, h: (200, b"[]")) is None

def test_replace_with_is_seen_by_holders(tmp_path):
    cat = load_catalog(tmp_path / "nope.json"); held = cat
    cat.replace_with(Catalog({"z": Product("z", "Z")}))
    assert held.ids() == ["z"]
```

(Imports for this file: `from kartcv.catalog import Catalog, Product, load_catalog, fetch_catalog`.)

```python
# pi/tests/test_events.py
import json, uuid
from kartcv.events import Event

def test_event_json_shape():
    d = Event.new(cart_id="7", type="added", product_id="kirkland-parmesan", confidence=0.93, method="local",
                  label="Kirkland Parmigiano Reggiano", cameras=[0, 1], crops=["state/crops/x_cam0.jpg"]).to_json()
    assert set(d) == {"event_id", "cart_id", "type", "product_id", "confidence", "method", "label", "cameras", "crops", "ts"}
    assert uuid.UUID(d["event_id"]).version == 4 and d["ts"].endswith("Z")
    assert json.loads(json.dumps(d)) == d
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `pi/.venv/bin/python -m pytest pi/tests -q`
Expected: FAIL / ERROR with `ModuleNotFoundError: No module named 'kartcv'`.

- [ ] **Step 4: Implement `config.py`, `http.py`, `catalog.py`, `events.py` and `config.example.json`** per the Interfaces block. `config.example.json` holds every Config field with its default, except `cameras`, which is `["/dev/v4l/by-path/REPLACE-cam0", "/dev/v4l/by-path/REPLACE-cam1"]`.

- [ ] **Step 5: Run the tests to verify they pass**

Run: `pi/.venv/bin/python -m pytest pi/tests -q`
Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add pi/pyproject.toml pi/requirements.txt pi/requirements-pi.txt pi/.gitignore pi/.env.example pi/config.example.json pi/kartcv pi/tests
git commit -m "pi: scaffold kartcv package with config, catalog, events" -- pi/pyproject.toml pi/requirements.txt pi/requirements-pi.txt pi/.gitignore pi/.env.example pi/config.example.json pi/kartcv pi/tests
```

---

### Task 2: Frame sources, snap and record tools

**Files:**
- Create: `pi/kartcv/sources.py`, `tools/snap.py`, `tools/record.py`
- Test: `pi/tests/test_sources.py`

**Interfaces:**
- Consumes: `Config` (Task 1).
- Produces:
  - `Frame(image: np.ndarray, ts: float, cam: int)` dataclass. `image` is BGR uint8.
  - `Tick = dict[int, Frame | None]`.
  - `LiveCamera(cam: int, source: int | str, width: int, height: int, fps: int)`:
    - A daemon thread grabs continuously (`CAP_PROP_FOURCC` MJPG; width, height, fps).
    - `.read() -> Frame | None` returns the latest frame, or `None` if there is no fresh frame within 2 s.
    - `.healthy: bool`. `.close()`. Reopens every 5 s after failure.
  - `FrameListSource(cam: int, frames: list[Frame])`: `.read()` returns the next frame, then `None`. `.exhausted: bool`.
  - `save_tick(root: Path, tick: Tick) -> None`: writes `root/cam{k}/{round(ts*1000):013d}.jpg`.
  - `load_recording(root: Path) -> list[FrameListSource]`: one per `cam*` directory, sorted by cam number, `ts` recovered from the file name.
  - `iter_ticks(sources: list[FrameListSource]) -> Iterator[Tick]`: zips the sources until all are exhausted.
  - `snap_all(cfg: Config, out_dir: Path) -> dict[int, Path | None]`: opens each configured camera, discards 10 warm-up frames, and saves `cam{k}.jpg`.

- [ ] **Step 1: Write the failing tests**

```python
# pi/tests/test_sources.py
import time, numpy as np
from kartcv.sources import Frame, FrameListSource, LiveCamera, save_tick, load_recording, iter_ticks

def img(v): return np.full((72, 128, 3), v, np.uint8)

def test_frame_list_source_in_order_then_none():
    s = FrameListSource(0, [Frame(img(1), 0.0, 0), Frame(img(2), 0.1, 0)])
    assert s.read().ts == 0.0 and s.read().ts == 0.1 and s.read() is None and s.exhausted

def test_recording_roundtrip(tmp_path):
    for i in range(3):
        save_tick(tmp_path, {0: Frame(img(10 * i), i * 0.1, 0), 1: Frame(img(20 * i), i * 0.1, 1)})
    srcs = load_recording(tmp_path)
    assert [s.cam for s in srcs] == [0, 1]
    ticks = list(iter_ticks(srcs))
    assert len(ticks) == 3 and abs(ticks[2][1].ts - 0.2) < 1e-6 and ticks[2][1].image.shape == (72, 128, 3)

def test_live_camera_bad_source_is_unhealthy_not_crashing():
    cam = LiveCamera(0, "/dev/does-not-exist", 1280, 720, 30)
    time.sleep(0.3)
    assert cam.read() is None and not cam.healthy
    cam.close()
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pi/.venv/bin/python -m pytest pi/tests/test_sources.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'kartcv.sources'`.

- [ ] **Step 3: Implement `sources.py`** per the Interfaces block.

- [ ] **Step 4: Implement `tools/snap.py` and `tools/record.py`**
  - `snap.py [--config P] [--cam SRC ...] [--list]`: calls `snap_all` into `tools/out/` and prints `cam{k}: OK (720, 1280, 3) -> path` or `cam{k}: FAIL`. `--list` prints `/dev/v4l/by-path/*` entries and `v4l2-ctl --list-devices` output where they exist (Linux), else says none were found.
  - `record.py [--config P] [--seconds 30] [--hz 10] [--out DIR]`: grabs from all `LiveCamera`s at `hz` and writes with `save_tick` (default out `tools/out/rec-<YYYYmmdd-HHMMSS>`).

- [ ] **Step 5: Run the tests, then a manual smoke test on the Mac camera**

Run: `pi/.venv/bin/python -m pytest pi/tests/test_sources.py -q && pi/.venv/bin/python tools/snap.py --cam 0`
Expected: tests pass, and the tool prints `cam0: OK (720, 1280, 3) -> tools/out/cam0.jpg`. If macOS blocks camera access, the tool prints `FAIL`: record that and continue, since it isn't a blocker.

- [ ] **Step 6: Commit**

```bash
git add pi/kartcv/sources.py pi/tests/test_sources.py tools/snap.py tools/record.py
git commit -m "pi: frame sources, recording format, snap/record tools" -- pi/kartcv/sources.py pi/tests/test_sources.py tools/snap.py tools/record.py
```

---

### Task 3: Synthetic two-camera scene generator

**Files:**
- Create: `pi/kartcv/synth.py`
- Test: `pi/tests/test_synth.py`

**Interfaces:**
- Consumes: `Frame`, `Tick` (Task 2).
- Produces:
  - Constants: `CAM_SIZE = (1280, 720)`, `MAT_SIZE = (800, 500)` (top-down mat, px).
  - `Item(item_id: str, x: int, y: int, w: int = 120, h: int = 90, seed: int = 0)`: the top-left corner on the mat.
  - `item_sprite(seed, w, h) -> np.ndarray`: base color HSV `((seed * 47) % 180, 200, 200)`, three stripes of hue +90, and a 4 px dark border. Distinct per seed.
  - `Scene` dataclass:
    - Fields: `items: list[Item] = []`, `hand: tuple[int, int] | None` (mat center of a skin-colored ellipse 140×90, BGR (120, 160, 220), drawn above items), `brightness: float = 1.0`, `shade: float = 0.0` (darkens the right half of the image with a smooth ramp up to this fraction), `tint: tuple[float, float, float] = (1, 1, 1)` (per-channel BGR gain), `shift: dict[int, tuple[int, int]] = {}` (per-camera translation, px), `hidden: dict[int, set[str]] = {}`.
    - `.render(cam, noise_seed=0) -> np.ndarray` (720×1280×3 uint8). The background is gray (90, 90, 90) with darker grid lines every 40 px (cart wall). The mat is tan (150, 170, 190) with seeded low-amplitude texture (σ 6, blurred). Items and the hand are warped by a fixed per-camera homography. **cam1 sees the mat rotated 180°** (opposite corner). Then brightness, tint, shade, and shift are applied, then Gaussian noise σ 2 seeded by `noise_seed`.
    - `.copy() -> Scene` (deep copy).
  - `project(cam, xy) -> tuple[int, int]` maps a mat point to image pixels. `item_box(cam, item, pad=0.10) -> tuple[x, y, w, h]` is the padded image bbox. `crop_item(cam, item) -> np.ndarray` renders the item alone on the mat and crops `item_box`.
  - `Script(scene: Scene, hz: int = 10, cams=(0, 1))` with `.ticks: list[Tick]`, `.scene`, `.t`. Every method returns `self`, and a tick's `noise_seed` = its index.
    - `still(seconds)`.
    - `drop(item)`: the hand moves in over 0.5 s (5 ticks) to the item center, the item appears on the 5th tick, the hand leaves over 0.5 s (5 ticks, with `hand=None` on the 5th, i.e. fully gone), then `still(1.5)`. All hand trips below use the same 5-in / 5-out shape.
    - `drop_many(items)`: one hand trip that places all of them.
    - `take(item_id)`: the hand comes in, the item disappears on arrival, the hand leaves, then `still(1.5)`.
    - `move(item_id, dx, dy)`.
    - `hand_pass()`: hand in and out, nothing placed.
    - `hand_rest(seconds)`: hand in, still for `seconds`, out, then `still(1.5)`.
    - `set(**scene_fields)`: changes the scene on the next tick, then `still(1.5)`.

- [ ] **Step 1: Write the failing tests**

```python
# pi/tests/test_synth.py
import numpy as np
from kartcv.synth import Scene, Item, Script, item_sprite, item_box

RED = Item("red-box", 300, 200, seed=1)

def changed(a, b): return (np.abs(a.astype(int) - b.astype(int)).sum(2) > 40).mean()

def test_two_distinct_views():
    a, b = Scene().render(0), Scene().render(1)
    assert a.shape == (720, 1280, 3) and changed(a, b) > 0.05

def test_item_visible_in_both_unless_hidden():
    empty, full = Scene(), Scene(items=[RED])
    assert changed(empty.render(0), full.render(0)) > 0.005 and changed(empty.render(1), full.render(1)) > 0.005
    hid = Scene(items=[RED], hidden={0: {"red-box"}})
    assert changed(empty.render(0), hid.render(0)) < 0.001 and changed(empty.render(1), hid.render(1)) > 0.005

def test_sprites_distinct():
    means = [item_sprite(s, 120, 90).reshape(-1, 3).mean(0) for s in (1, 2, 3)]
    assert min(np.linalg.norm(means[i] - means[j]) for i in range(3) for j in range(i + 1, 3)) > 40

def test_item_box_inside_frame():
    x, y, w, h = item_box(1, RED)
    assert 0 <= x and 0 <= y and x + w <= 1280 and y + h <= 720 and w > 40 and h > 30

def test_drop_timeline():
    sc = Script(Scene()).drop(RED)
    assert len(sc.ticks) == 25 and [i.item_id for i in sc.scene.items] == ["red-box"]
    ts = [t[0].ts for t in sc.ticks]
    assert np.allclose(np.diff(ts), 0.1)
    still = [t[0].image for t in sc.ticks[-15:]]
    assert max(changed(still[i], still[i + 1]) for i in range(14)) < 0.001
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pi/.venv/bin/python -m pytest pi/tests/test_synth.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'kartcv.synth'`.

- [ ] **Step 3: Implement `synth.py`** per the Interfaces block. Build each camera homography with `cv2.getPerspectiveTransform` from the mat corners to a fixed image quad that is visibly trapezoidal (far edge narrower). For cam1, feed the mat corners in 180°-rotated order.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `pi/.venv/bin/python -m pytest pi/tests/test_synth.py -q`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add pi/kartcv/synth.py pi/tests/test_synth.py
git commit -m "pi: synthetic two-camera scene generator and timeline script" -- pi/kartcv/synth.py pi/tests/test_synth.py
```

---

### Task 4: Motion and settle

**Files:**
- Create: `pi/kartcv/motion.py`
- Test: `pi/tests/test_motion.py`

**Interfaces:**
- Consumes: `Script`, `Scene`, `Item` (Task 3).
- Produces:
  - `MotionDetector(size=(320, 180), thresh=25, frac=0.005)`: `.update(image) -> bool`. Downscales, converts to gray, applies a 5×5 Gaussian blur, then computes absdiff vs the previous frame. Returns True if the changed fraction exceeds `frac`. The first frame returns False. `.reset()`.
  - `SettleTracker(settle_s=1.0)`: `.update(ts: float, moving: dict[int, bool]) -> bool` returns True exactly once, when motion happened and no camera has moved for ≥ `settle_s`. Cameras absent from `moving` are ignored. `.state -> "idle" | "motion"`. `.reset()`.

- [ ] **Step 1: Write the failing tests**

```python
# pi/tests/test_motion.py
from kartcv.motion import MotionDetector, SettleTracker
from kartcv.synth import Scene, Item, Script

def test_still_frames_no_motion():
    md = MotionDetector()
    assert not any(md.update(t[0].image) for t in Script(Scene()).still(1.0).ticks)

def test_hand_motion_detected():
    md = MotionDetector()
    flags = [md.update(t[0].image) for t in Script(Scene()).drop(Item("red-box", 300, 200, seed=1)).ticks]
    assert sum(flags[:10]) >= 3 and not any(flags[-14:])

def test_settle_fires_once_after_quiet():
    st = SettleTracker(1.0)
    assert [st.update(t, m) for t, m in [(0.0, {0: True, 1: False}), (0.5, {0: False, 1: False}),
            (0.99, {0: False, 1: False}), (1.0, {0: False, 1: False}), (1.5, {0: False, 1: False})]] \
        == [False, False, False, True, False]

def test_no_settle_without_motion_and_either_camera_restarts_clock():
    st = SettleTracker(1.0)
    assert not any(st.update(t / 10, {0: False, 1: False}) for t in range(50))
    st.update(0.0, {0: True, 1: False}); st.update(0.8, {0: False, 1: True})
    assert st.update(1.0, {0: False, 1: False}) is False and st.update(1.8, {0: False, 1: False}) is True

def test_missing_camera_does_not_block():
    st = SettleTracker(1.0); st.update(0.0, {0: True})
    assert st.update(1.0, {0: False}) is True
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pi/.venv/bin/python -m pytest pi/tests/test_motion.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'kartcv.motion'`.

- [ ] **Step 3: Implement `motion.py`** per the Interfaces block.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `pi/.venv/bin/python -m pytest pi/tests/test_motion.py -q`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add pi/kartcv/motion.py pi/tests/test_motion.py
git commit -m "pi: motion detector and settle tracker" -- pi/kartcv/motion.py pi/tests/test_motion.py
```

---

### Task 5: Change detection

**Files:**
- Create: `pi/kartcv/changes.py`
- Test: `pi/tests/test_changes.py`

**Interfaces:**
- Consumes: `Config` (Task 1); `Scene`, `Item`, `project` (Task 3).
- Produces:
  - `lab_distance(a, b) -> np.ndarray` (float32 per pixel): `sqrt((0.5·ΔL)² + Δa² + Δb²)` on `cv2.COLOR_BGR2LAB`.
  - `match_gain(img, target) -> np.ndarray`: scales `img` so its gray median equals `target`'s.
  - `translate(img, dx, dy) -> np.ndarray`: `warpAffine` with edge replication.
  - `Blob(cam, box: tuple[int, int, int, int], area_frac: float, before: np.ndarray, after: np.ndarray)`. `box` is padded by `crop_pad` in full-resolution pixels and clipped to the frame. The crops are cut from the full-resolution frames.
  - `ChangeResult(cam, status: "none" | "disturbed" | "blobs", blobs: list[Blob], changed_frac: float, shift: tuple[float, float], frame: np.ndarray, reference: np.ndarray)`.
  - `detect_changes(cam, reference, current, cfg) -> ChangeResult`. Algorithm, in order:
    1. Resize both to `cfg.diff_size` and convert to gray.
    2. `cv2.phaseCorrelate` (float32, Hanning window) gives `shift`, scaled to full-resolution px. If `hypot(shift) > cfg.max_shift_px` (in diff-size px) → `disturbed`.
    3. Apply `match_gain(current → reference)`, a 7×7 Gaussian blur on both, then `lab_distance > cfg.change_thresh`, then morph open 5×5 and close 15×15 (ellipse).
    4. If `changed_frac > cfg.disturbed_frac` → `disturbed`.
    5. Find connected components with area ≥ `min_blob_frac` → `blobs`; if there are none → `none`.

    This refines spec §5.2 "camera got bumped" with explicit shift detection.

- [ ] **Step 1: Write the failing tests**

```python
# pi/tests/test_changes.py
from kartcv.changes import detect_changes
from kartcv.config import Config
from kartcv.synth import Scene, Item, project

CFG = Config(); RED = Item("red-box", 300, 200, seed=1); BLUE = Item("blue-can", 560, 330, seed=2)

def run(before, after, cam=0):
    return detect_changes(cam, before.render(cam, noise_seed=1), after.render(cam, noise_seed=2), CFG)

def test_identical_is_none():
    assert run(Scene(), Scene()).status == "none"

def test_added_item_one_blob_around_it():
    r = run(Scene(), Scene(items=[RED]))
    assert r.status == "blobs" and len(r.blobs) == 1
    x, y, w, h = r.blobs[0].box; u, v = project(0, (RED.x + RED.w // 2, RED.y + RED.h // 2))
    assert x <= u <= x + w and y <= v <= y + h and r.blobs[0].after.shape[:2] == (h, w)

def test_two_separated_items_two_blobs():
    assert len(run(Scene(), Scene(items=[RED, BLUE])).blobs) == 2

def test_lighting_shadow_wobble_tiny_are_none():
    assert run(Scene(), Scene(brightness=1.3)).status == "none"
    assert run(Scene(), Scene(shade=0.25)).status == "none"            # Review Focus 3
    assert run(Scene(), Scene(shift={0: (2, 1)})).status == "none"
    assert run(Scene(), Scene(items=[Item("dot", 300, 200, w=12, h=12, seed=1)])).status == "none"

def test_bump_and_color_cast_are_disturbed():
    r = run(Scene(), Scene(shift={0: (60, 30)}))
    assert r.status == "disturbed" and r.blobs == [] and abs(r.shift[0] - 60) <= 3 and abs(r.shift[1] - 30) <= 3
    assert run(Scene(), Scene(tint=(0.6, 1.0, 1.5))).status == "disturbed"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pi/.venv/bin/python -m pytest pi/tests/test_changes.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'kartcv.changes'`.

- [ ] **Step 3: Implement `changes.py`** per the Interfaces block. Check the `phaseCorrelate` sign so that `shift` is +x when the content moved right in `current`. The bump test pins it.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `pi/.venv/bin/python -m pytest pi/tests/test_changes.py -q`
Expected: all pass. If a threshold must change to pass, change it in `Config` and in this plan's Global Constraints, and note why in the commit message.

- [ ] **Step 5: Commit**

```bash
git add pi/kartcv/changes.py pi/tests/test_changes.py
git commit -m "pi: change detection with gain normalization and bump detection" -- pi/kartcv/changes.py pi/tests/test_changes.py
```

---

### Task 6: Cart memory

**Files:**
- Create: `pi/kartcv/cart.py`
- Test: `pi/tests/test_cart.py`

**Interfaces:**
- Produces:
  - `View(cam: int, box: tuple[int, int, int, int], fingerprint: list[float], crop_path: str = "")`.
  - `Instance(instance_id: str, product_id: str | None, label: str, added_ts: str, views: dict[int, View])`.
  - `CartMemory(path: Path)`:
    - `.instances: dict[str, Instance]` (insertion-ordered).
    - `.add(product_id, label, views) -> Instance` (uuid4 hex id). `.remove(instance_id) -> Instance`. `.update_views(instance_id, views)` merges per camera.
    - `.views_in(cam) -> list[tuple[Instance, View]]`. `.count(product_id) -> int`. `.shift_views(cam, dx, dy)`. `.clear()`.
    - `.save()` writes JSON atomically (write temp, then `os.replace`). `CartMemory.load(path) -> CartMemory` returns an empty memory if the file is missing.
    - Every mutating method saves.

- [ ] **Step 1: Write the failing tests**

```python
# pi/tests/test_cart.py
from kartcv.cart import CartMemory, View

def v(cam, x=10): return View(cam, (x, 20, 30, 40), [1.0, 0.0])

def test_add_remove_count_persist(tmp_path):
    p = tmp_path / "cart.json"; m = CartMemory(p)
    a = m.add("red-box", "Red", {0: v(0), 1: v(1)}); m.add("red-box", "Red", {0: v(0, 200)}); b = m.add(None, "?", {1: v(1)})
    assert m.count("red-box") == 2 and len(m.views_in(0)) == 2 and len(m.views_in(1)) == 2
    m.remove(b.instance_id)
    m2 = CartMemory.load(p)
    assert list(m2.instances) == list(m.instances) and m2.instances[a.instance_id].views[1].box == (10, 20, 30, 40)

def test_update_shift_clear(tmp_path):
    m = CartMemory(tmp_path / "c.json"); a = m.add("x", "X", {0: v(0)})
    m.update_views(a.instance_id, {1: v(1, 99)}); m.shift_views(0, 5, -3)
    assert set(a.views) == {0, 1} and a.views[0].box == (15, 17, 30, 40)
    m.clear(); assert CartMemory.load(tmp_path / "c.json").instances == {}
    assert CartMemory.load(tmp_path / "missing.json").instances == {}
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pi/.venv/bin/python -m pytest pi/tests/test_cart.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'kartcv.cart'`.

- [ ] **Step 3: Implement `cart.py`** per the Interfaces block.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `pi/.venv/bin/python -m pytest pi/tests/test_cart.py -q`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add pi/kartcv/cart.py pi/tests/test_cart.py
git commit -m "pi: persistent cart memory" -- pi/kartcv/cart.py pi/tests/test_cart.py
```

---

### Task 7: Features, gallery, model fetch

**Files:**
- Create: `pi/kartcv/identify/__init__.py`, `pi/kartcv/identify/features.py`, `pi/kartcv/identify/gallery.py`, `tools/fetch_model.py`
- Test: `pi/tests/test_gallery.py`

**Interfaces:**
- Consumes: `Item`, `crop_item` (Task 3).
- Produces:
  - `FeatureExtractor` protocol: `.name: str`, `.__call__(crop_bgr) -> np.ndarray` (float32, L2-normalized).
  - `HistogramFeatures()`: name `"hist"`. HSV histogram with 8×8×4 bins (256-d), then elementwise square root, then L2-normalized.
  - `OnnxFeatures(model_path)`: name `"onnx:<file stem>"`. Resize to 224×224, BGR→RGB, /255, ImageNet mean `(0.485, 0.456, 0.406)` and std `(0.229, 0.224, 0.225)`, NCHW, onnxruntime CPU. The first output is flattened and L2-normalized.
  - `load_features(model_path, kind="auto") -> FeatureExtractor`: with `kind == "hist"` it returns `HistogramFeatures`. Otherwise it returns `OnnxFeatures` if the file exists and onnxruntime imports, else `HistogramFeatures` (with a warning).
  - `fetch_model(dest: Path) -> Path`:
    - Downloads `MOBILENET_URL = "https://github.com/onnx/models/raw/main/validated/vision/classification/mobilenet/model/mobilenetv2-12.onnx"`.
    - Uses `onnx` to make the output of the last `GlobalAveragePool` node the graph's only output, so the result is a 1280-d embedding.
    - Saves to `dest` and verifies with onnxruntime that the output size is 1280.
  - `Gallery(root: Path, features: FeatureExtractor)`, with public `.root` and `.features`:
    - `.load()`: reads `root/<product_id>/*.jpg` and caches vectors in `root/index.npz`, keyed by relative path + mtime + `features.name`. It re-embeds only changed or new files.
    - `.add(product_id, crop) -> Path` saves `{n:03d}.jpg` and updates the vectors and cache. `.products() -> set[str]`.
    - `.score(crops: list[np.ndarray]) -> list[tuple[str, float]]`: for each crop and each product, the mean of the top-3 cosine similarities (or fewer if the product has fewer examples). These are averaged over crops and returned sorted descending. An empty gallery returns `[]`.

- [ ] **Step 1: Write the failing tests**

```python
# pi/tests/test_gallery.py
import shutil, numpy as np, pytest
from kartcv.config import REPO_ROOT
from kartcv.identify.features import HistogramFeatures, OnnxFeatures, load_features
from kartcv.identify.gallery import Gallery
from kartcv.synth import Item, crop_item

RED, BLUE, GREEN = Item("red-box", 300, 200, seed=1), Item("blue-can", 300, 200, seed=2), Item("green-bag", 300, 200, seed=3)
MODEL = REPO_ROOT / "pi/models/features.onnx"

def test_histogram_features():
    f = HistogramFeatures(); a0, a1, b0 = f(crop_item(0, RED)), f(crop_item(1, RED)), f(crop_item(0, BLUE))
    assert a0.dtype == np.float32 and a0.shape == (256,) and abs(np.linalg.norm(a0) - 1) < 1e-5
    assert a0 @ a1 > a0 @ b0 + 0.2

def test_gallery_scores_and_cache(tmp_path):
    g = Gallery(tmp_path, HistogramFeatures()); g.load()
    assert g.score([crop_item(0, RED)]) == []
    for it in (RED, BLUE, GREEN):
        g.add(it.item_id, crop_item(0, it)); g.add(it.item_id, crop_item(1, it))
    moved = Item("red-box", 520, 60, seed=1)
    ranked = g.score([crop_item(0, moved), crop_item(1, moved)])
    assert ranked[0][0] == "red-box" and ranked[0][1] > ranked[1][1] and len(ranked) == 3
    shutil.copy(tmp_path / "blue-can" / "000.jpg", tmp_path / "blue-can" / "009.jpg")
    g2 = Gallery(tmp_path, HistogramFeatures()); g2.load()
    assert g2.products() == {"red-box", "blue-can", "green-bag"} and (tmp_path / "index.npz").exists()
    assert sum(1 for p in g2._paths if "blue-can" in str(p)) == 3   # picked up the externally added file

def test_load_features_fallback(tmp_path):
    assert isinstance(load_features(tmp_path / "missing.onnx"), HistogramFeatures)

@pytest.mark.skipif(not MODEL.exists(), reason="run tools/fetch_model.py first")
def test_onnx_features_dim():
    v = OnnxFeatures(MODEL)(crop_item(0, RED)); assert v.shape == (1280,) and abs(np.linalg.norm(v) - 1) < 1e-4
```

(`Gallery._paths` is the gallery's list of loaded image paths. It's the one private attribute the tests read.)

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pi/.venv/bin/python -m pytest pi/tests/test_gallery.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'kartcv.identify'`.

- [ ] **Step 3: Implement `features.py`, `gallery.py`, and `tools/fetch_model.py`** (the CLI calls `fetch_model(cfg.path("model_path"))` and prints the saved path).

- [ ] **Step 4: Run the tests, then fetch the real model and rerun**

Run: `pi/.venv/bin/python -m pytest pi/tests/test_gallery.py -q && pi/.venv/bin/python tools/fetch_model.py && pi/.venv/bin/python -m pytest pi/tests/test_gallery.py -q`
Expected: 3 passed + 1 skipped. Then `saved pi/models/features.onnx (1280-d)`. Then 4 passed.

- [ ] **Step 5: Commit** (the model file is gitignored)

```bash
git add pi/kartcv/identify pi/tests/test_gallery.py tools/fetch_model.py
git commit -m "pi: feature extractors, few-shot gallery, model fetch tool" -- pi/kartcv/identify pi/tests/test_gallery.py tools/fetch_model.py
```

---

### Task 8: Cloud identifier and hybrid policy

**Files:**
- Create: `pi/kartcv/identify/cloud.py`, `pi/kartcv/identify/hybrid.py`
- Test: `pi/tests/test_identify.py`

**Interfaces:**
- Consumes: `Catalog` (Task 1); `Gallery` (Task 7).
- Produces:
  - `CloudAnswer(product_id: str | None, confidence: float, label: str)`.
  - `CloudIdentifier(catalog, model: str, timeout_s: float, client=None)`. With no client, it creates `anthropic.Anthropic()`. `.identify(crops: list[np.ndarray]) -> CloudAnswer` **never raises**. Request:
    - Up to 4 crops, each re-encoded as JPEG with long side ≤ 512 px and sent as base64 `image` blocks with `media_type` `image/jpeg`. The images come first, then a text block containing `catalog.prompt_lines()`.
    - A short system prompt: identify the grocery item shown (all photos are the same item from different cameras); answer one catalog id or `"unknown"`.
    - `max_tokens=1024`.
    - `output_config={"effort": "low", "format": {"type": "json_schema", "schema": {...}}}`. The schema properties are `product_id` (`enum` = catalog ids + `"unknown"`), `confidence` (number), and `label` (string). All three are required, with `additionalProperties: false`.
  - Response handling:
    - `stop_reason == "refusal"`, a JSON parse error, an id not in the catalog, `"unknown"`, or `anthropic.APITimeoutError` / `APIConnectionError` / `APIStatusError` all give `CloudAnswer(None, 0.0 or the returned confidence, label or "error: <kind>")`.
    - Confidence is clamped to [0, 1].
  - `Identification(product_id: str | None, confidence: float, method: "local" | "cloud" | "none", label: str)`.
  - `HybridIdentifier(gallery: Gallery | None, cloud: CloudIdentifier | None, catalog, cfg)`. `.identify(crops) -> Identification`. Gallery products that aren't in the current catalog are dropped from the local ranking first, so a product the merchant removed can't be billed. A product added live has no gallery photos, so it always takes the cloud path using its `vision_hint`.
    1. Local accepts if top ≥ `local_min_score` and (top − second ≥ `local_min_margin`, or there is only one ranked product). The label is the catalog name.
    2. Otherwise the cloud accepts if `product_id` is set and confidence ≥ `cloud_min_conf`.
    3. Otherwise the result is `none`. The label is the cloud label if there is one, else the catalog name of the local top guess, else `"unknown item"`. The confidence is the max seen.

- [ ] **Step 1: Write the failing tests**

```python
# pi/tests/test_identify.py
import base64, json, cv2, numpy as np, anthropic
from types import SimpleNamespace as NS
from kartcv.catalog import Catalog, Product
from kartcv.config import Config
from kartcv.identify.cloud import CloudIdentifier, CloudAnswer
from kartcv.identify.hybrid import HybridIdentifier, Identification

CAT = Catalog({p.id: p for p in [Product("kirkland-parmesan", "Kirkland Parmigiano Reggiano", 12.99, "wedge"),
                                 Product("rao-marinara", "Rao's Marinara", 6.99, "jar")]})
CROP = np.full((300, 400, 3), 128, np.uint8)

def _req():
    try: import httpx2 as httpx
    except ImportError: import httpx
    return httpx.Request("POST", "https://api.anthropic.com/v1/messages")

class FakeClient:
    def __init__(self, text=None, stop="end_turn", exc=None):
        self.text, self.stop, self.exc, self.kwargs, self.options = text, stop, exc, None, None
        self.messages = self
    def with_options(self, **kw): self.options = kw; return self
    def create(self, **kw):
        self.kwargs = kw
        if self.exc: raise self.exc
        return NS(stop_reason=self.stop, content=[NS(type="text", text=self.text)])

def ans(pid, conf=0.8, label="x"): return json.dumps({"product_id": pid, "confidence": conf, "label": label})

def test_request_shape():
    fc = FakeClient(ans("kirkland-parmesan")); CloudIdentifier(CAT, "claude-haiku-5-5", 3.0, client=fc).identify([CROP] * 6)
    kw = fc.kwargs; content = kw["messages"][0]["content"]
    imgs = [b for b in content if b["type"] == "image"]
    assert kw["model"] == "claude-haiku-5-5" and fc.options == {"timeout": 3.0, "max_retries": 0} and len(imgs) == 4
    assert imgs[0]["source"]["media_type"] == "image/jpeg" and content[-1]["type"] == "text" and "rao-marinara | Rao's Marinara | jar" in content[-1]["text"]
    assert set(kw["output_config"]["format"]["schema"]["properties"]["product_id"]["enum"]) == {"kirkland-parmesan", "rao-marinara", "unknown"}
    assert kw["output_config"]["effort"] == "low"

def test_images_downscaled():
    fc = FakeClient(ans("unknown")); CloudIdentifier(CAT, "m", 3.0, client=fc).identify([np.zeros((900, 1200, 3), np.uint8)])
    data = base64.b64decode(fc.kwargs["messages"][0]["content"][0]["source"]["data"])
    assert max(cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR).shape[:2]) <= 512

def test_answers_and_failures():                                     # Review Focus 5
    def run(**kw): return CloudIdentifier(CAT, "m", 3.0, client=FakeClient(**kw)).identify([CROP])
    assert run(text=ans("kirkland-parmesan", 0.82, "parm")) == CloudAnswer("kirkland-parmesan", 0.82, "parm")
    assert run(text=ans("unknown", 0.3, "a can")).product_id is None
    assert run(text=ans("made-up", 0.9)).product_id is None
    assert run(text="not json").product_id is None
    assert run(text=ans("rao-marinara"), stop="refusal").product_id is None
    assert run(exc=anthropic.APITimeoutError(request=_req())).product_id is None
    assert run(exc=anthropic.APIConnectionError(request=_req())).product_id is None

class FakeGallery:
    def __init__(self, ranked): self.ranked = ranked
    def score(self, crops): return self.ranked
class FakeCloud:
    def __init__(self, answer): self.answer, self.calls = answer, 0
    def identify(self, crops): self.calls += 1; return self.answer

def hyb(ranked, cloud): return HybridIdentifier(FakeGallery(ranked), cloud, CAT, Config()).identify([CROP])

def test_hybrid_policy():
    c = FakeCloud(CloudAnswer("rao-marinara", 0.9, "jar"))
    assert hyb([("kirkland-parmesan", 0.9), ("rao-marinara", 0.7)], c) == Identification("kirkland-parmesan", 0.9, "local", "Kirkland Parmigiano Reggiano") and c.calls == 0
    assert hyb([("kirkland-parmesan", 0.85)], c).method == "local"
    assert hyb([("kirkland-parmesan", 0.80), ("rao-marinara", 0.76)], c) == Identification("rao-marinara", 0.9, "cloud", "Rao's Marinara")
    assert hyb([("kirkland-parmesan", 0.6)], c).method == "cloud" and hyb([], c).method == "cloud"
    assert hyb([("kirkland-parmesan", 0.6)], FakeCloud(CloudAnswer("rao-marinara", 0.4, "maybe jar"))) == Identification(None, 0.6, "none", "maybe jar")
    assert hyb([("kirkland-parmesan", 0.6)], None) == Identification(None, 0.6, "none", "Kirkland Parmigiano Reggiano")
    assert hyb([("gone-product", 0.95), ("kirkland-parmesan", 0.6)], None) == Identification(None, 0.6, "none", "Kirkland Parmigiano Reggiano")
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pi/.venv/bin/python -m pytest pi/tests/test_identify.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'kartcv.identify.cloud'`.

- [ ] **Step 3: Implement `cloud.py` and `hybrid.py`** per the Interfaces block. Read the JSON from the first content block whose `type == "text"`. The `label` returned on the cloud-accept path is the catalog name, not Claude's free text.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `pi/.venv/bin/python -m pytest pi/tests/test_identify.py -q`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add pi/kartcv/identify/cloud.py pi/kartcv/identify/hybrid.py pi/tests/test_identify.py
git commit -m "pi: Claude closed-set identifier and hybrid local-first policy" -- pi/kartcv/identify/cloud.py pi/kartcv/identify/hybrid.py pi/tests/test_identify.py
```

---

### Task 9: Added/removed decisions and camera combining

**Files:**
- Create: `pi/kartcv/decide.py`, `pi/tests/helpers.py`
- Test: `pi/tests/test_decide.py`

**Interfaces:**
- Consumes:
  - `ChangeResult`, `Blob`, `lab_distance`, `match_gain`, `detect_changes` (Task 5)
  - `CartMemory`, `View`, `Instance` (Task 6)
  - `FeatureExtractor`, `HistogramFeatures`, `Gallery` (Task 7)
  - `HybridIdentifier`, `Identification` (Task 8)
  - `Catalog`, `Product`, `Config` (Task 1)
- Produces:
  - `Decision(kind: "added" | "removed" | "moved", product_id, confidence, method, label, cameras: list[int], blobs: list[Blob], views: dict[int, View], instance_id: str | None)`. `views` holds fingerprints of the *after* crops for added/moved; for removed, `views` is `{}`.
  - `classify_blob(blob, result: ChangeResult, empty: np.ndarray, cart, features, cfg) -> "added" | "removed" | None`. Implements spec §5.3:
    - Cut the box from `empty` and gain-match the frames to it.
    - "≈ empty" means mean `lab_distance` < `empty_thresh`.
    - Both ≈ empty → `None`.
    - Neither → `removed` if some instance's view in this camera overlaps the box (IoU > 0.1) and `features(after) · view.fingerprint ≥ local_min_score`; else `added`.
  - `decide(results, empties: dict[int, np.ndarray], cart, identifier, features, cfg) -> list[Decision]`. Implements spec §5.4:
    - Only `status == "blobs"` results contribute.
    - **Added:** if every camera has ≤ 1 added blob, make one joint `identifier.identify([all added after crops])` call. Otherwise identify each blob, use per-product max-over-cameras counts, fill by confidence up to N = max per-camera count, and add `unknown` for the rest.
    - **Removed:** the score of blob vs instance = `features(before) · fingerprint` of the instance's view in that camera + `0.2 × IoU`. If the instance has no view in that camera, use the max over its views. Each instance's total is the sum over cameras of its best blob score. Take the top N = min(max per-camera removed count, number in cart) instances. `method="memory"`; confidence = that instance's best similarity clipped to [0, 1].
    - **Nudge:** an added decision and a removed decision with the same non-null `product_id` become one `moved` decision (the removed one's `instance_id`, the added one's views).
  - `apply_decision(cart, d) -> Instance | None`: added → `cart.add(...)`; removed → `cart.remove(d.instance_id)`; moved → `cart.update_views(...)`.
- `tests/helpers.py` produces:
  - `SYNTH` (three Items: red-box seed 1, blue-can seed 2, green-bag seed 3).
  - `synth_catalog() -> Catalog`.
  - `world(tmp_path) -> SimpleNamespace(cfg, catalog, features, gallery, identifier, cart, empties)`. It creates `tmp_path` if missing and uses `cfg = Config(features="hist")`, gallery at `tmp_path/"gallery"`, cart at `tmp_path/"world_cart.json"`, and `HistogramFeatures()` always. The gallery is enrolled with `crop_item` for each SYNTH item from both cameras at two positions, `HybridIdentifier(cloud=None)`, `empties = {c: Scene().render(c)}`.
  - `settle(before: Scene, after: Scene, cfg) -> list[ChangeResult]` for cams 0 and 1 (noise seeds 1 and 2).

- [ ] **Step 1: Write the failing tests**

```python
# pi/tests/test_decide.py
from kartcv.changes import ChangeResult
from kartcv.decide import decide, apply_decision, classify_blob
from kartcv.synth import Scene, Item
from helpers import world, settle

RED, BLUE = Item("red-box", 300, 200, seed=1), Item("blue-can", 560, 330, seed=2)

def step(w, before, after):
    ds = decide(settle(before, after, w.cfg), w.empties, w.cart, w.identifier, w.features, w.cfg)
    for d in ds: apply_decision(w.cart, d)
    return ds

def test_one_item_two_cameras_is_one_added(tmp_path):
    w = world(tmp_path); [d] = step(w, Scene(), Scene(items=[RED]))
    assert (d.kind, d.product_id, d.method, sorted(d.cameras)) == ("added", "red-box", "local", [0, 1])

def test_two_items_and_hidden_camera(tmp_path):
    w = world(tmp_path)
    assert {d.product_id for d in step(w, Scene(), Scene(items=[RED, BLUE]))} == {"red-box", "blue-can"}
    w2 = world(tmp_path / "b"); [d] = step(w2, Scene(), Scene(items=[RED], hidden={0: {"red-box"}}))
    assert d.product_id == "red-box" and d.cameras == [1]

def test_disturbed_camera_does_not_block_other(tmp_path):        # Review Focus 2
    w = world(tmp_path); rs = settle(Scene(), Scene(items=[RED]), w.cfg)
    r0 = rs[0]; rs[0] = ChangeResult(0, "disturbed", [], 0.7, (0.0, 0.0), r0.frame, r0.reference)
    [d] = decide(rs, w.empties, w.cart, w.identifier, w.features, w.cfg)
    assert (d.kind, d.product_id) == ("added", "red-box")

def test_removal_from_memory_and_bounds(tmp_path):
    w = world(tmp_path); step(w, Scene(), Scene(items=[RED, BLUE]))
    red_id = next(i.instance_id for i in w.cart.instances.values() if i.product_id == "red-box")
    [d] = step(w, Scene(items=[RED, BLUE]), Scene(items=[BLUE]))
    assert (d.kind, d.product_id, d.method, d.instance_id) == ("removed", "red-box", "memory", red_id)
    assert w.cart.count("red-box") == 0
    w2 = world(tmp_path / "b")
    assert step(w2, Scene(items=[RED]), Scene()) == []           # nothing in cart → nothing removed

def test_nudge_is_moved(tmp_path):
    w = world(tmp_path); step(w, Scene(), Scene(items=[RED]))
    moved = Item("red-box", 450, 200, seed=1)
    assert [d.kind for d in step(w, Scene(items=[RED]), Scene(items=[moved]))] == ["moved"]
    assert w.cart.count("red-box") == 1

def test_stacked_add_then_revealed_removal(tmp_path):
    w = world(tmp_path); big = Item("blue-can", 250, 150, w=300, h=220, seed=2); top = Item("red-box", 330, 210, seed=1)
    step(w, Scene(), Scene(items=[big]))
    rs = settle(Scene(items=[big]), Scene(items=[big, top]), w.cfg)
    assert classify_blob(rs[0].blobs[0], rs[0], w.empties[0], w.cart, w.features, w.cfg) == "added"
    step(w, Scene(items=[big]), Scene(items=[big, top]))
    rs = settle(Scene(items=[big, top]), Scene(items=[big]), w.cfg)
    assert classify_blob(rs[0].blobs[0], rs[0], w.empties[0], w.cart, w.features, w.cfg) == "removed"
    [d] = step(w, Scene(items=[big, top]), Scene(items=[big]))
    assert (d.kind, d.product_id) == ("removed", "red-box") and w.cart.count("blue-can") == 1
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pi/.venv/bin/python -m pytest pi/tests/test_decide.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'kartcv.decide'`.

- [ ] **Step 3: Implement `pi/tests/helpers.py`, then `decide.py`** per the Interfaces block.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `pi/.venv/bin/python -m pytest pi/tests/test_decide.py -q`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add pi/kartcv/decide.py pi/tests/helpers.py pi/tests/test_decide.py
git commit -m "pi: added/removed classification, camera combining, nudge cancel" -- pi/kartcv/decide.py pi/tests/helpers.py pi/tests/test_decide.py
```

---

### Task 10: Event sinks with outbox

**Files:**
- Create: `pi/kartcv/sinks.py`
- Test: `pi/tests/test_sinks.py`

**Interfaces:**
- Consumes: `Event` (Task 1).
- Produces:
  - `Sink` protocol: `.send(event) -> None`, `.close() -> None`.
  - `JsonlSink(path)` appends one `json.dumps(event.to_json())` line per event.
  - `ConsoleSink()` prints `ADDED kirkland-parmesan (local 0.93)`. Unknown products print as `?` with the label in quotes, e.g. `ADDED ? "a can" (none 0.40)`.
  - `MemorySink()` with `.events: list[Event]`.
  - `HttpSink(base_url, anon_key, outbox: Path, post=None, start_thread=True)`:
    - `.send` appends to the outbox file and wakes the worker.
    - `.flush_once(now: float) -> int` sends pending events in order, stops at the first failure, returns the number sent, and rewrites the outbox with the remainder.
    - A failure (status not 2xx, or `OSError`) sets `next_retry = now + min(30, 2**(failures-1))`, so the waits are 1, 2, 4, … capped at 30. Success resets the failure count.
    - `post(url, headers, body) -> int` defaults to `kartcv.http.post_json`.
    - The URL is `f"{base_url.rstrip('/')}/rest/v1/rpc/apply_cart_event"`. Headers: `apikey`, `Authorization: Bearer <key>`, `Content-Type: application/json`.
    - Body: `{"p_cart_id", "p_type", "p_product_id", "p_confidence", "p_source": "vision", "p_label", "p_camera": cameras[0] or None, "p_event_id": event_id, "p_method": method}`. The RPC is idempotent on `p_event_id` (CONTRACT v0.3+), so a retry after a lost response can't double-bill.
    - `.pending() -> int`.

- [ ] **Step 1: Write the failing tests**

```python
# pi/tests/test_sinks.py
import json
from kartcv.events import Event
from kartcv.sinks import JsonlSink, ConsoleSink, MemorySink, HttpSink

def ev(pid="kirkland-parmesan"):
    return Event.new(cart_id="7", type="added", product_id=pid, confidence=0.93, method="local", label="Parm", cameras=[0, 1], crops=[])

class Post:
    def __init__(self, codes): self.codes, self.calls = list(codes), []
    def __call__(self, url, headers, body):
        self.calls.append((url, headers, body)); c = self.codes.pop(0)
        if isinstance(c, Exception): raise c
        return c

def test_jsonl_and_console(tmp_path, capsys):
    s = JsonlSink(tmp_path / "e.jsonl"); s.send(ev()); s.send(ev())
    assert [json.loads(l)["product_id"] for l in (tmp_path / "e.jsonl").read_text().splitlines()] == ["kirkland-parmesan"] * 2
    ConsoleSink().send(ev()); assert "ADDED kirkland-parmesan (local 0.93)" in capsys.readouterr().out
    m = MemorySink(); m.send(ev()); assert len(m.events) == 1

def test_http_payload(tmp_path):
    p = Post([200]); s = HttpSink("https://x.supabase.co/", "k", tmp_path / "o.jsonl", post=p, start_thread=False)
    s.send(ev()); assert s.flush_once(0.0) == 1
    url, headers, body = p.calls[0]
    assert url == "https://x.supabase.co/rest/v1/rpc/apply_cart_event"
    assert headers["apikey"] == "k" and headers["Authorization"] == "Bearer k"
    assert {k: v for k, v in body.items() if k != "p_event_id"} == {"p_cart_id": "7", "p_type": "added",
        "p_product_id": "kirkland-parmesan", "p_confidence": 0.93, "p_source": "vision", "p_label": "Parm",
        "p_camera": 0, "p_method": "local"}
    assert len(body["p_event_id"]) == 36

def test_outbox_order_backoff_and_restart(tmp_path):
    out = tmp_path / "o.jsonl"; p = Post([500, OSError("down"), 200, 200])
    s = HttpSink("https://x", "k", out, post=p, start_thread=False)
    s.send(ev("a")); s.send(ev("b"))
    assert s.flush_once(0.0) == 0 and s.pending() == 2
    assert s.flush_once(0.5) == 0 and len(p.calls) == 1           # backing off 1 s
    assert s.flush_once(1.0) == 0 and s.pending() == 2            # OSError counts as failure, next wait 2 s
    s2 = HttpSink("https://x", "k", out, post=p, start_thread=False)   # restart: outbox survives
    assert s2.pending() == 2 and s2.flush_once(10.0) == 2
    assert [c[2]["p_product_id"] for c in p.calls[-2:]] == ["a", "b"] and s2.pending() == 0

def test_backoff_caps_at_30(tmp_path):
    s = HttpSink("https://x", "k", tmp_path / "o.jsonl", post=Post([500] * 10), start_thread=False); s.send(ev())
    t, waits = 0.0, []
    for _ in range(8):
        s.flush_once(t); waits.append(s.next_retry - t); t = s.next_retry
    assert waits == [1, 2, 4, 8, 16, 30, 30, 30]
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pi/.venv/bin/python -m pytest pi/tests/test_sinks.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'kartcv.sinks'`.

- [ ] **Step 3: Implement `sinks.py`** per the Interfaces block. `next_retry` is a public float (0.0 when nothing is pending). The worker thread loops `flush_once(time.monotonic())` whenever woken or once `next_retry` passes.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `pi/.venv/bin/python -m pytest pi/tests/test_sinks.py -q`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add pi/kartcv/sinks.py pi/tests/test_sinks.py
git commit -m "pi: event sinks with persistent ordered outbox" -- pi/kartcv/sinks.py pi/tests/test_sinks.py
```

---

### Task 11: Pipeline, CLI, end-to-end tests

**Files:**
- Create: `pi/kartcv/pipeline.py`, `pi/main.py`
- Test: `pi/tests/test_pipeline.py`, `pi/tests/test_main.py`

**Interfaces:**
- Consumes: everything above.
- Produces:
  - `Pipeline(cfg, cams: list[int], identifier, features, sinks: list[Sink], state_dir: Path)`. It loads `CartMemory(state_dir/"cart.json")` and the empties `state_dir/empty_cam{k}.jpg`.
  - `.step(tick: Tick) -> list[Event]`, in order:
    1. Apply a pending reset or first-run auto-reset. Auto-reset happens when no empty picture exists and every cam has a frame: empties := frames, references := frames, `cart.clear()`, save empties, log a warning on first run.
    2. Initialize missing references from frames.
    3. Motion per camera; `SettleTracker.update(min frame ts, moving)`.
    4. On settle: `detect_changes` per camera with a frame. For a `disturbed` result with `hypot(shift) > max_shift_px`, translate that cam's empty by `shift` and `cart.shift_views`. Set reference := frame for every camera.
    5. `decide` → for each decision: save crops `state_dir/crops/<event_id>_cam<k>.jpg` (after crop for added, before crop for removed). Fill `View.crop_path`, call `apply_decision`, and build the `Event` (`crops` relative to `state_dir.parent`). Every non-`moved` decision is sent to all sinks.
  - `.request_reset()` is thread-safe and applied on the next complete tick. `.status() -> dict` with keys `state`, `cameras` (`{cam: {"last_ts": float | None}}`), `items`, `last_events` (≤ 10 event dicts). `.latest_frames() -> dict[int, np.ndarray]`. `.cart` attribute.
  - `main(argv: list[str] | None = None) -> int` with subcommands:
    - `live [--config P] [--debug-view]`: 10 Hz loop over `LiveCamera`s; Ctrl-C exits 0.
    - `replay DIR [--config P] [--no-cloud] [--state DIR] [--gallery DIR] [--catalog FILE]`: runs `iter_ticks(load_recording(DIR))`, prints events, returns 0.
    - `reset`: POST `http://127.0.0.1:<port>/reset`; if refused, deletes `cart.json` and `empty_cam*.jpg` and prints `next start will reset`.
  - `build(cfg, env, args) -> tuple[Pipeline, list[Sink]]`:
    - Sinks: Jsonl (`state/events.jsonl`) + Console, plus `HttpSink` when `SUPABASE_URL` and `SUPABASE_ANON_KEY` are set.
    - `CloudIdentifier` only when `ANTHROPIC_API_KEY` is set and not `--no-cloud`. Otherwise warn "local-only mode".
    - `cfg.cart_id` comes from `CART_ID` when set.
    - Catalog: `fetch_catalog(SUPABASE_URL, SUPABASE_ANON_KEY)` when both are set and `--catalog` isn't given. Otherwise, or if the fetch returns `None`, `load_catalog(cfg.path("catalog_path"))`. Log which source was used and the product count.

- [ ] **Step 1: Write the failing tests**

```python
# pi/tests/test_pipeline.py
import numpy as np
from kartcv.config import Config
from kartcv.pipeline import Pipeline
from kartcv.sinks import MemorySink
from kartcv.synth import Scene, Item, Script
from helpers import world

RED, BLUE = Item("red-box", 300, 200, seed=1), Item("blue-can", 560, 330, seed=2)

def make(tmp_path, state="state"):
    w = world(tmp_path); sink = MemorySink()
    return Pipeline(w.cfg, [0, 1], w.identifier, w.features, [sink], tmp_path / state), sink

def run(p, script, start=0):
    out = []
    for tick in script.ticks[start:]: out += p.step(tick)
    return [(e.type, e.product_id) for e in out]

def test_first_run_resets_then_add_and_remove(tmp_path):
    p, sink = make(tmp_path); sc = Script(Scene()).still(1.0)
    assert run(p, sc) == [] and (tmp_path / "state/empty_cam0.jpg").exists()
    n = len(sc.ticks); sc.drop(RED); assert run(p, sc, n) == [("added", "red-box")]
    n = len(sc.ticks); sc.take("red-box"); assert run(p, sc, n) == [("removed", "red-box")]
    assert sink.events[-1].method == "memory" and len(p.cart.instances) == 0
    assert all((tmp_path / c).exists() for c in sink.events[0].crops) and sink.events[0].crops

def test_no_false_events(tmp_path):
    p, _ = make(tmp_path)
    sc = Script(Scene()).still(1.0).hand_pass().set(brightness=1.3).set(shift={0: (2, 1)}).set(shift={0: (60, 30)})
    assert run(p, sc) == []

def test_hand_rest_nets_zero(tmp_path):                           # Review Focus 1
    p, _ = make(tmp_path); ev = run(p, Script(Scene()).still(1.0).hand_rest(1.5))
    assert len(p.cart.instances) == 0 and sum(t == "added" for t, _ in ev) == sum(t == "removed" for t, _ in ev)

def test_bump_or_lighting_drift_then_remove(tmp_path):            # Review Focus 4
    for i, change in enumerate([{"shift": {0: (60, 30)}}, {"brightness": 1.2}]):
        p, _ = make(tmp_path / str(i)); sc = Script(Scene()).still(1.0).drop(RED).set(**change).take("red-box")
        assert run(p, sc)[-1] == ("removed", "red-box")

def test_nudge_two_items_hidden_stack(tmp_path):
    p, _ = make(tmp_path / "a"); sc = Script(Scene()).still(1.0).drop(RED)
    run(p, sc); n = len(sc.ticks); sc.move("red-box", 150, 0)
    assert run(p, sc, n) == [] and p.cart.count("red-box") == 1
    p, _ = make(tmp_path / "b")
    assert sorted(run(p, Script(Scene()).still(1.0).drop_many([RED, BLUE]))) == [("added", "blue-can"), ("added", "red-box")]
    p, sink = make(tmp_path / "c"); run(p, Script(Scene(hidden={0: {"red-box"}})).still(1.0).drop(RED))
    assert sink.events[0].cameras == [1]
    p, _ = make(tmp_path / "d"); big = Item("blue-can", 250, 150, w=300, h=220, seed=2); top = Item("red-box", 330, 210, seed=1)
    assert run(p, Script(Scene()).still(1.0).drop(big).drop(top).take("red-box")) == \
        [("added", "blue-can"), ("added", "red-box"), ("removed", "red-box")]

def test_reset_restart_and_missing_camera(tmp_path):
    p, _ = make(tmp_path); sc = Script(Scene()).still(1.0).drop(RED); run(p, sc)
    p2, _ = make(tmp_path)                                        # restart, same state dir
    assert p2.cart.count("red-box") == 1
    n = len(sc.ticks); sc.take("red-box"); assert run(p2, sc, n) == [("removed", "red-box")]
    n = len(sc.ticks); sc.drop(RED); run(p2, sc, n); p2.request_reset(); n = len(sc.ticks); sc.still(0.5)
    assert run(p2, sc, n) == [] and len(p2.cart.instances) == 0
    p3, _ = make(tmp_path / "m"); sc = Script(Scene()).still(1.0).drop(RED)
    for t in sc.ticks: t[1] = None
    assert run(p3, sc) == [("added", "red-box")]
```

```python
# pi/tests/test_main.py
import json
from pathlib import Path
from kartcv.sources import save_tick
from kartcv.synth import Scene, Item, Script
from helpers import world, SYNTH
import main

def test_replay_cli(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("KART_ENV_FILE", str(tmp_path / "none"))
    for k in ("ANTHROPIC_API_KEY", "SUPABASE_URL", "SUPABASE_ANON_KEY"): monkeypatch.delenv(k, raising=False)
    w = world(tmp_path / "w")
    store = tmp_path / "store.json"
    store.write_text(json.dumps({"products": [{"id": i.item_id, "name": i.item_id, "price": 1.0} for i in SYNTH]}))
    rec = tmp_path / "rec"
    for t in Script(Scene()).still(1.0).drop(Item("red-box", 300, 200, seed=1)).ticks: save_tick(rec, t)
    cfg = tmp_path / "cfg.json"; cfg.write_text('{"features": "hist"}')
    rc = main.main(["replay", str(rec), "--no-cloud", "--state", str(tmp_path / "state"),
                    "--gallery", str(w.gallery.root), "--catalog", str(store), "--config", str(cfg)])
    lines = (tmp_path / "state/events.jsonl").read_text().splitlines()
    assert rc == 0 and [json.loads(l)["type"] for l in lines] == ["added"] and "ADDED red-box" in capsys.readouterr().out
```

(`main.py` lives in `pi/`, so `import main` works through `pythonpath = ["."]`. `main` builds its extractor with `load_features(cfg.path("model_path"), cfg.features)`, and a missing `--config` file means "defaults".)

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pi/.venv/bin/python -m pytest pi/tests/test_pipeline.py pi/tests/test_main.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'kartcv.pipeline'`.

- [ ] **Step 3: Implement `pipeline.py` and `main.py`** per the Interfaces block.

- [ ] **Step 4: Run the whole suite**

Run: `pi/.venv/bin/python -m pytest pi/tests -q`
Expected: all pass.

- [ ] **Step 5: Live smoke test on the Mac camera** (one camera; checks wiring, not accuracy)

Run: `pi/.venv/bin/python pi/main.py live --config pi/tests/out/mac.json` after writing `{"cameras": [0]}` to that file. Wave a hand in front of the camera, then hold still.
Expected: the first run logs the empty-basket reset. After waving and stopping, a line like `ADDED ? "..." (none 0.xx)` or nothing at all, and no traceback. Ctrl-C exits cleanly.

- [ ] **Step 6: Commit**

```bash
git add pi/kartcv/pipeline.py pi/main.py pi/tests/test_pipeline.py pi/tests/test_main.py pi/tests/helpers.py
git commit -m "pi: tick-driven pipeline, live/replay/reset CLI, end-to-end synthetic tests" -- pi/kartcv/pipeline.py pi/main.py pi/tests/test_pipeline.py pi/tests/test_main.py pi/tests/helpers.py
```

---

### Task 12: Control server, debug view, trip-reset watcher

**Files:**
- Create: `pi/kartcv/server.py`, `pi/kartcv/trip.py`
- Modify: `pi/main.py` (start the server and, when Supabase env is set, the trip watcher in `live`)
- Test: `pi/tests/test_server.py`, `pi/tests/test_trip.py`

**Interfaces:**
- Consumes: `Pipeline.status`, `.request_reset`, `.latest_frames` (Task 11).
- Produces:
  - `TripWatcher(base_url, anon_key, cart_id, state_path: Path, on_new_trip: Callable[[], None], get=None, interval_s=2.0, start_thread=True)`:
    - `.poll_once() -> str | None` GETs `f"{base_url.rstrip('/')}/rest/v1/carts?cart_id=eq.{cart_id}&select=trip_id"` (headers `apikey`, `Authorization: Bearer`) and reads `rows[0]["trip_id"]`.
    - If that value differs from the last seen one, it calls `on_new_trip()` and saves `{"trip_id": ...}` to `state_path`.
    - The **first** value ever seen, with no state file, is only recorded and does not reset.
    - Network errors, non-200 responses, an empty row list, or a null `trip_id` change nothing and return `None`.
    - `get(url, headers) -> tuple[int, bytes]` defaults to `kartcv.http.get`. `.stop()`.
  - `main live` starts a `TripWatcher` when `SUPABASE_URL` and `SUPABASE_ANON_KEY` are set. Its `on_new_trip` calls `pipeline.request_reset()`, then refreshes the catalog in place: `new = fetch_catalog(...)`; if `new` is not `None`, `catalog.replace_with(new)`. Products the owner added live are therefore known on the next trip (CONTRACT v0.9 §3a).
  - `ControlServer(port: int, status_fn, reset_fn, frames_fn=None, debug_view=False, crops_dir: Path | None = None)` on a `ThreadingHTTPServer` in a daemon thread. `.start()`, `.stop()`, `.port` (the real port; `0` picks a free one).
  - `GET /status` → 200 JSON. `POST /reset` → calls `reset_fn` and returns 200 `{"ok": true}`.
  - With `debug_view`:
    - `GET /` → 200 HTML: `<img>` tags for `/cam/<k>.jpg` refreshed every 500 ms by JS, plus a list of the last events with crop thumbnails from `/crops/<file>`.
    - `GET /cam/<k>.jpg` → the latest frame as JPEG, or 404.
    - `GET /crops/<name>` → the file from `crops_dir` (name must match `^[\w-]+\.jpg$`), or 404.
  - Without `debug_view`, `/`, `/cam/*`, and `/crops/*` → 404.
  - `main live` starts the server on `cfg.server_port` with `debug_view` from `--debug-view` or the config.

- [ ] **Step 1: Write the failing tests**

```python
# pi/tests/test_server.py
import json, threading, urllib.request, urllib.error, numpy as np, pytest
from kartcv.server import ControlServer

def get(port, path, method="GET"):
    req = urllib.request.Request(f"http://127.0.0.1:{port}{path}", method=method, data=b"" if method == "POST" else None)
    try:
        with urllib.request.urlopen(req, timeout=2) as r: return r.status, r.headers.get("Content-Type"), r.read()
    except urllib.error.HTTPError as e: return e.code, None, b""

def test_status_reset_and_no_debug():
    flag = threading.Event(); s = ControlServer(0, lambda: {"items": 2, "state": "idle"}, flag.set); s.start()
    try:
        code, _, body = get(s.port, "/status"); assert code == 200 and json.loads(body)["items"] == 2
        assert get(s.port, "/reset", "POST")[0] == 200 and flag.is_set()
        assert get(s.port, "/")[0] == 404 and get(s.port, "/cam/0.jpg")[0] == 404
    finally: s.stop()

def test_debug_view(tmp_path):
    (tmp_path / "abc_cam0.jpg").write_bytes(b"\xff\xd8\xff")
    s = ControlServer(0, lambda: {"last_events": []}, lambda: None, frames_fn=lambda: {0: np.zeros((72, 128, 3), np.uint8)},
                      debug_view=True, crops_dir=tmp_path); s.start()
    try:
        code, ctype, body = get(s.port, "/"); assert code == 200 and "text/html" in ctype and b"/cam/0.jpg" in body
        code, ctype, _ = get(s.port, "/cam/0.jpg"); assert code == 200 and ctype == "image/jpeg"
        assert get(s.port, "/cam/5.jpg")[0] == 404 and get(s.port, "/crops/abc_cam0.jpg")[0] == 200
        assert get(s.port, "/crops/..%2Fsecret.jpg")[0] == 404
    finally: s.stop()
```

```python
# pi/tests/test_trip.py
import json
from kartcv.trip import TripWatcher

class Get:
    def __init__(self, replies): self.replies, self.urls = list(replies), []
    def __call__(self, url, headers):
        self.urls.append((url, headers)); r = self.replies.pop(0)
        if isinstance(r, Exception): raise r
        return r

def rows(tid): return (200, json.dumps([{"trip_id": tid}]).encode())

def test_first_seen_records_then_change_resets(tmp_path):
    resets = []; g = Get([rows("t1"), rows("t1"), OSError("down"), (500, b""), (200, b"[]"), rows(None), rows("t2")])
    w = TripWatcher("https://x.supabase.co/", "k", "7", tmp_path / "trip.json", lambda: resets.append(1), get=g, start_thread=False)
    assert w.poll_once() == "t1" and resets == []
    for _ in range(5): w.poll_once()
    assert resets == []
    w.poll_once(); assert resets == [1] and json.loads((tmp_path / "trip.json").read_text()) == {"trip_id": "t2"}
    url, headers = g.urls[0]
    assert url == "https://x.supabase.co/rest/v1/carts?cart_id=eq.7&select=trip_id" and headers["apikey"] == "k"

def test_change_while_off_resets_at_startup(tmp_path):
    (tmp_path / "trip.json").write_text('{"trip_id": "old"}'); resets = []
    w = TripWatcher("https://x", "k", "7", tmp_path / "trip.json", lambda: resets.append(1), get=Get([rows("new")]), start_thread=False)
    w.poll_once(); assert resets == [1]
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pi/.venv/bin/python -m pytest pi/tests/test_server.py pi/tests/test_trip.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'kartcv.server'`.

- [ ] **Step 3: Implement `server.py` and `trip.py`, and wire both into `main live`.** The `reset_fn` and `on_new_trip` passed by `main` are both `pipeline.request_reset`.

- [ ] **Step 4: Run the whole suite**

Run: `pi/.venv/bin/python -m pytest pi/tests -q`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add pi/kartcv/server.py pi/kartcv/trip.py pi/main.py pi/tests/test_server.py pi/tests/test_trip.py
git commit -m "pi: control server, debug view, trip_id reset watcher" -- pi/kartcv/server.py pi/kartcv/trip.py pi/main.py pi/tests/test_server.py pi/tests/test_trip.py
```

---

### Task 13: Enrollment and the run guide

**Files:**
- Create: `pi/kartcv/enroll.py`, `tools/enroll.py`, `pi/README.md`
- Test: `pi/tests/test_enroll.py`

**Interfaces:**
- Consumes: `Pipeline` (Task 11), `Gallery` (Task 7), `Catalog`, `Config`, `Tick`.
- Produces:
  - `run_enrollment(ticks: Iterable[Tick], product_id: str, rounds: int, gallery: Gallery, catalog: Catalog, cfg: Config, work_dir: Path, on_progress=print) -> int`:
    - Raises `ValueError` if `product_id` isn't in the catalog.
    - Runs a `Pipeline` in `work_dir` (its own state, not the real cart) with `features=gallery.features` and an identifier that always returns `Identification(product_id, 1.0, "local", name)`.
    - On each `added` event, it adds every crop file of that event to the gallery via `gallery.add(product_id, cv2.imread(path))`.
    - Prints `captured k/rounds: take it out` after each add and `put it back in a new pose` after each removal.
    - Stops after `rounds` added events and returns the count.
  - `tools/enroll.py PRODUCT_ID [--rounds 5] [--config P]`: live cameras feed ticks at 10 Hz; it prints `put PRODUCT_ID in the cart` first.
  - `pi/README.md`, plain English for whoever runs `pi/` on the Pi (the hardware chat or the operator):
    - **Install:** `sudo apt install -y python3-opencv python3-numpy python3-venv v4l-utils`; `python3 -m venv --system-site-packages ~/venv`; `~/venv/bin/pip install -r pi/requirements-pi.txt`; `~/venv/bin/python tools/fetch_model.py`.
    - **Configure:** copy `pi/config.example.json` → `pi/config.json`, run `tools/snap.py --list`, and paste the two `-video-index0` `/dev/v4l/by-path/...` paths into `cameras`.
    - **Run command for autostart:** `~/venv/bin/python pi/main.py live`, from the repo root, restarted on exit. The hardware chat owns the systemd unit.
    - The spec §14 milestone checks, each as "do this → you should see that".
    - The enrollment how-to.
    - Two warnings: the cart floor needs a solid mat, and the cart must be empty on first start (or run `python pi/main.py reset` with it empty).

- [ ] **Step 1: Write the failing tests**

```python
# pi/tests/test_enroll.py
import pytest
from kartcv.config import Config
from kartcv.enroll import run_enrollment
from kartcv.identify.features import HistogramFeatures
from kartcv.identify.gallery import Gallery
from kartcv.synth import Scene, Item, Script
from helpers import synth_catalog

def test_enroll_three_rounds(tmp_path):
    sc = Script(Scene()).still(1.0)
    for x in (150, 300, 450): sc.drop(Item("red-box", x, 200, seed=1)).take("red-box")
    g = Gallery(tmp_path / "gallery", HistogramFeatures()); g.load(); msgs = []
    n = run_enrollment(sc.ticks, "red-box", 3, g, synth_catalog(), Config(), tmp_path / "work", on_progress=msgs.append)
    assert n == 3 and len(list((tmp_path / "gallery/red-box").glob("*.jpg"))) == 6     # 2 cameras × 3 rounds
    assert any("captured 3/3" in m for m in msgs)

def test_enroll_unknown_product(tmp_path):
    with pytest.raises(ValueError):
        run_enrollment([], "nope", 1, Gallery(tmp_path, HistogramFeatures()), synth_catalog(), Config(), tmp_path / "w")
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pi/.venv/bin/python -m pytest pi/tests/test_enroll.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'kartcv.enroll'`.

- [ ] **Step 3: Implement `enroll.py`, `tools/enroll.py`, and write `pi/README.md`** per the Interfaces block.

- [ ] **Step 4: Run the whole suite**

Run: `pi/.venv/bin/python -m pytest pi/tests -q`
Expected: all pass (1 skipped if the ONNX model isn't fetched).

- [ ] **Step 5: Commit**

```bash
git add pi/kartcv/enroll.py tools/enroll.py pi/tests/test_enroll.py pi/README.md
git commit -m "pi: product enrollment through the real pipeline, run guide" -- pi/kartcv/enroll.py tools/enroll.py pi/tests/test_enroll.py pi/README.md
```

---

## Hardware follow-up (not part of this plan's execution)

These happen once the Pi and Brios are set up, following `pi/README.md`. The hardware chat owns Pi setup and the autostart unit.
1. Install the dependencies and set the camera paths in `pi/config.json`.
2. Check milestones 1–3 on the real cart.
3. Enroll the demo props from `data/store.json`.
4. Record replay clips with `tools/record.py` and tune `change_thresh`, `empty_thresh`, and `local_min_score`/`local_min_margin` against them.
5. Add the clips as regression fixtures.
