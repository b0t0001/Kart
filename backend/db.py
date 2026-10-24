"""KART backend database tool.

  python backend/db.py apply [--fresh] [--local]   run backend/db/NN_*.sql in order
  python backend/db.py seed                        load data/store.json into the catalog
  python backend/db.py reset-demo [--cart 7]       re-seed the catalog + reset_cart (between demo runs)
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
    ap.add_argument("command", choices=["apply", "seed", "reset-demo", "show"])
    ap.add_argument("--db-url")
    ap.add_argument("--fresh", action="store_true", help="drop our tables first (loses carts and history)")
    ap.add_argument("--local", action="store_true", help="plain Postgres: create Supabase's roles/publication first")
    ap.add_argument("--cart", default="7")
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
        elif args.command == "reset-demo":
            print("seeded", kartdb.seed(conn))
            conn.execute("select reset_cart(%s)", [args.cart])
            print(f"cart {args.cart} reset")
        if args.command in ("reset-demo", "show"):
            row = conn.execute("select to_jsonb(c) from carts c where cart_id = %s", [args.cart]).fetchone()
            print(json.dumps(row[0] if row else None, indent=2, default=str))


if __name__ == "__main__":
    main()
