import json
import threading
import urllib.error
import urllib.request

import numpy as np

from kartcv.server import ControlServer


def get(port, path, method="GET"):
    req = urllib.request.Request(f"http://127.0.0.1:{port}{path}", method=method,
                                 data=b"" if method == "POST" else None)
    try:
        with urllib.request.urlopen(req, timeout=2) as r:
            return r.status, r.headers.get("Content-Type"), r.read()
    except urllib.error.HTTPError as e:
        return e.code, None, b""


def test_status_reset_and_no_debug():
    flag = threading.Event()
    s = ControlServer(0, lambda: {"items": 2, "state": "idle"}, flag.set)
    s.start()
    try:
        code, _, body = get(s.port, "/status")
        assert code == 200 and json.loads(body)["items"] == 2
        assert get(s.port, "/reset", "POST")[0] == 200 and flag.is_set()
        assert get(s.port, "/")[0] == 404 and get(s.port, "/cam/0.jpg")[0] == 404
    finally:
        s.stop()


def test_debug_view(tmp_path):
    (tmp_path / "abc_cam0.jpg").write_bytes(b"\xff\xd8\xff")
    s = ControlServer(0, lambda: {"last_events": []}, lambda: None,
                      frames_fn=lambda: {0: np.zeros((72, 128, 3), np.uint8)}, debug_view=True, crops_dir=tmp_path)
    s.start()
    try:
        code, ctype, body = get(s.port, "/")
        assert code == 200 and "text/html" in ctype and b"/cam/0.jpg" in body
        code, ctype, _ = get(s.port, "/cam/0.jpg")
        assert code == 200 and ctype == "image/jpeg"
        assert get(s.port, "/cam/5.jpg")[0] == 404 and get(s.port, "/crops/abc_cam0.jpg")[0] == 200
        assert get(s.port, "/crops/..%2Fsecret.jpg")[0] == 404
    finally:
        s.stop()
