#!/usr/bin/env python3
"""Draw each camera's basket-floor ROI on a snapshot (no GUI needed).

  python tools/snap.py                                            # tools/out/cam0.jpg, cam1.jpg
  python tools/roi.py tools/out/cam0.jpg --grid                   # → cam0_grid.jpg: read coordinates off it
  python tools/roi.py tools/out/cam0.jpg --cam 0 --points "0.10,0.40 0.90,0.38 0.97,0.98 0.03,0.98"
                                                                  # → cam0_roi.jpg preview + the JSON
  ... add --write to save it into pi/config.json (other settings kept), then restart the cart
  python tools/roi.py tools/out/cam0.jpg --cam 0 --click --write  # click the corners (needs an OpenCV GUI)

Trace the basket FLOOR just inside the walls: leave out the mesh walls and anything showing the room.
Points are normalized 0..1 (x right, y down); pixel coordinates work too.
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "pi"))

import cv2  # noqa: E402

from kartcv.config import REPO_ROOT  # noqa: E402
from kartcv.roi import grid_overlay, parse_points, preview, write_roi  # noqa: E402


def click_points(img) -> list[list[float]] | None:
    pts: list[tuple[int, int]] = []
    title = "click the floor corners: Enter = done, Backspace = undo, Esc = cancel"
    try:
        cv2.namedWindow(title)
    except cv2.error:
        print("This OpenCV build has no GUI. Use --grid, then --points.")
        return None
    cv2.setMouseCallback(title, lambda ev, x, y, *_: pts.append((x, y)) if ev == cv2.EVENT_LBUTTONDOWN else None)
    h, w = img.shape[:2]
    while True:
        poly = [[x / w, y / h] for x, y in pts]
        cv2.imshow(title, preview(img, poly) if len(poly) >= 3 else img)
        k = cv2.waitKey(30) & 0xFF
        if k in (13, 10) and len(pts) >= 3:
            cv2.destroyAllWindows()
            return [[round(x, 4), round(y, 4)] for x, y in poly]
        if k in (8, 127) and pts:
            pts.pop()
        if k == 27:
            cv2.destroyAllWindows()
            return None


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("image", type=Path)
    ap.add_argument("--cam", type=int, help="camera index the snapshot came from (cam0 = 0)")
    ap.add_argument("--grid", action="store_true", help="write <image>_grid.jpg to read coordinates off")
    ap.add_argument("--points", help='"x,y x,y x,y …" normalized (or pixels)')
    ap.add_argument("--click", action="store_true", help="click the corners in a window")
    ap.add_argument("--write", action="store_true", help="save into pi/config.json")
    ap.add_argument("--config", type=Path, default=REPO_ROOT / "pi/config.json")
    args = ap.parse_args()
    img = cv2.imread(str(args.image))
    if img is None:
        print(f"can't read {args.image}")
        return 1
    if args.grid:
        out = args.image.with_name(args.image.stem + "_grid.jpg")
        cv2.imwrite(str(out), grid_overlay(img))
        print(f"wrote {out}")
        if not (args.points or args.click):
            return 0
    if args.points:
        poly = parse_points(args.points, (img.shape[1], img.shape[0]))
    elif args.click:
        poly = click_points(img)
        if poly is None:
            return 1
    else:
        print("give --points or --click (or --grid alone)")
        return 1
    if len(poly) < 3:
        print("a floor polygon needs at least 3 points")
        return 1
    out = args.image.with_name(args.image.stem + "_roi.jpg")
    cv2.imwrite(str(out), preview(img, poly))
    print(f"wrote {out} (check it: only the basket floor should be bright)")
    print(json.dumps({"roi": {str(args.cam if args.cam is not None else 0): poly}}))
    if args.write:
        if args.cam is None:
            print("--write needs --cam")
            return 1
        if not args.config.exists() and (REPO_ROOT / "pi/config.example.json").exists():
            shutil.copy(REPO_ROOT / "pi/config.example.json", args.config)
        write_roi(args.config, args.cam, poly)
        print(f"saved roi[{args.cam}] into {args.config}; restart the cart to use it")
    return 0


if __name__ == "__main__":
    sys.exit(main())
