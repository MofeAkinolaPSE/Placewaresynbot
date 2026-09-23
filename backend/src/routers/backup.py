"""
Admin data export — ACE / Placeware
===================================
Lets an administrator download the client's own data on demand, so weekly
backups don't depend on someone having shell access to the server.

Two formats, chosen automatically:

  * **SQL** (preferred) — a real `pg_dump`, directly restorable with psql.
    Requires the `pg_dump` binary in the backend image, at a major version
    >= the server's (pg_dump refuses to dump a newer server than itself).
  * **CSV bundle** (fallback) — a ZIP with one CSV per table plus a manifest,
    produced through `COPY ... TO STDOUT` over the normal connection. No
    binaries, no superuser file access, works everywhere.

The endpoint deliberately reports which one it produced rather than quietly
handing over a lesser artefact: a client who thinks they hold a restorable
backup and actually holds a pile of CSVs finds out at the worst moment.

Access: admin only, and every download is written to the audit log. This
streams the entire database, including personal data -- treat the resulting
file as the most sensitive artefact the system produces.
"""

from __future__ import annotations

import csv
import datetime as dt
import io
import logging
import os
import shutil
import subprocess
import zipfile
from typing import Any, Dict, Iterator, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse

from src.db import audit_event, db
from src.middleware import require_role

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/admin/backup", tags=["Admin Backup"])

_require_admin = require_role("admin")

# Tables holding credentials or tokens. Excluded from the CSV bundle: a
# routine weekly backup shouldn't hand out password hashes and refresh
# tokens in plain CSV. A real pg_dump is a different case -- it exists to
# restore the system exactly, and omitting these would make it useless.
_SENSITIVE_TABLES = {
    "placeware_refresh_tokens",
    "auth_device_keys",
}


def _list_tables() -> List[str]:
    """Base tables in the public schema. Uses a raw cursor because the
    TableQuery helper prefixes every name with 'public.', which cannot address
    information_schema."""
    conn = db.pool.getconn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT table_name FROM information_schema.tables "
                "WHERE table_schema = 'public' AND table_type = 'BASE TABLE' "
                "ORDER BY table_name"
            )
            return [r[0] for r in cur.fetchall()]
    finally:
        conn.commit()
        db.pool.putconn(conn)


def _pg_dump_path() -> Optional[str]:
    return shutil.which("pg_dump")


def _stream_pg_dump(database_url: str) -> Iterator[bytes]:
    """Stream a gzipped pg_dump straight through, so a large database never
    has to be buffered in memory or staged on disk."""
    cmd = [_pg_dump_path(), "--no-owner", "--no-acl", "--compress=9", database_url]
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    try:
        assert proc.stdout is not None
        while True:
            chunk = proc.stdout.read(64 * 1024)
            if not chunk:
                break
            yield chunk
        proc.wait(timeout=30)
        if proc.returncode != 0:
            err = (proc.stderr.read() if proc.stderr else b"").decode("utf-8", "replace")
            logger.error("pg_dump failed (%s): %s", proc.returncode, err[:500])
    finally:
        if proc.poll() is None:
            proc.kill()


def _build_csv_bundle(tables: List[str]) -> bytes:
    """One CSV per table plus a manifest, as a ZIP.

    Uses COPY ... TO STDOUT, which runs client-side over the existing
    connection -- no superuser, no server-side file writes, no shelling out.
    """
    conn = db.pool.getconn()
    buf = io.BytesIO()
    manifest: List[Dict[str, Any]] = []
    try:
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            for table in tables:
                if table in _SENSITIVE_TABLES:
                    manifest.append({"table": table, "rows": None, "note": "excluded (credentials)"})
                    continue
                out = io.StringIO()
                try:
                    with conn.cursor() as cur:
                        # Identifier is from information_schema, never user
                        # input, but quote it anyway so mixed-case or
                        # reserved-word table names don't break the copy.
                        cur.copy_expert(f'COPY "{table}" TO STDOUT WITH CSV HEADER', out)
                    conn.commit()
                except Exception as exc:
                    conn.rollback()
                    logger.warning("backup: skipping table %s: %s", table, exc)
                    manifest.append({"table": table, "rows": None, "note": f"failed: {exc}"[:200]})
                    continue
                text = out.getvalue()
                zf.writestr(f"tables/{table}.csv", text)
                manifest.append({"table": table, "rows": max(0, text.count("\n") - 1)})

            meta = io.StringIO()
            w = csv.writer(meta)
            w.writerow(["table", "rows", "note"])
            for m in manifest:
                w.writerow([m["table"], m.get("rows", ""), m.get("note", "")])
            zf.writestr("manifest.csv", meta.getvalue())
            zf.writestr(
                "README.txt",
                "Placeware / ACE data export\n"
                f"Generated: {dt.datetime.utcnow().isoformat()}Z\n\n"
                "One CSV per table under tables/, plus manifest.csv listing row counts.\n"
                "This is a DATA export, not a restorable SQL dump: it carries no schema,\n"
                "indexes or constraints. For a restorable backup use the SQL format\n"
                "(requires pg_dump in the backend image) or the server-side\n"
                "deploy/backup.sh job.\n\n"
                "Contains personal and commercial data. Store it encrypted.\n",
            )
    finally:
        db.pool.putconn(conn)
    return buf.getvalue()


@router.get("/info")
async def backup_info(_u=Depends(_require_admin)):
    """What a download would produce, so the UI can set expectations before
    the user commits to a large transfer."""
    try:
        tables = _list_tables()
        size = None
        conn = db.pool.getconn()
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT pg_size_pretty(pg_database_size(current_database()))")
                size = cur.fetchone()[0]
        except Exception:
            pass
        finally:
            conn.commit()
            db.pool.putconn(conn)
        has_dump = _pg_dump_path() is not None
        return {
            "format": "sql" if has_dump else "csv",
            "restorable": has_dump,
            "table_count": len(tables),
            "database_size": size,
            "excluded_tables": sorted(_SENSITIVE_TABLES) if not has_dump else [],
            "note": (
                "Full pg_dump, restorable with psql."
                if has_dump
                else "CSV bundle (data only, no schema). Install postgresql-client "
                     "in the backend image to enable restorable SQL dumps."
            ),
        }
    except Exception as exc:
        logger.error("backup info error: %s", exc)
        raise HTTPException(500, detail="Failed to read backup info")


@router.get("/download")
async def download_backup(
    fmt: str = Query("auto", pattern="^(auto|csv)$"),
    user: Dict[str, Any] = Depends(_require_admin),
):
    """Download a full backup of this deployment's data."""
    stamp = dt.datetime.utcnow().strftime("%Y-%m-%d")
    actor = user.get("sub") if isinstance(user, dict) else None
    database_url = os.getenv("DATABASE_URL", "")
    use_sql = fmt == "auto" and _pg_dump_path() and database_url

    try:
        audit_event(
            "admin_backup_downloaded",
            {"format": "sql" if use_sql else "csv"},
            actor_id=actor,
            event_class="security",
            action="backup_download",
            subject_type="database",
            subject_id="synbot",
        )
    except Exception:
        pass

    if use_sql:
        filename = f"placeware_backup_{stamp}.sql.gz"
        return StreamingResponse(
            _stream_pg_dump(database_url),
            media_type="application/gzip",
            headers={
                "Content-Disposition": f'attachment; filename="{filename}"',
                "X-Backup-Format": "sql",
            },
        )

    try:
        payload = _build_csv_bundle(_list_tables())
    except Exception as exc:
        logger.error("backup bundle error: %s", exc)
        raise HTTPException(500, detail="Failed to build backup bundle")

    filename = f"placeware_data_export_{stamp}.zip"
    return StreamingResponse(
        io.BytesIO(payload),
        media_type="application/zip",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "X-Backup-Format": "csv",
        },
    )
