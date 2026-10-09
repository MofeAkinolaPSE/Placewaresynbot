"""Gap-free document numbers per entity and document type.

The UPDATE ... RETURNING takes a row lock, so concurrent postings queue for
the next number instead of colliding; a rolled-back transaction gives its
number back.
"""
from __future__ import annotations

from typing import Optional

from src.fin.db import q1

DEFAULT_PREFIX = {
    "JOURNAL": "JV-",
    "SALES_INVOICE": "SI-",
    "CREDIT_NOTE": "CN-",
    "RECEIPT": "RCP-",
    "BILL": "BILL-",
    "DEBIT_NOTE": "DN-",
    "SUPPLIER_PAYMENT": "PV-",
    "CASH_VOUCHER": "CV-",
    "INVENTORY": "STK-",
    "STOCK_LOAN": "LN-",
    "RECALL": "RC-",
    "STOCK_COUNT": "SC-",
    "ASSET": "FA-",
    "DEPRECIATION": "DEP-",
    "RECONCILIATION": "REC-",
    "DATA_CORRECTION": "FIX-",
}


def sage_invoice_floor(conn, entity_id: str) -> int:
    """The next number in Sage's running invoice sequence: one more than the highest plain
    invoice number (no prefix, no leading zero) used in the last 60 days of Sage's Sales
    Journal. Other series Sage holds ('0058437', '00068', 58xxx) are left alone."""
    from src.fin.db import q
    rows = q(conn, r"""WITH last AS (SELECT MAX(txn_date) d FROM fin_sage_journal_lines WHERE legal_entity_id=%s AND kind='SJ')
                       SELECT DISTINCT reference::bigint AS n FROM fin_sage_journal_lines, last
                       WHERE legal_entity_id=%s AND kind='SJ' AND reference ~ '^[1-9][0-9]{3,6}$'
                         AND txn_date BETWEEN last.d - 14 AND last.d""", (entity_id, entity_id))
    nums = sorted(int(r["n"]) for r in rows)
    if not nums:
        return 0
    # the running sequence is where most recent invoices sit; a stray number from another
    # series (e.g. 58805 among 53xxx) is ignored
    median = nums[len(nums) // 2]
    return max(n for n in nums if abs(n - median) <= 1000) + 1


def last_invoice(conn, entity_id: str):
    """The last invoice raised in the running sequence - ACE Books or, before it took over, Sage -
    so the team can see where yesterday ended (the client's "invoice register" check)."""
    ace = q1(conn, r"""SELECT i.invoice_number AS number, i.invoice_date AS date, c.name AS customer, i.total, i.id::text AS id
                       FROM fin_sales_invoices i LEFT JOIN customers c ON c.id=i.customer_id
                       WHERE i.legal_entity_id=%s AND NOT i.is_opening AND i.status <> 'VOID' AND i.invoice_number ~ '^[1-9][0-9]{3,6}$'
                       ORDER BY i.invoice_number::bigint DESC LIMIT 1""", (entity_id,))
    floor = sage_invoice_floor(conn, entity_id)
    sage = None
    if floor:
        sage = q1(conn, """SELECT reference AS number, txn_date AS date, MAX(description) FILTER (WHERE debit > 0) AS customer,
                                  SUM(debit) FILTER (WHERE debit > 0) AS total
                           FROM fin_sage_journal_lines j
                           WHERE legal_entity_id=%s AND kind='SJ' AND reference=%s
                             AND account_code IN (SELECT a.code FROM fin_account_mappings m JOIN fin_accounts a ON a.id=m.account_id
                                                  WHERE m.legal_entity_id=%s AND m.mapping_key='AR_CONTROL')
                           GROUP BY reference, txn_date ORDER BY txn_date DESC LIMIT 1""", (entity_id, str(floor - 1), entity_id))
    if ace and (not sage or int(ace["number"]) >= int(sage["number"])):
        return {**ace, "source": "ace"}
    return {**sage, "source": "sage"} if sage else None


def next_invoice_preview(conn, entity_id: str) -> str:
    row = q1(conn, "SELECT prefix, next_value, pad FROM fin_number_sequences WHERE legal_entity_id=%s AND doc_type='SALES_INVOICE'",
             (entity_id,))
    floor = sage_invoice_floor(conn, entity_id)
    if floor:
        return str(max(floor, int(row["next_value"]) if row and row["prefix"] == "" else 0))
    return f"{row['prefix']}{int(row['next_value']):0{int(row['pad'])}d}" if row else "SI-000001"


def next_number(conn, entity_id: str, doc_type: str) -> str:
    if doc_type == "SALES_INVOICE":
        # Invoices continue the client's Sage numbering (53542 -> 53543), wherever they are raised.
        floor = sage_invoice_floor(conn, entity_id)
        if floor:
            row = q1(conn, """
                INSERT INTO fin_number_sequences (legal_entity_id, doc_type, prefix, next_value, pad)
                VALUES (%s, 'SALES_INVOICE', '', %s, 0)
                ON CONFLICT (legal_entity_id, doc_type)
                DO UPDATE SET prefix='', pad=0,
                              next_value = GREATEST(CASE WHEN fin_number_sequences.prefix='' THEN fin_number_sequences.next_value ELSE 0 END,
                                                    EXCLUDED.next_value - 1) + 1
                RETURNING next_value - 1 AS value""", (entity_id, floor + 1))
            value = int(row["value"])
            while q1(conn, "SELECT 1 FROM fin_sales_invoices WHERE legal_entity_id=%s AND invoice_number=%s", (entity_id, str(value))):
                value = int(q1(conn, """UPDATE fin_number_sequences SET next_value=next_value+1 WHERE legal_entity_id=%s
                                        AND doc_type='SALES_INVOICE' RETURNING next_value - 1 AS v""", (entity_id,))["v"])
            return str(value)
    row = q1(conn, """
        INSERT INTO fin_number_sequences (legal_entity_id, doc_type, prefix, next_value)
        VALUES (%s, %s, %s, 2)
        ON CONFLICT (legal_entity_id, doc_type)
        DO UPDATE SET next_value = fin_number_sequences.next_value + 1
        RETURNING prefix, next_value - 1 AS value, pad
    """, (entity_id, doc_type, DEFAULT_PREFIX.get(doc_type, doc_type[:3] + "-")))
    return f"{row['prefix']}{int(row['value']):0{int(row['pad'])}d}"


def release_if_last(conn, ctx, doc_type: str, number: str, table: str, column: str, row_id: str,
                    check_frontdesk: bool = True) -> Optional[str]:
    """A voided document gives its number back when it is the last one issued, so the next
    document takes it and the sequence has no gap (client, 8 Oct 2026). The voided record keeps
    everything else and is renamed "<number>-VOID" (it stays in the audit trail and the reports).
    A number with later documents after it cannot be reused without leaving another gap, so it stays.
    Returns the new name of the voided record, or None when the number was not released."""
    from src.fin import audit
    from src.fin.db import ex
    seq = q1(conn, """SELECT prefix, next_value, pad FROM fin_number_sequences WHERE legal_entity_id=%s AND doc_type=%s
                      FOR UPDATE""", (ctx.entity_id, doc_type))
    if not seq:
        return None
    prefix, pad = seq["prefix"] or "", int(seq["pad"] or 0)
    raw = str(number)
    if not raw.startswith(prefix) or not raw[len(prefix):].isdigit():
        return None
    value = int(raw[len(prefix):])
    if f"{prefix}{value:0{pad}d}" != raw or int(seq["next_value"]) != value + 1:
        return None   # not the last number issued
    if doc_type == "SALES_INVOICE" and check_frontdesk:
        # a Frontdesk request still holding the number keeps it
        held = q1(conn, """SELECT 1 FROM frontdesk_invoices f WHERE f.invoice_number=%s AND NOT EXISTS (
                               SELECT 1 FROM fin_source_postings p WHERE p.source_type='FRONTDESK' AND p.source_id=f.id::text
                               AND p.document_id::text=%s)""", (raw, str(row_id)))
        if held:
            return None
    renamed, k = f"{raw}-VOID", 1
    while q1(conn, f"SELECT 1 FROM {table} WHERE {column}=%s", (renamed,)):  # the number was voided before
        k += 1
        renamed = f"{raw}-VOID-{k}"
    ex(conn, f"UPDATE {table} SET {column}=%s WHERE id=%s", (renamed, row_id))
    ex(conn, "UPDATE fin_number_sequences SET next_value=%s WHERE legal_entity_id=%s AND doc_type=%s", (value, ctx.entity_id, doc_type))
    audit.record(conn, ctx, "DOCUMENT_NUMBER_RELEASED", table, row_id, ref=raw,
                 metadata={"renamed_to": renamed, "next_number": raw})
    return renamed
