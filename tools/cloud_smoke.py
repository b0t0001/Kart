#!/usr/bin/env python3
"""Real-Claude smoke test of the closed-set identifier: accuracy and latency.

  python tools/cloud_smoke.py               # synthetic name-printed cards (upper-bound accuracy)
  python tools/cloud_smoke.py --gallery     # the real enrolled prop photos in pi/gallery (true accuracy)

Needs ANTHROPIC_API_KEY in the shared .env. Uses the live catalog when Supabase is configured.
"""
from __future__ import annotations

import argparse
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "pi"))

import cv2  # noqa: E402

from kartcv.catalog import fetch_catalog, load_catalog  # noqa: E402
from kartcv.config import REPO_ROOT, load_config, load_env  # noqa: E402
from kartcv.identify.cloud import CloudIdentifier  # noqa: E402
from kartcv.identify.smoke import product_card, run_smoke  # noqa: E402
from kartcv.synth import Item, Scene, crop_item  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--config", type=Path, default=REPO_ROOT / "pi/config.json")
    ap.add_argument("--gallery", action="store_true", help="use the real enrolled photos")
    ap.add_argument("--products", type=int, default=10, help="synthetic mode: how many catalog products")
    args = ap.parse_args()
    cfg, env = load_config(args.config), load_env()
    if not env.get("ANTHROPIC_API_KEY"):
        print("ANTHROPIC_API_KEY is not set in the shared .env")
        return 1
    catalog = None
    if env.get("SUPABASE_URL") and env.get("SUPABASE_ANON_KEY"):
        catalog = fetch_catalog(env["SUPABASE_URL"], env["SUPABASE_ANON_KEY"])
    catalog = catalog or load_catalog(cfg.path("catalog_path"))

    samples = []
    if args.gallery:
        root = cfg.path("gallery_dir")
        for d in sorted(p for p in root.iterdir() if p.is_dir() and not p.name.startswith(".")):
            imgs = sorted(d.glob("*.jpg"))[:2]
            if imgs:
                samples.append((d.name, [cv2.imread(str(i)) for i in imgs]))
    else:
        ids = random.Random(0).sample(catalog.ids(), min(args.products, len(catalog.ids())))
        for k, pid in enumerate(ids):
            p = catalog.get(pid)
            samples.append((pid, [product_card(p, seed=2 * k), product_card(p, seed=2 * k + 1)]))
        empty = Scene().render(0)[200:420, 400:700]
        hand = crop_item(0, Item("hand?", 300, 200, w=140, h=90, seed=7))
        samples += [(None, [empty]), (None, [hand])]

    cloud = CloudIdentifier(catalog, cfg.cloud_model, cfg.cloud_timeout_s)
    r = run_smoke(cloud, samples)
    for row in r["rows"]:
        mark = "ok " if row["ok"] else "BAD"
        print(f"{mark} expected {row['expected'] or 'unknown':28s} got {row['got'] or 'unknown':28s} "
              f"conf {row['confidence']:.2f}  {row['seconds']:.2f}s  ({row['label']})")
    lat = r["latency_s"]
    print(f"\n{cfg.cloud_model}: accuracy {100 * r['accuracy']:.0f}% on {r['n']} samples; latency median "
          f"{lat['median']:.2f}s, p90 {lat['p90']:.2f}s, max {lat['max']:.2f}s (budget {cfg.cloud_timeout_s:.0f}s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
