#!/usr/bin/env python3
"""Record a running cart's cameras from a laptop, over Wi-Fi, no SSH needed.

On the Pi:      ~/venv/bin/python pi/main.py live --debug-view      (or the service with debug_view on)
On the laptop:  python tools/remote_record.py --seconds 30           # → tools/out/rec-remote-…/
                (if smartcart.local doesn't resolve: --host 192.168.137.127, the IP on the hotspot page)
Then:           python pi/main.py replay tools/out/rec-remote-…      # same pipeline, on the recording
"""
from __future__ import annotations

import argparse
import sys
import time
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "pi"))

from kartcv.config import REPO_ROOT  # noqa: E402
from kartcv.remote import discover_cams, fetch_tick  # noqa: E402
from kartcv.sources import save_tick  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--host", default="smartcart.local")
    ap.add_argument("--port", type=int, default=8080)
    ap.add_argument("--seconds", type=float, default=30.0)
    ap.add_argument("--hz", type=float, default=5.0)
    ap.add_argument("--out", type=Path)
    args = ap.parse_args()
    base = f"http://{args.host}:{args.port}"
    try:
        cams = discover_cams(base)
    except (OSError, ValueError) as e:
        print(f"can't reach {base}/status ({e}). Is pi/main.py live --debug-view running, on this network?")
        return 1
    out = args.out or REPO_ROOT / "tools/out" / f"rec-remote-{datetime.now():%Y%m%d-%H%M%S}"
    print(f"recording cams {cams} from {base} for {args.seconds:.0f} s at {args.hz:.0f} Hz -> {out}")
    n, missing = 0, 0
    try:
        end = time.monotonic() + args.seconds
        while time.monotonic() < end:
            t0 = time.monotonic()
            tick = fetch_tick(base, cams)
            missing += sum(f is None for f in tick.values())
            save_tick(out, tick)
            n += 1
            time.sleep(max(0.0, 1.0 / args.hz - (time.monotonic() - t0)))
    except KeyboardInterrupt:
        pass
    print(f"saved {n} ticks ({missing} missing frames) to {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
