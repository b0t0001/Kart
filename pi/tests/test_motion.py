from kartcv.motion import MotionDetector, SettleTracker
from kartcv.synth import Item, Scene, Script


def test_still_frames_no_motion():
    md = MotionDetector()
    assert not any(md.update(t[0].image) for t in Script(Scene()).still(1.0).ticks)


def test_hand_motion_detected():
    md = MotionDetector()
    flags = [md.update(t[0].image) for t in Script(Scene()).drop(Item("red-box", 300, 200, seed=1)).ticks]
    assert sum(flags[:10]) >= 3 and not any(flags[-14:])


def test_settle_fires_once_after_quiet():
    st = SettleTracker(1.0)
    steps = [(0.0, {0: True, 1: False}), (0.5, {0: False, 1: False}), (0.99, {0: False, 1: False}),
             (1.0, {0: False, 1: False}), (1.5, {0: False, 1: False})]
    assert [st.update(t, m) for t, m in steps] == [False, False, False, True, False]


def test_no_settle_without_motion_and_either_camera_restarts_clock():
    st = SettleTracker(1.0)
    assert not any(st.update(t / 10, {0: False, 1: False}) for t in range(50))
    st.update(0.0, {0: True, 1: False})
    st.update(0.8, {0: False, 1: True})
    assert st.update(1.0, {0: False, 1: False}) is False and st.update(1.8, {0: False, 1: False}) is True


def test_missing_camera_does_not_block():
    st = SettleTracker(1.0)
    st.update(0.0, {0: True})
    assert st.update(1.0, {0: False}) is True


def test_motion_outside_the_floor_roi_is_ignored():
    from kartcv.synth import mat_roi
    md = MotionDetector(roi=mat_roi(0))
    md.update(Scene().render(0, 1))
    assert md.update(Scene(room_shift=(40, 25)).render(0, 2)) is False
    assert md.update(Scene(room_shift=(40, 25), hand=(400, 250)).render(0, 3)) is True
