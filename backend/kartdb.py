"""Shared helpers for the KART backend scripts: env, DB connection, migrations, seeding."""

from __future__ import annotations

import json
import os
from pathlib import Path

import psycopg
from dotenv import load_dotenv

BACKEND = Path(__file__).resolve().parent
REPO = BACKEND.parent
DB_DIR = BACKEND / "db"
STORE_JSON = REPO / "data" / "store.json"
SHIM = DB_DIR / "local_supabase_shim.sql"

# Tables we own; --fresh drops these (never the whole schema: Supabase owns public's grants).
OUR_TABLES = ["receipts", "transcript", "cart_events", "carts", "deals", "products", "sections", "store_info"]


def load_env() -> None:
    """Load the shared env file (CONTRACT §6): KART_ENV_FILE, else <repo>/.env."""
    load_dotenv(os.environ.get("KART_ENV_FILE", REPO / ".env"))


def db_url(override: str | None = None) -> str:
    url = override or os.environ.get("SUPABASE_DB_URL")
    if not url:
        raise SystemExit("SUPABASE_DB_URL is not set (add it to the repo .env, or pass --db-url)")
    return url


def connect(url: str) -> psycopg.Connection:
    return psycopg.connect(url, autocommit=True)


def migration_files() -> list[Path]:
    return sorted(p for p in DB_DIR.glob("[0-9][0-9]_*.sql"))


def apply_migrations(conn: psycopg.Connection, *, fresh: bool = False, local: bool = False) -> list[str]:
    applied = []
    if local:
        conn.execute(SHIM.read_text())
        applied.append(SHIM.name)
    if fresh:
        conn.execute("drop view if exists product_catalog, live_deals cascade")
        conn.execute("drop table if exists " + ", ".join(OUR_TABLES) + " cascade")
    for f in migration_files():
        conn.execute(f.read_text())
        applied.append(f.name)
    return applied


def seed(conn: psycopg.Connection, store_path: Path = STORE_JSON) -> dict:
    store = json.loads(store_path.read_text())
    row = conn.execute("select seed_catalog(%s::jsonb)", [json.dumps(store)]).fetchone()
    return row[0]


def catalog_is_empty(conn: psycopg.Connection) -> bool:
    return conn.execute("select not exists (select 1 from products)").fetchone()[0]


# Postgres types of every RPC parameter, so calls resolve the same way PostgREST's do.
RPC_PARAM_TYPES = {
    "p_cart_id": "text", "p_type": "text", "p_product_id": "text", "p_confidence": "real",
    "p_source": "text", "p_label": "text", "p_camera": "int", "p_snapshot_url": "text",
    "p_event_id": "uuid", "p_method": "text", "p_plan": "jsonb", "p_resolves_event_id": "uuid",
    "p_status": "text", "p_section": "text", "p_role": "text", "p_text": "text", "p_provider": "text",
}


def rpc(conn: psycopg.Connection, name: str, **params) -> dict | None:
    """Call a cart RPC directly over SQL; returns the carts row as a dict (like PostgREST)."""
    args = ", ".join(f"{k} => %({k})s::{RPC_PARAM_TYPES[k]}" for k in params)
    values = {k: json.dumps(v) if RPC_PARAM_TYPES[k] == "jsonb" else v for k, v in params.items()}
    row = conn.execute(f"select to_jsonb(r) from {name}({args}) r", values).fetchone()
    return row[0] if row else None
