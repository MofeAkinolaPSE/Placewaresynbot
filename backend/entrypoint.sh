#!/bin/sh
set -e

echo "=========================================="
echo "  PlacewareBot — Starting up"
echo "=========================================="

echo "[1/2] Running database migrations..."
python scripts/apply_migrations.py

echo "[2/2] Starting API server..."
exec uvicorn app:app --host 0.0.0.0 --port 8000
