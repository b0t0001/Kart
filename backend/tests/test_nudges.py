"""Quantity nudges (CONTRACT v0.12, BETA): feature quantity_nudges, off by default."""

from __future__ import annotations

import psycopg
import pytest

from test_cart import add, current, remove

TACOS_FOR_4 = [
    {"product_id": "mission-tortillas", "reason": "tacos", "qty": 1, "basis": "4 people × 2 tacos ≈ 8 tortillas → 1 pack of 20"},
    {"product_id": "avocados", "reason": "guac", "qty": 1, "basis": "taco night for 4 → 1 bag of 5"},
    {"product_id": "tostitos-salsa", "reason": "salsa", "qty": 1},
    {"product_id": "tostitos-chips", "reason": "chips", "qty": 1},     # planned, so no Chips deal card
]


@pytest.fixture
def nudges(cart):
    """Cart 7 with the flag on for this cart only, and the taco plan."""
    cart("set_feature", p_feature="quantity_nudges", p_on=True)
    cart("set_plan", p_plan=TACOS_FOR_4)
    return cart


# ── Off (the default): nothing changes ──

def test_off_by_default_no_nudge_no_side_effects(cart, conn):
    assert conn.execute("select enabled_default from feature_flags where name = 'quantity_nudges'").fetchone()[0] is False
    cart("set_plan", p_plan=TACOS_FOR_4)
    for _ in range(3):
        row = add(cart, "avocados")
    row = cart("set_location", p_section="A9")
    row = cart("set_cart_status", p_status="checkout")
    assert row["nudge"] is None and row["nudged"] == [] and row["features"] == {}


def test_basis_passes_through_either_way(cart):
    row = cart("set_plan", p_plan=TACOS_FOR_4)
    tortillas = next(p for p in row["plan"] if p["product_id"] == "mission-tortillas")
    assert tortillas["basis"] == "4 people × 2 tacos ≈ 8 tortillas → 1 pack of 20"


# ── Over ──

def test_over_nudge_with_savings_then_keep(nudges):
    add(nudges, "avocados")
    row = add(nudges, "avocados")
    n = row["nudge"]
    assert (n["kind"], n["product_id"], n["have"], n["need"], n["savings"]) == ("over", "avocados", 2, 1, 5.99)
    assert n["text"] == ("That's 2 Avocados in the cart, and your list needs 1 (taco night for 4 → 1 bag of 5). "
                         "Keep the extra 1?")
    row = add(nudges, "avocados")                     # a 3rd bag updates the same nudge
    assert (row["nudge"]["have"], row["nudge"]["savings"]) == (3, 11.98)
    row = nudges("dismiss_nudge", p_action="keep")
    assert row["nudge"] is None
    assert next(p for p in row["plan"] if p["product_id"] == "avocados")["qty"] == 3
    row = add(nudges, "avocados")                     # once per product per direction per trip
    assert row["nudge"] is None and "over:avocados" in row["nudged"]


def test_over_clears_itself_when_counts_match(nudges):
    nudges("set_plan", p_plan=[{"product_id": "tostitos-salsa", "qty": 1},     # nothing behind Aisle 5,
                               {"product_id": "tostitos-chips", "qty": 1}])    # and Chips is planned: no card
    add(nudges, "tostitos-salsa")
    assert add(nudges, "tostitos-salsa")["nudge"]["kind"] == "over"
    assert remove(nudges, "tostitos-salsa")["nudge"] is None


def test_impulse_buys_are_never_nudged(nudges):
    add(nudges, "bananas")
    assert add(nudges, "bananas")["nudge"] is None


def test_a_deal_card_goes_first(cart):
    cart("set_feature", p_feature="quantity_nudges", p_on=True)
    cart("set_plan", p_plan=[p for p in TACOS_FOR_4 if p["product_id"] != "tostitos-chips"])
    add(cart, "avocados")
    row = add(cart, "avocados")                       # avocados pair with the Chips deal
    assert row["suggestion"]["product_id"] == "tostitos-chips" and row["nudge"] is None
    row = cart("dismiss_suggestion")
    assert row["nudge"]["kind"] == "over" and row["nudge"]["product_id"] == "avocados"


# ── Under ──

def test_under_when_the_shopper_moves_past_the_aisle(nudges):
    add(nudges, "avocados")                           # Aisle 1
    assert nudges("set_location", p_section="A2")["nudge"] is None        # at the tortillas: not passed yet
    n = nudges("set_location", p_section="A3")["nudge"]
    assert (n["kind"], n["product_id"], n["have"], n["need"], n["aisle"]) == ("under", "mission-tortillas", 0, 1, "Aisle 2")
    assert n["text"] == ("Before you go: you're 1 Tortillas short (4 people × 2 tacos ≈ 8 tortillas → 1 pack of 20). "
                         "It's in Aisle 2.")
    assert "savings" not in n
    row = nudges("dismiss_nudge", p_action="ok")
    assert row["nudge"] is None
    assert nudges("set_location", p_section="A4")["nudge"] is None        # not again this trip


def test_under_at_checkout_and_it_clears_when_fixed(nudges):
    add(nudges, "avocados")
    add(nudges, "tostitos-chips")
    add(nudges, "tostitos-salsa")
    n = nudges("set_cart_status", p_status="checkout")["nudge"]
    assert (n["kind"], n["product_id"]) == ("under", "mission-tortillas")
    assert add(nudges, "mission-tortillas")["nudge"] is None             # have == need: clears itself


# ── Flag plumbing ──

def test_global_default_and_overrides(cart, conn):
    try:
        conn.execute("update feature_flags set enabled_default = true where name = 'quantity_nudges'")
        cart("set_plan", p_plan=TACOS_FOR_4)
        add(cart, "avocados")
        assert add(cart, "avocados")["nudge"]["kind"] == "over"           # on for everyone
        row = cart("set_feature", p_feature="quantity_nudges", p_on=False)
        assert row["nudge"] is None and row["features"] == {"quantity_nudges": False}   # this cart opts out
        row = cart("set_feature", p_feature="quantity_nudges", p_on=None)
        assert row["features"] == {}                                    # back to the default
    finally:
        conn.execute("update feature_flags set enabled_default = false where name = 'quantity_nudges'")


def test_unknown_feature_and_bad_action_are_refused(cart):
    with pytest.raises(psycopg.errors.RaiseException, match="unknown feature"):
        cart("set_feature", p_feature="time_travel", p_on=True)
    with pytest.raises(psycopg.errors.RaiseException, match="keep, ok, skip or shop"):
        cart("dismiss_nudge", p_action="maybe")


def test_reset_clears_nudges_but_keeps_the_switch(nudges, conn):
    add(nudges, "avocados")
    add(nudges, "avocados")
    row = nudges("reset_cart")
    assert (row["nudge"], row["nudged"], row["features"]) == (None, [], {"quantity_nudges": True})


def test_anon_can_flip_its_cart_and_answer_nudges(db_url):
    with psycopg.connect(db_url) as c:
        c.execute("set local role anon")
        c.execute("select set_feature('7', 'quantity_nudges', true)")
        c.execute("select dismiss_nudge('7', 'ok')")
        assert c.execute("select enabled_default from feature_flags").fetchone()[0] is False
        c.rollback()


# ── Checkout: ONE combined under nudge ──

TACOS_FOR_8 = [
    {"product_id": "mission-tortillas", "qty": 2, "basis": "8 people × 2 tacos ≈ 16 tortillas → 2 packs of 10"},
    {"product_id": "ground-beef", "qty": 2},
    {"product_id": "tillamook-mexican-cheese", "qty": 1},
    {"product_id": "taco-seasoning", "qty": 1},
    {"product_id": "tostitos-salsa", "qty": 1},
    {"product_id": "tostitos-chips", "qty": 1},
]


@pytest.fixture
def at_checkout(cart):
    """Flag on, taco plan for 8, one tortilla pack, the chips and the salsa in the cart, then checkout."""
    cart("set_feature", p_feature="quantity_nudges", p_on=True)
    cart("set_plan", p_plan=TACOS_FOR_8)
    for pid in ["mission-tortillas", "tostitos-chips", "tostitos-salsa"]:
        add(cart, pid)
    cart("dismiss_suggestion")                        # Sour Cream pairs with the tortillas
    return cart


def test_checkout_gathers_every_short_item_into_one_nudge(at_checkout):
    n = at_checkout("set_cart_status", p_status="checkout")["nudge"]
    assert n["kind"] == "under"
    # walking order from where the shopper is (Aisle 5): ahead first, then back toward the entrance
    assert [(i["product_id"], i["have"], i["need"]) for i in n["items"]] == [
        ("taco-seasoning", 0, 1), ("tillamook-mexican-cheese", 0, 1), ("ground-beef", 0, 2), ("mission-tortillas", 1, 2)]
    assert n["items"][0] == {"product_id": "taco-seasoning", "name": "Taco Seasoning", "have": 0, "need": 1,
                             "aisle": "Aisle 5"}
    assert (n["product_id"], n["have"], n["need"], n["aisle"]) == ("taco-seasoning", 0, 1, "Aisle 5")  # compat
    assert n["text"] == "Before you go: you still need Taco Seasoning, Mexican Cheese, Ground Beef and Tortillas."


def test_the_checkout_list_shrinks_as_items_are_fixed(at_checkout):
    at_checkout("set_cart_status", p_status="checkout")
    n = add(at_checkout, "taco-seasoning")["nudge"]
    assert [i["product_id"] for i in n["items"]] == ["tillamook-mexican-cheese", "ground-beef", "mission-tortillas"]
    assert n["text"] == "Before you go: you still need Mexican Cheese, Ground Beef and Tortillas."


def test_skip_answers_the_whole_list_once(at_checkout):
    at_checkout("set_cart_status", p_status="checkout")
    row = at_checkout("dismiss_nudge", p_action="skip")
    assert row["nudge"] is None and row["status"] == "checkout"
    assert {"under:ground-beef", "under:taco-seasoning", "under:mission-tortillas"} <= set(row["nudged"])
    assert at_checkout("set_location", p_section="A9")["nudge"] is None    # none of them comes back


def test_go_get_them_returns_to_shopping(at_checkout):
    at_checkout("set_cart_status", p_status="checkout")
    row = at_checkout("dismiss_nudge", p_action="shop")
    assert row["nudge"] is None and row["status"] == "shopping"
    assert row["next_step"].startswith("Aisle ")                         # the route picks them up again


def test_one_short_item_at_checkout_reads_naturally(nudges):
    for pid in ["avocados", "tostitos-salsa", "tostitos-chips"]:
        add(nudges, pid)
    n = nudges("set_cart_status", p_status="checkout")["nudge"]
    assert n["text"] == "Before you go: you still need Tortillas." and len(n["items"]) == 1


def test_short_names_fit_and_the_lcd_still_truncates(conn):
    longest = conn.execute("select max(char_length(short_name)) from products").fetchone()[0]
    assert longest <= 16
    assert conn.execute("select fmt_lcd('A5', 'Taco Seasoning', '-20%')").fetchone()[0] == "A5 Taco Sea -20%"


def test_checkout_upgrades_a_mid_trip_nudge_to_the_full_list(at_checkout):
    row = at_checkout("set_location", p_section="A9")          # walked past everything
    assert row["nudge"]["kind"] == "under" and "items" not in row["nudge"]   # mid-trip: one at a time
    n = at_checkout("set_cart_status", p_status="checkout")["nudge"]
    assert len(n["items"]) == 4                                  # including the one already showing
