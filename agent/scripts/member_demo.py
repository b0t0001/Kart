"""The member memory beat, Act 1 → Act 2, run in-process: the real agent code and real Claude, against a Supabase,
playing the iPad's part with RPCs. Prints exactly what Kart says. A test cart and a test member only.

  backend/.venv/bin/python backend/members.py seed --member it-demo --db-url <that Supabase's DB URL>
  cd agent && set -a && . ../.env && set +a
  SUPABASE_URL=… SUPABASE_ANON_KEY=… .venv/bin/python scripts/member_demo.py [--cart it-mem-demo] [--member it-demo]

Act 1: signed in, Dylan tells Kart about Leo's party and says yes to a saved list. Act 2: the demo fast-forward to
the day before the party, a new trip, signed in again: Kart brings the party up, and "yes" shops the list. Cleans up
after itself (the remembered party, the demo date, the beta switch).
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
import time
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from line.events import AgentSendCustom, AgentSendText, CallStarted, UserCustomSent, UserTextSent, UserTurnEnded  # noqa: E402

from kart_agent.agent import KartAgent  # noqa: E402
from kart_agent.backend import SupabaseBackend  # noqa: E402
from kart_agent.brain import Brain  # noqa: E402
from kart_agent.llm import AnthropicLLM  # noqa: E402

ACT1 = ["Oh, next Saturday is Leo's soccer team party, we'll need pasta for 12.", "Yes."]
ACT2 = ["Yes.", "What do you know about me?"]


async def say(agent: KartAgent, event) -> tuple[str, list[dict]]:
    texts, customs = [], []
    async for out in agent.process(None, event):
        if isinstance(out, AgentSendText):
            texts.append(out.text)
        elif isinstance(out, AgentSendCustom):
            customs.append(out.metadata)
    return "".join(texts).strip(), customs


async def call(backend: SupabaseBackend, cart: str, member: str, lines: list[str]) -> None:
    """One Kart call, as the iPad starts it: the trip context names the member, then the shopper talks."""
    trip = (await backend.get_cart(cart))["trip_id"]
    agent = KartAgent(backend=backend, brain=Brain(llm=AnthropicLLM()), cart_id=cart, context_wait_seconds=0.2)
    agent.run_filter(UserCustomSent(metadata={"type": "trip_context", "cart_id": cart, "trip_id": trip, "member_id": member}))
    started = time.monotonic()
    text, _ = await say(agent, CallStarted())
    for line in (t for t in await backend.get_transcript(cart, trip) if t["role"] == "agent"):
        print(f"  Kart: {line['text']}")
    print(f"        ({time.monotonic() - started:.1f} s)")
    for line in lines:
        print(f"  Dylan: {line}")
        started = time.monotonic()
        text, customs = await say(agent, UserTurnEnded(content=[UserTextSent(content=line)]))
        shown = "".join(f"  [iPad: {c['type']}]" for c in customs)
        print(f"  Kart: {text}{shown}   ({time.monotonic() - started:.1f} s)")


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--cart", default="it-mem-demo")
    ap.add_argument("--member", default="it-demo")
    args = ap.parse_args()
    if args.cart == "7" or args.member == "1029":
        sys.exit("Use a test cart and a test member (cart 7 and member 1029 are the demo's).")
    backend = SupabaseBackend(os.environ["SUPABASE_URL"], os.environ["SUPABASE_ANON_KEY"])
    cart, member = args.cart, args.member
    await backend.rpc("reset_cart", p_cart_id=cart)
    await backend.rpc("set_feature", p_cart_id=cart, p_feature="member_memory", p_on=True)
    await backend.rpc("set_demo_date", p_cart_id=cart, p_date=None)
    before = {m["id"] for m in (await backend.rpc("member_profile", p_member_id=member) or {}).get("memories", [])}
    try:
        await backend.rpc("set_member", p_cart_id=cart, p_member_id=member)          # the iPad: sign-in, "That's me"
        today = (await backend.rpc("member_profile", p_member_id=member, p_cart_id=cart))["today"]
        print(f"ACT 1: signed in as {member}, cart {cart}, today {today} ({date.fromisoformat(today):%A})")
        await call(backend, cart, member, ACT1)
        profile = await backend.rpc("member_profile", p_member_id=member, p_cart_id=cart)
        party = next((m for m in profile["memories"] if m["id"] not in before and m["kind"] == "event"), None)
        if not party:
            sys.exit("Kart didn't remember an event in Act 1.")
        items = ", ".join(f"{i['short_name']} ×{i['qty']}" for i in party.get("items") or []) or "no list"
        print(f"  (remembered: {party['text']} · {party['event_date']} · {items})")

        eve = date.fromisoformat(party["event_date"]) - timedelta(days=1)            # the iPad's Fast-forward button
        await backend.rpc("set_demo_date", p_cart_id=cart, p_date=eve.isoformat())
        await backend.rpc("reset_cart", p_cart_id=cart)                               # a new trip: signed out
        await backend.rpc("set_member", p_cart_id=cart, p_member_id=member)          # signed in again
        print(f"\nACT 2: fast-forward to {eve} ({eve:%A}), a new trip, signed in again")
        await call(backend, cart, member, ACT2)
        plan = (await backend.get_cart(cart))["plan"]
        print("  (list: " + ", ".join(f"{p.get('name') or p['product_id']} ×{p.get('qty', 1)}" for p in plan) + ")")
    finally:
        after = (await backend.rpc("member_profile", p_member_id=member) or {}).get("memories", [])
        for m in after:
            if m["id"] not in before:
                await backend.rpc("member_forget", p_member_id=member, p_memory_id=m["id"])
        await backend.rpc("set_demo_date", p_cart_id=cart, p_date=None)
        await backend.rpc("reset_cart", p_cart_id=cart)
        await backend.rpc("set_feature", p_cart_id=cart, p_feature="member_memory", p_on=None)


if __name__ == "__main__":
    asyncio.run(main())
