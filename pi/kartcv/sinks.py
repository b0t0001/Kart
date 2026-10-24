"""Where events go (spec §8): a local log always, the backend when configured, with an ordered outbox."""
from __future__ import annotations

import json
import logging
import os
import threading
import time
from pathlib import Path
from typing import Callable

from kartcv import http
from kartcv.events import Event

log = logging.getLogger(__name__)

MAX_BACKOFF_S = 30.0


class JsonlSink:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def send(self, event: Event) -> None:
        with self.path.open("a") as f:
            f.write(json.dumps(event.to_json()) + "\n")

    def close(self) -> None:
        pass


class ConsoleSink:
    def send(self, event: Event) -> None:
        what = event.product_id if event.product_id else f'? "{event.label}"'
        print(f"{event.type.upper()} {what} ({event.method} {event.confidence:.2f})", flush=True)

    def close(self) -> None:
        pass


class MemorySink:
    def __init__(self):
        self.events: list[Event] = []

    def send(self, event: Event) -> None:
        self.events.append(event)

    def close(self) -> None:
        pass


def rpc_body(e: dict) -> dict:
    return {
        "p_cart_id": e["cart_id"],
        "p_type": e["type"],
        "p_product_id": e["product_id"],
        "p_confidence": e["confidence"],
        "p_source": "vision",
        "p_label": e["label"],
        "p_camera": e["cameras"][0] if e["cameras"] else None,
        "p_event_id": e["event_id"],  # apply_cart_event is idempotent on it, so retries can't double-bill
        "p_method": e["method"],
    }


class HttpSink:
    """Sends events to Supabase `apply_cart_event` in order, from a persistent outbox file.

    A failed send stops the flush (order matters: add before remove) and backs off 1, 2, 4 … 30 s.
    The outbox survives restarts. The lock is never held during a network call, so `send` from the
    camera loop never waits on the network.
    """

    def __init__(self, base_url: str, anon_key: str, outbox: Path, post: Callable | None = None,
                 start_thread: bool = True):
        self.url = f"{base_url.rstrip('/')}/rest/v1/rpc/apply_cart_event"
        self.headers = http.supabase_headers(anon_key)
        self.outbox = Path(outbox)
        self._post = post or http.post_json
        self._lock = threading.Lock()
        self._flush_lock = threading.Lock()
        self._pending: list[dict] = []
        if self.outbox.exists():
            self._pending = [json.loads(line) for line in self.outbox.read_text().splitlines() if line.strip()]
        self._failures = 0
        self.next_retry = 0.0
        self._wake = threading.Event()
        self._stop = threading.Event()
        self._thread = None
        if start_thread:
            self._thread = threading.Thread(target=self._run, name="http-sink", daemon=True)
            self._thread.start()

    def pending(self) -> int:
        with self._lock:
            return len(self._pending)

    def send(self, event: Event) -> None:
        e = event.to_json()
        with self._lock:
            self._pending.append(e)
            self.outbox.parent.mkdir(parents=True, exist_ok=True)
            with self.outbox.open("a") as f:
                f.write(json.dumps(e) + "\n")
        self._wake.set()

    def _rewrite_outbox(self) -> None:
        tmp = self.outbox.with_suffix(self.outbox.suffix + ".tmp")
        tmp.write_text("".join(json.dumps(e) + "\n" for e in self._pending))
        os.replace(tmp, self.outbox)

    def flush_once(self, now: float) -> int:
        sent = 0
        with self._flush_lock:
            while True:
                with self._lock:
                    if not self._pending or now < self.next_retry:
                        return sent
                    e = self._pending[0]
                try:
                    status = self._post(self.url, self.headers, rpc_body(e))
                    ok = 200 <= status < 300
                    if not ok:
                        log.warning("http sink: apply_cart_event returned HTTP %s", status)
                except Exception as err:  # any failure is a failed attempt: back off, keep the event
                    ok = False
                    log.warning("http sink: backend unreachable (%s: %s)", type(err).__name__, err)
                with self._lock:
                    if ok:
                        self._pending.pop(0)
                        self._failures = 0
                        self.next_retry = 0.0
                        self._rewrite_outbox()
                        sent += 1
                    else:
                        self._failures += 1
                        self.next_retry = now + min(MAX_BACKOFF_S, 2.0 ** (self._failures - 1))
                        return sent

    def _run(self) -> None:
        while not self._stop.is_set():
            wait = max(0.05, self.next_retry - time.monotonic()) if self.next_retry else 1.0
            self._wake.wait(timeout=wait)
            self._wake.clear()
            if not self._stop.is_set():
                try:
                    self.flush_once(time.monotonic())
                except Exception:  # never let the delivery thread die: the outbox would stop draining
                    log.exception("http sink: flush failed")

    def close(self) -> None:
        self._stop.set()
        self._wake.set()
        if self._thread is not None:
            self._thread.join(timeout=6.0)
