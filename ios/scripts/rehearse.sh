#!/bin/bash
# Run the automated demo rehearsal (spec §1.1) in the iPad simulator; screenshots land in build/shots/rehearsal/.
# usage: scripts/rehearse.sh [testName]   (default: every RehearsalTests test)
set -euo pipefail
cd "$(dirname "$0")/.."
[ -f Config.xcconfig ] || cp Config.example.xcconfig Config.xcconfig   # no Config yet: build against the mock
ONLY="KartUITests/RehearsalTests${1:+/$1}"
mkdir -p build/shots/rehearsal
xcodegen generate >/dev/null
TEST_RUNNER_SHOT_DIR="$PWD/build/shots/rehearsal" \
  xcodebuild test -project Kart.xcodeproj -scheme Kart -destination "platform=iOS Simulator,name=iPad Pro 13-inch (M5)" \
  -derivedDataPath build -only-testing:"$ONLY" -quiet
scripts/landscape-png.sh build/shots/rehearsal/*.png
ls build/shots/rehearsal
