"""db.py sync-catalog: store.json applied in place on a shared database."""

from __future__ import annotations

import json

import kartdb


def test_sync_updates_in_place_and_keeps_live_stock_and_other_deals(conn):
    conn.execute("update products set stock = 7, short_name = 'Old Name', price = 9.99 where id = 'rao-marinara'")
    conn.execute("insert into deals (id, product_id, type, value, label) "
                 "values ('d-owner-live', 'bananas', 'amount_off', 0.5, '$0.50 off')")
    conn.execute("delete from products where id = 'queso'")
    out = kartdb.sync_catalog(conn)
    assert out["products"] == len(json.loads(kartdb.STORE_JSON.read_text())["products"])
    rao = conn.execute("select short_name, price, stock from products where id = 'rao-marinara'").fetchone()
    assert (rao[0], float(rao[1]), rao[2]) == ("Marinara", 3.49, 7)          # names/prices synced, stock kept
    assert conn.execute("select stock from products where id = 'queso'").fetchone()[0] == 20   # new: file stock
    assert conn.execute("select active from deals where id = 'd-owner-live'").fetchone()[0]    # not deleted


def test_sync_with_stock_sets_counts_bought(conn):
    conn.execute("update products set stock = 7 where id = 'rao-marinara'")
    kartdb.sync_catalog(conn, with_stock=True)
    assert conn.execute("select stock from products where id = 'rao-marinara'").fetchone()[0] == 24


def test_demo_plan_catalog(conn):
    rows = dict(conn.execute("select id, short_name from product_catalog").fetchall())
    assert {rows[k] for k in ("queso", "black-beans", "jalapenos", "french-baguette")} == \
        {"Queso", "Black Beans", "Jalapeños", "Garlic Bread"}
    parm = conn.execute("select deal_label, sale_price from product_catalog where id = 'kirkland-parmesan'").fetchone()
    assert (parm[0], float(parm[1])) == ("$1 off", 3.99)
    assert conn.execute("select pairs_with from deals where id = 'd-chips-150off'").fetchone()[0] == ["tostitos-salsa", "queso"]
    assert conn.execute("select fmt_lcd('A5', 'Jalapeños', '')").fetchone()[0] == "A5 Jalapenos"


def test_nearby_stores_are_public_and_never_claim_stock(conn, db_url):
    nearby = conn.execute("select nearby from store_info where id = 1").fetchone()[0]
    assert {n["name"] for n in nearby} == {"Trader Joe's", "Berkeley Bowl", "Safeway", "Walgreens"}
    assert all({"name", "address", "distance_mi", "kind", "good_for"} <= n.keys() and "stock" not in n for n in nearby)
    import psycopg
    with psycopg.connect(db_url) as c:
        c.execute("set local role anon")
        assert len(c.execute("select nearby from store_info").fetchone()[0]) == 4
        c.rollback()


def test_bakery_is_the_last_aisle_in_the_mini_store(conn):
    aisles = dict(conn.execute("select id, name from sections").fetchall())
    assert aisles["A2"] == "Aisle 2 · Dairy & Eggs" and aisles["A8"] == "Aisle 8 · Bakery & Tortillas"
    placed = dict(conn.execute("select id, section from products where id in "
                               "('french-baguette', 'mission-tortillas', 'whole-milk')").fetchall())
    assert placed == {"french-baguette": "A8", "mission-tortillas": "A8", "whole-milk": "A2"}


def test_dessert_and_not_sold_here(conn):
    """DEMO_PLAN: 'add something chocolate' finds the Hershey's; 'add olive oil' is not sold here."""
    row = conn.execute("select short_name, section, price::float, tags from product_catalog where id = 'hershey-xl'").fetchone()
    assert row == ("Chocolate Bar", "A7", 3.89, ["dessert", "chocolate", "snack"])
    assert conn.execute("select count(*) from products where name ilike '%olive%' or name ilike '%oil%'").fetchone()[0] == 0
    nearby = conn.execute("select nearby from store_info").fetchone()[0]
    assert {n["name"] for n in nearby if "oil" in n["good_for"]} == {"Trader Joe's", "Safeway", "Berkeley Bowl"}


def test_kids_scissors_in_the_far_aisle(conn):
    row = conn.execute("select short_name, section, section_name, price::float from product_catalog "
                       "where id = 'kids-scissors'").fetchone()
    assert row == ("Kids' Scissors", "A9", "Aisle 9 · Household & School", 1.89)


def test_judging_stock_counts(conn):
    counts = kartdb.set_stock_counts(conn)
    assert counts == {"barilla-spaghetti": 3, "rao-marinara": 1, "kirkland-parmesan": 1, "kids-scissors": 1}
    assert dict(conn.execute("select id, stock from products where id = any(%s)", [list(counts)]).fetchall()) == counts
