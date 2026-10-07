"""Gap-free document numbers per entity and document type.

The UPDATE ... RETURNING takes a row lock, so concurrent postings queue for
the next number instead of colliding; a rolled-back transaction gives its
number back.
"""
from __future__ import annotations

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
