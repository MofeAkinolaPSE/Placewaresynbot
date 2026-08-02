"""
odbc_client.py — Read-only access to Sage 50 via Pervasive PSQL ODBC.

The ODBC driver installed with Sage 50 exposes the company's Pervasive database
as standard ODBC tables. All reads go through here; writes go through
sdk_client.py (the official Sage SDK) so Sage computes its own ledger postings.

All table and column names come from sage_schema.py — see that module before
changing anything here.

Fixes applied to the original implementation
--------------------------------------------
* **ORDER BY is now mandatory on scans.** The original emitted
  ``SELECT TOP 2000 * FROM ARTRANS`` with no ordering. Pervasive returns rows
  in undefined order, so once the table passed 2000 rows the window silently
  excluded new invoices — they were never synced and nothing logged it.
* **Identifiers are quoted.** ``WHERE DATE >= ?`` is a syntax error on
  Pervasive: DATE is a reserved word. All identifiers go through quote_ident().
* **Keyset pagination for scans.** The original emulated OFFSET by fetching
  ``limit + offset`` rows and slicing client-side, making the historical
  migration O(n^2) against an old Pervasive engine. scan_after() uses a
  ``WHERE key > ?`` cursor, which is O(page).
* **Connection reuse.** The original opened and closed a connection per query.
  Pervasive connection setup is expensive on Win7 hardware; a per-thread cached
  connection with health checking replaces it.
"""
from __future__ import annotations

import logging
import threading
from contextlib import contextmanager
from typing import Any, Dict, Generator, List, Optional, Tuple

import sage_schema as schema
from config import get_settings
from sage_schema import TABLE_MAP, quote_ident  # re-exported for compatibility

# pyodbc is imported lazily so that mock mode, the unit tests, and a developer
# machine without the Pervasive driver stack all work with nothing installed.
# In live mode the first real query raises a clear, actionable error instead of
# an ImportError at startup.
try:
    import pyodbc
    _ODBCError: type = pyodbc.Error
except ImportError:                                   # pragma: no cover
    pyodbc = None  # type: ignore[assignment]
    _ODBCError = Exception


def _require_pyodbc():
    if pyodbc is None:
        raise RuntimeError(
            "pyodbc is not installed, so Sage cannot be read. Install it with "
            "`pip install -r requirements.txt` using **32-bit** Python 3.9 — a "
            "64-bit interpreter cannot load the 32-bit Pervasive driver that "
            "ships with Sage 50 2013. See INSTALL.md."
        )

logger = logging.getLogger("bridge.odbc")

__all__ = [
    "TABLE_MAP", "fetch_all", "fetch_one", "scan_after", "execute_scalar",
    "list_odbc_tables", "list_columns", "get_connection", "close_all",
    "check_connection",
]


def _is_mock() -> bool:
    return get_settings().SAGE_MOCK


# ── mock support ─────────────────────────────────────────────────────────────

def _mock_fetch(
    table_key: str, limit: int, offset: int, search: Optional[str] = None
) -> List[Dict[str, Any]]:
    """Return mock data for the given table key when SAGE_MOCK=true."""
    import mock_data as md
    mapping: Dict[str, Any] = {
        "customers":       (md.MOCK_CUSTOMERS, "name"),
        "vendors":         (md.MOCK_VENDORS, "name"),
        "employees":       (md.MOCK_EMPLOYEES, "last_name"),
        "inventory":       (md.MOCK_INVENTORY, "description"),
        "accounts":        (md.MOCK_ACCOUNTS, "description"),
        "ar_transactions": (md.MOCK_INVOICES, None),
        "sales_orders":    (md.MOCK_SALES_ORDERS, None),
        "purchase_orders": (md.MOCK_PURCHASE_ORDERS, None),
        "payroll":         (md.MOCK_PAYROLL, None),
        "company":         ([md.MOCK_COMPANY], None),
        "jobs":            (md.MOCK_JOBS, None),
    }
    data, search_field_name = mapping.get(table_key, ([], None))
    if search and search_field_name:
        data = md.search_field(data, search_field_name, search)
    return md.paginate(data, limit, offset)


# ── connection handling ──────────────────────────────────────────────────────

_local = threading.local()


def _build_connection_string() -> str:
    settings = get_settings()
    if settings.SAGE_ODBC_CONN_STR:
        return settings.SAGE_ODBC_CONN_STR
    return "DSN={};".format(settings.SAGE_ODBC_DSN)


def _new_connection() -> pyodbc.Connection:
    _require_pyodbc()
    settings = get_settings()
    conn = pyodbc.connect(
        _build_connection_string(),
        autocommit=True,
        timeout=settings.ODBC_TIMEOUT_SECONDS,
    )
    logger.info("ODBC connection opened.")
    return conn


def _is_alive(conn: pyodbc.Connection) -> bool:
    """Cheap liveness probe — Pervasive drops idle connections silently."""
    try:
        conn.cursor().execute("SELECT 1").fetchone()
        return True
    except Exception:
        return False


@contextmanager
def get_connection() -> Generator[pyodbc.Connection, None, None]:
    """
    Yield this thread's ODBC connection, reconnecting if it has gone stale.

    The connection is cached per thread rather than opened per query: Pervasive
    connection setup is slow on the target hardware and the original code paid
    that cost on every single call.
    """
    conn: Optional[pyodbc.Connection] = getattr(_local, "conn", None)

    if conn is not None and not _is_alive(conn):
        logger.warning("ODBC connection went stale — reconnecting.")
        try:
            conn.close()
        except Exception:
            pass
        conn = None

    if conn is None:
        try:
            conn = _new_connection()
        except _ODBCError as exc:
            logger.error("ODBC connection failed: %s", _redact(exc))
            raise
        _local.conn = conn

    try:
        yield conn
    except _ODBCError as exc:
        # Drop the cached connection so the next call reconnects rather than
        # reusing a possibly-broken handle.
        logger.error("ODBC query error: %s", _redact(exc))
        try:
            conn.close()
        except Exception:
            pass
        _local.conn = None
        raise


def close_all() -> None:
    """Close this thread's connection. Called on shutdown."""
    conn = getattr(_local, "conn", None)
    if conn is not None:
        try:
            conn.close()
        except Exception:
            pass
        _local.conn = None


def _redact(exc: Exception) -> str:
    """
    Strip credentials out of a driver error before it reaches a log or client.

    Pervasive errors sometimes echo the full connection string, which can carry
    a UID/PWD.
    """
    text = str(exc)
    for marker in ("PWD=", "Password=", "pwd="):
        idx = text.find(marker)
        if idx != -1:
            end = text.find(";", idx)
            text = text[:idx] + marker + "***" + (text[end:] if end != -1 else "")
    return text


def check_connection() -> Tuple[bool, str]:
    """Return (ok, message). Used by /health and verify_onsite.py."""
    if _is_mock():
        return True, "mock mode"
    try:
        with get_connection() as conn:
            conn.cursor().execute("SELECT 1").fetchone()
        return True, "ok"
    except Exception as exc:
        return False, _redact(exc)


def _rows_to_dicts(cursor: pyodbc.Cursor) -> List[Dict[str, Any]]:
    """Convert cursor rows to plain dicts, lower-casing column names."""
    columns = [col[0].lower() for col in cursor.description]
    out: List[Dict[str, Any]] = []
    for row in cursor.fetchall():
        d: Dict[str, Any] = {}
        for col, val in zip(columns, row):
            # Sage pads CHAR columns; trailing spaces break equality checks
            # and make content fingerprints unstable.
            d[col] = val.rstrip() if isinstance(val, str) else val
        out.append(d)
    return out


# ── queries ──────────────────────────────────────────────────────────────────

def fetch_all(
    table_key: str,
    where: Optional[str] = None,
    params: Optional[tuple] = None,
    limit: int = 500,
    offset: int = 0,
    search: Optional[str] = None,
    order_by: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """
    ``SELECT TOP n * FROM <table> [WHERE ...] ORDER BY <key>``.

    ``order_by`` is a COLUMN NAME (not raw SQL) and is quoted. When omitted it
    defaults to the table's ordering key so results are always deterministic —
    an unordered TOP-n against Pervasive returns an arbitrary subset.

    ``offset`` is retained for API compatibility and applied client-side. It is
    O(offset); use scan_after() for anything that walks a whole table.
    """
    if _is_mock():
        logger.debug("[MOCK] fetch_all table=%s limit=%d", table_key, limit)
        return _mock_fetch(table_key, limit, offset, search)

    table = schema.table_name(table_key)          # validates + quotes
    order_col = quote_ident(order_by or schema.ORDERING_KEY)

    fetch_count = max(limit + max(offset, 0), 1)
    sql = "SELECT TOP {} * FROM {}".format(int(fetch_count), table)
    if where:
        sql += " WHERE " + where
    sql += " ORDER BY " + order_col

    logger.debug("ODBC: %s | params=%s", sql, params)
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(sql, params or ())
        rows = _rows_to_dicts(cursor)

    if offset > 0:
        rows = rows[offset:]
    return rows[:limit]


def fetch_one(
    table_key: str, where: str, params: tuple
) -> Optional[Dict[str, Any]]:
    """Return the first matching row, or None."""
    rows = fetch_all(table_key, where=where, params=params, limit=1)
    return rows[0] if rows else None


def scan_after(
    table_key: str,
    key_column: str,
    after_value: Optional[str],
    limit: int = 200,
) -> List[Dict[str, Any]]:
    """
    Keyset scan: rows with ``key_column > after_value``, ascending, capped.

    This is the primitive behind change detection. Unlike OFFSET pagination it
    stays O(page) no matter how far into the table the cursor has advanced, so
    scanning stays cheap on a company file with years of history — which
    matters on the target hardware.

    Pass ``after_value=None`` to start from the beginning.
    """
    if _is_mock():
        import mock_data as md
        rows = list(md.MOCK_INVOICES if table_key == "ar_transactions" else [])
        key = key_column.lower()
        rows.sort(key=lambda r: str(r.get(key, r.get("sage_id", ""))))
        if after_value is not None:
            rows = [
                r for r in rows
                if str(r.get(key, r.get("sage_id", ""))) > str(after_value)
            ]
        return rows[:limit]

    table = schema.table_name(table_key)
    key = quote_ident(key_column)

    sql = "SELECT TOP {} * FROM {}".format(int(limit), table)
    params: tuple = ()
    if after_value is not None:
        sql += " WHERE {} > ?".format(key)
        params = (after_value,)
    sql += " ORDER BY " + key

    logger.debug("ODBC scan: %s | after=%s", sql, after_value)
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(sql, params)
        return _rows_to_dicts(cursor)


def execute_scalar(sql: str, params: Optional[tuple] = None) -> Any:
    """Run a caller-supplied SELECT and return one scalar. Internal use only."""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(sql, params or ())
        row = cursor.fetchone()
        return row[0] if row else None


# ── schema discovery (setup/diagnostics) ─────────────────────────────────────

def list_odbc_tables() -> List[str]:
    """All table names visible through the DSN. Used by verify_onsite.py."""
    if _is_mock():
        return sorted(TABLE_MAP.values())
    with get_connection() as conn:
        return [row.table_name for row in conn.cursor().tables(tableType="TABLE")]


def list_columns(table_key: str) -> List[str]:
    """Real column names for a table. Used to validate sage_schema.py on site."""
    if _is_mock():
        return []
    real = TABLE_MAP.get(table_key, table_key)
    with get_connection() as conn:
        return [row.column_name for row in conn.cursor().columns(table=real)]
