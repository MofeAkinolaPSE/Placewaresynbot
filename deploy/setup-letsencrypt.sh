#!/usr/bin/env bash
# ⚠ LINUX VM ONLY. On the Windows + Docker Desktop server use deploy/issue-cert.ps1
#   instead: this script writes to host folders the nginx container cannot see
#   (the container reads the placeware_ssl_certs Docker volume) and looks for a
#   container named "placeware_frontend" (the real one is placeware-frontend.v1).
#
# deploy/setup-letsencrypt.sh — Obtain a browser-trusted TLS certificate via
# Let's Encrypt and install it at /etc/ssl/placeware/ (same path as self-signed
# cert, so nginx config never needs changing).
#
# ── Usage ────────────────────────────────────────────────────────────────────
#   sudo bash deploy/setup-letsencrypt.sh
#       Auto-detects VM public IP, uses <ip-dashes>.sslip.io as domain.
#       No domain purchase needed. Cert is browser-trusted immediately.
#
#   sudo bash deploy/setup-letsencrypt.sh yourdomain.com admin@example.com
#       Uses your own domain (A record must already point to this server).
#
# ── How it works ─────────────────────────────────────────────────────────────
#   1. Installs certbot (if not present).
#   2. Uses --webroot mode via /var/www/certbot — nginx serves the ACME
#      challenge at /.well-known/acme-challenge/ WITHOUT stopping.
#   3. After cert is issued, copies fullchain + key to /etc/ssl/placeware/
#      so nginx (in the Docker container) picks it up immediately.
#   4. Signals the running nginx container to reload its TLS config.
#   5. Installs a systemd timer for daily renewal checks (certs expire in 90d;
#      renewed automatically when < 30 days remain).
#
# ── Requirements ─────────────────────────────────────────────────────────────
#   - The frontend container must already be running (nginx serves port 80/443)
#   - Port 80 must be reachable from the internet (Let's Encrypt needs it)
#   - For sslip.io: no DNS config needed — it auto-maps IPs to subdomains
#   - For your own domain: DNS A record must point to this VM's public IP
# ─────────────────────────────────────────────────────────────────────────────
set -euo pipefail

CERT_DIR="/etc/ssl/placeware"
WEBROOT="/var/www/certbot"
DOMAIN="${1:-}"
EMAIL="${2:-}"

# ── Detect public IP and build sslip.io domain if no domain provided ─────────
if [ -z "$DOMAIN" ]; then
    echo "[letsencrypt] No domain provided — detecting public IP for sslip.io..."
    PUBLIC_IP=$(curl -sf https://checkip.amazonaws.com || \
                curl -sf https://api.ipify.org        || \
                hostname -I | awk '{print $1}')
    if [ -z "$PUBLIC_IP" ]; then
        echo "ERROR: Could not detect public IP. Pass your domain as the first argument."
        echo "  Usage: sudo bash deploy/setup-letsencrypt.sh yourdomain.com admin@you.com"
        exit 1
    fi
    # sslip.io maps dashes to dots: 203-0-113-45.sslip.io → 203.0.113.45
    DOMAIN=$(echo "$PUBLIC_IP" | tr '.' '-').sslip.io
    echo "[letsencrypt] Using sslip.io domain: $DOMAIN (resolves to $PUBLIC_IP)"
fi

# Use a no-reply address if no email given (certbot requires one for expiry alerts)
if [ -z "$EMAIL" ]; then
    EMAIL="admin@${DOMAIN}"
    echo "[letsencrypt] No email provided — using $EMAIL for expiry notifications."
fi

echo "[letsencrypt] Domain : $DOMAIN"
echo "[letsencrypt] Email  : $EMAIL"
echo "[letsencrypt] Cert   : $CERT_DIR/cert.pem"

# ── Install certbot ───────────────────────────────────────────────────────────
if ! command -v certbot &>/dev/null; then
    echo "[letsencrypt] Installing certbot..."
    apt-get update -qq
    apt-get install -y certbot
fi

# ── Create webroot for ACME challenges ───────────────────────────────────────
mkdir -p "$WEBROOT"

# ── Obtain certificate (webroot mode — nginx stays running) ──────────────────
echo "[letsencrypt] Requesting certificate from Let's Encrypt..."
certbot certonly \
    --webroot \
    --webroot-path "$WEBROOT" \
    --domain "$DOMAIN" \
    --email "$EMAIL" \
    --agree-tos \
    --non-interactive \
    --keep-until-expiring

LE_LIVE="/etc/letsencrypt/live/$DOMAIN"

if [ ! -f "$LE_LIVE/fullchain.pem" ]; then
    echo "ERROR: Certificate not found at $LE_LIVE — certbot may have failed."
    exit 1
fi

# ── Install certs to /etc/ssl/placeware/ (same path nginx already uses) ──────
echo "[letsencrypt] Installing certs to $CERT_DIR..."
mkdir -p "$CERT_DIR"
# fullchain = cert + intermediate chain (nginx needs both for OCSP stapling)
cp -f "$LE_LIVE/fullchain.pem"  "$CERT_DIR/cert.pem"
cp -f "$LE_LIVE/privkey.pem"    "$CERT_DIR/key.pem"
chmod 644 "$CERT_DIR/cert.pem"
chmod 640 "$CERT_DIR/key.pem"

# ── Signal nginx to reload TLS config without downtime ───────────────────────
NGINX_CONTAINER=$(docker ps --filter name=placeware_frontend --format '{{.ID}}' 2>/dev/null | head -1 || true)
if [ -n "$NGINX_CONTAINER" ]; then
    echo "[letsencrypt] Reloading nginx TLS config in container $NGINX_CONTAINER..."
    docker exec "$NGINX_CONTAINER" nginx -s reload
    echo "[letsencrypt] nginx reloaded."
else
    echo "[letsencrypt] WARNING: Frontend container not found — nginx will pick up new cert on next start."
fi

# ── Install renewal hook (copies renewed certs + reloads nginx) ──────────────
HOOK_PATH="/etc/letsencrypt/renewal-hooks/deploy/placeware-reload.sh"
echo "[letsencrypt] Installing renewal deploy hook at $HOOK_PATH..."
mkdir -p "$(dirname "$HOOK_PATH")"
cat > "$HOOK_PATH" <<'HOOK'
#!/usr/bin/env bash
# Renewal deploy hook — runs after certbot successfully renews the cert.
set -euo pipefail
DOMAIN_DIR=$(ls -1d /etc/letsencrypt/live/*/ | head -1)
CERT_DIR="/etc/ssl/placeware"
cp -f "${DOMAIN_DIR}fullchain.pem" "$CERT_DIR/cert.pem"
cp -f "${DOMAIN_DIR}privkey.pem"   "$CERT_DIR/key.pem"
chmod 644 "$CERT_DIR/cert.pem"
chmod 640 "$CERT_DIR/key.pem"
NGINX=$(docker ps --filter name=placeware_frontend --format '{{.ID}}' 2>/dev/null | head -1 || true)
[ -n "$NGINX" ] && docker exec "$NGINX" nginx -s reload && echo "[renewal-hook] nginx reloaded."
HOOK
chmod +x "$HOOK_PATH"

# ── Set up systemd timer for daily renewal check ──────────────────────────────
echo "[letsencrypt] Configuring daily renewal check via systemd timer..."
systemctl enable certbot.timer  2>/dev/null && \
systemctl start  certbot.timer  2>/dev/null && \
echo "[letsencrypt] certbot.timer enabled (checks daily, renews when < 30 days remain)." || \
echo "[letsencrypt] WARNING: Could not enable systemd timer — add a cron job manually:"
echo "  0 3 * * * certbot renew --quiet"

echo ""
echo "════════════════════════════════════════════════════════"
echo "  Let's Encrypt certificate installed successfully."
echo "  Domain  : https://$DOMAIN"
echo "  Expires : $(openssl x509 -noout -enddate -in "$CERT_DIR/cert.pem" | cut -d= -f2)"
echo "  Renewal : automatic (daily check, renews at < 30 days)"
echo "════════════════════════════════════════════════════════"
echo ""
echo "Next: tell clients to access the app at:"
echo "  https://$DOMAIN"
