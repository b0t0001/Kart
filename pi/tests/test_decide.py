from helpers import settle, world

from kartcv.changes import ChangeResult
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
