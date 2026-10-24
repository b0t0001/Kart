"""Member memory (CONTRACT v0.14, BETA): what Kart knows about a signed-in member, and how it uses it.

The backend computes the facts (`member_profile`: picks, rhythms, memories); this module turns them into
Claude's prompt, the fixed lines Kart says on its own, and the member-only tools.
"""

from __future__ import annotations

import re
from datetime import date
from typing import Any

from .tools import _tool

WELCOME_BACK = "Welcome back!"
NICE_TO_MEET = "Nice to meet you!"
PROFILE_FAILED_LINE = "Welcome back! What are we shopping for today?"
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
- "Forget that" is forget with that memory's id."""

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
    return QUESTIONS[n % len(QUESTIONS)] if _name(profile) else NAME_QUESTION


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


def member_section(profile: dict[str, Any]) -> str:
    """What Kart remembers, for Claude's system prompt, followed by the rules for using it."""
    member = profile.get("member") or {}
    lines = [f"About this shopper, from Kart's memory (today is {profile['weekday']}, {profile['today']}):"]
    who = f"- Name: {member['name']}" if member.get("name") else "- Name: not known yet"
    if member.get("household"):
        who += f", household of {member['household']}"
    lines.append(f"{who}. Trips here: {member.get('trips', 0)}.")
    memories = profile.get("memories") or []
    for m in memories:
        if m["kind"] == "event" and m.get("upcoming"):
            lines.append(f"- Coming up: {m['text']}, {_dated(m)} [memory id {m['id']}]; saved list: {_items(m)}.")
    for m in memories:
        if m["kind"] == "event" and not m.get("upcoming") and m.get("days_until") is not None and m["days_until"] >= -7:
            lines.append(f"- Recently: {m['text']}, {_dated(m)} [memory id {m['id']}]. You may ask how it went.")
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
    elif name == "forget":
        result = await backend.rpc("member_forget", p_member_id=member_id, p_memory_id=_memory_id(args))
    else:
        raise ValueError(f"unknown member tool: {name}")
    ctx["memory_changed"] = True
    return result
