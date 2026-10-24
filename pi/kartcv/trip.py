"""New-trip reset (spec §7, CONTRACT v0.4): poll carts.trip_id and reset the cart's memory when it changes.

The iPad starts a trip with the backend's reset_cart, which sets a new trip_id, so it never has to
reach the Pi over the network. The last seen id is saved, so a trip started while the Pi was off
still resets it at startup.
"""
from __future__ import annotations

import json
import logging
import threading
import urllib.parse
from pathlib import Path
from typing import Callable

from kartcv import http

log = logging.getLogger(__name__)


class TripWatcher:
    def __init__(self, base_url: str, anon_key: str, cart_id: str, state_path: Path,
                 on_new_trip: Callable[[], None], get: Callable | None = None,
                 interval_s: float = 2.0, start_thread: bool = True):
        self.url = (f"{base_url.rstrip('/')}/rest/v1/carts"
                    f"?cart_id=eq.{urllib.parse.quote(str(cart_id))}&select=trip_id")
        self.headers = http.supabase_headers(anon_key)
        self.state_path = Path(state_path)
        self.on_new_trip = on_new_trip
        self._get = get or http.get
        self.interval_s = interval_s
        self.last: str | None = None
        if self.state_path.exists():
            try:
                self.last = json.loads(self.state_path.read_text()).get("trip_id")
            except ValueError:
                self.last = None
        self._stop = threading.Event()
        self._thread = None
        if start_thread:
            self._thread = threading.Thread(target=self._run, name="trip-watcher", daemon=True)
            self._thread.start()

    def _save(self, trip_id: str) -> None:
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        self.state_path.write_text(json.dumps({"trip_id": trip_id}))

    def poll_once(self) -> str | None:
        try:
            status, body = self._get(self.url, self.headers)
        except OSError:
            return None
        if status != 200:
            return None
        try:
            rows = json.loads(body)
        except ValueError:
            return None
        if not isinstance(rows, list) or not rows or not rows[0].get("trip_id"):
            return None
        trip_id = str(rows[0]["trip_id"])
        if self.last is None:  # first ever sighting: remember it, but don't wipe a cart in use
            self.last = trip_id
            self._save(trip_id)
        elif trip_id != self.last:
            log.info("new trip %s: resetting cart memory", trip_id)
            self.last = trip_id
            self._save(trip_id)
            try:
                self.on_new_trip()
            except Exception:
                log.exception("trip reset handler failed")
        return trip_id

    def _run(self) -> None:
        while not self._stop.is_set():
            self.poll_once()
            self._stop.wait(self.interval_s)

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=6.0)
