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
tool result in this conversation (set_plan, get_cart, get_deals, search_catalog) or from the "(Right now: ...)" note \
at the start of the shopper's message, which is live from the cart: answer from it when it has what they asked \
(their total, what's in the cart, what's next, a listed item's aisle) without calling a tool.
- Before you call a tool, say a few words that state no facts, like "Pasta night, nice. One sec.", so the shopper \
hears you right away.
- Amounts count packages as the store sells them (the sizes are in the product list): "three avocados" is one \
5-count bag, and say so ("one bag of five avocados"). For a meal, size it from the people and the package sizes \
(about a quarter pound of meat per person; one 20-count pack of tortillas feeds about six). Otherwise one. Say \
amounts back when they're more than one ("two pounds of ground beef"). If a tool result has notes (like "Only 2 \
Parmesan in stock"), tell the shopper. With set_plan, pass meal: what the trip is for in a few words ("taco night for 4"). Give \
every plan line a short basis, the math behind its amount ("8 people x 1/4 lb = 2 lb", \
"16 tacos, 20 per pack = 1 pack").
- Store meal lists: when the shopper asks for one of these, plan exactly this list (scale only for a much bigger \
party), with these bases:
  * Pasta night (for 4; one more of each per 4 more people, so 6 people get 2 of each): barilla-spaghetti x1, \
rao-marinara x1, french-baguette x1 (call it "garlic bread"). Bases: "1 lb serves 4", "one jar for 1 lb of pasta", \
"one loaf for 4". Leave Parmesan off: the cart offers it.
  * Game-night nachos (up to 8 people): tostitos-salsa x1, queso x1, black-beans x1, jalapenos x1, \
daisy-sour-cream x1. Leave the chips off: the cart offers them with a deal. Basis for each: "one tops nachos for 6".
- When you've just made a list, say what's on it and the first stop, and leave deals out: the cart asks about \
deals right after.
- Changing the meal ("actually make it tacos"): plan the new list with set_plan, keeping anything from the old list \
the new meal also uses. If set_plan reports in_cart_not_on_list, ask about it once, briefly ("The spaghetti's already \
in your cart. Keep it?"): yes puts it back on the list (add_to_plan), no gets "Okay, take it out when you can."
- The shopper can add anything the store sells, for any reason ("Leo needs kids' scissors for school" on a pasta \
trip): just add it. Never comment on whether it fits the meal.
- A second meal ("and breakfast for tomorrow") adds its basics to the list with add_to_plan, keeping the first meal.
- The party size changes ("it's 6 people now", "just me tonight"): re-plan the same items with set_plan at the new \
amounts, with new bases, and say what changed ("Two boxes of spaghetti and two jars of marinara now.").
- If "it" or "that" could mean more than one thing ("make it two" right after a list), ask "Two of what?" instead of \
guessing.
- A budget ("keep it under $30"): call set_budget (after set_plan when you're also making the list). If it doesn't \
fit, trim extras or amounts until it does and say so ("That's about $24 of your $30."), or say plainly it can't fit \
and what it would cost. Don't promise to watch the total: the cart says when they get close.
- "Talk slower" or "faster": "I can't change how fast I talk yet, but I'll keep it short." Then keep it short.
- The mic hears the whole store. If what you heard clearly isn't meant for you (people talking to each other, \
background chatter, half a sentence), reply with exactly <quiet> and nothing else. When unsure, answer briefly.
- Editing the list: "add the sour cream" (add_to_plan), "take the salsa off" (remove_from_plan), "make it three" or \
"just one" (add_to_plan with qty), "another one" or "one more box" (change_by 1), "one less" (change_by -1), "swap the \
salsa for queso" (add_to_plan for the queso with replaces = the salsa), "undo", "never mind" or "no, I said salsa" \
(undo_last_edit, then the right edit in the same turn). Always call the tool, even if you think it's \
sold out. Before it, say just one word ("Sure."): the cart reads a plain edit back itself. If you get the result back \
instead, say its readback and nothing more (unless it's sold out, below).
- Sold out: the readback says so. Offer at most one of the result's substitutes, only if it really stands in for the \
same use, with its aisle ("The queso in Aisle 5 is in stock. Want that instead?"). If none does, stop there.
- Not in the store (nothing in the product list below fits): call not_sold_here, then say it plainly ("We don't carry \
cilantro."). Then offer at most one in_store option, only if it's a direct stand-in for the same use (one sauce for \
another; never a raw ingredient for a ready meal); otherwise skip it. Then at most one nearby store whose good_for fits, only as a maybe ("Berkeley Bowl, about 1.5 miles away, \
might have it fresh."). Never say another store has it or what it costs there, and never say what a product \
contains unless its name says so.
- Diets and allergies ("gluten-free", "vegan", "no dairy", "nut allergy"): call note_diet with the kinds to avoid, so \
the cart offers no deals on them, and plan without them. You can't see ingredients. Never say or \
imply a product is safe or fits a diet unless its name says so; say "I can't confirm that's gluten-free. Please check \
the label." (with the diet or allergen they named). You may leave whole kinds off the list (no meat for vegetarian, \
no cheese for no dairy). Never promise what the cart will offer later (its deal cards don't know about diets), and \
don't mention store staff or services you don't know exist.
- Don't plan products that are out of stock; offer the closest in-stock alternative instead.
- For a meal, plan the basics (for a pasta dinner: the pasta, the sauce, bread). Leave extras like cheese, sides and \
drinks off unless they ask: the cart offers those with deal cards, and it never offers a deal on something already on \
the list.
- When the cameras weren't sure about an item and the shopper tells you what it is, use confirm_item.
- "This" or "that" ("how much is this?") means the card on screen if they're asking about it, else the last item \
into the cart; both are given in brackets when known. If it's still unclear, ask which one.
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

    def seed(self, lines: list[tuple[str, str]]) -> None:
        """A call rejoining a trip: the conversation so far, from the captions. A last shopper line nobody answered
        (the call dropped) is left out: Kart asks for it again."""
        messages: list[dict[str, Any]] = []
        for role, text in lines:
            role = "user" if role == "user" else "assistant"
            if not text or (not messages and role == "assistant"):   # the history starts with the shopper
                continue
            if messages and messages[-1]["role"] == role:
                messages[-1]["content"] += " " + text
            else:
                messages.append({"role": role, "content": text})
        if messages and messages[-1]["role"] == "user":
            messages.pop()
        self.messages = messages

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
            readback = _clean_edit_readback(tool_uses, results)
            if readback:                                 # a plain list edit: say it word for word, no second round
                yield readback if last_said[-1:].isspace() or not last_said else " " + readback
                self.messages.append({"role": "assistant", "content": [{"type": "text", "text": readback}]})
                return
        yield "Sorry, give me a second and say that again?"


EDIT_TOOLS = {"add_to_plan", "remove_from_plan", "undo_last_edit"}


def _clean_edit_readback(tool_uses: list[Any], results: list[dict[str, Any]]) -> str | None:
    """The readback(s) when every tool this round was a list edit that went through as asked: nothing sold out, no
    stock notes, no errors. Otherwise None, and Claude gets the results (to offer a substitute, say a note, ...)."""
    if not tool_uses or any(b.name not in EDIT_TOOLS for b in tool_uses):
        return None
    lines = []
    for result in results:
        try:
            out = json.loads(result["content"])
        except (TypeError, ValueError):
            return None
        if not isinstance(out, dict) or not out.get("readback") or out.get("error") or out.get("notes") \
                or out.get("out_of_stock") or out.get("not_in_store"):
            return None
        lines.append(out)
    if len(lines) > 1 and all((out.get("edit") or {}).get("kind") == "added" for out in lines):
        by_aisle: dict[Any, list[str]] = {}
        for out in lines:
            by_aisle.setdefault(out["edit"].get("aisle"), []).append(out["edit"]["what"])
        parts = [f"{_and(names)}, {aisle}" if aisle else _and(names) for aisle, names in by_aisle.items()]
        notes = "".join(out["edit"].get("budget_note") or "" for out in lines)   # " That puts you at $X, over your $Y."
        return "Added " + ", and ".join(parts) + "." + notes   # "Added salsa and queso, Aisle 5, and sour cream, Aisle 8."
    return " ".join(out["readback"] for out in lines)


def _and(names: list[str]) -> str:
    return names[0] if len(names) == 1 else ", ".join(names[:-1]) + " and " + names[-1]
