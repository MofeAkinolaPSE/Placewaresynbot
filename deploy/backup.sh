#!/usr/bin/env bash
# deploy/backup.sh — Daily PostgreSQL backup for PlacewareBot.
#
# Creates a gzip-compressed pg_dump in /var/backups/placeware/
# Prunes backups older than 30 days.
# Installed as a systemd timer — see backup.timer and backup.service.
#
# Run manually to test:
#   sudo bash deploy/backup.sh
# ─────────────────────────────────────────────────────────────────────────────

set -euo pipefail

BACKUP_DIR="/var/backups/placeware"
DB_CONTAINER="placeware-postgres-1"    # adjust if container name differs
DB_USER="postgres"
DB_NAME="synbot_demo"
RETAIN_DAYS=30
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
OUTFILE="${BACKUP_DIR}/synbot_${TIMESTAMP}.sql.gz"

mkdir -p "$BACKUP_DIR"
chmod 750 "$BACKUP_DIR"

echo "[backup] Starting pg_dump of ${DB_NAME} → ${OUTFILE}"

if ! docker ps --format '{{.Names}}' | grep -q "^${DB_CONTAINER}$"; then
    # Try alternate naming convention
    DB_CONTAINER=$(docker ps --format '{{.Names}}' | grep -E 'db|postgres' | head -1 || true)
    if [[ -z "$DB_CONTAINER" ]]; then
        logger -t placeware-backup "ERROR: Postgres container not found"
        echo "[backup] ERROR: Could not find running postgres container"
        exit 1
    fi
fi

docker exec "$DB_CONTAINER" \
    pg_dump -U "$DB_USER" "$DB_NAME" \
    | gzip > "$OUTFILE"

SIZEKB=$(du -k "$OUTFILE" | cut -f1)
echo "[backup] Backup complete: ${OUTFILE} (${SIZEKB} KB)"
logger -t placeware-backup "SUCCESS: ${OUTFILE} (${SIZEKB} KB)"

# Prune old backups
echo "[backup] Pruning backups older than ${RETAIN_DAYS} days..."
find "$BACKUP_DIR" -name "synbot_*.sql.gz" -mtime "+${RETAIN_DAYS}" -delete
REMAINING=$(find "$BACKUP_DIR" -name "synbot_*.sql.gz" | wc -l)
echo "[backup] ${REMAINING} backup(s) retained in ${BACKUP_DIR}"
