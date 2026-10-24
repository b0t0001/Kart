"""Fixed lines Kart says on its own when the cart changes. Deterministic on purpose: fast, and never invents a price."""

from __future__ import annotations

from typing import Any


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
