import json

from kartcv.events import Event
from kartcv.sinks import ConsoleSink, HttpSink, JsonlSink, MemorySink


def ev(pid="kirkland-parmesan"):
    return Event.new(cart_id="7", type="added", product_id=pid, confidence=0.93, method="local", label="Parm",
                     cameras=[0, 1], crops=[])


class Post:
    def __init__(self, codes):
        self.codes, self.calls = list(codes), []

    def __call__(self, url, headers, body):
        self.calls.append((url, headers, body))
        c = self.codes.pop(0)
        if isinstance(c, Exception):
            raise c
        return c


def test_jsonl_and_console(tmp_path, capsys):
    s = JsonlSink(tmp_path / "e.jsonl")
    s.send(ev())
    s.send(ev())
    lines = (tmp_path / "e.jsonl").read_text().splitlines()
    assert [json.loads(line)["product_id"] for line in lines] == ["kirkland-parmesan"] * 2
    ConsoleSink().send(ev())
    ConsoleSink().send(Event.new(cart_id="7", type="added", product_id=None, confidence=0.4, method="none",
                                 label="a can", cameras=[0], crops=[]))
    out = capsys.readouterr().out
    assert "ADDED kirkland-parmesan (local 0.93)" in out and 'ADDED ? "a can" (none 0.40)' in out
    m = MemorySink()
    m.send(ev())
    assert len(m.events) == 1


def test_http_payload(tmp_path):
    p = Post([200])
    s = HttpSink("https://x.supabase.co/", "k", tmp_path / "o.jsonl", post=p, start_thread=False)
    e = ev()
    s.send(e)
    assert s.flush_once(0.0) == 1
    url, headers, body = p.calls[0]
    assert url == "https://x.supabase.co/rest/v1/rpc/apply_cart_event"
    assert headers["apikey"] == "k" and headers["Authorization"] == "Bearer k"
    assert body == {"p_cart_id": "7", "p_type": "added", "p_product_id": "kirkland-parmesan", "p_confidence": 0.93,
                    "p_source": "vision", "p_label": "Parm", "p_camera": 0, "p_event_id": e.event_id,
                    "p_method": "local"}


def test_outbox_order_backoff_and_restart(tmp_path):
    out = tmp_path / "o.jsonl"
    p = Post([500, OSError("down"), 200, 200])
    s = HttpSink("https://x", "k", out, post=p, start_thread=False)
    s.send(ev("a"))
    s.send(ev("b"))
    assert s.flush_once(0.0) == 0 and s.pending() == 2
    assert s.flush_once(0.5) == 0 and len(p.calls) == 1  # backing off 1 s
    assert s.flush_once(1.0) == 0 and s.pending() == 2   # OSError counts as failure, next wait 2 s
    s2 = HttpSink("https://x", "k", out, post=p, start_thread=False)  # restart: outbox survives
    assert s2.pending() == 2 and s2.flush_once(10.0) == 2
    assert [c[2]["p_product_id"] for c in p.calls[-2:]] == ["a", "b"] and s2.pending() == 0


def test_backoff_caps_at_30(tmp_path):
    s = HttpSink("https://x", "k", tmp_path / "o.jsonl", post=Post([500] * 10), start_thread=False)
    s.send(ev())
    t, waits = 0.0, []
    for _ in range(8):
        s.flush_once(t)
        waits.append(s.next_retry - t)
        t = s.next_retry
    assert waits == [1, 2, 4, 8, 16, 30, 30, 30]


def test_worker_thread_delivers(tmp_path):
    import time
    p = Post([200])
    s = HttpSink("https://x", "k", tmp_path / "o.jsonl", post=p)
    s.send(ev())
    for _ in range(50):
        if s.pending() == 0:
            break
        time.sleep(0.02)
    s.close()
    assert s.pending() == 0 and len(p.calls) == 1


def test_non_oserror_network_failures_are_retried(tmp_path):  # review I3
    import http.client
    p = Post([http.client.IncompleteRead(b""), ValueError("bad url"), 200])
    s = HttpSink("https://x", "k", tmp_path / "o.jsonl", post=p, start_thread=False)
    s.send(ev())
    assert s.flush_once(0.0) == 0 and s.pending() == 1
    assert s.flush_once(1.0) == 0 and s.pending() == 1
    assert s.flush_once(10.0) == 1 and s.pending() == 0
