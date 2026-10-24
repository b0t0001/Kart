import shutil

import numpy as np
import pytest

from kartcv.config import REPO_ROOT
from kartcv.identify.features import HistogramFeatures, OnnxFeatures, load_features
from kartcv.identify.gallery import Gallery
from kartcv.synth import Item, crop_item

RED = Item("red-box", 300, 200, seed=1)
BLUE = Item("blue-can", 300, 200, seed=2)
GREEN = Item("green-bag", 300, 200, seed=3)
MODEL = REPO_ROOT / "pi/models/features.onnx"


def test_histogram_features():
    f = HistogramFeatures()
    a0, a1, b0 = f(crop_item(0, RED)), f(crop_item(1, RED)), f(crop_item(0, BLUE))
    assert a0.dtype == np.float32 and a0.shape == (256,) and abs(np.linalg.norm(a0) - 1) < 1e-5
    assert a0 @ a1 > a0 @ b0 + 0.2


def test_gallery_scores_and_cache(tmp_path):
    g = Gallery(tmp_path, HistogramFeatures())
    g.load()
    assert g.score([crop_item(0, RED)]) == []
    for it in (RED, BLUE, GREEN):
        g.add(it.item_id, crop_item(0, it))
        g.add(it.item_id, crop_item(1, it))
    moved = Item("red-box", 520, 60, seed=1)
    ranked = g.score([crop_item(0, moved), crop_item(1, moved)])
    assert ranked[0][0] == "red-box" and ranked[0][1] > ranked[1][1] and len(ranked) == 3
    shutil.copy(tmp_path / "blue-can" / "000.jpg", tmp_path / "blue-can" / "009.jpg")
    g2 = Gallery(tmp_path, HistogramFeatures())
    g2.load()
    assert g2.products() == {"red-box", "blue-can", "green-bag"} and (tmp_path / "index.npz").exists()
    assert sum(1 for p in g2._paths if "blue-can" in str(p)) == 3  # picked up the externally added file


def test_load_features_fallback(tmp_path):
    assert isinstance(load_features(tmp_path / "missing.onnx"), HistogramFeatures)
    assert isinstance(load_features(MODEL, "hist"), HistogramFeatures)


@pytest.mark.skipif(not MODEL.exists(), reason="run tools/fetch_model.py first")
def test_onnx_features_dim():
    v = OnnxFeatures(MODEL)(crop_item(0, RED))
    assert v.shape == (1280,) and abs(np.linalg.norm(v) - 1) < 1e-4


def test_leave_one_out_report(tmp_path):  # review C3: decide hist vs ONNX on real enrolled props
    g = Gallery(tmp_path, HistogramFeatures())
    g.load()
    for it in (RED, BLUE, GREEN):
        for x, y in [(300, 200), (520, 300), (120, 80)]:
            for cam in (0, 1):
                g.add(it.item_id, crop_item(cam, Item(it.item_id, x, y, seed=it.seed), pad=0.0))
    r = g.leave_one_out()
    assert r["images"] == 18 and r["products"] == 3 and r["top1"] == 1.0 and r["median_margin"] > 0.1
