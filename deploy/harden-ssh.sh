#!/usr/bin/env bash
# deploy/harden-ssh.sh — Harden OpenSSH server configuration.
#
# Run ONCE on the Ubuntu VM as root:
#   sudo bash deploy/harden-ssh.sh
#
# SAFETY: This script verifies that an authorized_keys file exists for the
# current (non-root) user before disabling password authentication.
# It will ABORT if no SSH key is found, preventing lockout.
# ─────────────────────────────────────────────────────────────────────────────

set -euo pipefail

# Resolve OpenSSH server binary and config path dynamically.
SSHD_BIN="$(command -v sshd || true)"
SSHD_CONFIG="${SSHD_CONFIG:-/etc/ssh/sshd_config}"
BACKUP=""
SSH_SERVICE=""

echo "[harden-ssh] Checking prerequisites..."

if [[ -z "$SSHD_BIN" ]]; then
    echo "ERROR: 'sshd' not found. OpenSSH server is not installed."
    echo "Install it first, then rerun: sudo apt-get update && sudo apt-get install -y openssh-server"
    exit 1
fi

if [[ ! -f "$SSHD_CONFIG" ]]; then
    echo "ERROR: OpenSSH config not found at $SSHD_CONFIG"
    echo "If your distro uses a different location, rerun with:"
    echo "  sudo SSHD_CONFIG=/path/to/sshd_config bash deploy/harden-ssh.sh"
    exit 1
fi

if systemctl list-unit-files 2>/dev/null | grep -q '^ssh\.service'; then
    SSH_SERVICE="ssh"
elif systemctl list-unit-files 2>/dev/null | grep -q '^sshd\.service'; then
    SSH_SERVICE="sshd"
else
    echo "ERROR: Could not find ssh or sshd systemd service unit."
    echo "Check available units with: systemctl list-unit-files | grep -E 'ssh|sshd'"
    exit 1
fi

BACKUP="${SSHD_CONFIG}.bak.$(date +%Y%m%d_%H%M%S)"

# Safety check: ensure a non-root user with SSH keys exists
SUDO_USER_HOME=$(getent passwd "${SUDO_USER:-}" | cut -d: -f6 2>/dev/null || true)
if [[ -z "$SUDO_USER_HOME" ]]; then
    # Fallback: check for any user with authorized_keys
    SUDO_USER_HOME=$(find /home -name "authorized_keys" -maxdepth 3 2>/dev/null | head -1 | xargs dirname 2>/dev/null | xargs dirname 2>/dev/null || true)
fi

if [[ -z "$SUDO_USER_HOME" ]] || [[ ! -f "${SUDO_USER_HOME}/.ssh/authorized_keys" ]]; then
    echo "ERROR: No authorized_keys found. Add your SSH public key first:"
    echo "  ssh-copy-id user@${HOSTNAME}"
    echo "Aborting to prevent lockout."
    exit 1
fi

echo "[harden-ssh] Found authorized_keys at ${SUDO_USER_HOME}/.ssh/authorized_keys — safe to proceed."

# Backup original config
echo "[harden-ssh] Backing up ${SSHD_CONFIG} → ${BACKUP}"
cp "$SSHD_CONFIG" "$BACKUP"

apply_setting() {
    local key="$1"
    local val="$2"
    # If key exists (commented or not), replace it; otherwise append
    if grep -qiE "^#?${key}\s" "$SSHD_CONFIG"; then
        sed -i -E "s|^#?${key}\s.*|${key} ${val}|" "$SSHD_CONFIG"
    else
        echo "${key} ${val}" >> "$SSHD_CONFIG"
    fi
}

echo "[harden-ssh] Applying hardened settings..."

apply_setting "PasswordAuthentication"      "no"
apply_setting "PermitRootLogin"             "no"
apply_setting "MaxAuthTries"                "3"
apply_setting "LoginGraceTime"             "30"
apply_setting "X11Forwarding"              "no"
apply_setting "AllowTcpForwarding"         "no"
apply_setting "ClientAliveInterval"        "300"
apply_setting "ClientAliveCountMax"        "2"
apply_setting "PermitEmptyPasswords"       "no"
apply_setting "UsePAM"                     "yes"
apply_setting "Protocol"                   "2"

echo "[harden-ssh] Validating configuration..."
"$SSHD_BIN" -t -f "$SSHD_CONFIG"  # Dry-run test — aborts if config is invalid

echo "[harden-ssh] Restarting SSH service..."
systemctl restart "$SSH_SERVICE"

echo "[harden-ssh] Done. Summary of applied settings:"
grep -E "^(PasswordAuthentication|PermitRootLogin|MaxAuthTries|LoginGraceTime|X11Forwarding|AllowTcpForwarding)" "$SSHD_CONFIG"
echo ""
echo "IMPORTANT: Open a second terminal and verify you can still SSH in before closing this session."
