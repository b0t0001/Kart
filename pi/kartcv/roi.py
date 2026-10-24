"""Per-camera region of interest: the basket floor as each camera sees it (CONTRACT: pi/config.json "roi").

A polygon of normalized [x, y] points (0..1, x right, y down), so one polygon fits full-size live
frames and half-size clips alike. Everything outside it (the mesh walls, the room, people walking by)
is ignored by motion, change detection and the camera-shift estimate, and painted gray in floor crops
(Claude's crop of a tall item also shows its body above the floor: changes.Blob.ident).
"""
from __future__ import annotations

from functools import lru_cache

import cv2
import numpy as np

GRAY = 128


def _key(poly) -> tuple | None:
    if not poly or len(poly) < 3:
        return None
    return tuple((float(x), float(y)) for x, y in poly)


@lru_cache(maxsize=32)
def _mask(key: tuple, w: int, h: int) -> np.ndarray:
    pts = np.array([[round(x * (w - 1)), round(y * (h - 1))] for x, y in key], np.int32)
    m = np.zeros((h, w), np.uint8)
    cv2.fillPoly(m, [pts], 1)
    m.setflags(write=False)
    return m


def polygon_mask(poly, size_wh: tuple[int, int]) -> np.ndarray | None:
    """0/1 uint8 mask of the polygon at this frame size (read-only, cached), or None for "whole frame"."""
    key = _key(poly)
    return None if key is None else _mask(key, int(size_wh[0]), int(size_wh[1]))


def gray_outside(crop: np.ndarray, mask_crop: np.ndarray | None) -> np.ndarray:
    if mask_crop is None:
        return crop
    out = crop.copy()
    out[mask_crop == 0] = GRAY
    return out


def draw_outline(img: np.ndarray, poly, color=(0, 255, 255)) -> np.ndarray:
    key = _key(poly)
    if key is None:
        return img
    h, w = img.shape[:2]
    pts = np.array([[round(x * (w - 1)), round(y * (h - 1))] for x, y in key], np.int32)
    out = img.copy()
    cv2.polylines(out, [pts], True, color, 2)
    return out


# --- helpers for drawing a polygon from a camera snapshot (tools/roi.py) ---

def parse_points(text: str, size_wh: tuple[int, int] | None = None) -> list[list[float]]:
    """'x,y x,y …' → [[x, y], …], normalized. Pixel coordinates (any value > 1) need size_wh."""
    pts = [[float(v) for v in p.split(",")] for p in text.replace(";", " ").split()]
    if any(v > 1.0 for p in pts for v in p):
        if size_wh is None:
            raise ValueError("pixel coordinates need the image size")
        w, h = size_wh
        pts = [[x / w, y / h] for x, y in pts]
    return [[round(x, 4), round(y, 4)] for x, y in pts]


def grid_overlay(img: np.ndarray, step: float = 0.05) -> np.ndarray:
    """Labeled grid (every `step`, labels every 0.1) to read normalized coordinates off a snapshot."""
    out = img.copy()
    h, w = out.shape[:2]
    n = int(round(1 / step))
    for i in range(1, n):
        v = i * step
        major = abs(v * 10 - round(v * 10)) < 1e-6
        color, thick = ((0, 255, 255), 2) if major else ((0, 160, 160), 1)
        x, y = int(v * w), int(v * h)
        cv2.line(out, (x, 0), (x, h - 1), color, thick)
        cv2.line(out, (0, y), (w - 1, y), color, thick)
        if major:
            cv2.putText(out, f"{v:.1f}", (x + 3, 16), cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 1, cv2.LINE_AA)
            cv2.putText(out, f"{v:.1f}", (3, y - 4), cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 1, cv2.LINE_AA)
    return out


def preview(img: np.ndarray, poly) -> np.ndarray:
    """The polygon outlined, with everything outside it dimmed: what the cart will actually look at."""
    m = polygon_mask(poly, (img.shape[1], img.shape[0]))
    out = img.copy()
    if m is not None:
        out[m == 0] = (out[m == 0] * 0.35).astype(np.uint8)
    return draw_outline(out, poly)


def write_roi(config_path, cam: int, poly) -> None:
    """Set roi[cam] in pi/config.json, keeping every other setting."""
    import json
    from pathlib import Path

    path = Path(config_path)
    data = json.loads(path.read_text()) if path.exists() else {}
    data.setdefault("roi", {})[str(cam)] = [[float(x), float(y)] for x, y in poly]
    path.write_text(json.dumps(data, indent=2) + "\n")
