"""Member memory in the Line agent (CONTRACT v0.14, BETA)."""

import asyncio
import json
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


# ── Edge cases (spec §3.9) ──

async def customs(agent, event):
    return [o.metadata for o in [o async for o in agent.process(None, event)] if isinstance(o, AgentSendCustom)]


async def test_member_forgotten_drops_profile_and_tools():
    from kart_agent.memory import FORGOTTEN_LINE
    agent, backend, llm = make([Turn(chunks=["Hey."]), Turn(chunks=["Sure, pasta."])])
    await run(agent, CallStarted())
    forgotten = UserCustomSent(metadata={"type": "member_forgotten"})
    assert agent.run_filter(forgotten) is True
    assert await run(agent, forgotten) == [FORGOTTEN_LINE]
    assert agent.member_id is None
    await run(agent, said_by_user("pasta night for four"))
    request = llm.requests[-1]
    assert "About this shopper" not in request["system"]
    assert "remember" not in [t["name"] for t in request["tools"]]


async def test_same_trip_context_without_member_drops_silently():
    agent, backend, llm = make([Turn(chunks=["Hey."]), Turn(chunks=["Okay."])])
    await run(agent, CallStarted())
    assert agent.run_filter(trip_context(None, "trip-1")) is False
    assert agent.member_id is None
    await run(agent, said_by_user("what's on my list"))
    assert "About this shopper" not in llm.requests[-1]["system"]


async def test_same_trip_context_same_member_reloads_profile():
    agent, backend, llm = make([Turn(chunks=["Hey."]), Turn(chunks=["Okay."])])
    await run(agent, CallStarted())
    agent.run_filter(trip_context("1029", "trip-1"))      # the iPad forgot one memory: same member, same trip
    await run(agent, said_by_user("what's on my list"))
    assert len(profile_calls(backend)) == 2


async def test_member_idle_line():
    agent, backend, llm = make()
    idle = UserCustomSent(metadata={"type": "member_idle"})
    assert agent.run_filter(idle) is True
    assert await run(agent, idle) == ["Still shopping, Dylan?"]
    guest, _, _ = make(member=None)
    assert guest.run_filter(idle) is False


async def test_show_memories_sends_custom_event():
    agent, backend, llm = make([
        Turn(chunks=["Hey."]),
        Turn(tools=[ToolUse("t1", "show_memories", {})]),
        Turn(chunks=["Leo's party, the marinara, and your weekly milk. It's all on screen."]),
    ])
    await run(agent, CallStarted())
    assert await customs(agent, said_by_user("what do you know about me?")) == [{"type": "show_memories"}]


async def test_sign_out_tool_clears_member_and_tools():
    agent, backend, llm = make([
        Turn(chunks=["Hey."]),
        Turn(tools=[ToolUse("t1", "sign_out", {})]),
        Turn(chunks=["Sorry about that, you're shopping as a guest now. What are we getting?"]),
        Turn(chunks=["Sure."]),
    ])
    await run(agent, CallStarted())
    await run(agent, said_by_user("that's not me"))
    assert ("set_member", {"p_cart_id": "7", "p_member_id": None}) in backend.calls
    assert agent.member_id is None
    await run(agent, said_by_user("pasta night"))
    assert "About this shopper" not in llm.requests[-1]["system"]


async def test_dont_remember_that_forgets_saved_id():
    agent, backend, llm = make([
        Turn(chunks=["Hey."]),
        Turn(tools=[ToolUse("t1", "remember", {"kind": "note", "text": "Out of milk at home"})]),
        Turn(chunks=["Got it."]),
        Turn(tools=[ToolUse("t2", "forget", {"memory_id": 41})]),
        Turn(chunks=["Okay, forgotten."]),
    ])
    await run(agent, CallStarted())
    await run(agent, said_by_user("we're out of milk at home"))
    await run(agent, said_by_user("actually don't remember that"))
    assert ("member_forget", {"p_member_id": "1029", "p_memory_id": 41}) in backend.calls


async def test_quiet_mode_silences_the_lull_and_idle_lines():
    agent, backend, llm = make()
    agent._quiet = True                                    # "be quiet": Kart only answers
    assert agent.run_filter(UserCustomSent(metadata={"type": "lull"})) is False
    assert agent.run_filter(UserCustomSent(metadata={"type": "member_idle"})) is False


# ── The demo flow, v2 (Dylan, 2026-10-24): memory made live in Act 1, recalled after the fast-forward in Act 2 ──

LEO = {"id": 30, "kind": "event", "text": "Leo's soccer team party, pasta for 12", "event_date": "2026-10-25",
       "days_until": 1, "upcoming": True,
       "items": [{"product_id": "barilla-spaghetti", "short_name": "Spaghetti", "qty": 3},
                 {"product_id": "rao-marinara", "short_name": "Rao's Sauce", "qty": 2}]}


def with_leo():
    profile = copy.deepcopy(PROFILE)
    profile["memories"] = [LEO]
    return MemberBackend(profile=profile)


async def test_member_section_has_a_calendar_for_next_weekday():
    from kart_agent.memory import member_section
    section = member_section(PROFILE)
    assert "Next two weeks: Sun 2026-10-25, Mon 2026-10-26" in section and "Sat 2026-10-31" in section
    assert '"next Saturday" means the first Saturday after today' in section


async def test_save_for_later_reads_the_list_back():
    from kart_agent.tools import run_tool
    backend = MemberBackend()

    async def saved(name, **params):
        backend.calls.append((name, params))
        return {**LEO, "items": [{"product_id": "barilla-spaghetti", "short_name": "Spaghetti", "qty": 3},
                                 {"product_id": "rao-marinara", "short_name": "Rao's Sauce", "qty": 2}]}
    backend.rpc = saved
    ctx = {"backend": backend, "cart_id": "7", "trip_id": "trip-1", "member_id": "1029", "profile": PROFILE}
    out = json.loads(await run_tool("save_for_later", {"memory_id": 30, "items": [
        {"product_id": "barilla-spaghetti", "qty": 3}, {"product_id": "rao-marinara", "qty": 2}]}, ctx))
    assert out["readback"] == "Saved: three boxes of spaghetti and two rao's sauce for Leo's soccer team party."


async def test_greeting_offers_the_saved_list_and_yes_shops_it():
    agent, backend, llm = make(backend=with_leo())
    assert await run(agent, CallStarted()) == ["Welcome back, Dylan!",
                                               "Leo's soccer team party is tomorrow. Want the list you saved?"]
    assert llm.requests == []                                         # a fixed line: fast, and nothing invented
    assert await run(agent, said_by_user("Yes.")) == ["Done, it's on your list. First stop: Aisle 6 → Spaghetti."]
    plan = [params["p_plan"] for name, params in backend.calls if name == "set_plan"][-1]
    assert [(p["product_id"], p["qty"]) for p in plan] == [("barilla-spaghetti", 3), ("rao-marinara", 2)]


async def test_no_to_the_saved_list_keeps_it_for_later():
    agent, backend, llm = make(backend=with_leo())
    await run(agent, CallStarted())
    assert await run(agent, said_by_user("Not today.")) == ["Okay, it's saved for later."]
    assert not any(name == "set_plan" for name, _ in backend.calls)


async def test_member_yeah_after_kart_asks_reaches_claude():
    agent, backend, llm = make([Turn(chunks=["Got it, I'll remember Leo's party on Saturday. Want me to save a list for it?"]),
                                Turn(chunks=["Saved."])])
    await run(agent, said_by_user("Next Saturday is Leo's soccer team party, we'll need pasta for 12."))
    assert await run(agent, said_by_user("Yeah.")) == ["Saved."]


async def test_guest_yeah_after_a_question_stays_unchanged():
    agent, backend, llm = make([Turn(chunks=["Want me to add bread?"])], member=None)
    await run(agent, said_by_user("Pasta night."))
    assert await run(agent, said_by_user("Yeah.")) == [] and len(llm.requests) == 1


async def test_rejoined_member_call_keeps_the_member_without_regreeting():
    agent, backend, llm = make()
    backend.transcript = [("agent", "Welcome back, Dylan!")]           # this trip already talked: a dropped call
    assert await run(agent, CallStarted()) == []
    assert len(profile_calls(backend)) == 1 and "About this shopper" in agent.brain.system


# ── Review fixes: the member is really gone; memory survives a slow reload ──

def far_party_profile():
    profile = copy.deepcopy(PROFILE)                   # Leo's party in 5 days: the greeting goes to Claude
    return profile


async def test_forget_me_purges_the_member_from_claudes_history():
    from kart_agent.memory import FORGOTTEN_LINE
    agent, backend, llm = make([Turn(chunks=["Leo's soccer party is Thursday, Dylan."]), Turn(chunks=["Sure."])])
    await run(agent, CallStarted())
    assert await run(agent, UserCustomSent(metadata={"type": "member_forgotten"})) == [FORGOTTEN_LINE]
    await run(agent, said_by_user("What do you remember about me?"))
    sent = json.dumps(llm.requests[-1]["messages"])
    assert "Dylan" not in sent and "Leo" not in sent
    assert "forget everything" in sent                     # Claude knows why the slate is clean


async def test_not_me_purges_the_member_from_claudes_history():
    agent, backend, llm = make([Turn(chunks=["Welcome back, Dylan. Leo's party is Thursday."]),
                                Turn(tools=[ToolUse("t1", "sign_out", {})]),
                                Turn(chunks=["Sorry about that, you're shopping as a guest now. What are we getting?"]),
                                Turn(chunks=["Sure."])])
    await run(agent, CallStarted())
    await run(agent, said_by_user("That's not me."))
    await run(agent, said_by_user("Pasta night."))
    sent = json.dumps(llm.requests[-1]["messages"])
    assert "Dylan" not in sent and "Leo" not in sent


async def test_rejoin_after_forget_skips_what_came_before():
    from kart_agent.memory import FORGOTTEN_LINE
    agent, backend, llm = make(member=None)
    backend.cart["plan"] = [{"product_id": "barilla-spaghetti", "reason": "pasta night", "qty": 1, "done": False}]
    backend.transcript = [("user", "hey kart"), ("agent", "Welcome back, Dylan! Leo's soccer party is tomorrow."),
                          ("agent", FORGOTTEN_LINE), ("user", "pasta night"), ("agent", "Pasta night it is.")]
    assert await run(agent, CallStarted()) == []
    history = json.dumps(agent.brain.messages)
    assert "Dylan" not in history and "Leo" not in history and "Pasta night it is." in history


async def test_slow_reload_keeps_the_good_profile():
    agent, backend, llm = make([Turn(chunks=["Hey."]), Turn(chunks=["Okay."])])
    await run(agent, CallStarted())
    backend.delay = 2.0                                    # the reload times out...
    agent.run_filter(trip_context("1029", "trip-1"))       # ...after a same-member trip_context (every call sends two)
    await run(agent, said_by_user("what's on my list"))
    assert agent._profile is not None and "About this shopper, from Kart's memory" in llm.requests[-1]["system"]


async def test_a_failed_forget_me_is_said_honestly():
    agent, backend, llm = make()
    failed = UserCustomSent(metadata={"type": "member_forget_failed"})
    assert agent.run_filter(failed) is True
    assert await run(agent, failed) == ["Sorry, I couldn't do that just now."]
    assert agent.member_id == "1029"                       # nothing was forgotten


async def test_shopping_the_saved_list_on_an_empty_trip_names_the_meal():
    agent, backend, llm = make(backend=with_leo())
    await run(agent, CallStarted())
    await run(agent, said_by_user("Yes."))
    assert agent._meal == "Leo's soccer team party"        # a 4th box: "…and Leo's soccer team party needs three"
