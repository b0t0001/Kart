import time

import cv2
import numpy as np

from kartcv.sources import Frame, FrameListSource, LiveCamera, iter_ticks, load_recording, save_tick


def img(v):
    return np.full((72, 128, 3), v, np.uint8)


def test_frame_list_source_in_order_then_none():
    s = FrameListSource(0, [Frame(img(1), 0.0, 0), Frame(img(2), 0.1, 0)])
    assert s.read().ts == 0.0 and s.read().ts == 0.1 and s.read() is None and s.exhausted


def test_recording_roundtrip(tmp_path):
    for i in range(3):
        save_tick(tmp_path, {0: Frame(img(10 * i), i * 0.1, 0), 1: Frame(img(20 * i), i * 0.1, 1)})
    srcs = load_recording(tmp_path)
    assert [s.cam for s in srcs] == [0, 1]
    ticks = list(iter_ticks(srcs))
    assert len(ticks) == 3 and abs(ticks[2][1].ts - 0.2) < 1e-6 and ticks[2][1].image.shape == (72, 128, 3)


def test_live_camera_bad_source_is_unhealthy_not_crashing():
    cam = LiveCamera(0, "/dev/does-not-exist", 1280, 720, 30)
    time.sleep(0.3)
    assert cam.read() is None and not cam.healthy
    cam.close()


class FakeCap:
    def __init__(self, src):
        self.props = {}

    def isOpened(self):
        return True

    def set(self, prop, val):
        self.props[prop] = val
        return True

    def read(self):
        time.sleep(0.01)
        return True, np.full((720, 1280, 3), 100, np.uint8)

    def release(self):
        pass


def test_live_camera_warmup_and_no_buffersize():
    caps = []
    cam = LiveCamera(0, "/dev/fake", 1280, 720, 30, warmup_s=0.3,
                     capture_factory=lambda s: caps.append(FakeCap(s)) or caps[-1])
    time.sleep(0.1)
    assert cam.read() is None  # still warming up
    time.sleep(0.4)
    f = cam.read()
    assert f is not None and f.image.shape == (720, 1280, 3) and cam.healthy
    assert cv2.CAP_PROP_BUFFERSIZE not in caps[0].props and cv2.CAP_PROP_FOURCC in caps[0].props
    cam.close()
