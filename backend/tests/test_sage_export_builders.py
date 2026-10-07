"""Sage export builders must reproduce the client's own Sage Import/Export
templates exactly -- Sage maps import columns by position, so a wrong header
order or sign convention posts garbage rather than failing."""
import csv
import datetime as dt
from pathlib import Path

import pytest

from src.services.sage_export import builders as B
from src.services.sage_export._generated_layouts import HEADERS

TEMPLATES = Path(__file__).resolve().parents[1] / "docs" / "Latestmods-TB" / "sage-link" / "export-templates"
SETTINGS = {
    "ar_account": "11000",
    "period_anchor_month": dt.date(2026, 6, 1),
    "period_anchor_number": 34,
    "writeoff_gl_account": "59999",
    "payment_method_map": {
        "cash": {"method": "Cash", "cash_account": "10100", "reference": "CASH"},
        "bank_transfer": {"method": "Check", "cash_account": "10290", "reference": "TRANSFER"},
    },
}
ITEMS = {
    "HEXAXIM (Q)": {"item_id": "HEXAXIM (Q)", "item_description": "HEXAXIM", "sales_account": "40548",
                    "inventory_account": "12352", "cogs_account": "50748", "last_unit_cost": 30772},
    "MENACTRA (R)": {"item_id": "MENACTRA (R)", "item_description": "MENACTRA", "sales_account": "40505",
                     "inventory_account": "12305", "cogs_account": "50705", "last_unit_cost": 24500},
}


def _parse(doc, rows):
    text = B.to_csv(doc, rows)
    return list(csv.DictReader(text.splitlines()))


@pytest.mark.parametrize("doc,fname", [
    ("sales", "SALES.CSV"), ("receipts", "RECEIPTS.CSV"),
    ("adjust", "ADJUST.CSV"), ("customer", "CUSTOMER.CSV"),
])
def test_headers_match_client_templates(doc, fname):
    path = TEMPLATES / fname
    if not path.exists():
        pytest.skip("template files not shipped in this image")
    with open(path, newline="", encoding="latin-1") as fh:
        assert next(csv.reader(fh)) == HEADERS[doc]


def test_formatting_matches_sage():
    assert B.fmt_date(dt.date(2026, 6, 1)) == "6/1/26"
    assert B.fmt_date(dt.date(2026, 12, 25)) == "12/25/26"
    assert B.transaction_period(dt.date(2026, 6, 15), SETTINGS) == "34"
    assert B.transaction_period(dt.date(2026, 9, 1), SETTINGS) == "37"
    assert B.transaction_period(dt.date(2027, 1, 1), SETTINGS) == "41"
    assert B.expiry_label("2025-07-31") == "07/25"
    assert B.displayed_terms("Due on Receipt") == "C.O.D."
    assert B.displayed_terms("Net 30 Days") == "Net 30 Days"


def _invoice(**kw):
    inv = {
        "id": "u1", "invoice_number": "INV-20260901-ABC123", "date": dt.date(2026, 9, 1),
        "due_date": dt.date(2026, 10, 1), "terms": "Net 30 Days", "customer_id": "ANNOX NIG. LTD",
        "customer_name": "ANNOX NIG.LTD", "tax_amount": 0, "total_amount": 6019200,
        "lines": [
            {"sku": "HEXAXIM (Q)", "product": "HEXAXIM", "quantity": 160, "unit_price": 33620,
             "line_total": 5379200, "expiry_date": "2024-04-30"},
            {"sku": "MENACTRA (R)", "product": "MENACTRA", "quantity": 20, "unit_price": 32000,
             "line_total": 640000},
        ],
    }
    inv.update(kw)
    return inv


def test_sales_rows_follow_template_conventions():
    rows, blocked, ids = B.build_sales([_invoice()], ITEMS, SETTINGS)
    assert blocked == [] and ids == ["u1"]
    parsed = _parse("sales", rows)
    assert len(parsed) == 2
    first, second = parsed
    # header fields repeated on every distribution
    for r in parsed:
        assert r["Invoice/CM #"] == "INV-20260901-ABC123"
        assert r["Customer ID"] == "ANNOX NIG. LTD"
        assert r["Date"] == "9/1/26" and r["Date Due"] == "10/1/26"
        assert r["Accounts Receivable Account"] == "11000"
        assert r["Accounts Receivable Amount"] == "6019200.00"
        assert r["Number of Distributions"] == "2"
        assert r["Tax Type"] == "1" and r["Credit Memo"] == "FALSE"
        assert r["Transaction Period"] == "37"
    assert [r["Invoice/CM Distribution"] for r in parsed] == ["1", "2"]
    # credits are negative; AR amount is -sum(Amount)
    assert first["Amount"] == "-5379200.00" and second["Amount"] == "-640000.00"
    assert first["G/L Account"] == "40548"
    assert first["Inventory Account"] == "12352" and first["Cost of Sales Account"] == "50748"
    assert first["Item ID"] == "HEXAXIM (Q)" and first["Quantity"] == "160.00"
    assert first["U/M ID"] == "<Each>" and first["UPC / SKU"] == "04/24"
    assert first["Cost of Sales Amount"] == "4923520.00"  # 160 x 30772


@pytest.mark.parametrize("change,reason", [
    ({"customer_id": None}, "not linked to a Sage customer"),
    ({"tax_amount": 1500}, "VAT"),
    ({"total_amount": 1}, "do not match"),
    ({"lines": [{"sku": None, "product": "Mystery", "quantity": 1, "unit_price": 1}]}, "not matched"),
    ({"lines": [{"sku": "UNKNOWN", "product": "X", "quantity": 1, "unit_price": 1}], "total_amount": 1},
     "not in the Sage item list"),
])
def test_sales_blocks_whole_invoice(change, reason):
    rows, blocked, ids = B.build_sales([_invoice(**change)], ITEMS, SETTINGS)
    assert rows == [] and ids == []
    assert reason in blocked[0]["reason"]


def test_receipts_rows_follow_template_conventions():
    receipt = {
        "id": "r1", "receipt_number": "RCT-0001", "customer_id": "B.J Pharmacy",
        "customer_name": "B.J Pharmacy", "date": dt.date(2026, 6, 2), "amount": 200000,
        "payment_method": "cash",
        "applications": [{"invoice_id": "51779", "amount": 120958.82},
                         {"invoice_id": "51850", "amount": 79041.18}],
    }
    rows, blocked, ids = B.build_receipts([receipt], SETTINGS)
    assert blocked == [] and ids == ["r1"]
    parsed = _parse("receipts", rows)
    assert [r["Invoice Paid"] for r in parsed] == ["51779", "51850"]
    assert [r["Amount"] for r in parsed] == ["-120958.82", "-79041.18"]
    for r in parsed:
        assert r["Cash Amount"] == "200000.00" and r["Total Paid on Invoice(s)"] == "-200000.00"
        assert r["Payment Method"] == "Cash" and r["Cash Account"] == "10100"
        assert r["Reference"] == "CASH" and r["G/L Account"] == "11000"
        assert r["Number of Distributions"] == "2" and r["Prepayment"] == "FALSE"
        assert r["Credit Card Stored Reference"] == "{00000000-0000-0000-0000-000000000000}"


def test_receipts_block_unmapped_and_partial():
    base = {"id": "r", "receipt_number": "R", "customer_id": "C", "date": dt.date(2026, 6, 2),
            "amount": 100, "payment_method": "bank_transfer",
            "applications": [{"invoice_id": "1", "amount": 60}]}
    _, blocked, _ = B.build_receipts([base], SETTINGS)
    assert "Only 60.00 of 100.00" in blocked[0]["reason"]
    _, blocked, _ = B.build_receipts([{**base, "payment_method": "barter"}], SETTINGS)
    assert "No Sage cash account" in blocked[0]["reason"]
    _, blocked, _ = B.build_receipts([{**base, "applications": []}], SETTINGS)
    assert "prepayment" in blocked[0]["reason"]


def test_adjustment_row():
    ev = {"id": 7, "sku": "MENACTRA (R)", "quantity_change": -3, "event_type": "EXPIRY",
          "reference": "batch R expired", "date": dt.date(2026, 9, 3)}
    rows, blocked, ids = B.build_adjustments([ev], ITEMS, SETTINGS)
    assert blocked == [] and ids == ["7"]
    r = _parse("adjust", rows)[0]
    assert r["Item ID"] == "MENACTRA (R)" and r["Quantity"] == "-3.00"
    # credit inventory (header) / debit write-off (distribution): balances like every Sage template
    assert r["Amount Adjusted"] == "-73500.00" and r["Amount"] == "73500.00" and r["Unit Cost"] == "24500.00"
    assert r["Inventory Account"] == "12305" and r["G/L Source Account"] == "59999"
    _, blocked, _ = B.build_adjustments([ev], ITEMS, {**SETTINGS, "writeoff_gl_account": None})
    assert "write-off" in blocked[0]["reason"]


def test_customer_row_and_id_proposal():
    taken = {"golden cross hospita"}
    assert B.propose_customer_id("Golden Cross Hospital Ltd", taken) == "Golden Cross Hospi-2"
    assert B.propose_customer_id("New Pharmacy", taken) == "New Pharmacy"
    rows = B.build_customers([{"customer_id": "New Pharmacy", "name": "New Pharmacy", "phone": "080"}],
                             dt.date(2026, 9, 24))
    r = _parse("customer", rows)[0]
    assert r["Customer ID"] == "New Pharmacy" and r["Customer Since Date"] == "9/24/26"
    assert r["Use Receipt Settings"] == "TRUE" and r["Due Days"] == "30"


def test_unknown_column_fails_loudly():
    with pytest.raises(KeyError):
        B.make_row("sales", {"Customer Id": "typo"})


def test_column_selection_keeps_required_and_template_order():
    rows, _, _ = B.build_sales([_invoice()], ITEMS, SETTINGS)
    # "Amount" is required, so asking only for Description still keeps it;
    # output stays in template order regardless of the order asked for.
    cols = B.select_columns("sales", ["Description", "Customer Name"])
    assert cols == [c for c in HEADERS["sales"] if c in set(B.REQUIRED["sales"]) | {"Description", "Customer Name"}]
    parsed = list(csv.DictReader(B.to_csv("sales", rows, ["Description"]).splitlines()))
    assert list(parsed[0]) == B.select_columns("sales", ["Description"])
    assert parsed[0]["Amount"] == "-5379200.00" and parsed[0]["Description"] == "HEXAXIM"
    assert B.select_columns("sales", None) == HEADERS["sales"]


def test_receipts_fill_columns_sage_always_fills():
    rows, _, _ = B.build_receipts([{
        "id": "r", "receipt_number": "R1", "customer_id": "C", "date": dt.date(2026, 6, 2),
        "amount": 10, "payment_method": "cash", "applications": [{"invoice_id": "1", "amount": 10}]}], SETTINGS)
    r = _parse("receipts", rows)[0]
    assert r["Tax Type"] == "0" and r["U/M No. of Stocking Units"] == "0.00"


def test_records_after_sage_open_period_are_held_back():
    s = {**SETTINGS, "sage_open_until": dt.date(2026, 6, 30)}
    rows, blocked, _ = B.build_sales([_invoice(date=dt.date(2026, 7, 31))], ITEMS, s)
    assert rows == [] and "only open up to 30 Jun 2026" in blocked[0]["reason"]
    rows, blocked, _ = B.build_sales([_invoice(date=dt.date(2026, 6, 30))], ITEMS, s)
    assert rows and not blocked
