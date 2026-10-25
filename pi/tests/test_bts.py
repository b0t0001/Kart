"""tools/bts_record.py: behind-the-scenes clips from a running cart's debug page (laptop side, read-only)."""
import csv
import importlib.util
import json

import cv2
import numpy as np

from kartcv.config import REPO_ROOT

spec = importlib.util.spec_from_file_location("bts_record", REPO_ROOT / "tools/bts_record.py")
bts = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bts)


def jpeg(img):
    return cv2.imencode(".jpg", img)[1].tobytes()


class FakeCart:
    """The cart's debug server, as the frozen Pi serves it: /status, /cam/N.jpg, /crops/<name>."""

    def __init__(self):
        self.events, self.urls, self.tick = [], [], 0

    def __call__(self, url, headers, timeout=5.0):
        self.urls.append(url)
        path = url.split(":8080", 1)[1].split("?")[0]
        if path == "/status":
            return 200, json.dumps({"cameras": {"0": {}}, "last_events": self.events[-10:]}).encode()
        if path == "/cam/0.jpg":
            self.tick += 1
            return 200, jpeg(np.full((180, 320, 3), self.tick % 200, np.uint8))
        if path == "/crops/e2_cam0.jpg":
            return 200, jpeg(np.full((60, 80, 3), 90, np.uint8))
        return 404, b""


def ev(i, kind, method, label, pid, conf, crops=()):
    return {"event_id": f"e{i}", "type": kind, "product_id": pid, "label": label, "method": method,
            "confidence": conf, "cameras": [0], "crops": list(crops)}


def test_one_clip_per_add_or_remove_plus_full_and_csv(tmp_path):
    cart = FakeCart()
    cart.events.append(ev(1, "added", "cloud", "Barilla Spaghetti, 1 lb", "barilla-spaghetti", 0.97))  # before: skip
    rec = bts.BtsRecorder("http://cart:8080", tmp_path, fps=6, pre=1.0, post=1.0, get=cart)
    rec.start()
    t = 0.0
    for i in range(60):  # 10 s at 6 fps
        t = i / 6
        if i == 18:
            cart.events.append(ev(2, "added", "cloud", "Good & Gather Marinara Pasta Sauce, 23 oz", "rao-marinara",
                                  0.85, ["state/crops/e2_cam0.jpg"]))
        if i == 40:
            cart.events.append(ev(3, "removed", "memory", "Good & Gather Marinara Pasta Sauce, 23 oz",
                                  "rao-marinara", 0.98))
        rec.step(t)
    rec.close(t)
    clips = sorted(p.name for p in tmp_path.glob("*_*.mp4"))
    assert len(clips) == 2 and clips[0].endswith("_added_rao-marinara.mp4") and "_removed_rao-marinara" in clips[1]
    cap = cv2.VideoCapture(str(tmp_path / clips[0]))
    assert int(cap.get(cv2.CAP_PROP_FRAME_COUNT)) == 12  # 1 s before + 1 s after, at 6 fps
    full = cv2.VideoCapture(str(tmp_path / "full.mp4"))
    assert int(full.get(cv2.CAP_PROP_FRAME_COUNT)) >= 55
    rows = list(csv.DictReader(open(tmp_path / "events.csv")))
    assert [(r["type"], r["product_id"], r["method"]) for r in rows] == \
        [("added", "rao-marinara", "cloud"), ("removed", "rao-marinara", "memory")]
    assert all("POST" not in u and "reset" not in u for u in cart.urls)  # read-only


def test_lower_third_says_how_it_was_decided():
    assert bts.caption(ev(1, "added", "cloud", "Barilla Spaghetti, 1 lb", "barilla-spaghetti", 0.97)) == \
        "ADDED  |  Barilla Spaghetti  |  named by Claude 0.97"  # the name without its size
    assert bts.caption(ev(1, "added", "local", "Kids' Scissors", "kids-scissors", 0.72)).endswith("recognized on-cart 0.72")
    assert bts.caption(ev(1, "added", "none", "gray fabric, no grocery item visible", None, 0.4)) == \
        "ADDED  |  unrecognized item  |  unsure -> asks the shopper"
    assert bts.caption(ev(1, "removed", "memory", "Barilla Spaghetti, 1 lb", "barilla-spaghetti", 0.98)).endswith(
        "matched by where it was")


def test_picks_cam1_when_there_are_two_and_the_only_one_otherwise():
    assert bts.pick_cam([0, 1]) == 1 and bts.pick_cam([0]) == 0


cut_spec = importlib.util.spec_from_file_location("bts_cut", REPO_ROOT / "tools/bts_cut.py")
cut = importlib.util.module_from_spec(cut_spec)
cut_spec.loader.exec_module(cut)


def test_cutting_clips_from_saved_frames_and_the_carts_event_log(tmp_path):
    from datetime import datetime, timezone
    frames = REPO_ROOT / "pi/tests/clips/count-add2-remove1/cam1"  # <epoch_ms>.jpg at 5 Hz, as the laptop saves
    stamps = sorted(int(p.stem) for p in frames.glob("*.jpg"))
    at = lambda ms: datetime.fromtimestamp(ms / 1000, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")  # noqa: E731
    t_add, t_rem = stamps[len(stamps) // 3], stamps[2 * len(stamps) // 3]
    log = tmp_path / "events.jsonl"
    rows = [ev(0, "added", "cloud", "Barilla Spaghetti, 1 lb", "barilla-spaghetti", 0.9) | {"ts": "2020-01-01T00:00:00Z"},
            ev(1, "added", "cloud", "Barilla Spaghetti, 1 lb", "barilla-spaghetti", 0.97,
               ["state/crops/e1_cam0.jpg"]) | {"ts": at(t_add)},
            ev(2, "removed", "memory", "Barilla Spaghetti, 1 lb", "barilla-spaghetti", 0.98) | {"ts": at(t_rem)}]
    log.write_text("".join(json.dumps(r) + "\n" for r in rows))
    crops = tmp_path / "crops"
    crops.mkdir()
    cv2.imwrite(str(crops / "e1_cam0.jpg"), np.full((60, 80, 3), 90, np.uint8))
    out = tmp_path / "out"
    made = cut.cut(frames, log, out, crops_dir=crops, fps=5, pre=3, post=5)
    assert [p.name.split("_", 1)[1] for p in made] == ["added_barilla-spaghetti.mp4", "removed_barilla-spaghetti.mp4"]
    assert int(cv2.VideoCapture(str(made[0])).get(cv2.CAP_PROP_FRAME_COUNT)) == 40  # 3 s + 5 s at 5 fps
    span = (stamps[-1] - stamps[0]) / 1000
    assert abs(int(cv2.VideoCapture(str(out / "full.mp4")).get(cv2.CAP_PROP_FRAME_COUNT)) - span * 5) <= 6
    rows = list(csv.DictReader(open(out / "events.csv")))
    assert [r["type"] for r in rows] == ["added", "removed"]  # the 2020 event is from another session


def test_long_names_never_touch_the_method_text():  # field: "...Marinara Pasta Saucenamed by Claude 0.93"
    parts = ["ADDED", "Good & Gather Marinara Pasta Sauce Family Size Extra Chunky", "named by Claude 0.93"]
    for w, h in ((1280, 720), (640, 360), (320, 180)):
        scale, items = bts.layout(parts, w, max(28, int(h * 0.11)))
        texts = [it for it in items if it[0] == "text"]
        assert texts[-1][2] + texts[-1][3] <= w * 0.97  # fits the frame
        gaps = [b[2] - (a[2] + a[3]) for a, b in zip(texts, texts[1:])]
        assert min(gaps) >= w * 0.02  # room for the dot on both sides, always
    _, items = bts.layout(parts, 320, 28)
    assert any(it[1].endswith("...") for it in items if it[0] == "text")  # too long even small: cut, marked


def test_h264_through_ffmpeg_when_it_is_installed(tmp_path):
    import shutil
    import pytest
    if not shutil.which("ffmpeg"):
        pytest.skip("no ffmpeg on PATH")
    w = bts.open_writer(tmp_path / "x.mp4", 6, (320, 180))
    for i in range(12):
        w.write(np.full((180, 320, 3), i * 10, np.uint8))
    w.release()
    cap = cv2.VideoCapture(str(tmp_path / "x.mp4"))
    codec = int(cap.get(cv2.CAP_PROP_FOURCC)).to_bytes(4, "little").decode(errors="replace").lower()
    assert int(cap.get(cv2.CAP_PROP_FRAME_COUNT)) == 12 and codec in ("avc1", "h264")


def test_a_long_name_is_cut_at_a_word_and_marked():
    e = ev(1, "removed", "memory", "Market Pantry Grated Parmesan Cheese Shaker Family Size, 8 oz", "x", 0.9)
    name = bts.caption_parts(e)[1]
    assert name.endswith("...") and name[:-3].split()[-1] in "Market Pantry Grated Parmesan Cheese Shaker Family".split()
