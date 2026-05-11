#!/usr/bin/env bash
# deploy/setup-fail2ban.sh — Install and configure fail2ban for the PlacewareBot VM.
#
# Run ONCE on the Ubuntu VM as root:
#   sudo bash deploy/setup-fail2ban.sh
#
# Protects against:
#   - SSH brute-force: 5 failures in 10 min → 1 hour ban
#   - HTTP 429 abuse (rate-limit bypass attempts): 10 failures → 30 min ban
# ─────────────────────────────────────────────────────────────────────────────

set -euo pipefail

echo "[setup-fail2ban] Installing fail2ban..."
apt-get update -qq && apt-get install -y --no-install-recommends fail2ban

# ── Jail configuration ────────────────────────────────────────────────────────
# Place in jail.d so it survives fail2ban package upgrades (overrides jail.conf)
JAIL_FILE="/etc/fail2ban/jail.d/placeware.conf"

echo "[setup-fail2ban] Writing jail configuration to ${JAIL_FILE}..."

cat > "$JAIL_FILE" << 'EOF'
[DEFAULT]
# Backend for banning — nftables preferred on Ubuntu 22+, fallback to iptables
banaction = nftables
banaction_allports = nftables[type=allports]

[sshd]
enabled   = true
port      = ssh
filter    = sshd
logpath   = /var/log/auth.log
maxretry  = 5
findtime  = 600    ; 10 minutes
bantime   = 3600   ; 1 hour
ignoreip  = 127.0.0.1/8 ::1

[nginx-req-limit]
# Bans IPs that consistently trip the nginx rate limiter (indicating abuse).
# Requires nginx to log 429 status codes — our nginx.conf does this via
# limit_req_status 429.
enabled   = true
port      = http,https
filter    = nginx-req-limit
logpath   = /var/log/nginx/error.log
maxretry  = 10
findtime  = 300    ; 5 minutes
bantime   = 1800   ; 30 minutes
EOF

# ── nginx-req-limit filter ────────────────────────────────────────────────────
FILTER_FILE="/etc/fail2ban/filter.d/nginx-req-limit.conf"

cat > "$FILTER_FILE" << 'EOF'
[Definition]
failregex = limiting requests, excess:.* by zone .*, client: <HOST>
ignoreregex =
EOF

echo "[setup-fail2ban] Enabling and starting fail2ban..."
systemctl enable fail2ban
systemctl restart fail2ban

echo "[setup-fail2ban] Done. Active jails:"
fail2ban-client status
echo ""
echo "Useful commands:"
echo "  sudo fail2ban-client status sshd          # see banned IPs for SSH"
echo "  sudo fail2ban-client status nginx-req-limit"
echo "  sudo fail2ban-client set sshd unbanip <IP>  # manually unban"
