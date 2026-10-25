"""Local-first identification policy: gallery → Claude → unknown (spec §6.1)."""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

OVERSIZE = 2.0  # blob area vs the enrolled single-unit median that triggers a Claude count


@dataclass
class Identification:
    product_id: str | None
    confidence: float
    method: str  # "local" | "cloud" | "none"
    label: str
    count: int = 1  # identical units in this blob (claude_count beta)
    personal: bool = False  # the shopper's own belonging: remember it, never bill it (personal_items)
    asked: bool = False     # unknown after Claude really looked (not a timeout or no cloud at all)


class HybridIdentifier:
    def __init__(self, gallery, cloud, catalog, cfg):
        self.gallery, self.cloud, self.catalog, self.cfg = gallery, cloud, catalog, cfg

    def _oversized(self, pid: str, crops: list[np.ndarray], allow_cloud: bool = True) -> bool:
        """claude_count: is this blob much bigger than that product's enrolled single-unit photos?"""
        if not (allow_cloud and self.cfg.claude_count and self.cloud is not None and crops):
            return False
        typical = getattr(self.gallery, "typical_area", lambda _: None)(pid)
        if not typical:
            return False
        return max(c.shape[0] * c.shape[1] for c in crops) >= OVERSIZE * typical

    def identify(self, crops: list[np.ndarray], cloud_crops: list[np.ndarray] | None = None,
                 allow_cloud: bool = True) -> Identification:
        """`crops` are tight (what the gallery holds); `cloud_crops` may be padded for Claude's context.
        allow_cloud=False keeps the photos on the cart (an arm-like change: maybe a child's hand)."""
        ranked = self.gallery.score(crops) if self.gallery is not None else []
        # A gallery product the merchant removed must never be billed.
        ranked = [(pid, s) for pid, s in ranked if self.catalog.get(pid) is not None]
        best_conf = ranked[0][1] if ranked else 0.0

        if ranked:
            top_pid, top = ranked[0]
            margin = top - ranked[1][1] if len(ranked) > 1 else top
            if top >= self.cfg.local_min_score and margin >= self.cfg.local_min_margin:
                local = Identification(top_pid, top, "local", self.catalog.name(top_pid))
                if not self._oversized(top_pid, crops, allow_cloud):
                    return local
                # claude_count: much bigger than one enrolled unit, so maybe several. Let Claude count.
                a = self.cloud.identify(cloud_crops or crops)
                if a.product_id is not None and self.catalog.get(a.product_id) and a.confidence >= self.cfg.cloud_min_conf:
                    return Identification(a.product_id, a.confidence, "cloud", self.catalog.name(a.product_id), a.count)
                return local

        cloud_label = None
        if allow_cloud and self.cloud is not None and (cloud_crops or crops):
            a = self.cloud.identify(cloud_crops or crops)
            if a.personal and self.cfg.personal_items:
                return Identification(None, a.confidence, "personal", a.label or "personal item", personal=True)
            if a.product_id is not None and self.catalog.get(a.product_id) and a.confidence >= self.cfg.cloud_min_conf:
                return Identification(a.product_id, a.confidence, "cloud", self.catalog.name(a.product_id),
                                      a.count if self.cfg.claude_count else 1)
            best_conf = max(best_conf, a.confidence)
            if a.label and not a.label.startswith("error:"):
                cloud_label = a.label

        label = cloud_label or (self.catalog.name(ranked[0][0]) if ranked else "unknown item")
        return Identification(None, best_conf, "none", label, asked=cloud_label is not None)
