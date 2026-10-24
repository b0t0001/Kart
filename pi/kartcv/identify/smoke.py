"""Smoke test for the Claude closed-set identifier: accuracy and latency on known crops.

Without real prop photos it renders package-like cards with each product's name printed on them.
That is easier than real packaging, so treat its accuracy as an upper bound; the latency is real.
With an enrolled gallery it uses the real prop photos instead (see tools/cloud_smoke.py).
"""
from __future__ import annotations

import hashlib
import statistics
import time

import cv2
import numpy as np


def _color(text: str) -> tuple[int, int, int]:
    h = hashlib.md5(text.encode()).digest()
    return (60 + h[0] % 160, 60 + h[1] % 160, 60 + h[2] % 160)


def product_card(product, seed: int = 0) -> np.ndarray:
    """A package-like crop: brand-colored card, the product's name in big letters, a camera-ish warp."""
    rng = np.random.default_rng(seed)
    w, h = 300, 220
    card = np.full((h, w, 3), _color(product.id), np.uint8)
    cv2.rectangle(card, (0, h - 50), (w, h), (245, 245, 245), -1)
    words = product.name.replace(",", "").split()
    lines, line = [], ""
    for word in words:
        if len(line) + len(word) > 14 and line:
            lines.append(line)
            line = word
        else:
            line = f"{line} {word}".strip()
    lines.append(line)
    y = 40
    for ln in lines[:4]:
        cv2.putText(card, ln, (12, y), cv2.FONT_HERSHEY_DUPLEX, 0.9, (255, 255, 255), 2, cv2.LINE_AA)
        y += 38
    cv2.putText(card, (product.short_name or product.name)[:16], (12, h - 15), cv2.FONT_HERSHEY_SIMPLEX, 0.9,
                (30, 30, 30), 2, cv2.LINE_AA)
    # seen from a corner camera: perspective, a tan mat around it, sensor noise
    j = rng.uniform(-25, 25, (4, 2)).astype(np.float32)
    src = np.float32([[0, 0], [w, 0], [w, h], [0, h]])
    dst = np.float32([[40, 40], [w + 40, 40], [w + 40, h + 40], [40, h + 40]]) + j
    m = cv2.getPerspectiveTransform(src, dst)
    out = cv2.warpPerspective(card, m, (w + 80, h + 80), borderValue=(150, 170, 190))
    noise = rng.normal(0, 3, out.shape)
    return np.clip(out.astype(np.float32) + noise, 0, 255).astype(np.uint8)


def run_smoke(identifier, samples: list[tuple[str | None, list]]) -> dict:
    """samples: (expected product_id or None for "should be unknown", crops). Returns accuracy and latency."""
    rows, times = [], []
    for expected, crops in samples:
        t0 = time.perf_counter()
        a = identifier.identify(crops)
        dt = time.perf_counter() - t0
        times.append(dt)
        rows.append({"expected": expected, "got": a.product_id, "confidence": a.confidence, "label": a.label,
                     "seconds": dt, "ok": a.product_id == expected})
    srt = sorted(times)
    return {"n": len(rows), "accuracy": sum(r["ok"] for r in rows) / len(rows) if rows else 0.0, "rows": rows,
            "latency_s": {"median": statistics.median(times) if times else 0.0,
                          "p90": srt[int(0.9 * (len(srt) - 1))] if srt else 0.0, "max": srt[-1] if srt else 0.0}}
