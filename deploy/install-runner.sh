#!/usr/bin/env bash
# install-runner.sh — Install a GitHub Actions self-hosted runner on the Ubuntu VM
#
# Because the client's VM is on a private LAN (no inbound internet access),
# standard GitHub-hosted runners cannot SSH in.  A self-hosted runner solves
# this: it runs ON the VM and polls GitHub for jobs — only outbound traffic.
#
# USAGE (run on the Ubuntu VM):
#   bash scripts/install-runner.sh <REPO_URL> <RUNNER_TOKEN>
#
# STEPS TO GET A RUNNER TOKEN:
#   1. Go to: https://github.com/MofeAkinolaPSE/Placewaresynbot
#   2. Settings → Actions → Runners → "New self-hosted runner"
#   3. Select: Linux / x64
#   4. Copy the token shown (valid for 1 hour)
#   5. Run this script with that token
#
# EXAMPLE:
#   bash scripts/install-runner.sh \
#     https://github.com/MofeAkinolaPSE/Placewaresynbot \
#     AABCDEF1234567890TOKEN

set -euo pipefail

REPO_URL="${1:?Usage: $0 <repo-url> <runner-token>}"
RUNNER_TOKEN="${2:?Usage: $0 <repo-url> <runner-token>}"
RUNNER_VERSION="2.317.0"
RUNNER_DIR="$HOME/actions-runner"
RUNNER_NAME="placeware-vm"
RUNNER_LABEL="placeware-vm"

echo "======================================================="
echo " PlacewareBot — GitHub Actions Runner Setup"
echo "======================================================="
echo " Repo      : $REPO_URL"
echo " Runner dir: $RUNNER_DIR"
echo " Label     : $RUNNER_LABEL"
echo "======================================================="

# ── Step 1: Create runner directory ──────────────────────────────────────────
echo ""
echo "[1/5] Creating runner directory..."
mkdir -p "$RUNNER_DIR"
cd "$RUNNER_DIR"

# ── Step 2: Download runner ───────────────────────────────────────────────────
echo "[2/5] Downloading GitHub Actions runner v${RUNNER_VERSION}..."
curl -sSL \
  "https://github.com/actions/runner/releases/download/v${RUNNER_VERSION}/actions-runner-linux-x64-${RUNNER_VERSION}.tar.gz" \
  -o runner.tar.gz
tar xzf runner.tar.gz
rm runner.tar.gz
echo "    Download complete."

# ── Step 3: Configure ─────────────────────────────────────────────────────────
echo "[3/5] Configuring runner..."
./config.sh \
  --url     "$REPO_URL" \
  --token   "$RUNNER_TOKEN" \
  --name    "$RUNNER_NAME" \
  --labels  "$RUNNER_LABEL" \
  --work    "$RUNNER_DIR/_work" \
  --unattended \
  --replace
echo "    Configuration complete."

# ── Step 4: Install as systemd service ───────────────────────────────────────
echo "[4/5] Installing as systemd service..."
sudo ./svc.sh install
sudo ./svc.sh start
echo "    Service installed and started."

# ── Step 5: Verify ────────────────────────────────────────────────────────────
echo "[5/5] Verifying runner service..."
sudo ./svc.sh status

echo ""
echo "======================================================="
echo " Runner installation complete!"
echo "======================================================="
echo ""
echo " The runner is now ONLINE and listening for GitHub jobs."
echo " It runs as a systemd service: actions.runner.*.service"
echo ""
echo " Check status : sudo systemctl status actions.runner.*.service"
echo " View logs    : sudo journalctl -u actions.runner.*.service -f"
echo " Stop runner  : sudo ./svc.sh stop    (in $RUNNER_DIR)"
echo " Uninstall    : sudo ./svc.sh uninstall"
echo ""
echo " In your GitHub Actions workflow, target this runner with:"
echo "   runs-on: [self-hosted, linux, $RUNNER_LABEL]"
echo "======================================================="
