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


def test_hand_rest_nets_zero(tmp_path):  # Review Focus 1
    p, _ = make(tmp_path)
    ev = run(p, Script(Scene()).still(1.0).hand_rest(1.5))
    assert len(p.cart.instances) == 0
    assert sum(t == "added" for t, _ in ev) == sum(t == "removed" for t, _ in ev)


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
