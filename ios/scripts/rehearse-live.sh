#!/bin/bash
# The demo against the local Supabase (backend/docs/LOCAL_SUPABASE.md): resets the demo without the parmesan
# deal, runs LiveRehearsalTests, and plays the store owner (creates the deal through the merchant path when asked).
# Screenshots land in build/shots/live/.
set -euo pipefail
cd "$(dirname "$0")/.."
ROOT=$(cd .. && pwd)
SHOTS="$PWD/build/shots/live"
rm -rf "$SHOTS" && mkdir -p "$SHOTS"
scripts/make-config.sh >/dev/null
"$ROOT/backend/.venv/bin/python" "$ROOT/backend/db.py" reset-demo --cart ipad-live --without-deal d-parm-3off >/dev/null
( while sleep 0.5; do
    if [ -f "$SHOTS/request-parm-deal" ]; then
      rm -f "$SHOTS/request-parm-deal"
      "$ROOT/backend/.venv/bin/python" "$ROOT/backend/cart.py" deal kirkland-parmesan 3 >"$SHOTS/owner.log" 2>&1
    fi
  done ) &
OWNER=$!
trap 'kill $OWNER 2>/dev/null || true' EXIT
xcodegen generate >/dev/null
TEST_RUNNER_SHOT_DIR="$SHOTS" xcodebuild test -project Kart.xcodeproj -scheme Kart \
  -destination "platform=iOS Simulator,name=iPad Pro 13-inch (M5)" -derivedDataPath build \
  -only-testing:KartUITests/LiveRehearsalTests -quiet
scripts/landscape-png.sh "$SHOTS"/*.png
"$ROOT/backend/.venv/bin/python" "$ROOT/backend/db.py" reset-demo --cart ipad-live >/dev/null    # catalog restored, as the backend expects it
ls "$SHOTS"
