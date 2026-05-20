#!/usr/bin/env bash
# /etc/letsencrypt/renewal-hooks/deploy/placeware-reload.sh
# Installed by the CI deploy pipeline (Ensure TLS certificate step).
# Called automatically by certbot after a successful renewal.
# Copies the renewed cert to /etc/ssl/placeware/ and reloads nginx.
set -euo pipefail

CERT_DIR="/etc/ssl/placeware"
DOMAIN_DIR=$(ls -1d /etc/letsencrypt/live/*/ 2>/dev/null | head -1 || true)

if [ -z "$DOMAIN_DIR" ]; then
  echo "[renewal-hook] No Let's Encrypt live cert found — skipping."
  exit 0
fi

cp -f "${DOMAIN_DIR}fullchain.pem" "$CERT_DIR/cert.pem"
cp -f "${DOMAIN_DIR}privkey.pem"   "$CERT_DIR/key.pem"
chmod 644 "$CERT_DIR/cert.pem"
chmod 640 "$CERT_DIR/key.pem"
echo "[renewal-hook] Certs copied to $CERT_DIR."

NGINX=$(docker ps --filter name=placeware_frontend --format '{{.ID}}' 2>/dev/null | head -1 || true)
if [ -n "$NGINX" ]; then
  docker exec "$NGINX" nginx -s reload
  echo "[renewal-hook] nginx reloaded (container $NGINX)."
else
  echo "[renewal-hook] WARNING: Frontend container not found — nginx will use new cert on next start."
fi
