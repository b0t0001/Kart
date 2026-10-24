"""Kart's conversation: Claude with the store tools, streamed so speech can start on the first words."""

from __future__ import annotations

import json
from typing import Any, AsyncIterator, Protocol

from .tools import TOOLS, run_tool

SYSTEM_PROMPT = """You are Kart, the voice of a smart shopping cart in a warehouse store. The shopper is pushing you \
around the store and hears everything you say, so speak like a warm, quick friend: at most two short sentences per \
turn, no lists, no markdown, no emoji.

What you do: turn what they're shopping for into a list (set_plan / add_to_plan), tell them the next aisle, mention a \
deal only when it's relevant, answer questions about the cart, and start checkout when they're done.

Rules:
- Never invent products, prices, deals, aisles or stock. Every fact comes from a tool result in this conversation; \
look it up first (search_catalog, get_cart, get_deals).
- If something isn't in the store, say so plainly ("I don't see cilantro here").
- Don't plan products that are out of stock; offer the closest in-stock alternative instead.
- When the cameras weren't sure about an item and the shopper tells you what it is, use confirm_item.
- If you didn't catch what they said, ask again in a few words instead of guessing."""


class LLM(Protocol):
    def stream(self, *, system: str, messages: list[dict[str, Any]], tools: list[dict[str, Any]]) -> AsyncIterator[Any]:
        """Yields ("text", chunk) items, then one ("final", content_blocks, stop_reason)."""
        ...


def _block_dict(block: Any) -> dict[str, Any]:
    if hasattr(block, "model_dump"):
        return block.model_dump(exclude_none=True)
    if block.type == "text":
        return {"type": "text", "text": block.text}
    if block.type == "tool_use":
        return {"type": "tool_use", "id": block.id, "name": block.name, "input": block.input}
    return dict(vars(block))


class Brain:
    """Keeps the call's message history and runs the tool loop."""

    MAX_TOOL_ROUNDS = 6

    def __init__(self, llm: LLM, system: str = SYSTEM_PROMPT):
        self.llm = llm
        self.system = system
        self.messages: list[dict[str, Any]] = []

    async def respond(self, user_text: str, ctx: dict[str, Any]) -> AsyncIterator[str]:
        self.messages.append({"role": "user", "content": user_text})
        for _ in range(self.MAX_TOOL_ROUNDS):
            content: list[Any] = []
            stop_reason = "end_turn"
            async for item in self.llm.stream(system=self.system, messages=self.messages, tools=TOOLS):
                if item[0] == "text":
                    yield item[1]
                elif item[0] == "final":
                    content, stop_reason = item[1], item[2]
            self.messages.append({"role": "assistant", "content": [_block_dict(b) for b in content]})
            tool_uses = [b for b in content if b.type == "tool_use"]
            if stop_reason != "tool_use" or not tool_uses:
                return
            results = []
            for block in tool_uses:
                result = await run_tool(block.name, block.input, ctx)
                results.append({"type": "tool_result", "tool_use_id": block.id, "content": result,
                                **({"is_error": True} if '"error"' in result[:12] else {})})
            self.messages.append({"role": "user", "content": results})
        yield "Sorry, give me a second and say that again?"
