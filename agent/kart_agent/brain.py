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
- Never invent products, prices, deals, aisles or stock. The store's products are listed at the end by id: plan \
with those ids directly (search_catalog only when you're unsure). Every price, deal, aisle and stock fact comes from a \
tool result in this conversation (set_plan, get_cart, get_deals, search_catalog).
- Before you call a tool, say a few words that state no facts, like "Pasta night, nice. One sec.", so the shopper \
hears you right away.
- Amounts count packages as the store sells them (the sizes are in the product list): "three avocados" is one \
5-count bag, and say so ("one bag of five avocados"). For a meal, size it from the people and the package sizes \
(about a quarter pound of meat per person; one 20-count pack of tortillas feeds about six). Otherwise one. Say \
amounts back when they're more than one ("two pounds of ground beef"). "Make it three" or "just one" changes the amount with \
add_to_plan; "take the salsa off" uses remove_from_plan. If a tool result has notes (like "Only 2 Parmesan in stock"), \
tell the shopper.
- The mic hears the whole store. If what you heard clearly isn't meant for you (people talking to each other, \
background chatter, half a sentence), reply with exactly <quiet> and nothing else. When unsure, answer briefly.
- If something isn't in the store, say so plainly ("I don't see cilantro here").
- Don't plan products that are out of stock; offer the closest in-stock alternative instead.
- For a meal, plan the basics (for a pasta dinner: the pasta, the sauce, bread). Leave extras like cheese, sides and \
drinks off unless they ask: the cart offers those with deal cards, and it never offers a deal on something already on \
the list.
- When the cameras weren't sure about an item and the shopper tells you what it is, use confirm_item.
- If you didn't catch what they said, ask again in a few words instead of guessing."""


QUIET = "<quiet>"                                     # Claude's answer to chatter that wasn't meant for Kart


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
        self.base_system = system
        self.llm = llm
        self.system = system
        self.messages: list[dict[str, Any]] = []

    def remember(self, user_text: str, said: str) -> None:
        """A turn the agent answered itself (a yes/no to a deal), so Claude keeps the thread."""
        self.messages.append({"role": "user", "content": user_text})
        self.messages.append({"role": "assistant", "content": [{"type": "text", "text": said}]})

    def set_catalog(self, products: list[dict[str, Any]]) -> None:
        """Product ids and names only (no prices, deals or stock: those change), so a plan needs no search round."""
        lines = [f"- {p['id']}: {p.get('short_name') or p['name']}, {p['name']} ({p.get('category') or 'other'})"
                 for p in products]
        self.system = self.base_system + "\n\nStore products (id: what you call it, the package as sold (kind)):\n" + "\n".join(lines)

    async def respond(self, user_text: str, ctx: dict[str, Any]) -> AsyncIterator[str]:
        self.messages.append({"role": "user", "content": user_text})
        last_said = ""                                   # across tool rounds, so "One sec." and the answer don't run together
        for _ in range(self.MAX_TOOL_ROUNDS):
            content: list[Any] = []
            stop_reason = "end_turn"
            streamed: list[str] = []
            held: list[str] = []                         # text that might still turn out to be <quiet>
            async for item in self.llm.stream(system=self.system, messages=self.messages, tools=TOOLS):
                if item[0] == "text" and not streamed and QUIET.startswith(("".join(held) + item[1]).strip()):
                    held.append(item[1])                 # don't speak it yet
                    continue
                if item[0] == "text" and held:
                    item = ("text", "".join(held) + item[1])
                    held = []
                if item[0] == "text":
                    text = item[1]
                    if not streamed and last_said and not last_said[-1].isspace() and text[:1] and not text[0].isspace():
                        text = " " + text
                    streamed.append(item[1])
                    last_said = text or last_said
                    yield text
                elif item[0] == "final":
                    content, stop_reason = item[1], item[2]
            if "".join(held).strip() == QUIET:            # side chatter: say nothing, and keep the turn in history
                self.messages.append({"role": "assistant", "content": [{"type": "text", "text": QUIET}]})
                return
            if held:                                     # a short reply that only looked like the start of <quiet>
                streamed.extend(held)
                yield "".join(held)
            if not content:                              # a refusal or an empty turn: never store an empty message
                said = "".join(streamed).strip()
                if not said:
                    said = "Sorry, say that again?"
                    yield said
                self.messages.append({"role": "assistant", "content": [{"type": "text", "text": said}]})
                return
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
