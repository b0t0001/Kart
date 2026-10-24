import numpy as np

from kartcv.synth import Item, Scene, Script, item_box, item_sprite

RED = Item("red-box", 300, 200, seed=1)


def changed(a, b):
    return (np.abs(a.astype(int) - b.astype(int)).sum(2) > 40).mean()


def test_two_distinct_views():
    a, b = Scene().render(0), Scene().render(1)
    assert a.shape == (720, 1280, 3) and changed(a, b) > 0.05


def test_item_visible_in_both_unless_hidden():
    empty, full = Scene(), Scene(items=[RED])
    assert changed(empty.render(0), full.render(0)) > 0.005 and changed(empty.render(1), full.render(1)) > 0.005
    hid = Scene(items=[RED], hidden={0: {"red-box"}})
    assert changed(empty.render(0), hid.render(0)) < 0.001 and changed(empty.render(1), hid.render(1)) > 0.005


def test_sprites_distinct():
    means = [item_sprite(s, 120, 90).reshape(-1, 3).mean(0) for s in (1, 2, 3)]
    assert min(np.linalg.norm(means[i] - means[j]) for i in range(3) for j in range(i + 1, 3)) > 40


def test_item_box_inside_frame():
    x, y, w, h = item_box(1, RED)
    assert 0 <= x and 0 <= y and x + w <= 1280 and y + h <= 720 and w > 40 and h > 30


def test_drop_timeline():
    sc = Script(Scene()).drop(RED)
    assert len(sc.ticks) == 25 and [i.item_id for i in sc.scene.items] == ["red-box"]
    ts = [t[0].ts for t in sc.ticks]
    assert np.allclose(np.diff(ts), 0.1)
    still = [t[0].image for t in sc.ticks[-15:]]
    assert max(changed(still[i], still[i + 1]) for i in range(14)) < 0.001
