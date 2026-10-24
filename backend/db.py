"""KART backend database tool.

  python backend/db.py apply [--fresh] [--local]   run backend/db/NN_*.sql in order
  python backend/db.py seed                        load data/store.json into the catalog
  python backend/db.py sync-catalog [--with-stock] update the catalog from store.json IN PLACE (no deletes,
                                                   carts and change log untouched; safe on the shared project)
  python backend/db.py layout <name>                 switch to data/layouts/<name>.json in place (one undoable
                                                   merchant change; carts and deals untouched)
  python backend/db.py layout --show               the active layout
  python backend/db.py reset-demo [--cart 7] [--without-deal d-parm-3off]
                                                   re-seed the catalog, clear the merchant change log,
                                                   reset_cart, status idle (between demo runs)
  python backend/db.py show [--cart 7]             print the cart row

Connects with SUPABASE_DB_URL from the repo .env (or --db-url).
--local also applies db/local_supabase_shim.sql, for a plain Postgres (never on Supabase).
"""

from __future__ import annotations

import argparse
import json

import kartdb


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("command", choices=["apply", "seed", "sync-catalog", "layout", "reset-demo", "show"])
    ap.add_argument("name", nargs="?", help="layout: data/layouts/<name>.json")
    ap.add_argument("--db-url")
    ap.add_argument("--fresh", action="store_true", help="drop our tables first (loses carts and history)")
    ap.add_argument("--local", action="store_true", help="plain Postgres: create Supabase's roles/publication first")
    ap.add_argument("--cart", default="7")
    ap.add_argument("--with-stock", action="store_true", help="sync-catalog: also set stock from the file")
    ap.add_argument("--show", action="store_true", help="layout: print the active layout")
    ap.add_argument("--force", action="store_true", help="layout: apply a placeholder layout to a hosted database")
    ap.add_argument("--without-deal", action="append", default=[], metavar="DEAL_ID",
                    help="reset-demo: end this seeded deal, e.g. so the owner can create it live in the pitch")
    args = ap.parse_args()

    kartdb.load_env()
    with kartdb.connect(kartdb.db_url(args.db_url)) as conn:
        if args.command == "apply":
            for name in kartdb.apply_migrations(conn, fresh=args.fresh, local=args.local):
                print("applied", name)
            if kartdb.catalog_is_empty(conn):  # first setup; later applies keep merchant edits
                print("seeded", kartdb.seed(conn))
        elif args.command == "seed":
            print("seeded", kartdb.seed(conn))
        elif args.command == "sync-catalog":
            print("synced", kartdb.sync_catalog(conn, with_stock=args.with_stock))
        elif args.command == "layout" and (args.show or not args.name):
            snap = conn.execute("select layout_snapshot()").fetchone()[0]
            placed = dict(conn.execute("select section, count(*) from products where active group by section").fetchall())
            print(f"active layout: {snap['name']} ({snap['store']['name']})")
            for s in snap["sections"]:
                print(f"  {s['id']:4} {s['name']:34} x={s['x']:<3} {placed.get(s['id'], 0)} products")
        elif args.command == "layout":
            path = kartdb.LAYOUTS / f"{args.name}.json"
            if not path.exists():
                raise SystemExit(f"no layout {path} (have: {', '.join(p.stem for p in kartdb.LAYOUTS.glob('*.json'))})")
            hosted = "supabase.co" in kartdb.db_url(args.db_url)
            if json.loads(path.read_text()).get("placeholder") and hosted and not args.force:
                raise SystemExit(f"{args.name} still has PLACEHOLDER aisles; not applying it to the hosted project "
                                 "(fill in the real aisles and set placeholder: false, or pass --force)")
            out = kartdb.apply_layout(conn, args.name)
            print(f"applied change #{out['change']}: {out['summary']} (Undo it in the merchant console)")
        elif args.command == "reset-demo":
            print("seeded", kartdb.seed(conn))
            conn.execute("delete from merchant_changes")  # the log described the catalog we just replaced
            for deal in args.without_deal:
                conn.execute("update deals set active = false where id = %s", [deal])
                print("ended deal", deal)
            conn.execute("select reset_cart(%s)", [args.cart])
            conn.execute("select set_cart_status(%s, 'idle')", [args.cart])  # iPad back on Welcome
            print(f"cart {args.cart} reset (status idle)")
        if args.command in ("reset-demo", "show"):
            row = conn.execute("select to_jsonb(c) from carts c where cart_id = %s", [args.cart]).fetchone()
            print(json.dumps(row[0] if row else None, indent=2, default=str))


if __name__ == "__main__":
    main()
