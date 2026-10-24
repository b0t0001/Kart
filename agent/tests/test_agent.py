import asyncio
import re

from line.events import AgentSendCustom, AgentSendText, CallStarted, UserCustomSent, UserTextSent, UserTurnEnded, UserTurnStarted

from kart_agent.agent import GREETING, KartAgent
from kart_agent.brain import Brain

from fakes import FakeBackend, FakeLLM, ToolUse, Turn


async def run(agent, event):
    return [out.text for out in [o async for o in agent.process(None, event)] if isinstance(out, AgentSendText)]


def after_live_note(content):
    """What the shopper said (and any other bracketed context), without the "(Right now: ...)" cart note."""
    return re.sub(r"^\(Right now: .*?\.\) ", "", content)


def make(turns=()):
    backend = FakeBackend()
    agent = KartAgent(backend=backend, brain=Brain(llm=FakeLLM(list(turns))), cart_id="7", context_wait_seconds=0.01,
                      digest_delay_seconds=0)
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


async def test_a_deal_on_the_heels_of_an_add_says_both():
    agent, backend = make()
    backend.cart["plan"] = [{"product_id": "barilla-spaghetti", "reason": "pasta", "done": True}]
    backend.cart["items"] = [{"product_id": "barilla-spaghetti", "qty": 1}]
    added = UserCustomSent(metadata={"type": "cart_changed", "change": "added", "product_id": "barilla-spaghetti"})
    offer = UserCustomSent(metadata={"type": "suggestion", "deal_id": "d-parm-3off", "product_id": "kirkland-parmesan",
                                     "text": "Parmesan is $1 off in Aisle 4. Want it?"})
    await agent._refresh()                                              # the call already knows the list
    assert agent.run_filter(added) and agent.run_filter(offer)          # the offer cancels the add's line in Line
    assert await run(agent, offer) == ["Got the Spaghetti. Parmesan is $1 off in Aisle 4. Want it?"]


async def test_a_deal_long_after_an_add_is_said_alone():
    agent, backend = make()
    backend.cart["plan"] = [{"product_id": "barilla-spaghetti", "reason": "pasta", "done": True}]
    backend.cart["items"] = [{"product_id": "barilla-spaghetti", "qty": 1}]
    await agent._refresh()
    agent.run_filter(UserCustomSent(metadata={"type": "cart_changed", "change": "added", "product_id": "barilla-spaghetti"}))
    agent._last_add = (agent._last_add[0], agent._last_add[1] - 10)  # the add was ten seconds ago
    offer = UserCustomSent(metadata={"type": "suggestion", "deal_id": "d-parm-3off", "product_id": "kirkland-parmesan",
                                     "text": "Parmesan is $1 off in Aisle 4. Want it?"})
    assert agent.run_filter(offer)
    assert await run(agent, offer) == ["Parmesan is $1 off in Aisle 4. Want it?"]


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
    assert any(line["product_id"] == "kirkland-parmesan" for line in backend.cart["plan"])


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
    agent.run_filter(UserCustomSent(metadata={**BEEF_NUDGE, "product_id": "kirkland-parmesan"}))   # a different nudge
    assert await run(agent, UserTurnEnded(content=[UserTextSent(content="Oh, I'll put it back.")])) == ["Got it."]
    assert [p["p_action"] for name, p in backend.calls if name == "dismiss_nudge"] == ["keep", "ok"]


async def test_a_nudge_the_cart_already_cleared_is_not_answered():
    agent, backend = make([Turn(chunks=["Skip what?"])])
    agent.run_filter(UserCustomSent(metadata=BEEF_NUDGE))
    backend.cart["nudge"] = None                             # the extra came out: the backend cleared the nudge
    assert await run(agent, UserTurnEnded(content=[UserTextSent(content="Skip.")])) == ["Skip what?"]
    assert not any(name == "dismiss_nudge" for name, _ in backend.calls)


async def test_a_nudge_the_cart_still_shows_is_answered():
    agent, backend = make()
    agent.run_filter(UserCustomSent(metadata=BEEF_NUDGE))
    backend.cart["nudge"] = {"product_id": "ground-beef", "kind": "over", "have": 2, "need": 1}
    assert await run(agent, UserTurnEnded(content=[UserTextSent(content="Keep it.")])) == ["Okay, keeping it."]


async def test_a_deal_said_yes_to_is_ticked_off_when_it_goes_in():
    agent, backend = make()
    agent.run_filter(UserCustomSent(metadata=PARM_OFFER))
    assert await run(agent, UserTurnEnded(content=[UserTextSent(content="Yes.")])) == ["Added Parmesan to your list."]
    backend.cart["items"] = [{"product_id": "kirkland-parmesan", "qty": 1}]
    added = UserCustomSent(metadata={"type": "cart_changed", "change": "added", "product_id": "kirkland-parmesan"})
    assert agent.run_filter(added)                           # Kart knows the Parmesan is on the list now
    agent.coalesce_seconds = 0
    assert await run(agent, added) == ["Got the Parmesan."]


async def test_the_last_question_asked_gets_the_answer():
    agent, backend = make()
    agent.run_filter(UserCustomSent(metadata=BEEF_NUDGE))
    agent.run_filter(UserCustomSent(metadata=PARM_OFFER))    # the deal came after: "yeah" answers the deal
    assert await run(agent, UserTurnEnded(content=[UserTextSent(content="Yeah, sure.")])) == ["Added Parmesan to your list."]
    assert not any(name == "dismiss_nudge" for name, _ in backend.calls)


async def test_a_tap_on_the_nudge_card_ends_the_spoken_question():
    agent, backend = make([Turn(chunks=["Keep what?"])])
    agent.run_filter(UserCustomSent(metadata=BEEF_NUDGE))
    agent.run_filter(UserCustomSent(metadata={"type": "card_response", "card_id": "nudge-over:ground-beef", "action": "got_it"}))
    assert await run(agent, UserTurnEnded(content=[UserTextSent(content="Keep it.")])) == ["Keep what?"]



async def test_a_repeated_deal_or_nudge_event_is_said_once_per_trip():
    agent, backend = make()
    assert agent.run_filter(UserCustomSent(metadata=PARM_OFFER))
    assert not agent.run_filter(UserCustomSent(metadata=PARM_OFFER))      # the same deal again: already said
    assert agent.run_filter(UserCustomSent(metadata=BEEF_NUDGE))
    assert not agent.run_filter(UserCustomSent(metadata=BEEF_NUDGE))
    agent.run_filter(UserCustomSent(metadata={"type": "trip_context", "cart_id": "7", "trip_id": "a-new-trip"}))
    assert agent.run_filter(UserCustomSent(metadata=PARM_OFFER))          # a new trip starts fresh


async def test_the_nudge_names_the_trips_meal():
    plan_call = ToolUse("t1", "set_plan", {"meal": "pasta night for 4",
                                           "items": [{"product_id": "barilla-spaghetti", "reason": "noodles"}]})
    agent, backend = make([Turn(chunks=["On it."], tools=[plan_call]), Turn(chunks=["Done."])])
    await run(agent, UserTurnEnded(content=[UserTextSent(content="pasta night for four")]))
    nudge = {"type": "nudge", "product_id": "barilla-spaghetti", "kind": "over", "have": 2, "need": 1, "text": "x"}
    assert await run(agent, UserCustomSent(metadata=nudge)) == [
        "That's two boxes of spaghetti in the cart, and pasta night for 4 needs one. Keep the extra?"]


async def test_at_checkout_skip_it_or_go_get_it_by_voice():
    agent, backend = make()
    short = {"type": "nudge", "product_id": "barilla-spaghetti", "kind": "under", "have": 0, "need": 1, "text": "x"}
    agent.run_filter(UserCustomSent(metadata=short))
    assert await run(agent, UserTurnEnded(content=[UserTextSent(content="Um, I'll go get it.")])) == ["Okay, it's in Aisle 6."]
    agent.run_filter(UserCustomSent(metadata={**short, "product_id": "rao-marinara"}))
    assert await run(agent, UserTurnEnded(content=[UserTextSent(content="Skip it.")])) == ["Got it."]
    assert [p["p_action"] for name, p in backend.calls if name == "dismiss_nudge"] == ["shop", "skip"]  # shop: back to shopping


async def test_go_get_them_for_the_combined_nudge_says_where_to_start():
    agent, backend = make()
    combined = {"type": "nudge", "product_id": "rao-marinara", "kind": "under", "have": 0, "need": 1, "text": "x",
                "items": [{"product_id": "rao-marinara", "have": 0, "need": 1, "aisle": "Aisle 6"},
                          {"product_id": "kirkland-parmesan", "have": 0, "need": 1, "aisle": "Aisle 4"}]}
    agent.run_filter(UserCustomSent(metadata=combined))
    assert await run(agent, UserTurnEnded(content=[UserTextSent(content="Let me grab them.")])) == ["Okay, start in Aisle 6."]


async def test_the_agent_knows_when_the_cart_has_the_nudge_beta():
    agent, backend = make()
    backend.cart["features"] = {"quantity_nudges": True}
    backend.cart["plan"] = [{"product_id": "barilla-spaghetti", "qty": 1}]
    backend.cart["items"] = [{"product_id": "barilla-spaghetti", "qty": 2}]
    agent.coalesce_seconds = 0
    assert await run(agent, UserCustomSent(metadata={"type": "cart_changed", "change": "added",
                                                     "product_id": "barilla-spaghetti"})) == []



async def test_no_thanks_to_the_checkout_list_skips_it():
    agent, backend = make()
    combined = {"type": "nudge", "product_id": "rao-marinara", "kind": "under", "have": 0, "need": 1, "text": "x",
                "items": [{"product_id": "rao-marinara", "have": 0, "need": 1, "aisle": "Aisle 6"},
                          {"product_id": "kirkland-parmesan", "have": 0, "need": 1, "aisle": "Aisle 4"}]}
    agent.run_filter(UserCustomSent(metadata=combined))
    assert await run(agent, UserTurnEnded(content=[UserTextSent(content="No thanks.")])) == ["Got it."]
    assert [p["p_action"] for name, p in backend.calls if name == "dismiss_nudge"] == ["skip"]


async def test_a_plain_yes_answers_the_nudges_question():
    agent, backend = make()
    agent.run_filter(UserCustomSent(metadata=BEEF_NUDGE))             # "Keep the extra?"
    assert await run(agent, UserTurnEnded(content=[UserTextSent(content="Sure.")])) == ["Okay, keeping it."]
    combined = {"type": "nudge", "product_id": "rao-marinara", "kind": "under", "have": 0, "need": 1, "text": "x",
                "items": [{"product_id": "rao-marinara", "have": 0, "need": 1, "aisle": "Aisle 6"},
                          {"product_id": "kirkland-parmesan", "have": 0, "need": 1, "aisle": "Aisle 4"}]}
    agent.run_filter(UserCustomSent(metadata=combined))               # "...Want to grab them?"
    assert await run(agent, UserTurnEnded(content=[UserTextSent(content="Yeah.")])) == ["Okay, start in Aisle 6."]
    assert [p["p_action"] for name, p in backend.calls if name == "dismiss_nudge"] == ["keep", "shop"]


async def test_a_bare_okay_with_nothing_asked_gets_silence():
    agent, backend = make()                                  # no scripted Claude turns: calling Claude would fail
    assert await run(agent, UserTurnEnded(content=[UserTextSent(content="Okay, so.")])) == [] and backend.transcript == []



# Deals: ask first, then one at a time (Dylan's choice). The agent drives it and tells the iPad which card to show.

async def outputs(agent, event):
    return [o for o in [o async for o in agent.process(None, event)] if isinstance(o, (AgentSendText, AgentSendCustom))]


def planned_agent():
    plan_call = ToolUse("t1", "set_plan", {"meal": "pasta night for 4",
                                           "items": [{"product_id": "barilla-spaghetti", "reason": "pasta"}]})
    agent, backend = make([Turn(chunks=["One sec."], tools=[plan_call]), Turn(chunks=["Spaghetti's on your list."])])
    agent.digest_delay_seconds = 0
    return agent, backend


def spoken(outs):
    return [o.text for o in outs if isinstance(o, AgentSendText)]


def cards(outs):
    return [o.metadata for o in outs if isinstance(o, AgentSendCustom)]


async def test_after_the_list_kart_asks_about_the_deals_once():
    agent, backend = planned_agent()
    outs = await outputs(agent, UserTurnEnded(content=[UserTextSent(content="pasta night for four")]))
    assert spoken(outs)[-1] == "By the way, one deal goes with your list. Want to hear it?"
    assert cards(outs) == [{"type": "deal_digest", "count": 1}]


async def test_yes_walks_the_deals_one_at_a_time():
    agent, backend = planned_agent()
    await outputs(agent, UserTurnEnded(content=[UserTextSent(content="pasta night for four")]))
    outs = await outputs(agent, UserTurnEnded(content=[UserTextSent(content="Yeah, sure.")]))
    assert spoken(outs) == ["Parmesan is $3 off in Aisle 4. Want it?"]
    assert cards(outs) == [{"type": "digest_deal", "deal_id": "d-parm-3off", "product_id": "kirkland-parmesan",
                            "text": "Parmesan is $3 off in Aisle 4. Want it?", "index": 1, "count": 1}]
    outs = await outputs(agent, UserTurnEnded(content=[UserTextSent(content="Yes.")]))
    assert spoken(outs) == ["Added Parmesan to your list. That's all the deals."]
    assert cards(outs) == [{"type": "digest_done"}]
    assert any(line["product_id"] == "kirkland-parmesan" for line in backend.cart["plan"])
    assert not agent.run_filter(UserCustomSent(metadata=PARM_OFFER))   # walked already: never read out again


async def test_not_now_means_kart_tells_you_at_the_shelf():
    agent, backend = planned_agent()
    await outputs(agent, UserTurnEnded(content=[UserTextSent(content="pasta night for four")]))
    outs = await outputs(agent, UserTurnEnded(content=[UserTextSent(content="Not now.")]))
    assert spoken(outs) == ["No problem. I'll tell you at the shelf."] and cards(outs) == [{"type": "digest_done"}]
    assert agent.run_filter(UserCustomSent(metadata=PARM_OFFER))       # the spaghetti went in: Kart says the deal
    assert await run(agent, UserTurnEnded(content=[UserTextSent(content="Yes.")])) == ["Added Parmesan to your list."]


async def test_a_tap_on_the_digest_cards_works_like_saying_it():
    agent, backend = planned_agent()
    await outputs(agent, UserTurnEnded(content=[UserTextSent(content="pasta night for four")]))
    tap = UserCustomSent(metadata={"type": "card_response", "card_id": "digest", "action": "yes"})
    assert agent.run_filter(tap)
    assert spoken(await outputs(agent, tap)) == ["Parmesan is $3 off in Aisle 4. Want it?"]
    no = UserCustomSent(metadata={"type": "card_response", "card_id": "digest-deal-d-parm-3off", "action": "no"})
    assert agent.run_filter(no)
    outs = await outputs(agent, no)
    assert spoken(outs) == ["Okay. That's all the deals."] and cards(outs) == [{"type": "digest_done"}]


async def test_no_question_when_no_deal_goes_with_the_list():
    agent, backend = planned_agent()
    backend.deals = []
    outs = await outputs(agent, UserTurnEnded(content=[UserTextSent(content="pasta night for four")]))
    assert spoken(outs) == ["One sec.", " Spaghetti's on your list."] and cards(outs) == []



async def test_paid_is_said_once_the_ipad_says_so():
    agent, backend = make()
    paid = UserCustomSent(metadata={"type": "ui_action", "action": "paid"})
    assert agent.run_filter(paid)
    assert await run(agent, paid) == ["Paid. Thanks for shopping!"]
    assert not agent.run_filter(UserCustomSent(metadata={"type": "ui_action", "action": "checkout_tapped"}))


SPAG_OUT = {"type": "cart_changed", "change": "removed", "product_id": "barilla-spaghetti"}


async def test_a_planned_item_taken_out_asks_to_take_it_off_the_list_too():
    agent, backend = make()                                   # no Claude turns: the answer is a fast path
    backend.cart["plan"] = [{"product_id": "barilla-spaghetti", "reason": "pasta", "qty": 1, "done": False}]
    assert await run(agent, UserCustomSent(metadata=SPAG_OUT)) == ["Took the Spaghetti off your bill. Take it off the list too?"]
    assert await run(agent, UserTurnEnded(content=[UserTextSent(content="Yes, please.")])) == ["Took spaghetti off your list."]
    assert backend.cart["plan"] == []


async def test_no_keeps_the_item_on_the_list():
    agent, backend = make()
    backend.cart["plan"] = [{"product_id": "barilla-spaghetti", "reason": "pasta", "qty": 1, "done": False}]
    await run(agent, UserCustomSent(metadata=SPAG_OUT))
    assert await run(agent, UserTurnEnded(content=[UserTextSent(content="No.")])) == ["Okay, it stays on your list."]
    assert [p["product_id"] for p in backend.cart["plan"]] == ["barilla-spaghetti"]


async def test_taking_out_an_extra_box_asks_nothing():
    agent, backend = make()
    backend.cart["plan"] = [{"product_id": "barilla-spaghetti", "reason": "pasta", "qty": 1, "done": True}]
    backend.cart["items"] = [{"product_id": "barilla-spaghetti", "qty": 1}]   # box 2 came out; box 1 is still in
    assert await run(agent, UserCustomSent(metadata=SPAG_OUT)) == ["Took the Spaghetti off your bill."]


async def test_a_new_list_asks_about_its_own_deals_but_never_the_same_deal_twice():
    pasta = ToolUse("t1", "set_plan", {"meal": "pasta night for 4", "items": [{"product_id": "barilla-spaghetti", "reason": "pasta"}]})
    again = ToolUse("t2", "set_plan", {"meal": "pasta night for 6", "items": [{"product_id": "barilla-spaghetti", "reason": "pasta", "qty": 2}]})
    nachos = ToolUse("t3", "set_plan", {"meal": "nachos", "items": [{"product_id": "tostitos-salsa", "reason": "nachos"}]})
    agent, backend = make([Turn(chunks=["One sec."], tools=[pasta]), Turn(chunks=["Spaghetti's on."]),
                           Turn(chunks=["One sec."], tools=[again]), Turn(chunks=["Two boxes."]),
                           Turn(chunks=["One sec."], tools=[nachos]), Turn(chunks=["Salsa's on."])])
    backend.deals.append({"id": "d-queso", "product_id": "queso", "label": "$1 off", "pairs_with": ["tostitos-salsa"],
                          "ends_at": None})
    outs = await outputs(agent, UserTurnEnded(content=[UserTextSent(content="pasta night for four")]))
    assert cards(outs) == [{"type": "deal_digest", "count": 1}]
    await outputs(agent, UserTurnEnded(content=[UserTextSent(content="Not now.")]))
    outs = await outputs(agent, UserTurnEnded(content=[UserTextSent(content="it's six people now")]))
    assert cards(outs) == []                                   # the Parmesan was already asked about
    outs = await outputs(agent, UserTurnEnded(content=[UserTextSent(content="actually make it nachos")]))
    assert cards(outs) == [{"type": "deal_digest", "count": 1}]  # the new list has its own deal (queso)


async def test_this_means_the_last_item_into_the_cart():
    agent, backend = make([Turn(chunks=["The spaghetti is $1.99."])])
    backend.cart["plan"] = [{"product_id": "barilla-spaghetti", "reason": "pasta", "qty": 1, "done": True}]
    backend.cart["items"] = [{"product_id": "barilla-spaghetti", "qty": 1}]
    await agent._refresh()
    agent.run_filter(UserCustomSent(metadata={"type": "cart_changed", "change": "added", "product_id": "barilla-spaghetti"}))
    await run(agent, UserTurnEnded(content=[UserTextSent(content="How much is this?")]))
    heard = agent.brain.llm.requests[-1]["messages"][-1]["content"]
    assert after_live_note(heard) == "(The last item into the cart: Spaghetti.) How much is this?"


async def test_this_means_the_card_on_screen_when_one_is_open():
    agent, backend = make([Turn(chunks=["It's $3.99 with the deal."])])
    backend.unresolved = [{"event_id": "e1"}]
    agent.run_filter(UserCustomSent(metadata={"type": "ui_action", "action": "unknown_item"}))
    await run(agent, UserTurnEnded(content=[UserTextSent(content="What is that?")]))
    heard = agent.brain.llm.requests[-1]["messages"][-1]["content"]
    assert heard.startswith("(On screen: an \"Is this...?\" card for an item the cameras couldn't identify.)")


async def test_a_card_that_closed_by_itself_is_not_what_this_means():
    agent, backend = make([Turn(chunks=["Which one?"])])
    agent.run_filter(UserCustomSent(metadata={"type": "ui_action", "action": "unknown_item"}))
    backend.unresolved = []                                    # the item came out of the cart: the card is gone
    await run(agent, UserTurnEnded(content=[UserTextSent(content="What is that?")]))
    assert agent.brain.llm.requests[-1]["messages"][-1]["content"] == "What is that?"


async def test_a_plain_question_gets_no_extra_context():
    agent, backend = make([Turn(chunks=["Aisle 5."])])
    await run(agent, UserTurnEnded(content=[UserTextSent(content="Where is the salsa?")]))
    assert agent.brain.llm.requests[-1]["messages"][-1]["content"] == "Where is the salsa?"


async def test_after_a_dropped_call_kart_asks_what_was_said():
    agent, backend = make()
    lost = UserCustomSent(metadata={"type": "reconnected", "unanswered": True})
    assert agent.run_filter(lost)
    assert await run(agent, lost) == ["Sorry, I lost you for a second. What was that?"]
    assert not agent.run_filter(UserCustomSent(metadata={"type": "reconnected", "unanswered": False}))


async def test_a_rejoined_call_remembers_the_meal_and_the_conversation():
    agent, backend = make([Turn(chunks=["Aisle 6."])])
    backend.cart["plan"] = [{"product_id": "barilla-spaghetti", "reason": "pasta night for 4", "qty": 1, "done": False},
                            {"product_id": "kirkland-parmesan", "reason": "deal", "qty": 1, "done": False}]
    backend.transcript = [("agent", GREETING), ("user", "Pasta night for 4."), ("agent", "You're set with spaghetti."),
                          ("user", "Where's the")]                  # cut off by the drop: never answered
    assert await run(agent, CallStarted()) == []                     # a trip in progress: no greeting
    assert await run(agent, UserCustomSent(metadata={"type": "ui_action", "action": "paid"})) == ["Paid. Enjoy pasta night!"]
    await run(agent, UserTurnEnded(content=[UserTextSent(content="Where's the spaghetti?")]))
    messages = agent.brain.llm.requests[-1]["messages"]
    assert messages[:2] == [{"role": "user", "content": "Pasta night for 4."},
                            {"role": "assistant", "content": "You're set with spaghetti."}]
    assert messages[2]["role"] == "user" and after_live_note(messages[2]["content"]) == "Where's the spaghetti?"


async def test_the_deals_question_waits_while_kart_has_asked_its_own():
    tacos = ToolUse("t1", "set_plan", {"meal": "tacos", "items": [{"product_id": "barilla-spaghetti", "reason": "pasta"}]})
    agent, backend = make([Turn(chunks=["One sec."], tools=[tacos]),
                           Turn(chunks=["Tacos it is. The salsa's already in your cart. Keep it?"]),
                           Turn(chunks=["Okay, take it out when you can."])])
    outs = await outputs(agent, UserTurnEnded(content=[UserTextSent(content="actually make it tacos")]))
    assert cards(outs) == []                                   # "Keep it?" is still open: no second question
    outs = await outputs(agent, UserTurnEnded(content=[UserTextSent(content="No, I'll put it back.")]))
    assert spoken(outs)[0] == "Okay, take it out when you can." and cards(outs) == [{"type": "deal_digest", "count": 1}]


async def test_be_quiet_keeps_kart_quiet_until_asked_and_cards_still_work():
    agent, backend = make()                                   # no Claude: both are fast paths
    assert await run(agent, UserTurnEnded(content=[UserTextSent(content="Be quiet, please.")])) == \
        ["Okay, I'll stay quiet. Just ask if you need me."]
    backend.cart["plan"] = [{"product_id": "rao-marinara", "reason": "pasta", "qty": 1, "done": True}]
    backend.cart["items"] = [{"product_id": "rao-marinara", "qty": 1}]
    await agent._refresh()
    assert not agent.run_filter(UserCustomSent(metadata={"type": "cart_changed", "change": "added", "product_id": "rao-marinara"}))
    assert not agent.run_filter(UserCustomSent(metadata=PARM_OFFER))      # the card shows; Kart doesn't read it out
    assert await run(agent, UserTurnEnded(content=[UserTextSent(content="Yes.")])) == ["Added Parmesan to your list."]
    assert await run(agent, UserTurnEnded(content=[UserTextSent(content="You can talk again.")])) == ["Okay, I'm back."]
    assert agent.run_filter(UserCustomSent(metadata={"type": "cart_changed", "change": "added", "product_id": "rao-marinara"}))


async def test_thanks_gets_a_youre_welcome_when_nothing_is_asked():
    agent, backend = make()
    assert await run(agent, UserTurnEnded(content=[UserTextSent(content="Thanks!")])) == ["You're welcome!"]
    assert await run(agent, UserTurnEnded(content=[UserTextSent(content="Okay.")])) == []     # an ack still gets nothing


async def test_kart_remembers_which_deals_it_offered():
    agent, backend = planned_agent()
    backend_turn = Turn(chunks=["That was Parmesan, $3 off in Aisle 4."])
    agent.brain.llm.turns.append(backend_turn)
    await outputs(agent, UserTurnEnded(content=[UserTextSent(content="pasta night for four")]))
    await outputs(agent, UserTurnEnded(content=[UserTextSent(content="Not now.")]))
    await run(agent, UserTurnEnded(content=[UserTextSent(content="What was that deal again?")]))
    heard = agent.brain.llm.requests[-1]["messages"][-1]["content"]
    assert after_live_note(heard) == "(Deals Kart offered this trip: Parmesan is $3 off in Aisle 4.) What was that deal again?"


async def test_kart_says_once_when_the_bill_gets_close_to_the_budget():
    agent, backend = make()
    backend.cart.update({"budget": 30, "total": 27.4})
    backend.cart["plan"] = [{"product_id": "barilla-spaghetti", "reason": "pasta", "qty": 1, "done": True}]
    backend.cart["items"] = [{"product_id": "barilla-spaghetti", "qty": 1}]
    agent.coalesce_seconds = 0
    added = UserCustomSent(metadata={"type": "cart_changed", "change": "added", "product_id": "barilla-spaghetti"})
    await agent._refresh()
    assert await run(agent, added) == ["Got the Spaghetti. You're at $27.40 of $30."]
    assert await run(agent, added) == ["Got the Spaghetti."]
    backend.cart["total"] = 31.2
    assert await run(agent, added) == ["Got the Spaghetti. That's $31.20, over your $30."]


def no_dairy(agent):
    agent._diet.update({"diet": "no dairy", "kinds": {"cheese", "dairy"}, "products": set()})


async def test_a_deal_that_breaks_the_diet_is_never_read_out_and_its_card_goes_away():
    agent, backend = make()
    await agent._refresh()
    no_dairy(agent)
    assert agent.run_filter(UserCustomSent(metadata=PARM_OFFER))         # handled, quietly
    assert await run(agent, UserCustomSent(metadata=PARM_OFFER)) == []
    assert ("dismiss_suggestion", {"p_cart_id": "7"}) in backend.calls and agent._offer is None


async def test_the_deals_question_leaves_out_deals_that_break_the_diet():
    agent, backend = planned_agent()
    no_dairy(agent)
    outs = await outputs(agent, UserTurnEnded(content=[UserTextSent(content="pasta night for four")]))
    assert cards(outs) == []                                       # the only deal (Parmesan) is cheese


async def test_a_deal_on_something_taken_off_the_list_is_not_offered():
    drop = ToolUse("t1", "remove_from_plan", {"product_id": "kirkland-parmesan"})
    agent, backend = make([Turn(chunks=["Sure."], tools=[drop])])
    backend.cart["plan"] = [{"product_id": "kirkland-parmesan", "reason": "pasta", "qty": 1, "done": False}]
    assert await run(agent, UserTurnEnded(content=[UserTextSent(content="We've got parmesan at home, take it off.")])) == \
        ["Sure.", " Took parmesan off your list."]
    assert agent.run_filter(UserCustomSent(metadata=PARM_OFFER))
    assert await run(agent, UserCustomSent(metadata=PARM_OFFER)) == []     # "we have some at home": no deal on it
    assert ("dismiss_suggestion", {"p_cart_id": "7"}) in backend.calls


async def test_each_turn_carries_the_live_cart_so_simple_questions_need_no_tool():
    agent, backend = make([Turn(chunks=["You're at $1.99."])])
    backend.cart.update({"total": 1.99, "savings": 0, "next_step": "Aisle 6 → Rao's Sauce"})
    backend.cart["plan"] = [
        {"product_id": "barilla-spaghetti", "name": "Spaghetti", "qty": 1, "done": True, "aisle": "Aisle 6"},
        {"product_id": "rao-marinara", "name": "Rao's Sauce", "qty": 1, "done": False, "aisle": "Aisle 6"},
        {"product_id": "kirkland-parmesan", "name": "Parmesan", "qty": 2, "done": False, "aisle": "Aisle 4", "deal_label": "$3 off"}]
    backend.cart["items"] = [{"product_id": "barilla-spaghetti", "short_name": "Spaghetti", "qty": 1, "price": 1.99}]
    await run(agent, UserTurnEnded(content=[UserTextSent(content="What's my total?")]))
    assert agent.brain.llm.requests[-1]["messages"][-1]["content"] == (
        "(Right now: list: Spaghetti ✓ (Aisle 6); Rao's Sauce (Aisle 6); 2× Parmesan (Aisle 4, $3 off). "
        "Cart: Spaghetti ×1 $1.99. Total $1.99, saved $0.00. Next: Aisle 6 → Rao's Sauce.) What's my total?")
