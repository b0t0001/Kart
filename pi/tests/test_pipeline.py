from helpers import world

from kartcv.pipeline import Pipeline
from kartcv.sinks import MemorySink
from kartcv.synth import Item, Scene, Script

RED = Item("red-box", 300, 200, seed=1)
BLUE = Item("blue-can", 560, 330, seed=2)


def make(tmp_path, state="state"):
    w = world(tmp_path)
    sink = MemorySink()
    return Pipeline(w.cfg, [0, 1], w.identifier, w.features, [sink], tmp_path / state), sink


def run(p, script, start=0):
    out = []
    for tick in script.ticks[start:]:
        out += p.step(tick)
    return [(e.type, e.product_id) for e in out]


def test_first_run_resets_then_add_and_remove(tmp_path):
    p, sink = make(tmp_path)
    sc = Script(Scene()).still(1.0)
    assert run(p, sc) == [] and (tmp_path / "state/empty_cam0.jpg").exists()
    n = len(sc.ticks)
    sc.drop(RED)
    assert run(p, sc, n) == [("added", "red-box")]
    n = len(sc.ticks)
    sc.take("red-box")
    assert run(p, sc, n) == [("removed", "red-box")]
    assert sink.events[-1].method == "memory" and len(p.cart.instances) == 0
    assert sink.events[0].crops and all((tmp_path / c).exists() for c in sink.events[0].crops)


def test_logs_motion_then_settled(tmp_path, caplog):  # spec §14 milestone 2 check
    import logging
    p, _ = make(tmp_path)
    with caplog.at_level(logging.INFO, logger="kartcv.pipeline"):
        run(p, Script(Scene()).still(1.0).hand_pass())
    msgs = [r.getMessage() for r in caplog.records]
    assert "MOTION" in msgs and "SETTLED" in msgs and msgs.index("MOTION") < msgs.index("SETTLED")


def test_no_false_events(tmp_path):
    p, _ = make(tmp_path)
    sc = Script(Scene()).still(1.0).hand_pass().set(brightness=1.3).set(shift={0: (2, 1)}).set(shift={0: (60, 30)})
    assert run(p, sc) == []


def test_hand_rest_bills_nothing(tmp_path):  # Review Focus 1, review C1: not even an add+remove pair
    p, _ = make(tmp_path)
    assert run(p, Script(Scene()).still(1.0).hand_rest(1.5)) == [] and len(p.cart.instances) == 0


def test_hand_lingering_after_placing_bills_only_the_item(tmp_path):  # review C1
    p, _ = make(tmp_path)
    assert run(p, Script(Scene()).still(1.0).drop(RED, linger_s=1.5)) == [("added", "red-box")]
    assert len(p.cart.instances) == 1


def test_grab_pause_lift_removes_the_item(tmp_path):  # review C1: the shopper must not pay for it
    p, _ = make(tmp_path)
    sc = Script(Scene()).still(1.0).drop(RED)
    run(p, sc)
    n = len(sc.ticks)
    sc.take("red-box", linger_s=1.5)
    assert run(p, sc, n) == [("removed", "red-box")] and len(p.cart.instances) == 0


def test_hover_over_item_bills_nothing_new(tmp_path):  # review C1
    p, _ = make(tmp_path)
    sc = Script(Scene()).still(1.0).drop(Item("red-box", 340, 200, seed=1))
    run(p, sc)
    n = len(sc.ticks)
    sc.hand_rest(1.5)
    assert run(p, sc, n) == [] and p.cart.count("red-box") == 1


def test_armless_hand_unknown_is_resolved_when_it_leaves(tmp_path):  # review C1(d): no blocked checkout
    p, sink = make(tmp_path)
    run(p, Script(Scene(arm=False)).still(1.0).hand_rest(1.5))
    assert [(e.type, e.product_id) for e in sink.events] == [("added", None), ("removed", None)]
    assert sink.events[1].resolves_event_id == sink.events[0].event_id and len(p.cart.instances) == 0


def test_object_left_on_the_frame_edge_cannot_stall_billing(tmp_path):  # review C1: bounded waiting
    p, _ = make(tmp_path)
    sc = Script(Scene()).still(1.0).set(edge_object=True).drop(RED)  # e.g. a bag strap over the rim
    assert run(p, sc) == [("added", "red-box")]


def test_bump_or_lighting_drift_then_remove(tmp_path):  # Review Focus 4
    for i, change in enumerate([{"shift": {0: (60, 30)}}, {"brightness": 1.2}]):
        p, _ = make(tmp_path / str(i))
        sc = Script(Scene()).still(1.0).drop(RED).set(**change).take("red-box")
        assert run(p, sc)[-1] == ("removed", "red-box")


def test_nudge_two_items_hidden_stack(tmp_path):
    p, _ = make(tmp_path / "a")
    sc = Script(Scene()).still(1.0).drop(RED)
    run(p, sc)
    n = len(sc.ticks)
    sc.move("red-box", 150, 0)
    assert run(p, sc, n) == [] and p.cart.count("red-box") == 1

    p, _ = make(tmp_path / "b")
    assert sorted(run(p, Script(Scene()).still(1.0).drop_many([RED, BLUE]))) == \
        [("added", "blue-can"), ("added", "red-box")]

    p, sink = make(tmp_path / "c")
    run(p, Script(Scene(hidden={0: {"red-box"}})).still(1.0).drop(RED))
    assert sink.events[0].cameras == [1]

    p, _ = make(tmp_path / "d")
    big = Item("blue-can", 250, 150, w=300, h=220, seed=2)
    top = Item("red-box", 330, 210, seed=1)
    assert run(p, Script(Scene()).still(1.0).drop(big).drop(top).take("red-box")) == \
        [("added", "blue-can"), ("added", "red-box"), ("removed", "red-box")]


BAG = Item("green-bag", 300, 200, w=200, h=150, seed=3)  # a soft bag: it slumps after it's put down


def test_a_soft_item_slumping_in_place_is_not_billed_again(tmp_path):  # real cart: four-corners' almond bag
    p, _ = make(tmp_path)
    sc = Script(Scene()).still(1.0).drop(BAG).still(2.0)
    assert run(p, sc) == [("added", "green-bag")]
    box = next(iter(p.cart.instances.values())).views[0].box
    n = len(sc.ticks)
    sc.set(items=[Item("green-bag", 308, 214, w=214, h=136, seed=3)]).still(2.0)  # no hand: it just settles
    assert run(p, sc, n) == [] and len(p.cart.instances) == 1
    assert next(iter(p.cart.instances.values())).views[0].box != box  # memory follows it to its new shape


def test_a_different_item_laid_over_one_its_size_is_still_billed(tmp_path):
    p, _ = make(tmp_path)
    big = Item("blue-can", 250, 150, w=300, h=220, seed=2)
    cover = Item("green-bag", 255, 155, w=300, h=220, seed=3)
    sc = Script(Scene()).still(1.0).drop(big).still(1.0).drop(cover).still(2.0)
    assert run(p, sc) == [("added", "blue-can"), ("added", "green-bag")]


def test_a_second_unit_set_against_the_first_is_billed_not_taken_for_a_reveal(tmp_path):  # counting boxes
    p, _ = make(tmp_path)
    sc = Script(Scene()).still(1.0).drop(RED).still(1.0)
    run(p, sc)
    n = len(sc.ticks)
    # a hand puts the second box in right against the first, bumping it: one change covers both
    sc.hand_pass().set(items=[Item("red-box", 318, 200, seed=1), Item("red-box", 428, 200, seed=1)]).still(2.0)
    assert run(p, sc, n) == [("added", "red-box")] and p.cart.count("red-box") == 2


def test_lifting_out_something_that_was_in_the_empty_picture_bills_nothing(tmp_path):  # props-final 26 s
    p, _ = make(tmp_path)
    sc = Script(Scene(items=[RED])).still(1.0).take("red-box").still(2.0)  # it lay there at startup
    assert run(p, sc) == [] and len(p.cart.instances) == 0  # bare liner left behind is not an item
    n = len(sc.ticks)
    sc.drop(Item("blue-can", 300, 200, seed=2))  # and that spot still works for a real item
    assert run(p, sc, n) == [("added", "blue-can")]


def test_one_box_seen_in_two_pieces_is_one_unit(tmp_path):  # live 3-drop test: one Barilla box billed twice
    p, _ = make(tmp_path)
    # one flat box whose print cuts it in two for the cameras: two same-looking pieces close together
    pieces = [Item("red-box", 300, 200, w=110, h=90, seed=1), Item("red-box", 445, 200, w=110, h=90, seed=1)]
    sc = Script(Scene()).still(1.0).drop_many(pieces).still(2.0)
    assert run(p, sc) == [("added", "red-box")] and p.cart.count("red-box") == 1


def test_two_identical_items_put_in_together_far_apart_are_two_units(tmp_path):
    p, _ = make(tmp_path)
    sc = Script(Scene()).still(1.0).drop_many([Item("red-box", 120, 80, seed=1), Item("red-box", 600, 380, seed=1)])
    assert run(p, sc.still(2.0)) == [("added", "red-box")] * 2


def test_each_identical_box_a_hand_puts_in_is_billed(tmp_path):  # counting: three spaghetti boxes
    p, _ = make(tmp_path)
    sc = Script(Scene()).still(1.0)
    for x in (120, 330, 540):
        sc.drop(Item("red-box", x, 200, seed=1)).still(1.0)
    assert run(p, sc) == [("added", "red-box")] * 3


GHOST = Item("ghost", 560, 330, w=90, h=90, seed=4)  # something no enrolled product looks like, cam0 only


def _remove_red_while_cam0_glimpses(stays: bool):
    sc = Script(Scene()).still(1.0).drop(RED).still(1.0)
    sc.take("red-box").set(items=[GHOST], hidden={1: {"ghost"}}).still(1.5)  # as the box comes out
    if not stays:
        sc.set(items=[], hidden={})  # ...gone again before the recheck: a shadow, a sleeve, a crease
    return sc.still(5.0)


def test_a_lone_unknown_glimpsed_during_a_removal_is_held_and_dropped_if_it_goes(tmp_path):  # pasta run 1
    p, _ = make(tmp_path)
    assert run(p, _remove_red_while_cam0_glimpses(stays=False)) == [("added", "red-box"), ("removed", "red-box")]


def test_a_lone_unknown_that_stays_is_billed_after_the_recheck(tmp_path):
    p, _ = make(tmp_path)
    assert run(p, _remove_red_while_cam0_glimpses(stays=True)) == \
        [("added", "red-box"), ("removed", "red-box"), ("added", None)]


def _asked_cloud_pipeline(tmp_path, answer):
    from kartcv.identify.hybrid import HybridIdentifier
    w = world(tmp_path)

    class Cloud:  # Claude looks at whatever no enrolled photo matches
        def identify(self, crops):
            return answer

    ident = HybridIdentifier(w.gallery, Cloud(), w.catalog, w.cfg)
    sink = MemorySink()
    return Pipeline(w.cfg, [0, 1], ident, w.features, [sink], tmp_path / "state"), sink


def _cam0_only_ghost_appears():
    sc = Script(Scene()).still(1.0).drop(RED).still(1.0)
    return sc.set(items=[RED, GHOST], hidden={1: {"ghost"}}).still(6.0)  # cam1 sees nothing new there, ever


def test_a_lone_unknown_claude_looked_at_is_never_billed_if_the_other_camera_saw_nothing(tmp_path):  # run 4
    from kartcv.identify.cloud import CloudAnswer
    p, _ = _asked_cloud_pipeline(tmp_path, CloudAnswer(None, 0.4, "dark grey surface"))
    assert run(p, _cam0_only_ghost_appears()) == [("added", "red-box")]


def test_a_lone_unknown_is_still_billed_when_claude_could_not_answer(tmp_path):  # a timeout is no verdict
    from kartcv.identify.cloud import CloudAnswer
    p, _ = _asked_cloud_pipeline(tmp_path, CloudAnswer(None, 0.0, "error: timeout"))
    assert run(p, _cam0_only_ghost_appears()) == [("added", "red-box"), ("added", None)]


def _cam1_primary(tmp_path, blind=None):
    w = world(tmp_path)
    w.cfg.primary_cam = 1  # the wide top view decides; cam0 is the fallback
    if blind:
        w.cfg.blind_zone = {"0": blind}
    sink = MemorySink()
    return Pipeline(w.cfg, [0, 1], w.identifier, w.features, [sink], tmp_path / "state"), sink


HIDDEN = Item("blue-can", 560, 330, seed=2)  # cam1 can't see it (hidden={1: ...})


def test_with_cam1_primary_a_cam0_only_add_never_bills_alone(tmp_path):  # tonight: 8 of 11 cam0-only adds wrong
    p, _ = _cam1_primary(tmp_path)
    assert run(p, Script(Scene(hidden={1: {"blue-can"}})).still(1.0).drop(HIDDEN).still(5.0)) == []


def test_a_cam0_only_add_in_cam1s_blind_zone_bills(tmp_path):
    from kartcv.synth import CAM_SIZE, item_box
    x, y, w, h = item_box(0, HIDDEN, pad=0.3)
    W, H = CAM_SIZE
    zone = [[x / W, y / H], [(x + w) / W, y / H], [(x + w) / W, (y + h) / H], [x / W, (y + h) / H]]
    p, _ = _cam1_primary(tmp_path, blind=zone)
    assert run(p, Script(Scene(hidden={1: {"blue-can"}})).still(1.0).drop(HIDDEN).still(5.0)) == [("added", "blue-can")]


def test_cam0s_early_view_waits_for_cam1_and_joins_its_item(tmp_path):  # take 1: cam1 still held the jar
    p, _ = _cam1_primary(tmp_path)
    sc = Script(Scene(hidden={1: {"blue-can"}})).still(1.0).drop(HIDDEN).still(1.5)
    sc.set(hidden={}).still(5.0)  # cam1 sees it a moment later (it was behind the arm)
    assert run(p, sc) == [("added", "blue-can")]
    [inst] = p.cart.instances.values()
    assert set(inst.views) == {0, 1}


def test_an_arm_filling_cam0s_view_is_not_baked_into_its_picture(tmp_path):  # "65% of the view changed"
    import numpy as np
    from kartcv.sources import Frame
    p, sink = make(tmp_path)
    sc = Script(Scene()).still(1.0).drop(RED).still(1.0)
    run(p, sc)
    before = p.references[0].copy()
    last = sc.ticks[-1]
    t0 = max(f.ts for f in last.values())
    sleeve = np.full_like(last[0].image, (90, 40, 20))  # an arm right in front of cam0 fills its view
    ticks = [{0: Frame(sleeve if i < 15 else last[0].image, t0 + 0.1 * (i + 1), 0),
              1: Frame(last[1].image, t0 + 0.1 * (i + 1), 1)} for i in range(60)]
    for t in ticks[:15]:
        p.step(t)
    assert np.array_equal(p.references[0], before)  # judged while it was there: its picture kept
    for t in ticks[15:]:
        p.step(t)
    assert sink.events[-1].type == "added" and len(sink.events) == 1 and p.cart.count("red-box") == 1


def test_reset_restart_and_missing_camera(tmp_path):
    p, _ = make(tmp_path)
    sc = Script(Scene()).still(1.0).drop(RED)
    run(p, sc)
    p2, _ = make(tmp_path)  # restart, same state dir
    assert p2.cart.count("red-box") == 1
    n = len(sc.ticks)
    sc.take("red-box")
    assert run(p2, sc, n) == [("removed", "red-box")]
    n = len(sc.ticks)
    sc.drop(RED)
    run(p2, sc, n)
    p2.request_reset()
    n = len(sc.ticks)
    sc.still(0.5)
    assert run(p2, sc, n) == [] and len(p2.cart.instances) == 0

    p3, _ = make(tmp_path / "m")
    sc = Script(Scene()).still(1.0).drop(RED)
    for t in sc.ticks:
        t[1] = None
    assert run(p3, sc) == [("added", "red-box")]


def test_event_reaches_sinks_before_cart_memory_changes(tmp_path):  # review I6: crash-safe ordering
    seen = []

    class Probe:
        def send(self, ev):
            seen.append((ev.type, len(p.cart.instances)))

        def close(self):
            pass

    p, _ = make(tmp_path)
    p.sinks.append(Probe())
    sc = Script(Scene()).still(1.0).drop(RED).take("red-box")
    run(p, sc)
    assert seen == [("added", 0), ("removed", 1)]  # memory changes only after the event is safely queued


def test_camera_dropout_does_not_rebill(tmp_path):  # review C2
    p, _ = make(tmp_path)
    sc = Script(Scene()).still(1.0)
    n0 = len(sc.ticks)
    sc.drop(RED)
    for t in sc.ticks[n0:]:
        t[1] = None  # cam1 out while RED goes in
    sc.still(1.0).drop(BLUE)
    assert sorted(run(p, sc)) == [("added", "blue-can"), ("added", "red-box")]
    assert p.cart.count("red-box") == 1


def test_white_balance_drift_then_remove(tmp_path):  # review I2: auto white balance shifts color
    p, _ = make(tmp_path)
    sc = Script(Scene()).still(1.0).drop(RED).set(tint=(0.85, 1.0, 1.18)).take("red-box")
    assert run(p, sc)[-1] == ("removed", "red-box") and len(p.cart.instances) == 0


def test_empty_picture_refreshes_while_cart_is_empty(tmp_path):  # review I2
    p, _ = make(tmp_path)
    sc = Script(Scene()).still(1.0)
    run(p, sc)
    before = p.empties[0].astype(float).mean(axis=(0, 1))
    n = len(sc.ticks)
    sc.set(tint=(0.9, 1.0, 1.12)).hand_pass()  # drift is too slow to count as motion; the next settle catches it
    assert run(p, sc, n) == []
    after = p.empties[0].astype(float).mean(axis=(0, 1))
    assert abs(after[2] - before[2]) > 5  # the red channel moved with the new light


def make_roi(tmp_path):
    from kartcv.synth import mat_roi
    p, sink = make(tmp_path)
    p.cfg.roi = {"0": mat_roi(0), "1": mat_roi(1)}
    p.apply_roi()
    return p, sink


def test_rolling_cart_bills_nothing_and_never_realigns(tmp_path):  # real-cart bug
    p, _ = make_roi(tmp_path)
    sc = Script(Scene()).still(1.0).drop(RED)
    for dx in (15, 40, 70, 110):  # the room slides past the mesh while the cart is pushed
        sc.set(room_shift=(dx, dx // 3))
    sc.take("red-box")
    assert run(p, sc) == [("added", "red-box"), ("removed", "red-box")] and len(p.cart.instances) == 0


def test_big_camera_shift_is_disturbed_and_never_realigns_memory(tmp_path):  # request (b)
    p, _ = make(tmp_path)
    sc = Script(Scene()).still(1.0).drop(RED)
    run(p, sc)
    boxes = {c: v.box for c, v in next(iter(p.cart.instances.values())).views.items()}
    n = len(sc.ticks)
    sc.set(shift={0: (60, 30)})
    assert run(p, sc, n) == []
    assert {c: v.box for c, v in next(iter(p.cart.instances.values())).views.items()} == boxes
    assert 0 in p.status()["camera_moved"]


TALL = Item("red-box", 300, 200, seed=1, tall=900)  # an upright bottle: reaches the top edge of both frames


def test_tall_item_reaching_the_top_edge_is_billed_and_removed(tmp_path):  # real-cart: the Tide bottle
    from kartcv.changes import detect_changes
    cfg = make(tmp_path / "x")[0].cfg
    for c in (0, 1):  # in BOTH cameras it looks exactly like an arm reaching in from the edge
        r = detect_changes(c, Scene().render(c, 1), Scene(items=[TALL]).render(c, 2), cfg)
        assert r.blobs and all(b.edge for b in r.blobs)
    p, sink = make(tmp_path)
    sc = Script(Scene()).still(1.0).drop(TALL).still(4.0)
    assert [t for t, _ in run(p, sc)] == ["added"]
    n = len(sc.ticks)
    sc.take("red-box").still(4.0)
    assert [t for t, _ in run(p, sc, n)] == ["removed"]
    assert sink.events[0].product_id == sink.events[1].product_id and len(p.cart.instances) == 0


def test_a_tall_item_judged_at_the_recheck_reaches_claude_whole(tmp_path):  # real cart: the almond bag, cam0
    from kartcv.synth import mat_roi
    w = world(tmp_path)
    w.cfg.roi = {"0": mat_roi(0), "1": mat_roi(1)}
    p = Pipeline(w.cfg, [0, 1], w.identifier, w.features, [MemorySink()], tmp_path / "state")
    tall = Item("red-box", 300, 30, seed=1, tall=900)  # at the far edge of the floor, up to the top of the frame
    added = []
    for tick in Script(Scene()).still(1.0).drop(tall).still(4.0).ticks:
        p.step(tick)
        added += [b for d in p.last_decisions if d.kind == "added" for b in d.blobs]
    [b0] = [b for b in added if b.cam == 0]
    assert b0.edge and b0.box[1] > 40 and b0.ident_box[1] == 0  # judged against the true before-picture


def test_long_hand_rest_nets_zero_and_resolves(tmp_path):  # a hand left still for longer than the recheck
    p, sink = make(tmp_path)
    run(p, Script(Scene()).still(1.0).hand_rest(5.0).still(4.0))
    assert len(p.cart.instances) == 0
    adds = [e for e in sink.events if e.type == "added"]
    rems = [e for e in sink.events if e.type == "removed"]
    assert len(adds) == len(rems) and all(e.product_id is None for e in adds)
    assert {e.resolves_event_id for e in rems} == {e.event_id for e in adds}


def test_a_shift_disturbed_settle_keeps_the_old_reference(tmp_path):  # a false alarm must not bake in a new view
    import numpy as np
    p, _ = make(tmp_path)
    sc = Script(Scene()).still(1.0).drop(RED)
    run(p, sc)
    before = p.references[0].copy()
    n = len(sc.ticks)
    sc.set(shift={0: (60, 30)})
    run(p, sc, n)
    assert np.array_equal(p.references[0], before) and 0 in p.status()["camera_moved"]
    n = len(sc.ticks)
    sc.set(shift={}).take("red-box")  # the knock was transient; the removal is still seen
    assert run(p, sc, n) == [("removed", "red-box")]


def _slow_cloud_pipeline(tmp_path, seconds=1.5):
    import time
    from kartcv.identify.cloud import CloudAnswer
    from kartcv.identify.hybrid import HybridIdentifier
    w = world(tmp_path)

    class SlowCloud:  # like Claude over a phone hotspot
        def identify(self, crops):
            time.sleep(seconds)
            return CloudAnswer("green-bag", 0.9, "slow answer")

    sink = MemorySink()
    ident = HybridIdentifier(None, SlowCloud(), w.catalog, w.cfg)  # no gallery: every add goes to the cloud
    return Pipeline(w.cfg, [0, 1], ident, w.features, [sink], tmp_path / "state", background=True), sink


def test_a_second_add_during_a_slow_cloud_call_is_still_seen(tmp_path):  # real Pi: Claude froze the loop
    import time
    slow = 1.5

    def feed(seconds, name):
        p, sink = _slow_cloud_pipeline(tmp_path / name, seconds)
        t0 = time.perf_counter()
        for tick in Script(Scene()).still(1.0).drop(RED).drop(BLUE).ticks:
            p.step(tick)
        fed = time.perf_counter() - t0
        p.drain(timeout=10)
        p.close()
        return fed, sink, p

    baseline, _, _ = feed(0.0, "instant")  # just watching: ~0.5 s on a Mac, ~2.2 s on the Pi 4
    fed, sink, p = feed(slow, "slow")
    assert fed < baseline + slow  # the loop kept watching while Claude was busy (inline: + 2 calls)
    assert [e.type for e in sink.events] == ["added", "added"] and len(p.cart.instances) == 2


def test_background_judging_keeps_order_add_then_remove(tmp_path):
    p, sink = _slow_cloud_pipeline(tmp_path)
    for tick in Script(Scene()).still(1.0).drop(RED).take("red-box").ticks:
        p.step(tick)
    p.drain(timeout=10)
    p.close()
    assert [(e.type, e.product_id) for e in sink.events] == [("added", "green-bag"), ("removed", "green-bag")]
    assert len(p.cart.instances) == 0


def _counting_pipeline(tmp_path, flag):
    from kartcv.identify.cloud import CloudAnswer
    from kartcv.identify.hybrid import HybridIdentifier
    w = world(tmp_path)
    w.cfg.claude_count = flag

    class ThreeCloud:  # Claude sees three identical units in one clump
        def identify(self, crops):
            return CloudAnswer("green-bag", 0.9, "three bags", 3)

    sink = MemorySink()
    ident = HybridIdentifier(None, ThreeCloud(), w.catalog, w.cfg)
    return Pipeline(w.cfg, [0, 1], ident, w.features, [sink], tmp_path / "state"), sink


def test_claude_count_bills_each_unit_in_a_clump_and_removes_them_all(tmp_path):  # flag on
    p, sink = _counting_pipeline(tmp_path, True)
    sc = Script(Scene()).still(1.0).drop(RED)
    assert run(p, sc) == [("added", "green-bag")] * 3
    assert len({e.event_id for e in sink.events}) == 3 and len(p.cart.instances) == 3
    n = len(sc.ticks)
    sc.take("red-box")
    assert run(p, sc, n) == [("removed", "green-bag")] * 3 and len(p.cart.instances) == 0


def test_claude_count_off_bills_one_unit(tmp_path):  # flag off: the stable behavior
    p, _ = _counting_pipeline(tmp_path, False)
    assert run(p, Script(Scene()).still(1.0).drop(RED)) == [("added", "green-bag")]


def test_a_wide_angle_camera_with_barrel_distortion_works_in_the_corners(tmp_path):  # locked layout: cam1 is a fisheye
    from kartcv.synth import mat_roi
    fe = {1: 0.35}
    p, _ = make(tmp_path)
    p.cfg.roi = {"0": mat_roi(0), "1": mat_roi(1, fisheye=0.35, per_edge=8)}  # a polygon around the curved floor edge
    p.apply_roi()
    corner = Item("red-box", 660, 390, seed=1)  # where the lens shrinks and bends things most
    assert run(p, Script(Scene(fisheye=fe)).still(1.0).drop(corner).take("red-box")) == \
        [("added", "red-box"), ("removed", "red-box")]


def _cloud_pipeline(tmp_path, answer, **cfg):
    from kartcv.identify.hybrid import HybridIdentifier
    w = world(tmp_path)
    for k, v in cfg.items():
        setattr(w.cfg, k, v)
    calls = []

    class Cloud:
        def identify(self, crops):
            calls.append(len(crops))
            return answer

    sink = MemorySink()
    p = Pipeline(w.cfg, [0, 1], HybridIdentifier(None, Cloud(), w.catalog, w.cfg), w.features, [sink], tmp_path / "state")
    return p, sink, calls


def test_personal_items_are_remembered_but_never_billed(tmp_path):  # purse, phone, jacket, own bag
    from kartcv.identify.cloud import CloudAnswer
    p, sink, _ = _cloud_pipeline(tmp_path, CloudAnswer(None, 0.9, "black leather purse", personal=True),
                                 personal_items=True)
    sc = Script(Scene()).still(1.0).drop(RED)
    assert run(p, sc) == [] and len(p.cart.instances) == 1 and next(iter(p.cart.instances.values())).personal
    n = len(sc.ticks)
    sc.take("red-box")
    assert run(p, sc, n) == [] and len(p.cart.instances) == 0 and sink.events == []


def test_thats_mine_marks_an_unknown_personal_so_its_removal_is_silent(tmp_path):
    from kartcv.identify.cloud import CloudAnswer
    p, sink, _ = _cloud_pipeline(tmp_path, CloudAnswer(None, 0.3, "a phone?"))
    sc = Script(Scene()).still(1.0).drop(RED)
    assert run(p, sc) == [("added", None)]
    assert p.mark_personal(sink.events[0].event_id) is True and p.mark_personal("no-such-event") is False
    n = len(sc.ticks)
    sc.take("red-box")
    assert run(p, sc, n) == [] and len(p.cart.instances) == 0


def test_an_edge_origin_blob_never_goes_to_claude_and_leaves_no_crops(tmp_path):  # a child's hand, held still
    from kartcv.identify.cloud import CloudAnswer
    p, sink, calls = _cloud_pipeline(tmp_path, CloudAnswer("green-bag", 0.9, "bag"), edge_privacy=True)
    run(p, Script(Scene()).still(1.0).hand_rest(5.0))  # arm-like, still past the recheck
    assert calls == []  # nothing reached Claude
    adds = [e for e in sink.events if e.type == "added"]
    assert adds and all(e.product_id is None and e.crops == [] for e in adds)
    assert not any((tmp_path / "state" / "crops").glob(f"{adds[0].event_id}_*"))


def test_edge_privacy_off_restores_claude_for_rechecked_blobs(tmp_path):
    from kartcv.identify.cloud import CloudAnswer
    p, sink, calls = _cloud_pipeline(tmp_path, CloudAnswer("green-bag", 0.9, "bag"), edge_privacy=False)
    run(p, Script(Scene()).still(1.0).drop(TALL).still(4.0))
    assert calls and sink.events[0].product_id == "green-bag"
