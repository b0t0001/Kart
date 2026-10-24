#!/usr/bin/env bash
# Deploy the Supabase Edge Functions (P7 voice-token) and push their secrets.
# Reads the repo .env: SUPABASE_ACCESS_TOKEN, SUPABASE_PROJECT_REF, CARTESIA_API_KEY,
# CARTESIA_AGENT_ID (a placeholder is fine until the Line agent exists).
set -euo pipefail

BACKEND="$(cd "$(dirname "$0")" && pwd)"
ENV_FILE="${KART_ENV_FILE:-$BACKEND/../.env}"
set -a; source "$ENV_FILE"; set +a
: "${SUPABASE_ACCESS_TOKEN:?add SUPABASE_ACCESS_TOKEN to .env}"
: "${SUPABASE_PROJECT_REF:?add SUPABASE_PROJECT_REF to .env}"
: "${CARTESIA_API_KEY:?add CARTESIA_API_KEY to .env}"

# Only these two go to Supabase, through a private temp file (not argv, not the repo).
secrets="$(mktemp)"; trap 'rm -f "$secrets"' EXIT
chmod 600 "$secrets"
printf 'CARTESIA_API_KEY=%s\nCARTESIA_AGENT_ID=%s\n' "$CARTESIA_API_KEY" "${CARTESIA_AGENT_ID:-pending}" > "$secrets"
supabase secrets set --project-ref "$SUPABASE_PROJECT_REF" --env-file "$secrets"

# --use-api bundles server-side, so the deploy works without Docker running
supabase functions deploy voice-token --project-ref "$SUPABASE_PROJECT_REF" --workdir "$BACKEND" --use-api "$@"
