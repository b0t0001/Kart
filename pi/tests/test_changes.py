from kartcv.changes import detect_changes
from kartcv.config import Config
from kartcv.synth import Item, Scene, item_box, mat_roi, project

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
    # a strong color cast is cancelled by per-channel gain matching (or, if not, is "disturbed"): never blobs
    assert run(Scene(), Scene(tint=(0.6, 1.0, 1.5))).status in ("none", "disturbed")



def roi_cfg():
    from kartcv.synth import mat_roi
    return Config(roi={"0": mat_roi(0), "1": mat_roi(1)})


def test_room_moving_behind_the_mesh_is_ignored_with_a_floor_roi():  # real-cart bug: rolling
    after = Scene(room_shift=(40, 25))
    assert run(Scene(), after).status != "none"  # without a mask the room's motion is a "change"
    cfg = roi_cfg()
    r = detect_changes(0, Scene().render(0, 1), after.render(0, 2), cfg, roi=cfg.roi["0"])
    assert r.status == "none" and abs(r.shift[0]) < 3 and abs(r.shift[1]) < 3


def test_crops_are_gray_outside_the_floor():  # privacy: nothing beyond the basket goes to Claude
    cfg = roi_cfg()
    edge_item = Item("red-box", 0, 200, seed=1)  # lying against the mat's edge
    r = detect_changes(0, Scene().render(0, 1), Scene(items=[edge_item]).render(0, 2), cfg, roi=cfg.roi["0"])
    [b] = r.blobs
    gray = (b.after == 128).all(axis=2)
    assert gray.any() and not gray.all()


def test_item_against_the_wall_is_an_item_but_an_arm_over_the_rim_is_an_intrusion():
    cfg = roi_cfg()
    edge_item = Item("red-box", 0, 200, seed=1)
    r = detect_changes(0, Scene().render(0, 1), Scene(items=[edge_item]).render(0, 2), cfg, roi=cfg.roi["0"])
    assert [b.edge for b in r.blobs] == [False]
    r = detect_changes(0, Scene().render(0, 1), Scene(hand=(400, 250)).render(0, 2), cfg, roi=cfg.roi["0"])
    assert r.blobs and all(b.edge for b in r.blobs)
    r = detect_changes(0, Scene().render(0, 1), Scene(hand=(400, 250)).render(0, 2), CFG)  # no ROI: frame edge
    assert r.blobs and all(b.edge for b in r.blobs)


def _texture():
    import cv2
    import numpy as np
    rng = np.random.default_rng(0)  # coarse, high-contrast structure, like printed packaging
    return cv2.resize((rng.random((36, 64, 3)) * 255).astype(np.uint8), (1280, 720), interpolation=cv2.INTER_CUBIC)


def test_a_big_object_is_not_mistaken_for_a_camera_shift():  # real cart: the Tide bottle filled cam0's floor
    import numpy as np
    ref = _texture()
    part = ref.copy()  # only a region "moves" (like a big printed label that phase correlation latches onto)
    part[100:600, 200:1000] = np.roll(ref, (30, 80), axis=(0, 1))[100:600, 200:1000]
    assert detect_changes(0, ref, part, CFG).status == "blobs"
    r = detect_changes(0, ref, np.roll(ref, (30, 80), axis=(0, 1)), CFG)  # the whole view moved: a real knock
    assert r.status == "disturbed" and abs(r.shift[0] - 80) <= 3


def test_gain_matching_uses_the_unchanged_floor_only():  # a big colored item must not skew the colors
    import numpy as np
    from kartcv.changes import lab_distance, match_gain
    floor = np.full((100, 100, 3), (150, 170, 190), np.uint8)
    cur = np.clip(floor.astype(float) * 1.15, 0, 255).astype(np.uint8)  # the camera's exposure rose
    cur[:, :70] = (20, 90, 230)  # a big orange item covers 70 % of the floor
    unchanged = np.zeros((100, 100), np.uint8)
    unchanged[:, 70:] = 1
    skewed = float(lab_distance(match_gain(cur, floor)[:, 70:], floor[:, 70:]).mean())
    right = float(lab_distance(match_gain(cur, floor, unchanged)[:, 70:], floor[:, 70:]).mean())
    assert right < 3 < skewed


def test_sunlight_patch_is_lighting_not_an_item():  # real cart: sun stripes through blinds brightened
    cfg = roi_cfg()
    sunny = Scene(sun=(420, 0, 220, 300, 1.45))  # reaches the top edge, like the real stripe
    assert detect_changes(1, Scene().render(1, 1), sunny.render(1, 2), cfg, roi=cfg.roi["1"]).status == "none"


def test_an_items_long_shadow_is_not_part_of_the_item():  # real cart: the apple's shadow reached the frame edge
    cfg = roi_cfg()
    apple = Item("red-box", 330, 120, seed=1, shadow=600)
    r = detect_changes(1, Scene().render(1, 1), Scene(items=[apple]).render(1, 2), cfg, roi=cfg.roi["1"])
    assert len(r.blobs) == 1 and not r.blobs[0].edge  # just the item, billed now, not held back as an "arm"


def test_portrait_frames_are_compared_without_squashing():
    import cv2
    a = cv2.rotate(Scene().render(0, 1), cv2.ROTATE_90_CLOCKWISE)  # 1280 tall, 720 wide
    b = cv2.rotate(Scene(items=[RED]).render(0, 2), cv2.ROTATE_90_CLOCKWISE)
    r = detect_changes(0, a, b, CFG)
    assert r.status == "blobs" and len(r.blobs) == 1
    x, y, w, h = r.blobs[0].box
    rh, rw = RED.h, RED.w  # in this view the item is rotated too: taller than wide
    assert h > w and 0 <= x and x + w <= 720 and y + h <= 1280


def test_working_size_follows_the_frame_orientation():
    from kartcv.changes import work_size
    assert work_size((720, 1280, 3), (640, 360)) == (640, 360)
    assert work_size((1280, 720, 3), (640, 360)) == (360, 640)  # portrait: same detail both ways, no squash


def test_a_tall_items_identification_crop_shows_it_above_the_floor():  # real cart: the almond bag was gray
    import numpy as np
    cfg = Config(roi={"0": mat_roi(0)})
    tall = Item("red-box", 300, 30, seed=1, tall=60)  # at the far edge: its body rises past the floor outline
    before, after = Scene().render(0, 1), Scene(items=[tall]).render(0, 2)
    [b] = detect_changes(0, before, after, cfg, roi=cfg.roi["0"]).blobs
    top = item_box(0, tall, pad=0.0)[1] - tall.tall  # where its body ends in the image
    x, y, w, h = b.box
    assert not b.edge and y > top  # detection still only sees the part on the floor
    ix, iy, iw, ih = b.ident_box  # identification reaches up over the item's own body...
    assert (ix, iw) == (x, w) and iy + ih == y + h and top - 0.25 * h <= iy <= top
    assert np.array_equal(b.ident, after[iy:iy + ih, ix:ix + iw])  # ...unmasked, and no higher than it


def test_identification_crops_stay_inside_the_floor_box_for_a_flat_item():
    cfg = Config(roi={"0": mat_roi(0)})
    [b] = detect_changes(0, Scene().render(0, 1), Scene(items=[RED]).render(0, 2), cfg, roi=cfg.roi["0"]).blobs
    assert b.ident_box == b.box  # nothing rises above the floor: Claude gets the same box as before
