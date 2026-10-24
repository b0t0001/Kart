"""The iPad's trip RPCs (CONTRACT §5a P2–P8)."""

from __future__ import annotations

import uuid

import psycopg
import pytest

import kartdb
from test_cart import PASTA, add, current


# ── P2 status ──

def test_reset_starts_a_shopping_trip(cart):
    row = cart("reset_cart")
    assert row["status"] == "shopping" and row["trip_started_at"] is not None


def test_set_cart_status(cart):
    assert cart("set_cart_status", p_status="checkout")["status"] == "checkout"
    assert cart("set_cart_status", p_status="idle")["status"] == "idle"
    with pytest.raises(psycopg.errors.RaiseException):
        cart("set_cart_status", p_status="paid")       # only checkout() may set paid


# ── P3 location ──

def test_add_sets_location_and_reset_clears_it(cart):
    row = add(cart, "kirkland-parmesan")
    assert row["location"]["section"] == "A4" and row["location"]["source"] == "item"
    assert cart("reset_cart")["location"] is None


@pytest.mark.parametrize("said", ["A5", "a5", "5", "Aisle 5", "aisle 5"])
def test_set_location_understands_how_people_say_it(cart, said):
    row = cart("set_location", p_section=said)
    assert row["location"]["section"] == "A5" and row["location"]["source"] == "voice"


def test_set_location_rejects_unknown_aisle(cart):
    with pytest.raises(psycopg.errors.RaiseException):
        cart("set_location", p_section="aisle 42")


def test_voice_location_drives_the_route(cart):
    cart("set_plan", p_plan=PASTA)
    row = cart("set_location", p_section="A7")         # past the pasta: bakery ahead, then walk back
    assert [p["product_id"] for p in row["plan"]] == [
        "french-baguette", "rao-marinara", "barilla-spaghetti", "kirkland-parmesan"]
    assert row["next_step"] == "Aisle 8 → Garlic Bread, $1 off"


# ── P4 resolving unrecognized items ──

def unknown_event(cart):
    eid = str(uuid.uuid4())
    cart("apply_cart_event", p_type="added", p_product_id=None, p_confidence=0.3, p_source="vision",
         p_label="blue box", p_event_id=eid, p_method="none")
    return eid


def resolved_at(conn, eid):
    return conn.execute("select resolved_at from cart_events where event_id = %s", [eid]).fetchone()[0]


def test_confirming_an_unknown_item_adds_it_and_resolves_the_card(cart, conn):
    eid = unknown_event(cart)
    row = cart("apply_cart_event", p_type="added", p_product_id="barilla-spaghetti", p_confidence=1.0,
               p_source="manual", p_label="confirmed", p_resolves_event_id=eid)
    assert row["items"][0]["product_id"] == "barilla-spaghetti"
    assert resolved_at(conn, eid) is not None


def test_remove_on_a_confirm_card_just_resolves_it(cart, conn):
    eid = unknown_event(cart)
    row = cart("apply_cart_event", p_type="removed", p_product_id=None, p_confidence=1.0,
               p_source="manual", p_label="not an item", p_resolves_event_id=eid)
    assert row["items"] == [] and resolved_at(conn, eid) is not None


def test_manual_events_get_an_event_id(cart, conn):
    add(cart, "bananas", source="manual")
    assert conn.execute("select count(*) from cart_events where event_id is null").fetchone()[0] == 0


# ── P6 transcript ──

def test_transcript_lines_carry_the_trip_and_reset_clears_them(cart, conn):
    trip = cart("reset_cart")["trip_id"]
    line = cart("append_transcript", p_role="user", p_text="pasta dinner for my family")
    assert line["trip_id"] == trip and line["role"] == "user"
    cart("append_transcript", p_role="agent", p_text="Got it.")
    assert conn.execute("select count(*) from transcript where cart_id = '7'").fetchone()[0] == 2
    cart("reset_cart")
    assert conn.execute("select count(*) from transcript where cart_id = '7'").fetchone()[0] == 0


def test_transcript_role_is_checked(cart):
    with pytest.raises(psycopg.errors.RaiseException):
        cart("append_transcript", p_role="judge", p_text="hi")


# ── P8 checkout ──

def test_checkout_writes_receipt_takes_stock_and_sets_paid(cart, conn):
    add(cart, "barilla-spaghetti")
    add(cart, "kirkland-parmesan")
    stock_before = conn.execute("select stock from products where id = 'kirkland-parmesan'").fetchone()[0]
    receipt = cart("checkout", p_provider="simulated")
    assert (receipt["total"], receipt["savings"], receipt["item_count"]) == (5.98, 1.0, 2)
    assert receipt["status"] == "paid" and receipt["duration_s"] >= 0 and len(receipt["items"]) == 2
    assert current(conn)["status"] == "paid"
    assert conn.execute("select stock from products where id = 'kirkland-parmesan'").fetchone()[0] == stock_before - 1


def test_checkout_twice_returns_the_same_receipt(cart, conn):
    add(cart, "bananas")
    first = cart("checkout", p_provider="simulated")
    second = cart("checkout", p_provider="simulated")
    assert first["id"] == second["id"]
    assert conn.execute("select stock from products where id = 'bananas'").fetchone()[0] == 49


def test_checkout_blocks_on_unresolved_items(cart):
    add(cart, "bananas")
    eid = unknown_event(cart)
    with pytest.raises(psycopg.errors.RaiseException, match=r"^unresolved_items: 1 "):  # iPad matches this prefix
        cart("checkout", p_provider="simulated")
    cart("apply_cart_event", p_type="removed", p_product_id=None, p_confidence=1.0,
         p_source="manual", p_label="not an item", p_resolves_event_id=eid)
    assert cart("checkout", p_provider="simulated")["total"] == 1.49


# ── Analytics (06_analytics.sql) ──

def offers(conn):
    return conn.execute("select o.deal_id, o.accepted_at is not null, o.dismissed_at is not null "
                        "from deal_offers o join carts c using (cart_id) "
                        "where o.cart_id = '7' and o.trip_id = c.trip_id order by o.id").fetchall()


def test_offers_are_logged_with_their_outcome(cart, conn):
    add(cart, "barilla-spaghetti")                    # offers Parmesan
    add(cart, "kirkland-parmesan")                    # taken → offers Baguette
    cart("dismiss_suggestion")                        # "No thanks" to Baguette
    assert offers(conn) == [("d-parm-3off", True, False), ("d-baguette-1off", False, True)]


def test_store_insights_after_a_paid_trip(cart, conn):
    conn.execute("delete from receipts; delete from deal_offers")
    add(cart, "barilla-spaghetti")
    add(cart, "kirkland-parmesan")
    cart("checkout", p_provider="simulated")
    i = conn.execute("select to_jsonb(s) from store_insights s").fetchone()[0]
    assert (i["trips"], i["avg_basket"], i["avg_items"], i["deals_offered"], i["deals_accepted"]) == \
        (1, 5.98, 2.0, 2, 1)
    assert (i["deal_conversion_pct"], i["deal_revenue"]) == (50, 3.99)
    parm = conn.execute("select to_jsonb(d) from deal_performance d where deal_id = 'd-parm-3off'").fetchone()[0]
    assert (parm["offered"], parm["accepted"], parm["conversion_pct"], parm["units_sold"]) == (1, 1, 100, 1)


def test_analytics_are_not_public(db_url):
    with psycopg.connect(db_url) as c:
        c.execute("set local role anon")
        for sql in ["select * from store_insights", "select * from deal_offers"]:
            c.execute("savepoint s")
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                c.execute(sql)
            c.execute("rollback to savepoint s")
        c.rollback()


def test_rehearsal_carts_stay_out_of_the_numbers(cart, conn):
    conn.execute("delete from receipts; delete from deal_offers")
    for test_cart in ["ipad-live", "cv-e2e-1234", "ios-it-abc", "agent-it-x", "e2e-99", "smoke-1"]:
        kartdb.rpc(conn, "apply_cart_event", p_cart_id=test_cart, p_type="added", p_product_id="barilla-spaghetti",
                   p_confidence=0.9, p_source="vision", p_label="x")
        kartdb.rpc(conn, "checkout", p_cart_id=test_cart, p_provider="simulated")
    add(cart, "bananas")
    cart("checkout", p_provider="simulated")
    i = conn.execute("select to_jsonb(s) from store_insights s").fetchone()[0]
    assert (i["trips"], i["avg_basket"], i["deals_offered"]) == (1, 1.49, 0)
    parm = conn.execute("select offered from deal_performance where deal_id = 'd-parm-3off'").fetchone()[0]
    assert parm == 0


# ── "That's mine" (v0.15): resolution on unknown items ──

def resolution(conn, eid):
    return conn.execute("select resolved_at is not null, resolution from cart_events where event_id = %s",
                        [eid]).fetchone()


def test_thats_mine_unblocks_checkout_without_billing(cart, conn):
    add(cart, "bananas")
    eid = unknown_event(cart)
    with pytest.raises(psycopg.errors.RaiseException, match="unresolved_items"):
        cart("checkout", p_provider="simulated")
    row = cart("mark_personal", p_event_id=eid)
    assert (row["total"], row["item_count"]) == (1.49, 1)          # the bill is unchanged
    assert resolution(conn, eid) == (True, "personal")
    assert cart("checkout", p_provider="simulated")["total"] == 1.49


def test_mark_personal_only_takes_an_open_unknown_on_that_cart(cart, conn):
    eid = unknown_event(cart)
    with pytest.raises(psycopg.errors.RaiseException, match="not an unresolved unknown"):
        kartdb.rpc(conn, "mark_personal", p_cart_id="other-cart", p_event_id=eid)      # wrong cart
    cart("mark_personal", p_event_id=eid)
    with pytest.raises(psycopg.errors.RaiseException, match="not an unresolved unknown"):
        cart("mark_personal", p_event_id=eid)                                          # already answered
    known = str(uuid.uuid4())
    cart("apply_cart_event", p_type="added", p_product_id="bananas", p_confidence=0.9, p_source="vision",
         p_label="bananas", p_event_id=known)
    with pytest.raises(psycopg.errors.RaiseException, match="not an unresolved unknown"):
        cart("mark_personal", p_event_id=known)                                        # a recognized item


def test_manual_resolutions_say_what_happened(cart, conn):
    yes, gone = unknown_event(cart), unknown_event(cart)
    cart("apply_cart_event", p_type="added", p_product_id="barilla-spaghetti", p_confidence=1.0,
         p_source="manual", p_label="confirmed", p_resolves_event_id=yes)
    cart("apply_cart_event", p_type="removed", p_product_id=None, p_confidence=1.0,
         p_source="manual", p_label="not an item", p_resolves_event_id=gone)
    assert (resolution(conn, yes), resolution(conn, gone)) == ((True, "confirmed"), (True, "removed"))


def test_anon_can_say_thats_mine(cart, db_url):
    eid = unknown_event(cart)
    with psycopg.connect(db_url) as c:
        c.execute("set local role anon")
        c.execute("select mark_personal('7', %s)", [eid])
        c.rollback()
