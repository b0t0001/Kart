#!/usr/bin/env bash
# One-time Pi setup for KART (safe to re-run): system packages, ~/venv, repo checkout.
# On the Pi:        bash ~/kart/hardware/setup_pi.sh
# From the laptop:  ssh jamwan@smartcart.local 'bash -s' < hardware/setup_pi.sh
# Touches no network settings.
set -euo pipefail

REPO_URL=https://github.com/b0t0001/kart.git
REPO_DIR="$HOME/kart"
VENV="$HOME/venv"

sudo apt-get update
sudo apt-get install -y git python3-venv python3-opencv python3-numpy v4l-utils

[ -d "$REPO_DIR/.git" ] || git clone "$REPO_URL" "$REPO_DIR"

# --system-site-packages so the apt OpenCV is visible inside the venv.
[ -x "$VENV/bin/python" ] || python3 -m venv --system-site-packages "$VENV"
grep -qF 'source ~/venv/bin/activate' ~/.bashrc || echo 'source ~/venv/bin/activate' >> ~/.bashrc

# requirements-pi.txt leaves out OpenCV/NumPy (apt) and pytest; we still want pytest to run pi/tests here.
REQS="$REPO_DIR/pi/requirements-pi.txt"
if [ -f "$REQS" ]; then
  "$VENV/bin/pip" install -r "$REQS" pytest
else
  "$VENV/bin/pip" install onnxruntime onnx anthropic python-dotenv pytest
fi

"$VENV/bin/python" -c "import cv2, numpy; print('cv2', cv2.__version__, '| numpy', numpy.__version__)"
groups | grep -qw video || echo "WARNING: $USER is not in the video group (sudo usermod -aG video $USER, then log out/in)"
echo "setup done"
