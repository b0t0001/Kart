"""Demo levers: drive a cart (and the deals) from the laptop when a live piece misbehaves.

  python backend/cart.py show
  python backend/cart.py add kirkland-parmesan        # as if the cameras saw it (source: manual)
  python backend/cart.py remove rao-marinara
  python backend/cart.py plan pasta                   # or: tacos, or a list of product ids
  python backend/cart.py reset                        # new trip (the Pi clears its memory too)
  python backend/cart.py status checkout              # idle | shopping | checkout
  python backend/cart.py deal kirkland-parmesan 3     # $3 off; "20%" for percent off
  python backend/cart.py end-deal d-parm-3off

Every change goes through the same RPCs and merchant_apply as the real clients, so the iPad,
the console and the change log all update normally. Deals made here are logged as merchant
changes with request "cart.py fallback" and can be undone in the console.
"""

from __future__ import annotations

import argparse
import json
import os
import time

from psycopg.types.json import Jsonb

import kartdb

PLANS = {
    "pasta": ["barilla-spaghetti", "rao-marinara", "kirkland-parmesan", "french-baguette"],
    "tacos": ["mission-tortillas", "ground-beef", "tillamook-mexican-cheese", "tostitos-salsa",
              "tostitos-chips", "avocados", "daisy-sour-cream"],
}


def show(cart: dict) -> None:
    items = ", ".join(f"{i['short_name']}×{i['qty']} ${float(i['price']):.2f}" for i in cart["items"]) or "(empty)"
    print(f"cart {cart['cart_id']} · {cart['status']} · ${float(cart['total']):.2f} "
          f"(saved ${float(cart['savings']):.2f}) · {items}")
    print(f"  next: {cart['next_step']}")
    if cart.get("suggestion"):
        print(f"  suggest: {cart['suggestion']['text']}")


def merchant(conn, tool: str, args: dict, summary: str) -> int:
    cid = conn.execute("insert into merchant_changes (tool, args, summary, request) "
                       "values (%s, %s, %s, 'cart.py fallback') returning id",
                       [tool, Jsonb(args), summary]).fetchone()[0]
    conn.execute("select merchant_apply(%s)", [cid])
    return cid


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("command", choices=["show", "add", "remove", "plan", "reset", "status", "deal", "end-deal"])
    ap.add_argument("args", nargs="*")
    ap.add_argument("--cart")
    ap.add_argument("--db-url")
    a = ap.parse_args()

    kartdb.load_env()
    cart_id = a.cart or os.environ.get("CART_ID", "7")
    conn = kartdb.connect(kartdb.db_url(a.db_url))
    rpc = lambda fn, **kw: kartdb.rpc(conn, fn, p_cart_id=cart_id, **kw)  # noqa: E731

    if a.command in ("add", "remove"):
        for pid in a.args:
            row = rpc("apply_cart_event", p_type="added" if a.command == "add" else "removed", p_product_id=pid,
                      p_confidence=1.0, p_source="manual", p_label="cart.py", p_method="manual")
    elif a.command == "plan":
        ids = PLANS.get(a.args[0], a.args) if a.args else PLANS["pasta"]
        row = rpc("set_plan", p_plan=[{"product_id": p, "reason": "demo"} for p in ids])
    elif a.command == "reset":
        row = rpc("reset_cart")
    elif a.command == "status":
        row = rpc("set_cart_status", p_status=a.args[0])
    elif a.command == "deal":
        pid, amount = a.args[0], a.args[1]
        pct = amount.endswith("%")
        value = float(amount.rstrip("%").lstrip("$"))
        label = f"{value:g}% off" if pct else (f"${value:g} off" if value == int(value) else f"${value:.2f} off")
        seeded = json.loads(kartdb.STORE_JSON.read_text())["deals"]   # pair it the way the seed does
        pairs = next((d["pairs_with"] for d in seeded if d["product_id"] == pid),
                     next((p for p in PLANS.values() if pid in p), []))
        args = {"deal_id": f"d-{pid}-{time.strftime('%Y%m%d%H%M%S')}", "product_id": pid,
                "type": "percent_off" if pct else "amount_off", "value": value, "label": label,
                "ends_at": None, "pairs_with": [p for p in pairs if p != pid][:3]}
        cid = merchant(conn, "create_deal", args, f"New deal: {pid} {label} (cart.py fallback)")
        print(f"applied merchant change #{cid}: {pid} {label}, pairs with {args['pairs_with']}")
        row = None
    elif a.command == "end-deal":
        cid = merchant(conn, "end_deal", {"deal_id": a.args[0]}, f"End deal {a.args[0]} (cart.py fallback)")
        print(f"applied merchant change #{cid}")
        row = None
    else:
        row = None
    if row is None:
        row = conn.execute("select to_jsonb(c) from carts c where cart_id = %s", [cart_id]).fetchone()
        row = row[0] if row else None
    if row:
        show(row)
    else:
        print(json.dumps({"cart": cart_id, "exists": False}))


if __name__ == "__main__":
    main()
