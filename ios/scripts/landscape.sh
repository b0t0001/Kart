#!/bin/bash
# Turn the iPad simulator to landscape (once per simulator boot).
set -euo pipefail
cd "$(dirname "$0")/.."
xcodegen generate >/dev/null
xcodebuild test -project Kart.xcodeproj -scheme Kart -destination "platform=iOS Simulator,name=iPad Pro 13-inch (M5)" \
  -derivedDataPath build -only-testing:KartUITests/OrientationTests/testRotateToLandscape -quiet
