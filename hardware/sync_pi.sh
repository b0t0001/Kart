#!/usr/bin/env bash
# From the laptop: pull GitHub here, then fast-forward the Pi's checkout to match.
# Usage: bash hardware/sync_pi.sh        (KART_PI overrides the default ssh target)
set -euo pipefail

PI="${KART_PI:-jamwan@smartcart.local}"
cd "$(dirname "$0")/.."

git pull --ff-only
echo "laptop: $(git log --oneline -1)"
ssh -o BatchMode=yes "$PI" 'cd ~/kart && git pull --ff-only -q && echo "pi:     $(git log --oneline -1)"'
