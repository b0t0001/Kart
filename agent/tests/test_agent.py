from line.events import AgentSendText, CallStarted, UserCustomSent, UserTextSent, UserTurnEnded, UserTurnStarted

from kart_agent.agent import GREETING, KartAgent
from kart_agent.brain import Brain

from fakes import FakeBackend, FakeLLM, Turn


async def run(agent, event):
    return [out.text for out in [o async for o in agent.process(None, event)] if isinstance(out, AgentSendText)]


def make(turns=()):
    backend = FakeBackend()
    agent = KartAgent(backend=backend, brain=Brain(llm=FakeLLM(list(turns))), cart_id="7")
    return agent, backend


async def test_greets_on_call_start_and_writes_caption():
    agent, backend = make()
    assert await run(agent, CallStarted()) == [GREETING]
    assert backend.transcript == [("agent", GREETING)]


async def test_user_turn_goes_to_claude_and_both_sides_are_captioned():
    agent, backend = make([Turn(chunks=["Love it. ", "Pasta's in aisle 6."])])
    said = await run(agent, UserTurnEnded(content=[UserTextSent(content="pasta dinner for four")]))
    assert said == ["Love it. ", "Pasta's in aisle 6."]
    assert backend.transcript == [("user", "pasta dinner for four"), ("agent", "Love it. Pasta's in aisle 6.")]


async def test_trip_context_updates_state_without_speaking():
    agent, backend = make()
    assert agent.run_filter(UserCustomSent(metadata={"type": "trip_context", "cart_id": "9", "trip_id": "trip-9"})) is False
    assert agent.cart_id == "9" and agent.trip_id == "trip-9"


async def test_suggestion_runs_and_speaks_proactively():
    agent, backend = make()
    event = UserCustomSent(metadata={"type": "suggestion", "deal_id": "d", "text": "Parmesan is $3 off in Aisle 4. Want it?"})
    assert agent.run_filter(event) is True
    assert await run(agent, event) == ["Parmesan is $3 off in Aisle 4. Want it?"]
    assert backend.transcript[-1] == ("agent", "Parmesan is $3 off in Aisle 4. Want it?")


async def test_quiet_cart_changes_do_not_interrupt():
    agent, backend = make()
    backend.cart["plan"] = []
    event = UserCustomSent(metadata={"type": "cart_changed", "change": "added", "product_id": "bananas"})
    assert agent.run_filter(event) is False


async def test_barge_in_cancels():
    agent, _ = make()
    assert agent.cancel_filter(UserTurnStarted()) is True


# Final-review fixes ---------------------------------------------------------------------------

import asyncio
import time


async def test_a_proactive_line_never_cuts_kart_off():
    agent, backend = make([Turn(chunks=["Rao's is in aisle 6."])])
    agent._speaking = True                                       # Kart is mid-answer
    event = UserCustomSent(metadata={"type": "suggestion", "deal_id": "d", "text": "Parmesan is $3 off in Aisle 4. Want it?"})
    assert agent.run_filter(event) is False                     # don't start (and cancel) a turn
    agent._speaking = False
    said = await run(agent, UserTurnEnded(content=[UserTextSent(content="where's the sauce")]))
    assert said == ["Rao's is in aisle 6.", "Parmesan is $3 off in Aisle 4. Want it?"]   # said at the end instead


async def test_an_added_line_waits_a_beat_for_a_paired_deal():
    backend = FakeBackend()
    backend.cart["plan"] = [{"product_id": "rao-marinara", "reason": "pasta", "done": False}]
    agent = KartAgent(backend=backend, brain=Brain(llm=FakeLLM([])), cart_id="7", coalesce_seconds=0.2)
    started = time.monotonic()
    said = await run(agent, UserCustomSent(metadata={"type": "cart_changed", "change": "added", "product_id": "rao-marinara"}))
    assert said == ["Got the Rao's Sauce."] and time.monotonic() - started >= 0.2   # a suggestion in that window cancels it


async def test_no_greeting_when_rejoining_a_trip_in_progress():
    agent, backend = make()
    backend.cart["plan"] = [{"product_id": "rao-marinara", "reason": "pasta", "done": False}]
    assert await run(agent, CallStarted()) == []
