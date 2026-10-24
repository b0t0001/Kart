"""Camera check: stream both Brios at once (MJPEG 1280x720), report fps, save a still from each.

On the Pi:  ~/venv/bin/python ~/kart/hardware/check_cameras.py [--seconds 5]
Stills go to hardware/out/cam0.jpg, cam1.jpg. Exits 1 if any camera fails.

cam0/cam1 are ordered by USB port (by-path), so they stay the same across reboots
as long as each camera stays in the same port.
"""
import argparse
import glob
import os
import sys
import threading
import time

import cv2

OUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "out")


def find_cameras():
    """One stable by-path node per USB camera (udev adds both usb- and usbv2- links; keep one)."""
    seen, cams = set(), []
    for path in sorted(glob.glob("/dev/v4l/by-path/*usb*-video-index0")):
        real = os.path.realpath(path)
        if real not in seen:
            seen.add(real)
            cams.append(path)
    return cams


def fourcc_str(cap):
    code = int(cap.get(cv2.CAP_PROP_FOURCC))
    return "".join(chr((code >> 8 * i) & 0xFF) for i in range(4))


def stream(idx, path, args, results):
    cap = cv2.VideoCapture(path, cv2.CAP_V4L2)
    cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, args.width)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, args.height)
    cap.set(cv2.CAP_PROP_FPS, 30)
    # No CAP_PROP_BUFFERSIZE=1: on the Pi's V4L2 driver it halves the frame rate (measured 7.5 vs 15 fps).
    res ={"path": path, "dev": os.path.realpath(path), "ok": False, "frames": 0, "fails": 0}
    results[idx] = res
    if not cap.isOpened():
        res["error"] = "could not open"
        return
    res["fourcc"] = fourcc_str(cap)
    frame, start = None, time.monotonic()
    while time.monotonic() - start < args.seconds:
        ok, img = cap.read()
        if ok:
            frame = img
            res["frames"] += 1
        else:
            res["fails"] += 1
            time.sleep(0.05)
    res["fps"] = res["frames"] / args.seconds
    cap.release()
    if frame is None:
        res["error"] = "opened but returned no frames"
        return
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    res.update(
        ok=True,
        shape=f"{frame.shape[1]}x{frame.shape[0]}",
        brightness=float(gray.mean()),
        sharpness=float(cv2.Laplacian(gray, cv2.CV_64F).var()),
        still=os.path.join(OUT_DIR, f"cam{idx}.jpg"),
    )
    cv2.imwrite(res["still"], frame)


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--seconds", type=float, default=5.0, help="how long to stream both cams")
    ap.add_argument("--width", type=int, default=1280)
    ap.add_argument("--height", type=int, default=720)
    args = ap.parse_args()

    cams = find_cameras()
    print(f"found {len(cams)} USB camera(s)")
    if not cams:
        sys.exit(1)
    os.makedirs(OUT_DIR, exist_ok=True)

    results = [None] * len(cams)
    threads = [threading.Thread(target=stream, args=(i, p, args, results)) for i, p in enumerate(cams)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    for i, r in enumerate(results):
        port = r["path"].split("usb-0:")[-1].split(":")[0]
        if r["ok"]:
            print(
                f"cam{i} OK   {r['dev']} (port {port}) {r['shape']} {r['fourcc']} {r['fps']:.1f} fps "
                f"read-fails={r['fails']} brightness={r['brightness']:.0f} sharpness={r['sharpness']:.0f} -> {r['still']}"
            )
        else:
            print(f"cam{i} FAIL {r['dev']} (port {port}): {r.get('error')}")
        print(f"     by-path: {r['path']}")
    sys.exit(0 if all(r["ok"] for r in results) else 1)


if __name__ == "__main__":
    main()
