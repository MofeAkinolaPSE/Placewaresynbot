#!/usr/bin/env bash
# deploy/gen-tls-cert.sh — Generate a self-signed TLS certificate for the VM.
#
# Run ONCE on the Ubuntu VM before starting containers:
#   sudo bash deploy/gen-tls-cert.sh
#
# The cert is mounted read-only into the nginx container via docker-compose.yml.
#
# ── Upgrading to Let's Encrypt when a public domain is acquired ─────────────
#   1. sudo apt install certbot
#   2. sudo certbot certonly --standalone -d yourdomain.com
#   3. Update nginx.conf ssl_certificate paths:
#        ssl_certificate     /etc/letsencrypt/live/yourdomain.com/fullchain.pem;
#        ssl_certificate_key /etc/letsencrypt/live/yourdomain.com/privkey.pem;
#   4. Add renewal cron: sudo certbot renew --dry-run
#   5. Rebuild/restart frontend container: docker compose restart frontend
# ────────────────────────────────────────────────────────────────────────────

set -euo pipefail

CERT_DIR="/etc/ssl/placeware"
DAYS=825      # Apple/Chrome max validity for self-signed certs
VM_IP="${1:-192.168.100.84}"

echo "[gen-tls-cert] Creating certificate directory: $CERT_DIR"
mkdir -p "$CERT_DIR"
chmod 750 "$CERT_DIR"

echo "[gen-tls-cert] Generating 2048-bit RSA key and self-signed certificate..."
echo "[gen-tls-cert] Subject Alt Names: IP:${VM_IP}, IP:127.0.0.1, DNS:localhost"

openssl req -x509 -nodes \
    -newkey rsa:2048 \
    -keyout "${CERT_DIR}/key.pem" \
    -out    "${CERT_DIR}/cert.pem" \
    -days   "${DAYS}" \
    -subj   "/CN=placeware-internal/O=Placeware/C=NG" \
    -addext "subjectAltName=IP:${VM_IP},IP:127.0.0.1,DNS:localhost"

chmod 640 "${CERT_DIR}/key.pem"
chmod 644 "${CERT_DIR}/cert.pem"

echo "[gen-tls-cert] Done."
echo "  Certificate: ${CERT_DIR}/cert.pem  (valid ${DAYS} days)"
echo "  Private key: ${CERT_DIR}/key.pem"
echo ""
echo "Next: docker compose up -d --build"
echo "Then: curl -Ik https://${VM_IP}/  (expect 200 with Strict-Transport-Security header)"
