#!/usr/bin/env bash
# Morning go-live: point everything at the HOSTED Supabase project in one command.
#
#   backend/go_live.sh            # after the hosted values are in /Users/dylan/Documents/GitHub/kart/.env
#
# Needs in .env: SUPABASE_URL, SUPABASE_ANON_KEY, SUPABASE_SERVICE_ROLE_KEY, SUPABASE_DB_URL,
# SUPABASE_PROJECT_REF, SUPABASE_ACCESS_TOKEN, CARTESIA_API_KEY (CARTESIA_AGENT_ID optional).
# Steps: migrations → seed → Edge Function + secrets → demo simulation over REST (anon key) →
# end-to-end test → voice-token check → demo reset. Prints PASS/FAIL per step and overall.
set -uo pipefail

BACKEND="$(cd "$(dirname "$0")" && pwd)"
REPO="$(dirname "$BACKEND")"
ENV_FILE="${KART_ENV_FILE:-$REPO/.env}"
PY="$BACKEND/.venv/bin/python"

[ -f "$ENV_FILE" ] || { echo "FAIL: no $ENV_FILE"; exit 1; }
set -a; source "$ENV_FILE"; set +a

if [[ "${SUPABASE_URL:-}" == *127.0.0.1* || "${SUPABASE_URL:-}" == *localhost* ]] && [[ "${1:-}" != "--allow-local" ]]; then
  echo "FAIL: SUPABASE_URL in .env is still the LOCAL stack ($SUPABASE_URL)."
  echo "      Put the hosted project's values in .env first (or pass --allow-local to rehearse)."
  exit 1
fi
for v in SUPABASE_URL SUPABASE_ANON_KEY SUPABASE_DB_URL; do
  [ -n "${!v:-}" ] || { echo "FAIL: $v is not set in .env"; exit 1; }
done

if [ ! -x "$PY" ]; then
  python3 -m venv "$BACKEND/.venv" && "$PY" -m pip install -q -r "$BACKEND/requirements.txt"
fi

results=()
step() {  # step "name" command...
  local name="$1"; shift
  echo; echo "── $name"
  if "$@"; then results+=("PASS  $name"); else results+=("FAIL  $name"); fi
}

voice_token_check() {
  local out code
  out="$(curl -sS -w '\n%{http_code}' -X POST "$SUPABASE_URL/functions/v1/voice-token" \
         -H "Authorization: Bearer $SUPABASE_ANON_KEY" -H "apikey: $SUPABASE_ANON_KEY" \
         -H "Content-Type: application/json" -d "{\"cart_id\": \"${CART_ID:-7}\"}")"
  code="$(tail -n1 <<<"$out")"
  echo "HTTP $code $(head -n1 <<<"$out" | sed -E 's/"token":"[^"]*"/"token":"…"/')"
  [ "$code" = "200" ]
}

step "migrations (db/*.sql)"        "$PY" "$BACKEND/db.py" apply
step "seed catalog + reset cart"    "$PY" "$BACKEND/db.py" reset-demo
if [ -n "${SUPABASE_ACCESS_TOKEN:-}" ] && [ -n "${SUPABASE_PROJECT_REF:-}" ] && [ -n "${CARTESIA_API_KEY:-}" ]; then
  step "voice-token deploy + secrets" "$BACKEND/deploy_functions.sh"
  step "voice-token returns a token"  voice_token_check
else
  results+=("SKIP  voice-token (needs SUPABASE_ACCESS_TOKEN, SUPABASE_PROJECT_REF, CARTESIA_API_KEY)")
fi
# these two check out carts on purpose (that's the flow being verified); stock is restored below
step "demo simulation over REST"    "$PY" "$BACKEND/simulate_demo.py" --via rest --allow-hosted
step "end-to-end test (REST + realtime + merchant)" "$PY" -m pytest -q "$BACKEND/e2e" --allow-hosted
step "demo reset (catalog, cart ${CART_ID:-7} idle)" "$PY" "$BACKEND/db.py" reset-demo
step "stock restored from store.json"  "$PY" "$BACKEND/db.py" sync-catalog --with-stock

echo; echo "════ go-live summary"
fail=0
for r in "${results[@]}"; do echo "  $r"; [[ "$r" == FAIL* ]] && fail=1; done
if [ "$fail" = 0 ]; then echo "PASS"; else echo "FAIL"; fi
exit "$fail"
