"""End-to-end tests against a running Supabase (local `supabase start`, or the hosted project).

They talk to it exactly like the clients do: PostgREST RPCs and realtime with the ANON key
(the Pi and the iPad), and SQL with SUPABASE_DB_URL for the merchant side (merchant_apply is
service-role only). Values come from the repo .env. Each run uses its own cart id and undoes
exactly the catalog changes it made, so it's safe on the shared hosted project (it never
re-seeds the catalog or touches cart 7).
"""

from __future__ import annotations

import sys
import uuid
from pathlib import Path

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from client import ANON, CONFIGURED, DB_URL, URL, Rest, kartdb  # noqa: E402


@pytest.fixture(scope="session")
def rest():
    if not CONFIGURED:
        pytest.skip("SUPABASE_URL / SUPABASE_ANON_KEY / SUPABASE_DB_URL not set in .env")
    try:
        httpx.get(URL + "/rest/v1/", headers={"apikey": ANON}, timeout=5)
    except httpx.HTTPError as e:
        pytest.skip(f"Supabase not reachable at {URL}: {e}")
    return Rest()


@pytest.fixture(scope="session")
def db():
    if not CONFIGURED:
        pytest.skip("SUPABASE_DB_URL not set in .env")
    with kartdb.connect(DB_URL) as conn:
        yield conn


@pytest.fixture
def merchant_changes(db):
    """Merchant changes a test applies; undone newest-first afterwards."""
    applied: list[int] = []
    yield applied
    for cid in reversed(applied):
        db.execute("select merchant_undo(%s)", [cid])


@pytest.fixture
def cart_id(db):
    cid = f"e2e-{uuid.uuid4().hex[:8]}"
    yield cid
    db.execute("delete from transcript where cart_id = %s", [cid])
    db.execute("delete from receipts where cart_id = %s", [cid])
    db.execute("delete from cart_events where cart_id = %s", [cid])
    db.execute("delete from carts where cart_id = %s", [cid])
