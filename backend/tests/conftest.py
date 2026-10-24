"""Tests run against a throwaway local Postgres (not Supabase).

KART_TEST_PG points at a server where we may create the database kart_test,
default postgresql://postgres@localhost:54329/postgres. Start one with:

  initdb -D /tmp/kartpg -U postgres --auth=trust
  LC_ALL=en_US.UTF-8 pg_ctl -D /tmp/kartpg -o "-p 54329" start
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import psycopg
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import kartdb  # noqa: E402

ADMIN_URL = os.environ.get("KART_TEST_PG", "postgresql://postgres@localhost:54329/postgres")
TEST_DB = "kart_test"


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
def conn(db_url):
    """A connection with the catalog restored from store.json and cart 7 reset."""
    with kartdb.connect(db_url) as c:
        kartdb.seed(c)
        kartdb.rpc(c, "reset_cart", p_cart_id="7")
        yield c


@pytest.fixture
def cart(conn):
    """cart(fn, **params) calls a cart RPC on cart 7 and returns the row."""
    def call(fn, **params):
        return kartdb.rpc(conn, fn, p_cart_id="7", **params)
    return call
