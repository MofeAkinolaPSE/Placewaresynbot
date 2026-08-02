"""
test_invoice_extract.py — Data-extraction accuracy.

Covers the Step-2 requirement that every invoice field reaches SynBot: number,
date, customer, items, quantities, unit prices, totals, taxes, inventory
movement, payment info and status.

The original delivered only header fields, so these assertions are the
regression guard against sliding back to that.
"""
from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ.setdefault("BRIDGE_API_KEY", "test-key-that-is-long-enough-1234")
os.environ.setdefault("SAGE_MOCK", "true")

import invoice_extract as ix  # noqa: E402


# ── Numeric / date coercion ──────────────────────────────────────────────────

@pytest.mark.parametrize("raw,expected", [
    (None, 0.0), ("", 0.0), ("abc", 0.0),
    ("12.5", 12.5), (12.5, 12.5), (12, 12.0),
])
def test_num_never_raises(raw, expected):
    """Sage columns return odd types; extraction must not die on one bad cell."""
    assert ix._num(raw) == expected


@pytest.mark.parametrize("raw,expected", [
    ("2026-01-15", "2026-01-15"),
    ("01/15/2026", "2026-01-15"),
    ("20260115", "2026-01-15"),
    (None, None), ("", None), ("garbage", None),
])
def test_iso_date_normalisation(raw, expected):
    assert ix._iso_date(raw) == expected


def test_text_strips_sage_char_padding():
    """Sage pads CHAR columns; untrimmed values break fingerprint stability."""
    assert ix._text("CUST001   ") == "CUST001"


# ── Payment / status derivation ──────────────────────────────────────────────

def test_payment_unpaid():
    p = ix._derive_payment(1000.0, 0.0, "2099-01-01")
    assert p["payment_status"] == "unpaid"
    assert p["amount_due"] == 1000.0
    assert p["is_overdue"] is False


def test_payment_partial():
    p = ix._derive_payment(1000.0, 400.0, "2099-01-01")
    assert p["payment_status"] == "partial"
    assert p["amount_due"] == 600.0


def test_payment_paid():
    p = ix._derive_payment(1000.0, 1000.0, "2000-01-01")
    assert p["payment_status"] == "paid"
    assert p["amount_due"] == 0.0
    # A fully paid invoice is never overdue, regardless of due date.
    assert p["is_overdue"] is False


def test_payment_tolerates_rounding_noise():
    """0.004 left over from float money must read as paid, not partial."""
    p = ix._derive_payment(1000.0, 999.997, "2099-01-01")
    assert p["payment_status"] == "paid"


def test_payment_flags_overdue_with_day_count():
    p = ix._derive_payment(1000.0, 0.0, "2020-01-01")
    assert p["is_overdue"] is True
    assert p["days_overdue"] > 1000


# ── Inventory movement ───────────────────────────────────────────────────────

def test_inventory_movement_is_negative_for_a_sale():
    """
    Sign convention matters: a positive delta here would INFLATE stock on every
    sale. This is the single most damaging thing to get backwards.
    """
    lines = [{"item_id": "AMO500", "quantity": 25.0, "unit_price": 100.0,
              "description": "Amoxicillin"}]
    moves = ix._derive_inventory_movement(lines)
    assert len(moves) == 1
    assert moves[0]["quantity_delta"] == -25.0
    assert moves[0]["direction"] == "out"


def test_inventory_movement_skips_service_lines():
    """Lines with no item id are services/comments and move no stock."""
    lines = [
        {"item_id": "AMO500", "quantity": 5.0},
        {"item_id": "", "description": "Delivery charge", "quantity": 1.0},
        {"description": "Note only"},
    ]
    assert len(ix._derive_inventory_movement(lines)) == 1


def test_inventory_movement_ignores_zero_quantity():
    assert ix._derive_inventory_movement([{"item_id": "X", "quantity": 0}]) == []


def test_inventory_movement_normalises_sign_of_negative_input():
    """A credit line already negative must not become positive."""
    moves = ix._derive_inventory_movement([{"item_id": "X", "quantity": -4.0}])
    assert moves[0]["quantity_delta"] == -4.0


# ── Full record shape ────────────────────────────────────────────────────────

def _fake_sdk_invoice():
    return {
        "sage_id": "1001",
        "invoice_number": "PWR/INV/2026/001",
        "customer_id": "CUST001",
        "customer_name": "Lagos General Hospital",
        "date": "2026-01-15",
        "due_date": "2026-02-15",
        "po_number": "LGH/PO/2026/014",
        "total_amount": 787500.0,
        "amount_paid": 500000.0,
        "sales_tax_amount": 75000.0,
        "tax_code": "VAT",
        "note": "January supply",
        "lines": [
            {"line_no": 1, "item_id": "AMO500", "description": "Amoxicillin 500mg",
             "quantity": 25.0, "unit_price": 28500.0, "amount": 712500.0,
             "gl_account": "4000", "tax_type": "VAT", "tax_amount": 75000.0},
        ],
    }


def test_full_record_contains_every_required_field(monkeypatch):
    """One assertion per field named in the requirements."""
    import sdk_client
    monkeypatch.setattr(sdk_client, "sdk_get_invoice", lambda _id: _fake_sdk_invoice())

    rec = ix.extract_invoice("1001")
    assert rec is not None

    assert rec["sage_id"] == "1001"                       # invoice ID
    assert rec["invoice_number"] == "PWR/INV/2026/001"    # invoice number
    assert rec["date"] == "2026-01-15"                    # date
    assert rec["customer_id"] == "CUST001"                # customer
    assert rec["customer_name"] == "Lagos General Hospital"

    line = rec["lines"][0]
    assert line["item_id"] == "AMO500"                    # items
    assert line["quantity"] == 25.0                       # quantities
    assert line["unit_price"] == 28500.0                  # unit prices
    assert line["amount"] == 712500.0

    assert rec["subtotal"] == 712500.0                    # totals
    assert rec["payment"]["total_amount"] == 787500.0
    assert rec["tax"]["total_tax"] == 75000.0             # taxes
    assert rec["tax"]["tax_code"] == "VAT"

    assert rec["inventory_movement"][0]["quantity_delta"] == -25.0  # inventory
    assert rec["payment"]["amount_paid"] == 500000.0      # payment info
    assert rec["payment"]["payment_status"] == "partial"  # status
    assert rec["_meta"]["completeness"] == "full"         # metadata


def test_sdk_failure_falls_back_to_odbc_and_marks_partial(monkeypatch):
    """
    A degraded record must be LABELLED degraded, never passed off as complete —
    downstream finance figures depend on knowing the difference.
    """
    import sdk_client
    def boom(_id):
        raise RuntimeError("SDK session dead")
    monkeypatch.setattr(sdk_client, "sdk_get_invoice", boom)
    monkeypatch.setattr(ix.odbc, "fetch_all", lambda *a, **k: [])

    header = {"transno": "1001", "reference": "INV-1", "acctid": "CUST001",
              "date": "2026-01-15", "amount": 1000.0, "amtpaid": 0.0}
    rec = ix.extract_invoice("1001", header_row=header)

    assert rec is not None
    assert rec["_meta"]["completeness"] == "partial"
    assert rec["_meta"]["source"] == "odbc"
    assert "tax" in rec["_meta"]["missing"]
    assert "unavailable_reason" in rec["tax"]


def test_returns_none_when_both_sources_fail(monkeypatch):
    """
    None tells the watcher to leave the watermark unadvanced so the invoice is
    retried — the alternative would be silently skipping it.
    """
    import sdk_client
    monkeypatch.setattr(sdk_client, "sdk_get_invoice",
                        lambda _id: (_ for _ in ()).throw(RuntimeError("dead")))
    assert ix.extract_invoice("1001", header_row=None) is None
