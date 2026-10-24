"""Flag-off proof for a beta: one fixed trip, every RPC result printed as stable JSON.

Run it against two schemas and diff the outputs; with the beta's flag off they must match.
Volatile values (ids, uuids, timestamps, trip time) and the member-memory columns are dropped.

  KART_TEST_PG=postgresql://postgres@localhost:54329/postgres \\
    backend/.venv/bin/python backend/tests/snapshot_trip.py --backend <checkout>/backend --db kart_snap_x > out.json

Not collected by pytest (no test_ prefix).
"""

from __future__ import annotations

import argparse
import importlib
import json
import os
import sys

DROP = {"id", "trip_id", "event_id", "duration_s", "at", "member_id", "member_rev", "demo_date"}

TACOS_FOR_4 = [
    {"product_id": "mission-tortillas", "reason": "tacos", "qty": 1},
    {"product_id": "avocados", "reason": "guac", "qty": 1},
    {"product_id": "tostitos-salsa", "reason": "salsa", "qty": 1},
    {"product_id": "ground-beef", "reason": "tacos", "qty": 2},
]


def stable(value):
    if isinstance(value, dict):
        return {k: stable(v) for k, v in sorted(value.items()) if k not in DROP and not k.endswith("_at")}
    if isinstance(value, list):
        return [stable(v) for v in value]
    return value


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--backend", required=True, help="the backend/ directory whose db/ migrations to apply")
    ap.add_argument("--db", required=True, help="a scratch database name (dropped and recreated)")
    args = ap.parse_args()

    sys.path.insert(0, os.path.abspath(args.backend))
    kartdb = importlib.import_module("kartdb")
    import psycopg

    admin_url = os.environ.get("KART_TEST_PG", "postgresql://postgres@localhost:54329/postgres")
    with psycopg.connect(admin_url, autocommit=True) as admin:
        admin.execute(f"drop database if exists {args.db} with (force)")
        admin.execute(f"create database {args.db}")
    url = admin_url.rsplit("/", 1)[0] + "/" + args.db

    with kartdb.connect(url) as conn:
        kartdb.apply_migrations(conn, local=True)
        kartdb.seed(conn)

        def call(fn, **params):
            return stable(kartdb.rpc(conn, fn, p_cart_id="snap", **params))

        def event(kind, pid):
            return call("apply_cart_event", p_type=kind, p_product_id=pid, p_confidence=0.9, p_source="vision",
                        p_label=pid)

        steps = [("reset_cart", call("reset_cart")), ("set_plan", call("set_plan", p_plan=TACOS_FOR_4))]
        for pid in ("mission-tortillas", "avocados", "avocados", "barilla-spaghetti", "tostitos-salsa", "ground-beef"):
            steps.append((f"added {pid}", event("added", pid)))
        steps.append(("removed avocados", event("removed", "avocados")))
        steps.append(("set_location A9", call("set_location", p_section="A9")))
        steps.append(("checkout status", call("set_cart_status", p_status="checkout")))
        steps.append(("checkout", call("checkout")))
        print(json.dumps(steps, indent=1, sort_keys=True, default=str))


if __name__ == "__main__":
    main()
