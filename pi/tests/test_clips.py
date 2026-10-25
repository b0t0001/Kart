"""Regression tests from real-cart clips (pi/tests/clips/<name>/: cam0/, cam1/, expected.json).

Each clip replays through the real pipeline with its own floor ROI, offline (no gallery, no Claude:
products come out unknown), and must produce exactly the ground-truth "expected" events. The "live"
lines in expected.json are what a past live run printed, including known false ones (a cardboard flap,
a cloth outside the floor); they are history, not expectations, so they are asserted absent implicitly.

After the last frame the cart stands still for a few seconds, as it did live, so a pending intrusion
recheck is judged too (four-corners: the slumped almond bag was billed a second time at exactly that point).
"""
import json
import tempfile
from dataclasses import replace
from pathlib import Path

import pytest

from kartcv.catalog import load_catalog
from kartcv.config import REPO_ROOT, Config
from kartcv.identify.features import HistogramFeatures
from kartcv.identify.hybrid import HybridIdentifier
from kartcv.pipeline import Pipeline
from kartcv.sinks import MemorySink
from kartcv.sources import iter_ticks, load_recording

CLIPS = sorted(p for p in (Path(__file__).parent / "clips").glob("*") if (p / "expected.json").exists())


def held(ticks, seconds: float, hz: float = 5.0):
    """The clip's ticks, then its last frames held still for `seconds` more."""
    last = None
    for last in ticks:
        yield last
    for i in range(1, int(seconds * hz) + 1):
        yield {c: replace(f, ts=f.ts + i / hz) if f is not None else None for c, f in last.items()}


def replay(clip: Path):
    exp = json.loads((clip / "expected.json").read_text())
    cfg = Config(features="hist", roi=exp.get("roi", {}))
    catalog = load_catalog(REPO_ROOT / "data/store.json")
    sink = MemorySink()
    sources = load_recording(clip)
    p = Pipeline(cfg, [s.cam for s in sources], HybridIdentifier(None, None, catalog, cfg), HistogramFeatures(),
                 [sink], Path(tempfile.mkdtemp()) / "state")
    for tick in held(iter_ticks(sources), cfg.settle_s + cfg.intrusion_recheck_s + 1.0):
        p.step(tick)
    return exp, sink.events, p


@pytest.mark.parametrize("clip", CLIPS, ids=[c.name for c in CLIPS])
def test_real_clip(clip):
    exp, events, p = replay(clip)
    assert [e.type for e in events] == [x["type"] for x in exp["expected"]], exp["what_happened"]
    # Offline there's no gallery and no Claude, so units come out unknown. A named one must be right, and
    # an unknown removal must close the add of the same real product: what was taken out, not a neighbour.
    add_of = {e.event_id: want for e, want in zip(events, exp["expected"]) if e.type == "added"}
    for got, want in zip(events, exp["expected"]):
        if not want.get("product_id"):  # null or missing = any product
            continue
        if got.product_id is not None:
            assert got.product_id == want["product_id"]
        elif got.type == "removed":
            assert add_of[got.resolves_event_id].get("product_id") == want["product_id"], want
    adds = sum(e.type == "added" for e in events)
    assert len(p.cart.instances) == adds - (len(events) - adds)  # memory agrees with what was billed


@pytest.mark.parametrize("clip", CLIPS, ids=[c.name for c in CLIPS])
def test_enrollment_captures_every_placed_item_and_nothing_else(clip, tmp_path):
    # The enrollment guards (a hand came and went; not the liner's colors or its edge) must never turn
    # away a real placement: corner apples, tall bottles, the almond bag on the black-shirt liner.
    from helpers import synth_catalog
    from kartcv.enroll import run_enrollment
    from kartcv.identify.gallery import Gallery
    exp = json.loads((clip / "expected.json").read_text())
    cfg = Config(features="hist", roi=exp.get("roi", {}))
    gallery = Gallery(tmp_path / "gallery", HistogramFeatures())
    gallery.load()
    ticks = held(iter_ticks(load_recording(clip)), cfg.settle_s + cfg.intrusion_recheck_s + 1.0)
    n = run_enrollment(ticks, "red-box", 99, gallery, synth_catalog(), cfg, tmp_path / "w", on_progress=lambda m: None)
    # (an out-and-in of one product within one settle is a move, not an add: expected.json may say so)
    assert n == exp.get("enrollment_captures", sum(x["type"] == "added" for x in exp["expected"]))
