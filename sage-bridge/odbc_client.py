"""
odbc_client.py — Read-only access to Sage 50 via Pervasive PSQL ODBC.

The ODBC driver (installed with Sage 50) exposes the company's Pervasive
database as standard ODBC tables.  We use pyodbc for all read operations
here; writes go through sdk_client.py (the official Sage SDK) to guarantee
ledger integrity.

Table-name notes
----------------
Sage 50 / Peachtree uses a Pervasive (Actian Zen) Workgroup Engine.  The
exact table names are defined by the DDF files inside the company data
folder.  The names below are the canonical Peachtree Accounting table names
confirmed across Sage 50 2013 installations:

    CUSTOMER        — Customer master
    VENDOR          — Vendor master
    EMPLOYEE        — Employee master
    INVENTRY        — Inventory / stock items
    ACCOUNT         — Chart of accounts (GL accounts)
    ARTRANS         — AR transactions (invoices, receipts, credits)
    ARDETAIL        — AR transaction lines
    APTRANS         — AP transactions (bills, payments)
    APDETAIL        — AP transaction lines
    SOHEADER        — Sales order headers
    SODETAIL        — Sales order lines
    POHEADER        — Purchase order headers
    PODETAIL        — Purchase order lines
    JRNLHDR         — General journal entry headers
    JRNLROW         — General journal entry lines
    PAYROLL         — Payroll check records
    COMPANY         — Company information (single row)
    TAXCODE         — Sales tax codes
    SHIPMETHOD      — Shipping methods
    TERMS           — Payment terms
    DEPARTMENT      — Departments
    JOB             — Job records (job costing)

NOTE: If the client's DDF files use slightly different names (rare but
possible on very old company files), update TABLE_MAP below to match what
SELECT * FROM <table> returns via ODBC on the client machine.
"""
from __future__ import annotations

import logging
from contextlib import contextmanager
from typing import Any, Dict, Generator, List, Optional

import pyodbc

from config import get_settings

logger = logging.getLogger("bridge.odbc")


def _is_mock() -> bool:
    return get_settings().SAGE_MOCK


def _mock_fetch(table_key: str, limit: int, offset: int, search: Optional[str] = None) -> List[Dict[str, Any]]:
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

# ── Canonical table name map ─────────────────────────────────────────────────
# Keys are our internal names; values are the actual ODBC table names.
# Adjust if the client's DDF uses different names.
TABLE_MAP: Dict[str, str] = {
    "customers":        "CUSTOMER",
    "vendors":          "VENDOR",
    "employees":        "EMPLOYEE",
    "inventory":        "INVENTRY",
    "accounts":         "ACCOUNT",
    "ar_transactions":  "ARTRANS",
    "ar_lines":         "ARDETAIL",
    "ap_transactions":  "APTRANS",
    "ap_lines":         "APDETAIL",
    "sales_orders":     "SOHEADER",
    "sales_order_lines":"SODETAIL",
    "purchase_orders":  "POHEADER",
    "purchase_order_lines": "PODETAIL",
    "journal_headers":  "JRNLHDR",
    "journal_lines":    "JRNLROW",
    "payroll":          "PAYROLL",
    "company":          "COMPANY",
    "tax_codes":        "TAXCODE",
    "ship_methods":     "SHIPMETHOD",
    "terms":            "TERMS",
    "departments":      "DEPARTMENT",
    "jobs":             "JOB",
}


def _build_connection_string() -> str:
    """Return a pyodbc connection string for the Pervasive DSN."""
    settings = get_settings()
    if settings.SAGE_ODBC_CONN_STR:
        return settings.SAGE_ODBC_CONN_STR
    # Standard Pervasive ODBC using a named DSN.
    return f"DSN={settings.SAGE_ODBC_DSN};"


@contextmanager
def get_connection() -> Generator[pyodbc.Connection, None, None]:
    """Context manager that yields a pyodbc connection and closes it on exit."""
    conn_str = _build_connection_string()
    conn: Optional[pyodbc.Connection] = None
    try:
        conn = pyodbc.connect(conn_str, autocommit=True, timeout=10)
        yield conn
    except pyodbc.Error as exc:
        logger.error("ODBC connection error: %s", exc)
        raise
    finally:
        if conn:
            conn.close()


def _rows_to_dicts(cursor: pyodbc.Cursor) -> List[Dict[str, Any]]:
    """Convert cursor rows to a list of plain dicts (column_name → value)."""
    columns = [col[0].lower() for col in cursor.description]
    return [dict(zip(columns, row)) for row in cursor.fetchall()]


# ── Generic helpers ───────────────────────────────────────────────────────────

def fetch_all(
    table_key: str,
    where: Optional[str] = None,
    params: Optional[tuple] = None,
    limit: int = 500,
    offset: int = 0,
    search: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """
    SELECT * FROM <table> [WHERE ...] ORDER BY 1 FETCH FIRST n ROWS ONLY.
    table_key must be a key in TABLE_MAP.
    When SAGE_MOCK=true, returns mock data instead of querying ODBC.
    """
    if _is_mock():
        logger.info("[MOCK] fetch_all table=%s limit=%d offset=%d", table_key, limit, offset)
        return _mock_fetch(table_key, limit, offset, search)

    table = TABLE_MAP.get(table_key)
    if not table:
        raise ValueError(f"Unknown table key: {table_key!r}. Known: {list(TABLE_MAP)}")

    # Pervasive SQL on older Sage installs does not support FETCH FIRST/OFFSET.
    # Use TOP for limit and apply offset client-side for compatibility.
    fetch_count = max(limit + max(offset, 0), 1)
    sql = f"SELECT TOP {fetch_count} * FROM {table}"
    if where:
        sql += f" WHERE {where}"

    logger.debug("ODBC query: %s | params: %s", sql, params)
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(sql, params or ())
        rows = _rows_to_dicts(cursor)
        if offset > 0:
            rows = rows[offset:]
        return rows[:limit]


def fetch_one(
    table_key: str,
    where: str,
    params: tuple,
) -> Optional[Dict[str, Any]]:
    """Return the first matching row or None."""
    rows = fetch_all(table_key, where=where, params=params, limit=1)
    return rows[0] if rows else None


def execute_scalar(sql: str, params: Optional[tuple] = None) -> Any:
    """Run an arbitrary SELECT and return a single scalar value."""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(sql, params or ())
        row = cursor.fetchone()
        return row[0] if row else None


def list_odbc_tables() -> List[str]:
    """Return all table names visible via the current ODBC connection (debug/setup tool)."""
    with get_connection() as conn:
        cursor = conn.cursor()
        return [row.table_name for row in cursor.tables(tableType="TABLE")]
