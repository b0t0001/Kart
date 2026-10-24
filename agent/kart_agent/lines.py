"""Fixed lines Kart says on its own when the cart changes. Deterministic on purpose: fast, and never invents a price."""

from __future__ import annotations

import re
from typing import Any

_YES_FIRST = {"yes", "yeah", "yep", "yup", "sure", "ok", "okay", "absolutely", "definitely"}
_NO_FIRST = {"no", "nope", "nah"}
_YES = {"please", "yes please", "sounds good", "add it", "do it", "why not", "go for it", "i'll take it", "let's do it"}
_NO = {"no thanks", "no thank you", "not today", "not now", "skip it", "pass", "i'm good", "im good", "i'm okay"}


def _short(catalog: list[dict[str, Any]], product_id: str | None) -> str:
    for product in catalog:
        if product["id"] == product_id:
            return product.get("short_name") or product["name"]
    return "that"


def proactive_line(event: dict[str, Any], catalog: list[dict[str, Any]], plan: list[dict[str, Any]]) -> str | None:
    """What to say for an iPad custom event, or None to stay quiet."""
    kind = event.get("type")
    product_id = event.get("product_id")
    if kind == "suggestion":
        return event.get("text") or None
    if kind == "deal_changed":
        return f"Heads up, {_short(catalog, product_id)} just went {event.get('label', 'on sale')}."
    if kind != "cart_changed":
        return None
    change = event.get("change")
    if change == "added":
        planned = any(line.get("product_id") == product_id for line in plan)
        return f"Got the {_short(catalog, product_id)}." if planned else None
    if change == "removed":
        return f"Took the {_short(catalog, product_id)} off your bill."
    if change == "price_dropped" and event.get("to_price"):
        return f"Good news, {_short(catalog, product_id)} just dropped to ${float(event['to_price']):.2f}."
    return None


def yes_or_no(text: str) -> str | None:
    """A short spoken answer to Kart's deal question ("Yeah, sure." / "No thanks."), or None for anything longer."""
    words = re.sub(r"[^a-z' ]", " ", text.lower()).split()
    if not words or len(words) > 4:
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
