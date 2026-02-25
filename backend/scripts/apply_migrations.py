"""Apply SQL migration files in `backend/migrations/` to a Postgres database.

Usage:
  Set environment variable `DATABASE_URL` (Postgres DSN), then run:
    python backend/scripts/apply_migrations.py

If `DATABASE_URL` is not set, the script will default to
`postgresql://postgres:postgres@localhost:5432/postgres`.

The script creates a table `schema_migrations` to record applied files
and will skip files that are already applied.
"""
from __future__ import annotations
import os
import psycopg2
import glob
import pathlib
import sys
import datetime


def get_database_url() -> str:
    return os.getenv("DATABASE_URL") or os.getenv("POSTGRES_URL") or "postgresql://postgres:postgres@localhost:5432/postgres"


def ensure_migrations_table(conn):
    with conn.cursor() as cur:
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS schema_migrations (
                id SERIAL PRIMARY KEY,
                filename TEXT NOT NULL UNIQUE,
                applied_at TIMESTAMP WITH TIME ZONE NOT NULL
            )
            """
        )
        conn.commit()


def already_applied(conn, filename: str) -> bool:
    with conn.cursor() as cur:
        cur.execute("SELECT 1 FROM schema_migrations WHERE filename = %s LIMIT 1", (filename,))
        return cur.fetchone() is not None


def record_applied(conn, filename: str):
    with conn.cursor() as cur:
        cur.execute("INSERT INTO schema_migrations (filename, applied_at) VALUES (%s, %s)", (filename, datetime.datetime.utcnow()))
        conn.commit()


def apply_sql_file(conn, path: pathlib.Path):
    print(f"Applying {path.name}...")
    sql = path.read_text(encoding="utf-8")
    # Split on semicolons and execute statements safely
    statements = [s.strip() for s in sql.split(";") if s.strip()]
    with conn.cursor() as cur:
        for stmt in statements:
            try:
                cur.execute(stmt)
            except Exception as e:
                print(f"Error executing statement in {path.name}: {e}")
                conn.rollback()
                raise
        conn.commit()


def main():
    db_url = get_database_url()
    print(f"Using DATABASE_URL={db_url}")
    migrations_dir = pathlib.Path(__file__).resolve().parents[1] / "migrations"
    files = sorted(migrations_dir.glob("*.sql"))
    if not files:
        print("No migration files found.")
        return

    try:
        conn = psycopg2.connect(db_url)
    except Exception as e:
        print(f"Failed to connect to Postgres: {e}")
        sys.exit(1)

    try:
        ensure_migrations_table(conn)
        for f in files:
            name = f.name
            if already_applied(conn, name):
                print(f"Skipping already-applied: {name}")
                continue
            apply_sql_file(conn, f)
            record_applied(conn, name)
            print(f"Applied: {name}")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
