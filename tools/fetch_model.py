#!/usr/bin/env python3
"""Download the on-device feature model (MobileNetV2, ~14 MB) to pi/models/features.onnx.

Run once per machine (Mac and Pi). Without it the cart still works, on color histograms.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "pi"))

from kartcv.config import REPO_ROOT, load_config  # noqa: E402
from kartcv.identify.features import fetch_model  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--config", type=Path, default=REPO_ROOT / "pi/config.json")
    args = ap.parse_args()
    dest = load_config(args.config).path("model_path")
    fetch_model(dest)
    print(f"saved {dest.relative_to(REPO_ROOT) if dest.is_relative_to(REPO_ROOT) else dest} (1280-d)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
