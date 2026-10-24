"""Pull a running cart's live camera frames over its debug page, with no SSH (debug view must be on).

Lets a laptop watch and record what the Pi's cameras see, in the same replay format as
tools/record.py, so clips can be replayed and tuned anywhere.
"""
from __future__ import annotations

import json
import time

import cv2
import numpy as np

from kartcv import http
from kartcv.sources import Frame


def discover_cams(base: str, get=None) -> list[int]:
    get = get or http.get
    status, body = get(f"{base.rstrip('/')}/status", {})
    if status != 200:
        raise OSError(f"/status returned HTTP {status}")
    return sorted(int(c) for c in json.loads(body).get("cameras", {}))


def fetch_tick(base: str, cams: list[int], ts: float | None = None, get=None, quality: int = 95) -> dict:
    """One frame per camera, all stamped with the same time (None where a camera has no frame)."""
    get = get or http.get
    ts = time.time() if ts is None else ts
    tick = {}
    for c in cams:
        tick[c] = None
        try:
            status, body = get(f"{base.rstrip('/')}/cam/{c}.jpg?q={quality}", {})
        except OSError:
            continue
        if status != 200:
            continue
        img = cv2.imdecode(np.frombuffer(body, np.uint8), cv2.IMREAD_COLOR)
        if img is not None:
            tick[c] = Frame(img, ts, c)
    return tick
