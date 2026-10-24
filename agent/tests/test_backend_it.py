"""Live checks against a running Supabase (the local stack). KART_IT=1 plus SUPABASE_URL / SUPABASE_ANON_KEY."""

import os
import uuid

import pytest
from line.events import UserTextSent, UserTurnEnded

from kart_agent.agent import KartAgent
from kart_agent.backend import SupabaseBackend
from kart_agent.brain import Brain

from fakes import FakeLLM, ToolUse, Turn

pytestmark = pytest.mark.skipif(os.getenv("KART_IT") != "1", reason="needs a running Supabase (KART_IT=1)")


@pytest.fixture
async def backend():
    b = SupabaseBackend(os.environ["SUPABASE_URL"], os.environ["SUPABASE_ANON_KEY"])
    yield b


async def test_reads_live_catalog_and_cart(backend):
    cart_id = f"agent-it-{uuid.uuid4().hex[:8]}"
    await backend.rpc("reset_cart", p_cart_id=cart_id)
    catalog = await backend.get_catalog()
    assert any(p["id"] == "kirkland-parmesan" and "sale_price" in p for p in catalog)
    cart = await backend.get_cart(cart_id)
    assert cart["status"] == "shopping"
    await backend.rpc("set_cart_status", p_cart_id=cart_id, p_status="idle")


async def test_agent_turn_writes_plan_and_captions(backend):
    cart_id = f"agent-it-{uuid.uuid4().hex[:8]}"
    await backend.rpc("reset_cart", p_cart_id=cart_id)
    llm = FakeLLM([
        Turn(chunks=["Love it. "], tools=[ToolUse("t1", "set_plan", {"items": [
            {"product_id": "barilla-spaghetti", "reason": "pasta dinner"}, {"product_id": "rao-marinara", "reason": "pasta dinner"}]})]),
        Turn(chunks=["Pasta's in aisle 6."]),
    ])
    agent = KartAgent(backend=backend, brain=Brain(llm=llm), cart_id=cart_id)
    said = [o.text async for o in agent.process(None, UserTurnEnded(content=[UserTextSent(content="pasta dinner")]))]
    assert said == ["Love it. ", "Pasta's in aisle 6."]
    cart = await backend.get_cart(cart_id)
    assert {p["product_id"] for p in cart["plan"]} == {"barilla-spaghetti", "rao-marinara"}
    lines = await backend._get("transcript", {"cart_id": f"eq.{cart_id}", "order": "id"})
    assert [(line["role"], line["text"]) for line in lines] == [("user", "pasta dinner"), ("agent", "Love it. Pasta's in aisle 6.")]
    await backend.rpc("set_cart_status", p_cart_id=cart_id, p_status="idle")
