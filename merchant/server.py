"""KART merchant console: chat with the store, watch the catalog and the change log live.

  merchant/.venv/bin/python merchant/server.py              # http://localhost:8090
  merchant/.venv/bin/python merchant/server.py --db-url postgresql://postgres@localhost:54329/kart_dev

Server-side only: it holds the database URL and ANTHROPIC_API_KEY (from the repo .env);
the page gets neither.
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path

import psycopg
from fastapi import Body, FastAPI, HTTPException
from fastapi.responses import FileResponse

from agent import MerchantAgent, Store, open_store

STATIC = Path(__file__).resolve().parent / "static"


def create_app(store: Store, agent: MerchantAgent | None = None, cart_id: str | None = None) -> FastAPI:
    app = FastAPI(title="KART merchant console")
    agent = agent or MerchantAgent(store)
    cart_id = cart_id or os.environ.get("CART_ID", "7")

    def db_error(e: psycopg.Error) -> HTTPException:
        msg = (getattr(e.diag, "message_primary", None) or str(e)).removeprefix("stale: ")
        return HTTPException(409, msg)

    @app.get("/")
    def index():
        return FileResponse(STATIC / "index.html")

    @app.get("/api/state")
    def state():
        info = store.one("select name from store_info where id = 1") or {"name": "Store"}
        return {
            "store": info["name"],
            "catalog": store.catalog(),
            "deals": store.deals(),
            "changes": store.changes(30),
            "cart": store.cart(cart_id),
        }

    @app.post("/api/chat")
    def chat(message: str = Body(..., embed=True)):
        if not message.strip():
            raise HTTPException(400, "empty message")
        return agent.chat(message.strip())

    @app.post("/api/changes/{change_id}/confirm")
    def confirm(change_id: int):
        try:
            ch = store.apply(change_id)
        except psycopg.Error as e:
            raise db_error(e) from None
        agent.note(f"The owner CONFIRMED change #{ch['id']}; it is now live: {ch['summary']}")
        return ch

    @app.post("/api/changes/{change_id}/cancel")
    def cancel(change_id: int):
        try:
            ch = store.cancel(change_id)
        except psycopg.Error as e:
            raise db_error(e) from None
        agent.note(f"The owner cancelled change #{ch['id']}; nothing changed: {ch['summary']}")
        return ch

    @app.post("/api/changes/{change_id}/undo")
    def undo(change_id: int):
        try:
            ch = store.undo(change_id)
        except psycopg.Error as e:
            raise db_error(e) from None
        agent.note(f"The owner undid change #{change_id} with the Undo button (logged as #{ch['id']}).")
        return ch

    @app.post("/api/conversation/reset")
    def reset():
        agent.reset()
        return {"ok": True}

    return app


def main() -> None:
    import uvicorn

    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--db-url")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8090)
    args = ap.parse_args()
    uvicorn.run(create_app(open_store(args.db_url)), host=args.host, port=args.port)


if __name__ == "__main__":
    main()
