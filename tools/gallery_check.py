#!/usr/bin/env python3
"""Which matcher should the cart use? Scores the enrolled photos against each other with both
feature extractors (color histogram and the ONNX CNN) and recommends a `features` setting.

  python tools/gallery_check.py        # after enrolling the props with tools/enroll.py
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "pi"))

from kartcv.config import REPO_ROOT, load_config  # noqa: E402
from kartcv.identify.features import HistogramFeatures, OnnxFeatures  # noqa: E402
from kartcv.identify.gallery import Gallery  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--config", type=Path, default=REPO_ROOT / "pi/config.json")
    args = ap.parse_args()
    cfg = load_config(args.config)
    extractors = {"hist": HistogramFeatures()}
    if cfg.path("model_path").exists():
        extractors["auto"] = OnnxFeatures(cfg.path("model_path"))
    else:
        print("(no ONNX model: run tools/fetch_model.py to compare it too)")
    results = {}
    for name, feats in extractors.items():
        g = Gallery(cfg.path("gallery_dir"), feats)
        g.load()
        results[name] = g.leave_one_out()
        r = results[name]
        print(f"{name:5s} ({feats.name}): {r['images']} photos of {r['products']} products, "
              f"top-1 {100 * r['top1']:.0f}%, median lead {r['median_margin']:+.3f} (matcher needs ≥ {cfg.local_min_margin})")
    if not results["hist"]["images"]:
        print("gallery is empty: enroll props first (tools/enroll.py <product-id>)")
        return 1
    best = max(results, key=lambda k: (results[k]["top1"], results[k]["median_margin"]))
    print(f'recommendation: "features": "{best}" in pi/config.json (currently "{cfg.features}")')
    return 0


if __name__ == "__main__":
    sys.exit(main())
