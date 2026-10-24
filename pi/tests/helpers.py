"""Shared test fixtures: a synthetic catalog, an enrolled gallery, and settle helpers."""
from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

from kartcv.cart import CartMemory
from kartcv.catalog import Catalog, Product
from kartcv.changes import ChangeResult, detect_changes
from kartcv.config import Config
from kartcv.identify.features import HistogramFeatures
from kartcv.identify.gallery import Gallery
from kartcv.identify.hybrid import HybridIdentifier
from kartcv.synth import Item, Scene, crop_item

SYNTH = [Item("red-box", 300, 200, seed=1), Item("blue-can", 300, 200, seed=2), Item("green-bag", 300, 200, seed=3)]
ENROLL_AT = [(300, 200), (520, 300)]


def synth_catalog() -> Catalog:
    return Catalog({it.item_id: Product(it.item_id, it.item_id.replace("-", " ").title(), 1.0, f"synthetic {it.item_id}")
                    for it in SYNTH})


def world(tmp_path: Path) -> SimpleNamespace:
    tmp_path = Path(tmp_path)
    tmp_path.mkdir(parents=True, exist_ok=True)
    cfg = Config(features="hist")
    catalog = synth_catalog()
    features = HistogramFeatures()
    gallery = Gallery(tmp_path / "gallery", features)
    gallery.load()
    if not gallery.products():
        for it in SYNTH:
            for x, y in ENROLL_AT:
                for cam in (0, 1):
                    # tight crops, like Blob.after_core: the gallery holds what the matcher compares
                    gallery.add(it.item_id, crop_item(cam, replace(it, x=x, y=y), pad=0.0))
    identifier = HybridIdentifier(gallery, None, catalog, cfg)
    cart = CartMemory(tmp_path / "world_cart.json")
    empties = {c: Scene().render(c) for c in (0, 1)}
    return SimpleNamespace(cfg=cfg, catalog=catalog, features=features, gallery=gallery,
                           identifier=identifier, cart=cart, empties=empties)


def settle(before: Scene, after: Scene, cfg: Config) -> list[ChangeResult]:
    return [detect_changes(c, before.render(c, noise_seed=1), after.render(c, noise_seed=2), cfg) for c in (0, 1)]
