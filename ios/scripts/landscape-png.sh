#!/bin/bash
# Turn screenshots of the landscape-only app upright: portrait framebuffers get rotated, and the
# EXIF orientation tag XCUITest adds is dropped so every viewer shows the pixels as they are.
cd "$(dirname "$0")/.."
for f in "$@"; do
  w=$(sips -g pixelWidth "$f" | awk '/pixelWidth/ {print $2}')
  h=$(sips -g pixelHeight "$f" | awk '/pixelHeight/ {print $2}')
  if [ "$h" -gt "$w" ]; then sips -r 270 "$f" >/dev/null; fi
  python3 scripts/strip-exif.py "$f"
done
