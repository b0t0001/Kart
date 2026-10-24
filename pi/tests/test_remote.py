import json

import cv2
import numpy as np

from kartcv.remote import discover_cams, fetch_tick


def jpeg(v):
    ok, buf = cv2.imencode(".jpg", np.full((72, 128, 3), v, np.uint8))
    return buf.tobytes()


class Get:
    def __init__(self, routes):
        self.routes, self.urls = routes, []

    def __call__(self, url, headers):
        self.urls.append(url)
        path = url.split("8080", 1)[1]
        r = self.routes.get(path.split("?")[0])
        if isinstance(r, Exception):
            raise r
        return r or (404, b"")


def test_discover_cams_from_status():
    g = Get({"/status": (200, json.dumps({"cameras": {"0": {"last_ts": 1.0}, "1": {"last_ts": None}}}).encode())})
    assert discover_cams("http://smartcart.local:8080", get=g) == [0, 1]


def test_fetch_tick_one_frame_per_camera_same_timestamp():
    g = Get({"/cam/0.jpg": (200, jpeg(50)), "/cam/1.jpg": (404, b"")})
    tick = fetch_tick("http://smartcart.local:8080", [0, 1], ts=12.5, get=g)
    assert tick[0].ts == 12.5 and tick[0].cam == 0 and tick[0].image.shape == (72, 128, 3) and tick[1] is None
    assert all("q=95" in u for u in g.urls)


def test_fetch_tick_survives_network_errors():
    g = Get({"/cam/0.jpg": OSError("wifi"), "/cam/1.jpg": (200, b"not a jpeg")})
    assert fetch_tick("http://x:8080", [0, 1], ts=1.0, get=g) == {0: None, 1: None}
