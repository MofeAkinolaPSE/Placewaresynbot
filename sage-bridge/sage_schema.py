"""
sage_schema.py — EVERY assumption about the Sage 50 2013 database lives here.

Why this file exists
--------------------
Sage 50 / Peachtree stores its data in a Pervasive (Actian Zen) database whose
table and column names come from the .DDF files inside each company folder.
Those names vary between Sage versions and, occasionally, between company files
created by different Sage releases.

The names below are the canonical Peachtree names and are our best guess. They
have NOT been verified against the client's company file. Rather than scatter
that uncertainty across a dozen modules, all of it is collected here so that
correcting it on site is a single-file edit with no logic changes.

On-site procedure
-----------------
    python verify_onsite.py --report

That prints the real table list and, for each table we depend on, the real
column names alongside what we expected. Fix the mismatches below, re-run until
it reports OK, then start the service. Nothing else needs to change.

Quoting note
------------
Pervasive treats DATE, TIME, NUMBER, VALUE, STATUS and similar as reserved
words. Any identifier that might be reserved MUST go through quote_ident()
before being embedded in SQL, or the query fails with a syntax error. This bit
us in the original code, which emitted `WHERE DATE >= ?` unquoted.
"""
from __future__ import annotations

from typing import Dict, List

# ── Table names ──────────────────────────────────────────────────────────────
# internal key → real ODBC table name
TABLE_MAP: Dict[str, str] = {
    "customers":            "CUSTOMER",
    "vendors":              "VENDOR",
    "employees":            "EMPLOYEE",
    "inventory":            "INVENTRY",
    "accounts":             "ACCOUNT",
    "ar_transactions":      "ARTRANS",
    "ar_lines":             "ARDETAIL",
    "ap_transactions":      "APTRANS",
    "ap_lines":             "APDETAIL",
    "sales_orders":         "SOHEADER",
    "sales_order_lines":    "SODETAIL",
    "purchase_orders":      "POHEADER",
    "purchase_order_lines": "PODETAIL",
    "journal_headers":      "JRNLHDR",
    "journal_lines":        "JRNLROW",
    "payroll":              "PAYROLL",
    "company":              "COMPANY",
    "tax_codes":            "TAXCODE",
    "ship_methods":         "SHIPMETHOD",
    "terms":                "TERMS",
    "departments":          "DEPARTMENT",
    "jobs":                 "JOB",
}


# ── Column names, per logical role ───────────────────────────────────────────
# The watcher and the invoice extractor reference columns ONLY through these
# constants. If the client's DDF differs, change it here and nowhere else.

class ARTrans:
    """AR transaction header — one row per sales invoice."""
    TABLE = "ar_transactions"
    ID = "TRANSNO"            # Sage internal transaction key
    INVOICE_NUMBER = "REFERENCE"
    CUSTOMER_ID = "ACCTID"
    DATE = "DATE"             # reserved word — always quote_ident()
    DUE_DATE = "DUEDATE"
    AMOUNT = "AMOUNT"
    PAID = "AMTPAID"
    # Monotonic ordering key for change detection. See ORDERING_KEY below.
    ROWID = "TRANSNO"


class ARDetail:
    """AR transaction lines — one row per invoice line item."""
    TABLE = "ar_lines"
    PARENT_ID = "TRANSNO"     # FK back to ARTrans.ID
    LINE_NO = "LINENO"
    ITEM_ID = "ITEMID"
    DESCRIPTION = "DESCRPTN"
    QUANTITY = "QUANTITY"
    UNIT_PRICE = "UNITPRICE"
    AMOUNT = "AMOUNT"
    GL_ACCOUNT = "GLACCTNO"
    TAX_TYPE = "TAXTYPE"


#: Column used to order invoice scans deterministically.
#:
#: CRITICAL: the original code issued `SELECT TOP 2000 * FROM ARTRANS` with no
#: ORDER BY. Pervasive returns rows in physical/undefined order, so once the
#: table exceeded 2000 rows the window silently excluded new invoices. Every
#: scan now orders by this column.
ORDERING_KEY = ARTrans.ID


#: Tables verify_onsite.py must find before the service is considered usable.
REQUIRED_TABLES: List[str] = [
    "company",
    "customers",
    "inventory",
    "ar_transactions",
    "ar_lines",
]


#: Columns verify_onsite.py checks per table (internal key → column names).
REQUIRED_COLUMNS: Dict[str, List[str]] = {
    "ar_transactions": [
        ARTrans.ID, ARTrans.INVOICE_NUMBER, ARTrans.CUSTOMER_ID,
        ARTrans.DATE, ARTrans.AMOUNT,
    ],
    "ar_lines": [
        ARDetail.PARENT_ID, ARDetail.ITEM_ID, ARDetail.QUANTITY,
        ARDetail.UNIT_PRICE, ARDetail.AMOUNT,
    ],
}


# ── SQL identifier quoting ───────────────────────────────────────────────────

def quote_ident(name: str) -> str:
    """
    Quote a table/column identifier for Pervasive SQL.

    Pervasive uses double quotes for delimited identifiers. Embedded quotes are
    doubled. Rejects anything that is not a plain identifier so this can never
    become an injection vector — callers pass constants from this module, and a
    typo should fail loudly rather than produce surprising SQL.
    """
    if not name or not all(c.isalnum() or c == "_" for c in name):
        raise ValueError(f"Unsafe SQL identifier: {name!r}")
    return '"' + name.replace('"', '""') + '"'


def table_name(table_key: str) -> str:
    """Resolve an internal table key to a quoted real table name."""
    real = TABLE_MAP.get(table_key)
    if not real:
        raise ValueError(
            f"Unknown table key {table_key!r}. Known: {sorted(TABLE_MAP)}"
        )
    return quote_ident(real)
