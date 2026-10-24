"""Trim a recorded clip (tools/record.py layout: <dir>/cam<k>/<epoch_ms>.jpg) to fit the clip size cap.

Keeps every tick near motion, plus a still lead-in and tail, and drops long stretches where
nothing moves. Kept frames keep their original timestamps, so a dropped stretch shows up as a
time gap; it is always a still one, so the replay sees no motion across it.

  python hardware/trim_clip.py RAW_DIR OUT_DIR [--pre 2.5] [--post 6] [--max-mb 3]
"""
import argparse
import json
import shutil
import sys
from pathlib import Path

import cv2
import numpy as np


def load_ticks(raw: Path):
    cams = sorted(p for p in raw.iterdir() if p.is_dir() and p.name.startswith("cam"))
    names = sorted(set.intersection(*(set(f.name for f in c.glob("*.jpg")) for c in cams)))
    return cams, names


def roi_masks(cams, config: Path, size=(160, 90)):
    """Basket-floor mask per camera from pi/config.json "roi" (whole frame where none is set)."""
    roi = json.loads(config.read_text()).get("roi", {}) if config.exists() else {}
    masks = {}
    for c in cams:
        m = np.ones(size[::-1], bool)
        poly = roi.get(c.name.removeprefix("cam"))
        if poly:
            m = np.zeros(size[::-1], np.uint8)
            cv2.fillPoly(m, [np.round(np.array(poly) * size).astype(np.int32)], 1)
            m = m.astype(bool)
        masks[c] = m
    return masks


def motion_per_tick(cams, names, masks, thresh=30, frac=0.01):
    """True where any camera's small grayscale floor area changed noticeably since the previous tick."""
    moving, prev = [False] * len(names), {}
    for i, n in enumerate(names):
        for c in cams:
            g = cv2.GaussianBlur(cv2.resize(cv2.imread(str(c / n), cv2.IMREAD_GRAYSCALE), (160, 90)), (5, 5), 0)
            if c in prev and (cv2.absdiff(g, prev[c]) > thresh)[masks[c]].mean() > frac:
                moving[i] = True
            prev[c] = g
    return moving


def select(names, moving, pre_s, post_s):
    ts = np.array([int(Path(n).stem) / 1000.0 for n in names])
    keep = ts - ts[0] <= pre_s                      # still lead-in = the empty-basket picture
    for i in np.flatnonzero(moving):
        keep |= (ts >= ts[i] - pre_s) & (ts <= ts[i] + post_s)
    return keep


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("raw", type=Path)
    ap.add_argument("out", type=Path)
    ap.add_argument("--pre", type=float, default=2.5, help="seconds kept before motion (and at the start)")
    ap.add_argument("--post", type=float, default=6.0, help="seconds kept after motion")
    ap.add_argument("--max-mb", type=float, default=3.0)
    ap.add_argument("--quality", type=int, help="re-encode kept frames at this JPEG quality (default: copy as is)")
    ap.add_argument("--config", type=Path, default=Path(__file__).resolve().parents[1] / "pi/config.json",
                    help="where the per-camera floor ROI comes from")
    args = ap.parse_args()

    cams, names = load_ticks(args.raw)
    moving = motion_per_tick(cams, names, roi_masks(cams, args.config))
    ratio = 0.6 if args.quality and args.quality <= 70 else 1.0   # rough size estimate before re-encoding
    post = args.post
    while True:
        keep = select(names, moving, args.pre, post)
        size = ratio * sum((c / n).stat().st_size for c in cams for n, k in zip(names, keep) if k) / 1e6
        if size <= args.max_mb or post <= 3.0:
            break
        post -= 0.5
    if args.out.exists():
        shutil.rmtree(args.out)
    for c in cams:
        (args.out / c.name).mkdir(parents=True)
        for n, k in zip(names, keep):
            if not k:
                continue
            if args.quality:
                cv2.imwrite(str(args.out / c.name / n), cv2.imread(str(c / n)), [cv2.IMWRITE_JPEG_QUALITY, args.quality])
            else:
                shutil.copy2(c / n, args.out / c.name / n)
    size = sum(f.stat().st_size for f in args.out.rglob("*.jpg")) / 1e6
    kept = int(keep.sum())
    print(f"{args.out.name}: kept {kept}/{len(names)} ticks, {size:.1f} MB, tail {post:.1f} s"
          + ("" if size <= args.max_mb else "  (OVER the size cap)"))
    return 0 if size <= args.max_mb else 1


if __name__ == "__main__":
    sys.exit(main())
