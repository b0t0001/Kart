import json

import numpy as np

from kartcv.roi import grid_overlay, parse_points, polygon_mask, preview, write_roi


def test_parse_points_normalized_or_pixels():
    assert parse_points("0.1,0.4 0.9,0.38 0.97,0.98") == [[0.1, 0.4], [0.9, 0.38], [0.97, 0.98]]
    assert parse_points("128,72 1152,72 640,648", size_wh=(1280, 720)) == [[0.1, 0.1], [0.9, 0.1], [0.5, 0.9]]


def test_preview_dims_outside_only_and_grid_draws():
    img = np.full((100, 200, 3), 200, np.uint8)
    poly = [[0.25, 0.25], [0.75, 0.25], [0.75, 0.75], [0.25, 0.75]]
    out = preview(img, poly)
    assert out[50, 100].tolist() == [200, 200, 200] and out[5, 5].max() < 120
    assert grid_overlay(img).shape == img.shape and (grid_overlay(img) != img).any()
    assert polygon_mask(poly, (200, 100))[50, 100] == 1 and polygon_mask(poly, (200, 100))[5, 5] == 0


def test_write_roi_merges_into_config(tmp_path):
    cfg = tmp_path / "config.json"
    cfg.write_text(json.dumps({"cameras": ["/dev/a", "/dev/b"], "settle_s": 1.0}))
    write_roi(cfg, 0, [[0.1, 0.4], [0.9, 0.4], [0.5, 0.9]])
    write_roi(cfg, 1, [[0.2, 0.3], [0.8, 0.3], [0.5, 0.95]])
    d = json.loads(cfg.read_text())
    assert d["cameras"] == ["/dev/a", "/dev/b"] and d["settle_s"] == 1.0
    assert d["roi"] == {"0": [[0.1, 0.4], [0.9, 0.4], [0.5, 0.9]], "1": [[0.2, 0.3], [0.8, 0.3], [0.5, 0.95]]}
