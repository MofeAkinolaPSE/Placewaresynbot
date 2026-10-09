"""Which book of original entry (Sage journal code) each posting belongs to.

The one table the General Ledger's "Jrnl" column and the Journals-by-type reports both read, so
a posting is listed in exactly one journal and is labelled with that journal everywhere.
Bank vouchers follow Sage: money paid out is a cash disbursement, money received a cash receipt,
and a transfer between banks a general journal entry.
"""
from __future__ import annotations

from typing import Optional, Tuple

SOURCE_JOURNAL = {
    "SALES_INVOICE": "SJ", "CREDIT_NOTE": "SJ", "FRONTDESK": "SJ",
    "CUSTOMER_RECEIPT": "CRJ",
    "SUPPLIER_BILL": "PJ", "DEBIT_NOTE": "PJ",
    "SUPPLIER_PAYMENT": "CDJ", "CASH_VOUCHER": "CDJ",
    "STOCK_ADJUSTMENT": "INAJ", "STOCK_COUNT": "INAJ", "STOCK_LOAN": "INAJ", "STOCK_LOAN_RETURN": "INAJ",
    "STOCK_LOAN_WRITEOFF": "INAJ",
    "FIXED_ASSET": "FA", "DEPRECIATION_RUN": "FA", "FIXED_ASSET_DISPOSAL": "FA",
    "MANUAL_JOURNAL": "GENJ", "MIGRATION": "GENJ", "YEAR_END": "GENJ",
    "DATA_CORRECTION": "ADJ",
}
VOUCHER_JOURNAL = {"SPEND": "CDJ", "RECEIVE": "CRJ", "TRANSFER": "GENJ"}
DEFAULT = "GENJ"

# the Journals-by-type reports (COGS is the cost side of the Sales Journal, read separately)
KEY_CODE = {"sales": "SJ", "cash-receipts": "CRJ", "cash-disbursements": "CDJ", "purchases": "PJ", "cogs": "COGS",
            "general": "GENJ", "inventory-adjustments": "INAJ", "assets": "FA"}

# the journal report each code is listed in: corrections (ADJ) sit in the General Journal, as in Sage
REPORT_CODES = {"SJ": ("SJ",), "CRJ": ("CRJ",), "PJ": ("PJ",), "CDJ": ("CDJ",), "INAJ": ("INAJ",), "FA": ("FA",),
                "GENJ": ("GENJ", "ADJ")}


def journal_code(source_type: Optional[str], voucher_kind: Optional[str] = None) -> str:
    if source_type == "CASH_VOUCHER" and voucher_kind:
        return VOUCHER_JOURNAL.get(voucher_kind, "CDJ")
    return SOURCE_JOURNAL.get(source_type or "", DEFAULT)


def code_sql(source_type: str = "g.source_type", source_id: str = "g.source_id") -> str:
    """SQL expression giving the journal code of a posting, the same answer as journal_code()."""
    voucher = " ".join(f"WHEN '{k}' THEN '{v}'" for k, v in VOUCHER_JOURNAL.items())
    by_source = " ".join(f"WHEN '{k}' THEN '{v}'" for k, v in SOURCE_JOURNAL.items())
    return (f"(CASE WHEN {source_type}='CASH_VOUCHER' THEN COALESCE((SELECT CASE v.kind {voucher} END FROM fin_cash_vouchers v"
            f" WHERE v.id::text={source_id}::text), 'CDJ')"
            f" ELSE CASE COALESCE({source_type}, '') {by_source} ELSE '{DEFAULT}' END END)")


def report_codes(code: str) -> Tuple[str, ...]:
    return REPORT_CODES.get(code, (code,))
