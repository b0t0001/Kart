#!/usr/bin/env python3
"""Teach the cart what a product looks like (≈1 minute per product).

  sudo systemctl stop kart-cv              # on the Pi: free the cameras first
  python tools/enroll.py kirkland-parmesan # then follow the prompts, ~5 rounds
  sudo systemctl start kart-cv

Start with the cart EMPTY. Each round: put the item in BY HAND, out on the floor (not against a wall),
wait for "captured", take it out. Vary the pose (side, upright, turned) between rounds, but keep
the print in view: a plain back or a bare lid looks like every other product's.
A change no hand made (the liner settling) or that looks like the liner is ignored and says so.
Each capture prints its photo paths: open them, and delete any that don't show the product.
"""
from __future__ import annotations

import argparse
import logging
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "pi"))

from kartcv.catalog import fetch_catalog, load_catalog  # noqa: E402
from kartcv.config import REPO_ROOT, load_config, load_env  # noqa: E402
from kartcv.enroll import run_enrollment  # noqa: E402
from kartcv.identify.features import load_features  # noqa: E402
from kartcv.identify.gallery import Gallery  # noqa: E402
from kartcv.sources import open_cameras  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("product_id")
    ap.add_argument("--rounds", type=int, default=5)
    ap.add_argument("--config", type=Path, default=REPO_ROOT / "pi/config.json")
    args = ap.parse_args()
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s")

    cfg, env = load_config(args.config), load_env()
    catalog = None
    if env.get("SUPABASE_URL") and env.get("SUPABASE_ANON_KEY"):
        catalog = fetch_catalog(env["SUPABASE_URL"], env["SUPABASE_ANON_KEY"])
    catalog = catalog or load_catalog(cfg.path("catalog_path"))
    if catalog.get(args.product_id) is None:
        print(f"{args.product_id!r} isn't in the catalog. Known ids:\n  " + "\n  ".join(catalog.ids()))
        return 1

    gallery = Gallery(cfg.path("gallery_dir"), load_features(cfg.path("model_path"), cfg.features))
    gallery.load()
    cams = open_cameras(cfg)

    def ticks():
        while True:
            t0 = time.monotonic()
            yield {c.cam: c.read() for c in cams}
            time.sleep(max(0.0, 0.1 - (time.monotonic() - t0)))

    print(f"Enrolling {catalog.name(args.product_id)} ({args.rounds} rounds). Cart must be EMPTY right now.")
    print(f"waiting {cfg.camera_warmup_s:.0f} s for the cameras... then put {args.product_id} in the cart")
    try:
        n = run_enrollment(ticks(), args.product_id, args.rounds, gallery, catalog, cfg,
                           REPO_ROOT / "pi/state/enroll")
    except KeyboardInterrupt:
        n = None
    finally:
        for c in cams:
            c.close()
    print(f"done: {gallery.root / args.product_id} now has "
          f"{len(list((gallery.root / args.product_id).glob('*.jpg')))} photos" + ("" if n else " (stopped early)"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
