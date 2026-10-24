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


async def test_an_empty_turn_never_leaves_an_empty_assistant_message():
    llm = FakeLLM([Turn(chunks=[]), Turn(chunks=["Sure."])])     # e.g. a refusal: nothing came back
    brain = Brain(llm=llm)
    ctx = {"backend": FakeBackend(), "cart_id": "7", "trip_id": "t"}
    first = await collect(brain.respond("hmm", ctx))
    assert first == ["Sorry, say that again?"]
    await collect(brain.respond("pasta", ctx))
    assert all(m["content"] for m in llm.requests[1]["messages"] if m["role"] == "assistant")


class RefusingLLM:
    """Streams its own apology, then returns no content blocks (what llm.py does on a refusal)."""

    def __init__(self):
        self.requests = []

    async def stream(self, *, system, messages, tools):
        self.requests.append({"messages": list(messages)})
        yield ("text", "Sorry, I can't help with that one.")
        yield ("final", [], "end_turn")


async def test_a_refusal_is_said_once_and_stored_as_said():
    llm = RefusingLLM()
    brain = Brain(llm=llm)
    said = await collect(brain.respond("hmm", {"backend": FakeBackend(), "cart_id": "7", "trip_id": "t"}))
    assert said == ["Sorry, I can't help with that one."]
    assert brain.messages[-1] == {"role": "assistant", "content": [{"type": "text", "text": "Sorry, I can't help with that one."}]}
