"""Per-camera region of interest: the basket floor as each camera sees it (CONTRACT: pi/config.json "roi").

A polygon of normalized [x, y] points (0..1, x right, y down), so one polygon fits full-size live
frames and half-size clips alike. Everything outside it (the mesh walls, the room, people walking by)
is ignored by motion, change detection and the camera-shift estimate, and painted gray in crops.
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
