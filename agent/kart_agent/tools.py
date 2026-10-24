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
    _tool("set_budget", "The shopper gave a budget for the trip ('keep it under $30'). Returns the budget, what the "
          "trip will cost (the bill so far plus the rest of the list), and whether it fits.",
          {"amount": {"type": "number", "description": "dollars, e.g. 30"}}, ["amount"]),
    _tool("note_diet", "The shopper's diet or allergy for this trip ('no dairy', 'vegetarian'). Pass the store kinds to "
          "avoid, as the product list names them (cheese, dairy, meat), and any product whose name shows it (queso). "
          "The cart then offers no deals on them.",
          {"diet": {"type": "string"}, "avoid_kinds": {"type": "array", "items": {"type": "string"}},
           "avoid_products": {"type": "array", "items": {"type": "string"}}}, ["diet"]),
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


def _package(qty: int, product: dict[str, Any]) -> str:
    """ "one bag of five avocados" when the package has a count in it, else the amount ("two boxes of spaghetti")."""
    count, unit = re.search(r"\b(\d+)\s*ct\b", product["name"].lower()), _unit_of(product)
    if count and unit:
        units = unit if qty == 1 else unit + ("es" if unit.endswith(("x", "ch")) else "s")
        return f"{_words(qty)} {units} of {_words(int(count.group(1)))} {_name(product)}"
    return _amount(qty, product)


def _added(qty: int, product: dict[str, Any]) -> str:
    """What was added, as said: "sour cream", "one bag of five avocados", "two boxes of spaghetti"."""
    counted = _unit_of(product) is not None
    if qty == 1:
        return _package(1, product) if re.search(r"\b\d+\s*ct\b", product["name"].lower()) else _name(product)
    return _package(qty, product) if counted else f"{_name(product)}, {_words(qty)} of them"


def _readback(kind: str, product: dict[str, Any], qty: int, old: dict[str, Any] | None, in_cart: int) -> str:
    """The short line Kart says after a list edit, from the live catalog."""
    where = f", {product['aisle']}" if product.get("aisle") else ""
    counted = _unit_of(product) is not None                 # "two boxes of spaghetti"; else "sour cream, two"
    if kind == "added":
        return f"Added {_added(qty, product)}{where}."
    if kind == "swapped" and old is not None:
        return f"Swapped {_name(old)} for {_name(product)}{where}."
    if kind == "amount":
        return f"{_cap(_amount(qty, product))} now." if counted else f"{_cap(_name(product))}, {_words(qty)} now."
    if kind == "already":
        return f"{_cap(_name(product))}'s already on your list."
    if kind == "removed":
        return f"Took {_name(product)} off your list." + (" It's still in your cart." if in_cart else "")
    return f"{_cap(_name(product))} wasn't on your list."


def _capped(qty: Any, product: dict[str, Any]) -> tuple[int, str | None]:
    """Never plan more than the shelf has, and say so."""
    qty = qty if isinstance(qty, int) and not isinstance(qty, bool) and qty > 0 else 1
    stock = product.get("stock")
    if isinstance(stock, int) and 0 < stock < qty:
        return stock, f"Only {stock} {product.get('short_name') or product['name']} in stock: planned {stock}, not {qty}."
    return qty, None


def _dollars(amount: float) -> str:
    return f"${amount:g}" if float(amount).is_integer() else f"${amount:.2f}"


def _projected(cart: dict[str, Any]) -> float:
    """What the trip will cost: the bill so far plus the rest of the list at today's prices."""
    return round(float(cart.get("total") or 0) + float(cart.get("plan_estimate") or 0), 2)


def _budget_view(cart: dict[str, Any]) -> dict[str, Any]:
    budget, estimate = float(cart["budget"]), _projected(cart)
    view: dict[str, Any] = {"budget": cart["budget"], "estimate": estimate, "fits": estimate <= budget}
    view.update({"left": round(budget - estimate, 2)} if estimate <= budget else {"over_by": round(estimate - budget, 2)})
    return view


def _budget_note(before: dict[str, Any], after: dict[str, Any]) -> str:
    """ " That puts you at $15.95, over your $10." when this edit is the one that goes over."""
    budget = after.get("budget")
    if budget is None or _projected(after) <= float(budget) or _projected(before) > float(budget):
        return ""
    return f" That puts you at ${_projected(after):.2f}, over your {_dollars(float(budget))}."


async def _edit_plan(name: str, args: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
    """One voice edit through the backend's atomic add_to_plan / remove_from_plan, read back from the live catalog."""
    backend, cart_id = ctx["backend"], ctx["cart_id"]
    products = await backend.get_catalog()
    catalog = {p["id"]: p for p in products}
    cart = await backend.get_cart(cart_id)
    plan = cart.get("plan", [])
    before = _plan_lines(plan)                               # for undo
    product_id = _str(args, "product_id")
    product = catalog.get(product_id)
    current = next((line for line in plan if line.get("product_id") == product_id), None)
    had = (current.get("qty") or 1) if current else 0
    in_cart = sum(i.get("qty", 1) for i in cart.get("items", []) if i.get("product_id") == product_id)
    if product is None:
        return {"planned": [], "not_in_store": [product_id], "out_of_stock": [], "next_step": cart.get("next_step")}
    if name == "add_to_plan" and _sold_out(product):         # say so, offer what's in stock
        return {"planned": [], "not_in_store": [], "out_of_stock": [product_id], "next_step": cart.get("next_step"),
                "readback": f"Sorry, {_name(product)} is sold out today.",
                "substitutes": _substitutes(product, products, {line.get("product_id") for line in plan})}
    qty, change = args.get("qty"), args.get("change_by")
    qty = qty if isinstance(qty, int) and not isinstance(qty, bool) and qty > 0 else None
    change = change if isinstance(change, int) and not isinstance(change, bool) and change else None
    old = catalog.get(args["replaces"]) if name == "add_to_plan" and isinstance(args.get("replaces"), str) else None
    if old is not None and not any(line.get("product_id") == old["id"] for line in plan):
        old = None
    note, target, after = None, had, cart
    if name == "remove_from_plan":
        kind = "removed" if current else "absent"
    elif current is None:
        kind = "swapped" if old else "added"
        target, note = _capped(qty or (change if change and change > 0 else 1), product)
    elif change and had + change <= 0:                       # "one less" of the last one
        kind = "removed"
    elif change or qty:
        kind = "amount"
        target, note = _capped(had + change if change else qty, product)
    else:
        kind = "already"
    if old is not None:
        after = await backend.rpc("remove_from_plan", p_cart_id=cart_id, p_product_id=old["id"])
    if kind == "removed":
        after = await backend.rpc("remove_from_plan", p_cart_id=cart_id, p_product_id=product_id)
    elif kind in ("added", "swapped", "amount") and target != had:
        basis = args.get("basis") if kind != "amount" and isinstance(args.get("basis"), str) else None
        after = await backend.rpc("add_to_plan", p_cart_id=cart_id, p_product_id=product_id, p_qty=target - had,
                                  p_basis=basis, p_meal=None)
    result: dict[str, Any] = {"planned": [product_id] if kind not in ("removed", "absent") else [], "not_in_store": [],
                              "out_of_stock": [], "next_step": after.get("next_step"),
                              "readback": _readback(kind, product, target, old, in_cart) + _budget_note(cart, after)}
    if kind == "added":                                      # several adds at once are read back as one line
        result["edit"] = {"kind": "added", "what": _added(target, product), "aisle": product.get("aisle"),
                          "budget_note": _budget_note(cart, after)}
    if kind in ("added", "removed", "swapped", "amount") and isinstance(ctx.get("undo"), list):
        ctx["undo"].append({"plan": before, "readback": _undo_line(kind, product, had or 1, old)})
    if isinstance(ctx.get("skipped"), set):                 # taken off the list: no deals on it this trip
        ctx["skipped"] |= ({product_id} if kind == "removed" else set()) | ({old["id"]} if old else set())
        ctx["skipped"] -= {product_id} if kind in ("added", "swapped", "amount") else set()
    return {**result, "notes": [note]} if note else result


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
    from .memory import MEMBER_TOOL_NAMES, member_dispatch   # member memory beta (memory imports this module)
    if name in MEMBER_TOOL_NAMES:
        return await member_dispatch(name, args, ctx)
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
    if name in ("add_to_plan", "remove_from_plan"):
        return await _edit_plan(name, args, ctx)
    if name == "set_plan":
        products = await backend.get_catalog()
        catalog = {p["id"]: p for p in products}
        prior = await backend.get_cart(cart_id)
        before = _plan_lines(prior.get("plan", []))
        items = args.get("items")
        if not isinstance(items, list):
            raise ValueError("'items' must be a list")
        ctx["planned"] = True                                # the agent offers the deals that go with a new list
        if isinstance(args.get("meal"), str) and args["meal"].strip():
            ctx["meal"] = args["meal"].strip()               # Kart names the trip's meal in nudges
        meal = ctx.get("meal")
        planned, missing, sold_out, lines, notes = [], [], [], [], []
        for item in items:
            if not isinstance(item, dict) or not isinstance(item.get("product_id"), str):
                raise ValueError("each item needs a product_id")
            product = catalog.get(item["product_id"])
            if product is None:
                missing.append(item["product_id"])
            elif _sold_out(product):
                sold_out.append(item["product_id"])
            else:
                planned.append(item["product_id"])
                qty, note = _capped(item.get("qty", 1), product)
                notes += [note] if note else []
                basis = item.get("basis")
                lines.append({"product_id": item["product_id"], "reason": str(item.get("reason", "")), "qty": qty,
                              **({"basis": basis} if isinstance(basis, str) and basis else {}),
                              **({"meal": meal} if meal else {})})     # each line remembers the meal (for a rejoin)
        cart = await backend.rpc("set_plan", p_cart_id=cart_id, p_plan=lines)
        result: dict[str, Any] = {"planned": planned, "not_in_store": missing, "out_of_stock": sold_out,
                                  "next_step": cart.get("next_step")}
        if sold_out:
            result["substitutes"] = {pid: _substitutes(catalog[pid], products, set(planned)) for pid in sold_out}
        if isinstance(ctx.get("undo"), list):
            ctx["undo"].append({"plan": before, "readback": "Back to your last list."})
        off = [{"product_id": i["product_id"], "short_name": (catalog.get(i["product_id"]) or {}).get("short_name")
                or i.get("name"), "qty": i.get("qty", 1)}
               for i in prior.get("items", []) if i.get("product_id") not in planned]
        if off:                                              # a new list: Kart asks about these ("Keep it?")
            result["in_cart_not_on_list"] = off
        if cart.get("budget") is not None:                   # "keep it under $30": plan within it
            result["budget"] = _budget_view(cart)
        return {**result, "notes": notes} if notes else result
    if name == "set_budget":
        amount = args.get("amount")
        if not isinstance(amount, (int, float)) or isinstance(amount, bool) or amount <= 0:
            raise ValueError("'amount' must be a number of dollars above 0")
        return _budget_view(await backend.rpc("set_budget", p_cart_id=cart_id, p_amount=amount))
    if name == "note_diet":
        diet = _str(args, "diet")
        kinds = sorted({k.strip().lower() for k in args.get("avoid_kinds") or [] if isinstance(k, str) and k.strip()})
        products = sorted({p.strip() for p in args.get("avoid_products") or [] if isinstance(p, str) and p.strip()})
        kept = ctx.get("diet")
        if isinstance(kept, dict):                           # the agent keeps it for the trip
            kept.update({"diet": diet, "kinds": set(kept.get("kinds") or set()) | set(kinds),
                         "products": set(kept.get("products") or set()) | set(products)})
        return {"diet": diet, "avoiding_kinds": kinds, "avoiding_products": products}
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
