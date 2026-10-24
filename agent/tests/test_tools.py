import json

import pytest

from kart_agent.tools import TOOLS, run_tool

from fakes import FakeBackend


@pytest.fixture
def backend():
    return FakeBackend()


def ctx(backend):
    return {"backend": backend, "cart_id": "7", "trip_id": "trip-1"}


def test_every_tool_streams_eagerly_and_has_a_schema():
    names = {t["name"] for t in TOOLS}
    assert names == {"search_catalog", "get_cart", "set_plan", "add_to_plan", "remove_from_plan", "dismiss_nudge", "get_deals", "set_location",
                     "dismiss_suggestion", "confirm_item", "start_checkout", "not_sold_here", "undo_last_edit",
                     "set_budget"}
    assert all(t["eager_input_streaming"] and t["input_schema"]["type"] == "object" for t in TOOLS)


async def test_search_catalog_returns_live_prices(backend):
    out = json.loads(await run_tool("search_catalog", {"query": "pasta sauce"}, ctx(backend)))
    assert out[0]["id"] == "rao-marinara"
    assert {"short_name", "price", "sale_price", "deal_label", "aisle", "in_stock"} <= out[0].keys()


async def test_set_plan_rejects_unknown_and_sold_out_products(backend):
    out = json.loads(await run_tool("set_plan", {"items": [
        {"product_id": "barilla-spaghetti", "reason": "pasta dinner"},
        {"product_id": "cilantro", "reason": "tacos"},
        {"product_id": "bananas", "reason": "breakfast"}]}, ctx(backend)))
    assert out["planned"] == ["barilla-spaghetti"]
    assert out["not_in_store"] == ["cilantro"] and out["out_of_stock"] == ["bananas"]
    name, params = backend.calls[-1]
    assert name == "set_plan" and params["p_plan"] == [{"product_id": "barilla-spaghetti", "reason": "pasta dinner", "qty": 1}]


async def test_add_to_plan_keeps_existing_lines(backend):
    backend.cart["plan"] = [{"product_id": "barilla-spaghetti", "reason": "pasta dinner", "qty": 1, "done": False}]
    await run_tool("add_to_plan", {"product_id": "kirkland-parmesan", "reason": "deal"}, ctx(backend))
    assert [p["product_id"] for p in backend.cart["plan"]] == ["barilla-spaghetti", "kirkland-parmesan"]


async def test_confirm_item_resolves_the_oldest_unknown(backend):
    backend.unresolved = [{"event_id": "e-1", "label": "red jar"}, {"event_id": "e-2", "label": "box"}]
    out = json.loads(await run_tool("confirm_item", {"product_id": "rao-marinara"}, ctx(backend)))
    assert out["confirmed"] == "rao-marinara"
    name, params = backend.calls[-1]
    assert name == "apply_cart_event" and params["p_resolves_event_id"] == "e-1" and params["p_source"] == "manual"


async def test_invalid_input_is_an_error_not_a_crash(backend):
    out = json.loads(await run_tool("set_location", {"section": 5}, ctx(backend)))
    assert "error" in out
    out = json.loads(await run_tool("no_such_tool", {}, ctx(backend)))
    assert "error" in out


async def test_start_checkout_and_dismiss(backend):
    await run_tool("start_checkout", {}, ctx(backend))
    await run_tool("dismiss_suggestion", {}, ctx(backend))
    assert [c[0] for c in backend.calls] == ["set_cart_status", "dismiss_suggestion"]
    assert backend.calls[0][1]["p_status"] == "checkout"



async def test_add_to_plan_sets_the_amount_of_a_planned_line(backend):
    await run_tool("set_plan", {"items": [{"product_id": "barilla-spaghetti", "reason": "pasta"}]}, ctx(backend))
    out = json.loads(await run_tool("add_to_plan", {"product_id": "barilla-spaghetti", "reason": "pasta", "qty": 3}, ctx(backend)))
    assert [(p["product_id"], p["qty"]) for p in backend.cart["plan"]] == [("barilla-spaghetti", 3)]
    assert "notes" not in out


async def test_amounts_never_go_above_stock_and_say_so(backend):
    out = json.loads(await run_tool("set_plan", {"items": [{"product_id": "kirkland-parmesan", "reason": "pasta", "qty": 5}]},
                                    ctx(backend)))
    assert [(p["product_id"], p["qty"]) for p in backend.cart["plan"]] == [("kirkland-parmesan", 2)]
    assert out["notes"] == ["Only 2 Parmesan in stock: planned 2, not 5."]


async def test_remove_from_plan_takes_one_line_off(backend):
    await run_tool("set_plan", {"items": [{"product_id": "barilla-spaghetti", "reason": "pasta"},
                                          {"product_id": "rao-marinara", "reason": "pasta"}]}, ctx(backend))
    await run_tool("remove_from_plan", {"product_id": "rao-marinara"}, ctx(backend))
    assert [p["product_id"] for p in backend.cart["plan"]] == ["barilla-spaghetti"]


async def test_search_shows_how_many_are_in_stock(backend):
    found = json.loads(await run_tool("search_catalog", {"query": "parmesan"}, ctx(backend)))
    assert found[0]["stock"] == 2



async def test_every_planned_line_keeps_its_basis(backend):
    await run_tool("set_plan", {"items": [{"product_id": "barilla-spaghetti", "reason": "pasta", "qty": 2,
                                           "basis": "8 people x 1/4 lb = 2 lb"}]}, ctx(backend))
    await run_tool("add_to_plan", {"product_id": "rao-marinara", "reason": "pasta", "basis": "one jar for 2 lb"}, ctx(backend))
    assert [(p["product_id"], p.get("basis")) for p in backend.cart["plan"]] == [
        ("barilla-spaghetti", "8 people x 1/4 lb = 2 lb"), ("rao-marinara", "one jar for 2 lb")]


async def test_dismiss_nudge_passes_keep_or_ok(backend):
    await run_tool("dismiss_nudge", {"action": "keep"}, ctx(backend))
    await run_tool("dismiss_nudge", {"action": "shop"}, ctx(backend))
    assert ("dismiss_nudge", {"p_cart_id": "7", "p_action": "shop"}) in backend.calls
    out = json.loads(await run_tool("dismiss_nudge", {"action": "maybe"}, ctx(backend)))
    assert ("dismiss_nudge", {"p_cart_id": "7", "p_action": "keep"}) in backend.calls and "error" in out



async def test_set_plan_remembers_what_the_trip_is_for(backend):
    c = ctx(backend)
    await run_tool("set_plan", {"meal": "taco night for 4", "items": [{"product_id": "barilla-spaghetti", "reason": "x"}]}, c)
    assert c["meal"] == "taco night for 4"


# Editing the list by voice: every edit comes back with the line Kart reads back (facts from the live catalog).

def planned(backend):
    return {p["product_id"]: p["qty"] for p in backend.cart["plan"]}


async def test_adding_a_product_reads_back_where_it_is(backend):
    out = json.loads(await run_tool("add_to_plan", {"product_id": "daisy-sour-cream", "reason": "tacos"}, ctx(backend)))
    assert out["readback"] == "Added sour cream, Aisle 8." and planned(backend) == {"daisy-sour-cream": 1}


async def test_another_one_raises_the_amount_by_one(backend):
    backend.cart["plan"] = [{"product_id": "barilla-spaghetti", "reason": "pasta night", "qty": 1}]
    out = json.loads(await run_tool("add_to_plan", {"product_id": "barilla-spaghetti", "reason": "pasta night",
                                                    "change_by": 1}, ctx(backend)))
    assert out["readback"] == "Two boxes of spaghetti now." and planned(backend) == {"barilla-spaghetti": 2}


async def test_one_less_of_the_last_one_takes_it_off(backend):
    backend.cart["plan"] = [{"product_id": "tostitos-salsa", "reason": "nachos", "qty": 1}]
    out = json.loads(await run_tool("add_to_plan", {"product_id": "tostitos-salsa", "reason": "nachos", "change_by": -1},
                                    ctx(backend)))
    assert out["readback"] == "Took salsa off your list." and planned(backend) == {}


async def test_make_it_two_sets_the_amount(backend):
    backend.cart["plan"] = [{"product_id": "barilla-spaghetti", "reason": "pasta night", "qty": 3}]
    out = json.loads(await run_tool("add_to_plan", {"product_id": "barilla-spaghetti", "reason": "pasta night", "qty": 2},
                                    ctx(backend)))
    assert out["readback"] == "Two boxes of spaghetti now." and planned(backend) == {"barilla-spaghetti": 2}


async def test_adding_what_is_already_on_the_list_says_so(backend):
    backend.cart["plan"] = [{"product_id": "tostitos-salsa", "reason": "nachos", "qty": 1}]
    out = json.loads(await run_tool("add_to_plan", {"product_id": "tostitos-salsa", "reason": "nachos"}, ctx(backend)))
    assert out["readback"] == "Salsa's already on your list." and planned(backend) == {"tostitos-salsa": 1}


VERDE = {"id": "salsa-verde", "name": "Salsa Verde, 16 oz jar", "short_name": "Salsa Verde", "price": 3.99,
         "sale_price": 3.99, "deal_label": None, "aisle": "Aisle 5", "section": "A5", "in_stock": True, "stock": 12,
         "category": "salsa", "tags": ["tacos", "mexican"]}


async def test_a_sold_out_product_is_not_added_and_comes_with_a_real_stand_in(backend):
    backend.catalog.append(dict(VERDE))
    salsa = next(p for p in backend.catalog if p["id"] == "tostitos-salsa")
    salsa["stock"], salsa["in_stock"] = 0, False
    out = json.loads(await run_tool("add_to_plan", {"product_id": "tostitos-salsa", "reason": "nachos"}, ctx(backend)))
    assert out["readback"] == "Sorry, salsa is sold out today." and planned(backend) == {}
    assert [s["id"] for s in out["substitutes"]] == ["salsa-verde"]   # the same kind only: no queso for salsa
    assert out["substitutes"][0]["aisle"] == "Aisle 5"


async def test_a_sold_out_product_with_nothing_of_its_kind_gets_no_substitutes(backend):
    salsa = next(p for p in backend.catalog if p["id"] == "tostitos-salsa")
    salsa["stock"], salsa["in_stock"] = 0, False
    out = json.loads(await run_tool("add_to_plan", {"product_id": "tostitos-salsa", "reason": "nachos"}, ctx(backend)))
    assert out["substitutes"] == []


async def test_swap_replaces_one_product_with_another_in_one_update(backend):
    backend.cart["plan"] = [{"product_id": "barilla-spaghetti", "reason": "nachos", "qty": 1},
                            {"product_id": "tostitos-salsa", "reason": "nachos", "qty": 1}]
    out = json.loads(await run_tool("add_to_plan", {"product_id": "queso", "reason": "nachos", "replaces": "tostitos-salsa"},
                                    ctx(backend)))
    assert out["readback"] == "Swapped salsa for queso, Aisle 5."
    assert planned(backend) == {"barilla-spaghetti": 1, "queso": 1}
    assert [name for name, _ in backend.calls] == ["remove_from_plan", "add_to_plan"]   # the backend's atomic edits


async def test_removing_reads_back_and_says_when_it_is_still_in_the_cart(backend):
    backend.cart["plan"] = [{"product_id": "tostitos-salsa", "reason": "nachos", "qty": 1}]
    backend.cart["items"] = [{"product_id": "tostitos-salsa", "name": "Salsa", "qty": 1, "price": 3.49}]
    out = json.loads(await run_tool("remove_from_plan", {"product_id": "tostitos-salsa"}, ctx(backend)))
    assert out["readback"] == "Took salsa off your list. It's still in your cart." and planned(backend) == {}


async def test_something_the_store_does_not_carry_gets_in_store_options_and_nearby_stores(backend):
    out = json.loads(await run_tool("not_sold_here", {"item": "cilantro", "like": "salsa mexican"}, ctx(backend)))
    assert out["not_sold_here"] == "cilantro"
    assert [p["id"] for p in out["in_store"]][0] == "tostitos-salsa" and all(p["in_stock"] for p in out["in_store"])
    assert out["nearby_stores"][0] == {"name": "Berkeley Bowl", "distance": "about 1.5 miles away", "kind": "grocery",
                                       "good_for": ["produce", "fresh herbs"], "might_have_it": True}
    assert backend.calls == []                                  # nothing on the list changes


async def test_not_sold_here_works_before_the_backend_has_nearby_stores(backend):
    backend.nearby = None
    out = json.loads(await run_tool("not_sold_here", {"item": "cilantro"}, ctx(backend)))
    assert out["nearby_stores"] == [] and out["in_store"] == []


async def test_not_sold_here_notices_when_the_store_does_carry_it(backend):
    out = json.loads(await run_tool("not_sold_here", {"item": "sour cream"}, ctx(backend)))
    assert [p["id"] for p in out["sold_here"]] == ["daisy-sour-cream"] and "not_sold_here" not in out


async def test_an_amount_without_a_package_unit_still_reads_naturally(backend):
    backend.cart["plan"] = [{"product_id": "daisy-sour-cream", "reason": "tacos", "qty": 1}]
    out = json.loads(await run_tool("add_to_plan", {"product_id": "daisy-sour-cream", "reason": "tacos", "qty": 2},
                                    ctx(backend)))
    assert out["readback"] == "Sour cream, two now."


async def test_substitutes_skip_what_is_already_on_the_list(backend):
    backend.catalog.append(dict(VERDE))
    backend.cart["plan"] = [{"product_id": "salsa-verde", "reason": "nachos", "qty": 1}]
    salsa = next(p for p in backend.catalog if p["id"] == "tostitos-salsa")
    salsa["stock"], salsa["in_stock"] = 0, False
    out = json.loads(await run_tool("add_to_plan", {"product_id": "tostitos-salsa", "reason": "nachos"}, ctx(backend)))
    assert out["substitutes"] == []


async def test_nearby_stores_read_the_backends_shape(backend):
    backend.nearby = [{"kind": "produce", "name": "Berkeley Bowl", "address": "2020 Oregon St, Berkeley",
                       "good_for": ["produce", "fruit"], "distance_mi": 1.5}]
    out = json.loads(await run_tool("not_sold_here", {"item": "cilantro"}, ctx(backend)))
    assert out["nearby_stores"] == [{"name": "Berkeley Bowl", "distance": "about 1.5 miles away", "kind": "produce",
                                     "good_for": ["produce", "fruit"], "address": "2020 Oregon St, Berkeley",
                                     "might_have_it": True}]


# Undo: every list change can be taken back, one step at a time.

def trip_ctx(backend):
    return {**ctx(backend), "undo": []}                  # the agent keeps this list for the whole trip


async def test_undo_takes_back_an_add(backend):
    c = trip_ctx(backend)
    backend.cart["plan"] = [{"product_id": "barilla-spaghetti", "reason": "pasta", "qty": 1}]
    await run_tool("add_to_plan", {"product_id": "daisy-sour-cream", "reason": "tacos"}, c)
    out = json.loads(await run_tool("undo_last_edit", {}, c))
    assert out["readback"] == "Took sour cream back off your list." and planned(backend) == {"barilla-spaghetti": 1}


async def test_undo_puts_back_a_removed_item_and_an_amount(backend):
    c = trip_ctx(backend)
    backend.cart["plan"] = [{"product_id": "barilla-spaghetti", "reason": "pasta", "qty": 1},
                            {"product_id": "tostitos-salsa", "reason": "nachos", "qty": 1}]
    await run_tool("remove_from_plan", {"product_id": "tostitos-salsa"}, c)
    await run_tool("add_to_plan", {"product_id": "barilla-spaghetti", "reason": "pasta", "change_by": 1}, c)
    out = json.loads(await run_tool("undo_last_edit", {}, c))
    assert out["readback"] == "Back to one box of spaghetti." and planned(backend) == {"barilla-spaghetti": 1}
    out = json.loads(await run_tool("undo_last_edit", {}, c))
    assert out["readback"] == "Put salsa back on your list."
    assert planned(backend) == {"barilla-spaghetti": 1, "tostitos-salsa": 1}


async def test_undo_reverts_a_swap(backend):
    c = trip_ctx(backend)
    backend.cart["plan"] = [{"product_id": "tostitos-salsa", "reason": "nachos", "qty": 1}]
    await run_tool("add_to_plan", {"product_id": "queso", "reason": "nachos", "replaces": "tostitos-salsa"}, c)
    out = json.loads(await run_tool("undo_last_edit", {}, c))
    assert out["readback"] == "Swapped back to salsa." and planned(backend) == {"tostitos-salsa": 1}


async def test_undo_with_nothing_to_undo_changes_nothing(backend):
    out = json.loads(await run_tool("undo_last_edit", {}, trip_ctx(backend)))
    assert out["readback"] == "There's nothing to undo." and backend.calls == []


async def test_a_new_list_names_what_is_already_in_the_cart_but_off_the_list(backend):
    backend.cart["items"] = [{"product_id": "barilla-spaghetti", "name": "Spaghetti", "qty": 1, "price": 1.99},
                             {"product_id": "tostitos-salsa", "name": "Salsa", "qty": 1, "price": 3.49}]
    out = json.loads(await run_tool("set_plan", {"meal": "nachos", "items": [
        {"product_id": "tostitos-salsa", "reason": "nachos"}, {"product_id": "queso", "reason": "nachos"}]}, ctx(backend)))
    assert out["in_cart_not_on_list"] == [{"product_id": "barilla-spaghetti", "short_name": "Spaghetti", "qty": 1}]


async def test_a_meal_list_remembers_the_meal_on_every_line(backend):
    await run_tool("set_plan", {"meal": "pasta night for 4", "items": [
        {"product_id": "barilla-spaghetti", "reason": "pasta"}, {"product_id": "rao-marinara", "reason": "sauce"}]}, ctx(backend))
    assert [p["meal"] for p in backend.cart["plan"]] == ["pasta night for 4", "pasta night for 4"]   # plan[].meal


async def test_a_package_read_back_says_whats_in_it(backend):
    out = json.loads(await run_tool("add_to_plan", {"product_id": "avocados", "reason": "tacos"}, ctx(backend)))
    assert out["readback"] == "Added one bag of five avocados, Aisle 1."


async def test_voice_edits_use_the_backends_atomic_rpcs(backend):
    backend.cart["plan"] = [{"product_id": "barilla-spaghetti", "reason": "pasta", "qty": 1}]
    await run_tool("add_to_plan", {"product_id": "daisy-sour-cream", "reason": "tacos"}, ctx(backend))
    await run_tool("add_to_plan", {"product_id": "barilla-spaghetti", "reason": "pasta", "change_by": 1}, ctx(backend))
    await run_tool("add_to_plan", {"product_id": "barilla-spaghetti", "reason": "pasta"}, ctx(backend))   # already on
    await run_tool("remove_from_plan", {"product_id": "daisy-sour-cream"}, ctx(backend))
    assert [(name, p.get("p_product_id"), p.get("p_qty")) for name, p in backend.calls] == [
        ("add_to_plan", "daisy-sour-cream", 1), ("add_to_plan", "barilla-spaghetti", 1), ("remove_from_plan", "daisy-sour-cream", None)]
    assert planned(backend) == {"barilla-spaghetti": 2}


async def test_a_budget_says_whether_the_list_fits(backend):
    backend.cart["plan"] = [{"product_id": "barilla-spaghetti", "reason": "pasta", "qty": 1},
                            {"product_id": "rao-marinara", "reason": "pasta", "qty": 1}]
    out = json.loads(await run_tool("set_budget", {"amount": 10}, ctx(backend)))
    assert out == {"budget": 10, "estimate": 10.48, "fits": False, "over_by": 0.48}


async def test_an_edit_that_crosses_the_budget_says_so(backend):
    backend.cart.update({"budget": 10, "total": 0})
    backend.cart["plan"] = [{"product_id": "barilla-spaghetti", "reason": "pasta", "qty": 1}]
    out = json.loads(await run_tool("add_to_plan", {"product_id": "rao-marinara", "reason": "pasta"}, ctx(backend)))
    assert out["readback"] == "Added rao's sauce, Aisle 6. That puts you at $10.48, over your $10."
    out = json.loads(await run_tool("add_to_plan", {"product_id": "daisy-sour-cream", "reason": "tacos"}, ctx(backend)))
    assert out["readback"] == "Added sour cream, Aisle 8."            # already over: said once, not on every edit
