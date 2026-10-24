"""Aim check: has any camera moved since its reference picture? Run before every demo.

On the Pi:  ~/venv/bin/python ~/kart/hardware/aim_check.py           # compare against hardware/aim/
            ~/venv/bin/python ~/kart/hardware/aim_check.py --save    # store new references (empty cart, final aim)

Frames come from the running pipeline (http://localhost:8080/cam/<k>.jpg) when it is up,
otherwise straight from the cameras in pi/config.json. For each camera it prints the shift
(pixels at 1280x720) and rotation versus the reference, and writes a 50/50 overlay to
hardware/out/aim_cam<k>.jpg for eyeballing. Exits 1 if any camera needs attention.
If a camera MOVED: re-aim it to match the overlay, or redraw its ROI (tools/roi.py) and reset the cart.
"""
import argparse
import json
import math
import sys
import time
import urllib.request
from pathlib import Path

import cv2
import numpy as np

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
REF_DIR = HERE / "aim"
OUT_DIR = HERE / "out"
OK_PX, CHECK_PX, OK_DEG = 4.0, 15.0, 1.0   # the pipeline tolerates a few pixels of wobble (max_shift_px)


def cameras(config: Path):
    return json.loads(config.read_text())["cameras"]


def frame_from_live(k: int, port: int):
    try:
        with urllib.request.urlopen(f"http://localhost:{port}/cam/{k}.jpg", timeout=3) as r:
            img = cv2.imdecode(np.frombuffer(r.read(), np.uint8), cv2.IMREAD_COLOR)
        return img
    except OSError:
        return None


def frame_from_camera(src: str, warmup_s: float = 3.0):
    cap = cv2.VideoCapture(src, cv2.CAP_V4L2)
    cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1280)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)
    img, end = None, time.monotonic() + warmup_s   # let auto exposure settle
    while time.monotonic() < end or img is None:
        ok, f = cap.read()
        if ok:
            img = f
        elif time.monotonic() > end + 2:
            break
    cap.release()
    return img


def estimate_motion(ref, cur):
    """Euclidean (shift + rotation) from ref to cur, in 1280x720 pixels and degrees."""
    small = (320, 180)
    a = cv2.GaussianBlur(cv2.cvtColor(cv2.resize(ref, small), cv2.COLOR_BGR2GRAY), (5, 5), 0).astype(np.float32)
    b = cv2.GaussianBlur(cv2.cvtColor(cv2.resize(cur, small), cv2.COLOR_BGR2GRAY), (5, 5), 0).astype(np.float32)
    scale = ref.shape[1] / small[0]
    warp = np.eye(2, 3, dtype=np.float32)
    try:
        cc, warp = cv2.findTransformECC(a, b, warp, cv2.MOTION_EUCLIDEAN,
                                        (cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_COUNT, 200, 1e-5), None, 5)
        return warp[0, 2] * scale, warp[1, 2] * scale, math.degrees(math.atan2(warp[1, 0], warp[0, 0])), cc
    except cv2.error:   # ECC did not converge: fall back to translation only
        (dx, dy), resp = cv2.phaseCorrelate(a, b)
        return dx * scale, dy * scale, 0.0, resp


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--save", action="store_true", help="store the current views as the references")
    ap.add_argument("--config", type=Path, default=REPO / "pi/config.json")
    ap.add_argument("--port", type=int, default=8080, help="pipeline control server port")
    args = ap.parse_args()

    OUT_DIR.mkdir(exist_ok=True)
    REF_DIR.mkdir(exist_ok=True)
    worst = 0
    for k, src in enumerate(cameras(args.config)):
        cur = frame_from_live(k, args.port)
        how = "live pipeline"
        if cur is None:
            cur, how = frame_from_camera(src), "camera"
        if cur is None:
            print(f"cam{k}: FAIL, no frame ({src})")
            worst = max(worst, 2)
            continue
        ref_path = REF_DIR / f"cam{k}.jpg"
        if args.save:
            cv2.imwrite(str(ref_path), cur)
            print(f"cam{k}: reference saved -> {ref_path.relative_to(REPO)} (from {how})")
            continue
        if not ref_path.exists():
            print(f"cam{k}: no reference yet; run with --save on the empty cart")
            worst = max(worst, 2)
            continue
        ref = cv2.imread(str(ref_path))
        cur = cv2.resize(cur, (ref.shape[1], ref.shape[0]))
        dx, dy, deg, score = estimate_motion(ref, cur)
        shift = math.hypot(dx, dy)
        verdict = "OK" if shift <= OK_PX and abs(deg) <= OK_DEG else "CHECK" if shift <= CHECK_PX else "MOVED"
        worst = max(worst, {"OK": 0, "CHECK": 1, "MOVED": 2}[verdict])
        cv2.imwrite(str(OUT_DIR / f"aim_cam{k}.jpg"), cv2.addWeighted(ref, 0.5, cur, 0.5, 0))
        print(f"cam{k}: {verdict:5s} shift ({dx:+.1f}, {dy:+.1f}) px, rotation {deg:+.2f} deg, match {score:.2f} "
              f"-> overlay hardware/out/aim_cam{k}.jpg")
    if not args.save and worst == 2:
        print("A camera moved: re-aim it until the overlay lines up, or redraw its ROI (tools/roi.py) and reset the cart.")
    return 1 if worst else 0


if __name__ == "__main__":
    sys.exit(main())
