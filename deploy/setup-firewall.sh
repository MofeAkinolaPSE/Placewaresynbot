#!/usr/bin/env bash
# deploy/setup-firewall.sh — Configure UFW firewall for the PlacewareBot VM.
#
# Run ONCE on the Ubuntu VM as root:
#   sudo bash deploy/setup-firewall.sh
#
# Opens:  22 (SSH), 80 (HTTP → HTTPS redirect), 443 (HTTPS)
# Blocks: everything else including ports 8000 (backend) and 5432 (postgres)
#         which Docker exposes to the host but must not be internet-accessible.
# ─────────────────────────────────────────────────────────────────────────────

set -euo pipefail

echo "[setup-firewall] Installing UFW if not present..."
apt-get update -qq && apt-get install -y --no-install-recommends ufw

echo "[setup-firewall] Configuring rules..."

# Start from a clean default-deny baseline
ufw --force reset
ufw default deny incoming
ufw default allow outgoing

# Allow SSH first — CRITICAL: do this before enabling UFW or you lock yourself out
ufw allow 22/tcp comment "SSH"

# Allow web traffic
ufw allow 80/tcp  comment "HTTP (redirect to HTTPS)"
ufw allow 443/tcp comment "HTTPS"

# Explicitly block backend and DB ports that Docker exposes to the host.
# Docker manipulates iptables directly and can bypass UFW for published ports,
# so we insert REJECT rules in the INPUT chain via UFW.
ufw deny 8000/tcp comment "Backend internal — block external access"
ufw deny 5432/tcp comment "Postgres internal — block external access"
ufw deny 9090/tcp comment "Prometheus internal — SSH tunnel only"
ufw deny 3000/tcp comment "Grafana internal — SSH tunnel only"

echo "[setup-firewall] Enabling UFW..."
ufw --force enable

echo "[setup-firewall] Done."
ufw status verbose
echo ""
echo "IMPORTANT: UFW is active. Verify SSH still works from another terminal."
echo "To access Grafana/Prometheus remotely, use SSH tunnels:"
echo "  ssh -L 3000:localhost:3000 -L 9090:localhost:9090 user@192.168.100.84"
