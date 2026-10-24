"""Fixed lines Kart says on its own when the cart changes. Deterministic on purpose: fast, and never invents a price."""

from __future__ import annotations

import re
from typing import Any

_YES_FIRST = {"yes", "yeah", "yep", "yup", "sure", "ok", "okay", "absolutely", "definitely"}
_NO_FIRST = {"no", "nope", "nah"}
_YES = {"please", "yes please", "sounds good", "add it", "do it", "why not", "go for it", "i'll take it", "let's do it"}
_NO = {"no thanks", "no thank you", "not today", "not now", "skip it", "pass", "i'm good", "im good", "i'm okay"}
_FILLERS = {"uh", "uhh", "um", "umm", "oh", "ah", "hmm", "well", "so", "like", "hey", "kart"}
_MORE_THAN_AN_ANSWER = {"but", "how", "what", "which", "where", "why", "when", "if", "and", "also"}


def _short(catalog: list[dict[str, Any]], product_id: str | None) -> str:
    for product in catalog:
        if product["id"] == product_id:
            return product.get("short_name") or product["name"]
    return "that"


def proactive_line(event: dict[str, Any], catalog: list[dict[str, Any]], plan: list[dict[str, Any]],
                   items: list[dict[str, Any]] | None = None, meal: str | None = None, nudges: bool = False) -> str | None:
    """What to say for an iPad custom event, or None to stay quiet."""
    kind = event.get("type")
    product_id = event.get("product_id")
    if kind == "suggestion":
        return event.get("text") or None
    if kind == "nudge":
        return _nudge_line(event, catalog, meal)
    if kind == "deal_changed":
        return f"Heads up, {_short(catalog, product_id)} just went {event.get('label', 'on sale')}."
    if kind != "cart_changed":
        return None
    change = event.get("change")
    if change == "added":
        line = next((line for line in plan if line.get("product_id") == product_id), None)
        if line is None:
            return None
        want = line.get("qty") or 1
        have = sum(i.get("qty", 1) for i in (items or []) if i.get("product_id") == product_id)
        if nudges and have > want:                      # beta: "Keep the extra?" says it; "Got the X" first is noise
            return None
        if 0 < have < want:
            left = want - have
            return f"Got one {_short(catalog, product_id)}, {'one more' if left == 1 else f'{left} more'} to go."
        return f"Got the {_short(catalog, product_id)}."
    if change == "removed":
        return f"Took the {_short(catalog, product_id)} off your bill."
    if change == "price_dropped" and event.get("to_price"):
        return f"Good news, {_short(catalog, product_id)} just dropped to ${float(event['to_price']):.2f}."
    return None


_NUMBER_WORDS = ["zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten"]


def _words(n: int) -> str:
    return _NUMBER_WORDS[n] if 0 <= n < len(_NUMBER_WORDS) else str(n)


def _unit(product_name: str) -> str | None:
    """The package a count means, from the name as sold: "5 ct bag" -> bag, "20 ct" -> pack, "1 lb" -> pound."""
    name = product_name.lower()
    for word in ("bag", "wedge", "jar", "box", "bunch", "kit"):
        if re.search(rf"\b{word}\b", name):
            return word
    if re.search(r"\b\d+\s*ct\b", name):
        return "pack"
    if re.search(r"\b1 lb\b", name):
        return "pound"
    return None


def _amount(n: int, product: dict[str, Any]) -> str:
    name = (product.get("short_name") or product["name"]).lower()
    unit = _unit(product["name"])
    if unit is None:
        return f"{_words(n)} {name}"
    plural = unit + ("es" if unit.endswith(("x", "ch")) else "s")
    return f"{_words(n)} {unit if n == 1 else plural} of {name}"


def _nudge_line(event: dict[str, Any], catalog: list[dict[str, Any]], meal: str | None) -> str | None:
    """The backend's nudge text uses digits and short names ("1 Tortillas"). For speech: counts in words, in the
    package as sold ("one pack of tortillas"), tied to the trip's meal when Kart knows it. Falls back to the text when
    the product or counts aren't known."""
    product = next((p for p in catalog if p["id"] == event.get("product_id")), None)
    have, need = event.get("have"), event.get("need")
    if product is None or not isinstance(have, int) or not isinstance(need, int):
        return event.get("text") or None
    if event.get("kind") == "over":
        return f"That's {_amount(have, product)} in the cart, and {meal or 'your list'} needs {_words(need)}. Keep the extra?"
    short = need - have
    where = (f" They're in {product['aisle']}." if short > 1 else f" It's in {product['aisle']}.") if product.get("aisle") else ""
    return f"Before you go: you're {_amount(short, product)} short{f' for {meal}' if meal else ''}.{where}"


def only_filler(text: str) -> bool:
    """"Um." / "Hmm": nothing to answer."""
    return all(word in _FILLERS for word in re.sub(r"[^a-z' ]", " ", text.lower()).split())


def yes_or_no(text: str) -> str | None:
    """A plain spoken answer to Kart's deal question ("Uh, yeah, sure." / "No thanks."), or None when it's more than
    that (a question, a "but", a new request), which Claude should hear."""
    if "?" in text:
        return None
    words = re.sub(r"[^a-z' ]", " ", text.lower()).split()
    while words and words[0] in _FILLERS:
        words = words[1:]
    if not words or len(words) > 8 or _MORE_THAN_AN_ANSWER & set(words):
        return None
    phrase = " ".join(words)
    if phrase in _NO or words[0] in _NO_FIRST:
        return "no"
    if phrase in _YES or words[0] in _YES_FIRST:
        return "yes"
    return None


def accepted_line(catalog: list[dict[str, Any]], product_id: str | None) -> str:
    return f"Added {_short(catalog, product_id)} to your list."


DECLINED_LINE = "No problem."
KEEP_LINE = "Okay, keeping it."
NUDGE_OK_LINE = "Got it."

_KEEP = {"keep it", "keep", "keep them", "keep both", "keeping it", "i'll keep it", "i'll keep them", "yes keep it",
         "yeah keep it", "i want it", "i want them"}
_NUDGE_OK = {"ok", "okay", "got it", "gotcha", "i'll put it back", "put it back", "putting it back", "no",
             "nope", "nah", "fine", "right", "my bad", "oops", "skip it", "skip", "skip that", "never mind", "it's fine"}
_FETCH = ("go get it", "i'll get it", "i'll go get it", "i'll grab it", "let me get it", "let me grab it", "go back",
          "i'll go back", "get it")


def nudge_answer(text: str) -> str | None:
    """A plain spoken answer to a quantity nudge: 'keep', 'ok' (dismiss_nudge) or 'fetch' (short: go back for it),
    else None for Claude."""
    if "?" in text:
        return None
    words = re.sub(r"[^a-z' ]", " ", text.lower()).split()
    while words and words[0] in _FILLERS:
        words = words[1:]
    phrase = " ".join(words)
    if not words or len(words) > 6:
        return None
    if phrase in _KEEP or "keep" in words:
        return "keep"
    if phrase in _FETCH or phrase.startswith(("i'll go get", "i'll grab", "i'll get", "let me get", "let me grab")):
        return "fetch"
    if phrase in _NUDGE_OK or phrase.startswith(("okay", "ok ", "got it", "i'll put", "put it back")):
        return "ok"
    return None
