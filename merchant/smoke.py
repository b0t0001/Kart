"""Smoke-test the merchant agent with REAL Claude against the database in .env (hosted or local).

  merchant/.venv/bin/python merchant/smoke.py                          # in-process console app
  merchant/.venv/bin/python merchant/smoke.py --url http://127.0.0.1:8090   # a running server.py

For each example prompt: Claude stages the expected change with a preview → Confirm applies it →
the change log shows it → Undo restores the catalog. Then the live deal beat on a throwaway cart:
the owner's "parmesan $3 off" must switch that cart's suggestion. Prints latency per prompt and
PASS/FAIL. Costs a few cents.

Safe to run while other teams rehearse on the same database: it undoes exactly what it changed,
never touches cart 7 or the change log, and finally checks that this run left prices, aisles,
deals and the product list as it found them. Stock isn't compared: other teams' checkouts change
it on a shared database. --reset also runs `db.py reset-demo` at the end (only when nobody else
is using the database) and then compares everything, stock included, to data/store.json.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
import uuid
from datetime import datetime, timedelta
from pathlib import Path

import httpx

from agent import STORE_TZ, open_store

ROOT = Path(__file__).resolve().parents[1]
RESET = [str(ROOT / "backend/.venv/bin/python"), str(ROOT / "backend/db.py"), "reset-demo"]
STORE_JSON = ROOT / "data/store.json"


def next_sunday_end() -> datetime:
    now = datetime.now(STORE_TZ)
    days = (6 - now.weekday()) % 7
    return (now + timedelta(days=days)).replace(hour=23, minute=59, second=59, microsecond=0)


class Console:
    def __init__(self, url: str | None, store):
        if url:
            self.http = httpx.Client(base_url=url, timeout=120)
        else:
            from fastapi.testclient import TestClient
            from server import create_app
            self.http = TestClient(create_app(store))  # in-process: no network timeout to set

    def post(self, path, body=None):
        r = self.http.post(path, json=body if body is not None else {})
        return r.status_code, r.json()

    def chat(self, text):
        t = time.perf_counter()
        code, body = self.post("/api/chat", {"message": text})
        return body, time.perf_counter() - t


results: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> bool:
    results.append((name, ok, detail))
    print(f"  {'ok  ' if ok else 'FAIL'} {name}" + (f"  ({detail})" if detail else ""))
    return ok


def catalog_shape(store) -> dict:
    """What this run must leave as it found it: each listed product's price, aisle and running deal."""
    return {r["id"]: (float(r["price"]), r["section"], r["deal_id"]) for r in store.catalog()}


def safe(fn, *args) -> bool:
    try:
        return bool(fn(*args))
    except Exception as e:  # a surprising shape from Claude fails the check, not the run
        print(f"  check raised {type(e).__name__}: {e}")
        return False


def run_case(console, store, prompt, tool, verify_applied, verify_undone, follow_up=None):
    print(f"\n» {prompt!r}")
    console.post("/api/conversation/reset")
    out, secs = console.chat(prompt)
    print(f"  Claude ({secs:.1f}s): {out['reply']}")
    latency = f"{secs:.1f}s"
    if not out["staged"] and follow_up:
        out, more = console.chat(follow_up)
        print(f"  (follow-up {follow_up!r}) Claude ({more:.1f}s): {out['reply']}")
        latency += f" + {more:.1f}s follow-up"
    staged = [c for c in out["staged"] if c["tool"] == tool]
    if not check(f"{prompt}: staged {tool}", bool(staged), latency):
        return latency
    ch = staged[0]
    print(f"  preview: {ch['summary']}")
    for extra in out["staged"]:
        if extra["id"] != ch["id"]:
            console.post(f"/api/changes/{extra['id']}/cancel")
    before = {r["id"]: r for r in store.catalog()}       # what Undo must restore
    code, applied = console.post(f"/api/changes/{ch['id']}/confirm")
    check(f"{prompt}: Confirm applies", code == 200 and applied["status"] == "applied" and safe(verify_applied, ch),
          f"HTTP {code}" + ("" if code == 200 else f": {applied.get('detail')}"))
    if code != 200:
        return latency
    log = {c["id"]: c for c in store.changes(10)}
    check(f"{prompt}: in change log", log.get(ch["id"], {}).get("status") == "applied")
    code, _ = console.post(f"/api/changes/{ch['id']}/undo")
    check(f"{prompt}: Undo restores", code == 200 and safe(verify_undone, ch, before), f"HTTP {code}")
    return latency


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--url", help="a running console (default: run the app in-process)")
    ap.add_argument("--reset", action="store_true", help="run db.py reset-demo at the end")
    args = ap.parse_args()

    store = open_store()
    console = Console(args.url, store)
    start = catalog_shape(store)
    p = store.product
    sunday = next_sunday_end()
    latencies = {}

    latencies["spaghetti deal"] = run_case(
        console, store, "Spaghetti $1 off through Sunday", "create_deal",
        lambda ch: (p("barilla-spaghetti")["deal_label"] == "$1 off"
                    and p("barilla-spaghetti")["deal_ends_at"].astimezone(STORE_TZ).date() == sunday.date()),
        lambda ch, before: p("barilla-spaghetti")["deal_id"] == before["barilla-spaghetti"]["deal_id"])
    latencies["out of marinara"] = run_case(
        console, store, "We're out of marinara", "set_stock",
        lambda ch: p("rao-marinara")["stock"] == 0,
        lambda ch, before: p("rao-marinara")["stock"] == before["rao-marinara"]["stock"])
    latencies["move parmesan"] = run_case(
        console, store, "Move parmesan to aisle 6", "move_product",
        lambda ch: p("kirkland-parmesan")["section"] == "A6",
        lambda ch, before: p("kirkland-parmesan")["section"] == before["kirkland-parmesan"]["section"])
    latencies["add basil"] = run_case(
        console, store, "Add fresh basil, $2.49, produce aisle", "add_product",
        lambda ch: (bool(p(ch["args"]["id"])) and float(p(ch["args"]["id"])["price"]) == 2.49
                    and p(ch["args"]["id"])["section"] == "A1" and bool(ch["args"]["vision_hint"])),
        lambda ch, before: p(ch["args"]["id"]) is None,
        follow_up="20 in stock, go ahead and stage it")

    # The live beat on a throwaway cart
    print("\n» live beat: 'parmesan $1 off' while a cart holds spaghetti")
    cart = f"smoke-{uuid.uuid4().hex[:6]}"
    undo_ids = []
    try:
        if p("kirkland-parmesan")["deal_id"]:     # the pitch opens without a Parmesan deal
            end = store.stage("end_deal", {"deal_id": p("kirkland-parmesan")["deal_id"]},
                              "smoke: end the Parmesan deal for the live beat", "smoke.py")
            store.apply(end["id"])
            undo_ids.append(end["id"])
        store.q("select reset_cart(%s)", [cart])
        store.q("select set_plan(%s, %s::jsonb)", [cart, '[{"product_id":"barilla-spaghetti"},'
                                                        '{"product_id":"rao-marinara"},{"product_id":"french-baguette"}]'])
        store.q("select apply_cart_event(%s, 'added', 'barilla-spaghetti', 0.94, 'vision', 'smoke')", [cart])
        before = store.cart(cart)["suggestion"]
        console.post("/api/conversation/reset")
        out, secs = console.chat("parmesan $1 off")
        print(f"  Claude ({secs:.1f}s): {out['reply']}")
        latencies["parmesan beat"] = f"{secs:.1f}s"
        staged = [c for c in out["staged"] if c["tool"] == "create_deal"]
        if check("beat: staged create_deal on Parmesan",
                 bool(staged) and staged[0]["args"]["product_id"] == "kirkland-parmesan"):
            print(f"  preview: {staged[0]['summary']}")
            t = time.perf_counter()
            console.post(f"/api/changes/{staged[0]['id']}/confirm")
            undo_ids.append(staged[0]["id"])
            sugg = store.cart(cart)["suggestion"]
            check("beat: cart suggestion switches to Parmesan",
                  (sugg or {}).get("text") == "Parmesan is $1 off in Aisle 4. Want it?",
                  f"before={before and before['text']!r}, confirm→row {time.perf_counter() - t:.2f}s")
    finally:
        for cid in reversed(undo_ids):            # newest first, so each undo sees its own "after"
            store.undo(cid)
        for table in ("transcript", "receipts", "cart_events"):
            store.q(f"delete from {table} where cart_id = %s", [cart])
        store.q("delete from carts where cart_id = %s", [cart])

    end = catalog_shape(store)
    changed = sorted(k for k in start.keys() | end.keys() if start.get(k) != end.get(k))
    check("this run left prices, aisles, deals and products as it found them", not changed,
          f"changed: {changed}" if changed else "stock not compared: shared with other teams' checkouts")
    if args.reset:
        subprocess.run(RESET, check=True, capture_output=True)
        print("  reset-demo done")
        seed = json.loads(STORE_JSON.read_text())
        live = {r["id"]: r for r in store.catalog()}
        drift = [q["id"] for q in seed["products"]
                 if q["id"] not in live or float(live[q["id"]]["price"]) != q["price"]
                 or live[q["id"]]["section"] != q["section"] or live[q["id"]]["stock"] != q["stock"]]
        running = {r["deal_id"] for r in live.values() if r["deal_id"]}
        check("after reset-demo the catalog matches data/store.json (stock included)",
              not drift and running == {d["id"] for d in seed["deals"]} and len(live) == len(seed["products"]),
              f"drift={drift}, deals={sorted(running)}" if drift else "")

    print("\n════ latency per prompt (owner message → reply with staged preview)")
    for k, v in latencies.items():
        print(f"  {k:16} {v}")
    failed = [r for r in results if not r[1]]
    print("PASS" if not failed else f"FAIL ({len(failed)} checks)")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
