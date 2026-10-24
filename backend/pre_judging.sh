#!/usr/bin/env bash
# Pre-judging, demo operator only: the catalog with the real counts, then a clean demo state.
#
#   backend/pre_judging.sh             # asks for confirmation
#   backend/pre_judging.sh --members   # also seed the member-memory beta (if it ships)
#
# In order (docs/DEMO_PLAN.md):
#   1. db.py sync-catalog --with-stock: store.json's names, prices, deals AND stock (= counts bought).
#   2. db.py reset-demo: re-seeds the catalog (stock included, so step 1 is belt and braces), clears
#      the merchant change log, and resets cart 7 to idle (iPad on Welcome; the Pi clears its memory).
#   3. db.py judging-stock: stock = the props actually bought (data/judging_stock.json, 1 each). A paid
#      trip sells them out, so run this script before EACH judge group.
#   4. with --members: members.py seed, and cart 7's member_memory switch ON.
# It ends with a one-line summary (stock of the demo props, flag states for cart 7) to eyeball.
# It affects EVERY team on the database in .env, so run it once, right before judging.
set -euo pipefail

BACKEND="$(cd "$(dirname "$0")" && pwd)"
PY="$BACKEND/.venv/bin/python"
MEMBERS=0
YES=0
for arg in "$@"; do
  case "$arg" in
    --members) MEMBERS=1 ;;
    --yes) YES=1 ;;
    *) echo "unknown option: $arg"; exit 2 ;;
  esac
done
if [ "$MEMBERS" = 1 ] && [ ! -f "$BACKEND/members.py" ]; then
  echo "--members: backend/members.py isn't here (the member-memory branch isn't merged)."; exit 1
fi

url="$(set -a; source "${KART_ENV_FILE:-$BACKEND/../.env}"; echo "${SUPABASE_URL:-?}")"
echo "Pre-judging reset against $url: real stock counts, demo reset (cart 7, change log)$([ "$MEMBERS" = 1 ] && echo ', member seed')."
if [ "$YES" != 1 ]; then
  read -r -p "This resets the demo for every team. Type 'judging' to continue: " answer
  [ "$answer" = "judging" ] || { echo "Cancelled."; exit 1; }
fi

echo "── 1/4 sync-catalog --with-stock";  "$PY" "$BACKEND/db.py" sync-catalog --with-stock
echo "── 2/4 reset-demo";                  "$PY" "$BACKEND/db.py" reset-demo | head -2
echo "── 3/4 judging stock (props bought)"; "$PY" "$BACKEND/db.py" judging-stock
if [ "$MEMBERS" = 1 ]; then
  echo "── 4/4 members.py seed + cart ${CART_ID:-7} member_memory on"
  "$PY" "$BACKEND/members.py" seed
  "$PY" "$BACKEND/cart.py" feature member_memory on --cart "${CART_ID:-7}"
else
  echo "── 4/4 member seed skipped (pass --members if the beta ships)"
fi
echo; "$PY" "$BACKEND/db.py" judging-summary --cart "${CART_ID:-7}"
echo "Ready for judging."
