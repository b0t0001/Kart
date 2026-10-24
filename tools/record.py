#!/usr/bin/env python3
"""Record both cameras to a replay folder (tools/out/rec-YYYYmmdd-HHMMSS/cam{k}/<ts_ms>.jpg).

  python tools/record.py --seconds 30
  python pi/main.py replay tools/out/rec-...      # run the pipeline on it

  # a clip to share through git (≈ 4 MB per 15 s): half size, 5 Hz
  python tools/record.py --seconds 15 --hz 5 --scale 0.5 --quality 85 --out hardware/clips/<name>
"""
from __future__ import annotations

import argparse
import sys
import time
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "pi"))

from kartcv.config import REPO_ROOT, load_config  # noqa: E402
from kartcv.sources import Frame, open_cameras, save_tick  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--config", type=Path, default=REPO_ROOT / "pi/config.json")
    ap.add_argument("--seconds", type=float, default=30.0)
    ap.add_argument("--hz", type=float, default=10.0)
    ap.add_argument("--out", type=Path)
    ap.add_argument("--scale", type=float, default=1.0, help="0.5 = half-size frames, for sharing")
    ap.add_argument("--quality", type=int, default=95, help="JPEG quality")
    args = ap.parse_args()
    cfg = load_config(args.config)
    out = args.out or REPO_ROOT / "tools/out" / f"rec-{datetime.now():%Y%m%d-%H%M%S}"
    cams = open_cameras(cfg)
    print(f"waiting {cfg.camera_warmup_s:.0f} s for exposure to settle...")
    time.sleep(cfg.camera_warmup_s + 0.5)
    print(f"recording {args.seconds:.0f} s at {args.hz:.0f} Hz -> {out}")
    n = 0
    try:
        end = time.monotonic() + args.seconds
        while time.monotonic() < end:
            t0 = time.monotonic()
            ts = time.time()
            tick = {}
            for c in cams:
                f = c.read()
                tick[c.cam] = Frame(f.image, ts, c.cam) if f is not None else None  # same ts per tick
            save_tick(out, tick, scale=args.scale, quality=args.quality)
            n += 1
            time.sleep(max(0.0, 1.0 / args.hz - (time.monotonic() - t0)))
    except KeyboardInterrupt:
        pass
    finally:
        for c in cams:
            c.close()
    print(f"saved {n} ticks to {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
