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

    def __init__(self, backend: Any, brain: Brain, cart_id: str = "7"):
        self.backend = backend
        self.brain = brain
        self.cart_id = cart_id
        self.trip_id: str | None = None
        self._plan: list[dict[str, Any]] = []
        self._catalog: list[dict[str, Any]] = []

    # Line filters --------------------------------------------------------------------------------

    def run_filter(self, event: Any) -> bool:
        if isinstance(event, (CallStarted, UserTurnEnded, CallEnded)):
            return True
        if isinstance(event, UserCustomSent):
            meta = event.metadata or {}
            if meta.get("type") == "trip_context":       # state only: never interrupt Kart for it
                self.cart_id = str(meta.get("cart_id") or self.cart_id)
                self.trip_id = meta.get("trip_id") or self.trip_id
                return False
            if meta.get("type") not in SPEAKING_EVENTS:
                return False
            return proactive_line(meta, self._catalog, self._plan) is not None or meta.get("type") == "cart_changed" \
                and meta.get("change") != "added"
        return False

    def cancel_filter(self, event: Any) -> bool:
        return isinstance(event, UserTurnStarted)        # barge-in

    # Line agent --------------------------------------------------------------------------------

    async def process(self, env: Any, event: Any) -> AsyncIterator[AgentSendText]:
        if isinstance(event, CallStarted):
            await self._refresh()
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
            await self._refresh()
            line = proactive_line(event.metadata or {}, self._catalog, self._plan)
            if line:
                async for out in self._say([line]):
                    yield out

    async def _say(self, chunks: Any) -> AsyncIterator[AgentSendText]:
        """Speaks chunks as they arrive and captions whatever was actually said, even if the shopper cuts in."""
        spoken: list[str] = []
        try:
            if hasattr(chunks, "__aiter__"):
                async for chunk in chunks:
                    spoken.append(chunk)
                    yield AgentSendText(text=chunk)
            else:
                for chunk in chunks:
                    spoken.append(chunk)
                    yield AgentSendText(text=chunk)
        finally:
            if spoken:
                caption = asyncio.ensure_future(self._caption("agent", "".join(spoken).strip()))
                await asyncio.shield(caption)

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
            self._catalog = self._catalog or await self.backend.get_catalog()
        except Exception:
            pass
