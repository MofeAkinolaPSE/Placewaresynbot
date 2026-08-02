"""
invoice_extract.py — Assemble the complete invoice record sent to SynBot.

What was wrong before
---------------------
The sync path called ``GET /invoices``, which read the ARTRANS header table
over ODBC and returned header rows only. Line items, quantities and unit prices
were reachable only through ``sdk_get_invoice(id)`` behind ``/invoices/{id}``,
which the sync engine never called. Tax, inventory movement and payment
application were not modelled anywhere at all.

So SynBot was driving inventory and finance updates from invoice totals alone.

This module builds one complete record per invoice, covering every field the
brief asks for:

    invoice number/ID, date, customer, items, quantities, unit prices,
    line and invoice totals, taxes, inventory movement, payment info,
    status, plus metadata.

Sourcing strategy
-----------------
SDK first, ODBC as fallback:

  * The **SDK** is authoritative. It returns Sage's own computed values, so
    totals and tax match what an accountant sees in the UI.
  * **ODBC** is the fallback when the SDK is unavailable (not authorized yet,
    session dead, running read-only). Degraded but not useless — the record is
    marked ``"source": "odbc"`` and flags which fields are unverified, so
    SynBot can tell complete data from partial.

Never silently emit a partial record as though it were complete: every record
carries ``_meta.completeness`` describing exactly what is present.
"""
from __future__ import annotations

import datetime
import logging
from typing import Any, Dict, List, Optional

import odbc_client as odbc
import sage_schema as schema
import sdk_client as sdk

logger = logging.getLogger("bridge.invoice_extract")


# ── numeric coercion ─────────────────────────────────────────────────────────

def _num(value: Any, default: float = 0.0) -> float:
    """Coerce a Sage/ODBC value to float. Never raises."""
    if value is None:
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _text(value: Any, default: str = "") -> str:
    """Coerce to a trimmed string. Sage pads CHAR columns with spaces."""
    if value is None:
        return default
    try:
        return str(value).strip()
    except Exception:
        return default


def _iso_date(value: Any) -> Optional[str]:
    """Normalise a date-ish value to ISO YYYY-MM-DD, or None."""
    if value is None or value == "":
        return None
    if isinstance(value, datetime.datetime):
        return value.date().isoformat()
    if isinstance(value, datetime.date):
        return value.isoformat()
    text = str(value).strip()
    if not text:
        return None
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%d/%m/%Y", "%Y%m%d"):
        try:
            return datetime.datetime.strptime(text[:10], fmt).date().isoformat()
        except ValueError:
            continue
    logger.debug("Unparseable date value: %r", value)
    return None


# ── inventory movement ───────────────────────────────────────────────────────

def _derive_inventory_movement(lines: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Derive stock movement implied by the invoice lines.

    A sales invoice decrements stock for every line carrying an item ID.
    Service/comment lines (no item ID) move no stock and are excluded.

    Sign convention: ``quantity_delta`` is NEGATIVE for a sale. SynBot applies
    the delta directly, so getting this backwards would inflate stock on every
    sale — hence stating it explicitly rather than leaving it to the consumer.
    """
    movements: List[Dict[str, Any]] = []
    for line in lines:
        item_id = _text(line.get("item_id"))
        if not item_id:
            continue
        qty = _num(line.get("quantity"))
        if qty == 0:
            continue
        movements.append({
            "item_id": item_id,
            "description": line.get("description", ""),
            "quantity_delta": -abs(qty),      # sale removes stock
            "direction": "out",
            "unit_price": _num(line.get("unit_price")),
            "line_no": line.get("line_no"),
        })
    return movements


# ── payment / status ─────────────────────────────────────────────────────────

def _derive_payment(total: float, paid: float, due_date: Optional[str]) -> Dict[str, Any]:
    """Build the payment sub-record and derive a settlement status."""
    outstanding = round(total - paid, 2)

    if paid <= 0:
        status = "unpaid"
    elif outstanding <= 0.005:            # tolerate float noise on rounded money
        status = "paid"
    else:
        status = "partial"

    overdue = False
    days_overdue = 0
    if status != "paid" and due_date:
        try:
            d = datetime.date.fromisoformat(due_date)
            delta = (datetime.date.today() - d).days
            if delta > 0:
                overdue, days_overdue = True, delta
        except ValueError:
            pass

    return {
        "total_amount": round(total, 2),
        "amount_paid": round(paid, 2),
        "amount_due": outstanding,
        "payment_status": status,
        "is_overdue": overdue,
        "days_overdue": days_overdue,
    }


def _sum_line_tax(lines: List[Dict[str, Any]]) -> float:
    return round(sum(_num(l.get("tax_amount")) for l in lines), 2)


# ── SDK path (authoritative) ─────────────────────────────────────────────────

def _extract_via_sdk(invoice_id: str) -> Optional[Dict[str, Any]]:
    """Build a complete record from the Sage SDK. None if unavailable."""
    raw = sdk.sdk_get_invoice(invoice_id)
    if not raw:
        return None

    lines: List[Dict[str, Any]] = []
    for idx, line in enumerate(raw.get("lines") or []):
        qty = _num(line.get("quantity"))
        unit = _num(line.get("unit_price"))
        amount = _num(line.get("amount"), qty * unit)
        lines.append({
            "line_no": line.get("line_no", idx + 1),
            "item_id": _text(line.get("item_id")),
            "description": _text(line.get("description")),
            "quantity": qty,
            "unit_price": unit,
            "amount": round(amount, 2),
            "gl_account": _text(line.get("gl_account")),
            "tax_type": _text(line.get("tax_type")),
            "tax_amount": _num(line.get("tax_amount")),
        })

    total = _num(raw.get("total_amount"))
    paid = _num(raw.get("amount_paid"))
    subtotal = round(sum(l["amount"] for l in lines), 2)
    tax_total = _num(raw.get("sales_tax_amount"), _sum_line_tax(lines))
    due_date = _iso_date(raw.get("due_date"))

    return {
        "sage_id": _text(raw.get("sage_id"), invoice_id),
        "invoice_number": _text(raw.get("invoice_number")),
        "date": _iso_date(raw.get("date")),
        "due_date": due_date,
        "customer_id": _text(raw.get("customer_id")),
        "customer_name": _text(raw.get("customer_name")),
        "po_number": _text(raw.get("po_number")),
        "note": _text(raw.get("note")),
        "lines": lines,
        "line_count": len(lines),
        "subtotal": subtotal,
        "tax": {
            "total_tax": tax_total,
            "tax_code": _text(raw.get("tax_code")),
            "by_line": [
                {"line_no": l["line_no"], "tax_type": l["tax_type"],
                 "tax_amount": l["tax_amount"]}
                for l in lines if l["tax_type"] or l["tax_amount"]
            ],
        },
        "payment": _derive_payment(total, paid, due_date),
        "inventory_movement": _derive_inventory_movement(lines),
        "shipping": {
            "ship_date": _iso_date(raw.get("ship_date")),
            "ship_method": _text(raw.get("ship_method")),
        },
        "_meta": {
            "source": "sdk",
            "completeness": "full",
            "extracted_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        },
    }


# ── ODBC path (fallback) ─────────────────────────────────────────────────────

def _extract_via_odbc(header: Dict[str, Any]) -> Dict[str, Any]:
    """
    Build a record from ODBC rows when the SDK is unavailable.

    Degraded: Sage's computed tax lives in the SDK, so tax here is whatever the
    detail rows carry, and may be incomplete. The record says so explicitly in
    ``_meta`` rather than presenting a possibly-wrong number as authoritative.
    """
    H = schema.ARTrans
    D = schema.ARDetail

    sage_id = _text(header.get(H.ID.lower()) or header.get(H.ID))
    lines: List[Dict[str, Any]] = []

    try:
        detail_rows = odbc.fetch_all(
            D.TABLE,
            where="{} = ?".format(schema.quote_ident(D.PARENT_ID)),
            params=(sage_id,),
            limit=500,
            order_by=D.LINE_NO,
        )
    except Exception as exc:
        logger.warning("Could not read invoice lines for %s: %s", sage_id, exc)
        detail_rows = []

    for idx, r in enumerate(detail_rows):
        get = lambda col: r.get(col.lower(), r.get(col))  # noqa: E731
        qty = _num(get(D.QUANTITY))
        unit = _num(get(D.UNIT_PRICE))
        lines.append({
            "line_no": get(D.LINE_NO) or idx + 1,
            "item_id": _text(get(D.ITEM_ID)),
            "description": _text(get(D.DESCRIPTION)),
            "quantity": qty,
            "unit_price": unit,
            "amount": round(_num(get(D.AMOUNT), qty * unit), 2),
            "gl_account": _text(get(D.GL_ACCOUNT)),
            "tax_type": _text(get(D.TAX_TYPE)),
            "tax_amount": 0.0,     # not reliably available over ODBC
        })

    hget = lambda col: header.get(col.lower(), header.get(col))  # noqa: E731
    total = _num(hget(H.AMOUNT))
    paid = _num(hget(H.PAID))
    due_date = _iso_date(hget(H.DUE_DATE))

    return {
        "sage_id": sage_id,
        "invoice_number": _text(hget(H.INVOICE_NUMBER)),
        "date": _iso_date(hget(H.DATE)),
        "due_date": due_date,
        "customer_id": _text(hget(H.CUSTOMER_ID)),
        "customer_name": "",
        "po_number": "",
        "note": "",
        "lines": lines,
        "line_count": len(lines),
        "subtotal": round(sum(l["amount"] for l in lines), 2),
        "tax": {
            "total_tax": 0.0,
            "tax_code": "",
            "by_line": [],
            "unavailable_reason": "SDK unavailable; Sage-computed tax not readable over ODBC",
        },
        "payment": _derive_payment(total, paid, due_date),
        "inventory_movement": _derive_inventory_movement(lines),
        "shipping": {"ship_date": None, "ship_method": ""},
        "_meta": {
            "source": "odbc",
            "completeness": "partial",
            "missing": ["tax", "customer_name", "shipping", "note"],
            "extracted_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        },
    }


# ── public entry point ───────────────────────────────────────────────────────

def extract_invoice(
    invoice_id: str,
    header_row: Optional[Dict[str, Any]] = None,
) -> Optional[Dict[str, Any]]:
    """
    Return the complete invoice record for ``invoice_id``.

    Tries the SDK first and falls back to ODBC. ``header_row`` is the already
    fetched ARTRANS row, if the caller has one — it saves a round trip on the
    fallback path.

    Returns None only when neither source can produce a record; the caller
    leaves the watermark unadvanced so the invoice is retried rather than
    skipped.
    """
    try:
        record = _extract_via_sdk(invoice_id)
        if record:
            return record
        logger.debug("SDK returned nothing for invoice %s", invoice_id)
    except Exception as exc:
        logger.warning(
            "SDK extraction failed for invoice %s (%s) — falling back to ODBC",
            invoice_id, exc,
        )

    if header_row:
        try:
            return _extract_via_odbc(header_row)
        except Exception:
            logger.exception("ODBC extraction failed for invoice %s", invoice_id)

    logger.error(
        "Could not extract invoice %s from SDK or ODBC — it stays pending and "
        "will be retried on the next scan.", invoice_id,
    )
    return None
