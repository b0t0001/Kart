# KART merchant console

The store owner talks to the store instead of editing a backend: "move parmesan to aisle 6",
"spaghetti $1 off through Sunday", "we're out of Rao's", "add fresh basil, $2.49, produce".

```
agent.py          Claude (claude-opus-5-5) with typed tools; Store = catalog + change log over Postgres
server.py         FastAPI: the console page + /api (chat, state, confirm / cancel / undo)
static/index.html chat · live cart · live catalog · change log (mic button where the browser supports it)
tests/            pytest: staging, apply/undo, the agent loop with a scripted fake Claude, the API
```

## Why it's safe to let Claude edit the store

- **Typed tools, never SQL.** `search_products`, `list_deals`, `recent_changes` (read) and `update_price`,
  `move_product`, `set_stock`, `add_product`, `create_deal`, `end_deal`, `undo_change` (write), with
  strict JSON schemas. Bad requests (unknown product, $5 off a $1.49 item, a date in the past) come
  back to Claude as tool errors it can fix or ask about.
- **Claude can only propose.** Write tools validate and *stage* a pending change with a plain-English
  preview, e.g. "Change the price of Parmesan from $12.99 to $11.99. With its $3 off deal, shoppers pay
  $8.99. 1 cart with it now gets the lower price right away." No tool applies anything; only the
  owner's **Confirm** click does (`merchant_apply`, in `backend/db/05_merchant.sql`). That's enforced in
  code, not in the prompt.
- **Every change is logged and undoable.** `merchant_changes` keeps what the owner said, the preview
  they confirmed, and the catalog row before and after. **Undo** restores it, and refuses if something
  changed it since (so it never clobbers a newer edit). A preview that went stale before Confirm is
  refused too.
- **Live to the carts.** Catalog writes fire the cart recompute, so a confirmed deal shows on the iPad
  within a second: new prices on items already in carts (price drops only, CONTRACT P10), and the
  moment-of-decision suggestion switches to a deal the store just created.

## Run

```bash
python3 -m venv merchant/.venv && merchant/.venv/bin/pip install -r merchant/requirements.txt
merchant/.venv/bin/python merchant/server.py          # http://localhost:8090, uses SUPABASE_DB_URL + ANTHROPIC_API_KEY from .env
merchant/.venv/bin/python -m pytest merchant/tests    # needs the local test Postgres (see backend/README.md)
```

Demo reset: `backend/.venv/bin/python backend/db.py reset-demo` restores the catalog and clears the
change log. Add `--without-deal d-parm-3off` to have the owner create the Parmesan deal live in the
pitch (a cart holding spaghetti then switches its suggestion to it).

Env (names in `merchant/.env.example`): `SUPABASE_DB_URL`, `ANTHROPIC_API_KEY`, `CART_ID` (the cart shown
in the console), and optional `MERCHANT_MODEL`, `MERCHANT_EFFORT` (default `low`, for snappy previews),
`STORE_TZ` (default `America/Los_Angeles`).

The Claude request uses adaptive thinking (always on for Opus 5.5) and the server-side refusal fallback
(`fallbacks: "default"`), so a declined request is retried on another model instead of failing.
