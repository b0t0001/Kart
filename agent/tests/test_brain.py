from kart_agent.brain import Brain

from fakes import FakeBackend, FakeLLM, ToolUse, Turn


async def collect(stream):
    return [chunk async for chunk in stream]


async def test_streams_text_and_runs_tools_between_turns():
    backend = FakeBackend()
    llm = FakeLLM([
        Turn(chunks=["Love it. "], tools=[ToolUse("t1", "set_plan", {"items": [{"product_id": "barilla-spaghetti", "reason": "pasta dinner"}]})]),
        Turn(chunks=["Spaghetti's first, ", "aisle 6."]),
    ])
    brain = Brain(llm=llm)
    chunks = await collect(brain.respond("pasta dinner for four", {"backend": backend, "cart_id": "7", "trip_id": "trip-1"}))
    assert chunks == ["Love it. ", "Spaghetti's first, ", "aisle 6."]
    assert backend.calls[0][0] == "set_plan"
    second = llm.requests[1]["messages"]
    assert second[-1]["role"] == "user" and second[-1]["content"][0]["type"] == "tool_result"
    assert second[-1]["content"][0]["tool_use_id"] == "t1"


async def test_history_carries_across_turns():
    llm = FakeLLM([Turn(chunks=["Hi!"]), Turn(chunks=["Sure."])])
    brain = Brain(llm=llm)
    ctx = {"backend": FakeBackend(), "cart_id": "7", "trip_id": "trip-1"}
    await collect(brain.respond("hello", ctx))
    await collect(brain.respond("thanks", ctx))
    roles = [m["role"] for m in llm.requests[1]["messages"]]
    assert roles == ["user", "assistant", "user"]


async def test_system_prompt_forbids_invented_prices():
    llm = FakeLLM([Turn(chunks=["ok"])])
    await collect(Brain(llm=llm).respond("hi", {"backend": FakeBackend(), "cart_id": "7", "trip_id": "t"}))
    system = llm.requests[0]["system"]
    assert "Never invent" in system and "two short sentences" in system
