#!/usr/bin/env python3
"""Cut behind-the-scenes clips for the demo video, offline, from frames a laptop saved off the cart's
debug page and the cart's own event log.

  python tools/bts_cut.py FRAMES_DIR EVENTS_JSONL [--crops CROPS_DIR] [--offset SECONDS]

FRAMES_DIR    <epoch_ms>.jpg frames (e.g. /cam/0.jpg?overlay=1 saved at 5 Hz)
EVENTS_JSONL  the cart's pi/state/events.jsonl, copied off it (only events during the frames are used)
--crops       the cart's pi/state/crops/, for the "what Claude saw" inset
--offset      seconds to add to the cart's event times if its clock and the laptop's differ
-> FRAMES_DIR-bts/: HHMMSS_<added|removed>_<product>.mp4 (3 s before to 5 s after each event),
   full.mp4 (the whole stretch, each decision captioned for 5 s), events.csv
Needs only Python, opencv-python and numpy (Windows OK).
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from datetime import datetime
from pathlib import Path

import cv2

sys.path.insert(0, str(Path(__file__).resolve().parent))

from bts_record import INSET, burn, caption, caption_parts, open_writer  # noqa: E402


def load_frames(folder: Path) -> list[tuple[float, Path]]:
    return sorted((int(p.stem) / 1000.0, p) for p in Path(folder).glob("*.jpg") if p.stem.isdigit())


def load_events(path: Path, t0: float, t1: float, offset: float = 0.0) -> list[dict]:
    """ADDED/REMOVED events whose time (the cart's clock, + offset) falls between t0 and t1."""
    out = []
    for line in Path(path).read_text().splitlines():
        try:
            e = json.loads(line)
            t = datetime.fromisoformat(str(e["ts"]).replace("Z", "+00:00")).timestamp() + offset
        except (ValueError, KeyError, TypeError):
            continue
        if e.get("type") in ("added", "removed") and t0 <= t <= t1:
            out.append({**e, "_t": t})
    return sorted(out, key=lambda e: e["_t"])


class Frames:
    """Frames by time: the latest one at or before t (each image read once, kept while it's the latest)."""

    def __init__(self, frames: list[tuple[float, Path]], size: tuple[int, int]):
        self.frames, self.size, self.i, self.img = frames, size, -1, None

    def at(self, t: float):
        i = self.i
        while i + 1 < len(self.frames) and self.frames[i + 1][0] <= t + 1e-6:
            i += 1
        i = max(i, 0)
        if i != self.i or self.img is None:
            self.i = i
            img = cv2.imread(str(self.frames[i][1]), cv2.IMREAD_COLOR)
            self.img = img if img is None or (img.shape[1], img.shape[0]) == self.size else cv2.resize(img, self.size)
        return self.img


def _inset(e: dict, crops_dir: Path | None):
    for c in e.get("crops") or []:
        p = Path(crops_dir) / str(c).split("/")[-1] if crops_dir else None
        if p is not None and p.is_file():
            return cv2.imread(str(p), cv2.IMREAD_COLOR)
    return None


def cut(frames_dir: Path, events_path: Path, out: Path, crops_dir: Path | None = None, fps: float = 5.0,
        pre: float = 3.0, post: float = 5.0, offset: float = 0.0) -> list[Path]:
    frames = load_frames(frames_dir)
    if not frames:
        raise SystemExit(f"no <epoch_ms>.jpg frames in {frames_dir}")
    first = cv2.imread(str(frames[0][1]), cv2.IMREAD_COLOR)
    size = (first.shape[1], first.shape[0])
    t0, t1 = frames[0][0], frames[-1][0]
    events = load_events(events_path, t0 - pre, t1 + post, offset)
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    looks = [(e["_t"], caption_parts(e), _inset(e, crops_dir),
              INSET.get("memory" if e.get("type") == "removed" else e.get("method"), "")) for e in events]

    def frame_at(src: Frames, t: float):
        img = src.at(t)
        live = [lk for lk in looks if lk[0] <= t < lk[0] + post]
        return burn(img, live[-1][1], live[-1][2], live[-1][3]) if live else img

    made = []
    for e, (t, *_rest) in zip(events, looks):
        product = re.sub(r"[^A-Za-z0-9-]+", "-", str(e.get("product_id") or "unknown")).strip("-") or "unknown"
        stamp = datetime.fromtimestamp(t).strftime("%H%M%S")
        name, n = f"{stamp}_{e.get('type')}_{product}.mp4", 1
        while (out / name).exists():
            n += 1
            name = f"{stamp}_{e.get('type')}_{product}_{n}.mp4"
        src, writer = Frames(frames, size), open_writer(out / name, fps, size)
        for k in range(int(round((pre + post) * fps))):
            writer.write(frame_at(src, t - pre + k / fps))
        writer.release()
        made.append(out / name)
        print(f"  {name}: {caption(e)}")
    src, writer = Frames(frames, size), open_writer(out / "full.mp4", fps, size)
    for k in range(int((t1 - t0) * fps) + 1):
        writer.write(frame_at(src, t0 + k / fps))
    writer.release()
    with open(out / "events.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["time", "type", "product_id", "label", "method", "confidence", "cameras", "clip"])
        for e, p in zip(events, made):
            w.writerow([datetime.fromtimestamp(e["_t"]).strftime("%H:%M:%S"), e.get("type"), e.get("product_id"),
                        e.get("label"), e.get("method"), e.get("confidence"), e.get("cameras"), p.name])
    return made


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("frames", type=Path)
    ap.add_argument("events", type=Path)
    ap.add_argument("--crops", type=Path)
    ap.add_argument("--out", type=Path)
    ap.add_argument("--fps", type=float, default=5.0, help="the rate the frames were saved at")
    ap.add_argument("--pre", type=float, default=3.0)
    ap.add_argument("--post", type=float, default=5.0)
    ap.add_argument("--offset", type=float, default=0.0, help="seconds to add to the cart's event times")
    args = ap.parse_args()
    out = args.out or args.frames.parent / f"{args.frames.name}-bts"
    made = cut(args.frames, args.events, out, args.crops, args.fps, args.pre, args.post, args.offset)
    print(f"done: {len(made)} clips + full.mp4 + events.csv in {out}")
    if not made:
        print("no events fell inside the frames' time span: wrong events.jsonl, or the clocks differ (--offset)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
