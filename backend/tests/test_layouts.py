"""Store layouts (v0.15): data/layouts/<name>.json switched in place, one undoable merchant change."""

from __future__ import annotations

import json

import psycopg
import pytest

import kartdb
from test_cart import add, current


def snapshot(conn):
    return conn.execute("select layout_snapshot()").fetchone()[0]


def switch(conn, name):
    return kartdb.apply_layout(conn, name)["change"]


def test_mini_layout_is_exactly_todays_state(conn):
    snap, mini = snapshot(conn), json.loads((kartdb.LAYOUTS / "mini.json").read_text())
    assert snap["name"] == "mini"
    assert {s["id"]: s for s in snap["sections"]} == {s["id"]: s for s in mini["sections"]}
    assert {k: v for k, v in snap["products"].items() if k in mini["products"]} == mini["products"]


def test_switching_to_target_moves_aisles_and_routing_follows(cart, conn):
    cart("set_plan", p_plan=[{"product_id": "barilla-spaghetti", "reason": "pasta"}])
    add(cart, "bananas")                              # carts and their items survive a switch
    deals_before = conn.execute("select id, active, value from deals order by id").fetchall()
    cid = switch(conn, "target-berkeley")
    snap = snapshot(conn)
    assert snap["name"] == "target-berkeley" and "A4" not in {s["id"] for s in snap["sections"]}
    row = current(conn)
    assert row["next_step"] == "Aisle A12 → Spaghetti"
    assert row["items"][0]["product_id"] == "bananas" and row["items"][0]["section"] == "PRODUCE"
    assert conn.execute("select fmt_lcd(section, short_name, '') from products "
                        "where id = 'barilla-spaghetti'").fetchone()[0] == "A12 Spaghetti"
    assert cart("set_location", p_section="aisle A12")["location"]["section"] == "A12"
    # Target's shelf prices for the demo items; departments without a confirmed aisle read plainly
    prices = dict(conn.execute("select id, price::float from products where id in ('rao-marinara', 'queso')").fetchall())
    assert prices == {"rao-marinara": 2.19, "queso": 5.19}
    assert conn.execute("select section from products where id = 'hershey-xl'").fetchone()[0] == "A3"
    row = cart("set_plan", p_plan=[{"product_id": "french-baguette", "reason": "garlic bread"}])
    assert row["next_step"] == "Bakery → Garlic Bread, $1 off"
    assert conn.execute("select id, active, value from deals order by id").fetchall() == deals_before
    ch = conn.execute("select tool, status from merchant_changes where id = %s", [cid]).fetchone()
    assert ch == ("set_layout", "applied")


def test_undo_restores_the_previous_layout_exactly(conn):
    before = snapshot(conn)
    cid = switch(conn, "target-berkeley")
    conn.execute("select merchant_undo(%s)", [cid])
    assert snapshot(conn) == before


def test_undo_wont_clobber_a_later_move(conn):
    cid = switch(conn, "target-berkeley")
    conn.execute("update products set section = 'A6' where id = 'kirkland-parmesan'")
    with pytest.raises(psycopg.errors.RaiseException, match="stale"):
        conn.execute("select merchant_undo(%s)", [cid])


def test_a_bad_layout_changes_nothing(conn):
    before = snapshot(conn)
    bad = {"name": "bad", "sections": [{"id": "Z1", "name": "Aisle Z1", "x": 1, "y": 1, "w": 1, "h": 1}],
           "products": {"bananas": "Z9"}}
    with pytest.raises(psycopg.errors.RaiseException, match="sections it doesn't have"):
        conn.execute("select apply_layout(%s::jsonb)", [json.dumps(bad)])
    partial = {**bad, "products": {"bananas": "Z1"}}                       # leaves 20 products unplaced
    with pytest.raises(psycopg.errors.RaiseException, match="doesn't place"):
        with conn.transaction():
            conn.execute("select apply_layout(%s::jsonb)", [json.dumps(partial)])
    assert snapshot(conn) == before


def test_reset_demo_returns_to_mini_and_sync_keeps_another_layout(conn):
    switch(conn, "target-berkeley")
    kartdb.sync_catalog(conn)                                              # names/prices; placement stays
    assert snapshot(conn)["products"]["barilla-spaghetti"] == "A12"
    kartdb.seed(conn)                                                      # what reset-demo does
    snap = snapshot(conn)
    assert snap["name"] == "mini" and {s["id"] for s in snap["sections"]} == {f"A{i}" for i in range(1, 10)} | {"CK"}
