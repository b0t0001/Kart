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
    assert names == {"search_catalog", "get_cart", "set_plan", "add_to_plan", "get_deals", "set_location",
                     "dismiss_suggestion", "confirm_item", "start_checkout"}
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
    assert [p["product_id"] for p in backend.calls[-1][1]["p_plan"]] == ["barilla-spaghetti", "kirkland-parmesan"]


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
