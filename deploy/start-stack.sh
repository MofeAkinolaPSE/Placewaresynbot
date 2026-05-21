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

ensure_ssh_service_unit

run_cmd "Run preflight checks" bash "$REPO_ROOT/deploy/preflight-host.sh"

DO_HARDENING=0
if [[ "$SKIP_HARDENING" -eq 1 ]]; then
  DO_HARDENING=0
elif [[ "$MODE" == "first-run" || "$RUN_HARDENING" -eq 1 ]]; then
  DO_HARDENING=1
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