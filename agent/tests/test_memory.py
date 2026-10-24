import copy
import json

import pytest

from kart_agent.memory import (MEMBER_RULES, MEMBER_TOOLS, member_section, only_greeting, question, welcome_line)
from kart_agent.tools import run_tool

from fakes import FakeBackend
from member_fixtures import PROFILE


def member_ctx(**extra):
    return {"backend": FakeBackend(), "cart_id": "7", "trip_id": "trip-1", "member_id": "1029",
            "profile": copy.deepcopy(PROFILE), **extra}


def test_member_section_mentions_events_and_today():
    section = member_section(PROFILE)
    assert section.startswith("About this shopper, from Kart's memory (today is Saturday, 2026-10-24):")
    for fact in ("Dylan", "household of 4", "Leo's soccer party, pasta for the team", "Thursday 2026-10-29 (in 5 days)",
                 "memory id 16", "Spaghetti x1", "Likes the Marinara here", "Milk (every 7 days, usually Saturday",
                 "Last trip (2026-10-17): Milk, Tortillas", "Spaghetti: Leo's soccer party · Thu"):
        assert fact in section, fact
    assert section.endswith(MEMBER_RULES)


def test_welcome_lines():
    assert welcome_line(PROFILE) == "Welcome back, Dylan!"
    nameless = copy.deepcopy(PROFILE)
    nameless["member"]["name"] = None
    assert welcome_line(nameless) == "Welcome back!"
    new = {**nameless, "member": {**nameless["member"], "trips": 0}, "memories": []}
    assert welcome_line(new) == "Nice to meet you!"
    assert welcome_line(None) == "Welcome back!"


def test_question_asks_name_first_then_rotates():
    nameless = {**PROFILE, "member": {**PROFILE["member"], "name": None}}
    assert question(nameless, 0) == "By the way, what should I call you?"
    assert [question(PROFILE, n) for n in range(4)] == [
        "Any fun plans coming up I can help you shop for?", "Anyone coming over soon?",
        "Got anything coming up, like a party or a holiday?", "Any fun plans coming up I can help you shop for?"]


@pytest.mark.parametrize("text", ["Hey Kart", "hey kart!", "Hi, Kart.", "hey cart", "Hello Kart", "hey", "Hi.",
                                  "Kart?", "hey there"])
def test_only_greeting_yes(text):
    assert only_greeting(text)


@pytest.mark.parametrize("text", ["hey kart where's the milk", "hi, add eggs", "hello I'm done", "kart, checkout", ""])
def test_only_greeting_no(text):
    assert not only_greeting(text)


def test_member_tools_are_declared():
    assert [t["name"] for t in MEMBER_TOOLS] == ["remember", "save_for_later", "forget", "shop_saved_list",
                                                 "show_memories", "sign_out"]


async def test_remember_calls_rpc_with_member():
    ctx = member_ctx()
    await run_tool("remember", {"kind": "event", "text": "Friendsgiving for 10", "date": "2026-10-31"}, ctx)
    assert ctx["backend"].calls[-1] == ("member_remember", {
        "p_member_id": "1029", "p_kind": "event", "p_text": "Friendsgiving for 10", "p_event_date": "2026-10-31",
        "p_trip_id": "trip-1"})
    assert ctx["memory_changed"] is True


async def test_forget_requires_memory_id():
    ctx = member_ctx()
    result = json.loads(await run_tool("forget", {}, ctx))
    assert "memory_id" in result["error"]
    assert not any(name == "member_forget" for name, _ in ctx["backend"].calls)


async def test_member_tools_need_a_member():
    ctx = member_ctx(member_id=None)
    result = json.loads(await run_tool("remember", {"kind": "note", "text": "x"}, ctx))
    assert result["error"] == "no member is signed in"


async def test_shop_saved_list_one_set_plan_keeps_existing():
    ctx = member_ctx()
    ctx["backend"].cart["plan"] = [{"product_id": "kirkland-parmesan", "reason": "deal", "qty": 1}]
    await run_tool("shop_saved_list", {"memory_id": 16}, ctx)
    plans = [params["p_plan"] for name, params in ctx["backend"].calls if name == "set_plan"]
    assert len(plans) == 1
    assert [(p["product_id"], p["reason"]) for p in plans[0]] == [
        ("kirkland-parmesan", "deal"), ("barilla-spaghetti", "Leo's soccer party"),
        ("rao-marinara", "Leo's soccer party")]


def test_member_section_lists_due_reminders_only():
    reminder = {"id": 50, "kind": "reminder", "text": "batteries", "event_date": "2026-10-30", "days_until": 6,
                "upcoming": True, "items": [{"product_id": "kirkland-batteries", "short_name": "AA Batteries", "qty": 1}]}
    later = member_section({**PROFILE, "memories": [reminder]})
    assert "Reminder due now" not in later and "Reminder for later: batteries" in later
    due = member_section({**PROFILE, "memories": [{**reminder, "event_date": "2026-10-25", "days_until": 1}]})
    assert "Reminder due now: batteries" in due


def test_still_there_and_forgotten_lines():
    from kart_agent.memory import FORGOTTEN_LINE, still_there_line
    assert FORGOTTEN_LINE == "Done. I've forgotten everything about you."
    assert still_there_line(PROFILE) == "Still shopping, Dylan?"
    assert still_there_line(None) == "Still shopping?"


def test_member_rules_cover_the_conversational_moments():
    for phrase in ("show_memories", "sign_out", "don't remember that", "what did I buy last time",
                   "remind me", "health"):
        assert phrase in MEMBER_RULES, phrase


def test_forget_it_answering_a_question_means_no():
    assert '"never mind" or "forget it"' in MEMBER_RULES and "forget everything" in MEMBER_RULES


async def test_shop_saved_list_keeps_the_existing_lines_and_their_meal():
    ctx = member_ctx()
    ctx["backend"].cart["plan"] = [{"product_id": "kirkland-parmesan", "reason": "deal", "qty": 1,
                                    "meal": "pasta night for 4"}]
    await run_tool("shop_saved_list", {"memory_id": 16}, ctx)
    plan = [params["p_plan"] for name, params in ctx["backend"].calls if name == "set_plan"][-1]
    assert [(p["product_id"], p["reason"], p.get("meal")) for p in plan] == [
        ("kirkland-parmesan", "deal", "pasta night for 4"),                 # today's line keeps its label
        ("barilla-spaghetti", "Leo's soccer party", "Leo's soccer party"),
        ("rao-marinara", "Leo's soccer party", "Leo's soccer party")]
    assert ctx.get("meal") is None                                          # the trip's meal isn't renamed


def test_mid_trip_memory_moments_carry_on():
    assert "Mid-trip" in MEMBER_RULES and "don't ask what they're shopping for" in MEMBER_RULES
