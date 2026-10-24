#!/bin/bash
# Deploy Kart's voice agent to Cartesia Line. Run it yourself: it installs the Cartesia CLI (accepting Cartesia's
# terms), signs in with your Cartesia API key, creates the agent, gives it only the four values it needs from the
# repo .env (never the service-role key, and nothing is printed), deploys, and saves the agent id in .env.
set -euo pipefail
cd "$(dirname "$0")/.."
ENV_FILE="$(cd .. && pwd)/.env"
value() { grep -E "^$1=" "$ENV_FILE" | tail -1 | cut -d= -f2- | sed -e 's/^"//' -e 's/"$//'; }

if ! command -v cartesia >/dev/null && [ ! -x "$HOME/.cartesia/bin/cartesia" ]; then
  read -r -p "Install the Cartesia CLI (curl -fsSL https://cartesia.sh | sh)? This accepts Cartesia's terms. [y/N] " ok
  [ "$ok" = "y" ] || { echo "Stopped: no CLI."; exit 1; }
  curl -fsSL https://cartesia.sh | sh
fi
export PATH="$HOME/.cartesia/bin:$HOME/.local/bin:$PATH"
command -v cartesia >/dev/null || { echo "Installed, but 'cartesia' isn't on PATH: open a new terminal and rerun."; exit 1; }

echo; echo "1/4 Sign in: paste your Cartesia API key (CARTESIA_API_KEY in .env, or play.cartesia.ai/keys) when asked."
cartesia auth login

echo; echo "2/4 Create the agent: choose a NEW agent, name it kart, in your organization."
cartesia init

echo; echo "3/4 Agent settings: ANTHROPIC_API_KEY, SUPABASE_URL, SUPABASE_ANON_KEY, CART_ID (values not shown)."
for k in ANTHROPIC_API_KEY SUPABASE_URL SUPABASE_ANON_KEY; do
  [ -n "$(value $k)" ] || { echo "Stopped: $k is empty in .env."; exit 1; }
done
SETTINGS=$(mktemp); chmod 600 "$SETTINGS"; trap 'rm -f "$SETTINGS"' EXIT
{ echo "ANTHROPIC_API_KEY=$(value ANTHROPIC_API_KEY)"; echo "SUPABASE_URL=$(value SUPABASE_URL)"
  echo "SUPABASE_ANON_KEY=$(value SUPABASE_ANON_KEY)"; echo "CART_ID=7"; } > "$SETTINGS"
cartesia env set --from "$SETTINGS" >/dev/null && echo "set."

echo; echo "4/4 Deploy (if Cartesia says this needs a paid plan, stop here and tell Claude)."
cartesia deploy
echo; cartesia status
echo
read -r -p "Paste the agent id shown above: " AGENT_ID
[ -n "$AGENT_ID" ] || { echo "No id; put it in .env as CARTESIA_AGENT_ID yourself."; exit 1; }
if grep -qE '^CARTESIA_AGENT_ID=' "$ENV_FILE"; then
  sed -i '' "s|^CARTESIA_AGENT_ID=.*|CARTESIA_AGENT_ID=$AGENT_ID|" "$ENV_FILE"
else
  echo "CARTESIA_AGENT_ID=$AGENT_ID" >> "$ENV_FILE"
fi
echo "Saved CARTESIA_AGENT_ID in .env. Tell Claude it's deployed."
