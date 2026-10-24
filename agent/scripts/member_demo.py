"""The demo script (docs/DEMO_PLAN.md, member beta) run in-process: the real agent code and real Claude, against a
Supabase, playing the iPad's part (sign-in, camera drops via apply_cart_event, the deal/nudge/cart events the iPad
sends). Prints exactly what Kart says, with checks. A test cart and a test member only; cleans up after itself.

  backend/.venv/bin/python backend/members.py seed --member it-demo --db-url <that Supabase's DB URL>
  cd agent && set -a && . ../.env && . ../.env.local-stack && set +a      # Claude key + the local stack
  .venv/bin/python scripts/member_demo.py [--cart it-mem-demo] [--member it-demo]

Act 1 (steps 0–5c): pasta night for 4 → garlic bread off → scissors → spaghetti + the Parmesan deal → marinara →
a second spaghetti nudged and put back → mid-trip, Leo's party remembered and its list saved (today's list untouched).
Act 2 (steps 8–10): fast-forward to the day before, a new trip, sign in → the saved list → three spaghetti, no
nudge (a fourth nudges) → "What do you know about me?".
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
import uuid
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from line.events import AgentSendCustom, AgentSendText, CallStarted, UserCustomSent, UserTextSent, UserTurnEnded  # noqa: E402

from kart_agent.agent import KartAgent  # noqa: E402
from kart_agent.backend import SupabaseBackend  # noqa: E402
from kart_agent.brain import Brain  # noqa: E402
from kart_agent.llm import AnthropicLLM  # noqa: E402

PARTY = "Oh, next Saturday is Leo's soccer team party, we'll need pasta for 12."


class Demo:
    def __init__(self, backend: SupabaseBackend, cart: str, member: str):
        self.backend, self.cart, self.member = backend, cart, member
        self.agent: KartAgent | None = None
        self.seen_deal: str | None = None
        self.seen_nudge: tuple | None = None
        self.checks: list[tuple[str, bool]] = []

    async def _run(self, event) -> tuple[str, list[dict]]:
        texts, customs = [], []
        async for out in self.agent.process(None, event):
            if isinstance(out, AgentSendText):
                texts.append(out.text)
            elif isinstance(out, AgentSendCustom):
                customs.append(out.metadata)
        return "".join(texts).strip(), customs

    async def new_call(self) -> None:
        trip = (await self.backend.get_cart(self.cart))["trip_id"]
        self.agent = KartAgent(backend=self.backend, brain=Brain(llm=AnthropicLLM()), cart_id=self.cart,
                               context_wait_seconds=0.2)
        self.agent.run_filter(UserCustomSent(metadata={"type": "trip_context", "cart_id": self.cart, "trip_id": trip,
                                                       "member_id": self.member}))
        self.seen_deal, self.seen_nudge = None, None
        await self._run(CallStarted())
        for line in (t for t in await self.backend.get_transcript(self.cart, trip) if t["role"] == "agent"):
            print(f"    Kart: {line['text']}")

    async def say(self, text: str) -> str:
        print(f"  Dylan: {text}")
        said, customs = await self._run(UserTurnEnded(content=[UserTextSent(content=text)]))
        print(f"    Kart: {said}" + "".join(f"   [iPad: {c['type']}]" for c in customs))
        return said

    async def camera(self, kind: str, product_id: str) -> str:
        """A drop (or a take-out) the Pi bills, then the events the iPad sends; only the last speaking one is heard."""
        print(f"  [camera: {kind} {product_id}]")
        cart = await self.backend.rpc("apply_cart_event", p_cart_id=self.cart, p_type=kind, p_product_id=product_id,
                                      p_confidence=0.95, p_source="vision", p_label=product_id, p_camera=0,
                                      p_snapshot_url=None, p_event_id=str(uuid.uuid4()), p_method="local",
                                      p_resolves_event_id=None)
        return await self.events(cart, [{"type": "cart_changed", "change": kind, "product_id": product_id}])

    async def events(self, cart: dict | None = None, events: list[dict] | None = None) -> str:
        """The deal and nudge events the iPad sends when the cart row changes; only the last speaking one is heard."""
        cart = cart or await self.backend.get_cart(self.cart)
        events = events or []
        deal = cart.get("suggestion")
        if deal and deal.get("deal_id") != self.seen_deal:
            self.seen_deal = deal["deal_id"]
            events.append({"type": "suggestion", "deal_id": deal["deal_id"], "product_id": deal["product_id"],
                           "text": deal["text"]})
        nudge = cart.get("nudge")
        key = nudge and (nudge["product_id"], nudge["kind"], nudge.get("have"))
        if nudge and key != self.seen_nudge:
            self.seen_nudge = key
            events.append({"type": "nudge", **{k: nudge.get(k) for k in ("product_id", "kind", "text", "have", "need",
                                                                          "items")}})
        speaking = [e for e in events if self.agent.run_filter(UserCustomSent(metadata=e))]
        said = (await self._run(UserCustomSent(metadata=speaking[-1])))[0] if speaking else ""
        print(f"    Kart: {said}" if said else "    (Kart says nothing)")
        return said

    def check(self, name: str, ok: bool) -> None:
        self.checks.append((name, ok))
        print(f"    CHECK {'PASS' if ok else 'FAIL'}: {name}")


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--cart", default="it-mem-demo")
    ap.add_argument("--member", default="it-demo")
    args = ap.parse_args()
    if args.cart == "7" or args.member == "1029":
        sys.exit("Use a test cart and a test member (cart 7 and member 1029 are the demo's).")
    backend = SupabaseBackend(os.environ["SUPABASE_URL"], os.environ["SUPABASE_ANON_KEY"])
    demo, cart, member = Demo(backend, args.cart, args.member), args.cart, args.member
    await backend.rpc("reset_cart", p_cart_id=cart)
    for feature in ("member_memory", "quantity_nudges"):
        await backend.rpc("set_feature", p_cart_id=cart, p_feature=feature, p_on=True)
    await backend.rpc("set_demo_date", p_cart_id=cart, p_date=None)
    before = {m["id"] for m in (await backend.rpc("member_profile", p_member_id=member) or {}).get("memories", [])}
    try:
        await backend.rpc("set_member", p_cart_id=cart, p_member_id=member)
        today = (await backend.rpc("member_profile", p_member_id=member, p_cart_id=cart))["today"]
        print(f"ACT 1 — {today} ({date.fromisoformat(today):%A}), cart {cart}, member {member}, nudges on\n  0 sign in")
        await demo.new_call()
        print("  1"); await demo.say("Pasta night for my family of 4."); await demo.say("Not now.")
        print("  2"); await demo.say("We've got garlic bread at home, take it off.")
        print("  3"); await demo.say("Oh, and Leo needs kids' scissors for school.")
        print("  4"); await demo.camera("added", "barilla-spaghetti"); await demo.say("Yes.")
        print("  5"); await demo.camera("added", "rao-marinara"); await demo.say("Add olive oil too.")
        print("  5b"); await demo.camera("added", "barilla-spaghetti"); await demo.say("No.")
        await demo.camera("removed", "barilla-spaghetti")
        print("  5c")
        before_cart = await backend.get_cart(cart)
        asked = await demo.say(PARTY)
        saved = await demo.say("Yes.")
        after_cart = await backend.get_cart(cart)
        for line in (asked, saved):
            demo.check(f"mid-trip, no 'what are we getting' ({line[-40:]!r})", "what are we" not in line.lower())
        demo.check("today's list untouched by the saved list",
                   [(p["product_id"], p.get("qty")) for p in before_cart["plan"]]
                   == [(p["product_id"], p.get("qty")) for p in after_cart["plan"]])
        demo.check("today's nudge untouched", before_cart.get("nudge") == after_cart.get("nudge"))
        profile = await backend.rpc("member_profile", p_member_id=member, p_cart_id=cart)
        party = next((m for m in profile["memories"] if m["id"] not in before and m["kind"] == "event"), None)
        if not party:
            sys.exit("Kart didn't remember an event in step 5c.")
        print(f"    (saved: {party['text']} · {party['event_date']} · "
              + ", ".join(f"{i['short_name']} ×{i['qty']}" for i in party.get("items") or []) + ")")

        eve = date.fromisoformat(party["event_date"]) - timedelta(days=1)
        await backend.rpc("set_demo_date", p_cart_id=cart, p_date=eve.isoformat())         # "Fast-forward to Friday"
        await backend.rpc("reset_cart", p_cart_id=cart)
        await backend.rpc("set_member", p_cart_id=cart, p_member_id=member)
        print(f"\nACT 2 — fast-forward to {eve} ({eve:%A}), a new trip\n  8 sign in")
        await demo.new_call()
        print("  9"); await demo.say("Yes.")
        plan = {p["product_id"]: p.get("qty") for p in (await backend.get_cart(cart))["plan"]}
        demo.check(f"the saved list is today's list ({plan})", plan.get("barilla-spaghetti") == 3)
        await demo.camera("added", "barilla-spaghetti")         # a new trip: the Parmesan card comes back
        await demo.say("No thanks.")                            # a nudge waits while a deal card is up
        for _ in range(2):
            await demo.camera("added", "barilla-spaghetti")
        demo.check("three boxes: no nudge", (await backend.get_cart(cart)).get("nudge") is None)
        await demo.camera("added", "barilla-spaghetti")
        while (await backend.get_cart(cart)).get("suggestion"):   # a nudge waits while a deal card is up
            await demo.say("No thanks.")
        await demo.events()
        nudge = (await backend.get_cart(cart)).get("nudge")
        demo.check(f"a fourth box nudges ({(nudge or {}).get('text')!r})", bool(nudge) and nudge.get("kind") == "over")
        await demo.say("No.")
        await demo.camera("removed", "barilla-spaghetti")
        print("  10"); await demo.say("What do you know about me?")
        failed = [name for name, ok in demo.checks if not ok]
        print(f"\nCHECKS: {len(demo.checks) - len(failed)}/{len(demo.checks)} passed" + (f"; FAILED: {failed}" if failed else ""))
    finally:
        after = (await backend.rpc("member_profile", p_member_id=member) or {}).get("memories", [])
        for m in after:
            if m["id"] not in before:
                await backend.rpc("member_forget", p_member_id=member, p_memory_id=m["id"])
        await backend.rpc("set_demo_date", p_cart_id=cart, p_date=None)
        await backend.rpc("reset_cart", p_cart_id=cart)
        for feature in ("member_memory", "quantity_nudges"):
            await backend.rpc("set_feature", p_cart_id=cart, p_feature=feature, p_on=None)


if __name__ == "__main__":
    asyncio.run(main())
