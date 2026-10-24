import json

from kartcv.trip import TripWatcher


class Get:
    def __init__(self, replies):
        self.replies, self.urls = list(replies), []

    def __call__(self, url, headers):
        self.urls.append((url, headers))
        r = self.replies.pop(0)
        if isinstance(r, Exception):
            raise r
        return r


def rows(tid):
    return 200, json.dumps([{"trip_id": tid}]).encode()


def test_first_seen_records_then_change_resets(tmp_path):
    resets = []
    g = Get([rows("t1"), rows("t1"), OSError("down"), (500, b""), (200, b"[]"), rows(None), rows("t2")])
    w = TripWatcher("https://x.supabase.co/", "k", "7", tmp_path / "trip.json", lambda: resets.append(1),
                    get=g, start_thread=False)
    assert w.poll_once() == "t1" and resets == []
    for _ in range(5):
        w.poll_once()
    assert resets == []
    w.poll_once()
    assert resets == [1] and json.loads((tmp_path / "trip.json").read_text()) == {"trip_id": "t2"}
    url, headers = g.urls[0]
    assert url == "https://x.supabase.co/rest/v1/carts?cart_id=eq.7&select=trip_id" and headers["apikey"] == "k"


def test_change_while_off_resets_at_startup(tmp_path):
    (tmp_path / "trip.json").write_text('{"trip_id": "old"}')
    resets = []
    w = TripWatcher("https://x", "k", "7", tmp_path / "trip.json", lambda: resets.append(1),
                    get=Get([rows("new")]), start_thread=False)
    w.poll_once()
    assert resets == [1]


def test_unexpected_errors_do_not_kill_the_watcher(tmp_path):  # review I3
    import http.client
    resets = []
    g = Get([http.client.BadStatusLine("x"), ValueError("bad url"), rows("t1")])
    w = TripWatcher("https://x", "k", "7", tmp_path / "trip.json", lambda: resets.append(1), get=g, start_thread=False)
    assert w.poll_once() is None and w.poll_once() is None and w.poll_once() == "t1"
