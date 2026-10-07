"""Golden vertical slices (Development Engine spec §59): each business event
must produce the exact accounting, move the subledger, and leave the books
reconciled (Balance Sheet balances, AR/AP/inventory agree with the GL)."""
import datetime as dt
import uuid
from decimal import Decimal

import pytest

from src.fin import (accounts, assets, banking, closing, controls, inventory, periods, posting, purchases,
                     reports, sales, setup)
from src.fin.db import ex, q, q1
from src.fin.errors import FinError

D = dt.date(2026, 7, 10)


@pytest.fixture
def books(conn, make_entity):
    ctx, a = make_entity()
    extra = [("10500", "Petty Cash", "CASH"), ("48000", "Sales Returns", "SALES"), ("49000", "Sales Discounts", "SALES"),
             ("58500", "Inventory Adjustments", "COST_OF_SALES"), ("12990", "Stock on Loan", "OTHER_CURRENT_ASSET"),
             ("78200", "WHT suffered", "OPERATING_EXPENSE"), ("23700", "WHT payable", "OTHER_CURRENT_LIABILITY"),
             ("15150", "Motor Vehicles", "FIXED_ASSET"), ("17200", "Accum Dep MV", "ACCUMULATED_DEPRECIATION"),
             ("90300", "Depreciation MV", "OPERATING_EXPENSE"), ("90000", "Gain/Loss on disposal", "OTHER_EXPENSE"),
             ("64000", "Transport", "OPERATING_EXPENSE")]
    for c, n, st in extra:
        a[c] = accounts.create_account(conn, ctx, {"code": c, "name": n, "subtype": st})
    for key, code in {"AR_CONTROL": "11000", "AP_CONTROL": "20000", "SALES_DEFAULT": "40000", "INVENTORY_DEFAULT": "12000",
                      "COGS_DEFAULT": "50000", "DELIVERY_INCOME": "40800", "SALES_DISCOUNT": "49000",
                      "SALES_RETURNS": "48000", "INVENTORY_ADJUSTMENT": "58500", "STOCK_ON_LOAN": "12990",
                      "WHT_SUFFERED": "78200", "WHT_PAYABLE": "23700", "RETAINED_EARNINGS": "39005",
                      "ASSET_DISPOSAL": "90000"}.items():
        setup.set_mapping(conn, ctx, key, a[code]["id"])
    banks = {}
    for code, kind in (("10290", "BANK"), ("10100", "CASH")):
        banks[code] = banking.create_account(conn, ctx, {"gl_account_id": a[code]["id"], "kind": kind})
    for sku in ("ROTARIX", "MENACTRA"):
        ex(conn, """INSERT INTO fin_products (legal_entity_id, sku, name, revenue_account_id, inventory_account_id, cogs_account_id)
                    VALUES (%s,%s,%s,%s,%s,%s)""", (ctx.entity_id, sku, sku, a["40000"]["id"], a["12000"]["id"], a["50000"]["id"]))
    cust = q1(conn, "INSERT INTO customers (name, customer_code, credit_limit) VALUES (%s,%s,%s) RETURNING id",
              ("Test Hospital " + uuid.uuid4().hex[:6], "TH" + uuid.uuid4().hex[:8], 1_000_000))["id"]
    sup = str(q1(conn, "INSERT INTO suppliers (name, external_vendor_id) VALUES (%s,%s) RETURNING id",
                 ("Test Supplier " + uuid.uuid4().hex[:6], "TS" + uuid.uuid4().hex[:8]))["id"])
    return {"ctx": ctx, "a": a, "banks": banks, "customer": cust, "supplier": sup}


def _bal(conn, ctx, acct):
    return ledger_bal(conn, ctx.entity_id, acct["id"])


def ledger_bal(conn, entity_id, account_id, on=dt.date(2026, 12, 31)):
    r = q1(conn, "SELECT COALESCE(SUM(debit-credit),0) b FROM fin_v_general_ledger WHERE account_id=%s AND journal_date<=%s",
           (account_id, on))
    return Decimal(str(r["b"]))


def _reconciled(conn, ctx, on=dt.date(2026, 12, 31)):
    bs = reports.balance_sheet(conn, ctx.entity_id, on)
    assert bs["balanced"], bs["difference"]
    res = {r["code"]: r for r in controls.run_checks(conn, ctx.entity_id, on)}
    for code in ("LEDGER_BALANCED", "AR_RECONCILES", "AP_RECONCILES", "INVENTORY_RECONCILES", "STOCK_ON_LOAN_RECONCILES"):
        assert res[code]["status"] == "PASS", res[code]
    cf = reports.cash_flow(conn, ctx.entity_id, dt.date(2026, 1, 1), on)
    assert cf["reconciles"], cf


def _buy(conn, B, sku="ROTARIX", qty=100, cost=4645, batch="M", expiry="2027-06-30", inv_no=None):
    return purchases.create_bill(conn, B["ctx"], {
        "supplier_id": B["supplier"], "supplier_invoice_number": inv_no or uuid.uuid4().hex[:8], "bill_date": dt.date(2026, 7, 1),
        "lines": [{"line_type": "ITEM", "sku": sku, "quantity": qty, "unit_cost": cost, "batch_number": batch,
                   "expiry_date": expiry}]})


def test_purchase_then_credit_sale_posts_ar_revenue_cogs_and_stock(conn, books):
    B = books
    ctx, a = B["ctx"], B["a"]
    bill = _buy(conn, B)
    assert Decimal(str(bill["total"])) == Decimal("464500.00")
    assert _bal(conn, ctx, a["12000"]) == Decimal("464500.00") and _bal(conn, ctx, a["20000"]) == Decimal("-464500.00")
    inv = sales.create_invoice(conn, ctx, {"customer_id": B["customer"], "invoice_date": D, "lines": [
        {"line_type": "ITEM", "sku": "ROTARIX", "quantity": 10, "unit_price": 5600, "discount_amount": 1000},
        {"line_type": "CHARGE", "description": "Delivery charge", "unit_price": 10000}]})
    inv = sales.post_invoice(conn, ctx, str(inv["id"]))
    assert inv["status"] == "POSTED" and Decimal(str(inv["total"])) == Decimal("65000.00")   # 56,000 - 1,000 + 10,000
    assert _bal(conn, ctx, a["11000"]) == Decimal("65000.00")
    assert _bal(conn, ctx, a["40000"]) == Decimal("-56000.00")        # gross product sales
    assert _bal(conn, ctx, a["49000"]) == Decimal("1000.00")          # discount in its own head
    assert _bal(conn, ctx, a["40800"]) == Decimal("-10000.00")        # delivery to other income, not sales
    assert _bal(conn, ctx, a["50000"]) == Decimal("46450.00")         # 10 x 4,645 FIFO
    assert inventory.on_hand(conn, ctx.entity_id, "ROTARIX")["quantity"] == 90
    _reconciled(conn, ctx)


def test_receipts_partial_overpayment_and_wht(conn, books):
    B = books
    ctx, a = B["ctx"], B["a"]
    _buy(conn, B)
    inv = sales.post_invoice(conn, ctx, str(sales.create_invoice(conn, ctx, {"customer_id": B["customer"], "invoice_date": D,
                             "lines": [{"sku": "ROTARIX", "quantity": 20, "unit_price": 5000}]})["id"]))
    r1 = sales.create_receipt(conn, ctx, {"customer_id": B["customer"], "receipt_date": D, "method": "TRANSFER",
                                          "bank_account_id": B["banks"]["10290"]["id"], "amount": 57000, "wht_amount": 3000,
                                          "reference": "TRF-001", "allocations": [{"invoice_id": inv["id"], "amount": 60000}]})
    inv = sales.get_invoice(conn, ctx.entity_id, str(inv["id"]))
    assert inv["status"] == "PARTIALLY_PAID" and Decimal(str(inv["balance_due"])) == Decimal("40000.00")
    assert _bal(conn, ctx, a["78200"]) == Decimal("3000.00") and _bal(conn, ctx, a["10290"]) == Decimal("57000.00")
    # overpayment: 50,000 received, 40,000 applied, 10,000 left on account
    r2 = sales.create_receipt(conn, ctx, {"customer_id": B["customer"], "receipt_date": D, "method": "CASH",
                                          "bank_account_id": B["banks"]["10100"]["id"], "amount": 50000,
                                          "allocations": [{"invoice_id": inv["id"], "amount": 40000}]})
    assert Decimal(str(r2["unapplied"])) == Decimal("10000.00")
    assert sales.get_invoice(conn, ctx.entity_id, str(inv["id"]))["status"] == "PAID"
    assert sales.customer_exposure(conn, ctx.entity_id, B["customer"]) == Decimal("-10000.00")
    with pytest.raises(FinError) as e:  # duplicate cheque/transfer reference (meeting 2)
        sales.create_receipt(conn, ctx, {"customer_id": B["customer"], "receipt_date": D, "method": "TRANSFER",
                                         "bank_account_id": B["banks"]["10290"]["id"], "amount": 1, "reference": "trf-001"})
    assert e.value.code == "DUPLICATE_REFERENCE"
    _reconciled(conn, ctx)


def test_credit_limit_is_a_backend_control(conn, books):
    B = books
    ctx = B["ctx"]
    _buy(conn, B, qty=300)
    inv = sales.create_invoice(conn, ctx, {"customer_id": B["customer"], "invoice_date": D,
                                           "lines": [{"sku": "ROTARIX", "quantity": 250, "unit_price": 5600}]})  # 1.4m > 1m
    with pytest.raises(FinError) as e:
        sales.post_invoice(conn, ctx, str(inv["id"]))
    assert e.value.code == "CREDIT_LIMIT_EXCEEDED" and e.value.details["excess"] == "400000.00"
    posted = sales.post_invoice(conn, ctx, str(inv["id"]), override_credit=True, override_reason="MD approved")
    assert posted["credit_override_reason"] == "MD approved"
    assert q1(conn, "SELECT 1 FROM fin_validation_events WHERE entity_id=%s AND check_code='CREDIT_LIMIT_EXCEEDED'", (str(inv["id"]),))


def test_insufficient_stock_and_recalled_batch_block_sale(conn, books):
    B = books
    ctx = B["ctx"]
    _buy(conn, B, qty=5)
    inv = sales.create_invoice(conn, ctx, {"customer_id": B["customer"], "invoice_date": D,
                                           "lines": [{"sku": "ROTARIX", "quantity": 6, "unit_price": 100}]})
    with pytest.raises(FinError) as e:
        sales.post_invoice(conn, ctx, str(inv["id"]))
    assert e.value.code == "INSUFFICIENT_STOCK"


def test_return_inward_credit_note_restores_stock_at_original_cost(conn, books):
    B = books
    ctx, a = B["ctx"], B["a"]
    _buy(conn, B)
    inv = sales.post_invoice(conn, ctx, str(sales.create_invoice(conn, ctx, {"customer_id": B["customer"], "invoice_date": D,
                             "lines": [{"sku": "ROTARIX", "quantity": 10, "unit_price": 5600}]})["id"]))
    cn = sales.create_credit_note(conn, ctx, {"customer_id": B["customer"], "invoice_id": inv["id"], "note_date": D,
                                              "reason": "Wrong product ordered", "return_to_stock": True,
                                              "lines": [{"sku": "ROTARIX", "quantity": 4, "unit_price": 5600}]})
    assert Decimal(str(cn["total"])) == Decimal("22400.00")
    assert inventory.on_hand(conn, ctx.entity_id, "ROTARIX")["quantity"] == 94
    assert _bal(conn, ctx, a["48000"]) == Decimal("22400.00")                 # sales returns
    assert _bal(conn, ctx, a["50000"]) == Decimal("27870.00")                 # 6 x 4,645 left in COGS
    assert Decimal(str(sales.get_invoice(conn, ctx.entity_id, str(inv["id"]))["balance_due"])) == Decimal("33600.00")
    _reconciled(conn, ctx)


def test_void_invoice_reverses_everything(conn, books):
    B = books
    ctx, a = B["ctx"], B["a"]
    _buy(conn, B)
    inv = sales.post_invoice(conn, ctx, str(sales.create_invoice(conn, ctx, {"customer_id": B["customer"], "invoice_date": D,
                             "lines": [{"sku": "ROTARIX", "quantity": 10, "unit_price": 5600}]})["id"]))
    sales.void_invoice(conn, ctx, str(inv["id"]), "Raised in error")
    assert _bal(conn, ctx, a["11000"]) == 0 and _bal(conn, ctx, a["40000"]) == 0 and _bal(conn, ctx, a["50000"]) == 0
    assert inventory.on_hand(conn, ctx.entity_id, "ROTARIX")["quantity"] == 100
    _reconciled(conn, ctx)


def test_supplier_payment_with_wht_duplicate_bill_and_return_outward(conn, books):
    B = books
    ctx, a = B["ctx"], B["a"]
    bill = _buy(conn, B, inv_no="INV-777")
    with pytest.raises(FinError) as e:
        _buy(conn, B, inv_no="inv 777".replace(" ", "-").upper())
    assert e.value.code == "DUPLICATE_INVOICE"
    pay = purchases.create_payment(conn, ctx, {"supplier_id": B["supplier"], "payment_date": D, "method": "TRANSFER",
                                               "bank_account_id": B["banks"]["10290"]["id"], "amount": 441275,
                                               "wht_amount": 23225, "reference": "CHQ-9",
                                               "allocations": [{"bill_id": bill["id"], "amount": 464500}]})
    assert purchases.get_bill(conn, ctx.entity_id, str(bill["id"]))["status"] == "PAID"
    assert _bal(conn, ctx, a["23700"]) == Decimal("-23225.00") and _bal(conn, ctx, a["20000"]) == 0
    # return 10 units to the supplier: stock and AP both go down at received cost
    bill2 = _buy(conn, B, qty=20, batch="N")
    purchases.create_debit_note(conn, ctx, {"supplier_id": B["supplier"], "bill_id": bill2["id"], "note_date": D,
                                            "reason": "Short expiry", "lines": [{"sku": "ROTARIX", "quantity": 10, "batch_number": "N"}]})
    assert inventory.on_hand(conn, ctx.entity_id, "ROTARIX")["quantity"] == 110
    assert Decimal(str(purchases.get_bill(conn, ctx.entity_id, str(bill2["id"]))["balance_due"])) == Decimal("46450.00")
    _reconciled(conn, ctx)


def test_damage_expiry_and_count_adjustments(conn, books, ctx_for):
    B = books
    ctx, a = B["ctx"], B["a"]
    _buy(conn, B)
    adj = inventory.create_adjustment(conn, ctx, {"adjustment_date": D, "reason_code": "EXPIRY",
                                                  "lines": [{"sku": "ROTARIX", "quantity": -3, "batch_number": "M"}]})
    with pytest.raises(FinError):  # maker-checker on stock write-offs
        inventory.post_adjustment(conn, ctx, str(adj["id"]))
    checker = ctx_for(ctx.entity_id, "storekeeper")
    inventory.post_adjustment(conn, checker, str(adj["id"]))
    assert _bal(conn, ctx, a["58500"]) == Decimal("13935.00")
    count = inventory.create_count(conn, ctx, D)
    line = count["lines"][0]
    inventory.record_count(conn, ctx, str(count["id"]), [{"id": line["id"], "counted_qty": 95, "reason": "Found 2 short"}])
    inventory.post_count(conn, checker, str(count["id"]))
    assert inventory.on_hand(conn, ctx.entity_id, "ROTARIX")["quantity"] == 95
    _reconciled(conn, ctx)


def test_stock_loan_is_not_a_sale_and_returns_in_another_batch(conn, books):
    B = books
    ctx, a = B["ctx"], B["a"]
    _buy(conn, B)                                  # batch M
    loan = inventory.create_loan(conn, ctx, {"customer_id": B["customer"], "sku": "ROTARIX", "quantity": 5,
                                             "batch_number": "M", "loan_date": D, "expected_return_date": D + dt.timedelta(days=14)})
    assert _bal(conn, ctx, a["40000"]) == 0 and _bal(conn, ctx, a["11000"]) == 0      # no revenue, no AR
    assert _bal(conn, ctx, a["12990"]) == Decimal("23225.00")
    loan = inventory.return_loan(conn, ctx, str(loan["id"]), {"quantity": 5, "batch_number": "Q", "return_date": D})
    assert loan["status"] == "RETURNED" and loan["returns"][0]["batch_number"] == "Q"
    q_batch = q1(conn, "SELECT id FROM fin_batches WHERE legal_entity_id=%s AND batch_number='Q'", (ctx.entity_id,))["id"]
    assert inventory.on_hand(conn, ctx.entity_id, "ROTARIX", str(q_batch))["quantity"] == 5
    assert _bal(conn, ctx, a["12990"]) == 0
    _reconciled(conn, ctx)


def test_recall_finds_who_bought_the_batch(conn, books):
    B = books
    ctx = B["ctx"]
    _buy(conn, B, batch="R1")
    sales.post_invoice(conn, ctx, str(sales.create_invoice(conn, ctx, {"customer_id": B["customer"], "invoice_date": D,
                       "lines": [{"sku": "ROTARIX", "quantity": 7, "unit_price": 5600, "batch_number": "R1"}]})["id"]))
    batch = q1(conn, "SELECT id FROM fin_batches WHERE legal_entity_id=%s AND batch_number='R1'", (ctx.entity_id,))["id"]
    rc = inventory.open_recall(conn, ctx, {"batch_id": batch, "reason": "NAFDAC alert"})
    assert len(rc["items"]) == 1 and rc["items"][0]["customer_id"] == B["customer"]
    assert Decimal(str(rc["items"][0]["quantity_sold"])) == 7
    inv = sales.create_invoice(conn, ctx, {"customer_id": B["customer"], "invoice_date": D,
                                           "lines": [{"sku": "ROTARIX", "quantity": 1, "unit_price": 5600, "batch_id": str(batch)}]})
    with pytest.raises(FinError) as e:
        sales.post_invoice(conn, ctx, str(inv["id"]))
    assert e.value.code == "INVALID_BATCH"


def test_cash_book_lodgement_and_bank_reconciliation(conn, books):
    B = books
    ctx, a = B["ctx"], B["a"]
    cash, bank = B["banks"]["10100"], B["banks"]["10290"]
    banking.create_voucher(conn, ctx, {"kind": "RECEIVE", "bank_account_id": cash["id"], "voucher_date": D,
                                       "lines": [{"account_id": a["40800"]["id"], "amount": 50000}], "description": "Scrap sale"})
    banking.create_voucher(conn, ctx, {"kind": "SPEND", "bank_account_id": cash["id"], "voucher_date": D, "payee": "Driver",
                                       "lines": [{"account_id": a["64000"]["id"], "amount": 4000, "description": "Transportation"}]})
    banking.create_voucher(conn, ctx, {"kind": "TRANSFER", "bank_account_id": cash["id"], "to_bank_account_id": bank["id"],
                                       "voucher_date": D, "amount": 40000, "description": "Lodgement"})
    assert _bal(conn, ctx, a["10100"]) == Decimal("6000.00") and _bal(conn, ctx, a["10290"]) == Decimal("40000.00")
    banking.create_voucher(conn, ctx, {"kind": "SPEND", "bank_account_id": bank["id"], "voucher_date": D, "reference": "CHQ-55",
                                       "lines": [{"account_id": a["64000"]["id"], "amount": 7000}]})
    st = banking.import_statement(conn, ctx, bank["id"], statement_date=D, closing_balance="40000", lines=[
        {"line_date": D, "description": "Cash deposit", "amount": Decimal("40000")}])
    assert [l["match_status"] for l in st["lines"]] == ["MATCHED"]
    rec = banking.complete_reconciliation(conn, ctx, str(st["id"]))   # CHQ-55 stays an uncleared item
    assert Decimal(str(rec["difference"])) == 0
    _reconciled(conn, ctx)


def test_fixed_asset_depreciation_and_disposal(conn, books):
    B = books
    ctx, a = B["ctx"], B["a"]
    cat = assets.create_category(conn, ctx, {"code": "MV", "name": "Motor vehicles", "asset_account_id": a["15150"]["id"],
                                             "accum_dep_account_id": a["17200"]["id"], "dep_expense_account_id": a["90300"]["id"]})
    banking.create_voucher(conn, ctx, {"kind": "RECEIVE", "bank_account_id": B["banks"]["10290"]["id"], "voucher_date": dt.date(2026, 1, 2),
                                       "lines": [{"account_id": a["40800"]["id"], "amount": 5_000_000}]})
    car = assets.register_asset(conn, ctx, {"category_id": cat["id"], "name": "Toyota Hilux", "cost": 4_800_000,
                                            "useful_life_months": 48, "acquisition_date": dt.date(2026, 1, 5), "funding": "BANK",
                                            "bank_account_id": B["banks"]["10290"]["id"]})
    for m in (1, 2):
        p = periods.period_for(conn, ctx.entity_id, dt.date(2026, m, 15))
        assets.run_depreciation(conn, ctx, str(p["id"]))
    assert _bal(conn, ctx, a["17200"]) == Decimal("-200000.00")   # 4.8m / 48 = 100k a month (client's straight-line)
    with pytest.raises(FinError):
        assets.run_depreciation(conn, ctx, str(periods.period_for(conn, ctx.entity_id, dt.date(2026, 2, 1))["id"]))
    assets.dispose_asset(conn, ctx, str(car["id"]), {"disposal_date": dt.date(2026, 3, 1), "proceeds": 4_700_000,
                                                     "bank_account_id": B["banks"]["10290"]["id"]})
    assert _bal(conn, ctx, a["15150"]) == 0 and _bal(conn, ctx, a["17200"]) == 0
    assert _bal(conn, ctx, a["90000"]) == Decimal("-100000.00")   # 4.7m proceeds - 4.6m NBV = 100k gain
    _reconciled(conn, ctx)


def test_statements_tie_out_and_year_end_close(conn, books):
    B = books
    ctx, a = B["ctx"], B["a"]
    _buy(conn, B)
    sales.post_invoice(conn, ctx, str(sales.create_invoice(conn, ctx, {"customer_id": B["customer"], "invoice_date": D,
                       "lines": [{"sku": "ROTARIX", "quantity": 10, "unit_price": 5600}]})["id"]))
    is_ = reports.income_statement(conn, ctx.entity_id, dt.date(2026, 1, 1), dt.date(2026, 12, 31))
    assert is_["revenue"] == Decimal("56000.00") and is_["gross_profit"] == Decimal("9550.00")
    fy = q1(conn, "SELECT id FROM fin_fiscal_years WHERE legal_entity_id=%s", (ctx.entity_id,))["id"]
    for p in q(conn, "SELECT id FROM fin_periods WHERE fiscal_year_id=%s AND period_number<12 ORDER BY start_date", (fy,)):
        periods.close_period(conn, ctx, str(p["id"]), force_warnings=True)
    res = closing.close_fiscal_year(conn, ctx, str(fy))
    assert res["net_profit"] == Decimal("9550.00")
    assert _bal(conn, ctx, a["40000"]) == 0 and _bal(conn, ctx, a["39005"]) == Decimal("-9550.00")
    assert q1(conn, "SELECT status FROM fin_fiscal_years WHERE id=%s", (fy,))["status"] == "CLOSED"
    bs = reports.balance_sheet(conn, ctx.entity_id, dt.date(2026, 12, 31))
    assert bs["balanced"]
    with pytest.raises(FinError) as e:     # posting into the closed year is refused
        posting.post_system(conn, ctx, event_type="T", journal_date=dt.date(2026, 12, 1), description="late",
                            lines=[{"account_id": a["10100"]["id"], "debit": 1}, {"account_id": a["40000"]["id"], "credit": 1}],
                            source_type="t", source_id="late")
    assert e.value.code == "PERIOD_CLOSED"
