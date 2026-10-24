#!/usr/bin/env python3
"""Milestone 1: save one picture from each camera (tools/out/cam0.jpg, cam1.jpg).

  python tools/snap.py                 # cameras from pi/config.json
  python tools/snap.py --cam 0         # override (index or /dev/v4l/by-path/... path)
  python tools/snap.py --list          # show stable camera paths (Linux)
"""
from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "pi"))

from kartcv.config import REPO_ROOT, load_config  # noqa: E402
from kartcv.sources import camera_paths, snap_all  # noqa: E402


def list_cameras() -> None:
    paths = camera_paths()
    if paths:
        print("Stable camera paths, one per USB camera (put these in pi/config.json \"cameras\"):")
        for p in paths:
            print("  " + p)
    else:
        print("No /dev/v4l/by-path cameras found (not Linux, or no cameras plugged in).")
    if shutil.which("v4l2-ctl"):
        print(subprocess.run(["v4l2-ctl", "--list-devices"], capture_output=True, text=True).stdout)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--config", type=Path, default=REPO_ROOT / "pi/config.json")
    ap.add_argument("--cam", action="append", help="camera index or device path (repeatable)")
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--out", type=Path, default=REPO_ROOT / "tools/out")
    args = ap.parse_args()
    if args.list:
        list_cameras()
        return 0
    overrides = {}
    if args.cam:
        overrides["cameras"] = [int(c) if c.isdigit() else c for c in args.cam]
    cfg = load_config(args.config, overrides)
    results = snap_all(cfg, args.out)
    failed = False
    for cam, path in results.items():
        if path is None:
            failed = True
            print(f"cam{cam}: FAIL ({cfg.cameras[cam]})")
        else:
            import cv2
            shape = cv2.imread(str(path)).shape
            print(f"cam{cam}: OK {shape} -> {path.relative_to(REPO_ROOT) if path.is_relative_to(REPO_ROOT) else path}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
