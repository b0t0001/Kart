"""Member memory in the Line agent (CONTRACT v0.14, BETA)."""

import asyncio
import copy
import time

from line.events import AgentSendCustom, AgentSendText, CallStarted, UserCustomSent, UserTextSent, UserTurnEnded

from kart_agent.agent import GREETING, KartAgent
from kart_agent.brain import Brain
from kart_agent.memory import PROFILE_FAILED_LINE

from fakes import FakeBackend, FakeLLM, ToolUse, Turn
from member_fixtures import PROFILE

ANY_PLANS = "Any fun plans coming up I can help you shop for?"


class MemberBackend(FakeBackend):
    def __init__(self, profile=PROFILE, delay=0.0):
        super().__init__()
        self.profile = copy.deepcopy(profile)
        self.delay = delay

    async def rpc(self, name, **params):
        if name == "member_profile":
            self.calls.append((name, params))
            await asyncio.sleep(self.delay)
            return copy.deepcopy(self.profile)
        if name == "member_remember":
            self.calls.append((name, params))
            return {"id": 41, "kind": params["p_kind"], "text": params["p_text"], "event_date": params["p_event_date"]}
        return await super().rpc(name, **params)


def make(turns=(), backend=None, member="1029", trip="trip-1"):
    backend = backend or MemberBackend()
    llm = FakeLLM(list(turns))
    agent = KartAgent(backend=backend, brain=Brain(llm=llm), cart_id="7", context_wait_seconds=0.01,
                      digest_delay_seconds=0)
    agent.run_filter(trip_context(member, trip))
    return agent, backend, llm


def trip_context(member="1029", trip="trip-1"):
    return UserCustomSent(metadata={"type": "trip_context", "cart_id": "7", "trip_id": trip,
                                    **({"member_id": member} if member else {})})


async def run(agent, event):
    return [o.text for o in [o async for o in agent.process(None, event)] if isinstance(o, AgentSendText)]


def said_by_user(text):
    return UserTurnEnded(content=[UserTextSent(content=text)])


def profile_calls(backend):
    return [p for name, p in backend.calls if name == "member_profile"]


async def test_guest_greeting_unchanged():
    agent, backend, llm = make(member=None)
    assert await run(agent, CallStarted()) == [GREETING]
    assert profile_calls(backend) == [] and llm.requests == []


async def test_member_greeting_fixed_line_then_claude():
    agent, backend, llm = make([Turn(chunks=["Leo's soccer party is tomorrow. ", "Want the pasta list?"])])
    said = await run(agent, CallStarted())
    assert said == ["Welcome back, Dylan!", "Leo's soccer party is tomorrow. ", "Want the pasta list?"]
    assert profile_calls(backend) == [{"p_member_id": "1029", "p_cart_id": "7"}]
    request = llm.requests[0]
    assert "About this shopper, from Kart's memory" in request["system"]
    assert "remember" in [t["name"] for t in request["tools"]]
    assert request["messages"][-1]["content"].startswith('(The shopper just signed in, and Kart already said "Welcome back, Dylan!"')
    assert [role for role, _ in backend.transcript] == ["agent", "agent"]          # the cue is never captioned


async def test_profile_timeout_falls_back():
    agent, backend, llm = make(backend=MemberBackend(delay=2.0))
    started = time.monotonic()
    assert await run(agent, CallStarted()) == [PROFILE_FAILED_LINE]
    assert time.monotonic() - started < 1.5 and llm.requests == []


async def test_hey_kart_asks_once_per_trip():
    agent, backend, llm = make()
    assert await run(agent, said_by_user("Hey Kart")) == [ANY_PLANS]
    assert agent.brain.messages[-1] == {"role": "assistant", "content": [{"type": "text", "text": ANY_PLANS}]}
    assert await run(agent, said_by_user("hey kart")) == []          # asked already: back to filler, as for guests
    assert llm.requests == []


async def test_lull_asks_when_idle_and_prefixes_answer():
    agent, backend, llm = make([Turn(chunks=["Ooh, fun."])])
    lull = UserCustomSent(metadata={"type": "lull"})
    assert agent.run_filter(lull) is True
    assert await run(agent, lull) == [ANY_PLANS]
    await run(agent, said_by_user("I'm hosting Friendsgiving next Saturday"))
    assert llm.requests[-1]["messages"][-1]["content"] == \
        f'(Kart just asked: "{ANY_PLANS}") I\'m hosting Friendsgiving next Saturday'


async def test_lull_ignored_for_guest_or_after_asked():
    guest, _, _ = make(member=None)
    assert guest.run_filter(UserCustomSent(metadata={"type": "lull"})) is False
    agent, _, _ = make()
    await run(agent, said_by_user("Hey Kart"))
    assert agent.run_filter(UserCustomSent(metadata={"type": "lull"})) is False


async def test_memory_write_reloads_profile():
    agent, backend, llm = make([
        Turn(chunks=["Hey Dylan."]),
        Turn(tools=[ToolUse("t1", "remember", {"kind": "event", "text": "Friendsgiving for 10", "date": "2026-10-31"})]),
        Turn(chunks=["Ooh, fun. I'll remember that."]),
    ])
    await run(agent, CallStarted())
    assert len(profile_calls(backend)) == 1
    assert await run(agent, said_by_user("I'm hosting Friendsgiving next Saturday")) == ["Ooh, fun. I'll remember that."]
    assert ("member_remember", {"p_member_id": "1029", "p_kind": "event", "p_text": "Friendsgiving for 10",
                                "p_event_date": "2026-10-31", "p_trip_id": "trip-1"}) in backend.calls
    assert len(profile_calls(backend)) == 2


async def test_new_trip_resets_question_budget():
    agent, backend, llm = make()
    assert await run(agent, said_by_user("Hey Kart")) == [ANY_PLANS]
    agent.run_filter(trip_context("1029", "trip-2"))
    assert await run(agent, said_by_user("Hey Kart")) == ["Anyone coming over soon?"]
