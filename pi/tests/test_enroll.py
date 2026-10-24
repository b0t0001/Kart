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


def _gallery(tmp_path):
    g = Gallery(tmp_path / "gallery", HistogramFeatures())
    g.load()
    return g


def _photos(tmp_path):
    return sorted((tmp_path / "gallery/red-box").glob("*.jpg"))


def test_each_capture_prints_its_photos_for_the_operator_to_check(tmp_path):
    sc = Script(Scene()).still(1.0).drop(Item("red-box", 300, 200, seed=1))
    msgs = []
    run_enrollment(sc.ticks, "red-box", 1, _gallery(tmp_path), synth_catalog(), Config(), tmp_path / "w",
                   on_progress=msgs.append)
    [m] = [m for m in msgs if "captured 1/1" in m]
    assert all(str(p) in m for p in _photos(tmp_path)) and len(_photos(tmp_path)) == 2


def test_a_change_with_no_hand_in_the_cart_is_never_captured(tmp_path):  # real cart: the liner settling
    sc = Script(Scene()).still(1.0)
    sc.set(items=[Item("red-box", 300, 200, seed=1)]).still(2.0)  # nobody there: something just shifts into view
    sc.set(items=[]).still(2.0)                                    # ...and back out, still nobody
    sc.drop(Item("red-box", 450, 200, seed=1)).still(1.0)          # the operator really puts it in
    msgs = []
    n = run_enrollment(sc.ticks, "red-box", 1, _gallery(tmp_path), synth_catalog(), Config(), tmp_path / "w",
                       on_progress=msgs.append)
    assert n == 1 and len(_photos(tmp_path)) == 2 and any("no hand" in m for m in msgs)


def test_one_capture_per_round_even_if_something_else_shifts_too(tmp_path):
    sc = Script(Scene()).still(1.0).drop_many([Item("red-box", 300, 200, seed=1),
                                               Item("blue-can", 600, 330, seed=2)])  # + a second change
    n = run_enrollment(sc.ticks, "red-box", 2, _gallery(tmp_path), synth_catalog(), Config(), tmp_path / "w")
    assert n == 1 and len(_photos(tmp_path)) == 2


def test_a_change_along_the_floor_outline_is_not_captured(tmp_path):  # the liner's edge against the far wall
    from kartcv.enroll import along_outline
    from kartcv.roi import polygon_mask
    from kartcv.synth import mat_roi
    m = polygon_mask(mat_roi(0), (1280, 720))
    ys, xs = m.nonzero()
    top = ys.min()  # the far edge of the floor, as camera 0 sees it
    cx = int(xs[ys == top + 30].mean())
    assert along_outline((cx - 80, top, 160, 14), m) >= 0.7    # a strip right along the outline
    assert along_outline((cx - 60, top + 200, 120, 90), m) == 0.0  # an item out on the floor


def test_a_change_that_looks_like_the_liner_is_not_captured():
    import cv2
    from kartcv.enroll import liner_colored
    from kartcv.synth import crop_item
    empty = Scene().render(0, 1)
    fold = cv2.convertScaleAbs(empty[300:400, 500:650], alpha=0.75)  # the same cloth, in a fold's shadow
    assert liner_colored(fold, None, empty, None) >= 0.85
    assert liner_colored(crop_item(0, Item("red-box", 300, 200, seed=1), pad=0.0), None, empty, None) < 0.3
