"""KART merchant agent: the store owner talks to the store instead of editing a backend.

Claude gets a small set of typed tools and never SQL. Read tools run right away.
Write tools never touch the catalog: they validate the request and stage a *pending*
change with a plain-English preview. Only the owner's Confirm click applies it
(merchant_apply in backend/db/05_merchant.sql), every applied change is logged in
merchant_changes, and every one can be undone with one click. That is enforced in code,
not in the prompt: there is no tool that applies a change.
"""

from __future__ import annotations

import json
import os
import re
import sys
import threading
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo

import anthropic
import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
import kartdb  # noqa: E402

MODEL = os.environ.get("MERCHANT_MODEL", "claude-opus-5-5")
# Store-owner chat wants snappy previews; raise MERCHANT_EFFORT if tool choices get sloppy.
EFFORT = os.environ.get("MERCHANT_EFFORT", "low")
STORE_TZ = ZoneInfo(os.environ.get("STORE_TZ", "America/Los_Angeles"))
MAX_TOOL_ROUNDS = 8


class ToolError(Exception):
    """A request the store can't do as asked; the message goes back to Claude."""


# ── Formatting ──

def money(x) -> str:
    d = Decimal(str(x)).quantize(Decimal("0.01"))
    return f"${d:,.2f}"


def money_short(x) -> str:
    d = Decimal(str(x)).quantize(Decimal("0.01"))
    return f"${d:,.0f}" if d == d.to_integral() else f"${d:,.2f}"


def deal_label(kind: str, value) -> str:
    if kind == "amount_off":
        return f"{money_short(value)} off"
    v = Decimal(str(value))
    return f"{v.normalize():f}% off"


def sale_price(price, kind: str, value) -> Decimal:
    price, value = Decimal(str(price)), Decimal(str(value))
    if kind == "amount_off":
        return max(price - value, Decimal("0")).quantize(Decimal("0.01"))
    return (price * (1 - value / 100)).quantize(Decimal("0.01"))


def when(dt: datetime) -> str:
    local = dt.astimezone(STORE_TZ)
    return local.strftime("%a %b %-d, %-I:%M %p")


def plural(n: int, word: str) -> str:
    return f"{n} {word}" if n == 1 else f"{n} {word}s"


def slugify(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower().replace("'", "")).strip("-")[:60] or "item"


def _norm(text: str) -> str:
    return re.sub(r"[^a-z0-9 ]+", "", text.lower().replace("-", " "))


# ── The store (catalog + change log) ──

class Store:
    """Everything the agent and the console read or write, over one DB connection."""

    def __init__(self, db_url: str):
        self.url = db_url
        self.lock = threading.RLock()
        self.conn = self._connect()

    def _connect(self) -> psycopg.Connection:
        return psycopg.connect(self.url, autocommit=True, row_factory=dict_row)

    def q(self, sql: str, params=None) -> list[dict]:
        with self.lock:
            if self.conn.closed:
                self.conn = self._connect()
            try:
                cur = self.conn.execute(sql, params)
            except psycopg.OperationalError:
                self.conn = self._connect()
                cur = self.conn.execute(sql, params)
            return cur.fetchall() if cur.description else []

    def one(self, sql: str, params=None) -> dict | None:
        rows = self.q(sql, params)
        return rows[0] if rows else None

    # catalog
    def catalog(self) -> list[dict]:
        return self.q("select * from product_catalog order by section_x, sort")

    def product(self, product_id: str) -> dict | None:
        return self.one("select * from product_catalog where id = %s", [product_id])

    def sections(self) -> list[dict]:
        return self.q("select id, name from sections order by x, y")

    def deals(self) -> list[dict]:
        return self.q("""
            select d.*, p.short_name, d.id in (select id from live_deals) as live
            from deals d join products p on p.id = d.product_id
            order by d.active desc, d.created_at desc""")

    def carts_with(self, product_ids: list[str]) -> int:
        return self.one("""
            select count(*) as n from carts
            where exists (select 1 from jsonb_array_elements(items) e where e->>'product_id' = any(%s))""",
                        [product_ids])["n"]

    def cart(self, cart_id: str) -> dict | None:
        return self.one("select * from carts where cart_id = %s", [cart_id])

    # anonymous analytics (06_analytics.sql)
    def insights(self) -> dict:
        return self.one("select * from store_insights")

    def deal_performance(self, limit: int = 8) -> list[dict]:
        return self.q("select * from deal_performance where offered > 0 or live limit %s", [limit])

    # change log
    def stage(self, tool: str, args: dict, summary: str, request: str | None) -> dict:
        return self.one("insert into merchant_changes (tool, args, summary, request) "
                        "values (%s, %s, %s, %s) returning *", [tool, Jsonb(args), summary, request])

    def change(self, change_id: int) -> dict | None:
        return self.one("select * from merchant_changes where id = %s", [change_id])

    def changes(self, limit: int = 30) -> list[dict]:
        return self.q("select * from merchant_changes order by id desc limit %s", [limit])

    def apply(self, change_id: int) -> dict:
        return self.one("select * from merchant_apply(%s)", [change_id])

    def cancel(self, change_id: int) -> dict:
        return self.one("select * from merchant_cancel(%s)", [change_id])

    def undo(self, change_id: int) -> dict:
        return self.one("select * from merchant_undo(%s)", [change_id])


# ── Tools ──

def build_tools(section_ids: list[str]) -> list[dict]:
    product_id = {"type": "string", "description": "Exact product id from search_products, e.g. \"kirkland-parmesan\"."}
    tools = [
        {
            "name": "search_products",
            "description": "Search the live catalog by name, brand, category or tag (\"parmesan\", \"rao\", "
                           "\"cheese\", \"tacos\"). An empty query lists every product. Returns id, names, "
                           "price, any running deal and the price after it, aisle and stock. Read-only.",
            "input_schema": {"type": "object", "properties": {"query": {"type": "string"}},
                             "required": ["query"], "additionalProperties": False},
        },
        {
            "name": "list_deals",
            "description": "List every deal: running, scheduled, expired and ended, with its id. Read-only.",
            "input_schema": {"type": "object", "properties": {}, "required": [], "additionalProperties": False},
        },
        {
            "name": "store_insights",
            "description": "Anonymous store numbers: paid trips, average basket and items, average time in store, "
                           "savings, and for each deal how often the cart offered it at the moment of decision, "
                           "how often shoppers took it, and units sold. Read-only.",
            "input_schema": {"type": "object", "properties": {}, "required": [], "additionalProperties": False},
        },
        {
            "name": "recent_changes",
            "description": "The last 10 entries of the store's change log (id, what changed, status). "
                           "Use it to find the change the owner means by \"undo that\". Read-only.",
            "input_schema": {"type": "object", "properties": {}, "required": [], "additionalProperties": False},
        },
        {
            "name": "update_price",
            "description": "Stage a new list (shelf) price for a product. For a temporary discount use "
                           "create_deal instead. Stages only; the owner confirms.",
            "input_schema": {"type": "object", "properties": {
                "product_id": product_id,
                "new_price": {"type": "number", "description": "New list price in USD, e.g. 11.99."},
            }, "required": ["product_id", "new_price"], "additionalProperties": False},
        },
        {
            "name": "move_product",
            "description": "Stage moving a product to another aisle/section. Shopper directions follow it. "
                           "Stages only; the owner confirms.",
            "input_schema": {"type": "object", "properties": {
                "product_id": product_id,
                "section": {"type": "string", "enum": section_ids, "description": "Section id, e.g. \"A6\" for Aisle 6."},
            }, "required": ["product_id", "section"], "additionalProperties": False},
        },
        {
            "name": "set_stock",
            "description": "Stage the shelf count for a product. \"We're out of X\" means 0. "
                           "Stages only; the owner confirms.",
            "input_schema": {"type": "object", "properties": {
                "product_id": product_id,
                "stock": {"type": "integer", "description": "Units on the shelf, 0 or more."},
            }, "required": ["product_id", "stock"], "additionalProperties": False},
        },
        {
            "name": "add_product",
            "description": "Stage a new product. Ask the owner for anything you can't reasonably infer "
                           "(price, aisle). Stages only; the owner confirms.",
            "input_schema": {"type": "object", "properties": {
                "name": {"type": "string", "description": "Full name with brand and size, e.g. \"Fresh Basil, 0.75 oz\"."},
                "short_name": {"type": "string", "description": "At most 11 characters, used on the cart screen and by the voice, e.g. \"Basil\"."},
                "price": {"type": "number", "description": "List price in USD."},
                "section": {"type": "string", "enum": section_ids},
                "category": {"type": "string", "description": "One lowercase word, e.g. \"produce\"."},
                "tags": {"type": "array", "items": {"type": "string"},
                         "description": "Lowercase meal/use tags the shopping assistant plans with, e.g. [\"pasta\", \"italian\"]."},
                "stock": {"type": "integer"},
                "vision_hint": {"type": "string", "description": "What the item looks like in a cart (shape, packaging, colors, "
                                                                 "label text), so the cart cameras can recognize it. Always fill it: if "
                                                                 "the owner didn't describe it, write it from the product and its usual "
                                                                 "packaging. The preview shows it so they can correct it."},
            }, "required": ["name", "short_name", "price", "section", "category", "tags", "stock", "vision_hint"],
                "additionalProperties": False},
        },
        {
            "name": "create_deal",
            "description": "Stage a deal on one product. It replaces any deal already running on that product. "
                           "Shopper carts get it live, and the cart suggests it when a shopper picks up one of "
                           "the pairs_with products. Stages only; the owner confirms.",
            "input_schema": {"type": "object", "properties": {
                "product_id": product_id,
                "type": {"type": "string", "enum": ["amount_off", "percent_off"]},
                "value": {"type": "number", "description": "Dollars off (amount_off) or percent off (percent_off)."},
                "ends_at": {"type": ["string", "null"],
                            "description": "ISO 8601 end time with the store's UTC offset, e.g. \"through Sunday\" = "
                                           "that Sunday 23:59:59. null = until the owner ends it."},
                "pairs_with": {"type": "array", "items": {"type": "string"},
                               "description": "Product ids that go with it (spaghetti → sauce, parmesan). "
                                               "Pick 1-3 sensible ones from search_products."},
            }, "required": ["product_id", "type", "value", "ends_at", "pairs_with"], "additionalProperties": False},
        },
        {
            "name": "end_deal",
            "description": "Stage ending a running deal (id from search_products or list_deals). "
                           "Stages only; the owner confirms.",
            "input_schema": {"type": "object", "properties": {"deal_id": {"type": "string"}},
                             "required": ["deal_id"], "additionalProperties": False},
        },
        {
            "name": "undo_change",
            "description": "Stage undoing an applied change from the change log (id from recent_changes). "
                           "Stages only; the owner confirms.",
            "input_schema": {"type": "object", "properties": {"change_id": {"type": "integer"}},
                             "required": ["change_id"], "additionalProperties": False},
        },
    ]
    for t in tools:
        t["strict"] = True
    return tools


WRITE_TOOLS = {"update_price", "move_product", "set_stock", "add_product", "create_deal", "end_deal", "undo_change"}


def _product_line(p: dict) -> dict:
    out = {"id": p["id"], "name": p["name"], "short_name": p["short_name"], "price": float(p["price"]),
           "aisle": p["section_name"], "section": p["section"], "stock": p["stock"],
           "category": p["category"], "tags": p["tags"]}
    if p["deal_id"]:
        out["deal"] = {"id": p["deal_id"], "label": p["deal_label"], "sale_price": float(p["sale_price"]),
                       "ends_at": p["deal_ends_at"].isoformat() if p["deal_ends_at"] else None}
    return out


class Tools:
    """Runs one tool call: reads return data, writes return a staged change."""

    def __init__(self, store: Store):
        self.store = store
        self.sections = {s["id"]: s["name"] for s in store.sections()}

    def _product(self, product_id: str) -> dict:
        p = self.store.product(product_id)
        if not p:
            raise ToolError(f"No product with id {product_id!r}. Use search_products to find the exact id.")
        return p

    def _section(self, section: str) -> str:
        if section not in self.sections:
            raise ToolError(f"Unknown section {section!r}. Sections: {', '.join(self.sections)}.")
        return self.sections[section]

    def _impact(self, product_id: str) -> int:
        return self.store.carts_with([product_id])

    def run(self, name: str, inp: dict, request: str | None) -> tuple[str, dict | None]:
        """Returns (text for Claude, staged change or None). Raises ToolError."""
        if name == "search_products":
            return self.search_products(inp.get("query", "")), None
        if name == "list_deals":
            return self.list_deals(), None
        if name == "recent_changes":
            return self.recent_changes(), None
        if name == "store_insights":
            return json.dumps({"store": self.store.insights(), "deals": self.store.deal_performance()},
                              default=str), None
        if name not in WRITE_TOOLS:
            raise ToolError(f"Unknown tool {name}.")
        tool, args, summary = getattr(self, "stage_" + name)(inp)
        change = self.store.stage(tool, args, summary, request)
        text = (f"Staged change #{change['id']}. It is NOT applied yet. The owner sees this preview "
                f"with Confirm and Cancel buttons:\n{summary}")
        return text, change

    # reads
    def search_products(self, query: str) -> str:
        rows = self.store.catalog()
        words = [w for w in _norm(query).split() if w]
        if words:
            def score(p):
                hay = _norm(" ".join([p["id"], p["name"], p["short_name"], p["category"], *p["tags"]]))
                return sum(1 for w in words if w in hay or (len(w) > 3 and w.rstrip("s") in hay))
            rows = sorted((p for p in rows if score(p)), key=score, reverse=True)[:8]
        if not rows:
            return f"No products match {query!r}."
        return json.dumps([_product_line(p) for p in rows])

    def list_deals(self) -> str:
        now = datetime.now(STORE_TZ)
        out = []
        for d in self.store.deals():
            state = ("running" if d["live"] else "ended" if not d["active"]
                     else "expired" if d["ends_at"] and d["ends_at"] <= now else "scheduled")
            out.append({"id": d["id"], "product_id": d["product_id"], "product": d["short_name"],
                        "label": d["label"], "state": state, "pairs_with": d["pairs_with"],
                        "ends_at": d["ends_at"].isoformat() if d["ends_at"] else None})
        return json.dumps(out)

    def recent_changes(self) -> str:
        return json.dumps([{"id": c["id"], "tool": c["tool"], "summary": c["summary"], "status": c["status"]}
                           for c in self.store.changes(10)]) or "[]"

    # writes: each returns (tool, args, plain-English summary); nothing touches the catalog here
    def stage_update_price(self, inp):
        p = self._product(inp["product_id"])
        new = Decimal(str(inp["new_price"])).quantize(Decimal("0.01"))
        old = Decimal(str(p["price"]))
        if new <= 0 or new >= 10000:
            raise ToolError("Price must be between $0.01 and $9,999.99.")
        if new == old:
            raise ToolError(f"{p['short_name']} is already {money(old)}.")
        lines = [f"Change the price of {p['short_name']} ({p['name']}) from {money(old)} to {money(new)}."]
        if p["deal_id"]:
            lines.append(f"With its {p['deal_label']} deal, shoppers pay "
                         f"{money(sale_price(new, p['deal_type'], p['deal_value']))}.")
        n = self._impact(p["id"])
        if n:
            lines.append(f"{plural(n, 'cart')} with it now "
                         + (f"{'gets' if n == 1 else 'get'} the lower price right away." if new < old
                            else f"{'keeps' if n == 1 else 'keep'} the price {'its shopper' if n == 1 else 'they'} saw."))
        return "update_price", {"product_id": p["id"], "price": float(new), "expect": {"price": float(old)}}, " ".join(lines)

    def stage_move_product(self, inp):
        p = self._product(inp["product_id"])
        to = inp["section"]
        to_name = self._section(to)
        if to == p["section"]:
            raise ToolError(f"{p['short_name']} is already in {to_name}.")
        summary = (f"Move {p['short_name']} from {p['section_name']} to {to_name}. "
                   "Shopping lists and directions on the carts update right away.")
        return "move_product", {"product_id": p["id"], "section": to, "expect": {"section": p["section"]}}, summary

    def stage_set_stock(self, inp):
        p = self._product(inp["product_id"])
        stock = int(inp["stock"])
        if stock < 0 or stock > 100000:
            raise ToolError("Stock must be between 0 and 100,000.")
        if stock == p["stock"]:
            raise ToolError(f"{p['short_name']} stock is already {stock}.")
        summary = f"Set {p['short_name']} stock from {p['stock']} to {stock}"
        if stock == 0:
            summary += (" (out of stock). Kart stops suggesting it and shows it as out of stock "
                        "on shoppers' lists.")
        elif p["stock"] == 0:
            summary += ". It's back on shoppers' lists and can be suggested again."
        else:
            summary += "."
        return "set_stock", {"product_id": p["id"], "stock": stock, "expect": {"stock": p["stock"]}}, summary

    def stage_add_product(self, inp):
        name, short = inp["name"].strip(), inp["short_name"].strip()
        if not name or not short:
            raise ToolError("Name and short_name are required.")
        if len(short) > 11:
            raise ToolError(f"short_name must be 11 characters or fewer ({short!r} is {len(short)}).")
        price = Decimal(str(inp["price"])).quantize(Decimal("0.01"))
        if price <= 0 or price >= 10000:
            raise ToolError("Price must be between $0.01 and $9,999.99.")
        section_name = self._section(inp["section"])
        stock = int(inp["stock"])
        if stock < 0:
            raise ToolError("Stock can't be negative.")
        if not inp["vision_hint"].strip():
            raise ToolError("vision_hint is required so the cart cameras can recognize it.")
        base = slugify(name)
        pid, n = base, 2
        while self.store.one("select 1 from products where id = %s", [pid]):
            pid, n = f"{base}-{n}", n + 1
        tags = sorted({t.strip().lower() for t in inp["tags"] if t.strip()})
        args = {"id": pid, "name": name, "short_name": short, "price": float(price), "section": inp["section"],
                "category": inp["category"].strip().lower() or "other", "tags": tags, "stock": stock,
                "vision_hint": inp["vision_hint"].strip()}
        summary = (f"Add a new product: {name} (\"{short}\"), {money(price)}, in {section_name}, "
                   f"{stock} in stock" + (f", tagged {', '.join(tags)}" if tags else "") + ". "
                   f"Cart cameras will look for: {args['vision_hint']}")
        return "add_product", args, summary

    def stage_create_deal(self, inp):
        p = self._product(inp["product_id"])
        kind, value = inp["type"], Decimal(str(inp["value"])).quantize(Decimal("0.01"))
        price = Decimal(str(p["price"]))
        if kind == "amount_off" and not (0 < value < price):
            raise ToolError(f"A dollar-off deal on {p['short_name']} must be between $0.01 and {money(price)}.")
        if kind == "percent_off" and not (0 < value < 100):
            raise ToolError("A percent-off deal must be between 1 and 99 percent.")
        ends_at = None
        if inp.get("ends_at"):
            try:
                ends_at = datetime.fromisoformat(inp["ends_at"])
            except ValueError:
                raise ToolError(f"ends_at {inp['ends_at']!r} isn't an ISO 8601 time.") from None
            if ends_at.tzinfo is None:
                ends_at = ends_at.replace(tzinfo=STORE_TZ)
            if ends_at <= datetime.now(STORE_TZ):
                raise ToolError(f"ends_at {inp['ends_at']} is in the past.")
        pairs = []
        for q in inp["pairs_with"]:
            if q != p["id"] and q not in pairs:
                self._product(q)
                pairs.append(q)
        label = deal_label(kind, value)
        new_price = sale_price(price, kind, value)
        stamp = datetime.now(STORE_TZ).strftime("%Y%m%d%H%M%S")
        args = {"deal_id": f"d-{p['id']}-{stamp}", "product_id": p["id"], "type": kind, "value": float(value),
                "label": label, "ends_at": ends_at.isoformat() if ends_at else None, "pairs_with": pairs}
        lines = [f"New deal: {p['short_name']} {label} ({money(new_price)} instead of {money(price)}), "
                 + (f"through {when(ends_at)}." if ends_at else "until you end it.")]
        if pairs:
            names = [self.store.product(q)["short_name"] for q in pairs]
            lines.append(f"Kart suggests it when a shopper picks up {', '.join(names[:-1]) + ' or ' if len(names) > 1 else ''}{names[-1]}.")
        if p["deal_id"]:
            lines.append(f"Replaces the current {p['deal_label']} deal.")
        n = self._impact(p["id"])
        if n:
            lines.append(f"{plural(n, 'cart')} with {p['short_name']} {'gets' if n == 1 else 'get'} "
                         "the lower price right away.")
        return "create_deal", args, " ".join(lines)

    def stage_end_deal(self, inp):
        d = self.store.one("select d.*, p.short_name, p.price from deals d join products p on p.id = d.product_id "
                           "where d.id = %s", [inp["deal_id"]])
        if not d or not d["active"]:
            raise ToolError(f"No running deal with id {inp['deal_id']!r}. Use list_deals.")
        summary = (f"End the {d['short_name']} {d['label']} deal. Carts that already have {d['short_name']} "
                   f"keep the deal price; new ones pay {money(d['price'])}.")
        return "end_deal", {"deal_id": d["id"]}, summary

    def stage_undo_change(self, inp):
        c = self.store.change(int(inp["change_id"]))
        if not c or c["status"] != "applied" or c["tool"] == "undo":
            raise ToolError(f"Change #{inp['change_id']} can't be undone (only applied changes can).")
        return "undo", {"change_id": c["id"]}, f"Undo change #{c['id']}: {c['summary']}"


# ── The agent ──

SYSTEM = """You are the store assistant for {store}, a warehouse store whose shopping carts \
run KART: cameras bill items as they go in, and an iPad on each cart shows the live bill, \
directions and deals. You talk with the store's owner or manager, who is not technical. \
They tell you what changed in the store and you make it so in the live catalog.

How changes work:
- Look products up with search_products before changing anything, and use the exact ids it returns. \
Never invent products, ids, prices or deals.
- The write tools (update_price, move_product, set_stock, add_product, create_deal, end_deal, \
undo_change) only STAGE a change. The owner sees your staged change as a card with Confirm and \
Cancel buttons; nothing changes in the store until they press Confirm. Never say a change is done, \
live or applied unless a console update tells you it was confirmed.
- After staging, reply in one or two short sentences: what you staged, and that it's waiting for \
their Confirm. Don't repeat the whole preview; they can read the card.
- One request can need several changes ("Rao's is out, put the spaghetti on sale instead"): stage each.
- New products: the cart cameras recognize items from vision_hint, so always write one (from the owner's \
description, or from the product's usual packaging) and mention they can correct it.
- If something is ambiguous (two products match, no price given for a new item), ask one short question \
instead of guessing. Infer the obvious: "we're out of X" is stock 0; "X $3 off" is an amount_off deal; \
"20% off" is percent_off; a temporary discount is a deal, while "X now costs $Y" is a price change.
- Deals: one running deal per product (a new one replaces the old). Choose pairs_with from products a \
shopper buys together, since that's when the cart suggests the deal. "Through Sunday" ends at 23:59:59 \
that Sunday, store time.
- Shoppers keep the price they saw: price drops and new deals reach carts right away; increases and \
ended deals only affect items added afterwards. Mention it when it matters.

Questions like "how are the deals doing?" or "how big are baskets?": use store_insights and answer \
with the two or three numbers that matter. The numbers are anonymous totals; there is no shopper data.

Write like a helpful store clerk: plain words, no ids, no JSON, no jargon.

Store sections: {sections}."""


class MerchantAgent:
    """One conversation with the owner. History lives in memory (one console, one owner)."""

    def __init__(self, store: Store, client: anthropic.Anthropic | None = None):
        self.store = store
        self._client = client
        self.tools_impl = Tools(store)
        self.tools = build_tools(list(self.tools_impl.sections))
        info = store.one("select name from store_info where id = 1") or {"name": "the store"}
        sections = "; ".join(f"{k} = {v}" for k, v in self.tools_impl.sections.items())
        self.system = SYSTEM.format(store=info["name"], sections=sections)
        self.lock = threading.Lock()
        self.reset()

    def reset(self) -> None:
        self.messages: list[dict] = []
        self.notes: list[str] = []

    @property
    def client(self) -> anthropic.Anthropic:
        if self._client is None:  # created on first chat, so the console runs without a key
            self._client = anthropic.Anthropic()
        return self._client

    def note(self, text: str) -> None:
        """A console event Claude should know about on the next turn (confirmed, cancelled, undone)."""
        self.notes.append(text)

    def _call(self):
        try:
            return self._create()
        except TypeError as e:  # the SDK's "Could not resolve authentication method"
            if "authentication" not in str(e):
                raise
            raise anthropic.AnthropicError(str(e)) from e

    def _create(self):
        return self.client.beta.messages.create(
            model=MODEL,
            max_tokens=16000,
            system=self.system,
            tools=self.tools,
            messages=self.messages,
            output_config={"effort": EFFORT},
            cache_control={"type": "ephemeral"},     # caches the growing conversation prefix
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",                     # a refused request is retried server-side
        )

    def chat(self, text: str) -> dict:
        with self.lock:
            start = len(self.messages)
            now = datetime.now(STORE_TZ)
            update = f"Now: {now:%A %Y-%m-%d %H:%M} store time ({now:%Z}, UTC{now:%z})."
            shown = list(self.notes)
            if shown:
                update += "\nConsole updates since your last reply:\n" + "\n".join(f"- {n}" for n in shown)
            self.messages.append({"role": "user", "content": text})
            # Operator channel: a mid-conversation system message, so the history prefix stays cached.
            self.messages.append({"role": "system", "content": update})
            staged: list[dict] = []
            try:
                reply = self._run(text, staged)
            except anthropic.AnthropicError as e:   # API errors, and no credentials configured
                del self.messages[start:]    # drop the unanswered tail so the history stays valid
                if staged:
                    self.notes.append("A request failed midway; these changes were staged and are still "
                                      "waiting: " + ", ".join(f"#{c['id']}" for c in staged))
                why = ("ANTHROPIC_API_KEY isn't set" if not isinstance(e, anthropic.APIError)
                       else type(e).__name__)
                return {"reply": f"Sorry, I couldn't reach the assistant ({why}). Try again.",
                        "staged": staged, "error": True}
            del self.notes[:len(shown)]  # keep any that arrived while we were talking
            return {"reply": reply, "staged": staged}

    def _run(self, request: str, staged: list[dict]) -> str:
        for _ in range(MAX_TOOL_ROUNDS):
            response = self._call()
            if response.stop_reason == "refusal":
                # keep the history valid (a system message can't be followed by a user turn)
                self.messages.append({"role": "assistant", "content": [
                    {"type": "text", "text": "(I declined that request.)"}]})
                return "Sorry, I can't help with that one."
            self.messages.append({"role": "assistant", "content": response.content})
            if response.stop_reason == "pause_turn":
                continue
            if response.stop_reason != "tool_use":
                text = " ".join(b.text for b in response.content if b.type == "text").strip()
                if response.stop_reason == "max_tokens":
                    text += " (I ran out of room; ask me to continue.)"
                return text or "Done."
            results = []
            for block in response.content:
                if block.type != "tool_use":
                    continue
                try:
                    out, change = self.tools_impl.run(block.name, dict(block.input), request)
                    if change:
                        staged.append(change)
                    results.append({"type": "tool_result", "tool_use_id": block.id, "content": out})
                except (ToolError, KeyError, ValueError, TypeError) as e:
                    results.append({"type": "tool_result", "tool_use_id": block.id,
                                    "content": f"Error: {e}", "is_error": True})
            self.messages.append({"role": "user", "content": results})
        return "That took more steps than I expected. Check the staged changes and tell me what's left."


def open_store(db_url: str | None = None) -> Store:
    kartdb.load_env()
    return Store(kartdb.db_url(db_url))
