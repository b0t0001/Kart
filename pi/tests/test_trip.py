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


def test_personal_resolutions_are_applied_once_and_the_cursor_survives_restarts(tmp_path):  # "That's mine"
    from kartcv.trip import PersonalWatcher
    marked = []
    rows = [{"event_id": "e1", "resolved_at": "2026-10-24T10:00:01.5+00:00"},
            {"event_id": "e2", "resolved_at": "2026-10-24T10:00:05+00:00"}]
    g = Get([(200, json.dumps(rows).encode()), (200, b"[]"), OSError("down"),
             (400, b'{"message":"column cart_events.resolution does not exist"}')])
    w = PersonalWatcher("https://x.supabase.co/", "k", "7", tmp_path / "personal.json", marked.append,
                        get=g, start_thread=False)
    assert w.poll_once() == 2 and marked == ["e1", "e2"]
    first = g.urls[0][0]
    assert first.startswith("https://x.supabase.co/rest/v1/cart_events?") and g.urls[0][1]["apikey"] == "k"
    assert "cart_id=eq.7" in first and "resolution=eq.personal" in first and "order=resolved_at.asc" in first
    assert w.poll_once() == 0 and "resolved_at=gt.2026-10-24T10%3A00%3A05%2B00%3A00" in g.urls[1][0]
    assert w.poll_once() is None and w.poll_once() is None  # offline / column not there yet: retry later
    g2 = Get([(200, b"[]")])
    PersonalWatcher("https://x", "k", "7", tmp_path / "personal.json", marked.append, get=g2, start_thread=False).poll_once()
    assert "10%3A00%3A05" in g2.urls[0][0] and marked == ["e1", "e2"]  # a restart resumes after the last one


def test_a_failing_mark_does_not_stop_the_watcher(tmp_path):
    from kartcv.trip import PersonalWatcher
    rows = [{"event_id": "e1", "resolved_at": "2026-10-24T10:00:01+00:00"}]

    def boom(eid):
        raise RuntimeError("worker busy")

    w = PersonalWatcher("https://x", "k", "7", tmp_path / "p.json", boom,
                        get=Get([(200, json.dumps(rows).encode())]), start_thread=False)
    assert w.poll_once() == 1
