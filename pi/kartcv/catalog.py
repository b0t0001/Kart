"""Product catalog: the closed set CV identifies against (CONTRACT §2, v0.9 §3a)."""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path

from kartcv import http

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class Product:
    id: str
    name: str
    price: float = 0.0
    vision_hint: str = ""
    short_name: str = ""


class Catalog:
    def __init__(self, products: dict[str, Product]):
        self.products = products

    def ids(self) -> list[str]:
        return sorted(self.products)

    def get(self, pid: str | None) -> Product | None:
        return self.products.get(pid) if pid else None

    def name(self, pid: str) -> str:
        p = self.products.get(pid)
        return p.name if p else pid

    def prompt_lines(self) -> str:
        return "\n".join(f"{p.id} | {p.name} | {p.vision_hint}" for p in sorted(self.products.values(), key=lambda p: p.id))

    def replace_with(self, other: Catalog) -> None:
        # One assignment, so readers on other threads see either the old or the new dict.
        self.products = other.products


def _product(row: dict) -> Product:
    return Product(
        id=row["id"],
        name=row.get("name") or row["id"],
        price=float(row.get("price") or 0.0),
        vision_hint=row.get("vision_hint") or "",
        short_name=row.get("short_name") or "",
    )


def _from_rows(rows: list[dict]) -> Catalog:
    return Catalog({r["id"]: _product(r) for r in rows})


FALLBACK_CATALOG = _from_rows([
    {"id": "kirkland-parmesan", "name": "Kirkland Parmigiano Reggiano", "price": 12.99,
     "vision_hint": "wedge of hard pale-yellow cheese in clear wrap, red/white Kirkland label"},
    {"id": "barilla-spaghetti", "name": "Barilla Spaghetti", "price": 1.99,
     "vision_hint": "blue cardboard box of dry spaghetti, Barilla logo"},
    {"id": "rao-marinara", "name": "Rao's Marinara", "price": 6.99,
     "vision_hint": "glass jar of red tomato sauce, black and white Rao's label"},
])


def load_catalog(path: Path) -> Catalog:
    path = Path(path)
    if not path.exists():
        log.warning("catalog: %s not found, using the built-in fallback catalog", path)
        return Catalog(dict(FALLBACK_CATALOG.products))
    return _from_rows(json.loads(path.read_text())["products"])


def fetch_catalog(base_url: str, anon_key: str, get=None) -> Catalog | None:
    """Live catalog from Supabase. The product_catalog view lists only active products. None on any failure."""
    get = get or http.get
    url = f"{base_url.rstrip('/')}/rest/v1/product_catalog?select=id,name,short_name,price,vision_hint"
    try:
        status, body = get(url, http.supabase_headers(anon_key))
    except OSError as e:
        log.warning("catalog: Supabase fetch failed (%s)", e)
        return None
    if status != 200:
        log.warning("catalog: Supabase returned HTTP %s", status)
        return None
    try:
        rows = json.loads(body)
    except ValueError:
        log.warning("catalog: Supabase returned invalid JSON")
        return None
    if not isinstance(rows, list) or not rows:
        return None
    return _from_rows(rows)
