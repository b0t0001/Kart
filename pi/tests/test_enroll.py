import pytest
from helpers import synth_catalog

from kartcv.config import Config
from kartcv.enroll import run_enrollment
from kartcv.identify.features import HistogramFeatures
from kartcv.identify.gallery import Gallery
from kartcv.synth import Item, Scene, Script


def test_enroll_three_rounds(tmp_path):
    sc = Script(Scene()).still(1.0)
    for x in (150, 300, 450):
        sc.drop(Item("red-box", x, 200, seed=1)).take("red-box")
    g = Gallery(tmp_path / "gallery", HistogramFeatures())
    g.load()
    msgs = []
    n = run_enrollment(sc.ticks, "red-box", 3, g, synth_catalog(), Config(), tmp_path / "work", on_progress=msgs.append)
    assert n == 3 and len(list((tmp_path / "gallery/red-box").glob("*.jpg"))) == 6  # 2 cameras × 3 rounds
    assert any("captured 3/3" in m for m in msgs)


def test_enroll_unknown_product(tmp_path):
    with pytest.raises(ValueError):
        run_enrollment([], "nope", 1, Gallery(tmp_path, HistogramFeatures()), synth_catalog(), Config(), tmp_path / "w")
