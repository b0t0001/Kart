"""The Line agent: greets, answers the shopper with Claude, and speaks up when the cart or a deal changes."""

from __future__ import annotations

import asyncio
from typing import Any, AsyncIterator

from line.events import AgentSendText, CallEnded, CallStarted, UserCustomSent, UserTurnEnded, UserTurnStarted

from .brain import Brain
from .lines import (DECLINED_LINE, KEEP_LINE, NUDGE_OK_LINE, accepted_line, nudge_answer, only_ack, only_filler,
                    proactive_line, yes_or_no)
from .tools import run_tool

GREETING = "Hi, I'm Kart. What are we shopping for today?"
SPEAKING_EVENTS = {"suggestion", "nudge", "deal_changed", "cart_changed"}


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
                 context_wait_seconds: float = 1.0, barge_in: bool = True):
        self.backend = backend
        self.brain = brain
        self.cart_id = cart_id                      # the default; the iPad's trip_context names the real one
        self.trip_id: str | None = None
        self.coalesce_seconds = coalesce_seconds    # an "added" line waits this long for a paired suggestion
        self.context_wait_seconds = context_wait_seconds   # how long the greeting waits for the iPad's trip_context
        self.barge_in = barge_in                    # off (KART_BARGE_IN=off) for a loud floor: nothing cuts Kart off
        self._context = asyncio.Event()
        self._plan: list[dict[str, Any]] = []
        self._items: list[dict[str, Any]] = []
        self._catalog: list[dict[str, Any]] = []
        self._speaking = False
        self._pending: str | None = None            # a proactive line that arrived while Kart was talking
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
                self.trip_id = meta.get("trip_id") or self.trip_id
                self._context.set()
                return False
            key = _said_key(meta)
            if key in self._said:                        # the same deal or nudge again (a burst, a second screen)
                return False
            if key:
                self._said.add(key)
            if meta.get("type") == "suggestion":
                self._offer = meta                       # "Want it?" can now be answered with a plain yes or no
                self._last_asked = "offer"
            elif meta.get("type") == "nudge":
                self._nudge = meta                       # "Keep it?" / "Before you go…" can be answered by voice
                self._last_asked = "nudge"
            elif meta.get("type") == "card_response":    # answered on the screen
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
            if not self._offer and not self._nudge and only_ack(text):   # "Okay, so." with nothing asked
                return
            await self._refresh()
            ctx = {"backend": self.backend, "cart_id": self.cart_id, "trip_id": self.trip_id}
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
        elif isinstance(event, UserCustomSent):
            meta = event.metadata or {}
            if meta.get("type") == "cart_changed" and meta.get("change") == "added":
                await asyncio.sleep(self.coalesce_seconds)   # a paired deal suggestion arriving now replaces this line
            await self._refresh()
            line = proactive_line(meta, self._catalog, self._plan, self._items, self._meal, self._nudges)
            if line:
                async for out in self._say([line], interruptible=False):
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

    async def _refresh(self) -> None:
        try:
            cart = await self.backend.get_cart(self.cart_id)
            self.trip_id = self.trip_id or cart.get("trip_id")
            self._plan = cart.get("plan", [])
            self._items = cart.get("items", [])
            self._nudges = bool((cart.get("features") or {}).get("quantity_nudges"))
            self._catalog = self._catalog or await self.backend.get_catalog()
            self.brain.set_catalog(self._catalog)
        except Exception:
            pass
