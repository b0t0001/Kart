"""Tiny stdlib HTTP helpers for the Supabase REST calls (catalog, events, trip watch)."""
from __future__ import annotations

import http.client
import json
import urllib.error
import urllib.request


def supabase_headers(anon_key: str) -> dict:
    return {"apikey": anon_key, "Authorization": f"Bearer {anon_key}", "Content-Type": "application/json"}


def get(url: str, headers: dict, timeout: float = 5.0) -> tuple[int, bytes]:
    """Returns (status, body). HTTP error statuses are returned; every other failure raises OSError."""
    try:
        req = urllib.request.Request(url, headers=headers, method="GET")
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, resp.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read() or b""
    except (http.client.HTTPException, ValueError) as e:  # truncated replies, bad status lines, bad URLs
        raise OSError(f"{type(e).__name__}: {e}") from e


def post_json(url: str, headers: dict, body: dict, timeout: float = 5.0) -> int:
    """Returns the HTTP status. Every other failure raises OSError (URLError is one)."""
    try:
        data = json.dumps(body).encode()
        req = urllib.request.Request(url, data=data, headers={**headers, "Content-Type": "application/json"},
                                     method="POST")
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            resp.read()
            return resp.status
    except urllib.error.HTTPError as e:
        return e.code
    except (http.client.HTTPException, ValueError) as e:
        raise OSError(f"{type(e).__name__}: {e}") from e
