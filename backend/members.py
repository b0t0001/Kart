"""KART member memory (CONTRACT v0.14, BETA): the demo member.

  python backend/members.py seed [--member 1029] [--name Dylan] [--household 4] [--today YYYY-MM-DD] [--with-party]
        rebuild one member: ten weeks of trips ending a week before today and a marinara preference.
        No party: in the demo Dylan tells Kart about Leo's party live (Act 1). --with-party adds it
        (next Saturday, pasta for 12) for rehearsals that skip Act 1. Touches nothing else. Run it right
        before judging (backend/pre_judging.sh --members): the history is relative to the run.
  python backend/members.py show <member_id> [--cart 7]
        print the member's profile, as the iPad and the agent see it

Connects with SUPABASE_DB_URL from the repo .env (or --db-url).
"""

from __future__ import annotations

import argparse
import json
from datetime import date, timedelta

import psycopg

import kartdb

TZ = "America/Los_Angeles"

# The usual-day basket (taco night) plus the weekly staples, with the weeks (0 = ten weeks ago) each
# line was skipped. Fixed, not random, so the demo's picks are always the same: milk is the most
# regular (due), tortillas the next (your usual), and last week's trip had everything.
USUAL_DAY = [("mission-tortillas", 1, {2}), ("ground-beef", 2, {1, 5}), ("tillamook-mexican-cheese", 1, {3, 6}),
             ("tostitos-salsa", 1, {4}), ("tostitos-chips", 1, {2}), ("avocados", 1, {1, 4, 7}),
             ("daisy-sour-cream", 1, {0, 3, 5, 8}), ("whole-milk", 1, set()), ("bananas", 1, {3, 6})]
# Every other week, three days after the usual-day trip, alternating.
TOP_UPS = [[("barilla-spaghetti", 1), ("rao-marinara", 1), ("large-eggs", 1)],
           [("french-baguette", 1), ("large-eggs", 1)]]
PARTY = ("Leo's soccer team party, pasta for 12",
         [("barilla-spaghetti", 3), ("rao-marinara", 2)])        # the demo's pasta; the Parmesan is the deal card's


def store_today(conn: psycopg.Connection) -> date:
    return conn.execute(f"select (now() at time zone '{TZ}')::date").fetchone()[0]


def seed_member(conn: psycopg.Connection, member_id: str, name: str, household: int, today: date,
                with_party: bool = False) -> dict:
    """Deletes and rebuilds one member relative to `today`; returns what it made."""
    catalog = {pid: price for pid, price in conn.execute("select id, price from products")}
    short = dict(conn.execute("select id, coalesce(short_name, name) from products"))
    skipped: set[str] = set()

    trips: list[tuple[date, list[tuple[str, int]]]] = []
    for week, offset in enumerate(range(70, 0, -7)):            # ten usual-day trips, the last a week ago
        day = today - timedelta(days=offset)
        lines = [(pid, qty) for pid, qty, skipped_weeks in USUAL_DAY if week not in skipped_weeks]
        if offset in (70, 35):                                  # paper towels every five weeks
            lines.append(("kirkland-paper-towels", 1))
        trips.append((day, lines))
        if week % 2 == 0:
            trips.append((day + timedelta(days=3), list(TOP_UPS[(week // 2) % 2])))

    conn.execute("delete from members where member_id = %s", [member_id])
    conn.execute(f"insert into members (member_id, name, household, created_at) "
                 f"values (%s, %s, %s, (%s::date + time '10:00') at time zone '{TZ}')",
                 [member_id, name, household, today - timedelta(days=71)])
    purchases = 0
    for day, lines in trips:
        for pid, qty in lines:
            if pid not in catalog:                             # the catalog is changing for the demo meals
                skipped.add(pid)
                continue
            conn.execute(f"insert into member_purchases (member_id, product_id, qty, price, bought_at, source) "
                         f"values (%s, %s, %s, %s, (%s::date + time '11:00') at time zone '{TZ}', 'seed')",
                         [member_id, pid, qty, catalog[pid], day])
            purchases += 1

    party_date = None
    if with_party:                                              # next Saturday: the first one after today
        party_date = today + timedelta(days=(5 - today.weekday()) % 7 or 7)
        items = [{"product_id": pid, "qty": qty} for pid, qty in PARTY[1] if pid in catalog]
        skipped |= {pid for pid, _ in PARTY[1] if pid not in catalog}
        conn.execute("insert into member_memories (member_id, kind, text, event_date, items) "
                     "values (%s, 'event', %s, %s, %s::jsonb)", [member_id, PARTY[0], party_date, json.dumps(items)])
    if "rao-marinara" in short:
        conn.execute("insert into member_memories (member_id, kind, text) values (%s, 'preference', %s)",
                     [member_id, f"Likes the {short['rao-marinara']} here"])
    return {"member_id": member_id, "trips": len(trips), "purchases": purchases,
            "event_date": party_date and party_date.isoformat(), "skipped": sorted(skipped)}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("command", choices=["seed", "show"])
    ap.add_argument("member_id", nargs="?")
    ap.add_argument("--member", default="1029")
    ap.add_argument("--name", default="Dylan")
    ap.add_argument("--household", type=int, default=4)
    ap.add_argument("--today", type=date.fromisoformat, help="seed relative to this day (default: the store's today)")
    ap.add_argument("--cart", help="show: use this cart's demo date and list")
    ap.add_argument("--with-party", action="store_true", help="seed: add Leo's party (rehearsals that skip Act 1)")
    ap.add_argument("--db-url")
    args = ap.parse_args()
    member_id = args.member_id or args.member

    kartdb.load_env()
    with kartdb.connect(kartdb.db_url(args.db_url)) as conn:
        if args.command == "seed":
            today = args.today or store_today(conn)
            made = seed_member(conn, member_id, args.name, args.household, today, with_party=args.with_party)
            print(f"seeded member {member_id} ({args.name}): {made['trips']} trips, {made['purchases']} purchases")
            if made["event_date"]:
                print(f"Leo's soccer team party: {made['event_date']} (next Saturday)")
            else:
                print("No party yet: Dylan tells Kart about it in Act 1 (--with-party adds it for rehearsals).")
            if made["skipped"]:
                print("skipped (not in the catalog):", ", ".join(made["skipped"]))
        else:
            row = conn.execute("select member_profile(%s, %s)", [member_id, args.cart]).fetchone()
            print(json.dumps(row[0], indent=2))


if __name__ == "__main__":
    main()
