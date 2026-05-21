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

NGINX_LOG_PATH="${NGINX_LOG_PATH:-/var/log/nginx/error.log}"
ENABLE_NGINX_JAIL="${ENABLE_NGINX_JAIL:-auto}"
NGINX_JAIL_ACTIVE=0

echo "[setup-fail2ban] Installing fail2ban..."
apt-get update -qq && apt-get install -y --no-install-recommends fail2ban

if [[ "$ENABLE_NGINX_JAIL" == "1" || "$ENABLE_NGINX_JAIL" == "true" ]]; then
	if [[ -f "$NGINX_LOG_PATH" ]]; then
		NGINX_JAIL_ACTIVE=1
	else
		echo "[setup-fail2ban] WARN: ENABLE_NGINX_JAIL requested but log path missing: $NGINX_LOG_PATH"
		echo "[setup-fail2ban] WARN: nginx jail disabled; sshd jail remains enabled."
	fi
elif [[ "$ENABLE_NGINX_JAIL" == "auto" ]]; then
	if [[ -f "$NGINX_LOG_PATH" ]]; then
		NGINX_JAIL_ACTIVE=1
	fi
fi

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
EOF

if [[ "$NGINX_JAIL_ACTIVE" -eq 1 ]]; then
cat >> "$JAIL_FILE" << EOF

[nginx-req-limit]
# Bans IPs that consistently trip the nginx rate limiter (indicating abuse).
# Requires nginx to log 429 status codes.
enabled   = true
port      = http,https
filter    = nginx-req-limit
logpath   = $NGINX_LOG_PATH
maxretry  = 10
findtime  = 300    ; 5 minutes
bantime   = 1800   ; 30 minutes
EOF
fi

# ── nginx-req-limit filter ────────────────────────────────────────────────────
FILTER_FILE="/etc/fail2ban/filter.d/nginx-req-limit.conf"

if [[ "$NGINX_JAIL_ACTIVE" -eq 1 ]]; then
cat > "$FILTER_FILE" << 'EOF'
[Definition]
failregex = limiting requests, excess:.* by zone .*, client: <HOST>
ignoreregex =
EOF
fi

echo "[setup-fail2ban] Enabling and starting fail2ban..."
systemctl enable fail2ban
systemctl restart fail2ban

echo "[setup-fail2ban] Done. Active jails:"
fail2ban-client status
if [[ "$NGINX_JAIL_ACTIVE" -eq 1 ]]; then
	echo "[setup-fail2ban] nginx-req-limit jail is enabled (log path: $NGINX_LOG_PATH)."
else
	echo "[setup-fail2ban] nginx-req-limit jail is disabled (log path missing or disabled by config)."
	echo "[setup-fail2ban] To force-enable later: ENABLE_NGINX_JAIL=1 NGINX_LOG_PATH=/path/to/nginx/error.log sudo bash deploy/setup-fail2ban.sh"
fi
echo ""
echo "Useful commands:"
echo "  sudo fail2ban-client status sshd          # see banned IPs for SSH"
echo "  sudo fail2ban-client status nginx-req-limit"
echo "  sudo fail2ban-client set sshd unbanip <IP>  # manually unban"
