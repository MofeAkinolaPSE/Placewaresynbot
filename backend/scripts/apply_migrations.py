#!/usr/bin/env python3
"""Apply SQL migration files in `backend/migrations` in filename order.

This script records applied migrations in a `schema_migrations` table and
executes each SQL file as a single script against Postgres. It avoids naive
semicolon splitting so functions and dollar-quoted blocks remain intact.

Usage:
  Set environment variable `DATABASE_URL` (Postgres DSN), then run:
    python apply_migrations.py

If `DATABASE_URL` is not set, the script will try sensible defaults.
"""
from __future__ import annotations
import os
import sys
import pathlib
import datetime
from urllib.parse import urlsplit, urlunsplit
import psycopg2


def get_database_url() -> str:
    return os.getenv("DATABASE_URL") or os.getenv("POSTGRES_URL") or "postgresql://postgres:postgres@localhost:5432/postgres"


def redact_dsn(dsn: str) -> str:
    parts = urlsplit(dsn)
    if not parts.netloc:
        return dsn
    netloc = parts.netloc
    if "@" not in netloc:
        return dsn
    userinfo, host = netloc.rsplit("@", 1)
    username = userinfo.split(":", 1)[0]
    redacted_userinfo = f"{username}:***" if username else "***"
    return urlunsplit((parts.scheme, f"{redacted_userinfo}@{host}", parts.path, parts.query, parts.fragment))


def print_server_fingerprint(conn):
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT
                current_database(),
                current_user,
                coalesce(inet_server_addr()::text, 'local_socket') as server_addr,
                inet_server_port(),
                version()
            """
        )
        database_name, db_user, server_addr, server_port, version = cur.fetchone()
    print(
        "Connected to "
        f"db={database_name} user={db_user} host={server_addr} port={server_port} "
        f"version={version}"
    )


def validate_pgvector_preflight(conn, migration_files: list[pathlib.Path]):
    if not any(path.name == "000_full_schema_with_rls.sql" for path in migration_files):
        return

    with conn.cursor() as cur:
        cur.execute("SELECT EXISTS(SELECT 1 FROM pg_available_extensions WHERE name = 'vector')")
        vector_available = bool(cur.fetchone()[0])
        cur.execute("SELECT EXISTS(SELECT 1 FROM pg_extension WHERE extname = 'vector')")
        vector_installed = bool(cur.fetchone()[0])

    if not vector_available:
        raise RuntimeError(
            "pgvector extension is not available on the active database server. "
            "This usually means your app is connected to a different Postgres instance than the pgvector-enabled one. "
            "Repoint DATABASE_URL to the pgvector-enabled server before running migrations."
        )

    if not vector_installed:
        with conn.cursor() as cur:
            cur.execute("CREATE EXTENSION IF NOT EXISTS vector")
        conn.commit()
        print("Enabled extension: vector")


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
    with conn.cursor() as cur:
        try:
            cur.execute(sql)
            conn.commit()
        except Exception as e:
            conn.rollback()
            print(f"Error executing {path.name}: {e}")
            raise


def main():
    db_url = get_database_url()
    print(f"Using DATABASE_URL={redact_dsn(db_url)}")
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
        print_server_fingerprint(conn)
        validate_pgvector_preflight(conn, files)
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
