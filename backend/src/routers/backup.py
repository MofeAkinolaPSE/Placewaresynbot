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


# ---------------------------------------------------------------------------
# Scheduled backups (daily / weekly / monthly), prepared on the server and
# downloaded by an administrator to their desktop or an external drive.
# ---------------------------------------------------------------------------

BACKUP_DIR = os.getenv("BACKUP_DIR", "/backend/backups")
_TZ_NAME = os.getenv("APP_TIMEZONE", "Africa/Lagos")
_LOCK_KEY = 72031907  # pg advisory lock: one backup at a time across workers


def _tz():
    try:
        from zoneinfo import ZoneInfo
        return ZoneInfo(_TZ_NAME)
    except Exception:
        return dt.timezone.utc


class _Conn:
    def __enter__(self):
        self.c = db.pool.getconn()
        return self.c

    def __exit__(self, exc_type, *_):
        if exc_type:
            self.c.rollback()
        else:
            self.c.commit()
        db.pool.putconn(self.c)


def _rows(cur) -> List[Dict[str, Any]]:
    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, r)) for r in cur.fetchall()]


def _settings(cur) -> Dict[str, Any]:
    cur.execute("SELECT frequency, run_hour, weekday, month_day, keep_last, updated_by, updated_at FROM system_backup_settings WHERE id=1")
    r = _rows(cur)
    return r[0] if r else {"frequency": "off", "run_hour": 18, "weekday": 4, "month_day": 1, "keep_last": 8}


def _last_due(s: Dict[str, Any], now: dt.datetime) -> Optional[dt.datetime]:
    """The most recent moment a backup was due under the schedule (local time)."""
    f = s["frequency"]
    if f == "off":
        return None
    at = now.replace(hour=int(s["run_hour"]), minute=0, second=0, microsecond=0)
    if f == "daily":
        return at if at <= now else at - dt.timedelta(days=1)
    if f == "weekly":
        at -= dt.timedelta(days=(at.weekday() - int(s["weekday"])) % 7)
        return at if at <= now else at - dt.timedelta(days=7)
    at = at.replace(day=int(s["month_day"]))
    if at > now:
        prev = (at.replace(day=1) - dt.timedelta(days=1))
        at = at.replace(year=prev.year, month=prev.month)
    return at


def _next_due(s: Dict[str, Any], now: dt.datetime) -> Optional[dt.datetime]:
    last = _last_due(s, now)
    if not last:
        return None
    if s["frequency"] == "daily":
        return last + dt.timedelta(days=1)
    if s["frequency"] == "weekly":
        return last + dt.timedelta(days=7)
    nxt = (last.replace(day=28) + dt.timedelta(days=4)).replace(day=int(s["month_day"]))
    return nxt


def _write_backup(path: str) -> str:
    """Write the backup file; returns its format. A real pg_dump when the binary is present."""
    database_url = os.getenv("DATABASE_URL", "")
    if _pg_dump_path() and database_url:
        proc = subprocess.run([_pg_dump_path(), "--no-owner", "--no-acl", "--compress=9", "-f", path, database_url],
                              capture_output=True, timeout=3 * 3600)
        if proc.returncode != 0:
            raise RuntimeError(proc.stderr.decode("utf-8", "replace")[:500] or "pg_dump failed")
        return "sql"
    with open(path, "wb") as fh:
        fh.write(_build_csv_bundle(_list_tables()))
    return "csv"


def create_backup(kind: str, actor: Optional[str]) -> Dict[str, Any]:
    os.makedirs(BACKUP_DIR, exist_ok=True)
    with _Conn() as c, c.cursor() as cur:
        cur.execute("SELECT pg_try_advisory_lock(%s)", (_LOCK_KEY,))
        if not cur.fetchone()[0]:
            raise HTTPException(409, detail="A backup is already being prepared")
        try:
            cur.execute("INSERT INTO system_backups (kind, requested_by) VALUES (%s,%s) RETURNING id, started_at", (kind, actor))
            bid, started = cur.fetchone()
            c.commit()
            stamp = started.astimezone(_tz()).strftime("%Y-%m-%d_%H%M")
            ext = "sql.gz" if _pg_dump_path() else "zip"
            name = f"placeware_backup_{stamp}_{kind.lower()}.{ext}"
            path = os.path.join(BACKUP_DIR, name)
            try:
                fmt = _write_backup(path + ".partial")
                os.replace(path + ".partial", path)
                import hashlib
                h = hashlib.sha256()
                with open(path, "rb") as fh:
                    for chunk in iter(lambda: fh.read(1 << 20), b""):
                        h.update(chunk)
                cur.execute("""UPDATE system_backups SET status='READY', format=%s, file_name=%s, size_bytes=%s, sha256=%s,
                               finished_at=now() WHERE id=%s""", (fmt, name, os.path.getsize(path), h.hexdigest(), bid))
            except Exception as exc:
                logger.exception("backup failed")
                try:
                    os.remove(path + ".partial")
                except OSError:
                    pass
                cur.execute("UPDATE system_backups SET status='FAILED', error=%s, finished_at=now() WHERE id=%s", (str(exc)[:500], bid))
            c.commit()
            _prune(cur, int(_settings(cur)["keep_last"]))
            c.commit()
            cur.execute("SELECT * FROM system_backups WHERE id=%s", (bid,))
            return _rows(cur)[0]
        finally:
            cur.execute("SELECT pg_advisory_unlock(%s)", (_LOCK_KEY,))


def _prune(cur, keep: int) -> None:
    """Keep the newest `keep` backups on the server; older files are removed (they were offered
    for download - the client's copies are on their own drives)."""
    cur.execute("""SELECT id, file_name FROM system_backups WHERE status='READY' ORDER BY started_at DESC OFFSET %s""", (keep,))
    for bid, name in cur.fetchall():
        try:
            if name:
                os.remove(os.path.join(BACKUP_DIR, name))
        except OSError:
            pass
        cur.execute("UPDATE system_backups SET status='DELETED' WHERE id=%s", (bid,))


def tick() -> Optional[Dict[str, Any]]:
    """Called every few minutes: prepare the scheduled backup when it is due."""
    with _Conn() as c, c.cursor() as cur:
        cur.execute("""UPDATE system_backups SET status='FAILED', error='Interrupted (server restarted while preparing)',
                       finished_at=now() WHERE status='RUNNING' AND started_at < now() - interval '6 hours'""")
        s = _settings(cur)
        due = _last_due(s, dt.datetime.now(_tz()))
        if not due:
            return None
        cur.execute("""SELECT 1 FROM system_backups WHERE kind='SCHEDULED' AND status IN ('READY','RUNNING','DELETED')
                       AND started_at >= %s LIMIT 1""", (due,))
        if cur.fetchone():
            return None
        cur.execute("""SELECT 1 FROM system_backups WHERE kind='SCHEDULED' AND status='FAILED' AND started_at >= %s
                       AND started_at > now() - interval '1 hour' LIMIT 1""", (due,))
        if cur.fetchone():
            return None  # failed recently: retry in an hour, not every tick
    try:
        return create_backup("SCHEDULED", "schedule")
    except HTTPException:
        return None


def _summary(cur) -> Dict[str, Any]:
    s = _settings(cur)
    now = dt.datetime.now(_tz())
    cur.execute("""SELECT id, kind, status, format, file_name, size_bytes, sha256, error, requested_by, started_at, finished_at,
                          download_count, last_downloaded_at, last_downloaded_by
                   FROM system_backups WHERE status <> 'DELETED' ORDER BY started_at DESC LIMIT 30""")
    items = _rows(cur)
    waiting = next((b for b in items if b["status"] == "READY" and not b["download_count"]), None)
    return {"settings": s, "timezone": _TZ_NAME, "next_due": _next_due(s, now), "items": items,
            "awaiting_download": waiting, "restorable": _pg_dump_path() is not None}


def _actor(user: Any) -> Optional[str]:
    """The signed-in person's email (the token carries only their id)."""
    if not isinstance(user, dict):
        return None
    if user.get("email"):
        return user["email"]
    uid = user.get("sub") or user.get("user_id")
    try:
        with _Conn() as c, c.cursor() as cur:
            cur.execute("SELECT email FROM placeware_users WHERE id::text=%s", (str(uid),))
            r = cur.fetchone()
            return r[0] if r and r[0] else uid
    except Exception:
        return uid


@router.get("/schedule")
async def backup_schedule(_u=Depends(_require_admin)):
    with _Conn() as c, c.cursor() as cur:
        return _summary(cur)


@router.put("/schedule")
async def save_backup_schedule(payload: Dict[str, Any], user: Dict[str, Any] = Depends(_require_admin)):
    f = str(payload.get("frequency") or "").lower()
    if f not in ("off", "daily", "weekly", "monthly"):
        raise HTTPException(422, detail="Choose daily, weekly, monthly or off")
    try:
        hour, wd, md, keep = (int(payload.get("run_hour", 18)), int(payload.get("weekday", 4)),
                              int(payload.get("month_day", 1)), int(payload.get("keep_last", 8)))
    except (TypeError, ValueError):
        raise HTTPException(422, detail="Hour, weekday, day of month and number to keep must be whole numbers")
    if not (0 <= hour <= 23 and 0 <= wd <= 6 and 1 <= md <= 28 and 1 <= keep <= 60):
        raise HTTPException(422, detail="Hour 0-23, weekday 0-6, day of month 1-28, keep 1-60")
    actor = _actor(user)
    with _Conn() as c, c.cursor() as cur:
        cur.execute("""UPDATE system_backup_settings SET frequency=%s, run_hour=%s, weekday=%s, month_day=%s, keep_last=%s,
                       updated_by=%s, updated_at=now() WHERE id=1""", (f, hour, wd, md, keep, actor))
        try:
            audit_event("backup_schedule_changed", {"frequency": f, "run_hour": hour, "weekday": wd, "month_day": md,
                                                     "keep_last": keep}, actor_id=actor, event_class="security",
                        action="backup_schedule", subject_type="database", subject_id="synbot")
        except Exception:
            pass
        c.commit()
        return _summary(cur)


@router.post("/run")
async def run_backup_now(user: Dict[str, Any] = Depends(_require_admin)):
    import asyncio
    actor = _actor(user)
    return await asyncio.to_thread(create_backup, "MANUAL", actor)


@router.get("/files/{backup_id}/download")
async def download_prepared_backup(backup_id: str, user: Dict[str, Any] = Depends(_require_admin)):
    from fastapi.responses import FileResponse
    actor = _actor(user)
    with _Conn() as c, c.cursor() as cur:
        cur.execute("SELECT file_name, format, sha256 FROM system_backups WHERE id::text=%s AND status='READY'", (backup_id,))
        r = cur.fetchone()
        if not r or not r[0]:
            raise HTTPException(404, detail="That backup is no longer on the server")
        path = os.path.join(BACKUP_DIR, r[0])
        if not os.path.exists(path):
            cur.execute("UPDATE system_backups SET status='DELETED' WHERE id::text=%s", (backup_id,))
            raise HTTPException(404, detail="That backup file is missing on the server")
        cur.execute("""UPDATE system_backups SET download_count=download_count+1, last_downloaded_at=now(), last_downloaded_by=%s
                       WHERE id::text=%s""", (actor, backup_id))
    try:
        audit_event("admin_backup_downloaded", {"format": r[1], "file": r[0], "sha256": r[2]}, actor_id=actor,
                    event_class="security", action="backup_download", subject_type="database", subject_id="synbot")
    except Exception:
        pass
    return FileResponse(path, filename=r[0], media_type="application/gzip" if r[1] == "sql" else "application/zip",
                        headers={"X-Backup-Format": r[1] or "", "X-Backup-Sha256": r[2] or ""})


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
