#!/bin/bash
# The demo against the live backend in the repo .env (hosted or local) on its own cart, ipad-live. It resets only
# that cart, before and after (even on failure), and never touches the store's catalog, deals or merchant log:
# only the demo operator runs `db.py reset-demo` (contract §3a). The Parmesan card comes from the store's seeded
# deal; the live merchant beat is the backend's own smoke test. Screenshots land in build/shots/live/.
set -euo pipefail
cd "$(dirname "$0")/.."
ROOT=$(cd .. && pwd)
SHOTS="$PWD/build/shots/live"
cart() { "$ROOT/backend/.venv/bin/python" "$ROOT/backend/cart.py" "$@" --cart ipad-live >/dev/null; }
idle() { cart reset && cart status idle; }    # a fresh trip, then back to Welcome
rm -rf "$SHOTS" && mkdir -p "$SHOTS"
scripts/make-config.sh >/dev/null
idle
trap idle EXIT
xcodegen generate >/dev/null
TEST_RUNNER_SHOT_DIR="$SHOTS" xcodebuild test -project Kart.xcodeproj -scheme Kart \
  -destination "platform=iOS Simulator,name=iPad Pro 13-inch (M5)" -derivedDataPath build \
  -only-testing:KartUITests/LiveRehearsalTests -quiet
scripts/landscape-png.sh "$SHOTS"/*.png
ls "$SHOTS"
