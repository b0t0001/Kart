"""Teach the gallery a product by dropping it in the cart a few times (spec §6.3).

Runs the real pipeline (its own scratch state, never the real cart) with an identifier that always
answers the product being enrolled. Each "added" contributes the tight core crop from every camera
that saw it, which is exactly what the matcher compares at run time.

A photo of anything but the product poisons the gallery, so a capture must be a change a hand put
in: a hand came and went since the last capture or removal, the change isn't the liner itself (its
colors, or its edge along the floor outline), and only the biggest such change of a settle counts.
"""
from __future__ import annotations

import shutil
from pathlib import Path
from typing import Callable, Iterable

import cv2
import numpy as np

from kartcv.decide import liner_model, liner_share
from kartcv.identify.hybrid import Identification
from kartcv.motion import floor_difference
from kartcv.pipeline import Pipeline
from kartcv.roi import polygon_mask

HAND = 0.03          # floor share a hand covers on its way in and out (real cart: 0.06–0.63; no hand, even rolling, ≤ 0.014)
EDGE_BAND = 0.03     # of the frame width: the strip inside the floor outline, where the liner meets the wall
EDGE_MAX = 0.7       # a change this much inside that strip is the liner's edge settling, not a product
LINER_MAX = 0.85     # a change whose pixels are this much liner-colored is the liner itself (a fold)


class _Fixed:
    def __init__(self, product_id: str, name: str):
        self.answer = Identification(product_id, 1.0, "local", name)

    def identify(self, crops, cloud_crops=None, allow_cloud=True) -> Identification:
        return self.answer


def liner_colored(crop: np.ndarray, crop_mask, empty: np.ndarray, empty_mask) -> float:
    """Share of the crop's pixels (inside crop_mask, if any) in the empty liner's own colors."""
    return liner_share(crop, crop_mask, liner_model(empty, empty_mask))


def along_outline(box: tuple[int, int, int, int], floor: np.ndarray) -> float:
    """Share of the floor inside `box` that lies in the EDGE_BAND strip along the floor outline."""
    band = max(3, int(round(EDGE_BAND * floor.shape[1])))
    inner = cv2.erode(floor.astype(np.uint8), cv2.getStructuringElement(cv2.MORPH_RECT, (2 * band + 1, 2 * band + 1)),
                      borderType=cv2.BORDER_CONSTANT, borderValue=0)
    x, y, w, h = box
    on = floor[y:y + h, x:x + w].astype(bool)
    return float(1.0 - inner[y:y + h, x:x + w][on].mean()) if on.any() else 1.0


def _not_the_product(d, frames: dict, pipeline: Pipeline) -> str | None:
    """Why this add is the liner rather than the product, or None."""
    for b in d.blobs:
        img = frames[b.cam]
        h, w = img.shape[:2]
        floor = polygon_mask(pipeline.cfg.roi.get(str(b.cam)), (w, h))
        floor = floor if floor is not None else np.ones((h, w), np.uint8)
        if along_outline(b.core_box, floor) >= EDGE_MAX:
            return f"cam{b.cam}: it lies along the edge of the floor (the liner's edge settling?)"
        x, y, bw, bh = b.core_box
        empty = pipeline.empties.get(b.cam)
        if empty is not None and liner_colored(img[y:y + bh, x:x + bw], floor[y:y + bh, x:x + bw],
                                               empty, floor) >= LINER_MAX:
            return f"cam{b.cam}: it looks like the liner (a fold settling?)"
    return None


def run_enrollment(ticks: Iterable[dict], product_id: str, rounds: int, gallery, catalog, cfg, work_dir: Path,
                   on_progress: Callable[[str], None] = print) -> int:
    if catalog.get(product_id) is None:
        raise ValueError(f"{product_id!r} is not in the catalog")
    state = Path(work_dir) / "state"
    shutil.rmtree(state, ignore_errors=True)  # fresh empty-basket reset every enrollment
    identifier = _Fixed(product_id, catalog.name(product_id))
    pipeline = None
    captured = 0
    hand = False  # a hand came and went since the last capture or removal
    peak: dict[int, float] = {}
    for tick in ticks:
        if pipeline is None:
            pipeline = Pipeline(cfg, sorted(tick), identifier, gallery.features, [], state)
        frames = {c: f.image for c, f in tick.items() if f is not None}
        moving = pipeline.settle.state == "motion"
        cover = {c: floor_difference(img, pipeline.references[c], cfg.motion_size, cfg.motion_thresh,
                                     cfg.roi.get(str(c)))
                 for c, img in frames.items() if moving and c in pipeline.references}
        for c, v in cover.items():
            peak[c] = max(peak.get(c, 0.0), v)
        pipeline.step(tick)
        if moving and pipeline.settle.state != "motion":  # settled: did something come and go meanwhile?
            hand = hand or any(peak.get(c, 0.0) - v >= HAND for c, v in cover.items())
            peak = {}
        decisions = pipeline.last_decisions
        if any(d.kind == "removed" for d in decisions):
            hand = False
            on_progress("put it back in, in a new pose")
        adds = sorted((d for d in decisions if d.kind == "added"), key=lambda d: -sum(b.area_frac for b in d.blobs))
        if not adds:
            continue
        if not hand:
            on_progress("ignored a change with no hand in the cart (the liner settling?); nothing captured")
            continue
        reasons = [_not_the_product(d, frames, pipeline) for d in adds]
        d = next((d for d, why in zip(adds, reasons) if why is None), None)
        if d is None:
            on_progress(f"ignored a change: {reasons[0]}; nothing captured")
            continue
        paths = [gallery.add(product_id, b.after_core) for b in d.blobs]
        captured += 1
        hand = False
        on_progress(f"captured {captured}/{rounds}: take it out   (check: {' '.join(str(p) for p in paths)})")
        if captured >= rounds:
            return captured
    return captured
