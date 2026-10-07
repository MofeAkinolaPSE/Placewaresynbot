"""Pure row builders for the ACE -> Sage 50 export (no DB access).

Each builder takes plain dicts (loaded by `loader.py`) and returns
`(rows, blocked)`: `rows` are lists of strings in the exact column order of
the client's Sage Import/Export template, `blocked` explains every source
record left out and why. A record is either exported whole or blocked whole --
a half-exported invoice would post a wrong AR balance in Sage.

Conventions reproduced from the client's own template exports
(backend/docs/Latestmods-TB/sage-link/export-templates/):
  * one row per distribution; header fields repeated on every row
  * `Number of Distributions` = row count, `... Distribution` = 1..N
  * Sales line `Amount` is negative (credit), `Accounts Receivable Amount`
    positive and equal to -sum(Amount)
  * Receipts: `Cash Amount` positive, `Total Paid on Invoice(s)` and each
    line `Amount` negative, `G/L Account` = AR (11000)
  * dates M/D/YY, money 2dp, CRLF line endings
"""
from __future__ import annotations

import csv
import datetime as dt
import io
from decimal import ROUND_HALF_UP, Decimal
from typing import Any, Dict, Iterable, List, Optional, Tuple

from src.services.sage_export._generated_layouts import CONSTANTS, HEADERS

# Sage 50 field-length limits (truncating beats a rejected import row).
MAX_CUSTOMER_ID = 20
MAX_CUSTOMER_NAME = 39
MAX_INVOICE_NO = 20
MAX_REFERENCE = 20
MAX_ADDRESS = 30
MAX_SHIP_VIA = 20
MAX_DESCRIPTION = 160
MAX_REASON = 30

# Columns taken from CONSTANTS that must instead be computed per row.
_COMPUTED = {"Transaction Period"}

Blocked = Dict[str, Any]

# Columns each builder actually sets (vs. template defaults). Filled in by
# make_row as it runs, so it can't drift from the builders.
SET_BY_ACE: Dict[str, set] = {}


# ---------------------------------------------------------------------------
# Formatting
# ---------------------------------------------------------------------------

def fmt_date(d: Optional[dt.date]) -> str:
    if d is None:
        return ""
    return f"{d.month}/{d.day}/{d.year % 100:02d}"


def _dec(x: Any) -> Decimal:
    return Decimal(str(x or 0)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def money(x: Any) -> str:
    return f"{_dec(x):.2f}"


def trunc(s: Any, n: int) -> str:
    return str(s or "").strip()[:n]


def expiry_label(v: Any) -> str:
    """Sage's `UPC / SKU` column carries the batch expiry as MM/YY."""
    if not v:
        return ""
    try:
        d = v if isinstance(v, dt.date) else dt.date.fromisoformat(str(v)[:10])
        return f"{d.month:02d}/{d.year % 100:02d}"
    except ValueError:
        return ""


def transaction_period(d: dt.date, settings: Dict[str, Any]) -> str:
    """Sage numbers accounting periods consecutively; derive from one anchor."""
    anchor: dt.date = settings["period_anchor_month"]
    months = (d.year - anchor.year) * 12 + (d.month - anchor.month)
    return str(int(settings["period_anchor_number"]) + months)


def displayed_terms(terms: Optional[str]) -> str:
    t = (terms or "").strip()
    if not t or t.lower() in {"due on receipt", "cod", "c.o.d", "cash"}:
        return "C.O.D."
    return trunc(t, 20)


def make_row(doc: str, values: Dict[str, Any]) -> List[str]:
    """Lay values out in template order; unset columns take the template's
    constant value (e.g. `Tax Type`=1, GUID placeholders) or blank."""
    header = HEADERS[doc]
    unknown = set(values) - set(header)
    if unknown:  # a typo here would silently drop data -- fail loudly instead
        raise KeyError(f"{doc}: unknown Sage column(s) {sorted(unknown)}")
    SET_BY_ACE.setdefault(doc, set()).update(k for k, v in values.items() if v not in (None, ""))
    consts = CONSTANTS.get(doc, {})
    out = []
    for col in header:
        if col in values:
            v = values[col]
            out.append("" if v is None else str(v))
        elif col in consts and col not in _COMPUTED:
            out.append(consts[col])
        else:
            out.append("")
    return out


# Columns a user may never untick: without them Sage can't post the
# transaction at all (who, which document, when, which account, how much).
REQUIRED: Dict[str, List[str]] = {
    "customer": ["Customer ID", "Customer Name"],
    "sales": [
        "Customer ID", "Invoice/CM #", "Date", "Accounts Receivable Account",
        "Accounts Receivable Amount", "Number of Distributions", "Invoice/CM Distribution",
        "Quantity", "Item ID", "G/L Account", "Unit Price", "Amount",
        "Inventory Account", "Cost of Sales Account",
    ],
    "receipts": [
        "Customer ID", "Reference", "Date", "Payment Method", "Cash Account", "Cash Amount",
        "Number of Distributions", "Invoice Paid", "G/L Account", "Amount",
    ],
    "adjust": [
        "Item ID", "Reference", "Date", "Inventory Account", "Number of Distributions",
        "G/L Source Account", "Unit Cost", "Quantity", "Amount",
    ],
}


def select_columns(doc: str, wanted: Optional[Iterable[str]]) -> List[str]:
    """The columns to write, always in template order. None/empty = all
    (which is how the client's Sage templates were exported)."""
    header = HEADERS[doc]
    if not wanted:
        return list(header)
    keep = set(wanted) | set(REQUIRED.get(doc, []))
    return [c for c in header if c in keep]


def to_csv(doc: str, rows: Iterable[List[str]], columns: Optional[Iterable[str]] = None) -> str:
    cols = select_columns(doc, columns)
    idx = [HEADERS[doc].index(c) for c in cols]
    buf = io.StringIO()
    w = csv.writer(buf, quoting=csv.QUOTE_MINIMAL, lineterminator="\r\n")
    w.writerow(cols)
    w.writerows([r[i] for i in idx] for r in rows)
    return buf.getvalue()


def beyond_open_period(d: dt.date, settings: Dict[str, Any]) -> Optional[str]:
    """Sage refuses (at the Date field) anything outside its open fiscal
    years. Hold such records back with a plain reason instead."""
    limit = settings.get("sage_open_until")
    if limit and d > limit:
        return (f"Dated {d:%d %b %Y}, but Sage is only open up to {limit:%d %b %Y}")
    return None


_OPEN_FIX = "The accountant must open the next fiscal year in Sage (Year-End Wizard), then update 'Sage open up to' in Export settings"


def _block(doc: str, source_id: Any, ref: str, reason: str, fix: str = "") -> Blocked:
    return {"doc_type": doc, "source_id": str(source_id), "ref": ref, "reason": reason, "fix": fix}


# ---------------------------------------------------------------------------
# Sales Journal
# ---------------------------------------------------------------------------

def build_sales(
    invoices: List[Dict[str, Any]],
    item_accounts: Dict[str, Dict[str, Any]],
    settings: Dict[str, Any],
) -> Tuple[List[List[str]], List[Blocked], List[str]]:
    """Returns (rows, blocked, exported_invoice_ids).

    Each invoice dict: id, invoice_number, date, due_date, terms, customer_id,
    customer_name, customer_po, ship_via, ship_address, tax_amount,
    total_amount, lines=[{sku, product, quantity, unit_price, line_total,
    expiry_date}]. `sku` is already resolved (None if unresolvable).
    """
    rows: List[List[str]] = []
    blocked: List[Blocked] = []
    exported: List[str] = []
    txn_no = 0

    for inv in invoices:
        ref = inv["invoice_number"]
        if not inv.get("customer_id"):
            blocked.append(_block(
                "sales", inv["id"], ref,
                f"Customer '{inv.get('customer_name') or '?'}' is not linked to a Sage customer",
                "Link the walk-in to a CRM customer (Customer Workspace), then re-preview",
            ))
            continue
        if _dec(inv.get("tax_amount")) > 0:
            blocked.append(_block(
                "sales", inv["id"], ref,
                "Invoice carries VAT; the client's Sage sales are posted without VAT",
                "Confirm VAT treatment with the accountant and enter this invoice in Sage manually",
            ))
            continue
        closed = beyond_open_period(inv["date"], settings)
        if closed:
            blocked.append(_block("sales", inv["id"], ref, closed, _OPEN_FIX))
            continue
        if len(ref) > MAX_INVOICE_NO:
            blocked.append(_block("sales", inv["id"], ref, "Invoice number longer than 20 characters"))
            continue
        lines = [l for l in (inv.get("lines") or []) if float(l.get("quantity") or 0) > 0]
        if not lines:
            blocked.append(_block("sales", inv["id"], ref, "Invoice has no lines with a quantity"))
            continue

        problem = None
        built: List[Dict[str, Any]] = []
        for l in lines:
            sku = l.get("sku")
            acct = item_accounts.get(sku) if sku else None
            if not sku:
                problem = f"Line '{l.get('product')}' is not matched to a Sage Item ID"
                break
            if not acct:
                problem = f"Item '{sku}' is not in the Sage item list (import ITEM.CSV as Item GL Accounts)"
                break
            if not (acct.get("sales_account") and acct.get("inventory_account") and acct.get("cogs_account")):
                problem = f"Item '{sku}' has no Sales/Inventory/COGS account in Sage"
                break
            qty = _dec(l.get("quantity"))
            price = _dec(l.get("unit_price"))
            line_total = _dec(l.get("line_total")) if l.get("line_total") not in (None, "") else _dec(qty * price)
            built.append({"l": l, "sku": sku, "acct": acct, "qty": qty, "price": price, "total": line_total})
        if problem:
            blocked.append(_block("sales", inv["id"], ref, problem,
                                  "Fix the product on the invoice or add the item in Sage first"))
            continue

        ar_amount = sum((b["total"] for b in built), Decimal("0"))
        if inv.get("total_amount") not in (None, "") and abs(ar_amount - _dec(inv["total_amount"])) > Decimal("0.01"):
            blocked.append(_block(
                "sales", inv["id"], ref,
                f"Line totals ({money(ar_amount)}) do not match invoice total ({money(inv['total_amount'])})",
            ))
            continue

        txn_no += 1
        date: dt.date = inv["date"]
        header = {
            "Customer ID": trunc(inv["customer_id"], MAX_CUSTOMER_ID),
            "Customer Name": trunc(inv.get("customer_name"), MAX_CUSTOMER_NAME),
            "Invoice/CM #": ref,
            "Apply to Invoice Number": "",
            "Credit Memo": "FALSE",
            "Date": fmt_date(date),
            "Ship to Address-Line One": trunc(inv.get("ship_address"), MAX_ADDRESS),
            "Customer PO": trunc(inv.get("customer_po"), 20),
            "Ship Via": trunc(inv.get("ship_via"), MAX_SHIP_VIA),
            "Date Due": fmt_date(inv.get("due_date") or date),
            "Discount Date": fmt_date(date),
            "Displayed Terms": displayed_terms(inv.get("terms")),
            "Accounts Receivable Account": settings.get("ar_account") or "11000",
            "Accounts Receivable Amount": money(ar_amount),
            "Number of Distributions": str(len(built)),
            "Apply to Invoice Distribution": "0",
            "Transaction Period": transaction_period(date, settings),
            "Transaction Number": str(txn_no),
        }
        for i, b in enumerate(built, start=1):
            acct = b["acct"]
            unit_cost = _dec(acct.get("last_unit_cost"))
            rows.append(make_row("sales", {
                **header,
                "Invoice/CM Distribution": str(i),
                "Quantity": money(b["qty"]),
                "Item ID": b["sku"],
                "Description": trunc(acct.get("item_description") or b["l"].get("product"), MAX_DESCRIPTION),
                "G/L Account": acct["sales_account"],
                "Unit Price": money(b["price"]),
                "UPC / SKU": expiry_label(b["l"].get("expiry_date")),
                "Amount": money(-b["total"]),
                "Inventory Account": acct["inventory_account"],
                "Cost of Sales Account": acct["cogs_account"],
                "U/M ID": "<Each>",
                "Stocking Quantity": money(b["qty"]),
                "Stocking Unit Price": money(b["price"]),
                "Cost of Sales Amount": money(b["qty"] * unit_cost),
            }))
        exported.append(str(inv["id"]))
    return rows, blocked, exported


# ---------------------------------------------------------------------------
# Cash Receipts Journal
# ---------------------------------------------------------------------------

def build_receipts(
    receipts: List[Dict[str, Any]],
    settings: Dict[str, Any],
) -> Tuple[List[List[str]], List[Blocked], List[str]]:
    """Each receipt: id, receipt_number, customer_id, customer_name, date,
    amount, payment_method, applications=[{invoice_id, amount}]."""
    rows: List[List[str]] = []
    blocked: List[Blocked] = []
    exported: List[str] = []
    method_map: Dict[str, Dict[str, str]] = settings.get("payment_method_map") or {}
    txn_no = 0

    for r in receipts:
        ref = r["receipt_number"]
        pm = method_map.get((r.get("payment_method") or "").lower())
        apps = [a for a in (r.get("applications") or []) if _dec(a.get("amount")) > 0]
        amount = _dec(r.get("amount"))
        applied = sum((_dec(a["amount"]) for a in apps), Decimal("0"))
        if not r.get("customer_id"):
            blocked.append(_block("receipts", r["id"], ref, "Receipt has no Sage customer ID"))
            continue
        closed = beyond_open_period(r["date"], settings)
        if closed:
            blocked.append(_block("receipts", r["id"], ref, closed, _OPEN_FIX))
            continue
        if not pm or not pm.get("cash_account"):
            blocked.append(_block("receipts", r["id"], ref,
                                  f"No Sage cash account mapped for payment method '{r.get('payment_method')}'",
                                  "Add it under Export settings > Payment methods"))
            continue
        if not apps:
            blocked.append(_block("receipts", r["id"], ref,
                                  "Receipt is not applied to any invoice (prepayment)",
                                  "Enter prepayments in Sage directly"))
            continue
        if abs(applied - amount) > Decimal("0.01"):
            blocked.append(_block("receipts", r["id"], ref,
                                  f"Only {money(applied)} of {money(amount)} is applied to invoices",
                                  "Apply the full amount, or enter the remainder in Sage"))
            continue

        txn_no += 1
        date: dt.date = r["date"]
        header = {
            "Customer ID": trunc(r["customer_id"], MAX_CUSTOMER_ID),
            "Customer Name": trunc(r.get("customer_name"), MAX_CUSTOMER_NAME),
            "Reference": trunc(pm.get("reference") or "TRANSFER", MAX_REFERENCE),
            "Date": fmt_date(date),
            "Payment Method": pm.get("method") or "Check",
            "Cash Account": pm["cash_account"],
            "Cash Amount": money(amount),
            "Total Paid on Invoice(s)": money(-amount),
            "Prepayment": "FALSE",
            "Number of Distributions": str(len(apps)),
            "G/L Account": settings.get("ar_account") or "11000",
            "Transaction Period": transaction_period(date, settings),
            "Transaction Number": str(txn_no),
            "Receipt Number": trunc(ref, MAX_REFERENCE),
            # Always present on the client's invoice-payment rows (206/208).
            "Tax Type": "0",
            "U/M No. of Stocking Units": "0.00",
        }
        for a in apps:
            rows.append(make_row("receipts", {
                **header,
                "Invoice Paid": trunc(a["invoice_id"], MAX_INVOICE_NO),
                "Amount": money(-_dec(a["amount"])),
            }))
        exported.append(str(r["id"]))
    return rows, blocked, exported


# ---------------------------------------------------------------------------
# Inventory Adjustments Journal
# ---------------------------------------------------------------------------

def build_adjustments(
    events: List[Dict[str, Any]],
    item_accounts: Dict[str, Dict[str, Any]],
    settings: Dict[str, Any],
) -> Tuple[List[List[str]], List[Blocked], List[str]]:
    """Each event: id, sku, quantity_change (signed), event_type, reference, date.

    Signs follow the rule every other client template obeys (checked across
    SALES/RECEIPTS/PURCHASE/PAYMENTS): positive = debit, negative = credit,
    and the header amount is the exact negative of the distribution amounts.
    Stock out: Amount Adjusted (inventory account) is negative = credit,
    Amount (G/L Source / write-off account) positive = debit. Sage rejected
    the first test file, which had both negative, at G/L Source Account.
    """
    rows: List[List[str]] = []
    blocked: List[Blocked] = []
    exported: List[str] = []
    writeoff = settings.get("writeoff_gl_account")
    txn_no = 0

    for e in events:
        ref = f"ACE-ADJ-{e['id']}"
        acct = item_accounts.get(e.get("sku") or "")
        if not writeoff:
            blocked.append(_block("adjust", e["id"], ref, "No write-off GL account configured",
                                  "Set it under Export settings (ask the accountant which account)"))
            continue
        if not acct or not acct.get("inventory_account"):
            blocked.append(_block("adjust", e["id"], ref,
                                  f"Item '{e.get('sku')}' is not in the Sage item list"))
            continue
        closed = beyond_open_period(e["date"], settings)
        if closed:
            blocked.append(_block("adjust", e["id"], ref, closed, _OPEN_FIX))
            continue
        qty = _dec(e.get("quantity_change"))
        if qty == 0:
            continue
        unit_cost = _dec(acct.get("last_unit_cost"))
        amount = qty * unit_cost
        txn_no += 1
        date: dt.date = e["date"]
        reason = f"{e.get('event_type', '').title()}: {e.get('reference') or ''}".strip(": ")
        rows.append(make_row("adjust", {
            "Item ID": e["sku"],
            "Reference": trunc(ref, MAX_REFERENCE),
            "Date": fmt_date(date),
            "Reason to Adjust": trunc(reason, MAX_REASON),
            "Inventory Account": acct["inventory_account"],
            "Amount Adjusted": money(amount),
            "Number of Distributions": "1",
            "G/L Source Account": writeoff,
            "Unit Cost": money(unit_cost),
            "Quantity": money(qty),
            "Amount": money(-amount),
            "Transaction Period": transaction_period(date, settings),
            "Transaction Number": str(txn_no),
        }))
        exported.append(str(e["id"]))
    return rows, blocked, exported


# ---------------------------------------------------------------------------
# Customer List (only customers Sage doesn't have yet)
# ---------------------------------------------------------------------------

def build_customers(customers: List[Dict[str, Any]], today: dt.date) -> List[List[str]]:
    """Each: customer_id (<=20, already assigned), name, phone, email, address, city.

    Non-constant defaults mirror the majority of the client's existing
    customer records (credit limit 10,000,000, Net 30, not a prospect).
    """
    rows = []
    for c in customers:
        rows.append(make_row("customer", {
            "Customer ID": trunc(c["customer_id"], MAX_CUSTOMER_ID),
            "Customer Name": trunc(c.get("name"), MAX_CUSTOMER_NAME),
            "Prospect": "FALSE",
            "Bill to Address-Line One": trunc(c.get("address"), MAX_ADDRESS),
            "Bill to City": trunc(c.get("city"), 20),
            "Bill to Country": "NIGERIA",
            "Telephone 1": trunc(c.get("phone"), 20),
            "Customer E-mail": trunc(c.get("email"), 64),
            "G/L Sales Account": "11000",
            "Ship Via": "0",
            "Use Standard Terms": "FALSE",
            "C.O.D. Terms": "FALSE",
            "Credit Limit": "10000000.00",
            "Customer Since Date": fmt_date(today),
        }))
    return rows


def propose_customer_id(name: str, taken: set) -> str:
    """Sage-style ID: the name cut to 20 chars (as the client's own IDs are,
    e.g. 'Golden Cross Hospita'), made unique with a numeric suffix."""
    base = trunc(name, MAX_CUSTOMER_ID) or "ACE Customer"
    if base.lower() not in taken:
        return base
    for n in range(2, 1000):
        suffix = f"-{n}"
        cand = base[: MAX_CUSTOMER_ID - len(suffix)] + suffix
        if cand.lower() not in taken:
            return cand
    raise ValueError(f"cannot find a free Sage customer ID for {name!r}")
