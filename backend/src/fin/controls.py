"""Financial Control Engine — the 'Internal Accounting Review' the client asked for.

Every check is computed live from the ledger and subledgers (nothing is
trusted from a stored summary). Checks return PASS/FAIL with the numbers
that explain the result, so a finding can be traced rather than just shown.
Subledger checks register themselves as those modules are loaded.
"""
from __future__ import annotations

import datetime as dt
from typing import Any, Callable, Dict, List

from src.fin.db import ZERO, money, q, q1

# (code, title, blocking_for_close, fn(conn, entity_id, as_of) -> (ok, message, details))
_CHECKS: List[tuple] = []


def register(code: str, title: str, blocking: bool = True):
    def deco(fn: Callable):
        _CHECKS.append((code, title, blocking, fn))
        return fn
    return deco


def _result(code, title, blocking, ok, message, details=None) -> Dict[str, Any]:
    return {"code": code, "title": title, "blocking": blocking, "status": "PASS" if ok else "FAIL",
            "message": message, "details": details or {}}


def run_checks(conn, entity_id: str, as_of: dt.date) -> List[Dict[str, Any]]:
    out = []
    for code, title, blocking, fn in _CHECKS:
        try:
            ok, msg, details = fn(conn, entity_id, as_of)
        except Exception as exc:  # a broken check must be visible, not silently green
            ok, msg, details = False, f"Check could not run: {exc}", {}
        out.append(_result(code, title, blocking, ok, msg, details))
    return out


@register("LEDGER_BALANCED", "Total debits equal total credits")
def _ledger_balanced(conn, entity_id, as_of):
    r = q1(conn, """SELECT COALESCE(SUM(debit),0) d, COALESCE(SUM(credit),0) c FROM fin_v_general_ledger
                    WHERE legal_entity_id=%s AND journal_date <= %s""", (entity_id, as_of))
    d, c = money(r["d"]), money(r["c"])
    return d == c, ("Ledger is balanced" if d == c else f"Ledger is out by ₦{abs(d - c):,.2f}"), \
        {"total_debit": str(d), "total_credit": str(c)}


@register("JOURNALS_BALANCED", "Every posted journal balances")
def _journals_balanced(conn, entity_id, as_of):
    bad = q(conn, """SELECT journal_number, SUM(debit) d, SUM(credit) c FROM fin_v_general_ledger
                     WHERE legal_entity_id=%s AND journal_date <= %s GROUP BY journal_number
                     HAVING SUM(debit) <> SUM(credit) LIMIT 20""", (entity_id, as_of))
    return not bad, ("All posted journals balance" if not bad else f"{len(bad)} unbalanced journal(s)"), \
        {"journals": [b["journal_number"] for b in bad]}


def close_checklist(conn, ctx, period: Dict[str, Any]) -> List[Dict[str, Any]]:
    start, end = period["start_date"], period["end_date"]
    items: List[Dict[str, Any]] = []
    pending = q(conn, """SELECT journal_number, status FROM fin_journals WHERE legal_entity_id=%s
                         AND journal_date BETWEEN %s AND %s AND status IN ('DRAFT','SUBMITTED','APPROVED')""",
                (ctx.entity_id, start, end))
    items.append(_result("NO_UNPOSTED_JOURNALS", "No unposted journals in the period", True, not pending,
                         "All journals in the period are posted" if not pending
                         else f"{len(pending)} journal(s) still unposted",
                         {"journals": [p["journal_number"] for p in pending]}))
    for code, title, blocking, fn in _CHECKS:
        try:
            ok, msg, details = fn(conn, ctx.entity_id, end)
        except Exception as exc:
            ok, msg, details = False, f"Check could not run: {exc}", {}
        items.append(_result(code, title, blocking, ok, msg, details))
    return items


# ---------------------------------------------------------------------------
# Subledger <-> GL reconciliations (the client's internal accounting review:
# "accounts receivable out of balance with the aged receivable report")
# ---------------------------------------------------------------------------

def _control_balance(conn, entity_id, key, as_of):
    from src.fin.accounts import optional_mapped
    acct = optional_mapped(conn, entity_id, key)
    if not acct:
        return None, None
    r = q1(conn, """SELECT COALESCE(SUM(debit-credit),0) b FROM fin_v_general_ledger
                    WHERE account_id=%s AND journal_date <= %s""", (acct["id"], as_of))
    return acct, money(r["b"])


@register("AR_RECONCILES", "AR control account = customer balances")
def _ar(conn, entity_id, as_of):
    from src.fin.reports import subledger_balances
    acct, gl = _control_balance(conn, entity_id, "AR_CONTROL", as_of)
    if acct is None:
        used = q1(conn, "SELECT 1 FROM fin_sales_invoices WHERE legal_entity_id=%s LIMIT 1", (entity_id,))
        return not used, ("No receivables yet" if not used else "AR control account is not mapped"), {}
    sub = subledger_balances(conn, entity_id, as_of)["ar"]
    diff = gl - sub
    return diff == 0, ("AR agrees with customer balances" if diff == 0 else
                       f"AR control {acct['code']} is ₦{gl:,.2f} but customer balances total ₦{sub:,.2f} (difference ₦{diff:,.2f})"), \
        {"gl": str(gl), "subledger": str(sub), "difference": str(diff), "account": acct["code"]}


@register("AP_RECONCILES", "AP control account = supplier balances")
def _ap(conn, entity_id, as_of):
    from src.fin.reports import subledger_balances
    acct, gl = _control_balance(conn, entity_id, "AP_CONTROL", as_of)
    if acct is None:
        used = q1(conn, "SELECT 1 FROM fin_supplier_bills WHERE legal_entity_id=%s LIMIT 1", (entity_id,))
        return not used, ("No payables yet" if not used else "AP control account is not mapped"), {}
    sub = subledger_balances(conn, entity_id, as_of)["ap"]
    diff = -gl - sub
    return diff == 0, ("AP agrees with supplier balances" if diff == 0 else
                       f"AP control {acct['code']} is ₦{-gl:,.2f} but supplier balances total ₦{sub:,.2f} (difference ₦{diff:,.2f})"), \
        {"gl": str(-gl), "subledger": str(sub), "difference": str(diff), "account": acct["code"]}


@register("INVENTORY_RECONCILES", "Inventory GL = stock valuation")
def _inventory(conn, entity_id, as_of):
    gl = money(q1(conn, """SELECT COALESCE(SUM(debit-credit),0) b FROM fin_v_general_ledger
                           WHERE legal_entity_id=%s AND subtype='INVENTORY' AND journal_date <= %s""", (entity_id, as_of))["b"])
    val = money(q1(conn, """SELECT COALESCE(SUM(total_cost),0) v FROM fin_inventory_transactions WHERE legal_entity_id=%s
                            AND txn_date <= %s AND txn_type NOT IN ('LOAN_OUT','LOAN_RETURN')""", (entity_id, as_of))["v"])
    diff = gl - val
    return diff == 0, ("Inventory GL agrees with the stock valuation" if diff == 0 else
                       f"Inventory accounts total ₦{gl:,.2f} but valued stock is ₦{val:,.2f} (difference ₦{diff:,.2f})"), \
        {"gl": str(gl), "valuation": str(val), "difference": str(diff)}


@register("STOCK_ON_LOAN_RECONCILES", "Stock-on-loan account = open loans", blocking=False)
def _loans(conn, entity_id, as_of):
    from src.fin.accounts import optional_mapped
    acct = optional_mapped(conn, entity_id, "STOCK_ON_LOAN")
    if not acct:
        return True, "No stock-on-loan account mapped", {}
    gl = money(q1(conn, "SELECT COALESCE(SUM(debit-credit),0) b FROM fin_v_general_ledger WHERE account_id=%s AND journal_date<=%s",
                  (acct["id"], as_of))["b"])
    val = money(q1(conn, """SELECT COALESCE(SUM((quantity-quantity_returned)*unit_cost),0) v FROM fin_stock_loans
                            WHERE legal_entity_id=%s AND status IN ('OPEN','PARTIALLY_RETURNED')""", (entity_id,))["v"])
    return gl == val, f"Stock on loan ₦{gl:,.2f} vs open loans ₦{val:,.2f}", {"gl": str(gl), "loans": str(val)}


@register("FRONTDESK_POSTED", "Every approved Frontdesk sale reached the books")
def _frontdesk(conn, entity_id, as_of):
    failed = q(conn, """SELECT source_ref, message FROM fin_source_postings WHERE legal_entity_id=%s AND status='FAILED'
                        ORDER BY updated_at DESC LIMIT 20""", (entity_id,))
    # Approved on/after cut-over but never attempted (e.g. approved before the hook existed,
    # or while auto-posting was paused). Excluded invoices carry a SKIPPED record and are not listed.
    from src.fin.integrations import unposted_frontdesk
    missing = [m for m in unposted_frontdesk(conn, entity_id) if m["invoice_date"] <= as_of]
    ok = not failed and not missing
    parts = []
    if failed:
        parts.append(f"{len(failed)} failed to post")
    if missing:
        parts.append(f"{len(missing)} approved since go-live not yet posted (run Backfill)")
    return ok, ("All approved Frontdesk invoices are posted" if ok else "Frontdesk invoices: " + "; ".join(parts)), \
        {"failed": failed, "not_posted": [m["invoice_number"] for m in missing]}


@register("DUPLICATE_REFERENCES", "No cheque / transfer reference used twice", blocking=False)
def _dups(conn, entity_id, as_of):
    rows = q(conn, """SELECT 'receipt' AS kind, lower(reference) ref, COUNT(*) n, array_agg(receipt_number) docs
                      FROM fin_customer_receipts WHERE legal_entity_id=%s AND status='POSTED' AND reference IS NOT NULL
                      AND method IN ('CHEQUE','TRANSFER') GROUP BY lower(reference) HAVING COUNT(*) > 1
                      UNION ALL
                      SELECT 'payment', lower(reference), COUNT(*), array_agg(payment_number) FROM fin_supplier_payments
                      WHERE legal_entity_id=%s AND status='POSTED' AND reference IS NOT NULL GROUP BY lower(reference)
                      HAVING COUNT(*) > 1""", (entity_id, entity_id))
    return not rows, ("No duplicated references" if not rows else f"{len(rows)} reference(s) used more than once"), {"duplicates": rows}


@register("SUSPENSE_CLEAR", "Suspense accounts are cleared", blocking=False)
def _suspense(conn, entity_id, as_of):
    rows = q(conn, """SELECT a.code, a.name, SUM(g.debit-g.credit) b FROM fin_v_general_ledger g JOIN fin_accounts a ON a.id=g.account_id
                      WHERE g.legal_entity_id=%s AND g.journal_date<=%s AND (a.name ILIKE '%%suspense%%')
                      GROUP BY a.code, a.name HAVING SUM(g.debit-g.credit) <> 0""", (entity_id, as_of))
    return not rows, ("Suspense accounts are clear" if not rows else f"{len(rows)} suspense account(s) carry a balance"), \
        {"accounts": [{"code": r["code"], "name": r["name"], "balance": str(money(r["b"]))} for r in rows]}


@register("OVERDUE_STOCK_LOANS", "Stock loans returned on time", blocking=False)
def _overdue_loans(conn, entity_id, as_of):
    rows = q(conn, """SELECT l.loan_number, c.name, l.sku, l.quantity - l.quantity_returned AS outstanding, l.expected_return_date
                      FROM fin_stock_loans l LEFT JOIN customers c ON c.id=l.customer_id WHERE l.legal_entity_id=%s
                      AND l.status IN ('OPEN','PARTIALLY_RETURNED') AND l.expected_return_date < %s""", (entity_id, as_of))
    return not rows, ("No overdue stock loans" if not rows else f"{len(rows)} stock loan(s) overdue"), {"loans": rows}


@register("EXPIRED_STOCK", "No expired batches still counted as stock", blocking=False)
def _expired(conn, entity_id, as_of):
    rows = q(conn, """SELECT b.sku, b.batch_number, b.expiry_date, SUM(l.qty_remaining) q, SUM(l.qty_remaining*l.unit_cost) v
                      FROM fin_batches b JOIN fin_cost_layers l ON l.batch_id=b.id WHERE b.legal_entity_id=%s
                      AND b.expiry_date < %s GROUP BY b.sku, b.batch_number, b.expiry_date HAVING SUM(l.qty_remaining) > 0
                      ORDER BY b.expiry_date LIMIT 50""", (entity_id, as_of))
    total = sum((money(r["v"]) for r in rows), ZERO)
    return not rows, ("No expired stock on hand" if not rows else
                      f"{len(rows)} expired batch(es) worth ₦{total:,.2f} still in stock - write them off"), {"batches": rows}


@register("BANK_RECONCILED", "No bank entries left unreconciled for 45+ days", blocking=False)
def _bank(conn, entity_id, as_of):
    # Only accounts with book entries not yet matched to a statement for 45+ days.
    stale = q(conn, """SELECT b.name, MIN(g.journal_date) AS oldest_uncleared, COUNT(*) AS items
                       FROM fin_bank_accounts b JOIN fin_v_general_ledger g ON g.account_id=b.gl_account_id
                       WHERE b.legal_entity_id=%s AND b.kind='BANK' AND b.status='ACTIVE' AND g.journal_date <= %s
                         AND NOT EXISTS (SELECT 1 FROM fin_cleared_lines c WHERE c.journal_line_id=g.line_id)
                       GROUP BY b.name HAVING MIN(g.journal_date) < %s::date - 45""", (entity_id, as_of, as_of))
    return not stale, ("Bank accounts are reconciled" if not stale
                       else f"{len(stale)} bank account(s) have entries unreconciled for over 45 days"), {"accounts": stale}


@register("ASSET_REGISTER_RECONCILES", "Fixed-asset register = fixed-asset accounts (cost)", blocking=False)
def _assets(conn, entity_id, as_of):
    gl = money(q1(conn, """SELECT COALESCE(SUM(debit-credit),0) b FROM fin_v_general_ledger WHERE legal_entity_id=%s
                           AND subtype='FIXED_ASSET' AND journal_date<=%s""", (entity_id, as_of))["b"])
    reg = money(q1(conn, """SELECT COALESCE(SUM(cost),0) c FROM fin_fixed_assets WHERE legal_entity_id=%s AND acquisition_date<=%s
                            AND (status<>'DISPOSED' OR disposal_date > %s)""", (entity_id, as_of, as_of))["c"])
    return gl == reg, (f"Asset register ₦{reg:,.2f} agrees with the fixed-asset accounts" if gl == reg else
                       f"Asset register ₦{reg:,.2f} vs fixed-asset accounts ₦{gl:,.2f}: assets still to be listed"), \
        {"gl": str(gl), "register": str(reg), "difference": str(gl - reg)}


def run_and_store(conn, ctx, as_of) -> Dict[str, Any]:
    from src.fin.db import jsonb
    results = run_checks(conn, ctx.entity_id, as_of)
    fails = sum(1 for r in results if r["status"] == "FAIL")
    row = q1(conn, """INSERT INTO fin_control_runs (legal_entity_id, as_of, results, fail_count, run_by)
                      VALUES (%s,%s,%s,%s,%s) RETURNING id, run_at""", (ctx.entity_id, as_of, jsonb(results), fails, ctx.actor_id))
    return {"id": row["id"], "run_at": row["run_at"], "as_of": as_of, "results": results, "fail_count": fails}
