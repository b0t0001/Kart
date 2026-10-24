#!/usr/bin/env bash
# Install the kart-cv systemd service so the pipeline starts on power-up.
# On the Pi:  bash ~/kart/hardware/install_service.sh         (enable for next boot)
#             bash ~/kart/hardware/install_service.sh --now   (also start it now)
# Logs:       journalctl -u kart-cv -f
# Undo:       sudo systemctl disable --now kart-cv
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
REPO="$(dirname "$HERE")"

if [ ! -f "$REPO/pi/main.py" ]; then
  echo "pi/main.py not found; pull the CV code first (git -C $REPO pull)" >&2
  exit 1
fi

sudo cp "$HERE/kart-cv.service" /etc/systemd/system/kart-cv.service
sudo systemctl daemon-reload
if [ "${1:-}" = "--now" ]; then
  sudo systemctl enable --now kart-cv
  systemctl --no-pager status kart-cv | head -15
else
  sudo systemctl enable kart-cv
  echo "enabled; starts on next boot (or: sudo systemctl start kart-cv)"
fi
