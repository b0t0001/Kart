"""End-to-end tests against a running Supabase (local `supabase start`, or the hosted project).

They talk to it exactly like the clients do: PostgREST RPCs and realtime with the ANON key
(the Pi and the iPad), and SQL with SUPABASE_DB_URL for the merchant side (merchant_apply is
service-role only). Values come from the repo .env. Each run uses its own cart id and undoes
exactly the catalog changes it made (it never re-seeds the catalog or touches cart 7).

It REFUSES a non-local Supabase by default: the trips end in checkout, which takes items off the
shared stock (contract: automated runs on hosted never call checkout). Allow it with
`--allow-hosted` or KART_E2E_ALLOW_HOSTED=1; go_live.sh does, then restores stock.
"""

from __future__ import annotations

import os
import sys
import uuid
from pathlib import Path

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from client import ANON, CONFIGURED, DB_URL, URL, Rest, kartdb  # noqa: E402

LOCAL_HOSTS = ("127.0.0.1", "localhost", "[::1]")


def pytest_addoption(parser):
    parser.addoption("--allow-hosted", action="store_true",
                     help="run against a non-local Supabase (checkout takes items off its stock)")


@pytest.fixture(scope="session", autouse=True)
def local_only(pytestconfig):
    is_local = any(f"//{h}" in URL for h in LOCAL_HOSTS) and any(f"@{h}" in DB_URL for h in LOCAL_HOSTS)
    allowed = pytestconfig.getoption("--allow-hosted", default=False) or os.environ.get("KART_E2E_ALLOW_HOSTED") == "1"
    if CONFIGURED and not is_local and not allowed:
        pytest.skip(f"e2e refuses the hosted project ({URL}): its trips end in checkout, which drains shared "
                    "stock. Point .env at the local stack, or pass --allow-hosted (go_live.sh does).")


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
