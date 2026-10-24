"""Merchant tests run against a throwaway local Postgres, like backend/tests (see its conftest)."""

from __future__ import annotations

import os
import sys
from pathlib import Path

import psycopg
import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "merchant"))
sys.path.insert(0, str(ROOT / "backend"))
import kartdb  # noqa: E402
from agent import Store, Tools  # noqa: E402

ADMIN_URL = os.environ.get("KART_TEST_PG", "postgresql://postgres@localhost:54329/postgres")
TEST_DB = "kart_merchant_test"


@pytest.fixture(scope="session")
def db_url():
    try:
        admin = psycopg.connect(ADMIN_URL, autocommit=True)
    except psycopg.OperationalError as e:
        pytest.skip(f"no test Postgres at {ADMIN_URL}: {e}")
    admin.execute(f"drop database if exists {TEST_DB} with (force)")
    admin.execute(f"create database {TEST_DB}")
    admin.close()
    url = ADMIN_URL.rsplit("/", 1)[0] + "/" + TEST_DB
    with kartdb.connect(url) as conn:
        kartdb.apply_migrations(conn, local=True)
    return url


@pytest.fixture
def store(db_url):
    """Catalog restored from store.json, empty change log, cart 7 reset."""
    with kartdb.connect(db_url) as c:
        kartdb.seed(c)
        c.execute("delete from merchant_changes")
        c.execute("select reset_cart('7')")
    s = Store(db_url)
    yield s
    s.conn.close()


@pytest.fixture
def tools(store):
    return Tools(store)
