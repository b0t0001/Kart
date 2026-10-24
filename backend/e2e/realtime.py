"""Minimal Supabase Realtime client (Phoenix protocol) for the end-to-end tests:
subscribe to postgres_changes on one table/filter and wait for a matching row."""

from __future__ import annotations

import json
import time

from websockets.sync.client import connect


class Watch:
    def __init__(self, url: str, anon: str, table: str, filter_: str | None = None):
        ws_url = url.replace("https://", "wss://").replace("http://", "ws://")
        self._conn = connect(f"{ws_url}/realtime/v1/websocket?apikey={anon}&vsn=1.0.0", open_timeout=10)
        self.ws = self._conn.__enter__()
        change = {"event": "*", "schema": "public", "table": table}
        if filter_:
            change["filter"] = filter_
        self.topic = f"realtime:e2e-{table}"
        self._send("phx_join", {"config": {"broadcast": {"self": False}, "presence": {"key": ""},
                                           "postgres_changes": [change]},
                                "access_token": anon})
        self._wait_subscribed()

    def _send(self, event: str, payload: dict) -> None:
        self.ws.send(json.dumps({"topic": self.topic, "event": event, "payload": payload,
                                 "ref": str(time.monotonic_ns()), "join_ref": "1"}))

    def _messages(self, timeout: float):
        end = time.monotonic() + timeout
        while (left := end - time.monotonic()) > 0:
            try:
                yield json.loads(self.ws.recv(timeout=left))
            except TimeoutError:
                return

    def _wait_subscribed(self, timeout: float = 15) -> None:
        for m in self._messages(timeout):
            if m["event"] == "phx_reply" and m["payload"].get("status") == "error":
                raise RuntimeError(f"realtime join failed: {m['payload']}")
            if m["event"] == "system" and m["payload"].get("status") == "ok" \
                    and "Subscribed" in m["payload"].get("message", ""):
                return
        raise TimeoutError("realtime subscription never confirmed")

    def wait_for(self, predicate, timeout: float = 10) -> dict:
        """Next changed row (record) for which predicate(record) is true."""
        for m in self._messages(timeout):
            if m["event"] == "postgres_changes":
                record = m["payload"]["data"].get("record") or {}
                if predicate(record):
                    return record
        raise TimeoutError("no matching realtime change")

    def close(self) -> None:
        self._conn.__exit__(None, None, None)
