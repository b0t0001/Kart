"""Local-first identification policy: gallery → Claude → unknown (spec §6.1)."""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass
class Identification:
    product_id: str | None
    confidence: float
    method: str  # "local" | "cloud" | "none"
    label: str


class HybridIdentifier:
    def __init__(self, gallery, cloud, catalog, cfg):
        self.gallery, self.cloud, self.catalog, self.cfg = gallery, cloud, catalog, cfg

    def identify(self, crops: list[np.ndarray]) -> Identification:
        ranked = self.gallery.score(crops) if self.gallery is not None else []
        # A gallery product the merchant removed must never be billed.
        ranked = [(pid, s) for pid, s in ranked if self.catalog.get(pid) is not None]
        best_conf = ranked[0][1] if ranked else 0.0

        if ranked:
            top_pid, top = ranked[0]
            margin = top - ranked[1][1] if len(ranked) > 1 else top
            if top >= self.cfg.local_min_score and margin >= self.cfg.local_min_margin:
                return Identification(top_pid, top, "local", self.catalog.name(top_pid))

        cloud_label = None
        if self.cloud is not None and crops:
            a = self.cloud.identify(crops)
            if a.product_id is not None and self.catalog.get(a.product_id) and a.confidence >= self.cfg.cloud_min_conf:
                return Identification(a.product_id, a.confidence, "cloud", self.catalog.name(a.product_id))
            best_conf = max(best_conf, a.confidence)
            if a.label and not a.label.startswith("error:"):
                cloud_label = a.label

        label = cloud_label or (self.catalog.name(ranked[0][0]) if ranked else "unknown item")
        return Identification(None, best_conf, "none", label)
