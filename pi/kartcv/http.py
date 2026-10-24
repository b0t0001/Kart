"""Tiny stdlib HTTP helpers for the Supabase REST calls (catalog, events, trip watch)."""
from __future__ import annotations

import json
import urllib.error
import urllib.request


def supabase_headers(anon_key: str) -> dict:
    return {"apikey": anon_key, "Authorization": f"Bearer {anon_key}", "Content-Type": "application/json"}


def get(url: str, headers: dict, timeout: float = 5.0) -> tuple[int, bytes]:
    """Returns (status, body). HTTP error statuses are returned; network failures raise OSError."""
    req = urllib.request.Request(url, headers=headers, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, resp.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read() or b""


def post_json(url: str, headers: dict, body: dict, timeout: float = 5.0) -> int:
    """Returns the HTTP status. Network failures raise OSError (URLError is one)."""
    data = json.dumps(body).encode()
    req = urllib.request.Request(url, data=data, headers={**headers, "Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            resp.read()
            return resp.status
    except urllib.error.HTTPError as e:
        return e.code
