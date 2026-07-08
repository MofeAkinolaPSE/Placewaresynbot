"""loader.py — Upload extracted Sage 50 data to Synbot backend.

Two modes:
  1. HTTP upload  — POST /sage/import/batch  (multipart ZIP)
  2. Direct DB    — psycopg2 INSERT ... ON CONFLICT DO NOTHING
"""
from __future__ import annotations

import csv
import io
import json
import logging
import uuid
import zipfile
from typing import Any, Dict, List, Optional

log = logging.getLogger("loader")


# ---------------------------------------------------------------------------
# HTTP upload via /sage/import/batch
# ---------------------------------------------------------------------------

def upload_to_backend(
    datasets: Dict[str, List[Dict[str, Any]]],
    backend_url: str,
    token: str,
    timeout: int = 600,
) -> Dict[str, Any]:
    """Bundle datasets into a ZIP and POST to /sage/import/batch.

    datasets: {file_type: [row_dict, ...]}
    backend_url: base URL of the Synbot backend (e.g. http://localhost or http://backend:8000)
    token: JWT access token with admin/finance role

    Returns the parsed JSON response.
    """
    try:
        import requests
        import urllib3
    except ImportError:
        raise RuntimeError(
            "requests not installed. Run: pip install requests  or  "
            "D:\\py38\\python.exe -m pip install requests"
        )

    zip_bytes = _build_zip(datasets)
    url = _resolve_batch_url(backend_url)

    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

    log.info(f"Uploading {len(zip_bytes) // 1024} KB ZIP to {url}")

    # Use allow_redirects=False so we can re-POST after nginx's HTTP→HTTPS 301.
    # Following a 301 automatically converts POST → GET, which returns 405.
    def _do_post(target_url: str) -> "requests.Response":
        return requests.post(
            target_url,
            headers={"Authorization": f"Bearer {token}"},
            files={"file": ("sage_export.zip", zip_bytes, "application/zip")},
            timeout=timeout,
            verify=False,
            allow_redirects=False,
        )

    resp = _do_post(url)

    # Follow 3xx redirects manually so the method stays POST
    _followed = 0
    while resp.status_code in (301, 302, 303, 307, 308) and _followed < 3:
        location = resp.headers.get("Location", "")
        if not location:
            break
        log.info(f"Redirected ({resp.status_code}) → {location}")
        resp = _do_post(location)
        _followed += 1

    if resp.status_code == 405:
        raise RuntimeError(
            "Upload failed: HTTP 405 Method Not Allowed.\n"
            "Tip: bypass nginx by pointing directly at FastAPI — use:\n"
            "  --upload http://localhost:8000"
        )

    if resp.status_code not in (200, 202):
        raise RuntimeError(
            f"Upload failed: HTTP {resp.status_code}\n{resp.text[:500]}"
        )

    try:
        return resp.json()
    except ValueError:
        return {"raw": resp.text[:500]}


def _resolve_batch_url(backend_url: str) -> str:
    """Ensure the URL ends with /sage/import/batch."""
    url = backend_url.rstrip("/")
    if not url.endswith("/sage/import/batch"):
        url = url + "/sage/import/batch"
    return url


def _build_zip(datasets: Dict[str, List[Dict[str, Any]]]) -> bytes:
    """Build an in-memory ZIP with one CSV per dataset."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        manifest = {
            "source": "sage50_2013_btrieve",
            "generator": "placeware_data_assimilation",
            "datasets": {k: len(v) for k, v in datasets.items() if v},
        }
        zf.writestr("manifest.json", json.dumps(manifest, indent=2))

        for file_type, rows in datasets.items():
            if not rows:
                continue
            csv_bytes = _rows_to_csv_bytes(rows)
            zf.writestr(f"{file_type}.csv", csv_bytes)

    return buf.getvalue()


def _rows_to_csv_bytes(rows: List[Dict[str, Any]]) -> bytes:
    if not rows:
        return b""
    buf = io.StringIO()
    writer = csv.DictWriter(
        buf,
        fieldnames=list(rows[0].keys()),
        extrasaction="ignore",
        lineterminator="\r\n",
    )
    writer.writeheader()
    for row in rows:
        # Convert None → "" for CSV
        writer.writerow({k: ("" if v is None else str(v)) for k, v in row.items()})
    return buf.getvalue().encode("utf-8-sig")


# ---------------------------------------------------------------------------
# Direct PostgreSQL insert
# ---------------------------------------------------------------------------

def upload_direct_db(
    datasets: Dict[str, List[Dict[str, Any]]],
    db_url: str,
    target_tables: Dict[str, str],
) -> Dict[str, int]:
    """Insert datasets directly into PostgreSQL snapshot tables.

    target_tables: {file_type: table_name}
    Returns: {file_type: rows_inserted}
    """
    try:
        import psycopg2
        import psycopg2.extras
    except ImportError:
        raise RuntimeError(
            "psycopg2 not installed. Run: pip install psycopg2-binary  or use --upload instead."
        )

    batch_id = str(uuid.uuid4())
    results: Dict[str, int] = {}

    conn = psycopg2.connect(db_url)
    conn.autocommit = False

    try:
        with conn.cursor() as cur:
            for file_type, rows in datasets.items():
                if not rows:
                    results[file_type] = 0
                    continue

                table = target_tables.get(file_type)
                if not table:
                    log.warning(f"No target table for {file_type} — skipped")
                    continue

                # Stamp batch_id and imported_at
                import datetime
                imported_at = datetime.datetime.utcnow().isoformat()

                stamped = []
                for row in rows:
                    r = dict(row)
                    r["batch_id"] = batch_id
                    r["imported_at"] = imported_at
                    stamped.append(r)

                # Build INSERT ... ON CONFLICT DO NOTHING
                cols = list(stamped[0].keys())
                col_str = ", ".join(f'"{c}"' for c in cols)
                val_str = ", ".join(f"%({c})s" for c in cols)
                sql = f'INSERT INTO "{table}" ({col_str}) VALUES ({val_str}) ON CONFLICT DO NOTHING'

                psycopg2.extras.execute_batch(cur, sql, stamped, page_size=500)
                results[file_type] = len(stamped)
                log.info(f"  {table}: {len(stamped)} rows inserted")

        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

    return results
