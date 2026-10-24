import asyncio

from line.events import AgentSendText, CallStarted, UserCustomSent, UserTextSent, UserTurnEnded, UserTurnStarted

from kart_agent.agent import GREETING, KartAgent
from kart_agent.brain import Brain

from fakes import FakeBackend, FakeLLM, Turn


async def run(agent, event):
    return [out.text for out in [o async for o in agent.process(None, event)] if isinstance(out, AgentSendText)]


def make(turns=()):
    backend = FakeBackend()
    agent = KartAgent(backend=backend, brain=Brain(llm=FakeLLM(list(turns))), cart_id="7", context_wait_seconds=0.01)
    return agent, backend


def captioned_carts(backend):
    return [params["p_cart_id"] for name, params in backend.calls if name == "append_transcript"]


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


async def test_the_greeting_goes_to_the_ipads_cart_not_the_default_one():
    backend = FakeBackend()
    agent = KartAgent(backend=backend, brain=Brain(llm=FakeLLM([])), cart_id="7", context_wait_seconds=1.0)
    greeting = asyncio.create_task(run(agent, CallStarted()))
    await asyncio.sleep(0.05)                              # the iPad's trip_context lands just after the call starts
    agent.run_filter(UserCustomSent(metadata={"type": "trip_context", "cart_id": "ipad-voice", "trip_id": "t"}))
    assert await greeting == [GREETING]
    assert captioned_carts(backend) == ["ipad-voice"]


async def test_without_trip_context_it_greets_on_its_own_cart_after_a_short_wait():
    agent, backend = make()
    assert await run(agent, CallStarted()) == [GREETING]
    assert captioned_carts(backend) == ["7"]


async def test_the_brain_knows_the_store_products_from_the_first_turn():
    agent, backend = make([Turn(chunks=["Love it."])])
    await run(agent, UserTurnEnded(content=[UserTextSent(content="pasta dinner for four")]))
    assert "- rao-marinara: Rao's Sauce, Rao's Homemade Marinara Sauce, 24 oz (sauce)" in agent.brain.llm.requests[0]["system"]


PARM_OFFER = {"type": "suggestion", "deal_id": "d-parm-3off", "product_id": "kirkland-parmesan",
              "text": "Parmesan is $3 off in Aisle 4. Want it?"}


async def test_a_spoken_yes_takes_the_offered_deal_without_claude():
    agent, backend = make()                                  # no scripted Claude turns: calling Claude would fail
    agent.run_filter(UserCustomSent(metadata=PARM_OFFER))
    said = await run(agent, UserTurnEnded(content=[UserTextSent(content="Yeah, sure.")]))
    assert said == ["Added Parmesan to your list."]
    plans = [p["p_plan"] for name, p in backend.calls if name == "set_plan"]
    assert plans and any(line["product_id"] == "kirkland-parmesan" for line in plans[-1])


async def test_a_spoken_no_dismisses_the_offered_deal():
    agent, backend = make()
    agent.run_filter(UserCustomSent(metadata=PARM_OFFER))
    assert await run(agent, UserTurnEnded(content=[UserTextSent(content="No thanks.")])) == ["No problem."]
    assert ("dismiss_suggestion", {"p_cart_id": "7"}) in backend.calls


async def test_a_longer_answer_to_an_offer_still_goes_to_claude():
    agent, backend = make([Turn(chunks=["It's the 1.5 pound wedge."])])
    agent.run_filter(UserCustomSent(metadata=PARM_OFFER))
    said = await run(agent, UserTurnEnded(content=[UserTextSent(content="Yes, but how big is the parmesan?")]))
    assert said == ["It's the 1.5 pound wedge."]


async def test_a_tap_on_the_card_ends_the_spoken_offer():
    agent, backend = make([Turn(chunks=["Yes to what?"])])
    agent.run_filter(UserCustomSent(metadata=PARM_OFFER))
    agent.run_filter(UserCustomSent(metadata={"type": "card_response", "card_id": "deal-d-parm-3off", "action": "yes"}))
    assert await run(agent, UserTurnEnded(content=[UserTextSent(content="Yes.")])) == ["Yes to what?"]


async def test_claude_hears_the_offer_when_it_gets_the_answer():
    agent, backend = make([Turn(chunks=["It's the 1.5 pound wedge."])])
    agent.run_filter(UserCustomSent(metadata=PARM_OFFER))
    await run(agent, UserTurnEnded(content=[UserTextSent(content="Yes, but how big is the parmesan?")]))
    sent = agent.brain.llm.requests[0]["messages"][-1]["content"]
    assert "Parmesan is $3 off in Aisle 4. Want it?" in sent and sent.endswith("Yes, but how big is the parmesan?")



async def said_events(agent, event):
    return [o for o in [o async for o in agent.process(None, event)] if isinstance(o, AgentSendText)]


async def test_chatter_cant_cut_off_the_greeting_or_a_deal_line():
    agent, backend = make()
    assert [e.interruptible for e in await said_events(agent, CallStarted())] == [False]
    assert agent.run_filter(UserCustomSent(metadata=PARM_OFFER))
    assert [e.interruptible for e in await said_events(agent, UserCustomSent(metadata=PARM_OFFER))] == [False]


async def test_answers_can_be_cut_off_unless_barge_in_is_off():
    agent, backend = make([Turn(chunks=["Love it."])])
    assert [e.interruptible for e in await said_events(agent, UserTurnEnded(content=[UserTextSent(content="pasta dinner")]))] == [True]
    assert agent.cancel_filter(UserTurnStarted())
    quiet = KartAgent(backend=FakeBackend(), brain=Brain(llm=FakeLLM([Turn(chunks=["Love it."])])), cart_id="7",
                      context_wait_seconds=0.01, barge_in=False)
    assert not quiet.cancel_filter(UserTurnStarted())
    assert [e.interruptible for e in await said_events(quiet, UserTurnEnded(content=[UserTextSent(content="pasta dinner")]))] == [False]


async def test_side_chatter_gets_no_answer_and_no_caption():
    agent, backend = make([Turn(chunks=["<qui", "et>"])])
    said = await run(agent, UserTurnEnded(content=[UserTextSent(content="You know we're close to Taco Bell, bro.")]))
    assert said == [] and backend.transcript == []


async def test_a_filler_alone_gets_no_answer():
    agent, backend = make()                                  # no scripted Claude turns: calling Claude would fail
    assert await run(agent, UserTurnEnded(content=[UserTextSent(content="Um.")])) == [] and backend.transcript == []



BEEF_NUDGE = {"type": "nudge", "product_id": "ground-beef", "kind": "over", "have": 2, "need": 1,
              "text": "That's your 2nd Ground Beef. Your list says 1. Keep it?"}


async def test_a_nudge_is_said_once_and_cant_be_cut_off():
    agent, backend = make()
    assert agent.run_filter(UserCustomSent(metadata=BEEF_NUDGE))
    said = await said_events(agent, UserCustomSent(metadata=BEEF_NUDGE))
    assert [(e.text, e.interruptible) for e in said] == [(BEEF_NUDGE["text"], False)]


async def test_keep_it_and_got_it_answer_the_nudge_without_claude():
    agent, backend = make()                                  # no scripted Claude turns: calling Claude would fail
    agent.run_filter(UserCustomSent(metadata=BEEF_NUDGE))
    assert await run(agent, UserTurnEnded(content=[UserTextSent(content="Uh, keep it.")])) == ["Okay, keeping it."]
    agent.run_filter(UserCustomSent(metadata=BEEF_NUDGE))
    assert await run(agent, UserTurnEnded(content=[UserTextSent(content="Oh, I'll put it back.")])) == ["Got it."]
    assert [p["p_action"] for name, p in backend.calls if name == "dismiss_nudge"] == ["keep", "ok"]


async def test_the_last_question_asked_gets_the_answer():
    agent, backend = make()
    agent.run_filter(UserCustomSent(metadata=BEEF_NUDGE))
    agent.run_filter(UserCustomSent(metadata=PARM_OFFER))    # the deal came after: "yeah" answers the deal
    assert await run(agent, UserTurnEnded(content=[UserTextSent(content="Yeah, sure.")])) == ["Added Parmesan to your list."]
    assert not any(name == "dismiss_nudge" for name, _ in backend.calls)


async def test_a_tap_on_the_nudge_card_ends_the_spoken_question():
    agent, backend = make([Turn(chunks=["Keep what?"])])
    agent.run_filter(UserCustomSent(metadata=BEEF_NUDGE))
    agent.run_filter(UserCustomSent(metadata={"type": "card_response", "card_id": "nudge-ground-beef|over", "action": "got_it"}))
    assert await run(agent, UserTurnEnded(content=[UserTextSent(content="Keep it.")])) == ["Keep what?"]
