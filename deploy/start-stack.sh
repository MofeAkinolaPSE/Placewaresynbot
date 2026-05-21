#!/usr/bin/env bash
# deploy/start-stack.sh — single entrypoint for VM bootstrap + stack startup.
#
# First run (interactive, recommended):
#   sudo bash deploy/start-stack.sh --first-run --install-deps
#
# Repeat deploy (idempotent):
#   sudo bash deploy/start-stack.sh --redeploy

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
BACKEND_DIR="$REPO_ROOT/backend"

MODE="first-run"
INSTALL_DEPS=0
NON_INTERACTIVE=0
ASSUME_YES=0
SKIP_HARDENING=0
RUN_HARDENING=0
SKIP_SSH_HARDENING=0
CONNECTIVITY_MODE=""
RUN_LETSENCRYPT=0
LE_DOMAIN=""
LE_EMAIL=""
SKIP_DB_CHECK=0
RESET_DB=0
SEED_ADMIN=0

PASS_COUNT=0
WARN_COUNT=0

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
CYAN='\033[0;36m'
NC='\033[0m'

log_info() { echo -e "${CYAN}[start-stack]${NC} $*"; }
log_pass() { echo -e "${GREEN}[PASS]${NC} $*"; PASS_COUNT=$((PASS_COUNT + 1)); }
log_warn() { echo -e "${YELLOW}[WARN]${NC} $*"; WARN_COUNT=$((WARN_COUNT + 1)); }
die() { echo -e "${RED}[FAIL]${NC} $*" >&2; exit 1; }

usage() {
  cat <<'EOF'
Usage:
  sudo bash deploy/start-stack.sh [options]

Modes:
  --first-run                  Full bootstrap (default)
  --redeploy                   Fast idempotent rerun (hardening skipped by default)

Options:
  --install-deps               Install host dependencies if missing (Ubuntu/Debian)
  --run-hardening              Run hardening in redeploy mode
  --skip-hardening             Skip hardening phase entirely
  --skip-ssh-hardening         Skip deploy/harden-ssh.sh only
  --connectivity MODE          MODE in: required | advisory | skip
  --letsencrypt                Run deploy/setup-letsencrypt.sh after deploy
  --letsencrypt-domain DOMAIN  Domain passed to setup-letsencrypt
  --letsencrypt-email EMAIL    Email passed to setup-letsencrypt
  --skip-db-check              Skip post-deploy DB readiness checks (not recommended)
  --reset-db                   Destroy and recreate Postgres volume before deploy (DATA LOSS)
  --seed-admin                 Run backend/seed_admin.py in running backend container
  --non-interactive            No prompts. Required checks fail if confirmation is needed
  --yes                        Assume "yes" for prompts (still blocks on hard failures)
  -h, --help                   Show this help

Examples:
  sudo bash deploy/start-stack.sh --first-run --install-deps
  sudo bash deploy/start-stack.sh --redeploy
  sudo bash deploy/start-stack.sh --redeploy --run-hardening --connectivity required
EOF
}

confirm() {
  local prompt="$1"

  if [[ "$ASSUME_YES" -eq 1 ]]; then
    return 0
  fi

  if [[ "$NON_INTERACTIVE" -eq 1 ]]; then
    return 1
  fi

  read -r -p "$prompt [y/N]: " answer
  case "${answer,,}" in
    y|yes) return 0 ;;
    *) return 1 ;;
  esac
}

require_file() {
  local path="$1"
  [[ -f "$path" ]] || die "Required file not found: $path"
}

run_cmd() {
  local label="$1"
  shift
  log_info "$label"
  "$@"
  log_pass "$label"
}

get_service_container_id() {
  local service_name="$1"
  docker ps \
    --filter "label=com.docker.swarm.service.name=${service_name}" \
    --format '{{.ID}}' \
    | head -1
}

get_backend_env_value() {
  local key="$1"
  if [[ ! -f "$BACKEND_DIR/.env" ]]; then
    return 0
  fi
  grep -E "^${key}=" "$BACKEND_DIR/.env" | tail -1 | cut -d'=' -f2-
}

infer_app_db_name() {
  local db_url
  db_url="$(get_backend_env_value "DATABASE_URL")"

  if [[ -n "$db_url" ]]; then
    python3 - <<PY
from urllib.parse import urlparse
u = urlparse(${db_url@Q})
name = (u.path or '').lstrip('/')
print(name or 'synbot_demo')
PY
    return 0
  fi

  local pg_db
  pg_db="$(get_backend_env_value "POSTGRES_DB")"
  if [[ -n "$pg_db" ]]; then
    echo "$pg_db"
  else
    echo "synbot_demo"
  fi
}

ensure_app_database_exists() {
  local db_name
  db_name="$(infer_app_db_name)"

  if [[ ! "$db_name" =~ ^[a-zA-Z0-9_]+$ ]]; then
    die "Refusing to validate DB with unexpected name: $db_name"
  fi

  local db_cid
  db_cid="$(get_service_container_id "placeware_db")"
  [[ -n "$db_cid" ]] || die "Could not find running DB container for database existence probe"

  local exists
  exists="$(docker exec "$db_cid" psql -U postgres -tAc "SELECT 1 FROM pg_database WHERE datname='${db_name}'" | tr -d '[:space:]')"

  if [[ "$exists" == "1" ]]; then
    log_pass "Application database exists (${db_name})"
    return 0
  fi

  log_warn "Application database '${db_name}' missing. Creating it now..."
  docker exec "$db_cid" psql -U postgres -v ON_ERROR_STOP=1 -c "CREATE DATABASE \"${db_name}\""
  log_pass "Application database created (${db_name})"
}

reset_db_state() {
  log_warn "DB reset requested. This will permanently delete Postgres data volume contents."

  if [[ "$ASSUME_YES" -ne 1 && "$NON_INTERACTIVE" -eq 1 ]]; then
    die "--reset-db in non-interactive mode requires --yes"
  fi

  if ! confirm "Proceed with destructive DB reset for volume placeware_db_data?"; then
    die "DB reset cancelled by user"
  fi

  if docker service inspect placeware_db >/dev/null 2>&1; then
    log_info "Scaling placeware_db to 0 replicas before volume removal"
    docker service update --replicas 0 placeware_db >/dev/null 2>&1 || true
    sleep 8
  fi

  local holders
  holders="$(docker ps -a --filter volume=placeware_db_data --format '{{.ID}}')"
  if [[ -n "$holders" ]]; then
    echo "$holders" | xargs -r docker rm -f >/dev/null 2>&1 || true
  fi

  docker volume rm placeware_db_data >/dev/null 2>&1 || true
  log_pass "DB volume reset completed"
}

run_admin_seed() {
  local backend_cid
  backend_cid="$(get_service_container_id "placeware_backend")"
  [[ -n "$backend_cid" ]] || die "Could not find running backend container for admin seed"

  log_info "Running admin seed in backend container"
  docker exec "$backend_cid" /bin/sh -lc '
    if [ -f /backend/seed_admin.py ]; then
      exec python /backend/seed_admin.py
    elif [ -f seed_admin.py ]; then
      exec python seed_admin.py
    else
      echo "seed_admin.py not found in container filesystem" >&2
      exit 1
    fi
  '
  log_pass "Admin seed completed"
}

wait_for_service_replicas() {
  local service_name="$1"
  local expected="$2"
  local attempts="${3:-24}"
  local delay_secs="${4:-5}"
  local replicas=""

  for i in $(seq 1 "$attempts"); do
    replicas=$(docker service ls --filter "name=${service_name}" --format '{{.Replicas}}' 2>/dev/null || echo "0/0")
    if [[ "$replicas" == "$expected" ]]; then
      return 0
    fi
    log_info "Waiting for ${service_name} replicas=${expected} (current=${replicas}, attempt ${i}/${attempts})"
    sleep "$delay_secs"
  done

  log_warn "Service ${service_name} did not converge to ${expected}; current=${replicas}"
  return 1
}

post_deploy_db_check() {
  log_info "Running post-deploy DB readiness checks"

  wait_for_service_replicas "placeware_db" "1/1" 24 5 || {
    docker service ps placeware_db --no-trunc || true
    docker service logs placeware_db --tail 80 || true
    die "DB service failed readiness check"
  }

  ensure_app_database_exists

  wait_for_service_replicas "placeware_backend" "1/1" 30 5 || {
    docker service ps placeware_backend --no-trunc || true
    docker service logs placeware_backend --tail 120 || true
    die "Backend service failed readiness check"
  }

  local backend_cid
  backend_cid="$(get_service_container_id "placeware_backend")"
  [[ -n "$backend_cid" ]] || die "Could not find running backend container for DB connectivity probe"

  docker exec "$backend_cid" python - <<'PY'
import os
from urllib.parse import urlparse

import psycopg2

dsn = os.getenv("DATABASE_URL", "")
if not dsn:
    raise SystemExit("DATABASE_URL missing inside backend container")

parsed = urlparse(dsn)
host = parsed.hostname or ""
if host == "db":
    # Explicitly verify overlay DNS resolution for the db service name.
    import socket
    socket.getaddrinfo("db", 5432)

conn = psycopg2.connect(dsn)
cur = conn.cursor()
cur.execute("SELECT 1")
cur.fetchone()
cur.close()
conn.close()
print("DB connectivity probe succeeded")
PY

  log_pass "Post-deploy DB readiness checks"
}

has_ssh_service_unit() {
  systemctl list-unit-files 2>/dev/null | grep -qE '^ssh\.service|^sshd\.service'
}

ensure_ssh_service_unit() {
  if has_ssh_service_unit; then
    log_pass "SSH service unit present (ssh/sshd)"
    return 0
  fi

  log_warn "SSH service unit missing. Attempting automatic fix (install openssh-server)."

  command -v apt-get >/dev/null 2>&1 || die "apt-get not found. Install openssh-server manually for this distro."

  export DEBIAN_FRONTEND=noninteractive
  apt-get update -qq
  apt-get install -y --no-install-recommends openssh-server

  systemctl enable --now ssh >/dev/null 2>&1 || systemctl enable --now sshd >/dev/null 2>&1 || true

  has_ssh_service_unit || die "Automatic fix failed: ssh/sshd service unit still missing after openssh-server install."
  log_pass "SSH service unit auto-fixed"
}

install_dependencies() {
  log_info "Dependency install requested. Installing runtime prerequisites."
  export DEBIAN_FRONTEND=noninteractive
  apt-get update -qq
  apt-get install -y --no-install-recommends \
    ca-certificates \
    curl \
    docker.io \
    openssh-server \
    python3 \
    python3-pip \
    ufw \
    fail2ban

  systemctl enable docker >/dev/null 2>&1 || true
  systemctl start docker

  log_pass "Host dependencies installed"
}

connectivity_gate() {
  local gate_mode="$1"

  if [[ "$gate_mode" == "skip" ]]; then
    log_warn "Connectivity gate skipped (--connectivity skip)."
    return 0
  fi

  echo ""
  log_info "Connectivity gate (Phase 4)"
  echo "Run this on the Sage Windows host before cutover completion:"
  echo "  cd sage-bridge"
  echo "  powershell -ExecutionPolicy Bypass -File .\\start_and_test.ps1 -SkipWrite"
  echo "  (or: python test_connectivity.py --skip-write)"
  echo ""
  echo "Required .env alignment:"
  echo "  - backend/.env: SAGE_BRIDGE_URL, SAGE_BRIDGE_KEY, SAGE_BRIDGE_WEBHOOK_SECRET"
  echo "  - sage-bridge/.env: BRIDGE_API_KEY, SYNBOT_WEBHOOK_URL, SYNBOT_WEBHOOK_KEY"

  if [[ "${CONNECTIVITY_OK:-0}" == "1" ]]; then
    log_pass "Connectivity attested via CONNECTIVITY_OK=1"
    return 0
  fi

  if [[ "$gate_mode" == "advisory" ]]; then
    log_warn "Connectivity not enforced. Set CONNECTIVITY_OK=1 after running test_connectivity.py"
    return 0
  fi

  if [[ "$NON_INTERACTIVE" -eq 1 ]]; then
    die "Connectivity gate is required in non-interactive mode. Set CONNECTIVITY_OK=1 after running test_connectivity.py"
  fi

  echo ""
  if confirm "Type yes only if test_connectivity.py completed successfully"; then
    log_pass "Connectivity manually confirmed"
  else
    die "Connectivity gate not confirmed. Resolve bridge/VM connectivity and rerun."
  fi
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --first-run)
      MODE="first-run"
      ;;
    --redeploy)
      MODE="redeploy"
      ;;
    --install-deps)
      INSTALL_DEPS=1
      ;;
    --run-hardening)
      RUN_HARDENING=1
      ;;
    --skip-hardening)
      SKIP_HARDENING=1
      ;;
    --skip-ssh-hardening)
      SKIP_SSH_HARDENING=1
      ;;
    --connectivity)
      shift
      [[ $# -gt 0 ]] || die "Missing value for --connectivity"
      CONNECTIVITY_MODE="$1"
      ;;
    --letsencrypt)
      RUN_LETSENCRYPT=1
      ;;
    --letsencrypt-domain)
      shift
      [[ $# -gt 0 ]] || die "Missing value for --letsencrypt-domain"
      LE_DOMAIN="$1"
      ;;
    --letsencrypt-email)
      shift
      [[ $# -gt 0 ]] || die "Missing value for --letsencrypt-email"
      LE_EMAIL="$1"
      ;;
    --skip-db-check)
      SKIP_DB_CHECK=1
      ;;
    --reset-db)
      RESET_DB=1
      ;;
    --seed-admin)
      SEED_ADMIN=1
      ;;
    --non-interactive)
      NON_INTERACTIVE=1
      ;;
    --yes)
      ASSUME_YES=1
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      die "Unknown option: $1"
      ;;
  esac
  shift
done

[[ "$EUID" -eq 0 ]] || die "Run as root. Example: sudo bash deploy/start-stack.sh --first-run --install-deps"

if [[ ! -f /etc/os-release ]]; then
  log_warn "Could not detect OS from /etc/os-release"
elif ! grep -qiE 'ubuntu|debian' /etc/os-release; then
  log_warn "This script is validated on Ubuntu/Debian. Continue with caution."
fi

if [[ -z "$CONNECTIVITY_MODE" ]]; then
  CONNECTIVITY_MODE="advisory"
fi

case "$CONNECTIVITY_MODE" in
  required|advisory|skip) ;;
  *) die "Invalid --connectivity mode: $CONNECTIVITY_MODE (use required|advisory|skip)" ;;
esac

require_file "$REPO_ROOT/deploy/preflight-host.sh"
require_file "$REPO_ROOT/deploy/harden-ssh.sh"
require_file "$REPO_ROOT/deploy/setup-firewall.sh"
require_file "$REPO_ROOT/deploy/setup-fail2ban.sh"
require_file "$REPO_ROOT/deploy/init-swarm.sh"
require_file "$BACKEND_DIR/.env"

echo ""
echo "====================================================================="
echo " start-stack mode: $MODE"
echo " repo root       : $REPO_ROOT"
echo " connectivity    : $CONNECTIVITY_MODE"
echo "====================================================================="

if [[ "$INSTALL_DEPS" -eq 1 ]]; then
  install_dependencies
else
  log_info "Dependency install skipped (--install-deps not provided)."
fi

if [[ "$RESET_DB" -eq 1 ]]; then
  reset_db_state
  SEED_ADMIN=1
fi

DO_HARDENING=0
if [[ "$SKIP_HARDENING" -eq 1 ]]; then
  DO_HARDENING=0
elif [[ "$MODE" == "first-run" || "$RUN_HARDENING" -eq 1 ]]; then
  DO_HARDENING=1
fi

if [[ "$DO_HARDENING" -eq 1 ]]; then
  ensure_ssh_service_unit
  run_cmd "Run preflight checks (strict SSH mode)" env STRICT_SSH_CHECKS=1 bash "$REPO_ROOT/deploy/preflight-host.sh"
else
  log_info "Skipping SSH auto-fix because hardening is not scheduled in this run."
  run_cmd "Run preflight checks (non-strict SSH mode)" env STRICT_SSH_CHECKS=0 bash "$REPO_ROOT/deploy/preflight-host.sh"
fi

if [[ "$DO_HARDENING" -eq 1 ]]; then
  log_info "Hardening phase enabled"

  if [[ "$SKIP_SSH_HARDENING" -eq 1 ]]; then
    log_warn "Skipping SSH hardening (--skip-ssh-hardening)."
  else
    if confirm "Proceed with SSH hardening (disables password login and root login)?"; then
      run_cmd "Apply SSH hardening" bash "$REPO_ROOT/deploy/harden-ssh.sh"
    else
      if [[ "$MODE" == "first-run" ]]; then
        die "SSH hardening declined in first-run mode. Re-run with --skip-ssh-hardening only if intentionally deferring."
      fi
      log_warn "SSH hardening declined. Continuing because mode is redeploy."
    fi
  fi

  run_cmd "Configure firewall" bash "$REPO_ROOT/deploy/setup-firewall.sh"
  run_cmd "Configure fail2ban" bash "$REPO_ROOT/deploy/setup-fail2ban.sh"
else
  log_info "Hardening phase skipped."
fi

run_cmd "Initialize swarm/build/deploy stack" bash "$REPO_ROOT/deploy/init-swarm.sh"

if [[ "$SKIP_DB_CHECK" -eq 1 ]]; then
  log_warn "Skipping DB readiness checks (--skip-db-check)."
else
  post_deploy_db_check
fi

if [[ "$SEED_ADMIN" -eq 1 ]]; then
  run_admin_seed
fi

if [[ "$RUN_LETSENCRYPT" -eq 1 ]]; then
  if [[ -n "$LE_DOMAIN" && -n "$LE_EMAIL" ]]; then
    run_cmd "Setup Let's Encrypt cert" bash "$REPO_ROOT/deploy/setup-letsencrypt.sh" "$LE_DOMAIN" "$LE_EMAIL"
  elif [[ -n "$LE_DOMAIN" ]]; then
    run_cmd "Setup Let's Encrypt cert" bash "$REPO_ROOT/deploy/setup-letsencrypt.sh" "$LE_DOMAIN"
  else
    run_cmd "Setup Let's Encrypt cert" bash "$REPO_ROOT/deploy/setup-letsencrypt.sh"
  fi
else
  log_info "Let's Encrypt step skipped (self-signed flow remains active)."
fi

connectivity_gate "$CONNECTIVITY_MODE"

echo ""
echo "====================================================================="
echo " Completed start-stack workflow"
echo "   Pass: $PASS_COUNT"
echo "   Warn: $WARN_COUNT"
echo "====================================================================="
echo "Useful follow-ups:"
echo "  docker stack ps placeware"
echo "  docker service logs placeware_backend --tail 80"
echo "  docker service logs placeware_frontend --tail 40"
echo ""