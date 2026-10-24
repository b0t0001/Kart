"""Member memory (CONTRACT v0.14, BETA): what Kart knows about a signed-in member, and how it uses it.

The backend computes the facts (`member_profile`: picks, rhythms, memories); this module turns them into
Claude's prompt, the fixed lines Kart says on its own, and the member-only tools.
"""

from __future__ import annotations

import re
from datetime import date, timedelta
from typing import Any

from .lines import _amount
from .tools import _tool

WELCOME_BACK = "Welcome back!"
NICE_TO_MEET = "Nice to meet you!"
PROFILE_FAILED_LINE = "Welcome back! What are we shopping for today?"
FORGOTTEN_LINE = "Done. I've forgotten everything about you."
GUEST_NOW = "shopping as a guest now"                  # in Kart's "not me" apology (MEMBER_RULES)
FORGOTTEN_NOTE = ("(The shopper had Kart forget everything about them; they're a guest now. Never mention anything "
                  "said earlier about them.)")
NOT_ME_NOTE = "(That wasn't the member who signed in; they're a guest now. Nothing said earlier about the member applies.)"
LIST_LATER_LINE = "Okay, it's saved for later."
NAME_QUESTION = "By the way, what should I call you?"
QUESTIONS = ["Any fun plans coming up I can help you shop for?", "Anyone coming over soon?",
             "Got anything coming up, like a party or a holiday?"]

GREETING_TURN = ('(The shopper just signed in, and Kart already said "{welcome}". Add at most two short sentences '
                 "that use the most relevant memory, then ask what they're shopping for. Don't welcome them again.)")

MEMBER_RULES = """How to use what you remember (a signed-in member):
- Use at most one or two memories in a turn, naturally, like a friend who remembers. Never recite their history \
or what they paid.
- Only state memories that are in the section above. Work dates out from today above.
- Leave deals to the cart's deal cards; don't pitch them from memory.
- When they share a future plan (an event, guests, a holiday), call remember with kind "event" and its date, then \
offer to start a list for it, and put store products on it with save_for_later (never set_plan). Say plainly what \
the store doesn't carry.
- "Shop my Friendsgiving list", or yes to "want the pasta list?", is shop_saved_list.
- A lasting preference ("we're vegetarian now") is remember kind "preference"; their name or how many people are \
in the household is kind "name" or "household". Small talk is never saved.
- If a memory tool returns an error, say you couldn't save it, and never claim you'll remember.
- When they mention a coming event, call remember (kind "event", with its date). Its text is the event in their \
words, names kept, then the detail: "Leo's soccer team party, pasta for 12". Then say exactly: "Got it, I'll remember \
<the event, short, with the name> on <weekday>. Want me to save a list for it?"
- A saved list is sized like a meal for their guests (about a pound of pasta per four people, a jar of sauce per six), \
basics only: leave cheese, bread and extras off unless they ask. After save_for_later, say its readback word for word.
- "Forget that" is forget with that memory's id. But "never mind" or "forget it" answering your own question just \
means no: forget nothing. To "forget everything about me", call show_memories: the Forget me button is on that screen. If they say "don't remember that" right after you saved \
something, forget that memory (its id came back from remember) and say so.
- "What do you know about me?": call show_memories (it opens the memory screen), then say one short sentence \
naming at most three things.
- "That's not me" right after you greet them: call sign_out, then say "Sorry about that, you're shopping as a guest \
now. What are we getting?"
- "what did I buy last time?": answer briefly from the last trip, items only, no prices unless asked. Otherwise \
never volunteer their history.
- "remind me about X next week": remember kind "reminder" with its date, then save_for_later for the product if \
the store has it. A reminder comes up near its date; don't bring it up before then.
- Never save health, pregnancy, religion, sexuality, finances or details about children beyond what the plan \
needs. Save the event, not the reason ("dinner on Saturday", not why)."""

KINDS = ("event", "reminder", "preference", "note", "name", "household")
MEMBER_TOOLS: list[dict[str, Any]] = [
    _tool("remember", "Save something worth knowing on future trips: a coming event (with its date), a lasting "
          "preference, their name, how many people are in the household. Not small talk.",
          {"kind": {"type": "string", "enum": list(KINDS)}, "text": {"type": "string"},
           "date": {"type": "string", "description": "YYYY-MM-DD, for an event or reminder"}}, ["kind", "text"]),
    _tool("save_for_later", "Put store products on a saved list for a coming event, not on today's list.",
          {"memory_id": {"type": "integer"},
           "items": {"type": "array", "items": {"type": "object", "properties": {
               "product_id": {"type": "string"}, "qty": {"type": "integer", "minimum": 1}}, "required": ["product_id"]}}},
          ["memory_id", "items"]),
    _tool("forget", "Forget one memory the shopper asked you to forget.", {"memory_id": {"type": "integer"}},
          ["memory_id"]),
    _tool("shop_saved_list", "Put a saved event list on today's shopping list, keeping what's already on it.",
          {"memory_id": {"type": "integer"}}, ["memory_id"]),
    _tool("show_memories", "The shopper asked what you know or remember about them: open the memory screen."),
    _tool("sign_out", "The shopper says they aren't this member, or wants to sign out."),
]
MEMBER_TOOL_NAMES = {t["name"] for t in MEMBER_TOOLS}

_GREETINGS = {"hey kart", "hi kart", "hello kart", "hey cart", "hi cart", "hello cart", "hey", "hi", "hello", "kart",
              "cart", "hey there", "hi there", "hello there", "yo kart", "ok kart", "okay kart"}


def only_greeting(text: str) -> bool:
    """A bare "Hey Kart": nothing asked, so Kart can ask its one question for the trip."""
    return " ".join(re.sub(r"[^a-z ]+", " ", text.lower()).split()) in _GREETINGS


def _name(profile: dict[str, Any] | None) -> str | None:
    return ((profile or {}).get("member") or {}).get("name")


def welcome_line(profile: dict[str, Any] | None) -> str:
    if profile is None:
        return WELCOME_BACK
    if _name(profile):
        return f"Welcome back, {_name(profile)}!"
    if not (profile.get("member") or {}).get("trips") and not profile.get("memories"):
        return NICE_TO_MEET
    return WELCOME_BACK


def question(profile: dict[str, Any] | None, n: int) -> str:
    """Kart's one question for the trip: their name first, else the next in the rotation."""
    if profile is not None and not _name(profile):   # a member Kart can't name yet (an unknown profile: don't ask)
        return NAME_QUESTION
    return QUESTIONS[n % len(QUESTIONS)]


def still_there_line(profile: dict[str, Any] | None) -> str:
    """Said after 3 quiet minutes while signed in; the iPad signs out at 5."""
    return f"Still shopping, {_name(profile)}?" if _name(profile) else "Still shopping?"


def after_last_drop(lines: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """A rejoined call's history starts after the last "forget me" or "not me": that member is gone for good."""
    for i in range(len(lines) - 1, -1, -1):
        text = lines[i].get("text") or ""
        if lines[i].get("role") == "agent" and (text == FORGOTTEN_LINE or GUEST_NOW in text):
            return lines[i + 1:]
    return lines


def saved_list_offer(profile: dict[str, Any] | None) -> tuple[dict[str, Any], str] | None:
    """An event in the next two days with a saved list: Kart offers it in a fixed line (the demo's recall moment)."""
    for m in (profile or {}).get("memories") or []:
        if m.get("kind") == "event" and m.get("items") and m.get("days_until") is not None and 0 <= m["days_until"] <= 2:
            return m, f"{_label(m)} is {_when(m['days_until'])}. Want the list you saved?"
    return None


def list_shopped_line(next_step: str | None) -> str:
    return f"Done, it's on your list. First stop: {next_step}." if next_step else "Done, it's on your list."


def _label(memory: dict[str, Any]) -> str:
    return memory["text"].split(",")[0].strip()


def _when(days: int | None) -> str:
    if days is None:
        return "no date yet"
    if days == 0:
        return "today"
    if days == 1:
        return "tomorrow"
    return f"in {days} days" if days > 0 else f"{-days} days ago"


def _dated(memory: dict[str, Any]) -> str:
    if not memory.get("event_date"):
        return "no date yet"
    weekday = date.fromisoformat(memory["event_date"]).strftime("%A")
    return f"{weekday} {memory['event_date']} ({_when(memory.get('days_until'))})"


def _items(memory: dict[str, Any]) -> str:
    items = memory.get("items") or []
    return ", ".join(f"{i['short_name']} x{i['qty']}" for i in items) or "none yet"


def member_section(profile: dict[str, Any] | None) -> str:
    """What Kart remembers, for Claude's system prompt, followed by the rules for using it."""
    if profile is None:                              # the profile didn't load: no facts, but remember still works
        return ("About this shopper: a signed-in member. Kart's memory didn't load this time, so don't mention "
                "anything you remember.\n\n" + MEMBER_RULES)
    member = profile.get("member") or {}
    lines = [f"About this shopper, from Kart's memory (today is {profile['weekday']}, {profile['today']}):"]
    who = f"- Name: {member['name']}" if member.get("name") else "- Name: not known yet"
    if member.get("household"):
        who += f", household of {member['household']}"
    lines.append(f"{who}. Trips here: {member.get('trips', 0)}.")
    start = date.fromisoformat(profile["today"])
    lines.append("- Next two weeks: " + ", ".join(f"{d:%a} {d.isoformat()}" for d in (start + timedelta(days=n)
                                                                                     for n in range(1, 15)))
                 + '. "next Saturday" means the first Saturday after today (the same for any weekday).')
    memories = profile.get("memories") or []
    for m in memories:
        if m["kind"] == "event" and m.get("upcoming"):
            lines.append(f"- Coming up: {m['text']}, {_dated(m)} [memory id {m['id']}]; saved list: {_items(m)}.")
    for m in memories:
        if m["kind"] == "event" and not m.get("upcoming") and m.get("days_until") is not None and m["days_until"] >= -7:
            lines.append(f"- Recently: {m['text']}, {_dated(m)} [memory id {m['id']}]. You may ask how it went.")
    for m in memories:
        if m["kind"] != "reminder" or m.get("days_until") is None:
            continue
        if -3 <= m["days_until"] <= 1:
            lines.append(f"- Reminder due now: {m['text']}, {_dated(m)} [memory id {m['id']}]; saved list: {_items(m)}.")
        elif m["days_until"] > 1:
            lines.append(f"- Reminder for later: {m['text']}, {_dated(m)} [memory id {m['id']}]. "
                         "Don't bring it up before then.")
    for m in memories:
        if m["kind"] == "preference":
            lines.append(f"- Likes: {m['text']} [memory id {m['id']}].")
        elif m["kind"] == "note":
            lines.append(f"- Note: {m['text']} [memory id {m['id']}].")
    usuals = profile.get("usuals") or []
    if usuals:
        parts = []
        for u in usuals:
            rhythm = f"every {u['every_days']} days" if u.get("every_days") else f"{u['times']} times"
            if u.get("weekday"):
                rhythm += f", usually {u['weekday']}"
            parts.append(f"{u['short_name']} ({rhythm}, last {u['last']})")
        lines.append("- Usually buys: " + "; ".join(parts) + ".")
    picks = profile.get("picks") or []
    if picks:
        lines.append("- This week's picks (on the screen): " + "; ".join(f"{p['short_name']}: {p['reason']}" for p in picks) + ".")
    trip = profile.get("last_trip")
    if trip:
        lines.append(f"- Last trip ({trip['date']}): {', '.join(trip['items'])}.")
    return "\n".join(lines) + "\n\n" + MEMBER_RULES


def _memory_id(args: dict[str, Any]) -> int:
    value = args.get("memory_id")
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError("'memory_id' must be an integer")
    return value


async def member_dispatch(name: str, args: dict[str, Any], ctx: dict[str, Any]) -> Any:
    """The member tools. Writes go through the backend's member RPCs; a write marks the profile stale."""
    member_id = ctx.get("member_id")
    if not member_id:
        raise ValueError("no member is signed in")
    backend = ctx["backend"]
    if name == "show_memories":
        ctx["show_memories"] = True
        return {"ok": True}
    if name == "sign_out":
        await backend.rpc("set_member", p_cart_id=ctx["cart_id"], p_member_id=None)
        ctx["signed_out"] = True
        return {"ok": True, "now": "guest"}
    if name == "shop_saved_list":
        memory_id = _memory_id(args)
        memory = next((m for m in (ctx.get("profile") or {}).get("memories") or [] if m.get("id") == memory_id), None)
        if not memory or not memory.get("items"):
            raise ValueError("that memory has no saved list")
        from .tools import _dispatch                 # tools imports this module; resolve at call time
        cart = await backend.get_cart(ctx["cart_id"])
        plan = [{"product_id": p["product_id"], "reason": p.get("reason", ""), "qty": p.get("qty", 1),
                 "basis": p.get("basis")} for p in cart.get("plan", [])]
        listed = {p["product_id"] for p in plan}
        title = memory["text"].split(",")[0].strip()
        plan += [{"product_id": i["product_id"], "reason": title, "qty": i.get("qty", 1)}
                 for i in memory["items"] if i["product_id"] not in listed]
        return await _dispatch("set_plan", {"items": plan, "meal": title}, ctx)
    if name == "remember":
        kind, text = args.get("kind"), args.get("text")
        if kind not in KINDS:
            raise ValueError(f"'kind' must be one of {', '.join(KINDS)}")
        if not isinstance(text, str) or not text.strip():
            raise ValueError("'text' must be a non-empty string")
        result = await backend.rpc("member_remember", p_member_id=member_id, p_kind=kind, p_text=text.strip(),
                                   p_event_date=args.get("date") or None, p_trip_id=ctx.get("trip_id"))
    elif name == "save_for_later":
        items = args.get("items")
        if not isinstance(items, list) or not items:
            raise ValueError("'items' must be a non-empty list")
        result = await backend.rpc("member_save_for_later", p_member_id=member_id, p_memory_id=_memory_id(args),
                                   p_items=[{"product_id": i.get("product_id"), "qty": i.get("qty", 1)}
                                            for i in items if isinstance(i, dict)])
        if isinstance(result, dict) and result.get("items"):    # "Saved: three boxes of spaghetti and two jars of marinara"
            catalog = {p["id"]: p for p in await backend.get_catalog()}
            said = [_amount(i["qty"], catalog[i["product_id"]]) if i["product_id"] in catalog
                    else f"{i['qty']} {i['short_name']}" for i in result["items"]]
            listed = said[0] if len(said) == 1 else ", ".join(said[:-1]) + " and " + said[-1]
            result = {**result, "readback": f"Saved: {listed} for {_label(result)}."}
    elif name == "forget":
        result = await backend.rpc("member_forget", p_member_id=member_id, p_memory_id=_memory_id(args))
    else:
        raise ValueError(f"unknown member tool: {name}")
    ctx["memory_changed"] = True
    return result
