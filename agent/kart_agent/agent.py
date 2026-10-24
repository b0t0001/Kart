"""The Line agent: greets, answers the shopper with Claude, and speaks up when the cart or a deal changes."""

from __future__ import annotations

import asyncio
from typing import Any, AsyncIterator

from line.events import AgentSendText, CallEnded, CallStarted, UserCustomSent, UserTurnEnded, UserTurnStarted

from .brain import Brain
from .lines import proactive_line

GREETING = "Hi, I'm Kart. What are we shopping for today?"
SPEAKING_EVENTS = {"suggestion", "deal_changed", "cart_changed"}


class KartAgent:
    """One per call. `run_filter` decides which events start a turn (a new turn cuts off the current one)."""

    def __init__(self, backend: Any, brain: Brain, cart_id: str = "7", coalesce_seconds: float = 0.6,
                 context_wait_seconds: float = 1.0):
        self.backend = backend
        self.brain = brain
        self.cart_id = cart_id                      # the default; the iPad's trip_context names the real one
        self.trip_id: str | None = None
        self.coalesce_seconds = coalesce_seconds    # an "added" line waits this long for a paired suggestion
        self.context_wait_seconds = context_wait_seconds   # how long the greeting waits for the iPad's trip_context
        self._context = asyncio.Event()
        self._plan: list[dict[str, Any]] = []
        self._items: list[dict[str, Any]] = []
        self._catalog: list[dict[str, Any]] = []
        self._speaking = False
        self._pending: str | None = None            # a proactive line that arrived while Kart was talking

    # Line filters --------------------------------------------------------------------------------

    def run_filter(self, event: Any) -> bool:
        if isinstance(event, (CallStarted, UserTurnEnded, CallEnded)):
            return True
        if isinstance(event, UserCustomSent):
            meta = event.metadata or {}
            if meta.get("type") == "trip_context":       # state only: never interrupt Kart for it
                self.cart_id = str(meta.get("cart_id") or self.cart_id)
                self.trip_id = meta.get("trip_id") or self.trip_id
                self._context.set()
                return False
            if meta.get("type") not in SPEAKING_EVENTS:
                return False
            line = proactive_line(meta, self._catalog, self._plan)
            if not line:
                return False
            if self._speaking:                           # never cut Kart off: say it when this turn ends
                self._pending = line
                return False
            return True
        return False

    def cancel_filter(self, event: Any) -> bool:
        return isinstance(event, UserTurnStarted)        # barge-in

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
            async for out in self._say([GREETING]):
                yield out
        elif isinstance(event, UserTurnEnded):
            text = " ".join(part.content for part in event.content if hasattr(part, "content") and part.content).strip()
            if not text:
                return
            await self._caption("user", text)
            await self._refresh()
            ctx = {"backend": self.backend, "cart_id": self.cart_id, "trip_id": self.trip_id}
            async for out in self._say(self.brain.respond(text, ctx)):
                yield out
        elif isinstance(event, UserCustomSent):
            meta = event.metadata or {}
            if meta.get("type") == "cart_changed" and meta.get("change") == "added":
                await asyncio.sleep(self.coalesce_seconds)   # a paired deal suggestion arriving now replaces this line
            await self._refresh()
            line = proactive_line(meta, self._catalog, self._plan)
            if line:
                async for out in self._say([line]):
                    yield out

    async def _say(self, chunks: Any) -> AsyncIterator[AgentSendText]:
        """Speaks chunks as they arrive and captions whatever was actually said, even if the shopper cuts in."""
        spoken: list[str] = []
        self._speaking = True
        try:
            if hasattr(chunks, "__aiter__"):
                async for chunk in chunks:
                    spoken.append(chunk)
                    yield AgentSendText(text=chunk)
            else:
                for chunk in chunks:
                    spoken.append(chunk)
                    yield AgentSendText(text=chunk)
            if self._pending:                            # a deal or cart line that waited for Kart to finish
                await self._flush_caption(spoken)
                spoken = [self._pending]
                self._pending = None
                yield AgentSendText(text=spoken[0])
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
            self._catalog = self._catalog or await self.backend.get_catalog()
        except Exception:
            pass
