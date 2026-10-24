"""Teach the gallery a product by dropping it in the cart a few times (spec §6.3).

Runs the real pipeline (its own scratch state, never the real cart) with an identifier that always
answers the product being enrolled. Each "added" contributes the tight core crop from every camera
that saw it, which is exactly what the matcher compares at run time.
"""
from __future__ import annotations

import shutil
from pathlib import Path
from typing import Callable, Iterable

from kartcv.identify.hybrid import Identification
from kartcv.pipeline import Pipeline


class _Fixed:
    def __init__(self, product_id: str, name: str):
        self.answer = Identification(product_id, 1.0, "local", name)

    def identify(self, crops, cloud_crops=None, allow_cloud=True) -> Identification:
        return self.answer


def run_enrollment(ticks: Iterable[dict], product_id: str, rounds: int, gallery, catalog, cfg, work_dir: Path,
                   on_progress: Callable[[str], None] = print) -> int:
    if catalog.get(product_id) is None:
        raise ValueError(f"{product_id!r} is not in the catalog")
    state = Path(work_dir) / "state"
    shutil.rmtree(state, ignore_errors=True)  # fresh empty-basket reset every enrollment
    identifier = _Fixed(product_id, catalog.name(product_id))
    pipeline = None
    captured = 0
    for tick in ticks:
        if pipeline is None:
            pipeline = Pipeline(cfg, sorted(tick), identifier, gallery.features, [], state)
        pipeline.step(tick)
        for d in pipeline.last_decisions:
            if d.kind == "added":
                for b in d.blobs:
                    gallery.add(product_id, b.after_core)
                captured += 1
                on_progress(f"captured {captured}/{rounds}: take it out")
                if captured >= rounds:
                    return captured
            elif d.kind == "removed":
                on_progress("put it back in, in a new pose")
    return captured
