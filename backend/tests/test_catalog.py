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
