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


def test_long_hand_rest_nets_zero_and_resolves(tmp_path):  # a hand left still for longer than the recheck
    p, sink = make(tmp_path)
    run(p, Script(Scene()).still(1.0).hand_rest(5.0).still(4.0))
    assert len(p.cart.instances) == 0
    adds = [e for e in sink.events if e.type == "added"]
    rems = [e for e in sink.events if e.type == "removed"]
    assert len(adds) == len(rems) and all(e.product_id is None for e in adds)
    assert {e.resolves_event_id for e in rems} == {e.event_id for e in adds}
