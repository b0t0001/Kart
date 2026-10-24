#!/bin/bash
# Screenshot demo scenarios in the iPad simulator (run scripts/landscape.sh once per boot first).
# usage: scripts/shoot.sh <scenario>[,<scenario>…] [extra launch args…]   → build/shots/<scenario>.png
#        SKIP_BUILD=1 reuses the last build; SHOOT_WAIT sets seconds to wait before the shot (default 3).
set -euo pipefail
cd "$(dirname "$0")/.."
SCENARIOS=${1:?scenario[,scenario…]}; shift || true
DEVICE="iPad Pro 13-inch (M5)"
if [ -z "${SKIP_BUILD:-}" ]; then
  xcodegen generate >/dev/null
  xcodebuild -project Kart.xcodeproj -scheme Kart -destination "platform=iOS Simulator,name=$DEVICE" \
    -derivedDataPath build build -quiet
fi
xcrun simctl boot "$DEVICE" 2>/dev/null || true
xcrun simctl bootstatus "$DEVICE" -b >/dev/null
xcrun simctl install "$DEVICE" build/Build/Products/Debug-iphonesimulator/Kart.app
mkdir -p build/shots
for s in ${SCENARIOS//,/ }; do
  xcrun simctl terminate "$DEVICE" com.kart.app 2>/dev/null || true
  xcrun simctl launch "$DEVICE" com.kart.app -KartScenario "$s" "$@" >/dev/null
  sleep "${SHOOT_WAIT:-3}"
  xcrun simctl io "$DEVICE" screenshot "build/shots/$s.png" >/dev/null 2>&1
  sips -r 270 "build/shots/$s.png" >/dev/null   # framebuffer is portrait; the app is landscape
  echo "build/shots/$s.png"
done
