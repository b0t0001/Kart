"""Cheap motion detection and the "settled" trigger (spec §5.1)."""
from __future__ import annotations

import cv2
import numpy as np

from kartcv.changes import work_size
from kartcv.roi import polygon_mask

_EPS = 1e-6  # tick timestamps are floats; 2.3 - 1.3 must count as a full second


class MotionDetector:
    """Frame-to-frame difference on a tiny blurred image.

    Uses the largest per-channel difference rather than grayscale: skin over a tan mat can have
    the same brightness, and a grayscale diff would not see the hand at all.
    """

    def __init__(self, size: tuple[int, int] = (320, 180), thresh: int = 25, frac: float = 0.005, roi=None):
        self.size, self.thresh, self.frac = tuple(size), thresh, frac
        self._roi = roi  # only the basket floor counts: rolling past the room isn't motion
        self._prev: np.ndarray | None = None

    def update(self, image: np.ndarray) -> bool:
        size = work_size(image.shape, self.size)  # portrait mounts keep their shape
        small = cv2.GaussianBlur(cv2.resize(image, size, interpolation=cv2.INTER_AREA), (5, 5), 0)
        prev, self._prev = self._prev, small
        if prev is None or prev.shape != small.shape:
            return False
        moved = cv2.absdiff(small, prev).max(axis=2) > self.thresh
        mask = polygon_mask(self._roi, size)
        if mask is not None:
            moved &= mask.astype(bool)
        area = int(mask.sum()) if mask is not None else size[0] * size[1]
        return int(moved.sum()) / max(1, area) > self.frac

    def reset(self) -> None:
        self._prev = None


class SettleTracker:
    """Fires once when motion has happened and no camera has moved for `settle_s`."""

    def __init__(self, settle_s: float = 1.0):
        self.settle_s = settle_s
        self.state = "idle"
        self._last_motion = 0.0

    def update(self, ts: float, moving: dict[int, bool]) -> bool:
        if any(moving.values()):
            self.state = "motion"
            self._last_motion = ts
            return False
        if self.state == "motion" and ts - self._last_motion >= self.settle_s - _EPS:
            self.state = "idle"
            return True
        return False

    def reset(self) -> None:
        self.state = "idle"
        self._last_motion = 0.0
