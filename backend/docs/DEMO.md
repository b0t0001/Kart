# KART demo runbook: backend and merchant console

All commands run from the repo root. `P=backend/.venv/bin/python` is shorthand below.

## Once, before judging

1. **The database.** Use the hosted project if `backend/go_live.sh` printed PASS. If the venue Wi-Fi or
   the hosted project fails, use the local stack (see "If something fails" below).
2. **The merchant console** on the laptop facing the judges:
   `merchant/.venv/bin/python merchant/server.py`, then open http://localhost:8090.
   It needs `ANTHROPIC_API_KEY` in `.env`. Try one change and Confirm it, then reset (step 3).
3. **Reset.** `$P backend/db.py reset-demo --without-deal d-parm-3off`
   - This restores the catalog from `data/store.json`, clears the merchant change log, and sets cart 7
     to idle. The iPad goes to Welcome, and the Pi clears its memory because `trip_id` changes.
   - `--without-deal d-parm-3off` starts with no Parmesan deal, so the owner can create it live
     (beat 4). Drop the flag to keep the seeded deal.

Run step 3 between every judge group. Store insights keep accumulating across runs (they're real
trips), and the reset doesn't clear them.

## The flow, with the merchant beat (about 2 minutes)

| # | Who | What happens | What you see |
|---|---|---|---|
| 1 | Judge | Taps **Start** on the iPad | `reset_cart`: status shopping, new trip |
| 2 | Judge | "I'm making a pasta dinner for my family" | `set_plan`: the agent lists the basics (spaghetti, sauce, maybe bread). Next stop shows the first aisle on the route from the entrance |
| 3 | Judge | Drops the **spaghetti** in the cart | Total $1.99. A deal card appears only for something that goes with it and is **not** already on the list |
| 4 | Teammate (owner) | Says or types in the console: **"Parmesan $3 off through Sunday"** → reads the preview → **Confirm** | Within about a second the cart's card switches to **"Parmesan is $3 off in Aisle 4. Want it?"** and the console's catalog row flashes. *Line:* "the store just pushed a deal to the shopper at the moment of decision, and Claude couldn't change anything without a human Confirm." |
| 4b | Judge | Says **"Yes"** | Parmesan goes on the list with "$3 off" on its row. The card is consumed, so the next eligible deal, if there is one, can pop right away |
| 5 | Judge | Drops the **parmesan** | $9.99 with "$3 off" and a strikethrough price; "saved $3.00" |
| 6 | Judge | Takes something back out | Total drops |
| 7 | Judge | "I'm done" → **Pay** | Receipt: "You saved $3.00 · N-minute trip". In the console, Store insights adds a trip and the Parmesan bar fills |

**Cards never show for items already on the shopping list.** If the voice agent puts Parmesan on
the list in beat 2, the owner's new deal appears on that list row ("$3 off") instead of as a card.
For the card moment, keep "pasta dinner" planned as the basics; `cart.py plan pasta` does exactly
that.

Optional merchant beats, if a judge asks:
- **"We're out of Rao's"** → Confirm. The shopping list shows it out of stock, and Kart stops suggesting it.
- **"Move parmesan to aisle 6"** → Confirm. The cart's Next stop changes.
- **Undo** any change from the change log.
- **"How are the deals doing?"** Claude answers from the anonymous insights.

## If something fails

| Symptom | Do this |
|---|---|
| The cameras miss an item, or the cart shows the wrong item | iPad: fix it on the confirm card. Laptop: `$P backend/cart.py add kirkland-parmesan` (or `remove …`). It goes through the same RPC, so the iPad updates normally |
| The merchant chat is slow, errors, or has no API key | `$P backend/cart.py deal kirkland-parmesan 3`, the same beat without Claude. It's logged as a merchant change and can be undone in the console. Ending a deal: `$P backend/cart.py end-deal <deal_id>` |
| Checkout says "unresolved items" | An unidentified item is waiting on its confirm card. Tap Yes or Remove there |
| The suggestion card doesn't appear | Each deal is offered once per trip, only while its product is in stock and not already in the cart **or on the list**. Run `$P backend/cart.py reset` (or reset-demo) and repeat |
| Prices look odd after the owner's edits | `$P backend/db.py reset-demo` |
| You want to see the cart from the laptop | `$P backend/cart.py show`, or the console's "Cart on the floor" panel |
| Hosted Supabase or the venue Wi-Fi is down | Switch to the local stack: `colima start`, then `supabase start --workdir backend`, then `$P backend/db.py apply`. Put the local values in `.env` (see `backend/docs/LOCAL_SUPABASE.md`), restart the console, and point the iPad and Pi at `http://<laptop LAN IP>:54321` |
| The voice token fails (502) | Check that `CARTESIA_API_KEY` is set as a function secret (`backend/deploy_functions.sh`). The iPad's mock voice session is the fallback |

## Health check (about 30 seconds)

```bash
backend/.venv/bin/python backend/simulate_demo.py     # the whole flow over REST with the anon key
backend/.venv/bin/python -m pytest -q backend/e2e     # REST + realtime + the merchant beat
backend/.venv/bin/python backend/db.py reset-demo     # afterwards: clean slate
```
