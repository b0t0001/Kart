"""In-memory stand-ins for the Supabase backend and Claude, so the agent runs with no keys."""

from __future__ import annotations

import copy
from dataclasses import dataclass, field
from typing import Any, AsyncIterator

CATALOG = [
    {"id": "barilla-spaghetti", "name": "Barilla Spaghetti, 1 lb", "short_name": "Spaghetti", "price": 1.99,
     "sale_price": 1.99, "deal_label": None, "aisle": "Aisle 6", "section": "A6", "in_stock": True,
     "stock": 30, "category": "pasta", "tags": ["pasta", "italian", "staple"]},
    {"id": "rao-marinara", "name": "Rao's Homemade Marinara Sauce, 24 oz", "short_name": "Rao's Sauce", "price": 8.49,
     "sale_price": 8.49, "deal_label": None, "aisle": "Aisle 6", "section": "A6", "in_stock": True,
     "stock": 20, "category": "sauce", "tags": ["pasta", "italian"]},
    {"id": "kirkland-parmesan", "name": "Kirkland Signature Parmigiano Reggiano, 1.5 lb wedge", "short_name": "Parmesan",
     "price": 12.99, "sale_price": 9.99, "deal_label": "$3 off", "aisle": "Aisle 4", "section": "A4", "in_stock": True,
     "stock": 2, "category": "cheese", "tags": ["pasta", "italian"]},
    {"id": "bananas", "name": "Bananas, bunch (about 2.5 lb)", "short_name": "Bananas", "price": 1.49, "sale_price": 1.49,
     "deal_label": None, "aisle": "Aisle 1", "section": "A1", "in_stock": False, "stock": 0, "category": "produce", "tags": ["fruit"]},
    {"id": "tostitos-salsa", "name": "Salsa, 16 oz jar", "short_name": "Salsa", "price": 3.49, "sale_price": 3.49,
     "deal_label": None, "aisle": "Aisle 5", "section": "A5", "in_stock": True, "stock": 35, "category": "salsa",
     "tags": ["tacos", "nachos", "mexican", "snack"]},
    {"id": "queso", "name": "Salsa con Queso Dip, 15 oz jar", "short_name": "Queso", "price": 3.99, "sale_price": 3.99,
     "deal_label": None, "aisle": "Aisle 5", "section": "A5", "in_stock": True, "stock": 20, "category": "dip",
     "tags": ["nachos", "mexican", "snack", "party"]},
    {"id": "daisy-sour-cream", "name": "Sour Cream, 16 oz", "short_name": "Sour Cream", "price": 2.99, "sale_price": 2.99,
     "deal_label": None, "aisle": "Aisle 8", "section": "A8", "in_stock": True, "stock": 30, "category": "dairy",
     "tags": ["tacos", "nachos", "mexican"]},
]

NEARBY = [{"name": "Berkeley Bowl", "distance": 1.5, "kind": "grocery", "good_for": ["produce", "fresh herbs"]},
          {"name": "Walgreens", "distance": 0.4, "kind": "pharmacy", "good_for": ["household", "snacks"]}]


DEALS = [{"id": "d-parm-3off", "product_id": "kirkland-parmesan", "label": "$3 off",
          "pairs_with": ["barilla-spaghetti", "rao-marinara"], "ends_at": None}]


@dataclass
class FakeBackend:
    cart: dict[str, Any] = field(default_factory=lambda: {
        "cart_id": "7", "trip_id": "trip-1", "status": "shopping", "items": [], "plan": [], "total": 0, "savings": 0,
        "next_step": None, "suggestion": None})
    unresolved: list[dict[str, Any]] = field(default_factory=list)
    deals: list[dict[str, Any]] = field(default_factory=lambda: copy.deepcopy(DEALS))
    transcript: list[tuple[str, str]] = field(default_factory=list)
    calls: list[tuple[str, dict[str, Any]]] = field(default_factory=list)
    catalog: list[dict[str, Any]] = field(default_factory=lambda: copy.deepcopy(CATALOG))
    nearby: list[dict[str, Any]] | None = field(default_factory=lambda: copy.deepcopy(NEARBY))   # None: the read fails

    async def get_cart(self, cart_id: str) -> dict[str, Any]:
        return copy.deepcopy(self.cart)

    async def get_catalog(self) -> list[dict[str, Any]]:
        return copy.deepcopy(self.catalog)

    async def get_nearby_stores(self) -> list[dict[str, Any]]:
        if self.nearby is None:
            raise RuntimeError("store_info.nearby is not there yet")
        return copy.deepcopy(self.nearby)

    async def get_live_deals(self) -> list[dict[str, Any]]:
        return copy.deepcopy(self.deals)

    async def unresolved_events(self, cart_id: str, trip_id: str) -> list[dict[str, Any]]:
        return copy.deepcopy(self.unresolved)

    async def rpc(self, name: str, **params: Any) -> Any:
        self.calls.append((name, params))
        if name == "set_plan":
            self.cart["plan"] = [{"product_id": p["product_id"], "reason": p["reason"], "qty": p.get("qty", 1),
                                  "done": False, **({"basis": p["basis"]} if p.get("basis") else {})} for p in params["p_plan"]]
            self.cart["next_step"] = "Aisle 6 → Spaghetti"
        if name == "set_cart_status":
            self.cart["status"] = params["p_status"]
        if name == "dismiss_suggestion":
            self.cart["suggestion"] = None
        if name == "append_transcript":
            self.transcript.append((params["p_role"], params["p_text"]))
        if name == "apply_cart_event" and params.get("p_resolves_event_id"):
            self.unresolved = [e for e in self.unresolved if e["event_id"] != params["p_resolves_event_id"]]
        return copy.deepcopy(self.cart)


@dataclass
class ToolUse:
    id: str
    name: str
    input: dict[str, Any]
    type: str = "tool_use"


@dataclass
class Text:
    text: str
    type: str = "text"


@dataclass
class Turn:
    """One scripted model turn: text chunks to stream, then optional tool calls."""
    chunks: list[str] = field(default_factory=list)
    tools: list[ToolUse] = field(default_factory=list)


class FakeLLM:
    """Plays scripted turns and records what it was sent."""

    def __init__(self, turns: list[Turn]):
        self.turns = list(turns)
        self.requests: list[dict[str, Any]] = []

    async def stream(self, *, system: str, messages: list[dict[str, Any]], tools: list[dict[str, Any]]) -> AsyncIterator[Any]:
        self.requests.append({"system": system, "messages": copy.deepcopy(messages), "tools": tools})
        turn = self.turns.pop(0)
        for chunk in turn.chunks:
            yield ("text", chunk)
        content = ([Text("".join(turn.chunks))] if turn.chunks else []) + turn.tools
        yield ("final", content, "tool_use" if turn.tools else "end_turn")
