"""Shared by the e2e tests and their fixtures: env values and the anon-key REST client."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import kartdb  # noqa: E402

kartdb.load_env()
URL = os.environ.get("SUPABASE_URL", "").rstrip("/")
ANON = os.environ.get("SUPABASE_ANON_KEY", "")
DB_URL = os.environ.get("SUPABASE_DB_URL", "")

CONFIGURED = bool(URL and ANON and DB_URL)


class Rest:
    """The anon-key PostgREST client every cart-side caller uses."""

    def __init__(self):
        self.http = httpx.Client(base_url=URL + "/rest/v1", timeout=15,
                                 headers={"apikey": ANON, "Authorization": f"Bearer {ANON}"})

    def rpc(self, name: str, **params) -> dict:
        r = self.http.post(f"/rpc/{name}", json=params)
        if r.status_code >= 400:
            raise RpcError(r.status_code, r.json())
        return r.json()

    def get(self, path: str, **params):
        r = self.http.get(path, params=params)
        r.raise_for_status()
        return r.json()


class RpcError(Exception):
    def __init__(self, status: int, body: dict):
        super().__init__(f"{status}: {json.dumps(body)}")
        self.status, self.body = status, body
