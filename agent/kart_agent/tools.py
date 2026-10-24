"""Claude's tools. Every fact Kart states comes from here (the live backend), never from the model."""

from __future__ import annotations

import json
import re
import uuid
from typing import Any

from .lines import _amount, _unit_of, _words


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
          "product already on the list: 'make it three'). Returns `readback`, the short line to say back.",
          {"product_id": {"type": "string"}, "reason": {"type": "string"}, "qty": {"type": "integer", "minimum": 1},
           "change_by": {"type": "integer", "description": "'another one' = 1, 'one less' = -1: changes the amount by this"},
           "replaces": {"type": "string", "description": "'swap the salsa for queso': the salsa's product_id, taken off "
                                                         "in the same update"},
           "basis": {"type": "string"}}, ["product_id", "reason"]),
    _tool("remove_from_plan", "Take one product off the shopping list. Returns `readback`.",
          {"product_id": {"type": "string"}}, ["product_id"]),
    _tool("undo_last_edit", "Take back the last change to the shopping list: 'undo', 'never mind', or 'no, I said "
          "salsa' (then add the right one). Returns `readback`."),
    _tool("not_sold_here", "The shopper wants something that isn't in the store's product list. Returns in-stock "
          "products that could stand in (matching `like`) and nearby stores that might have it. Changes nothing.",
          {"item": {"type": "string", "description": "what they asked for, e.g. 'cilantro'"},
           "like": {"type": "string", "description": "words for what could stand in, e.g. 'salsa mexican'"}}, ["item"]),
    _tool("get_deals", "Every live deal in the store, with product, label and aisle."),
    _tool("set_location", "The shopper said where they are, e.g. 'aisle 5'.", {"section": {"type": "string"}}, ["section"]),
    _tool("dismiss_suggestion", "The shopper said no to the current deal suggestion."),
    _tool("dismiss_nudge", "Answer Kart's quantity nudge: 'keep' (keep the extra; the list goes up), 'ok' (got it), "
          "'skip' (skip what's missing) or 'shop' (go back for what's missing, at checkout).",
          {"action": {"type": "string", "enum": ["keep", "ok", "skip", "shop"]}}, ["action"]),
    _tool("confirm_item", "The shopper said what the cameras' unrecognized item is.", {"product_id": {"type": "string"}}, ["product_id"]),
    _tool("start_checkout", "The shopper is done; show the bill."),
]


def _tokens(text: str) -> set[str]:
    return {t for t in re.split(r"[^a-z0-9]+", text.lower().replace("'", "")) if t}


def _product_view(p: dict[str, Any]) -> dict[str, Any]:
    keys = ("id", "short_name", "name", "price", "sale_price", "deal_label", "aisle", "in_stock", "stock")
    return {k: p.get(k) for k in keys}


def _name(p: dict[str, Any]) -> str:
    """How the product sounds mid-sentence: "sour cream"."""
    return (p.get("short_name") or p["name"]).lower()


def _cap(text: str) -> str:
    return text[:1].upper() + text[1:]


def _sold_out(p: dict[str, Any]) -> bool:
    return p.get("in_stock") is False or p.get("stock") == 0


def _substitutes(product: dict[str, Any], catalog: list[dict[str, Any]], listed: set[str] = frozenset()) -> list[dict[str, Any]]:
    """In-stock stand-ins for a sold-out product: the same kind only (one salsa for another), never one already on the
    list; the most shared tags first."""
    tags = set(product.get("tags") or [])
    scored = [(-len(tags & set(p.get("tags") or [])), index, p) for index, p in enumerate(catalog)
              if p["id"] != product["id"] and p["id"] not in listed and not _sold_out(p)
              and p.get("category") == product.get("category")]
    return [_product_view(p) for *_, p in sorted(scored, key=lambda s: s[:2])[:3]]


def _distance(value: Any) -> Any:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return f"about {value:g} {'mile' if value == 1 else 'miles'} away"
    return value


async def _nearby_stores(backend: Any) -> list[dict[str, Any]]:
    """Other stores nearby (store_info.nearby), each one that only *might* have it. Empty if the store has none."""
    try:
        stores = await backend.get_nearby_stores()
    except Exception:
        return []
    return [{"name": s["name"], "distance": _distance(s.get("distance_mi", s.get("distance"))), "kind": s.get("kind"),
             "good_for": s.get("good_for") or [], **({"address": s["address"]} if s.get("address") else {}),
             "might_have_it": True}
            for s in stores if isinstance(s, dict) and isinstance(s.get("name"), str)]


def _undo_line(kind: str, product: dict[str, Any], before: int, old: dict[str, Any] | None) -> str:
    """What Kart says when the edit is taken back."""
    if kind == "added":
        return f"Took {_name(product)} back off your list."
    if kind == "removed":
        return f"Put {_name(product)} back on your list."
    if kind == "swapped" and old is not None:
        return f"Swapped back to {_name(old)}."
    if _unit_of(product) is not None:
        return f"Back to {_amount(before, product)}."
    return f"{_cap(_name(product))} back to {_words(before)}."


def _plan_lines(plan: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """A list as set_plan takes it back."""
    keys = ("product_id", "reason", "qty", "basis")
    return [{k: line[k] for k in keys if line.get(k) is not None} for line in plan]


def _readback(kind: str, product: dict[str, Any], qty: int, old: dict[str, Any] | None, in_cart: int) -> str:
    """The short line Kart says after a list edit, from the live catalog."""
    where = f", {product['aisle']}" if product.get("aisle") else ""
    counted = _unit_of(product) is not None                 # "two boxes of spaghetti"; else "sour cream, two"
    if kind == "added":
        if qty == 1 or counted:
            return f"Added {_name(product) if qty == 1 else _amount(qty, product)}{where}."
        return f"Added {_name(product)}, {_words(qty)} of them{where}."
    if kind == "swapped" and old is not None:
        return f"Swapped {_name(old)} for {_name(product)}{where}."
    if kind == "amount":
        return f"{_cap(_amount(qty, product))} now." if counted else f"{_cap(_name(product))}, {_words(qty)} now."
    if kind == "already":
        return f"{_cap(_name(product))}'s already on your list."
    if kind == "removed":
        return f"Took {_name(product)} off your list." + (" It's still in your cart." if in_cart else "")
    return f"{_cap(_name(product))} wasn't on your list."


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
    if name == "not_sold_here":
        item, products = _str(args, "item"), await backend.get_catalog()
        asked = _tokens(item)
        carried = [p for p in products if asked and asked <= _tokens(f"{p['name']} {p.get('short_name') or ''}")]
        if carried:                                          # it is sold here after all: add it instead
            return {"sold_here": [_product_view(p) for p in carried[:3]]}
        like, scored = _tokens(args.get("like") or ""), []
        for index, p in enumerate(products):
            words = _tokens(" ".join([p["name"], p.get("short_name") or "", p.get("category") or "", *p.get("tags", [])]))
            hits = len(like & words)
            if hits and not _sold_out(p):
                scored.append((-hits, index, p))
        return {"not_sold_here": item, "in_store": [_product_view(p) for *_, p in sorted(scored, key=lambda s: s[:2])[:3]],
                "nearby_stores": await _nearby_stores(backend)}
    if name in ("set_plan", "add_to_plan", "remove_from_plan"):
        products = await backend.get_catalog()
        catalog = {p["id"]: p for p in products}
        edit: tuple[str, str, dict[str, Any] | None, int] | None = None   # (kind, product_id, swapped-out product, in cart)
        if name in ("add_to_plan", "remove_from_plan"):
            cart = await backend.get_cart(cart_id)
            items = [{"product_id": p["product_id"], "reason": p.get("reason", ""), "qty": p.get("qty", 1),
                      "basis": p.get("basis")} for p in cart.get("plan", [])]
            before = _plan_lines(items)                     # for undo
            product_id = _str(args, "product_id")
            product = catalog.get(product_id)
            current = next((i for i in items if i["product_id"] == product_id), None)
            in_cart = sum(i.get("qty", 1) for i in cart.get("items", []) if i.get("product_id") == product_id)
            qty, change = args.get("qty"), args.get("change_by")
            qty = qty if isinstance(qty, int) and qty > 0 else None
            change = change if isinstance(change, int) and not isinstance(change, bool) and change else None
            if name == "add_to_plan" and product is not None and _sold_out(product):   # say so, offer what's in stock
                return {"planned": [], "not_in_store": [], "out_of_stock": [product_id], "next_step": cart.get("next_step"),
                        "readback": f"Sorry, {_name(product)} is sold out today.",
                        "substitutes": _substitutes(product, products, {i["product_id"] for i in items})}
            if name == "remove_from_plan":
                items = [i for i in items if i["product_id"] != product_id]
                edit = ("removed" if current else "absent", product_id, None, in_cart)
            elif current is None:
                old = catalog.get(args["replaces"]) if isinstance(args.get("replaces"), str) else None
                items = [i for i in items if old is None or i["product_id"] != old["id"]]
                items.append({"product_id": product_id, "reason": _str(args, "reason"),
                              "qty": qty or (change if change and change > 0 else 1), "basis": args.get("basis")})
                edit = ("swapped" if old else "added", product_id, old, in_cart)
            elif change and current["qty"] + change <= 0:   # "one less" of the last one
                items = [i for i in items if i["product_id"] != product_id]
                edit = ("removed", product_id, None, in_cart)
            elif change or qty:
                new = current["qty"] + change if change else qty
                items = [{**i, "qty": new, "basis": args.get("basis") or i.get("basis")}
                         if i["product_id"] == product_id else i for i in items]
                edit = ("amount", product_id, None, in_cart)
            else:
                edit = ("already", product_id, None, in_cart)
        else:
            prior = await backend.get_cart(cart_id)
            before = _plan_lines(prior.get("plan", []))
            items = args.get("items")
            if not isinstance(items, list):
                raise ValueError("'items' must be a list")
            ctx["planned"] = True                            # the agent offers the deals that go with a new list
            if isinstance(args.get("meal"), str) and args["meal"].strip():
                ctx["meal"] = args["meal"].strip()           # Kart names the trip's meal in nudges
        planned, missing, sold_out, lines, notes = [], [], [], [], []
        meal = ctx.get("meal") if name == "set_plan" else None   # each meal line remembers the meal (for a rejoin)
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
                lines.append({"product_id": item["product_id"], "reason": meal or str(item.get("reason", "")), "qty": qty,
                              **({"basis": basis} if isinstance(basis, str) and basis else {})})
        cart = await backend.rpc("set_plan", p_cart_id=cart_id, p_plan=lines)
        result: dict[str, Any] = {"planned": planned, "not_in_store": missing, "out_of_stock": sold_out,
                                  "next_step": cart.get("next_step")}
        if sold_out:
            result["substitutes"] = {pid: _substitutes(catalog[pid], products, set(planned)) for pid in sold_out}
        if edit and edit[1] in catalog:
            kind, pid, old, in_cart = edit
            final = next((line["qty"] for line in lines if line["product_id"] == pid), 1)
            result["readback"] = _readback(kind, catalog[pid], final, old, in_cart)
            if kind in ("added", "removed", "swapped", "amount") and isinstance(ctx.get("undo"), list):
                was = next((line["qty"] for line in before if line["product_id"] == pid), 1)
                ctx["undo"].append({"plan": before, "readback": _undo_line(kind, catalog[pid], was, old)})
        elif name == "set_plan":
            if isinstance(ctx.get("undo"), list):
                ctx["undo"].append({"plan": before, "readback": "Back to your last list."})
            off = [{"product_id": i["product_id"], "short_name": (catalog.get(i["product_id"]) or {}).get("short_name")
                    or i.get("name"), "qty": i.get("qty", 1)}
                   for i in prior.get("items", []) if i.get("product_id") not in planned]
            if off:                                          # a new list: Kart asks about these ("Keep it?")
                result["in_cart_not_on_list"] = off
        return {**result, "notes": notes} if notes else result
    if name == "undo_last_edit":
        stack = ctx.get("undo")
        if not stack:
            return {"readback": "There's nothing to undo."}
        last = stack.pop()
        cart = await backend.rpc("set_plan", p_cart_id=cart_id, p_plan=last["plan"])
        return {"readback": last["readback"], "next_step": cart.get("next_step")}
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
        if action not in ("keep", "ok", "skip", "shop"):
            raise ValueError("action must be 'keep', 'ok', 'skip' or 'shop'")
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
