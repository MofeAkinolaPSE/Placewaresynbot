#!/bin/sh
set -e

echo "=========================================="
echo "  PlacewareBot — Starting up"
echo "=========================================="

echo "[1/2] Running database migrations..."
python scripts/apply_migrations.py

echo "[2/2] Starting API server..."
# Pass CMD arguments through — allows docker-compose.prod.yml to override
# the uvicorn command (e.g. add --workers 4) without duplicating migrations.
exec "$@"
