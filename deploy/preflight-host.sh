#!/usr/bin/env bash
# deploy/preflight-host.sh — Validate host prerequisites before hardening/deploy.
#
# Usage:
#   bash deploy/preflight-host.sh
#
# Exit codes:
#   0 = preflight passed (no blocking errors)
#   1 = one or more blocking checks failed

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
BACKEND_DIR="$REPO_ROOT/backend"

PASS_COUNT=0
WARN_COUNT=0
FAIL_COUNT=0

pass() { echo "[PASS] $*"; PASS_COUNT=$((PASS_COUNT + 1)); }
warn() { echo "[WARN] $*"; WARN_COUNT=$((WARN_COUNT + 1)); }
fail() { echo "[FAIL] $*"; FAIL_COUNT=$((FAIL_COUNT + 1)); }

check_cmd() {
  local cmd="$1"
  if command -v "$cmd" >/dev/null 2>&1; then
    pass "Command available: $cmd"
  else
    fail "Missing command: $cmd"
  fi
}

echo "[preflight] Repository root: $REPO_ROOT"

# Basic repository structure checks
[[ -d "$BACKEND_DIR" ]] && pass "Found backend directory" || fail "Missing backend directory"
[[ -d "$REPO_ROOT/SynbotUI" ]] && pass "Found SynbotUI directory" || fail "Missing SynbotUI directory"
[[ -d "$REPO_ROOT/deploy" ]] && pass "Found deploy directory" || fail "Missing deploy directory"

# Core host command checks
check_cmd docker
check_cmd systemctl
check_cmd curl
check_cmd python3

# Docker daemon access
if docker info >/dev/null 2>&1; then
  pass "Docker daemon reachable by current user"
else
  fail "Docker daemon not reachable (user may need docker group membership or daemon is down)"
fi

# SSH server checks (for harden-ssh.sh compatibility)
if command -v sshd >/dev/null 2>&1; then
  pass "OpenSSH server binary detected"
else
  fail "OpenSSH server binary not found (install openssh-server before hardening)"
fi

if [[ -f /etc/ssh/sshd_config ]]; then
  pass "OpenSSH config file found at /etc/ssh/sshd_config"
else
  warn "OpenSSH config not found at /etc/ssh/sshd_config (set SSHD_CONFIG override if using a custom path)"
fi

if systemctl list-unit-files 2>/dev/null | grep -q '^ssh\\.service'; then
  pass "Detected SSH service unit: ssh.service"
elif systemctl list-unit-files 2>/dev/null | grep -q '^sshd\\.service'; then
  pass "Detected SSH service unit: sshd.service"
else
  fail "No ssh/sshd systemd service unit found"
fi

# Backend env contract checks
if [[ -f "$BACKEND_DIR/.env" ]]; then
  pass "backend/.env exists"

  # Detect malformed lines early (anything non-empty that is not comment or KEY=VALUE).
  while IFS= read -r env_line || [ -n "$env_line" ]; do
    case "$env_line" in
      ''|'#'*) continue ;;
    esac
    if [[ ! "$env_line" =~ ^[A-Za-z_][A-Za-z0-9_]*= ]]; then
      fail "backend/.env malformed line (not KEY=VALUE): $env_line"
    fi
  done < "$BACKEND_DIR/.env"

  REQUIRED_ENV_KEYS=(
    DEEPSEEK_API_KEY
    DEEPSEEK_MODEL
    EMAIL_FROM
    EMAIL_PASS
    POSTGRES_PASSWORD
    JWT_SECRET
    ADMIN_PASSWORD
    SAGE_BRIDGE_URL
    SAGE_BRIDGE_KEY
    SAGE_BRIDGE_WEBHOOK_SECRET
  )

  for key in "${REQUIRED_ENV_KEYS[@]}"; do
    if grep -q "^${key}=" "$BACKEND_DIR/.env"; then
      value="$(grep "^${key}=" "$BACKEND_DIR/.env" | tail -1 | cut -d'=' -f2-)"
      if [[ -n "$value" ]]; then
        pass "backend/.env key present: $key"
      else
        fail "backend/.env key is empty: $key"
      fi
    else
      fail "backend/.env key missing: $key"
    fi
  done

  if grep -q '^DEV_TOKEN_ENABLED=0$' "$BACKEND_DIR/.env"; then
    pass "DEV_TOKEN_ENABLED is 0"
  else
    warn "DEV_TOKEN_ENABLED is not 0 in backend/.env"
  fi
else
  fail "backend/.env missing (copy backend/.env.example and fill secrets)"
fi

# Compatibility check for fail2ban nginx jail
if [[ -f /var/log/nginx/error.log ]]; then
  pass "Host nginx error log exists for optional fail2ban nginx jail"
else
  warn "Host nginx error log missing; setup-fail2ban will enable sshd jail only"
fi

# Deploy script presence checks
for file in \
  "$REPO_ROOT/deploy/harden-ssh.sh" \
  "$REPO_ROOT/deploy/setup-firewall.sh" \
  "$REPO_ROOT/deploy/setup-fail2ban.sh" \
  "$REPO_ROOT/deploy/init-swarm.sh" \
  "$REPO_ROOT/deploy/setup-letsencrypt.sh"; do
  if [[ -f "$file" ]]; then
    pass "Found script: $file"
  else
    fail "Missing script: $file"
  fi
done

# Summary
echo ""
echo "[preflight] Summary: ${PASS_COUNT} pass, ${WARN_COUNT} warn, ${FAIL_COUNT} fail"

if [[ "$FAIL_COUNT" -gt 0 ]]; then
  echo "[preflight] BLOCKED: Fix failures before production hardening/deploy."
  exit 1
fi

echo "[preflight] OK: No blocking failures detected."
exit 0
