#!/usr/bin/env bash
# watchdog.sh — Monitor PlacewareBot containers and auto-restart unhealthy ones.
#
# Runs as a systemd service (see watchdog.service).
# Install with:
#   sudo cp scripts/watchdog.service /etc/systemd/system/placeware-watchdog.service
#   sudo systemctl daemon-reload
#   sudo systemctl enable --now placeware-watchdog.service
#
# Logs go to: /var/log/placeware-watchdog.log  (also visible via journalctl)

set -euo pipefail

# ── Configuration ─────────────────────────────────────────────────────────────
COMPOSE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)/backend"
CHECK_INTERVAL_SECS=60   # how often to poll container health
UNHEALTHY_THRESHOLD=3    # consecutive unhealthy polls before restart
RESTART_COOLDOWN_SECS=90 # wait after restart before resuming checks
LOGFILE="/var/log/placeware-watchdog.log"

# ── Helpers ───────────────────────────────────────────────────────────────────
log() {
  local msg="[$(date -u '+%Y-%m-%dT%H:%M:%SZ')] $*"
  echo "$msg"
  echo "$msg" >> "$LOGFILE" 2>/dev/null || true
}

container_health() {
  # Returns: healthy | unhealthy | starting | none | missing
  local name="$1"
  docker inspect --format='{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}' \
    "$name" 2>/dev/null || echo "missing"
}

restart_service() {
  local service="$1"
  log "RESTART: Triggering 'docker compose restart $service'..."
  cd "$COMPOSE_DIR"
  docker compose \
    -f docker-compose.yml \
    -f docker-compose.prod.yml \
    restart "$service" 2>&1 | while IFS= read -r line; do log "  $line"; done
  log "RESTART: Done. Cooling down ${RESTART_COOLDOWN_SECS}s before next check."
  sleep "$RESTART_COOLDOWN_SECS"
}

# ── Main loop ─────────────────────────────────────────────────────────────────
log "====== PlacewareBot Watchdog started ======"
log "Compose dir : $COMPOSE_DIR"
log "Check every : ${CHECK_INTERVAL_SECS}s"
log "Restart after: ${UNHEALTHY_THRESHOLD} consecutive unhealthy polls"

backend_strikes=0
frontend_strikes=0

while true; do

  # ── Check backend ──────────────────────────────────────────────────────────
  backend_status=$(container_health "chat-backend.v1")

  if [[ "$backend_status" == "unhealthy" || "$backend_status" == "missing" ]]; then
    backend_strikes=$((backend_strikes + 1))
    log "WARN: backend status='$backend_status' (strike $backend_strikes/$UNHEALTHY_THRESHOLD)"

    if [[ "$backend_strikes" -ge "$UNHEALTHY_THRESHOLD" ]]; then
      log "ALERT: Backend has been unhealthy for $UNHEALTHY_THRESHOLD checks."
      restart_service "backend"
      backend_strikes=0
      frontend_strikes=0   # frontend health depends on backend; reset its counter too
      continue
    fi
  elif [[ "$backend_status" == "healthy" || "$backend_status" == "none" ]]; then
    # 'none' means no healthcheck configured — assume OK
    if [[ "$backend_strikes" -gt 0 ]]; then
      log "INFO: Backend recovered (was at $backend_strikes strikes)."
    fi
    backend_strikes=0
  fi
  # 'starting' → container is warming up; do nothing

  # ── Check frontend ─────────────────────────────────────────────────────────
  frontend_status=$(container_health "placeware-frontend.v1")

  if [[ "$frontend_status" == "unhealthy" || "$frontend_status" == "missing" ]]; then
    frontend_strikes=$((frontend_strikes + 1))
    log "WARN: Frontend status='$frontend_status' (strike $frontend_strikes/$UNHEALTHY_THRESHOLD)"

    if [[ "$frontend_strikes" -ge "$UNHEALTHY_THRESHOLD" ]]; then
      log "ALERT: Frontend has been unhealthy for $UNHEALTHY_THRESHOLD checks. Restarting."
      restart_service "frontend"
      frontend_strikes=0
    fi
  else
    if [[ "$frontend_strikes" -gt 0 ]]; then
      log "INFO: Frontend recovered."
    fi
    frontend_strikes=0
  fi

  sleep "$CHECK_INTERVAL_SECS"
done
