from helpers import settle, world

from kartcv.cart import View
from kartcv.changes import ChangeResult, detect_changes
from kartcv.decide import apply_decision, classify_blob, decide
from kartcv.synth import Item, Scene

RED = Item("red-box", 300, 200, seed=1)
BLUE = Item("blue-can", 560, 330, seed=2)


def step(w, before, after):
    ds = decide(settle(before, after, w.cfg), w.empties, w.cart, w.identifier, w.features, w.cfg)
    for d in ds:
        apply_decision(w.cart, d)
    return ds


def test_one_item_two_cameras_is_one_added(tmp_path):
    w = world(tmp_path)
    [d] = step(w, Scene(), Scene(items=[RED]))
    assert (d.kind, d.product_id, d.method, sorted(d.cameras)) == ("added", "red-box", "local", [0, 1])


def test_two_items_and_hidden_camera(tmp_path):
    w = world(tmp_path)
    assert {d.product_id for d in step(w, Scene(), Scene(items=[RED, BLUE]))} == {"red-box", "blue-can"}
    w2 = world(tmp_path / "b")
    [d] = step(w2, Scene(), Scene(items=[RED], hidden={0: {"red-box"}}))
    assert d.product_id == "red-box" and d.cameras == [1]


def test_disturbed_camera_does_not_block_other(tmp_path):  # Review Focus 2
    w = world(tmp_path)
    rs = settle(Scene(), Scene(items=[RED]), w.cfg)
    r0 = rs[0]
    rs[0] = ChangeResult(0, "disturbed", [], 0.7, (0.0, 0.0), r0.frame, r0.reference)
    [d] = decide(rs, w.empties, w.cart, w.identifier, w.features, w.cfg)
    assert (d.kind, d.product_id) == ("added", "red-box")


def test_removal_from_memory_and_bounds(tmp_path):
    w = world(tmp_path)
    step(w, Scene(), Scene(items=[RED, BLUE]))
    red_id = next(i.instance_id for i in w.cart.instances.values() if i.product_id == "red-box")
    [d] = step(w, Scene(items=[RED, BLUE]), Scene(items=[BLUE]))
    assert (d.kind, d.product_id, d.method, d.instance_id) == ("removed", "red-box", "memory", red_id)
    assert w.cart.count("red-box") == 0
    w2 = world(tmp_path / "b")
    assert step(w2, Scene(items=[RED]), Scene()) == []  # nothing in cart → nothing removed


def test_nudge_is_moved(tmp_path):
    w = world(tmp_path)
    step(w, Scene(), Scene(items=[RED]))
    moved = Item("red-box", 450, 200, seed=1)
    assert [d.kind for d in step(w, Scene(items=[RED]), Scene(items=[moved]))] == ["moved"]
    assert w.cart.count("red-box") == 1


def test_stacked_add_then_revealed_removal(tmp_path):
    w = world(tmp_path)
    big = Item("blue-can", 250, 150, w=300, h=220, seed=2)
    top = Item("red-box", 330, 210, seed=1)
    step(w, Scene(), Scene(items=[big]))
    rs = settle(Scene(items=[big]), Scene(items=[big, top]), w.cfg)
    assert classify_blob(rs[0].blobs[0], rs[0], w.empties[0], w.cart, w.features, w.cfg) == "added"
    step(w, Scene(items=[big]), Scene(items=[big, top]))
    rs = settle(Scene(items=[big, top]), Scene(items=[big]), w.cfg)
    assert classify_blob(rs[0].blobs[0], rs[0], w.empties[0], w.cart, w.features, w.cfg) == "removed"
    [d] = step(w, Scene(items=[big, top]), Scene(items=[big]))
    assert (d.kind, d.product_id) == ("removed", "red-box") and w.cart.count("blue-can") == 1


def test_camera_without_empty_picture_is_skipped(tmp_path):  # review I1
    w = world(tmp_path)
    step(w, Scene(), Scene(items=[RED]))
    only_cam0 = {0: w.empties[0]}  # cam1 never got an empty-basket picture
    ds = decide(settle(Scene(items=[RED]), Scene(), w.cfg), only_cam0, w.cart, w.identifier, w.features, w.cfg)
    assert [(d.kind, d.product_id) for d in ds] == [("removed", "red-box")]


def test_gain_matching_runs_once_per_camera_not_per_blob(tmp_path, monkeypatch):  # review I4: Pi speed
    import kartcv.decide as dm
    w = world(tmp_path)
    calls = []
    real = dm.match_gain
    monkeypatch.setattr(dm, "match_gain", lambda *a: calls.append(1) or real(*a))
    items = [RED, BLUE, Item("green-bag", 80, 60, seed=3)]
    decide(settle(Scene(), Scene(items=items), w.cfg), w.empties, w.cart, w.identifier, w.features, w.cfg)
    assert len(calls) <= 2 * 2  # (current, reference) once per camera, however many blobs


def test_removal_of_something_never_billed_removes_nothing(tmp_path):  # review C1(c): location gating
    w = world(tmp_path)
    step(w, Scene(), Scene(items=[BLUE]))  # only BLUE is in memory; RED arrives unbilled
    assert step(w, Scene(items=[RED, BLUE]), Scene(items=[BLUE])) == [] and w.cart.count("blue-can") == 1


def test_every_unit_whose_spot_emptied_is_removed(tmp_path):  # review C1(c)
    from kartcv.cart import View
    w = world(tmp_path)
    step(w, Scene(), Scene(items=[RED]))
    red = next(iter(w.cart.instances.values()))
    w.cart.add(None, "a hand?", {c: View(c, v.box, v.fingerprint) for c, v in red.views.items()})  # same spot
    ds = step(w, Scene(items=[RED]), Scene())
    assert sorted((d.kind, d.product_id or "") for d in ds) == [("removed", ""), ("removed", "red-box")]
    assert len(w.cart.instances) == 0


class FlatFeatures:
    """An extractor that can't tell items apart (like pooled CNN features on look-alike packaging)."""
    name = "flat"

    def __call__(self, crop):
        import numpy as np
        v = np.ones(8, np.float32) + crop.mean() / 1e4
        return v / np.linalg.norm(v)


def test_stacked_add_is_not_mistaken_for_a_reveal_when_features_cant_discriminate(tmp_path):  # review C3
    w = world(tmp_path)
    big = Item("blue-can", 250, 150, w=300, h=220, seed=2)
    top = Item("red-box", 330, 210, seed=1)
    flat = FlatFeatures()
    for d in decide(settle(Scene(), Scene(items=[big]), w.cfg), w.empties, w.cart, w.identifier, flat, w.cfg):
        apply_decision(w.cart, d)
    rs = settle(Scene(items=[big]), Scene(items=[big, top]), w.cfg)
    assert classify_blob(rs[0].blobs[0], rs[0], w.empties[0], w.cart, flat, w.cfg) == "added"


def test_joint_identification_sends_the_biggest_view_first(tmp_path):  # one camera's blob may be spurious
    w = world(tmp_path)
    seen = []

    class Spy:
        def identify(self, crops, cloud_crops=None):
            seen.append([c.shape[0] * c.shape[1] for c in (cloud_crops or crops)])
            return w.identifier.identify(crops, cloud_crops)

    decide(settle(Scene(), Scene(items=[RED], hidden={}), w.cfg), w.empties, w.cart, Spy(), w.features, w.cfg)
    assert seen and seen[0] == sorted(seen[0], reverse=True)


BIG = Item("big", 140, 80, w=540, h=360, seed=11)  # covers more than half of the floor
SMALL = Item("red-box", 20, 400, w=110, h=80, seed=1)


def _roi_world(tmp_path):
    from kartcv.synth import mat_roi
    w = world(tmp_path)
    w.cfg.roi = {"0": mat_roi(0), "1": mat_roi(1)}
    return w


def test_exposure_change_with_a_big_item_still_detects_just_the_item(tmp_path):  # real cart: issue 2
    w = _roi_world(tmp_path)
    r = detect_changes(0, Scene().render(0, 1), Scene(items=[BIG], brightness=1.15).render(0, 2), w.cfg,
                       roi=w.cfg.roi["0"])
    assert r.status == "blobs" and len(r.blobs) == 1


def test_removal_next_to_a_big_item_after_an_exposure_change_is_a_removal(tmp_path):  # real cart: issue 3
    w = _roi_world(tmp_path)
    w.cart.add("green-bag", "Big", {0: View(0, (300, 150, 600, 420), [0.0] * 256)})  # the big item, remembered
    before, after = Scene(items=[BIG, SMALL], brightness=1.15), Scene(items=[BIG], brightness=1.15)
    r = detect_changes(0, before.render(0, 1), after.render(0, 2), w.cfg, roi=w.cfg.roi["0"])
    [b] = r.blobs
    assert classify_blob(b, r, w.empties[0], w.cart, w.features, w.cfg) == "removed"
