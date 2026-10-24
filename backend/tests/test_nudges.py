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

def test_rolled_back_no_nudge_no_side_effects(cart, conn):
    """The rollback path: with the flag off (globally here), nothing nudges and nothing extra is kept."""
    flags = dict(conn.execute("select name, enabled_default from feature_flags").fetchall())
    assert flags == {"quantity_nudges": True, "quantity_nudges_midtrip": False}      # shipped defaults
    conn.execute("update feature_flags set enabled_default = false where name = 'quantity_nudges'")
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
    add(cart, "tostitos-salsa")
    row = add(cart, "tostitos-salsa")                 # salsa pairs with the Chips deal
    assert row["suggestion"]["product_id"] == "tostitos-chips" and row["nudge"] is None
    row = cart("dismiss_suggestion")
    assert row["nudge"]["kind"] == "over" and row["nudge"]["product_id"] == "tostitos-salsa"


# ── Under ──

def midtrip(cart):
    """The sub-option for one-at-a-time mid-trip 'short' nudges (off by default)."""
    cart("set_feature", p_feature="quantity_nudges_midtrip", p_on=True)


def test_under_when_the_shopper_moves_past_the_aisle(nudges):
    midtrip(nudges)
    nudges("set_plan", p_plan=TACOS_FOR_4[:2])          # avocados (Aisle 1) + tortillas (Aisle 8)
    add(nudges, "avocados")
    assert nudges("set_location", p_section="A8")["nudge"] is None        # at the tortillas: not passed yet
    n = nudges("set_location", p_section="A9")["nudge"]
    assert (n["kind"], n["product_id"], n["have"], n["need"], n["aisle"]) == ("under", "mission-tortillas", 0, 1, "Aisle 8")
    assert n["text"] == ("Before you go: you're 1 Tortillas short (4 people × 2 tacos ≈ 8 tortillas → 1 pack of 20). "
                         "It's in Aisle 8.")
    assert "savings" not in n
    row = nudges("dismiss_nudge", p_action="ok")
    assert row["nudge"] is None
    assert nudges("set_location", p_section="A9")["nudge"] is None        # not again this trip


def test_under_at_checkout_and_it_clears_when_fixed(nudges):
    add(nudges, "avocados")
    add(nudges, "tostitos-chips")
    add(nudges, "tostitos-salsa")
    n = nudges("set_cart_status", p_status="checkout")["nudge"]
    assert (n["kind"], n["product_id"]) == ("under", "mission-tortillas")
    assert add(nudges, "mission-tortillas")["nudge"] is None             # have == need: clears itself


# ── Flag plumbing ──

def test_global_default_and_overrides(cart, conn):
    """Main feature since 2026-10-24: on for every cart unless a cart opts out."""
    cart("set_plan", p_plan=TACOS_FOR_4)
    add(cart, "avocados")
    assert add(cart, "avocados")["nudge"]["kind"] == "over"               # on by default
    row = cart("set_feature", p_feature="quantity_nudges", p_on=False)
    assert row["nudge"] is None and row["features"] == {"quantity_nudges": False}   # this cart opts out
    row = cart("set_feature", p_feature="quantity_nudges", p_on=None)
    assert row["features"] == {} and row["nudge"] is None                # back on, but already said this trip


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
        ("taco-seasoning", 0, 1), ("mission-tortillas", 1, 2), ("tillamook-mexican-cheese", 0, 1), ("ground-beef", 0, 2)]
    assert n["items"][0] == {"product_id": "taco-seasoning", "name": "Taco Seasoning", "have": 0, "need": 1,
                             "aisle": "Aisle 5"}
    assert (n["product_id"], n["have"], n["need"], n["aisle"]) == ("taco-seasoning", 0, 1, "Aisle 5")  # compat
    assert n["text"] == "Before you go: you still need Taco Seasoning, Tortillas, Mexican Cheese and Ground Beef."


def test_the_checkout_list_shrinks_as_items_are_fixed(at_checkout):
    at_checkout("set_cart_status", p_status="checkout")
    n = add(at_checkout, "taco-seasoning")["nudge"]
    assert [i["product_id"] for i in n["items"]] == ["mission-tortillas", "tillamook-mexican-cheese", "ground-beef"]
    assert n["text"] == "Before you go: you still need Tortillas, Mexican Cheese and Ground Beef."


def test_skip_answers_the_whole_list_once(at_checkout):
    at_checkout("set_cart_status", p_status="checkout")
    row = at_checkout("dismiss_nudge", p_action="skip")
    assert row["nudge"] is None and row["status"] == "checkout"
    assert {"done:ground-beef", "done:taco-seasoning", "done:mission-tortillas"} <= set(row["nudged"])
    assert at_checkout("set_location", p_section="A9")["nudge"] is None    # none of them comes back
    at_checkout("set_cart_status", p_status="shopping")
    assert at_checkout("set_cart_status", p_status="checkout")["nudge"] is None   # a skip is final


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
    midtrip(at_checkout)
    row = at_checkout("set_location", p_section="A9")          # walked past everything
    assert row["nudge"]["kind"] == "under" and "items" not in row["nudge"]   # mid-trip: one at a time
    n = at_checkout("set_cart_status", p_status="checkout")["nudge"]
    assert len(n["items"]) == 4                                  # including the one already showing



# ── "Go get them" is a promise: the next checkout re-lists what's still short ──

def test_shop_then_checkout_again_relists_only_whats_still_short(at_checkout):
    at_checkout("set_cart_status", p_status="checkout")
    row = at_checkout("dismiss_nudge", p_action="shop")
    assert row["status"] == "shopping" and not any(m.startswith("done:") for m in row["nudged"])
    for pid in ["taco-seasoning", "tillamook-mexican-cheese", "ground-beef", "ground-beef"]:
        add(at_checkout, pid)                         # got all but the 2nd tortilla pack
    n = at_checkout("set_cart_status", p_status="checkout")["nudge"]
    assert [(i["product_id"], i["have"], i["need"]) for i in n["items"]] == [("mission-tortillas", 1, 2)]
    assert n["text"] == "Before you go: you still need Tortillas."
    at_checkout("dismiss_nudge", p_action="skip")
    at_checkout("set_cart_status", p_status="shopping")
    assert at_checkout("set_cart_status", p_status="checkout")["nudge"] is None


def test_promised_items_dont_nag_one_by_one_while_shopping(at_checkout):
    at_checkout("set_cart_status", p_status="checkout")
    at_checkout("dismiss_nudge", p_action="shop")
    assert at_checkout("set_location", p_section="A9")["nudge"] is None       # walking past: no singles


def test_loop_guard_after_two_promises(at_checkout):
    for _ in range(2):
        assert at_checkout("set_cart_status", p_status="checkout")["nudge"]["items"]
        at_checkout("dismiss_nudge", p_action="shop")
    row = at_checkout("set_cart_status", p_status="checkout")             # 3rd time, still short
    assert row["nudge"] is None
    assert {"done:ground-beef", "done:mission-tortillas"} <= set(row["nudged"])


def test_ok_on_a_mid_trip_nudge_is_final_for_checkout_too(nudges):
    midtrip(nudges)
    nudges("set_plan", p_plan=TACOS_FOR_4[:2])          # avocados (Aisle 1) + tortillas (Aisle 8)
    add(nudges, "avocados")
    assert nudges("set_location", p_section="A9")["nudge"]["product_id"] == "mission-tortillas"
    nudges("dismiss_nudge", p_action="ok")
    assert nudges("set_cart_status", p_status="checkout")["nudge"] is None    # tortillas: answered already



# ── Mid-trip "short" nudges are off by default (voice-call review, DEMO_PLAN §3) ──

PASTA_FOR_4 = [{"product_id": "barilla-spaghetti", "qty": 1, "basis": "1 lb serves 4"},
               {"product_id": "rao-marinara", "qty": 1},
               {"product_id": "french-baguette", "qty": 1}]


@pytest.fixture
def pasta(cart):
    cart("set_feature", p_feature="quantity_nudges", p_on=True)
    cart("set_plan", p_plan=PASTA_FOR_4)
    return cart


def say_yes_to_the_parmesan(cart):
    row = add(cart, "barilla-spaghetti")              # Aisle 6, already past the Parmesan's Aisle 4
    assert row["suggestion"]["product_id"] == "kirkland-parmesan"
    return cart("set_plan", p_plan=PASTA_FOR_4 + [{"product_id": "kirkland-parmesan", "qty": 1}])


def test_a_yes_behind_the_shopper_stays_silent(pasta):
    """(a) the Parmesan joins the plan while the shopper stands in Aisle 6: no 'one Parmesan short'."""
    assert say_yes_to_the_parmesan(pasta)["nudge"] is None
    assert add(pasta, "rao-marinara")["nudge"] is None


def test_items_behind_the_shopper_wait_for_checkout(pasta):
    """(b) the garlic bread (Aisle 2) is behind the shopper, who went straight to the pasta."""
    add(pasta, "barilla-spaghetti")
    assert pasta("dismiss_suggestion")["nudge"] is None
    assert add(pasta, "rao-marinara")["nudge"] is None
    assert pasta("set_location", p_section="A9")["nudge"] is None
    n = pasta("set_cart_status", p_status="checkout")["nudge"]
    assert n["text"] == "Before you go: you still need Garlic Bread."


def test_with_the_sub_option_an_item_must_be_passed_after_it_joined(pasta):
    midtrip(pasta)
    pasta("set_plan", p_plan=PASTA_FOR_4[:2])                           # no bread: only the Parmesan matters here
    add(pasta, "barilla-spaghetti")
    row = pasta("set_plan", p_plan=PASTA_FOR_4[:2] + [{"product_id": "kirkland-parmesan", "qty": 1}])
    assert row["nudge"] is None                                          # joined while already past it
    assert add(pasta, "rao-marinara")["nudge"] is None                  # same aisle: hasn't moved on
    pasta("dismiss_suggestion")                                          # the Garlic Bread card goes first
    n = pasta("set_location", p_section="A9")["nudge"]                  # moved on past it since joining
    assert (n["kind"], n["product_id"]) == ("under", "kirkland-parmesan")


def test_join_times_are_only_kept_with_nudges_on(cart):
    cart("set_feature", p_feature="quantity_nudges", p_on=False)
    row = cart("set_plan", p_plan=PASTA_FOR_4)
    assert row["plan_joined"] == {}
