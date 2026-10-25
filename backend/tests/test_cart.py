"""Cart RPC behaviour: CONTRACT §3 plus the demo moments."""

from __future__ import annotations

import json
import uuid

import psycopg
import pytest

import kartdb


def add(cart, pid, **kw):
    return cart("apply_cart_event", p_type="added", p_product_id=pid, p_confidence=0.9,
                p_source=kw.pop("source", "vision"), p_label=kw.pop("label", pid), **kw)


def remove(cart, pid, **kw):
    return cart("apply_cart_event", p_type="removed", p_product_id=pid, p_confidence=0.9,
                p_source="vision", p_label=pid, **kw)


def qty(row, pid):
    return next((i["qty"] for i in row["items"] if i["product_id"] == pid), 0)


def events(conn, current_trip=True):
    """Cart 7's events, by default only those of the current trip."""
    return conn.execute("select e.type, e.product_id, e.applied, e.label, e.method, e.trip_id::text "
                        "from cart_events e join carts c using (cart_id) where cart_id = '7' "
                        "and (not %s or e.trip_id = c.trip_id) order by e.id", [current_trip]).fetchall()


# ── Adds, removes, idempotency ──

def test_add_joins_price_and_suggests_parmesan(cart):
    row = add(cart, "barilla-spaghetti")
    assert row["items"][0]["price"] == 1.99
    assert row["items"][0]["name"] == "Barilla Spaghetti, 1 lb"
    assert row["total"] == 1.99 and row["item_count"] == 1
    s = row["suggestion"]
    assert s["product_id"] == "kirkland-parmesan" and s["deal_id"] == "d-parm-3off"
    assert s["text"] == "Parmesan is $1 off in Aisle 4. Want it?"
    assert row["lcd_line1"] == "A4 Parmesan -$1"


def test_repeated_event_id_is_ignored(cart, conn):
    eid = str(uuid.uuid4())
    add(cart, "barilla-spaghetti", p_event_id=eid, p_method="local")
    row = add(cart, "barilla-spaghetti", p_event_id=eid, p_method="local")
    assert qty(row, "barilla-spaghetti") == 1
    assert len(events(conn)) == 1


def test_add_twice_then_remove(cart):
    add(cart, "barilla-spaghetti")
    row = add(cart, "barilla-spaghetti")
    assert qty(row, "barilla-spaghetti") == 2 and row["total"] == 3.98
    row = remove(cart, "barilla-spaghetti")
    assert qty(row, "barilla-spaghetti") == 1
    row = remove(cart, "barilla-spaghetti")
    assert row["items"] == [] and row["total"] == 0


def test_remove_of_item_not_in_cart_is_recorded_not_applied(cart, conn):
    row = remove(cart, "rao-marinara")
    assert row["items"] == []
    assert events(conn)[-1][:3] == ("removed", "rao-marinara", False)


def test_unrecognized_events_are_recorded_only(cart, conn):
    add(cart, None, label="blue box", p_method="none")
    row = add(cart, "not-a-real-id", label="mystery")
    assert row["items"] == []
    (t1, p1, a1, l1, m1, _), (t2, p2, a2, l2, _, _) = events(conn)
    assert (p1, a1, m1) == (None, False, "none")
    assert p2 is None and not a2 and "[unknown id: not-a-real-id]" in l2


def test_manual_fix_gets_manual_method(cart, conn):
    row = add(cart, "barilla-spaghetti", source="manual")
    assert qty(row, "barilla-spaghetti") == 1
    assert events(conn)[-1][4] == "manual"


def test_bad_method_does_not_wedge_cv(cart, conn):
    row = add(cart, "bananas", p_method="telepathy")
    assert qty(row, "bananas") == 1
    assert events(conn)[-1][4] is None


# ── Deals ──

def test_amount_off_deal_price_and_savings(cart):
    row = add(cart, "kirkland-parmesan")
    item = row["items"][0]
    assert (item["price"], item["list_price"], item["deal_label"]) == (3.19, 4.19, "$1 off")
    assert row["savings"] == 1.0


def test_percent_off_deal(cart):
    row = add(cart, "daisy-sour-cream")
    assert row["items"][0]["price"] == 2.39  # 2.99 × 0.8
    assert row["items"][0]["deal_label"] == "20% off"


def test_expired_deal_not_applied(cart, conn):
    conn.execute("update deals set ends_at = now() - interval '1 minute' where id = 'd-parm-3off'")
    row = add(cart, "kirkland-parmesan")
    assert row["items"][0]["price"] == 4.19 and "deal_label" not in row["items"][0]


def current(conn):
    return conn.execute("select to_jsonb(c) from carts c where cart_id = '7'").fetchone()[0]


def test_price_drop_reaches_open_cart(cart, conn):
    add(cart, "barilla-spaghetti")
    conn.execute("update products set price = 1.49 where id = 'barilla-spaghetti'")
    row = current(conn)
    assert row["items"][0]["price"] == 1.49 and row["total"] == 1.49


def test_new_deal_reaches_item_already_in_cart(cart, conn):
    """Merchant demo: 'spaghetti $1 off' while it's in the cart → the bill drops live."""
    add(cart, "barilla-spaghetti")
    conn.execute("insert into deals (id, product_id, type, value, label) "
                 "values ('d-spag-1off', 'barilla-spaghetti', 'amount_off', 1, '$1 off')")
    item = current(conn)["items"][0]
    assert (item["price"], item["list_price"], item["deal_label"]) == (0.99, 1.99, "$1 off")
    assert current(conn)["savings"] == 1.0


def test_price_increase_does_not_raise_the_bill(cart, conn):
    """P10: the price you saw is the price you pay."""
    add(cart, "barilla-spaghetti")
    conn.execute("update products set price = 2.49 where id = 'barilla-spaghetti'")
    row = current(conn)
    assert row["items"][0]["price"] == 1.99 and row["savings"] == 0
    remove(cart, "barilla-spaghetti")
    row = add(cart, "barilla-spaghetti")              # a fresh line gets today's price
    assert row["items"][0]["price"] == 2.49


def test_ended_deal_is_kept_for_items_already_in_cart(cart, conn):
    add(cart, "kirkland-parmesan")
    conn.execute("update deals set active = false where id = 'd-parm-3off'")
    item = current(conn)["items"][0]
    assert (item["price"], item["deal_label"]) == (3.19, "$1 off")


def test_new_deal_reaches_cart_with_a_pairing_item(cart, conn):
    """Merchant demo: 'chips $2 off' → a cart holding salsa gets the suggestion live."""
    conn.execute("delete from deals where id = 'd-chips-150off'")
    row = add(cart, "tostitos-salsa")
    assert row["suggestion"] is None
    conn.execute("insert into deals (id, product_id, type, value, label, pairs_with) "
                 "values ('d-chips-2off', 'tostitos-chips', 'amount_off', 2, '$2 off', '{tostitos-salsa}')")
    row = current(conn)
    assert row["suggestion"]["deal_id"] == "d-chips-2off"
    assert row["suggestion"]["text"] == "Tortilla Chips are $2 off in Aisle 7. Want them?"


# ── Suggestions ──

def test_suggestion_cleared_when_accepted_and_offered_once(cart):
    add(cart, "barilla-spaghetti")
    row = add(cart, "kirkland-parmesan")              # accepted
    assert row["suggestion"]["product_id"] == "french-baguette"
    row = cart("dismiss_suggestion")                  # "no thanks"
    assert row["suggestion"] is None
    row = add(cart, "rao-marinara")                   # pairs with both; both already offered
    assert row["suggestion"] is None
    assert set(row["suggested_deals"]) == {"d-parm-3off", "d-baguette-1off"}


def test_out_of_stock_deal_is_not_suggested(cart, conn):
    conn.execute("update products set stock = 0 where id = 'kirkland-parmesan'")
    row = add(cart, "barilla-spaghetti")
    assert row["suggestion"]["product_id"] == "french-baguette"


def test_most_recent_pairing_wins(cart):
    add(cart, "tostitos-salsa")                       # → chips
    row = add(cart, "kirkland-paper-towels")          # chips still valid: kept
    assert row["suggestion"]["product_id"] == "tostitos-chips"


# ── Plan, route, next step ──

PASTA = [
    {"product_id": "rao-marinara", "reason": "sauce"},
    {"product_id": "barilla-spaghetti", "reason": "pasta", "qty": 2},
    {"product_id": "kirkland-parmesan", "reason": "topping"},
    {"product_id": "french-baguette", "reason": "bread"},
]


def test_plan_is_route_ordered_from_the_entrance(cart):
    row = cart("set_plan", p_plan=PASTA)
    assert [p["product_id"] for p in row["plan"]] == [
        "kirkland-parmesan", "rao-marinara", "barilla-spaghetti", "french-baguette"]   # bakery is last
    assert row["next_step"] == "Aisle 4 → Parmesan, $1 off"
    assert row["plan"][0]["aisle"] == "Aisle 4" and row["plan"][0]["in_stock"] is True


def test_route_continues_from_where_the_shopper_is(cart):
    cart("set_plan", p_plan=PASTA)
    row = add(cart, "rao-marinara")                   # shopper is in aisle 6 now
    order = [p["product_id"] for p in row["plan"]]
    assert order == ["rao-marinara", "barilla-spaghetti", "french-baguette", "kirkland-parmesan"]
    assert row["plan"][0]["done"] is True
    assert row["next_step"] == "Aisle 6 → Spaghetti"


def test_plan_qty_and_all_done(cart):
    cart("set_plan", p_plan=PASTA)
    for pid in ["rao-marinara", "barilla-spaghetti", "kirkland-parmesan", "french-baguette"]:
        row = add(cart, pid)
    assert row["next_step"] == "Aisle 6 → Spaghetti"  # wants 2
    row = add(cart, "barilla-spaghetti")
    assert all(p["done"] for p in row["plan"])
    assert row["next_step"] == "All done → Checkout"
    assert row["lcd_line1"] == "Done -> Checkout"


def test_out_of_stock_plan_item_is_skipped(cart, conn):
    conn.execute("update products set stock = 0 where id = 'rao-marinara'")
    row = cart("set_plan", p_plan=[{"product_id": "rao-marinara", "reason": "sauce"},
                                   {"product_id": "barilla-spaghetti", "reason": "pasta"}])
    rao = next(p for p in row["plan"] if p["product_id"] == "rao-marinara")
    assert rao["in_stock"] is False
    assert row["next_step"] == "Aisle 6 → Spaghetti"


def test_moving_a_product_updates_directions(cart, conn):
    cart("set_plan", p_plan=[{"product_id": "kirkland-parmesan", "reason": "topping"}])
    conn.execute("update products set section = 'A6' where id = 'kirkland-parmesan'")
    row = current(conn)
    assert row["next_step"] == "Aisle 6 → Parmesan, $1 off"


def test_set_plan_rejects_non_array(cart):
    with pytest.raises(psycopg.errors.RaiseException):
        cart("set_plan", p_plan={"product_id": "bananas"})


# ── Reset ──

def test_reset_clears_and_issues_new_trip_id(cart, conn):
    before = cart("set_plan", p_plan=PASTA)
    add(cart, "barilla-spaghetti")
    row = cart("reset_cart")
    assert row["trip_id"] != before["trip_id"]
    assert (row["items"], row["plan"], row["suggestion"], row["suggested_deals"]) == ([], [], None, [])
    assert row["total"] == 0 and row["lcd_line1"] == "KART ready"
    assert events(conn) == []                                          # new trip, no events yet
    assert events(conn, current_trip=False)[-1][5] == before["trip_id"]   # old events keep their trip


def test_unknown_cart_is_created_on_first_event(conn):
    row = kartdb.rpc(conn, "apply_cart_event", p_cart_id="99", p_type="added", p_product_id="bananas",
                     p_confidence=0.9, p_source="vision", p_label="bananas")
    assert row["cart_id"] == "99" and row["total"] == 1.49


# ── LCD ──

def test_every_lcd_line_fits_16_ascii_chars(conn):
    rows = conn.execute("select section, short_name, deal_type, deal_value from product_catalog").fetchall()
    for section, short, dtype, dval in rows:
        line = conn.execute("select fmt_lcd(%s, %s, fmt_deal_short(%s, %s))",
                            [section, short, dtype, dval]).fetchone()[0]
        assert len(line) <= 16 and line.isascii(), line


# ── Permissions (what the anon key can and can't do) ──

def test_anon_reads_and_calls_rpcs_but_cannot_write_tables(db_url):
    with psycopg.connect(db_url) as c:      # one transaction, rolled back
        c.execute("set local role anon")
        assert c.execute("select count(*) from product_catalog").fetchone()[0] == len(
            json.loads(kartdb.STORE_JSON.read_text())["products"])
        kartdb.rpc(c, "apply_cart_event", p_cart_id="7", p_type="added", p_product_id="bananas",
                   p_confidence=0.9, p_source="vision", p_label="bananas")
        for sql in ["update products set price = 0",
                    "insert into deals (id, product_id, type, value, label) values ('x','bananas','amount_off',1,'x')",
                    "update carts set total = 0",
                    "select seed_catalog('{}'::jsonb)",
                    "select recompute_cart('7')"]:
            c.execute("savepoint s")
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                c.execute(sql)
            c.execute("rollback to savepoint s")
        c.rollback()


def test_a_deal_created_after_the_suggestion_takes_its_place(cart, conn):
    """Merchant demo: the cart shows Baguette; the owner creates a Parmesan deal; the cart switches."""
    conn.execute("update deals set active = false where id = 'd-parm-3off'")
    row = add(cart, "barilla-spaghetti")
    assert row["suggestion"]["product_id"] == "french-baguette"
    conn.execute("insert into deals (id, product_id, type, value, label, pairs_with) "
                 "values ('d-parm-live', 'kirkland-parmesan', 'amount_off', 3, '$3 off', '{barilla-spaghetti}')")
    s = current(conn)["suggestion"]
    assert (s["deal_id"], s["text"]) == ("d-parm-live", "Parmesan is $3 off in Aisle 4. Want it?")
    row = add(cart, "rao-marinara")                   # an older deal doesn't push it out
    assert row["suggestion"]["deal_id"] == "d-parm-live"


# ── A "Yes" consumes the suggestion (the product goes on the plan) ──

def test_yes_moves_on_to_the_next_deal(cart):
    row = add(cart, "tostitos-salsa")
    assert row["suggestion"]["product_id"] == "tostitos-chips"
    row = add(cart, "mission-tortillas")              # Sour Cream is now eligible, but Chips holds the slot
    assert row["suggestion"]["product_id"] == "tostitos-chips"
    row = cart("set_plan", p_plan=[{"product_id": "tostitos-chips", "reason": "said yes"}])
    assert row["suggestion"]["product_id"] == "daisy-sour-cream"  # the next eligible deal, right away
    assert set(row["suggested_deals"]) == {"d-chips-150off", "d-sourcream-20pct"}
    row = cart("set_plan", p_plan=[])                 # taking it off the list doesn't re-offer Chips
    assert row["suggestion"]["product_id"] == "daisy-sour-cream"


def test_nothing_is_offered_for_items_on_the_plan(cart, conn):
    cart("set_plan", p_plan=[{"product_id": "kirkland-parmesan", "reason": "topping"}])
    row = add(cart, "barilla-spaghetti")
    assert row["suggestion"]["product_id"] == "french-baguette"   # not the planned Parmesan
    conn.execute("insert into deals (id, product_id, type, value, label, pairs_with) "
                 "values ('d-parm-new', 'kirkland-parmesan', 'amount_off', 4, '$4 off', '{barilla-spaghetti}')")
    assert current(conn)["suggestion"]["product_id"] == "french-baguette"   # a newer deal on a planned item doesn't pop
    assert current(conn)["plan"][0]["deal_label"] == "$4 off"             # it shows on the list row instead


def test_planned_suggestion_is_consumed_when_nothing_else_is_eligible(cart):
    row = add(cart, "barilla-spaghetti")
    assert row["suggestion"]["product_id"] == "kirkland-parmesan"
    row = cart("set_plan", p_plan=[{"product_id": "kirkland-parmesan", "reason": "said yes"}])
    assert row["suggestion"]["product_id"] == "french-baguette"     # Baguette comes next
    row = cart("set_plan", p_plan=[{"product_id": "kirkland-parmesan", "reason": "said yes"},
                                   {"product_id": "french-baguette", "reason": "said yes"}])
    assert row["suggestion"] is None


# ── v0.20 P5: one "No thanks" quiets unprompted deal cards for the rest of the trip ──

def test_no_thanks_quiets_every_other_card_including_new_store_deals(cart, conn):
    add(cart, "barilla-spaghetti")
    row = cart("dismiss_suggestion")
    assert (row["suggestion"], row["deals_quiet"]) == (None, True)
    assert add(cart, "tostitos-salsa")["suggestion"] is None          # Chips would pair with it
    conn.execute("insert into deals (id, product_id, type, value, label, pairs_with) "
                 "values ('d-parm-live', 'kirkland-parmesan', 'amount_off', 3, '$3 off', '{barilla-spaghetti}')")
    assert current(conn)["suggestion"] is None                        # a fresh store deal doesn't pop either
    assert set(current(conn)["suggested_deals"]) == {"d-parm-3off"}   # nothing else was offered


def test_no_thanks_with_no_card_up_quiets_nothing(cart):
    row = cart("dismiss_suggestion")
    assert row["deals_quiet"] is False
    assert add(cart, "barilla-spaghetti")["suggestion"]["product_id"] == "kirkland-parmesan"


def test_a_card_cleared_for_the_shopper_can_leave_the_others_on(cart):
    """The agent clears a card the shopper never heard (an item they avoid) with p_quiet false."""
    add(cart, "barilla-spaghetti")
    row = cart("dismiss_suggestion", p_quiet=False)
    assert row["deals_quiet"] is False
    assert row["suggestion"]["product_id"] == "french-baguette"       # the next card, as before v0.20
