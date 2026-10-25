#!/usr/bin/env python3
"""Behind-the-scenes clips for the demo video: the cart's camera (with its floor outline) and what it
decided, one MP4 per add or remove, read from a running cart's debug page. Laptop side, read-only.

  python tools/bts_record.py --host 192.168.137.127        # Ctrl+C to stop
  -> tools/out/bts/<session>/HHMMSS_added_<product>.mp4    (3 s before to 5 s after each event)
     tools/out/bts/<session>/full.mp4, events.csv

Safe for a running cart: plain GETs only (/status every 0.5 s, one camera ~6 fps); never resets it,
never touches Supabase. The cart needs its debug view on (debug_view in its config).
Camera: cam1 if the cart has two, else its only one (--cam to choose).
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import sys
import time
from collections import deque
from datetime import datetime
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "pi"))

from kartcv import http  # noqa: E402
from kartcv.config import REPO_ROOT  # noqa: E402
from kartcv.remote import discover_cams  # noqa: E402

HOW = {"cloud": "named by Claude {c:.2f}", "local": "recognized on-cart {c:.2f}",
       "none": "unsure -> asks the shopper", "memory": "matched by where it was"}
INSET = {"cloud": "what Claude saw", "local": "what it matched", "none": "what Claude saw",
         "memory": "what was taken out"}


def pick_cam(cams: list[int]) -> int:
    """cam1, the wide top view, if there are two; a cam1-only cart serves it as camera 0."""
    return 1 if 1 in cams else cams[0]


def caption(ev: dict) -> str:
    kind = str(ev.get("type", "")).upper()
    method = "memory" if kind == "REMOVED" else ev.get("method", "")
    name = "unrecognized item" if method == "none" else str(ev.get("label") or ev.get("product_id") or "item")
    how = HOW.get(method, "").format(c=float(ev.get("confidence") or 0.0))
    return "  |  ".join(x for x in (kind, name[:44], how) if x)


def burn(img: np.ndarray, text: str, inset: np.ndarray | None = None, inset_label: str = "") -> np.ndarray:
    """A dark lower-third with the decision, and the event's crop as a small inset, top right."""
    out = img.copy()
    h, w = out.shape[:2]
    band = max(28, int(h * 0.11))
    shade = out.copy()
    cv2.rectangle(shade, (0, h - band), (w, h), (0, 0, 0), -1)
    out = cv2.addWeighted(shade, 0.65, out, 0.35, 0)
    scale = 0.45 * band / 28
    font = cv2.FONT_HERSHEY_DUPLEX
    while scale > 0.3 and cv2.getTextSize(text, font, scale, 1)[0][0] > w * 0.94:
        scale -= 0.05
    thick = max(1, int(round(scale * 1.6)))
    cv2.putText(out, text, (int(w * 0.03), h - int(band * 0.32)), font, scale, (255, 255, 255), thick, cv2.LINE_AA)
    if inset is not None and inset.size:
        iw = int(w * 0.26)
        ih = max(1, int(inset.shape[0] * iw / inset.shape[1]))
        ih = min(ih, int(h * 0.45))
        small = cv2.resize(inset, (iw, ih), interpolation=cv2.INTER_AREA)
        x, y = w - iw - int(w * 0.02), int(h * 0.04)
        cv2.rectangle(out, (x - 2, y - 2), (x + iw + 1, y + ih + 1), (255, 255, 255), 2)
        out[y:y + ih, x:x + iw] = small
        if inset_label:
            cv2.putText(out, inset_label, (x, y + ih + int(18 * scale / 0.45)), font, scale * 0.8, (255, 255, 255),
                        1, cv2.LINE_AA)
    return out


def open_writer(path: Path, fps: float, size: tuple[int, int]) -> cv2.VideoWriter:
    """H.264 if this OpenCV has it, otherwise MPEG-4 (Windows' opencv-python usually lacks H.264)."""
    for codec in ("avc1", "mp4v"):
        w = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*codec), fps, size)
        if w.isOpened():
            return w
        w.release()
    raise OSError(f"can't write {path}: no MP4 codec in this OpenCV")


class BtsRecorder:
    def __init__(self, base: str, out: Path, cam: int | None = None, fps: float = 6.0, pre: float = 3.0,
                 post: float = 5.0, quality: int = 80, get=None):
        self.base, self.out, self.cam = base.rstrip("/"), Path(out), cam
        self.fps, self.pre, self.post, self.quality = fps, pre, post, quality
        self.get = get or http.get
        self.frames: deque = deque()  # (t, image), the last pre + post seconds and a bit
        self.pending: list[tuple[float, datetime, dict, np.ndarray | None]] = []
        self.seen: set[str] = set()
        self.size: tuple[int, int] | None = None
        self.full = None
        self.full_t = None  # time the next frame of full.mp4 stands for
        self.last_status = -1e9
        self.clips = 0

    def start(self) -> None:
        self.out.mkdir(parents=True, exist_ok=True)
        if self.cam is None:
            self.cam = pick_cam(discover_cams(self.base, get=self.get))
        for e in self._events():  # what's in the log already happened before we started
            self.seen.add(e.get("event_id", ""))
        with open(self.out / "events.csv", "w", newline="") as f:
            csv.writer(f).writerow(["time", "type", "product_id", "label", "method", "confidence", "cameras", "clip"])

    def _events(self) -> list[dict]:
        status, body = self.get(f"{self.base}/status", {})
        return json.loads(body).get("last_events", []) if status == 200 else []

    def _image(self, path: str) -> np.ndarray | None:
        try:
            status, body = self.get(f"{self.base}{path}", {})
        except OSError:
            return None
        if status != 200:
            return None
        return cv2.imdecode(np.frombuffer(body, np.uint8), cv2.IMREAD_COLOR)

    def step(self, now: float) -> None:
        img = self._image(f"/cam/{self.cam}.jpg?overlay=1&q={self.quality}")
        if img is not None:
            if self.size is None:
                self.size = (img.shape[1], img.shape[0])
                self.full = open_writer(self.out / "full.mp4", self.fps, self.size)
                self.full_t = now
            elif (img.shape[1], img.shape[0]) != self.size:
                img = cv2.resize(img, self.size)
            self.frames.append((now, img))
            while self.frames and self.frames[0][0] < now - self.pre - self.post - 2.0:
                self.frames.popleft()
            while self.full_t <= now:  # constant frame rate: repeat the latest frame through any stall
                self.full.write(img)
                self.full_t += 1.0 / self.fps
        if now - self.last_status >= 0.5:
            self.last_status = now
            try:
                for e in self._events():
                    if e.get("event_id", "") in self.seen or e.get("type") not in ("added", "removed"):
                        continue
                    self.seen.add(e.get("event_id", ""))
                    crops = e.get("crops") or []
                    inset = self._image("/crops/" + crops[0].split("/")[-1]) if crops else None
                    self.pending.append((now, datetime.now(), e, inset))
                    print(f"  {caption(e)}")
            except (OSError, ValueError):
                pass  # the cart missed a beat; the next poll catches up
        self._flush(now)

    def _flush(self, now: float, final: bool = False) -> None:
        for job in [j for j in self.pending if final or now >= j[0] + self.post]:
            self.pending.remove(job)
            self._write_clip(*job)

    def _write_clip(self, t: float, when: datetime, e: dict, inset) -> None:
        if not self.frames:
            return
        product = re.sub(r"[^A-Za-z0-9-]+", "-", str(e.get("product_id") or "unknown")).strip("-") or "unknown"
        stamp = when.strftime("%H%M%S")
        name, n = f"{stamp}_{e.get('type')}_{product}.mp4", 1
        while (self.out / name).exists():  # two events in one second
            n += 1
            name = f"{stamp}_{e.get('type')}_{product}_{n}.mp4"
        writer = open_writer(self.out / name, self.fps, self.size)
        text = caption(e)
        label = INSET.get("memory" if e.get("type") == "removed" else e.get("method"), "")
        frames = list(self.frames)
        for k in range(int(round((self.pre + self.post) * self.fps))):
            at = t - self.pre + k / self.fps
            img = next((f for ft, f in reversed(frames) if ft <= at + 1e-6), frames[0][1])
            writer.write(burn(img, text, inset, label) if at >= t - 1e-6 else img)  # the decision shows at T
        writer.release()
        self.clips += 1
        with open(self.out / "events.csv", "a", newline="") as f:
            csv.writer(f).writerow([when.strftime("%H:%M:%S"), e.get("type"), e.get("product_id"),
                                    e.get("label"), e.get("method"), e.get("confidence"), e.get("cameras"), name])
        print(f"  wrote {name}")

    def close(self, now: float) -> None:
        self._flush(now, final=True)
        if self.full is not None:
            self.full.release()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--host", default="smartcart.local")
    ap.add_argument("--port", type=int, default=8080)
    ap.add_argument("--cam", type=int, help="camera to film (default: cam1 if there are two, else the only one)")
    ap.add_argument("--fps", type=float, default=6.0)
    ap.add_argument("--pre", type=float, default=3.0, help="seconds before each event")
    ap.add_argument("--post", type=float, default=5.0, help="seconds after each event")
    ap.add_argument("--seconds", type=float, help="stop after this long (default: until Ctrl+C)")
    ap.add_argument("--out", type=Path)
    args = ap.parse_args()
    base = f"http://{args.host}:{args.port}"
    out = args.out or REPO_ROOT / "tools/out/bts" / datetime.now().strftime("%Y%m%d-%H%M%S")
    rec = BtsRecorder(base, out, args.cam, args.fps, args.pre, args.post)
    try:
        rec.start()
    except (OSError, ValueError) as e:
        print(f"can't reach {base}/status ({e}). Same Wi-Fi as the cart? Is its debug view on?")
        return 1
    print(f"filming cam{rec.cam} from {base} -> {out}  (Ctrl+C to stop)")
    t_end = time.monotonic() + args.seconds if args.seconds else None
    now = time.monotonic()
    try:
        while t_end is None or now < t_end:
            now = time.monotonic()
            rec.step(now)
            time.sleep(max(0.0, 1.0 / args.fps - (time.monotonic() - now)))
    except KeyboardInterrupt:
        pass
    rec.close(time.monotonic())
    print(f"done: {rec.clips} clips + full.mp4 + events.csv in {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
