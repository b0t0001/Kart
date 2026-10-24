"""Member memory (CONTRACT v0.14, BETA): feature member_memory, off by default."""

from __future__ import annotations

from datetime import date, timedelta

import psycopg
import pytest

import kartdb
from test_cart import add

TZ = "America/Los_Angeles"


def store_today(conn) -> date:
    return conn.execute(f"select (now() at time zone '{TZ}')::date").fetchone()[0]


@pytest.fixture
def member_cart(cart, conn):
    """Cart 7 with the beta on for this cart only; test members are wiped first."""
    conn.execute("delete from members where member_id like 'it-%'")
    cart("set_feature", p_feature="member_memory", p_on=True)
    return cart


# ── Off (the default) ──

def test_flag_seeded_off_and_set_member_refuses(cart, conn):
    assert conn.execute("select enabled_default from feature_flags where name = 'member_memory'").fetchone()[0] is False
    with pytest.raises(psycopg.errors.RaiseException, match="feature_off: member_memory"):
        cart("set_member", p_member_id="it-1")
    with pytest.raises(psycopg.errors.RaiseException, match="feature_off: member_memory"):
        cart("set_demo_date", p_date="2026-10-30")
    row = cart("reset_cart")
    assert row["member_id"] is None and row["demo_date"] is None and row["member_rev"] == 0


# ── Sign-in ──

def test_set_member_creates_unknown_member(member_cart, conn):
    row = member_cart("set_member", p_member_id="it-1")
    assert row["member_id"] == "it-1"
    assert conn.execute("select name from members where member_id = 'it-1'").fetchone() == (None,)


def test_bad_member_id_rejected(member_cart):
    with pytest.raises(psycopg.errors.RaiseException, match="bad member id"):
        member_cart("set_member", p_member_id="it 1; drop")


def test_set_member_null_signs_out(member_cart):
    member_cart("set_member", p_member_id="it-1")
    assert member_cart("set_member", p_member_id=None)["member_id"] is None


def test_new_trip_clears_member_keeps_demo_date(member_cart):
    member_cart("set_member", p_member_id="it-1")
    member_cart("set_demo_date", p_date="2026-10-30")
    row = member_cart("reset_cart")
    assert row["member_id"] is None
    assert row["demo_date"] == "2026-10-30"


# ── Checkout feeds history ──

def purchases(conn, member_id):
    return conn.execute(
        f"select product_id, qty, source, (bought_at at time zone '{TZ}')::date from member_purchases "
        "where member_id = %s order by product_id", [member_id]).fetchall()


def test_checkout_copies_purchases_once_with_demo_date(member_cart, conn):
    today = store_today(conn)
    member_cart("set_member", p_member_id="it-1")
    add(member_cart, "barilla-spaghetti")
    add(member_cart, "barilla-spaghetti")
    add(member_cart, "whole-milk")
    member_cart("set_demo_date", p_date=(today + timedelta(days=6)).isoformat())
    receipt = member_cart("checkout")
    member_cart("checkout")                                   # idempotent per trip
    later = today + timedelta(days=6)
    assert purchases(conn, "it-1") == [("barilla-spaghetti", 2, "checkout", later), ("whole-milk", 1, "checkout", later)]
    stored = conn.execute(f"select member_id, (created_at at time zone '{TZ}')::date from receipts where id = %s",
                          [receipt["id"]]).fetchone()
    assert stored == ("it-1", today)                          # the receipt itself stays real


def test_guest_checkout_writes_no_purchases(member_cart, conn):
    add(member_cart, "whole-milk")
    receipt = member_cart("checkout")
    assert conn.execute("select count(*) from member_purchases").fetchone()[0] == 0
    assert conn.execute("select member_id from receipts where id = %s", [receipt["id"]]).fetchone() == (None,)
