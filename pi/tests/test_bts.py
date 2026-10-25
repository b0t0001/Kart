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
        "ADDED  |  Barilla Spaghetti, 1 lb  |  named by Claude 0.97"
    assert bts.caption(ev(1, "added", "local", "Kids' Scissors", "kids-scissors", 0.72)).endswith("recognized on-cart 0.72")
    assert bts.caption(ev(1, "added", "none", "gray fabric, no grocery item visible", None, 0.4)) == \
        "ADDED  |  unrecognized item  |  unsure -> asks the shopper"
    assert bts.caption(ev(1, "removed", "memory", "Barilla Spaghetti, 1 lb", "barilla-spaghetti", 0.98)).endswith(
        "matched by where it was")


def test_picks_cam1_when_there_are_two_and_the_only_one_otherwise():
    assert bts.pick_cam([0, 1]) == 1 and bts.pick_cam([0]) == 0
