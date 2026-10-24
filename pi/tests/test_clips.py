"""Regression tests from real-cart clips (pi/tests/clips/<name>/: cam0/, cam1/, expected.json).

Each clip replays through the real pipeline with its own floor ROI, offline (no gallery, no Claude:
products come out unknown), and must produce exactly the ground-truth "expected" events. The "live"
lines in expected.json are what a past live run printed, including known false ones (a cardboard flap,
a cloth outside the floor); they are history, not expectations, so they are asserted absent implicitly.
"""
import json
import tempfile
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


def replay(clip: Path):
    exp = json.loads((clip / "expected.json").read_text())
    cfg = Config(features="hist", roi=exp.get("roi", {}))
    catalog = load_catalog(REPO_ROOT / "data/store.json")
    sink = MemorySink()
    sources = load_recording(clip)
    p = Pipeline(cfg, [s.cam for s in sources], HybridIdentifier(None, None, catalog, cfg), HistogramFeatures(),
                 [sink], Path(tempfile.mkdtemp()) / "state")
    for tick in iter_ticks(sources):
        p.step(tick)
    return exp, sink.events, p


@pytest.mark.parametrize("clip", CLIPS, ids=[c.name for c in CLIPS])
def test_real_clip(clip):
    exp, events, p = replay(clip)
    assert [e.type for e in events] == [x["type"] for x in exp["expected"]], exp["what_happened"]
    for got, want in zip(events, exp["expected"]):
        if want.get("product_id"):  # null or missing = any product (unknowns are fine without enrolled props)
            assert got.product_id == want["product_id"]
    adds = sum(e.type == "added" for e in events)
    assert len(p.cart.instances) == adds - (len(events) - adds)  # memory agrees with what was billed
