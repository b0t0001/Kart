"""Shopper conversations (SHOPPER_INTERACTIONS.md): two meals, voice list edits, a budget."""

from __future__ import annotations

import psycopg
import pytest

from test_cart import add


def line(row, pid):
    return next((p for p in row["plan"] if p["product_id"] == pid), None)


# ── Two meals on one trip ──

def test_the_same_product_from_two_meals_is_one_line(cart):
    row = cart("set_plan", p_plan=[
        {"product_id": "daisy-sour-cream", "qty": 1, "reason": "tacos", "meal": "Taco night", "basis": "for 4"},
        {"product_id": "mission-tortillas", "qty": 1, "meal": "Taco night"},
        {"product_id": "daisy-sour-cream", "qty": 1, "meal": "Game-night nachos", "basis": "for 6"}])
    sc = line(row, "daisy-sour-cream")
    assert [p["product_id"] for p in row["plan"]].count("daisy-sour-cream") == 1
    assert (sc["qty"], sc["meal"], sc["meals"], sc["basis"]) == (2, "Taco night", ["Taco night", "Game-night nachos"],
                                                                  "for 4 + for 6")
    assert line(row, "mission-tortillas")["meal"] == "Taco night" and "meals" not in line(row, "mission-tortillas")
    assert line(add(cart, "daisy-sour-cream"), "daisy-sour-cream")["done"] is False     # one tub isn't two
    assert line(add(cart, "daisy-sour-cream"), "daisy-sour-cream")["done"] is True


# ── Atomic voice edits ──

def test_add_to_plan_appends_or_adds_to_the_line(cart):
    cart("set_plan", p_plan=[{"product_id": "barilla-spaghetti", "qty": 1, "meal": "Pasta night", "basis": "1 lb serves 4"}])
    row = cart("add_to_plan", p_product_id="rao-marinara", p_qty=1, p_meal="Pasta night")
    assert [p["product_id"] for p in row["plan"]] == ["barilla-spaghetti", "rao-marinara"]
    row = cart("add_to_plan", p_product_id="barilla-spaghetti", p_qty=1, p_basis="leftovers", p_meal="Lunch")
    sp = line(row, "barilla-spaghetti")
    assert (sp["qty"], sp["basis"], sp["meals"]) == (2, "1 lb serves 4 + leftovers", ["Pasta night", "Lunch"])


def test_negative_qty_lowers_and_zero_drops_the_line(cart):
    cart("set_plan", p_plan=[{"product_id": "tostitos-salsa", "qty": 2}, {"product_id": "queso", "qty": 1}])
    assert line(cart("add_to_plan", p_product_id="tostitos-salsa", p_qty=-1), "tostitos-salsa")["qty"] == 1
    row = cart("add_to_plan", p_product_id="tostitos-salsa", p_qty=-1)
    assert line(row, "tostitos-salsa") is None and line(row, "queso") is not None


def test_remove_from_plan_and_unknown_products(cart):
    cart("set_plan", p_plan=[{"product_id": "queso"}, {"product_id": "black-beans"}])
    row = cart("remove_from_plan", p_product_id="queso")
    assert [p["product_id"] for p in row["plan"]] == ["black-beans"]
    assert cart("remove_from_plan", p_product_id="queso")["plan"] == row["plan"]       # not there: no-op
    with pytest.raises(psycopg.errors.RaiseException, match="unknown product"):
        cart("add_to_plan", p_product_id="cilantro")


def test_list_edits_keep_nudge_join_times(cart):
    cart("set_feature", p_feature="quantity_nudges", p_on=True)
    first = cart("set_plan", p_plan=[{"product_id": "queso"}])["plan_joined"]["queso"]
    row = cart("add_to_plan", p_product_id="black-beans")
    assert row["plan_joined"]["queso"] == first and "black-beans" in row["plan_joined"]


# ── Budget ──

def test_budget_running_total_and_estimate(cart):
    cart("set_plan", p_plan=[{"product_id": "barilla-spaghetti", "qty": 1},
                             {"product_id": "kirkland-parmesan", "qty": 1},     # $4.19, $1 off → $3.19
                             {"product_id": "rao-marinara", "qty": 1}])
    row = cart("set_budget", p_amount=30)
    assert (row["budget"], row["budget_left"], row["plan_estimate"]) == (30.0, 30.0, 7.37)
    row = add(cart, "kirkland-parmesan")
    assert (row["total"], row["budget_left"], row["plan_estimate"]) == (3.19, 26.81, 4.18)
    assert cart("set_budget", p_amount=None)["budget_left"] is None
    with pytest.raises(psycopg.errors.RaiseException, match="more than"):
        cart("set_budget", p_amount=0)


def test_budget_is_per_trip(cart):
    cart("set_budget", p_amount=25)
    row = cart("reset_cart")
    assert (row["budget"], row["budget_left"]) == (None, None)


def test_anon_can_edit_the_list_and_set_a_budget(cart, db_url):
    with psycopg.connect(db_url) as c:
        c.execute("set local role anon")
        c.execute("select add_to_plan('7', 'queso', 1, null, 'Nachos')")
        c.execute("select remove_from_plan('7', 'queso')")
        c.execute("select set_budget('7', 30)")
        c.rollback()


def test_taking_it_off_the_list_means_dont_pitch_it(cart):
    """'We've got garlic bread at home, take it off' → no 'Garlic Bread is $1 off' card this trip."""
    cart("set_plan", p_plan=[{"product_id": "barilla-spaghetti"}, {"product_id": "rao-marinara"},
                             {"product_id": "french-baguette"}])
    row = cart("remove_from_plan", p_product_id="french-baguette")
    assert "d-baguette-1off" in row["suggested_deals"]
    cart("add_to_plan", p_product_id="kirkland-parmesan")                     # Parmesan planned: no card either
    for pid in ["barilla-spaghetti", "rao-marinara"]:
        assert add(cart, pid)["suggestion"] is None
