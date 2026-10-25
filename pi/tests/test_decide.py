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
        def identify(self, crops, cloud_crops=None, allow_cloud=True):
            seen.append([c.shape[0] * c.shape[1] for c in (cloud_crops or crops)])
            return w.identifier.identify(crops, cloud_crops, allow_cloud)

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


def _held_back(rs, cam):
    """cam's change was held back this settle (an arm reached its edge): no blobs, just a deferred spot."""
    r = rs[cam]
    held = ChangeResult(cam, "none", [], 0.0, (0.0, 0.0), r.frame, r.reference)
    held.deferred = [b.box for b in r.blobs]
    rs[cam] = held
    return rs


def _quiet(rs, cam):
    r = rs[cam]
    rs[cam] = ChangeResult(cam, "none", [], 0.0, (0.0, 0.0), r.frame, r.reference)
    return rs


def test_a_late_view_from_a_held_back_camera_attaches_instead_of_billing_twice(tmp_path):
    w = world(tmp_path)
    ds = decide(_held_back(settle(Scene(), Scene(items=[RED]), w.cfg), 1), w.empties, w.cart, w.identifier,
                w.features, w.cfg)
    assert [(d.kind, d.cameras) for d in ds] == [("added", [0])]
    for d in ds:
        apply_decision(w.cart, d)
    later = _quiet(settle(Scene(), Scene(items=[RED]), w.cfg), 0)  # the arm left: now cam1 sees the item
    ds = decide(later, w.empties, w.cart, w.identifier, w.features, w.cfg)
    assert [d.kind for d in ds] == ["moved"]
    for d in ds:
        apply_decision(w.cart, d)
    [inst] = w.cart.instances.values()
    assert set(inst.views) == {0, 1}


def test_the_held_back_spot_expires_after_one_clean_look(tmp_path):
    w = world(tmp_path)
    for d in decide(_held_back(settle(Scene(), Scene(items=[RED]), w.cfg), 1), w.empties, w.cart, w.identifier,
                    w.features, w.cfg):
        apply_decision(w.cart, d)
    clean = _quiet(_quiet(settle(Scene(), Scene(), w.cfg), 0), 1)  # cam1 looked and saw nothing there
    decide(clean, w.empties, w.cart, w.identifier, w.features, w.cfg)
    later = _quiet(settle(Scene(), Scene(items=[RED]), w.cfg), 0)
    assert [d.kind for d in decide(later, w.empties, w.cart, w.identifier, w.features, w.cfg)] == ["added"]


def test_an_item_still_in_its_spot_is_never_removed_for_a_neighbour(tmp_path):  # props-final 204 s: spaghetti
    w = world(tmp_path)
    strip = Item("blue-can", 150, 380, w=500, h=60, seed=2)  # a long box near the front
    tall = Item("red-box", 200, 250, w=120, h=170, seed=1)   # stood partly on it
    step(w, Scene(), Scene(items=[strip]))
    # the other camera already took the tall one off the bill; this camera sees its spot empty only now
    assert step(w, Scene(items=[strip, tall]), Scene(items=[strip])) == [] and w.cart.count("blue-can") == 1


def test_a_removal_goes_to_the_unit_whose_footprint_emptied_however_alike_they_look(tmp_path):  # props-final: scissors
    from kartcv.decide import _decide_removed, gain_matched
    w = world(tmp_path)
    box = Item("blue-can", 150, 300, w=400, h=150, seed=2)
    card = Item("red-box", 250, 330, w=120, h=80, seed=1)  # lying on the box
    step(w, Scene(), Scene(items=[box]))
    step(w, Scene(items=[box]), Scene(items=[box, card]))
    card_id = next(i.instance_id for i in w.cart.instances.values() if i.product_id == "red-box")
    rs = settle(Scene(items=[box, card]), Scene(items=[box]), w.cfg)
    for inst in w.cart.instances.values():  # worst case for look: the box remembers exactly what vanished,
        for c, v in inst.views.items():     # the card only a sliver that says nothing
            v.fingerprint = (w.features(rs[c].blobs[0].before_core).tolist() if inst.instance_id != card_id
                             else [0.0] * len(v.fingerprint))
    removed = {r.cam: r.blobs for r in rs}
    matched = {r.cam: gain_matched(r, w.empties[r.cam], None, w.cart) for r in rs}
    [d] = _decide_removed(removed, w.cart, w.features, w.cfg, matched, w.empties)
    assert d.instance_id == card_id


def test_a_late_view_split_in_two_blobs_attaches_whole(tmp_path):  # props-final: cam0's spaghetti at the edge
    w = world(tmp_path)
    halves = [Item("blue-can", 150, 380, w=180, h=60, seed=2), Item("blue-can", 380, 380, w=180, h=60, seed=2)]
    rs = settle(Scene(), Scene(items=halves), w.cfg)
    assert len(rs[0].blobs) == 2
    b1 = rs[1].blobs[0]
    w.cart.add("blue-can", "Blue Can", {1: View(1, b1.box, w.features(b1.after_core).tolist())},
               awaiting={0: [b.box for b in rs[0].blobs]})  # billed from cam1; cam0 was held back
    ds = decide([rs[0]], w.empties, w.cart, w.identifier, w.features, w.cfg)
    assert [d.kind for d in ds] == ["moved"] and len(w.cart.instances) == 1


def test_a_unit_whose_spot_emptied_too_little_for_a_blob_is_still_taken_off(tmp_path):  # props-final: scissors
    from dataclasses import replace
    w = world(tmp_path)
    step(w, Scene(), Scene(items=[RED]))  # billed when it was seen...
    w.cfg = replace(w.cfg, min_blob_frac=0.05)  # ...but its spot emptying makes less than a blob
    rs = settle(Scene(items=[RED]), Scene(), w.cfg)
    assert all(r.status == "none" for r in rs)  # no blob at all: too small
    [d] = decide(rs, w.empties, w.cart, w.identifier, w.features, w.cfg)
    assert (d.kind, d.product_id) == ("removed", "red-box")


def test_a_spot_that_changed_but_is_not_bare_keeps_its_unit(tmp_path):  # something laid over it, or an arm
    from dataclasses import replace
    w = world(tmp_path)
    step(w, Scene(), Scene(items=[RED]))
    w.cfg = replace(w.cfg, min_blob_frac=0.5)
    cover = Item("blue-can", 290, 190, w=140, h=110, seed=2)  # covers it: its spot changed, but isn't bare floor
    assert decide(settle(Scene(items=[RED]), Scene(items=[RED, cover]), w.cfg), w.empties, w.cart,
                  w.identifier, w.features, w.cfg) == []
    assert w.cart.count("red-box") == 1



def test_a_late_view_of_the_unit_just_billed_is_that_unit_not_a_second(tmp_path):  # live: drop 1 billed twice
    # p1: cam0 looks late in the same hand-in. p2/held: the next item's hand-in came before cam0, which was
    # held back (an arm at the edge) when this was billed: still that unit (pasta run 4, items 3 s apart).
    # p2/blind: cam0 simply hadn't seen it, and a second identical box is possible: billed (counting).
    for name, placement, held, kinds in (("p1", "p1", False, ["moved"]), ("held", "p2", True, ["moved"]),
                                         ("blind", "p2", False, ["added"])):
        w = world(tmp_path / name)
        rs = settle(Scene(), Scene(items=[RED]), w.cfg)
        [d] = decide([rs[1]], w.empties, w.cart, w.identifier, w.features, w.cfg, placement="p1")  # cam1 bills it
        if held:
            d.awaiting = {0: [b.box for b in rs[0].blobs]}
        apply_decision(w.cart, d)
        ds = decide([rs[0]], w.empties, w.cart, w.identifier, w.features, w.cfg, placement=placement)  # cam0, later
        assert [d.kind for d in ds] == kinds, name


def test_a_box_set_beside_one_already_billed_is_a_second_unit_even_if_its_hand_went_unseen(tmp_path):  # counting
    w = world(tmp_path)
    first, beside = Item("red-box", 300, 200, seed=1), Item("red-box", 440, 200, seed=1)  # a small gap between
    for d in decide(settle(Scene(), Scene(items=[first]), w.cfg), w.empties, w.cart, w.identifier, w.features,
                    w.cfg, placement="p1"):
        apply_decision(w.cart, d)
    ds = decide(settle(Scene(items=[first]), Scene(items=[first, beside]), w.cfg), w.empties, w.cart,
                w.identifier, w.features, w.cfg, placement="p1")  # same placement: its hand-in was missed
    assert [d.kind for d in ds] == ["added"] and len(ds[0].blobs) >= 1


LID = Item("lid", 250, 150, w=90, h=90, seed=7)      # a close-up of just the jar's lid: the gallery misnames it
LID_UNKNOWN = Item("lid", 250, 150, w=90, h=90, seed=4)  # ...or doesn't recognize it at all
JAR = Item("red-box", 300, 200, seed=1)              # the whole jar, as the other camera sees it


def _cam(w, cam, after_items):
    from kartcv.changes import detect_changes
    return detect_changes(cam, Scene().render(cam, 1), Scene(items=after_items).render(cam, 2), w.cfg)


def test_a_lid_closeup_in_one_camera_and_the_named_jar_in_the_other_are_one_unit(tmp_path):  # pasta run 3
    w = world(tmp_path)
    label = Item("red-box", 380, 150, seed=1)  # cam0 also catches part of the label, just past the lid
    r0 = _cam(w, 0, [LID, label])
    assert len(r0.blobs) == 2  # two pieces in cam0; the lid alone looks like another product
    ds = decide([r0, _cam(w, 1, [JAR])], w.empties, w.cart, w.identifier, w.features, w.cfg, placement="p1")
    assert [(d.kind, d.product_id) for d in ds] == [("added", "red-box")]


def test_two_products_put_in_together_stay_two_even_if_one_camera_misses_one(tmp_path):
    w = world(tmp_path)
    red, blue = Item("red-box", 120, 80, seed=1), Item("blue-can", 600, 380, seed=2)
    ds = decide([_cam(w, 0, [blue]), _cam(w, 1, [red, blue])], w.empties, w.cart, w.identifier, w.features,
                w.cfg, placement="p1")  # cam0 can't see the red box
    assert sorted(d.product_id for d in ds if d.kind == "added") == ["blue-can", "red-box"]


def test_an_unknown_billed_first_is_replaced_when_the_other_camera_names_it(tmp_path):  # cam1 held back
    w = world(tmp_path)
    [d] = decide([_cam(w, 0, [LID_UNKNOWN])], w.empties, w.cart, w.identifier, w.features, w.cfg, placement="p1")
    assert (d.kind, d.product_id) == ("added", None)  # only the lid: unknown
    apply_decision(w.cart, d)
    ds = decide([_cam(w, 1, [JAR])], w.empties, w.cart, w.identifier, w.features, w.cfg, placement="p1")
    assert [(d.kind, d.product_id) for d in ds] == [("removed", None), ("added", "red-box")]
    for d in ds:
        apply_decision(w.cart, d)
    [inst] = w.cart.instances.values()
    assert inst.product_id == "red-box" and set(inst.views) == {0, 1}  # one unit, named, seen by both



def test_a_late_view_next_to_the_piece_already_seen_is_that_item(tmp_path):  # run 4: the jar body, judged late
    w = world(tmp_path)
    rs = settle(Scene(), Scene(items=[RED]), w.cfg)
    b0, b1 = rs[0].blobs[0], rs[1].blobs[0]
    x, y, bw, bh = b0.box
    lid = View(0, (x, max(0, y - bh // 2), bw, bh // 2), w.features(b0.after_core).tolist())  # just above it
    w.cart.add("red-box", "Red Box", {0: lid, 1: View(1, b1.box, w.features(b1.after_core).tolist())},
               placement="p1")
    for b in rs[0].blobs:
        b.placement = "p1"  # it waited on an intrusion since the jar's hand-in; judged during the next one
    ds = decide([rs[0]], w.empties, w.cart, w.identifier, w.features, w.cfg, placement="p2")
    assert [d.kind for d in ds] == ["moved"] and len(w.cart.instances) == 1


def test_a_pending_view_keeps_the_hand_in_it_started_in(tmp_path):  # run 4: judged during the next placement
    w = world(tmp_path)
    rs = settle(Scene(), Scene(items=[LID_UNKNOWN]), w.cfg)
    [d] = decide([rs[1]], w.empties, w.cart, w.identifier, w.features, w.cfg, placement="p1")  # cam1 bills it
    apply_decision(w.cart, d)
    for b in rs[0].blobs:
        b.placement = "p1"  # cam0 had to wait (an arm at the edge) when this was put in
    ds = decide([rs[0]], w.empties, w.cart, w.identifier, w.features, w.cfg, placement="p2")
    assert [d.kind for d in ds] == ["moved"] and len(w.cart.instances) == 1


def test_an_item_moved_by_a_hand_in_belongs_to_it(tmp_path):  # single-drops 61 s, every box named
    w = world(tmp_path)
    here, there = Item("red-box", 150, 100, seed=1), Item("red-box", 560, 330, seed=1)
    [d] = decide([settle(Scene(), Scene(items=[here]), w.cfg)[1]], w.empties, w.cart, w.identifier, w.features,
                 w.cfg, placement="p1")  # billed from cam1 only
    apply_decision(w.cart, d)
    # hand-in p2 takes it from one spot and puts it down at another; cam1 sees the move, cam0 is held back
    [d] = decide([settle(Scene(items=[here]), Scene(items=[there]), w.cfg)[1]], w.empties, w.cart, w.identifier,
                 w.features, w.cfg, placement="p2")
    assert d.kind == "moved"
    apply_decision(w.cart, d)
    r0 = settle(Scene(), Scene(items=[there]), w.cfg)[0]  # cam0's first look at it, after it waited
    for b in r0.blobs:
        b.placement = "p2"
    ds = decide([r0], w.empties, w.cart, w.identifier, w.features, w.cfg, placement="p2")
    assert [d.kind for d in ds] == ["moved"] and w.cart.count("red-box") == 1
