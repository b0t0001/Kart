"""The Line agent: greets, answers the shopper with Claude, and speaks up when the cart or a deal changes."""

from __future__ import annotations

import asyncio
import json
import time
from typing import Any, AsyncIterator

from line.events import AgentSendCustom, AgentSendText, CallEnded, CallStarted, UserCustomSent, UserTurnEnded, UserTurnStarted

from .brain import Brain
from .lines import (DECLINED_LINE, KEEP_LINE, LIST_KEPT, LIST_TOO, NUDGE_OK_LINE, accepted_line, nudge_answer, only_ack,
                    only_filler, proactive_line, yes_or_no)
from .tools import run_tool

GREETING = "Hi, I'm Kart. What are we shopping for today?"
ADD_THEN_DEAL_SECONDS = 3.0                         # a deal this soon after an add says "Got the X." first
SPEAKING_EVENTS = {"suggestion", "nudge", "deal_changed", "cart_changed", "ui_action"}


def _count_word(n: int) -> str:
    return ["zero", "one", "two", "three"][n] if 0 <= n <= 3 else str(n)


def _digest_answer(text: str) -> str | None:
    """"Yes" / "not now" to the deals question or to one deal; None for anything else (Claude hears it)."""
    lowered = text.lower()
    if "not now" in lowered or "later" in lowered:
        return "no"
    return yes_or_no(text)


def _said_key(meta: dict[str, Any]) -> str | None:
    """Deals are offered once per trip and nudges once per product and direction per trip, so these keys are stable."""
    if meta.get("type") == "suggestion" and meta.get("deal_id"):
        return f"suggestion|{meta['deal_id']}"
    if meta.get("type") == "nudge" and meta.get("product_id"):
        return f"nudge|{meta['product_id']}|{meta.get('kind')}"
    return None


class KartAgent:
    """One per call. `run_filter` decides which events start a turn (a new turn cuts off the current one)."""

    def __init__(self, backend: Any, brain: Brain, cart_id: str = "7", coalesce_seconds: float = 0.6,
                 context_wait_seconds: float = 1.0, barge_in: bool = True, digest_delay_seconds: float = 2.5):
        self.backend = backend
        self.brain = brain
        self.cart_id = cart_id                      # the default; the iPad's trip_context names the real one
        self.trip_id: str | None = None
        self.coalesce_seconds = coalesce_seconds    # an "added" line waits this long for a paired suggestion
        self.context_wait_seconds = context_wait_seconds   # how long the greeting waits for the iPad's trip_context
        self.barge_in = barge_in                    # off (KART_BARGE_IN=off) for a loud floor: nothing cuts Kart off
        self.digest_delay_seconds = digest_delay_seconds   # the pause after reading the list before asking about deals
        self._digest: dict[str, Any] | None = None  # "N deals go with your list": asked, then walked one at a time
        self._digest_offered = False
        self._context = asyncio.Event()
        self._plan: list[dict[str, Any]] = []
        self._items: list[dict[str, Any]] = []
        self._catalog: list[dict[str, Any]] = []
        self._speaking = False
        self._pending: str | None = None            # a proactive line that arrived while Kart was talking
        self._last_add: tuple[dict[str, Any], float] | None = None   # the latest "added" event, until it's said
        self._undo: list[dict[str, Any]] = []      # earlier lists, newest last: "undo" puts the last one back
        self._list_too: str | None = None         # the product Kart asked "Take it off the list too?" about
        self._offer: dict[str, Any] | None = None   # the deal Kart just asked about, until it's answered
        self._nudge: dict[str, Any] | None = None   # the quantity nudge Kart just said (v0.12 beta)
        self._last_asked: str | None = None         # "offer" or "nudge": a plain answer goes to the latest question
        self._said: set[str] = set()                # deals and nudges already said this trip (repeats are dropped)
        self._meal: str | None = None               # "taco night for 4", from Claude's set_plan
        self._nudges = False                        # the cart's quantity_nudges beta (carts.features)

    # Line filters --------------------------------------------------------------------------------

    def run_filter(self, event: Any) -> bool:
        if isinstance(event, (CallStarted, UserTurnEnded, CallEnded)):
            return True
        if isinstance(event, UserCustomSent):
            meta = event.metadata or {}
            if meta.get("type") == "trip_context":       # state only: never interrupt Kart for it
                self.cart_id = str(meta.get("cart_id") or self.cart_id)
                if meta.get("trip_id") and meta.get("trip_id") != self.trip_id:   # a new trip starts fresh
                    self._said, self._meal, self._offer, self._nudge = set(), None, None, None
                    self._undo = []
                    self._digest, self._digest_offered = None, False
                self.trip_id = meta.get("trip_id") or self.trip_id
                self._context.set()
                return False
            key = _said_key(meta)
            if key in self._said:                        # the same deal or nudge again (a burst, a second screen)
                return False
            if key:
                self._said.add(key)
            if meta.get("type") == "suggestion" and self._digest:   # mid walk-through: Kart is reading them out
                return False
            if meta.get("type") == "cart_changed" and meta.get("change") == "added":
                self._last_add = (meta, time.monotonic())   # a paired deal right behind it says "Got the X" first
            if meta.get("type") == "suggestion":
                self._offer = meta                       # "Want it?" can now be answered with a plain yes or no
                self._last_asked = "offer"
            elif meta.get("type") == "nudge":
                self._nudge = meta                       # "Keep it?" / "Before you go…" can be answered by voice
                self._last_asked = "nudge"
            elif meta.get("type") == "card_response":    # answered on the screen
                if str(meta.get("card_id", "")).startswith("digest"):
                    return self._digest is not None      # the deals walk-through: Kart says the next one
                if str(meta.get("card_id", "")).startswith("nudge-"):
                    self._nudge = None
                else:
                    self._offer = None
            if meta.get("type") not in SPEAKING_EVENTS:
                return False
            line = proactive_line(meta, self._catalog, self._plan, self._items, self._meal, self._nudges)
            if not line:
                return False
            if self._speaking:                           # never cut Kart off: say it when this turn ends
                self._pending = line
                return False
            return True
        return False

    def cancel_filter(self, event: Any) -> bool:
        return self.barge_in and isinstance(event, UserTurnStarted)   # barge-in

    # Line agent --------------------------------------------------------------------------------

    async def process(self, env: Any, event: Any) -> AsyncIterator[AgentSendText]:
        if isinstance(event, CallStarted):
            try:                                         # the iPad says which cart right after the call starts
                await asyncio.wait_for(self._context.wait(), self.context_wait_seconds)
            except TimeoutError:
                pass
            await self._refresh()
            if self._plan or self._items:                # rejoining a trip in progress (app relaunch, reconnect)
                return
            async for out in self._say([GREETING], interruptible=False):   # chatter can't wipe the greeting
                yield out
        elif isinstance(event, UserTurnEnded):
            text = " ".join(part.content for part in event.content if hasattr(part, "content") and part.content).strip()
            if not text or only_filler(text):            # "Um." gets no answer and no caption
                return
            if not self._offer and not self._nudge and not self._digest and not self._list_too and only_ack(text):
                return
            await self._refresh()
            ctx = self._ctx()
            plain = yes_or_no(text) if self._list_too and self._last_asked == "list_too" else None
            if plain:                                    # "Take it off the list too?" "Yes."
                await self._caption("user", text)
                product_id, self._list_too = self._list_too, None
                line = LIST_KEPT
                if plain == "yes":
                    out = json.loads(await run_tool("remove_from_plan", {"product_id": product_id}, ctx))
                    line = out.get("readback") or line
                self.brain.remember(text, line)
                async for out_text in self._say([line], interruptible=False):
                    yield out_text
                return
            digest_reply = _digest_answer(text) if self._digest and self._last_asked == "digest" else None
            if digest_reply:                             # "yes" / "not now" to the deals walk-through
                await self._caption("user", text)
                async for out in self._digest_step(digest_reply, ctx):
                    yield out
                return
            asked_nudge = self._nudge and (self._last_asked == "nudge" or not self._offer)
            nudge_reply = nudge_answer(text) if asked_nudge else None
            if asked_nudge and nudge_reply is None:      # a plain yes/no answers the nudge's own question
                plain = yes_or_no(text)
                checkout_list = bool(self._nudge.get("items"))
                if plain == "yes":
                    nudge_reply = "keep" if self._nudge.get("kind") == "over" else ("shop" if checkout_list else "ok")
                elif plain == "no":
                    nudge_reply = "skip" if checkout_list else "ok"
            if nudge_reply:                              # "keep it" / "got it": dismiss_nudge, no Claude round
                await self._caption("user", text)
                nudge, self._nudge = self._nudge, None
                if nudge_reply == "ok" and nudge.get("items"):  # "no thanks" to the checkout list: skip them all
                    nudge_reply = "skip"
                await run_tool("dismiss_nudge", {"action": nudge_reply}, ctx)   # shop: the backend goes back to shopping
                line = KEEP_LINE if nudge_reply == "keep" else NUDGE_OK_LINE
                if nudge_reply == "shop":                    # short at checkout: say where to go
                    items = nudge.get("items") if isinstance(nudge.get("items"), list) else []
                    first = items[0].get("aisle") if items else None
                    aisle = first or next((p.get("aisle") for p in self._catalog if p["id"] == nudge.get("product_id")), None)
                    line = (f"Okay, start in {aisle}." if len(items) > 1 else f"Okay, it's in {aisle}.") if aisle \
                        else "Okay, go grab it."
                self.brain.remember(text, line)
                async for out in self._say([line], interruptible=False):
                    yield out
                return
            answer = yes_or_no(text) if self._offer else None
            if answer:                                   # a plain yes/no to the deal: no Claude round, nothing invented
                await self._caption("user", text)
                offer, self._offer = self._offer, None
                if answer == "yes":
                    await run_tool("add_to_plan", {"product_id": offer.get("product_id"), "reason": "deal"}, ctx)
                    await self._refresh()                # on the list now: its add gets "Got the X."
                    line = accepted_line(self._catalog, offer.get("product_id"))
                else:
                    await run_tool("dismiss_suggestion", {}, ctx)
                    line = DECLINED_LINE
                self.brain.remember(text, line)
                async for out in self._say([line], interruptible=False):
                    yield out
                return
            heard = text
            if self._offer:                              # more than a yes/no: Claude still needs to know what was asked
                heard = f'(Kart just asked: "{self._offer.get("text", "")}") {text}'
                self._offer = None
            async for out in self._say(self._caption_first(text, self.brain.respond(heard, ctx)), interruptible=self.barge_in):
                yield out
            self._meal = ctx.get("meal") or self._meal
            await self._refresh()                        # Claude's tools may have changed the list
            if ctx.get("planned") and not self._digest_offered:     # a new list: ask about the deals, after a beat
                async for out in self._offer_digest():
                    yield out
        elif isinstance(event, UserCustomSent):
            meta = event.metadata or {}
            if meta.get("type") == "card_response" and str(meta.get("card_id", "")).startswith("digest"):
                answer = "yes" if meta.get("action") == "yes" else "no"
                ctx = self._ctx()
                async for out in self._digest_step(answer, ctx):
                    yield out
                return
            if meta.get("type") == "cart_changed" and meta.get("change") == "added":
                await asyncio.sleep(self.coalesce_seconds)   # a paired deal suggestion arriving now replaces this line
            await self._refresh()
            line = proactive_line(meta, self._catalog, self._plan, self._items, self._meal, self._nudges)
            if meta.get("type") == "cart_changed" and meta.get("change") == "added":
                self._last_add = None                    # said (or nothing to say): a later deal stands alone
            if line and line.endswith(LIST_TOO):
                self._list_too, self._last_asked = meta.get("product_id"), "list_too"
            elif line and meta.get("type") == "suggestion" and self._last_add:
                add, at = self._last_add
                self._last_add = None
                got = proactive_line(add, self._catalog, self._plan, self._items, self._meal, self._nudges)
                if got and time.monotonic() - at < ADD_THEN_DEAL_SECONDS:   # the deal cancelled the add's own line
                    line = f"{got} {line}"
            if line:
                async for out in self._say([line], interruptible=False):
                    yield out

    # Deals: ask first, then one at a time --------------------------------------------------------------------

    async def _relevant_deals(self) -> list[dict[str, Any]]:
        """Live deals on something not on the list or in the cart that pair with the list, in route order (max 3)."""
        try:
            deals = await self.backend.get_live_deals()
        except Exception:
            return []
        catalog = {p["id"]: p for p in self._catalog}
        plan = [line.get("product_id") for line in self._plan]
        taken = set(plan) | {i.get("product_id") for i in self._items}
        found = []
        for deal in deals:
            product = catalog.get(deal.get("product_id"))
            pairs = [plan.index(p) for p in deal.get("pairs_with") or [] if p in plan]
            if product is None or product.get("in_stock") is False or deal["product_id"] in taken or not pairs:
                continue
            found.append((min(pairs), deal, product))
        return [{"deal": d, "product": p} for _, d, p in sorted(found, key=lambda x: x[0])][:3]

    async def _offer_digest(self) -> AsyncIterator[Any]:
        await self._refresh()
        deals = await self._relevant_deals()
        if not deals:
            return
        self._digest_offered = True
        await asyncio.sleep(self.digest_delay_seconds)
        self._digest, self._last_asked = {"deals": deals, "i": -1}, "digest"
        n = len(deals)
        question = (f"By the way, one deal goes with your list. Want to hear it?" if n == 1
                    else f"By the way, {_count_word(n)} deals go with your list. Want to hear them?")
        yield AgentSendCustom(metadata={"type": "deal_digest", "count": n})
        async for out in self._say([question], interruptible=False):
            yield out

    def _deal_line(self, entry: dict[str, Any]) -> str:
        product, deal = entry["product"], entry["deal"]
        return f"{product.get('short_name') or product['name']} is {deal['label']} in {product.get('aisle')}. Want it?"

    async def _digest_step(self, answer: str, ctx: dict[str, Any]) -> AsyncIterator[Any]:
        digest = self._digest
        if digest is None:
            return
        if digest["i"] < 0 and answer != "yes":                     # "not now": each deal is said at its shelf
            self._digest = None
            yield AgentSendCustom(metadata={"type": "digest_done"})
            async for out in self._say(["No problem. I'll tell you at the shelf."], interruptible=False):
                yield out
            return
        prefix = ""
        if digest["i"] >= 0:                                         # the answer to the deal just read out
            entry = digest["deals"][digest["i"]]
            name = entry["product"].get("short_name") or entry["product"]["name"]
            if answer == "yes":
                await run_tool("add_to_plan", {"product_id": entry["product"]["id"], "reason": "deal"}, ctx)
                await self._refresh()
                prefix = f"Added {name} to your list. "
            else:
                prefix = "Okay. "
        digest["i"] += 1
        if digest["i"] < len(digest["deals"]):
            entry = digest["deals"][digest["i"]]
            self._said.add(f"suggestion|{entry['deal']['id']}")    # walked here: never read out again this trip
            line = self._deal_line(entry)
            yield AgentSendCustom(metadata={"type": "digest_deal", "deal_id": entry["deal"]["id"],
                                            "product_id": entry["product"]["id"], "text": line,
                                            "index": digest["i"] + 1, "count": len(digest["deals"])})
            async for out in self._say([prefix + line], interruptible=False):
                yield out
            return
        self._digest = None
        yield AgentSendCustom(metadata={"type": "digest_done"})
        async for out in self._say([prefix + "That's all the deals."], interruptible=False):
            yield out

    async def _caption_first(self, user_text: str, chunks: AsyncIterator[str]) -> AsyncIterator[str]:
        """The shopper's words reach the thread only once Kart answers, so chatter Kart stays quiet on never shows."""
        first = True
        async for chunk in chunks:
            if first:
                first = False
                await self._caption("user", user_text)
            yield chunk

    async def _say(self, chunks: Any, interruptible: bool = True) -> AsyncIterator[AgentSendText]:
        """Speaks chunks as they arrive and captions whatever was actually said, even if the shopper cuts in."""
        spoken: list[str] = []
        self._speaking = True
        try:
            if hasattr(chunks, "__aiter__"):
                async for chunk in chunks:
                    spoken.append(chunk)
                    yield AgentSendText(text=chunk, interruptible=interruptible)
            else:
                for chunk in chunks:
                    spoken.append(chunk)
                    yield AgentSendText(text=chunk, interruptible=interruptible)
            if self._pending:                            # a deal or cart line that waited for Kart to finish
                await self._flush_caption(spoken)
                spoken = [self._pending]
                self._pending = None
                yield AgentSendText(text=spoken[0], interruptible=False)
        finally:
            self._speaking = False
            await self._flush_caption(spoken)

    async def _flush_caption(self, spoken: list[str]) -> None:
        if spoken:
            text = "".join(spoken).strip()
            spoken.clear()
            await asyncio.shield(asyncio.ensure_future(self._caption("agent", text)))

    async def _caption(self, role: str, text: str) -> None:
        try:
            await self.backend.rpc("append_transcript", p_cart_id=self.cart_id, p_role=role, p_text=text)
        except Exception:
            pass                                          # captions must never break the conversation

    def _ctx(self) -> dict[str, Any]:
        """What the tools get: the backend, this cart and trip, and the trip's undo history."""
        return {"backend": self.backend, "cart_id": self.cart_id, "trip_id": self.trip_id, "undo": self._undo}

    async def _refresh(self) -> None:
        try:
            cart = await self.backend.get_cart(self.cart_id)
            self.trip_id = self.trip_id or cart.get("trip_id")
            self._plan = cart.get("plan", [])
            self._items = cart.get("items", [])
            self._nudges = bool((cart.get("features") or {}).get("quantity_nudges"))
            live = cart.get("nudge") if "nudge" in cart else self._nudge
            if self._nudge and not (live and (live.get("product_id"), live.get("kind")) ==
                                    (self._nudge.get("product_id"), self._nudge.get("kind"))):
                self._nudge = None                       # cleared or replaced on the cart: nothing left to answer
            self._catalog = self._catalog or await self.backend.get_catalog()
            self.brain.set_catalog(self._catalog)
        except Exception:
            pass
