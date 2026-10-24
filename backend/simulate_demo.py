"""Play the 2-minute KART demo against the cart database, as CV and the iPad would.

  python backend/simulate_demo.py                 # via Supabase REST if SUPABASE_URL is set, else SQL
  python backend/simulate_demo.py --delay 3       # pause between steps (watch the iPad update live)
  python backend/simulate_demo.py --via db --db-url postgresql://postgres@localhost:54329/kart_dev

REST mode uses the anon key, exactly like the Pi and the iPad, so it also checks permissions.
"""

from __future__ import annotations

import argparse
import os
import time
import uuid

import httpx

import kartdb

PASTA_PLAN = [
    {"product_id": "barilla-spaghetti", "reason": "the pasta"},
    {"product_id": "rao-marinara", "reason": "the sauce"},
    {"product_id": "kirkland-parmesan", "reason": "to grate on top"},
    {"product_id": "french-baguette", "reason": "garlic bread"},
]


def vision(type_, product_id, label, confidence=0.93, method="local", event_id=None):
    return {"p_type": type_, "p_product_id": product_id, "p_confidence": confidence,
            "p_source": "vision", "p_label": label, "p_camera": 0,
            "p_event_id": event_id or str(uuid.uuid4()), "p_method": method}


def steps():
    first_add = vision("added", "barilla-spaghetti", "Barilla Spaghetti, 1 lb", 0.94)
    unknown = vision("added", None, "blue cardboard box, label not visible", 0.31, "none")
    return [
        ("iPad: new trip", "reset_cart", {}),
        ("Voice agent: 'pasta dinner for my family' → plan", "set_plan", {"p_plan": PASTA_PLAN}),
        ("CV: spaghetti dropped in (local match)", "apply_cart_event", first_add),
        ("CV: outbox retries the same event (must be ignored)", "apply_cart_event", first_add),
        ("CV: parmesan, the suggested deal (cloud match)", "apply_cart_event",
         vision("added", "kirkland-parmesan", "Kirkland Parmigiano Reggiano", 0.88, "cloud")),
        ("CV: Rao's marinara", "apply_cart_event", vision("added", "rao-marinara", "Rao's Homemade Marinara")),
        ("CV: Rao's taken back out", "apply_cart_event",
         vision("removed", "rao-marinara", "Rao's Homemade Marinara", 0.97, "memory")),
        ("CV: something it can't identify", "apply_cart_event", unknown),
        ("iPad: confirm card → 'it's spaghetti'", "apply_cart_event",
         {"p_type": "added", "p_product_id": "barilla-spaghetti", "p_confidence": 1.0,
          "p_source": "manual", "p_label": "confirmed by shopper", "p_method": "manual",
          "p_resolves_event_id": unknown["p_event_id"]}),
        ("Voice: 'I'm done'", "set_cart_status", {"p_status": "checkout"}),
        ("iPad: tap to pay (simulated)", "checkout", {"p_provider": "simulated"}),
    ]


class RestClient:
    def __init__(self, url: str, key: str):
        self.http = httpx.Client(base_url=url.rstrip("/") + "/rest/v1", timeout=10,
                                 headers={"apikey": key, "Authorization": f"Bearer {key}"})

    def call(self, name: str, params: dict) -> dict:
        r = self.http.post(f"/rpc/{name}", json=params)
        r.raise_for_status()
        return r.json()


class SqlClient:
    def __init__(self, url: str):
        self.conn = kartdb.connect(url)

    def call(self, name: str, params: dict) -> dict:
        return kartdb.rpc(self.conn, name, **params)


def show(cart: dict) -> None:
    if "duration_s" in cart:  # a receipt
        print(f"   RECEIPT ${cart['total']:.2f}  saved ${cart['savings']:.2f}  "
              f"{cart['item_count']} items  {cart['duration_s']} s  via {cart['provider']}")
        return
    items = ", ".join(f"{i['short_name']}×{i['qty']} ${i['price']:.2f}"
                      + (f" ({i['deal_label']})" if i.get("deal_label") else "")
                      for i in cart["items"]) or "(empty)"
    print(f"   total ${cart['total']:.2f}  saved ${cart['savings']:.2f}  items: {items}")
    print(f"   next_step: {cart['next_step']}")
    print(f"   status:    {cart['status']}   lcd: [{cart['lcd_line1']:<16}]")
    if cart.get("suggestion"):
        print(f"   suggest:   {cart['suggestion']['text']}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--via", choices=["auto", "rest", "db"], default="auto")
    ap.add_argument("--db-url")
    ap.add_argument("--cart", default=None, help="default: CART_ID from .env, else 7")
    ap.add_argument("--delay", type=float, default=0.0)
    args = ap.parse_args()

    kartdb.load_env()
    cart = args.cart or os.environ.get("CART_ID", "7")
    use_rest = args.via == "rest" or (args.via == "auto" and os.environ.get("SUPABASE_URL") and not args.db_url)
    if use_rest:
        client = RestClient(os.environ["SUPABASE_URL"], os.environ["SUPABASE_ANON_KEY"])
        print(f"via Supabase REST (anon key), cart {cart}")
    else:
        client = SqlClient(kartdb.db_url(args.db_url))
        print(f"via SQL, cart {cart}")

    for n, (title, fn, params) in enumerate(steps(), 1):
        result = client.call(fn, {"p_cart_id": cart, **params})
        print(f"\n{n}. {title}")
        show(result)
        time.sleep(args.delay)


if __name__ == "__main__":
    main()
