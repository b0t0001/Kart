"""Claude's tools. Every fact Kart states comes from here (the live backend), never from the model."""

from __future__ import annotations

import json
import re
import uuid
from typing import Any

def _tool(name: str, description: str, properties: dict[str, Any] | None = None, required: list[str] | None = None) -> dict[str, Any]:
    return {
        "name": name,
        "description": description,
        "eager_input_streaming": True,
        "input_schema": {"type": "object", "properties": properties or {}, "required": required or []},
    }


_PLAN_ITEM = {
    "type": "object",
    "properties": {
        "product_id": {"type": "string"},
        "reason": {"type": "string", "description": "why it's on the list, e.g. 'pasta dinner'"},
        "qty": {"type": "integer", "minimum": 1},
        "basis": {"type": "string", "description": "the math behind the amount, e.g. '8 people x 1/4 lb = 2 lb of beef'"},
    },
    "required": ["product_id", "reason"],
}

TOOLS: list[dict[str, Any]] = [
    _tool("search_catalog", "Find store products by words (name, kind, meal). Returns ids, live prices, deals, aisle, stock.",
          {"query": {"type": "string"}}, ["query"]),
    _tool("get_cart", "The shopper's cart right now: items, total, savings, list progress, next stop, open deal suggestion."),
    _tool("set_plan", "Replace the shopping list with these products. The store orders it by walking route.",
          {"items": {"type": "array", "items": _PLAN_ITEM},
           "meal": {"type": "string", "description": "what the trip is for, in a few words, e.g. 'taco night for 4'"}},
          ["items"]),
    _tool("add_to_plan", "Add one product to the shopping list, keeping the rest; with qty, sets how many (also for a "
          "product already on the list: 'make it three').",
          {"product_id": {"type": "string"}, "reason": {"type": "string"}, "qty": {"type": "integer", "minimum": 1},
           "basis": {"type": "string"}}, ["product_id", "reason"]),
    _tool("remove_from_plan", "Take one product off the shopping list.", {"product_id": {"type": "string"}}, ["product_id"]),
    _tool("get_deals", "Every live deal in the store, with product, label and aisle."),
    _tool("set_location", "The shopper said where they are, e.g. 'aisle 5'.", {"section": {"type": "string"}}, ["section"]),
    _tool("dismiss_suggestion", "The shopper said no to the current deal suggestion."),
    _tool("dismiss_nudge", "Answer Kart's quantity nudge: 'keep' (keep the extra; the list goes up) or 'ok' (got it).",
          {"action": {"type": "string", "enum": ["keep", "ok"]}}, ["action"]),
    _tool("confirm_item", "The shopper said what the cameras' unrecognized item is.", {"product_id": {"type": "string"}}, ["product_id"]),
    _tool("start_checkout", "The shopper is done; show the bill."),
]


def _tokens(text: str) -> set[str]:
    return {t for t in re.split(r"[^a-z0-9]+", text.lower().replace("'", "")) if t}


def _product_view(p: dict[str, Any]) -> dict[str, Any]:
    keys = ("id", "short_name", "name", "price", "sale_price", "deal_label", "aisle", "in_stock", "stock")
    return {k: p.get(k) for k in keys}


async def run_tool(name: str, args: Any, ctx: dict[str, Any]) -> str:
    """Runs one tool and returns its JSON result. Bad input or a failed call becomes {"error": …}, never an exception."""
    try:
        return json.dumps(await _dispatch(name, args if isinstance(args, dict) else {}, ctx))
    except (ValueError, TypeError, KeyError) as error:
        return json.dumps({"error": str(error)})
    except Exception as error:  # a backend failure must not end the call
        return json.dumps({"error": f"{type(error).__name__}: {error}"})


def _str(args: dict[str, Any], key: str) -> str:
    value = args.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"'{key}' must be a non-empty string")
    return value


async def _dispatch(name: str, args: dict[str, Any], ctx: dict[str, Any]) -> Any:
    backend, cart_id = ctx["backend"], ctx["cart_id"]
    if name == "search_catalog":
        query = _tokens(_str(args, "query"))
        scored = []
        for index, p in enumerate(await backend.get_catalog()):
            words = _tokens(" ".join([p["name"], p.get("short_name") or "", p.get("category") or "", *p.get("tags", [])]))
            hits = len(query & words)
            if hits:
                scored.append((-hits, index, p))
        return [_product_view(p) for _, _, p in sorted(scored)[:8]]
    if name == "get_cart":
        cart = await backend.get_cart(cart_id)
        return {
            "items": [{"short_name": i.get("short_name") or i["name"], "qty": i["qty"], "price": i["price"],
                       "deal_label": i.get("deal_label")} for i in cart.get("items", [])],
            "total": cart.get("total"), "savings": cart.get("savings"), "status": cart.get("status"),
            "plan": [{"product_id": p["product_id"], "name": p.get("name"), "qty": p.get("qty", 1), "done": p.get("done"),
                      "aisle": p.get("aisle")}
                     for p in cart.get("plan", [])],
            "next_step": cart.get("next_step"),
            "suggestion": (cart.get("suggestion") or {}).get("text"),
            "unrecognized_items": len(await backend.unresolved_events(cart_id, ctx.get("trip_id") or cart.get("trip_id"))),
        }
    if name in ("set_plan", "add_to_plan", "remove_from_plan"):
        catalog = {p["id"]: p for p in await backend.get_catalog()}
        if name in ("add_to_plan", "remove_from_plan"):
            cart = await backend.get_cart(cart_id)
            items = [{"product_id": p["product_id"], "reason": p.get("reason", ""), "qty": p.get("qty", 1),
                      "basis": p.get("basis")} for p in cart.get("plan", [])]
            product_id = _str(args, "product_id")
            if name == "remove_from_plan":
                items = [i for i in items if i["product_id"] != product_id]
            elif all(i["product_id"] != product_id for i in items):
                items.append({"product_id": product_id, "reason": _str(args, "reason"), "qty": args.get("qty", 1),
                              "basis": args.get("basis")})
            elif isinstance(args.get("qty"), int):
                items = [{**i, "qty": args["qty"], "basis": args.get("basis") or i.get("basis")}
                         if i["product_id"] == product_id else i for i in items]
        else:
            items = args.get("items")
            if not isinstance(items, list):
                raise ValueError("'items' must be a list")
            if isinstance(args.get("meal"), str) and args["meal"].strip():
                ctx["meal"] = args["meal"].strip()           # Kart names the trip's meal in nudges
        planned, missing, sold_out, lines, notes = [], [], [], [], []
        for item in items:
            if not isinstance(item, dict) or not isinstance(item.get("product_id"), str):
                raise ValueError("each item needs a product_id")
            product = catalog.get(item["product_id"])
            if product is None:
                missing.append(item["product_id"])
            elif product.get("in_stock") is False:
                sold_out.append(item["product_id"])
            else:
                planned.append(item["product_id"])
                qty = item.get("qty", 1)
                qty = qty if isinstance(qty, int) and qty > 0 else 1
                stock = product.get("stock")
                if isinstance(stock, int) and 0 < stock < qty:       # never plan more than the shelf has, and say so
                    notes.append(f"Only {stock} {product.get('short_name') or product['name']} in stock: planned {stock}, not {qty}.")
                    qty = stock
                basis = item.get("basis")
                lines.append({"product_id": item["product_id"], "reason": str(item.get("reason", "")), "qty": qty,
                              **({"basis": basis} if isinstance(basis, str) and basis else {})})
        cart = await backend.rpc("set_plan", p_cart_id=cart_id, p_plan=lines)
        result = {"planned": planned, "not_in_store": missing, "out_of_stock": sold_out, "next_step": cart.get("next_step")}
        return {**result, "notes": notes} if notes else result
    if name == "get_deals":
        return [_product_view(p) for p in await backend.get_catalog() if p.get("deal_label")]
    if name == "set_location":
        cart = await backend.rpc("set_location", p_cart_id=cart_id, p_section=_str(args, "section"))
        return {"next_step": cart.get("next_step")}
    if name == "dismiss_suggestion":
        await backend.rpc("dismiss_suggestion", p_cart_id=cart_id)
        return {"ok": True}
    if name == "dismiss_nudge":
        action = _str(args, "action")
        if action not in ("keep", "ok"):
            raise ValueError("action must be 'keep' or 'ok'")
        await backend.rpc("dismiss_nudge", p_cart_id=cart_id, p_action=action)
        return {"ok": True}
    if name == "confirm_item":
        product_id = _str(args, "product_id")
        pending = await backend.unresolved_events(cart_id, ctx.get("trip_id"))
        if not pending:
            return {"error": "nothing is waiting to be confirmed"}
        await backend.rpc("apply_cart_event", p_cart_id=cart_id, p_type="added", p_product_id=product_id, p_confidence=1,
                          p_source="manual", p_label=None, p_camera=None, p_snapshot_url=None,
                          p_event_id=str(uuid.uuid4()), p_method="manual", p_resolves_event_id=pending[0]["event_id"])
        return {"confirmed": product_id}
    if name == "start_checkout":
        await backend.rpc("set_cart_status", p_cart_id=cart_id, p_status="checkout")
        return {"ok": True}
    raise ValueError(f"unknown tool {name}")
