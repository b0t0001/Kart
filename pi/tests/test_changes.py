from kartcv.changes import detect_changes
from kartcv.config import Config
from kartcv.synth import Item, Scene, project

CFG = Config()
RED = Item("red-box", 300, 200, seed=1)
BLUE = Item("blue-can", 560, 330, seed=2)


def run(before, after, cam=0):
    return detect_changes(cam, before.render(cam, noise_seed=1), after.render(cam, noise_seed=2), CFG)


def test_identical_is_none():
    assert run(Scene(), Scene()).status == "none"


def test_added_item_one_blob_around_it():
    r = run(Scene(), Scene(items=[RED]))
    assert r.status == "blobs" and len(r.blobs) == 1
    x, y, w, h = r.blobs[0].box
    u, v = project(0, (RED.x + RED.w // 2, RED.y + RED.h // 2))
    assert x <= u <= x + w and y <= v <= y + h and r.blobs[0].after.shape[:2] == (h, w)


def test_two_separated_items_two_blobs():
    assert len(run(Scene(), Scene(items=[RED, BLUE])).blobs) == 2


def test_lighting_shadow_wobble_tiny_are_none():
    assert run(Scene(), Scene(brightness=1.3)).status == "none"
    assert run(Scene(), Scene(shade=0.25)).status == "none"  # Review Focus 3
    assert run(Scene(), Scene(shift={0: (2, 1)})).status == "none"
    assert run(Scene(), Scene(items=[Item("dot", 300, 200, w=12, h=12, seed=1)])).status == "none"


def test_bump_and_color_cast_are_disturbed():
    r = run(Scene(), Scene(shift={0: (60, 30)}))
    assert r.status == "disturbed" and r.blobs == [] and abs(r.shift[0] - 60) <= 3 and abs(r.shift[1] - 30) <= 3
    assert run(Scene(), Scene(tint=(0.6, 1.0, 1.5))).status == "disturbed"
