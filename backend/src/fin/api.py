"""ACE Books HTTP API  (prefix /fin).

Thin layer: authenticate -> resolve company context -> call one domain
service inside one transaction -> JSON. Business errors are returned as
HTTP errors whose `detail` is {code, message, details} (Financial API spec
§60). No endpoint mutates financial tables directly; there is deliberately
no generic "post a journal line" or "edit a posted document" endpoint.
"""
from __future__ import annotations

import datetime as dt
from typing import Any, Callable, Dict, List, Optional

import psycopg2
from fastapi import APIRouter, Body, File, Form, HTTPException, Query, Request, UploadFile

from src.fin import (accounts, assets, audit, banking, books_ledger, closing, controls, dashboard, data_exceptions, integrations, inventory,
                     ledger, ledger_reports, migration, numbering, periods, posting, purchases, report_center, reports, rules,
                     sage_history, sage_ledger, sales, setup)
from src.fin.context import build_context
from src.fin.db import plain, q, q1, tx
from src.fin.errors import FinError, from_db_error, invalid
from src.utils.shared_response import shared_response

router = APIRouter(prefix="/fin", tags=["ACE Books"])

DATE_KEYS = {"journal_date", "invoice_date", "due_date", "receipt_date", "note_date", "bill_date", "payment_date",
             "voucher_date", "adjustment_date", "count_date", "loan_date", "expected_return_date", "return_date",
             "acquisition_date", "depreciation_start", "disposal_date", "statement_date", "start_date", "cutover_date",
             "expiry_date", "manufacture_date", "reversal_date", "as_of", "on", "amend_date"}


def _date(v: Any) -> Any:
    if v in (None, "") or isinstance(v, dt.date):
        return v or None
    try:
        return dt.date.fromisoformat(str(v)[:10])
    except ValueError:
        raise FinError("VALIDATION_FAILED", f"Not a valid date: {v!r} (use YYYY-MM-DD)")


def _dates(d: Any) -> Any:
    if isinstance(d, dict):
        return {k: (_date(v) if k in DATE_KEYS else _dates(v)) for k, v in d.items()}
    if isinstance(d, list):
        return [_dates(x) for x in d]
    return d


def _run(request: Request, fn: Callable, perm: Optional[str] = None, cache_ttl: int = 0) -> Any:
    """cache_ttl > 0: read-only reports shared across workers and users (src/utils/shared_response.py).
    The caller's permission is still checked first; the key is the entity plus the full query, and
    any save anywhere drops it."""
    try:
        with tx() as conn:
            ctx = build_context(request, conn)
            if perm:
                ctx.require(perm)
            if cache_ttl:
                params = "&".join(f"{k}={v}" for k, v in sorted(request.query_params.multi_items()))
                key = f"fin:resp:{ctx.entity_id}:{request.url.path}?{params}"
                return shared_response(key, cache_ttl, lambda: plain(fn(conn, ctx)))
            return plain(fn(conn, ctx))
    except FinError as e:
        raise HTTPException(status_code=e.status, detail=e.to_detail())
    except psycopg2.Error as e:
        err = from_db_error(e)
        if err:
            raise HTTPException(status_code=err.status, detail=err.to_detail())
        if isinstance(e, psycopg2.DataError):
            # a malformed id, date or number in the request: the caller's mistake, not a server fault
            raise HTTPException(status_code=400, detail={"code": "VALIDATION_FAILED",
                                                         "message": "A value in the request is not valid (check the ids and dates)"})
        raise


def _today() -> dt.date:
    return dt.date.today()


def _range(date_from: Optional[str], date_to: Optional[str]) -> tuple:
    t = _date(date_to) or _today()
    f = _date(date_from) or t.replace(day=1)
    if f > t:
        raise FinError("VALIDATION_FAILED", "'from' is after 'to'")
    return f, t


# ---------------------------------------------------------------------------
# Context & setup
# ---------------------------------------------------------------------------

@router.get("/context")
def get_context(request: Request):
    def fn(conn, ctx):
        ent = q1(conn, """SELECT e.id, e.code, e.name, e.base_currency, e.fiscal_year_start_month, o.name AS organization
                          FROM fin_legal_entities e JOIN fin_organizations o ON o.id=e.organization_id WHERE e.id=%s""", (ctx.entity_id,))
        return {"entity": ent, "entities": q(conn, "SELECT id, code, name FROM fin_legal_entities WHERE status='ACTIVE' ORDER BY name"),
                "user": {"id": ctx.actor_id, "name": ctx.actor_name, "roles": ctx.roles},
                "permissions": sorted(ctx.permissions), "period": periods.current_period(conn, ctx.entity_id),
                "settings": setup.get_settings(conn, ctx.entity_id),
                "setup": {"accounts": q1(conn, "SELECT COUNT(*) n FROM fin_accounts WHERE legal_entity_id=%s", (ctx.entity_id,))["n"],
                          "fiscal_years": q1(conn, "SELECT COUNT(*) n FROM fin_fiscal_years WHERE legal_entity_id=%s", (ctx.entity_id,))["n"],
                          "opening_posted": bool(q1(conn, "SELECT 1 FROM fin_journals WHERE legal_entity_id=%s AND journal_type='OPENING' AND status='POSTED'", (ctx.entity_id,))),
                          "products": q1(conn, "SELECT COUNT(*) n FROM fin_products WHERE legal_entity_id=%s", (ctx.entity_id,))["n"]}}
    return _run(request, fn)


@router.get("/settings")
def get_settings(request: Request):
    return _run(request, lambda c, x: setup.get_settings(c, x.entity_id), "accounting.view")


@router.put("/settings")
def put_settings(request: Request, payload: Dict[str, Any] = Body(...)):
    return _run(request, lambda c, x: setup.update_settings(c, x, _dates(payload)))


@router.get("/mappings")
def get_mappings(request: Request):
    def fn(conn, ctx):
        have = {m["mapping_key"]: m for m in setup.list_mappings(conn, ctx.entity_id)}
        return [{"mapping_key": k, "description": d, **({k2: v for k2, v in have[k].items() if k2 != "mapping_key"} if k in have else {})}
                for k, d in rules.MAPPING_KEYS.items()]
    return _run(request, fn, "accounting.view")


@router.put("/mappings/{key}")
def put_mapping(key: str, request: Request, payload: Dict[str, Any] = Body(...)):
    if key not in rules.MAPPING_KEYS:
        raise HTTPException(404, detail={"code": "RESOURCE_NOT_FOUND", "message": f"Unknown posting rule {key}"})
    return _run(request, lambda c, x: setup.set_mapping(c, x, key, payload["account_id"], payload.get("note")))


@router.get("/dashboard")
def get_dashboard(request: Request, as_of: Optional[str] = None):
    return _run(request, lambda c, x: dashboard.control_tower(c, x.entity_id, _date(as_of) or _today()), "reports.view",
                cache_ttl=60)


# ---------------------------------------------------------------------------
# Periods
# ---------------------------------------------------------------------------

@router.get("/periods")
def list_periods(request: Request):
    return _run(request, lambda c, x: periods.list_years(c, x.entity_id), "accounting.view")


@router.post("/fiscal-years")
def create_year(request: Request, payload: Dict[str, Any] = Body(...)):
    def fn(conn, ctx):
        ctx.require("finance.period.close")
        return periods.create_fiscal_year(conn, ctx, _date(payload["start_date"]))
    return _run(request, fn)


@router.post("/fiscal-years/{fy_id}/close")
def close_year(fy_id: str, request: Request):
    return _run(request, lambda c, x: closing.close_fiscal_year(c, x, fy_id))


@router.get("/periods/{period_id}/checklist")
def period_checklist(period_id: str, request: Request):
    def fn(conn, ctx):
        p = q1(conn, "SELECT * FROM fin_periods WHERE id=%s AND legal_entity_id=%s", (period_id, ctx.entity_id))
        if not p:
            raise FinError("RESOURCE_NOT_FOUND", "Period not found")
        return {"period": p, "checklist": controls.close_checklist(conn, ctx, p)}
    return _run(request, fn, "accounting.view")


@router.post("/periods/{period_id}/close")
def close_period(period_id: str, request: Request, payload: Dict[str, Any] = Body(default={})):
    return _run(request, lambda c, x: periods.close_period(c, x, period_id, force_warnings=bool(payload.get("accept_warnings"))))


@router.post("/periods/{period_id}/reopen")
def reopen_period(period_id: str, request: Request, payload: Dict[str, Any] = Body(...)):
    return _run(request, lambda c, x: periods.reopen_period(c, x, period_id, payload.get("reason", "")))


# ---------------------------------------------------------------------------
# Chart of accounts
# ---------------------------------------------------------------------------

@router.get("/accounts")
def list_accounts(request: Request, search: Optional[str] = None, account_type: Optional[str] = None,
                  include_inactive: bool = True, as_of: Optional[str] = None, history: bool = False):
    """The chart of accounts. With history=true every account also carries its balance at `as_of`
    from the whole ledger (Sage's years and ACE Books) and how many entries it has had, when the
    first and last were - so the chart shows every account's real activity, not only ACE's own."""
    def fn(conn, ctx):
        rows = accounts.list_accounts(conn, ctx.entity_id, search=search, account_type=account_type,
                                      include_inactive=include_inactive)
        if not history:
            return rows
        on = _date(as_of) or _today()
        bal = books_ledger.balances(conn, ctx.entity_id, on)
        # income and expense show their year to date (Sage closes them each year)
        ytd = books_ledger.ytd_pl(conn, ctx.entity_id, on)
        act = {r["account_code"]: r for r in q(conn, """
            SELECT account_code, COUNT(*) AS n, MIN(txn_date) AS first, MAX(txn_date) AS last FROM fin_sage_gl_lines
            WHERE legal_entity_id=%s AND (debit <> 0 OR credit <> 0) AND txn_date <= %s GROUP BY account_code""", (ctx.entity_id, on))}
        for r in rows:
            pl = r["account_type"] in ("REVENUE", "EXPENSE")
            r["balance_as_of"] = ytd.get(r["code"], 0) if pl else bal.get(r["code"], 0)
            r["balance_basis"] = "year to date" if pl else "balance"
            s = act.get(r["code"]) or {}
            r["entries"] = int(s.get("n") or 0) + int(r.get("posting_count") or 0)
            r["first_entry"] = s.get("first")
            r["last_entry"] = s.get("last")
        return rows
    return _run(request, fn, "accounting.view")


@router.post("/accounts")
def create_account(request: Request, payload: Dict[str, Any] = Body(...)):
    return _run(request, lambda c, x: accounts.create_account(c, x, payload))


@router.get("/accounts/{account_id}")
def get_account(account_id: str, request: Request):
    return _run(request, lambda c, x: accounts.get_account(c, x.entity_id, account_id), "accounting.view")


@router.patch("/accounts/{account_id}")
def patch_account(account_id: str, request: Request, payload: Dict[str, Any] = Body(...)):
    return _run(request, lambda c, x: accounts.update_account(c, x, account_id, payload))


@router.post("/accounts/{account_id}/deactivate")
def deactivate_account(account_id: str, request: Request, payload: Dict[str, Any] = Body(default={})):
    return _run(request, lambda c, x: accounts.set_status(c, x, account_id, False, payload.get("reason")))


@router.post("/accounts/{account_id}/activate")
def activate_account(account_id: str, request: Request):
    return _run(request, lambda c, x: accounts.set_status(c, x, account_id, True))


@router.get("/accounts/{account_id}/activity")
def account_activity(account_id: str, request: Request, date_from: Optional[str] = Query(None, alias="from"),
                     date_to: Optional[str] = Query(None, alias="to"), limit: int = 500, offset: int = 0,
                     customer_id: Optional[int] = None, supplier_id: Optional[str] = None, product_sku: Optional[str] = None):
    def fn(conn, ctx):
        f, t = _range(date_from, date_to)
        return ledger.account_activity(conn, ctx.entity_id, account_id, f, t, limit=limit, offset=offset,
                                       customer_id=customer_id, supplier_id=supplier_id, product_sku=product_sku)
    return _run(request, fn, "accounting.view")


# ---------------------------------------------------------------------------
# Journals, GL, TB
# ---------------------------------------------------------------------------

@router.get("/journals")
def list_journals(request: Request, status: Optional[str] = None, search: Optional[str] = None,
                  date_from: Optional[str] = Query(None, alias="from"), date_to: Optional[str] = Query(None, alias="to"),
                  journal_type: Optional[str] = None, source_type: Optional[str] = None, limit: int = 100, offset: int = 0):
    return _run(request, lambda c, x: posting.list_journals(c, x.entity_id, status=status, search=search,
                                                             date_from=_date(date_from), date_to=_date(date_to),
                                                             journal_type=journal_type, source_type=source_type,
                                                             limit=limit, offset=offset), "accounting.view")


@router.post("/journals")
def create_journal(request: Request, payload: Dict[str, Any] = Body(...)):
    p = payload
    return _run(request, lambda c, x: posting.create_manual(c, x, journal_date=_date(p["journal_date"]),
                                                             description=p.get("description", ""), lines=p.get("lines") or [],
                                                             journal_type=p.get("journal_type", "MANUAL"),
                                                             idempotency_key=request.headers.get("Idempotency-Key")))


@router.get("/journals/{journal_id}")
def get_journal(journal_id: str, request: Request):
    def fn(conn, ctx):
        j = posting.get_journal(conn, ctx.entity_id, journal_id)
        j["audit"] = q(conn, """SELECT action, actor_name, reason, created_at, metadata FROM fin_audit_events
                                WHERE entity_type='journal' AND entity_id=%s ORDER BY id""", (journal_id,))
        return j
    return _run(request, fn, "accounting.view")


@router.put("/journals/{journal_id}")
def update_journal(journal_id: str, request: Request, payload: Dict[str, Any] = Body(...)):
    return _run(request, lambda c, x: posting.update_manual(c, x, journal_id, journal_date=_date(payload["journal_date"]),
                                                             description=payload.get("description", ""), lines=payload.get("lines") or []))


@router.delete("/journals/{journal_id}")
def delete_journal(journal_id: str, request: Request):
    return _run(request, lambda c, x: posting.delete_draft(c, x, journal_id) or {"deleted": journal_id})


@router.post("/journals/{journal_id}/{action}")
def journal_action(journal_id: str, action: str, request: Request, payload: Dict[str, Any] = Body(default={})):
    acts = {
        "validate": lambda c, x: posting.validate_journal(c, x, journal_id),
        "submit": lambda c, x: posting.submit(c, x, journal_id),
        "approve": lambda c, x: posting.approve(c, x, journal_id, payload.get("comment")),
        "reject": lambda c, x: posting.reject(c, x, journal_id, payload.get("reason", "")),
        "post": lambda c, x: posting.post_manual(c, x, journal_id),
        "reverse": lambda c, x: posting.reverse(c, x, journal_id, reversal_date=_date(payload.get("reversal_date")),
                                                reason=payload.get("reason", "")),
    }
    if action not in acts:
        raise HTTPException(404, detail={"code": "RESOURCE_NOT_FOUND", "message": f"Unknown action {action}"})
    return _run(request, acts[action])


@router.get("/trial-balance")
def trial_balance(request: Request, date_from: Optional[str] = Query(None, alias="from"),
                  date_to: Optional[str] = Query(None, alias="to"), include_zero: bool = False):
    """Opening, period debits/credits and closing per account - any range, back to the first Sage year."""
    def fn(conn, ctx):
        t = _date(date_to) or _today()
        f = _date(date_from) or reports._fy_start(conn, ctx.entity_id, t)
        s = books_ledger.gl_summary(conn, ctx.entity_id, f, t, include_zero=include_zero)
        rows, tot = [], {k: 0 for k in ("opening_debit", "opening_credit", "period_debit", "period_credit", "closing_debit", "closing_credit")}
        from decimal import Decimal as _D
        z = _D("0")
        for r in s["rows"]:
            o, c = r["opening"], r["closing"]
            row = {**r, "period_debit": r["debit"], "period_credit": r["credit"], "opening_debit": max(o, z),
                   "opening_credit": max(-o, z), "closing_debit": max(c, z), "closing_credit": max(-c, z)}
            for k in tot:
                tot[k] += row[k]
            rows.append(row)
        return {"date_from": f, "date_to": t, "history_until": s["history_until"], "rows": rows, "totals": tot,
                "balanced": tot["closing_debit"] == tot["closing_credit"], "difference": tot["closing_debit"] - tot["closing_credit"]}
    return _run(request, fn, "reports.view", cache_ttl=60)


@router.get("/general-ledger")
def general_ledger(request: Request, date_from: Optional[str] = Query(None, alias="from"),
                   date_to: Optional[str] = Query(None, alias="to"), account_ids: Optional[str] = None):
    def fn(conn, ctx):
        f, t = _range(date_from, date_to)
        ids = set(account_ids.split(",")) if account_ids else None
        out = []
        for r in books_ledger.gl_summary(conn, ctx.entity_id, f, t)["rows"]:
            if ids and str(r["account_id"]) not in ids:
                continue
            a = books_ledger.gl_account(conn, ctx.entity_id, r["code"], f, t)
            out.append({"account_id": r["account_id"], "code": r["code"], "name": r["name"], "opening": a["opening"],
                        "closing": a["closing"], "rows": [l for m in a["months"] for l in m["lines"]]})
        return out
    return _run(request, fn, "reports.view")


# ---------------------------------------------------------------------------
# The one ledger in Sage's layouts (Sage history up to the hand-over, ACE Books after it)
# ---------------------------------------------------------------------------

@router.get("/ledger/range")
def ledger_range(request: Request):
    def fn(conn, ctx):
        s = q1(conn, "SELECT cutover_date FROM fin_settings WHERE legal_entity_id=%s", (ctx.entity_id,))
        return {"history_start": books_ledger.history_start(conn, ctx.entity_id),
                "history_until": books_ledger.history_until(conn, ctx.entity_id),
                "cutover_date": s["cutover_date"] if s else None,
                "loaded": sage_ledger.coverage(conn, ctx.entity_id)}
    return _run(request, fn, "reports.view")


@router.get("/ledger/gl-summary")
def ledger_gl_summary(request: Request, date_from: Optional[str] = Query(None, alias="from"),
                      date_to: Optional[str] = Query(None, alias="to"), include_zero: bool = False, codes: Optional[str] = None):
    def fn(conn, ctx):
        f, t = _range(date_from, date_to)
        return books_ledger.gl_summary(conn, ctx.entity_id, f, t, codes.split(",") if codes else None, include_zero)
    return _run(request, fn, "reports.view", cache_ttl=60)


@router.get("/ledger/gl-account/{code}")
def ledger_gl_account(code: str, request: Request, date_from: Optional[str] = Query(None, alias="from"),
                      date_to: Optional[str] = Query(None, alias="to"), search: Optional[str] = None):
    def fn(conn, ctx):
        f, t = _range(date_from, date_to)
        return books_ledger.gl_account(conn, ctx.entity_id, code, f, t, search=search or None)
    return _run(request, fn, "reports.view")


@router.get("/ledger/trial-balance")
def ledger_trial_balance(request: Request, as_of: Optional[str] = None, include_zero: bool = False):
    """Sage 'General Ledger Trial Balance': Account ID, Description, Debit, Credit as of a date."""
    return _run(request, lambda c, x: books_ledger.trial_balance_as_of(c, x.entity_id, _date(as_of) or _today(), include_zero),
                "reports.view", cache_ttl=60)


@router.get("/ledger/journal/{key}")
def ledger_journal(key: str, request: Request, date_from: Optional[str] = Query(None, alias="from"),
                   date_to: Optional[str] = Query(None, alias="to"), search: Optional[str] = None):
    def fn(conn, ctx):
        f, t = _range(date_from, date_to)
        return ledger_reports.journal(conn, ctx.entity_id, key, f, t, search=search or None)
    return _run(request, fn, "reports.view")


@router.get("/ledger/party/{kind}")
def ledger_party(kind: str, request: Request, date_from: Optional[str] = Query(None, alias="from"),
                 date_to: Optional[str] = Query(None, alias="to"), party_id: Optional[str] = None,
                 search: Optional[str] = None, only_activity: bool = False):
    def fn(conn, ctx):
        f, t = _range(date_from, date_to)
        if kind.upper() not in ("CUSTOMER", "VENDOR"):
            raise invalid("kind is customer or vendor")
        return ledger_reports.party_ledger(conn, ctx.entity_id, kind, f, t, party_id or None, search or None, only_activity)
    return _run(request, fn, "receivables.view" if kind.lower() == "customer" else "payables.view")


@router.get("/sage-history/transaction")
def sage_transaction(request: Request, date: str, jrnl: Optional[str] = None, ref: Optional[str] = None):
    return _run(request, lambda c, x: books_ledger.sage_transaction(c, x.entity_id, _date(date), jrnl or None, ref or None),
                "reports.view")


@router.get("/sage-history/receipt")
def sage_receipt(request: Request, date: str, ref: Optional[str] = None, customer: Optional[str] = None):
    return _run(request, lambda c, x: ledger_reports.sage_receipt(c, x.entity_id, _date(date), ref or None, customer or None),
                "receivables.view")


# ---------------------------------------------------------------------------
# Reports
# ---------------------------------------------------------------------------

@router.get("/reports/{name}")
def report(name: str, request: Request, date_from: Optional[str] = Query(None, alias="from"),
           date_to: Optional[str] = Query(None, alias="to"), as_of: Optional[str] = None,
           compare_from: Optional[str] = None, compare_to: Optional[str] = None, budget_id: Optional[str] = None,
           basis: str = "due_date", sku: Optional[str] = None, kind: Optional[str] = None,
           expiring_within_days: Optional[int] = None):
    def fn(conn, ctx):
        f, t = _range(date_from, date_to)
        on = _date(as_of) or t
        if name == "income-statement":
            fy = reports._fy_start(conn, ctx.entity_id, t) if not date_from else f
            return reports.income_statement(conn, ctx.entity_id, fy, t, _date(compare_from), _date(compare_to), budget_id)
        if name == "balance-sheet":
            return reports.balance_sheet(conn, ctx.entity_id, on)
        if name == "cash-flow":
            return reports.cash_flow(conn, ctx.entity_id, f, t)
        if name == "retained-earnings":
            fy = reports._fy_start(conn, ctx.entity_id, t) if not date_from else f
            return reports.retained_earnings(conn, ctx.entity_id, fy, t)
        if name == "aged-receivables":
            return reports.aged_receivables(conn, ctx.entity_id, on, basis)
        if name == "aged-payables":
            return reports.aged_payables(conn, ctx.entity_id, on, basis)
        if name == "journal":
            return ledger_reports.journal(conn, ctx.entity_id, kind or "sales", f, t)
        if name == "inventory-valuation":
            return reports.inventory_valuation(conn, ctx.entity_id, on)
        if name == "unit-activity":
            return reports.unit_activity(conn, ctx.entity_id, f, t, sku)
        if name == "stock-status":
            return reports.stock_status(conn, ctx.entity_id)
        if name == "batches":
            return reports.batch_list(conn, ctx.entity_id, sku, expiring_within_days)
        if name == "budget-vs-actual":
            if not budget_id:
                raise invalid("Choose a budget")
            fy = reports._fy_start(conn, ctx.entity_id, t) if not date_from else f
            return reports.budget_vs_actual(conn, ctx.entity_id, budget_id, fy, t)
        raise FinError("RESOURCE_NOT_FOUND", f"Unknown report {name}")
    return _run(request, fn, "reports.view", cache_ttl=60)


@router.get("/reports/customer-statement/{customer_id}")
def customer_statement(customer_id: int, request: Request, date_from: Optional[str] = Query(None, alias="from"),
                       date_to: Optional[str] = Query(None, alias="to")):
    def fn(conn, ctx):
        t = _date(date_to) or _today()
        f = _date(date_from) or dt.date(t.year, 1, 1)
        # Sage's own customer ledger before the hand-over + ACE Books documents after it
        led = ledger_reports.party_ledger(conn, ctx.entity_id, "CUSTOMER", f, t, str(customer_id))
        c = q1(conn, "SELECT id, name, customer_code, contact_details, credit_limit FROM customers WHERE id=%s", (customer_id,))
        rows = [r for r in led["rows"] if r["row_kind"] == "TXN"]
        opening = next((r["balance"] for r in led["rows"] if r["row_kind"] == "BALFWD"), 0)
        return {"customer": c, "date_from": f, "date_to": t, "opening_balance": opening, "rows": rows,
                "closing_balance": rows[-1]["balance"] if rows else opening, "history_until": led["history_until"],
                "total_debit": led["total_debit"], "total_credit": led["total_credit"],
                "aging": reports.aged_customer(conn, ctx.entity_id, customer_id, t)}
    return _run(request, fn, "receivables.view")


@router.get("/reports/supplier-statement/{supplier_id}")
def supplier_statement(supplier_id: str, request: Request, date_from: Optional[str] = Query(None, alias="from"),
                       date_to: Optional[str] = Query(None, alias="to")):
    def fn(conn, ctx):
        t = _date(date_to) or _today()
        f = _date(date_from) or dt.date(t.year, 1, 1)
        led = ledger_reports.party_ledger(conn, ctx.entity_id, "VENDOR", f, t, str(supplier_id))
        s = q1(conn, "SELECT id, name, external_vendor_id FROM suppliers WHERE id=%s", (supplier_id,))
        rows = [r for r in led["rows"] if r["row_kind"] == "TXN"]
        opening = next((r["balance"] for r in led["rows"] if r["row_kind"] == "BALFWD"), 0)
        return {"supplier": s, "date_from": f, "date_to": t, "opening_balance": opening, "rows": rows,
                "closing_balance": rows[-1]["balance"] if rows else opening, "history_until": led["history_until"],
                "total_debit": led["total_debit"], "total_credit": led["total_credit"]}
    return _run(request, fn, "payables.view")


# ---------------------------------------------------------------------------
# Report Center (Sage report set) and lineage overviews
# ---------------------------------------------------------------------------

@router.get("/report-center/{key}")
def report_center_run(key: str, request: Request, date_from: Optional[str] = Query(None, alias="from"),
                      date_to: Optional[str] = Query(None, alias="to"), as_of: Optional[str] = None,
                      account_id: Optional[str] = None, customer_id: Optional[int] = None, supplier_id: Optional[str] = None,
                      sku: Optional[str] = None, bank_account_id: Optional[str] = None, month: Optional[str] = None,
                      with_balance: bool = False):
    def fn(conn, ctx):
        t = _date(date_to) or _today()
        f = _date(date_from) or reports._fy_start(conn, ctx.entity_id, t)
        if f > t:
            raise FinError("VALIDATION_FAILED", "'from' is after 'to'")
        return report_center.run(conn, ctx.entity_id, key, {
            "from": f, "to": t, "as_of": _date(as_of) or t, "account_id": account_id, "customer_id": customer_id,
            "supplier_id": supplier_id, "sku": sku, "bank_account_id": bank_account_id, "month": month,
            "with_balance": with_balance})
    return _run(request, fn, "reports.view")


@router.get("/customers/{customer_id}/overview")
def customer_overview(customer_id: int, request: Request):
    """Customer lineage hub: who they are, what they owe, what they bought, their documents."""
    def fn(conn, ctx):
        c = sales.customer(conn, customer_id)
        today = _today()
        items = reports.ar_open_items(conn, ctx.entity_id, today, customer_id)
        invoices = q(conn, """SELECT id, invoice_number, invoice_date, due_date, total, total - amount_settled AS balance, status, is_opening
                              FROM fin_sales_invoices WHERE legal_entity_id=%s AND customer_id=%s AND status <> 'DRAFT'
                              ORDER BY invoice_date DESC LIMIT 100""", (ctx.entity_id, customer_id))
        receipts = q(conn, """SELECT id, receipt_number, receipt_date, method, reference, amount, status FROM fin_customer_receipts
                              WHERE legal_entity_id=%s AND customer_id=%s ORDER BY receipt_date DESC LIMIT 50""", (ctx.entity_id, customer_id))
        products = q(conn, """SELECT l.sku, p.name, SUM(l.quantity) AS quantity, SUM(l.line_total) AS amount, MAX(i.invoice_date) AS last_date
                              FROM fin_sales_invoice_lines l JOIN fin_sales_invoices i ON i.id=l.invoice_id
                              LEFT JOIN fin_products p ON p.legal_entity_id=i.legal_entity_id AND p.sku=l.sku
                              WHERE i.legal_entity_id=%s AND i.customer_id=%s AND l.sku IS NOT NULL AND i.status NOT IN ('DRAFT','VOID')
                              GROUP BY l.sku, p.name ORDER BY amount DESC LIMIT 50""", (ctx.entity_id, customer_id))
        loans = q(conn, """SELECT id, loan_number, sku, loan_date, quantity - quantity_returned AS outstanding, status FROM fin_stock_loans
                           WHERE legal_entity_id=%s AND customer_id=%s AND status IN ('OPEN','PARTIALLY_RETURNED')""", (ctx.entity_id, customer_id))
        frontdesk = q(conn, """SELECT f.id, f.invoice_number, f.status, f.total_amount AS total, f.created_at::date AS date
                               FROM frontdesk_invoices f JOIN frontdesk_walk_ins w ON w.id=f.walk_in_id
                               WHERE w.customer_id=%s AND f.status IN ('draft','qc_pending','qc_passed','finance_pending')
                               ORDER BY f.created_at DESC""", (customer_id,))
        return {"customer": c, "balance": sum((i["open_amount"] for i in items), 0),
                "exposure": sales.customer_exposure(conn, ctx.entity_id, customer_id),
                "frontdesk_in_progress": frontdesk, "sage": sage_history.customer_history(conn, ctx.entity_id, customer_id),
                "overdue": sum((i["open_amount"] for i in items if i["due_date"] < today), 0),
                "open_items": items, "invoices": invoices, "receipts": receipts, "products": products, "loans": loans}
    return _run(request, fn, "receivables.view")


@router.get("/suppliers/{supplier_id}/overview")
def supplier_overview(supplier_id: str, request: Request):
    def fn(conn, ctx):
        s = purchases.supplier(conn, supplier_id)
        today = _today()
        items = reports.ap_open_items(conn, ctx.entity_id, today, supplier_id)
        bills = q(conn, """SELECT id, bill_number, supplier_invoice_number, bill_date, due_date, total, total - amount_settled AS balance, status, is_opening
                           FROM fin_supplier_bills WHERE legal_entity_id=%s AND supplier_id=%s ORDER BY bill_date DESC LIMIT 100""",
                  (ctx.entity_id, supplier_id))
        payments = q(conn, """SELECT id, payment_number, payment_date, method, reference, amount, status FROM fin_supplier_payments
                              WHERE legal_entity_id=%s AND supplier_id=%s ORDER BY payment_date DESC LIMIT 50""", (ctx.entity_id, supplier_id))
        products = q(conn, """SELECT l.sku, p.name, SUM(l.quantity) AS quantity, SUM(l.line_total) AS amount, MAX(b.bill_date) AS last_date
                              FROM fin_supplier_bill_lines l JOIN fin_supplier_bills b ON b.id=l.bill_id
                              LEFT JOIN fin_products p ON p.legal_entity_id=b.legal_entity_id AND p.sku=l.sku
                              WHERE b.legal_entity_id=%s AND b.supplier_id=%s AND l.sku IS NOT NULL AND b.status <> 'VOID'
                              GROUP BY l.sku, p.name ORDER BY amount DESC LIMIT 50""", (ctx.entity_id, supplier_id))
        sage = q(conn, """SELECT p.sku, COALESCE(pr.name, MAX(p.description)) AS name, SUM(p.quantity) AS quantity, SUM(p.amount) AS amount,
                                 MAX(p.bill_date) AS last_date
                          FROM fin_sage_purchase_lines p LEFT JOIN fin_products pr ON pr.legal_entity_id=p.legal_entity_id AND pr.sku=p.sku
                          WHERE p.legal_entity_id=%s AND p.supplier_id=%s GROUP BY p.sku, pr.name ORDER BY amount DESC LIMIT 100""",
                 (ctx.entity_id, supplier_id))
        return {"supplier": s, "balance": sum((i["open_amount"] for i in items), 0), "sage_products": sage,
                "sage_bills": sage_history.supplier_bills(conn, ctx.entity_id, supplier_id),
                "overdue": sum((i["open_amount"] for i in items if i["due_date"] < today and i["doc_type"] == "BILL"), 0),
                "open_items": items, "bills": bills, "payments": payments, "products": products}
    return _run(request, fn, "payables.view")


# ---------------------------------------------------------------------------
# Parties & products
# ---------------------------------------------------------------------------

@router.get("/customers")
def find_customers(request: Request, search: str = "", limit: int = 20):
    return _run(request, lambda c, x: q(c, """SELECT id, name, customer_code, credit_limit, payment_terms_days FROM customers
                                               WHERE name ILIKE %s OR customer_code ILIKE %s ORDER BY name LIMIT %s""",
                                         (f"%{search}%", f"%{search}%", limit)), "receivables.view")


@router.get("/customers/{customer_id}/credit")
def customer_credit(customer_id: int, request: Request, amount: float = 0):
    return _run(request, lambda c, x: sales.credit_check(c, x.entity_id, customer_id, sales.money(amount)), "receivables.view")


@router.get("/suppliers")
def find_suppliers(request: Request, search: str = "", limit: int = 20):
    return _run(request, lambda c, x: q(c, """SELECT id, name, external_vendor_id AS supplier_code, payment_terms, address, phone, contact_email FROM suppliers
                                               WHERE name ILIKE %s OR external_vendor_id ILIKE %s ORDER BY name LIMIT %s""",
                                         (f"%{search}%", f"%{search}%", limit)), "payables.view")


@router.get("/products")
def find_products(request: Request, search: str = "", limit: int = 30, customer_id: Optional[int] = None,
                  for_sale: bool = False):
    """Product search with the prefills the invoice forms need: stock on hand, the sellable
    batches (batch number, manufacture date, expiry, quantity, cost) earliest expiry first,
    list price and the last price this customer paid (ACE Books first, then Sage history).
    for_sale=true lists only what can be sold now: an item whose every lot is expired, recalled
    or quarantined - or that has no stock - is left out (services are always offered)."""
    def fn(conn, ctx):
        sellable = """(SELECT COALESCE(SUM(l.qty_remaining),0) FROM fin_cost_layers l LEFT JOIN fin_batches b ON b.id=l.batch_id
                       WHERE l.legal_entity_id=p.legal_entity_id AND l.sku=p.sku AND l.qty_remaining > 0
                         AND (b.id IS NULL OR (b.status='AVAILABLE' AND (b.expiry_date IS NULL OR b.expiry_date >= current_date))))"""
        # A lot Sage sold below zero (its receipt never entered) stays visible, flagged, so the newest
        # stock is never hidden from an invoice: the user records the receipt from there.
        pending = """EXISTS (SELECT 1 FROM fin_data_exceptions x WHERE x.legal_entity_id=p.legal_entity_id
                     AND x.kind='STOCK_SHORT_LOT' AND x.status='OPEN' AND x.key=p.sku)"""
        sale_filter = f" AND (p.product_type <> 'INVENTORY' OR {sellable} > 0 OR {pending})" if for_sale else ""
        rows = q(conn, f"""SELECT p.id, p.sku, p.name, p.product_type, p.standard_price, p.status, p.uom, p.lot_expiry,
                                 COALESCE((SELECT SUM(qty_remaining) FROM fin_cost_layers l
                                           WHERE l.legal_entity_id=p.legal_entity_id AND l.sku=p.sku),0) AS on_hand,
                                 {sellable} AS sellable_qty,
                                 fb.id AS next_batch_id, fb.batch_number AS next_batch, fb.expiry_date AS next_expiry,
                                 fb.manufacture_date AS next_mfg, fb.available AS next_batch_qty
                          FROM fin_products p
                          LEFT JOIN LATERAL (SELECT b.id, b.batch_number, b.expiry_date, b.manufacture_date, SUM(l.qty_remaining) AS available
                                             FROM fin_cost_layers l JOIN fin_batches b ON b.id=l.batch_id
                                             WHERE l.legal_entity_id=p.legal_entity_id AND l.sku=p.sku AND l.qty_remaining > 0
                                               AND b.status='AVAILABLE' AND (b.expiry_date IS NULL OR b.expiry_date >= current_date)
                                             GROUP BY b.id ORDER BY b.expiry_date NULLS LAST LIMIT 1) fb ON TRUE
                          WHERE p.legal_entity_id=%s AND p.status='ACTIVE' AND (p.sku ILIKE %s OR p.name ILIKE %s) {sale_filter}
                          ORDER BY ({sellable} > 0) DESC, p.name, fb.expiry_date NULLS LAST, p.sku
                          LIMIT %s""", (ctx.entity_id, f"%{search}%", f"%{search}%", limit))
        for r in rows:
            r["batches"] = q(conn, """SELECT b.id, b.batch_number, b.lot_code, b.pack_batch_number, b.manufacture_date, b.expiry_date, b.status,
                                             SUM(l.qty_remaining) AS available,
                                             round(SUM(l.qty_remaining * l.unit_cost) / NULLIF(SUM(l.qty_remaining),0), 2) AS unit_cost,
                                             (b.status='AVAILABLE' AND (b.expiry_date IS NULL OR b.expiry_date >= current_date)) AS sellable
                                      FROM fin_cost_layers l JOIN fin_batches b ON b.id=l.batch_id
                                      WHERE l.legal_entity_id=%s AND l.sku=%s AND l.qty_remaining > 0
                                      GROUP BY b.id ORDER BY 9 DESC, b.expiry_date NULLS LAST""", (ctx.entity_id, r["sku"]))
            last = None
            if customer_id:
                last = q1(conn, """SELECT l.unit_price AS price, i.invoice_date AS date FROM fin_sales_invoice_lines l
                                   JOIN fin_sales_invoices i ON i.id=l.invoice_id
                                   WHERE i.legal_entity_id=%s AND i.customer_id=%s AND l.sku=%s AND i.status NOT IN ('DRAFT','VOID')
                                   ORDER BY i.invoice_date DESC LIMIT 1""", (ctx.entity_id, customer_id, r["sku"]))
                if not last:
                    last = q1(conn, """SELECT ROUND(amount/NULLIF(quantity,0), 2) AS price, invoice_date AS date FROM fin_sage_sales_lines
                                       WHERE legal_entity_id=%s AND customer_id=%s AND lower(trim(description))=lower(trim(%s))
                                         AND quantity > 0 ORDER BY invoice_date DESC LIMIT 1""", (ctx.entity_id, customer_id, r["name"]))
            recent = q1(conn, """SELECT ROUND(amount/NULLIF(quantity,0), 2) AS price, invoice_date AS date FROM fin_sage_sales_lines
                                 WHERE legal_entity_id=%s AND lower(trim(description))=lower(trim(%s)) AND quantity > 0
                                 ORDER BY invoice_date DESC LIMIT 1""", (ctx.entity_id, r["name"]))
            r["customer_last_price"] = last["price"] if last else None
            r["customer_last_date"] = last["date"] if last else None
            r["recent_price"] = recent["price"] if recent else None
            r["suggested_price"] = (r["customer_last_price"] or r["standard_price"] or r["recent_price"])
            r["last_cost"] = inventory.last_unit_cost(conn, ctx.entity_id, r["sku"]) or None
        fams = data_exceptions.pending_lots(conn, ctx.entity_id, list({data_exceptions.family(r["sku"]) for r in rows}))
        for r in rows:
            fam = fams.get(data_exceptions.family(r["sku"]), [])
            r["receipt_pending"] = next((x for x in fam if x["sku"] == r["sku"]), None)
            r["family_receipts_pending"] = fam
        return rows
    return _run(request, fn, "inventory.view")


@router.post("/products")
def create_product(request: Request, payload: Dict[str, Any] = Body(...)):
    def fn(conn, ctx):
        ctx.require("inventory.product.create")
        sku = str(payload.get("sku") or "").strip()
        if not sku or not payload.get("name"):
            raise invalid("SKU and name are required")
        if q1(conn, "SELECT 1 FROM fin_products WHERE legal_entity_id=%s AND sku=%s", (ctx.entity_id, sku)):
            raise FinError("DUPLICATE_RESOURCE", f"Product {sku} already exists")
        p = q1(conn, """INSERT INTO fin_products (legal_entity_id, sku, name, product_type, uom, revenue_account_id,
                        inventory_account_id, cogs_account_id, standard_price, reorder_level)
                        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING *""",
               (ctx.entity_id, sku, payload["name"], payload.get("product_type", "INVENTORY"), payload.get("uom", "Each"),
                payload.get("revenue_account_id"), payload.get("inventory_account_id"), payload.get("cogs_account_id"),
                payload.get("standard_price"), payload.get("reorder_level")))
        audit.record(conn, ctx, "PRODUCT_CREATED", "product", p["id"], ref=sku, after=p)
        return p
    return _run(request, fn)


@router.get("/products/{sku:path}/movements")
def product_movements(sku: str, request: Request, date_from: Optional[str] = Query(None, alias="from"),
                      date_to: Optional[str] = Query(None, alias="to")):
    def fn(conn, ctx):
        t = _date(date_to) or _today()
        f = _date(date_from) or dt.date(t.year - 1, 1, 1)
        return {"product": rules.product(conn, ctx.entity_id, sku), "on_hand": inventory.on_hand(conn, ctx.entity_id, sku),
                "movements": reports.item_movements(conn, ctx.entity_id, sku, f, t),
                "batches": reports.batch_list(conn, ctx.entity_id, sku),
                "sage": sage_history.product_history(conn, ctx.entity_id, sku)}
    return _run(request, fn, "inventory.view")


# ---------------------------------------------------------------------------
# Sales & receivables
# ---------------------------------------------------------------------------

@router.get("/sales/invoices")
def list_invoices(request: Request, customer_id: Optional[int] = None, status: Optional[str] = None, search: Optional[str] = None,
                  date_from: Optional[str] = Query(None, alias="from"), date_to: Optional[str] = Query(None, alias="to"),
                  open_only: bool = False, limit: int = 100, offset: int = 0):
    return _run(request, lambda c, x: sales.list_invoices(c, x.entity_id, customer_id=customer_id, status=status, search=search,
                                                           date_from=_date(date_from), date_to=_date(date_to),
                                                           open_only=open_only, limit=limit, offset=offset), "receivables.view")


@router.post("/sales/invoices")
def create_invoice(request: Request, payload: Dict[str, Any] = Body(...)):
    def fn(conn, ctx):
        p = _dates(payload)
        inv = sales.create_invoice(conn, ctx, p)
        if p.get("post"):
            inv = sales.post_invoice(conn, ctx, str(inv["id"]), override_credit=bool(p.get("override_credit")),
                                     override_reason=p.get("override_reason"))
        return inv
    return _run(request, fn)


@router.get("/sales/invoices/{invoice_id}")
def get_invoice(invoice_id: str, request: Request):
    return _run(request, lambda c, x: sales.get_invoice(c, x.entity_id, invoice_id), "receivables.view")


@router.post("/sales/invoices/{invoice_id}/post")
def post_invoice(invoice_id: str, request: Request, payload: Dict[str, Any] = Body(default={})):
    return _run(request, lambda c, x: sales.post_invoice(c, x, invoice_id, override_credit=bool(payload.get("override_credit")),
                                                          override_reason=payload.get("override_reason")))


@router.post("/sales/invoices/{invoice_id}/amend")
def amend_invoice(invoice_id: str, request: Request, payload: Dict[str, Any] = Body(...)):
    return _run(request, lambda c, x: sales.amend_invoice(c, x, invoice_id, _dates(payload)))


@router.post("/receivables/receipts/{receipt_id}/correct")
def correct_receipt(receipt_id: str, request: Request, payload: Dict[str, Any] = Body(...)):
    return _run(request, lambda c, x: sales.correct_receipt(c, x, receipt_id, _dates(payload)))


@router.post("/banking/vouchers/{voucher_id}/correct")
def correct_voucher(voucher_id: str, request: Request, payload: Dict[str, Any] = Body(...)):
    return _run(request, lambda c, x: banking.correct_voucher(c, x, voucher_id, _dates(payload)))


@router.post("/sales/invoices/{invoice_id}/void")
def void_invoice(invoice_id: str, request: Request, payload: Dict[str, Any] = Body(...)):
    return _run(request, lambda c, x: sales.void_invoice(c, x, invoice_id, payload.get("reason", ""), _date(payload.get("on"))))


@router.get("/sales/credit-notes")
def list_credit_notes(request: Request, limit: int = 100, offset: int = 0):
    return _run(request, lambda c, x: sales.list_credit_notes(c, x.entity_id, limit, offset), "receivables.view")


@router.post("/sales/credit-notes")
def create_credit_note(request: Request, payload: Dict[str, Any] = Body(...)):
    return _run(request, lambda c, x: sales.create_credit_note(c, x, _dates(payload)))


@router.get("/sales/credit-notes/{cn_id}")
def get_credit_note(cn_id: str, request: Request):
    return _run(request, lambda c, x: sales.get_credit_note(c, x.entity_id, cn_id), "receivables.view")


@router.post("/sales/credit-notes/{cn_id}/allocate")
def allocate_credit_note(cn_id: str, request: Request, payload: Dict[str, Any] = Body(...)):
    return _run(request, lambda c, x: sales.allocate_credit_note(c, x, cn_id, payload.get("allocations") or []))


@router.get("/sales/invoice-register")
def sales_invoice_register(request: Request, date_from: Optional[str] = Query(None, alias="from"),
                           date_to: Optional[str] = Query(None, alias="to"), search: Optional[str] = None,
                           customer_id: Optional[int] = None):
    def fn(conn, ctx):
        f, t = _range(date_from, date_to)
        return ledger_reports.invoice_register(conn, ctx.entity_id, f, t, search or None, customer_id)
    return _run(request, fn, "receivables.view")


@router.get("/receivables/open-items")
def ar_open_items(request: Request, customer_id: int, as_of: Optional[str] = None):
    """A customer's open items. Invoices carry what was sold on them (`items`), so a receipt can be
    applied knowing which goods or service it pays for."""
    def fn(conn, ctx):
        rows = reports.ar_open_items(conn, ctx.entity_id, _date(as_of) or _today(), customer_id)
        ids = [str(r["doc_id"]) for r in rows if r["doc_type"] == "INVOICE"]
        if ids:
            what = {str(r["id"]): r for r in q(conn, """
                SELECT i.id, i.invoice_date, i.is_opening, COALESCE(i.original_total, i.total) AS invoice_total,
                       COALESCE((SELECT string_agg(COALESCE(NULLIF(l.description,''), l.sku) || CASE WHEN l.line_type IN ('ITEM','SERVICE')
                                         THEN ' x' || trim(to_char(l.quantity, 'FM999999990.##')) ELSE '' END, ', ' ORDER BY l.line_no)
                                 FROM fin_sales_invoice_lines l WHERE l.invoice_id=i.id),
                                (SELECT string_agg(COALESCE(s.description, s.sku) || COALESCE(' x' || trim(to_char(s.quantity, 'FM999999990.##')), ''),
                                                   ', ' ORDER BY s.line_no)
                                 FROM fin_sage_sales_lines s WHERE s.legal_entity_id=i.legal_entity_id
                                   AND s.invoice_number=split_part(i.invoice_number, '/', 1))) AS items
                FROM fin_sales_invoices i WHERE i.id = ANY(%s::uuid[])""", (ids,))}
            for r in rows:
                w = what.get(str(r["doc_id"]))
                if w:
                    r["items"] = w["items"]
                    r["invoice_total"] = w["invoice_total"]
                    r["from_sage"] = w["is_opening"]
        return rows
    return _run(request, fn, "receivables.view")


@router.get("/receivables/receipts")
def list_receipts(request: Request, customer_id: Optional[int] = None, search: Optional[str] = None,
                  date_from: Optional[str] = Query(None, alias="from"), date_to: Optional[str] = Query(None, alias="to"),
                  limit: int = 100, offset: int = 0):
    return _run(request, lambda c, x: sales.list_receipts(c, x.entity_id, customer_id=customer_id, search=search,
                                                           date_from=_date(date_from), date_to=_date(date_to),
                                                           limit=limit, offset=offset), "receivables.view")


@router.post("/receivables/receipts")
def create_receipt(request: Request, payload: Dict[str, Any] = Body(...)):
    return _run(request, lambda c, x: sales.create_receipt(c, x, _dates(payload)))


@router.get("/receivables/receipts/{receipt_id}")
def get_receipt(receipt_id: str, request: Request):
    return _run(request, lambda c, x: sales.get_receipt(c, x.entity_id, receipt_id), "receivables.view")


@router.post("/receivables/receipts/{receipt_id}/allocate")
def allocate_receipt(receipt_id: str, request: Request, payload: Dict[str, Any] = Body(...)):
    return _run(request, lambda c, x: sales.allocate_receipt(c, x, receipt_id, payload.get("allocations") or []))


@router.post("/receivables/receipts/{receipt_id}/void")
def void_receipt(receipt_id: str, request: Request, payload: Dict[str, Any] = Body(...)):
    return _run(request, lambda c, x: sales.void_receipt(c, x, receipt_id, payload.get("reason", ""), _date(payload.get("on"))))


# ---------------------------------------------------------------------------
# Payables
# ---------------------------------------------------------------------------

@router.get("/payables/bills")
def list_bills(request: Request, supplier_id: Optional[str] = None, search: Optional[str] = None, open_only: bool = False,
               date_from: Optional[str] = Query(None, alias="from"), date_to: Optional[str] = Query(None, alias="to"),
               limit: int = 100, offset: int = 0):
    return _run(request, lambda c, x: purchases.list_bills(c, x.entity_id, supplier_id=supplier_id, search=search,
                                                            open_only=open_only, date_from=_date(date_from), date_to=_date(date_to),
                                                            limit=limit, offset=offset), "payables.view")


@router.post("/payables/bills")
def create_bill(request: Request, payload: Dict[str, Any] = Body(...)):
    return _run(request, lambda c, x: purchases.create_bill(c, x, _dates(payload)))


@router.get("/payables/bills/{bill_id}")
def get_bill(bill_id: str, request: Request):
    return _run(request, lambda c, x: purchases.get_bill(c, x.entity_id, bill_id), "payables.view")


@router.post("/payables/bills/{bill_id}/void")
def void_bill(bill_id: str, request: Request, payload: Dict[str, Any] = Body(...)):
    return _run(request, lambda c, x: purchases.void_bill(c, x, bill_id, payload.get("reason", "")))


@router.get("/payables/open-items")
def ap_open_items(request: Request, supplier_id: str, as_of: Optional[str] = None):
    return _run(request, lambda c, x: reports.ap_open_items(c, x.entity_id, _date(as_of) or _today(), supplier_id), "payables.view")


@router.get("/payables/payments")
def list_payments(request: Request, supplier_id: Optional[str] = None, search: Optional[str] = None,
                  date_from: Optional[str] = Query(None, alias="from"), date_to: Optional[str] = Query(None, alias="to"),
                  limit: int = 100, offset: int = 0):
    return _run(request, lambda c, x: purchases.list_payments(c, x.entity_id, supplier_id=supplier_id, search=search,
                                                               date_from=_date(date_from), date_to=_date(date_to),
                                                               limit=limit, offset=offset), "payables.view")


@router.post("/payables/payments")
def create_payment(request: Request, payload: Dict[str, Any] = Body(...)):
    return _run(request, lambda c, x: purchases.create_payment(c, x, _dates(payload)))


@router.get("/payables/payments/{payment_id}")
def get_payment(payment_id: str, request: Request):
    return _run(request, lambda c, x: purchases.get_payment(c, x.entity_id, payment_id), "payables.view")


@router.post("/payables/payments/{payment_id}/allocate")
def allocate_payment(payment_id: str, request: Request, payload: Dict[str, Any] = Body(...)):
    return _run(request, lambda c, x: purchases.allocate_payment(c, x, payment_id, payload.get("allocations") or []))


@router.post("/payables/payments/{payment_id}/void")
def void_payment(payment_id: str, request: Request, payload: Dict[str, Any] = Body(...)):
    return _run(request, lambda c, x: purchases.void_payment(c, x, payment_id, payload.get("reason", "")))


@router.get("/payables/debit-notes")
def list_debit_notes(request: Request, limit: int = 100, offset: int = 0, supplier_id: Optional[str] = None,
                     search: Optional[str] = None, status: Optional[str] = None,
                     date_from: Optional[str] = Query(None, alias="from"), date_to: Optional[str] = Query(None, alias="to")):
    return _run(request, lambda c, x: purchases.list_debit_notes(c, x.entity_id, limit, offset, supplier_id=supplier_id, search=search,
                                                                  date_from=_date(date_from), date_to=_date(date_to), status=status),
                "payables.view")


@router.post("/payables/debit-notes/{dn_id}/allocate")
def allocate_debit_note(dn_id: str, request: Request, payload: Dict[str, Any] = Body(...)):
    return _run(request, lambda c, x: purchases.allocate_debit_note(c, x, dn_id, payload.get("allocations") or []))


@router.post("/payables/debit-notes")
def create_debit_note(request: Request, payload: Dict[str, Any] = Body(...)):
    return _run(request, lambda c, x: purchases.create_debit_note(c, x, _dates(payload)))


@router.get("/payables/debit-notes/{dn_id}")
def get_debit_note(dn_id: str, request: Request):
    return _run(request, lambda c, x: purchases.get_debit_note(c, x.entity_id, dn_id), "payables.view")


# ---------------------------------------------------------------------------
# Inventory
# ---------------------------------------------------------------------------

@router.get("/inventory/adjustments")
def list_adjustments(request: Request, limit: int = 300):
    """ACE Books adjustments, then the inventory adjustments made in Sage (one row per transaction)."""
    def fn(conn, ctx):
        ace = q(conn, """SELECT a.*, a.id::text AS id, 'ACE' AS source,
                                (SELECT COUNT(*) FROM fin_stock_adjustment_lines l WHERE l.adjustment_id=a.id) AS lines
                         FROM fin_stock_adjustments a WHERE a.legal_entity_id=%s
                         ORDER BY a.adjustment_date DESC, a.adjustment_number DESC LIMIT %s""", (ctx.entity_id, limit))
        sage = q(conn, """SELECT NULL AS id, COALESCE(NULLIF(reference, ''), 'INAJ') AS adjustment_number, txn_date AS adjustment_date,
                                 MAX(description) AS notes, 'SAGE' AS reason_code, 'POSTED' AS status, COUNT(*) AS lines,
                                 SUM(debit) AS total_value, reference, 'SAGE' AS source
                          FROM fin_sage_gl_lines WHERE legal_entity_id=%s AND jrnl='INAJ' AND (debit <> 0 OR credit <> 0)
                          GROUP BY txn_date, reference ORDER BY txn_date DESC LIMIT %s""", (ctx.entity_id, limit))
        return ace + sage
    return _run(request, fn, "inventory.view")


@router.post("/inventory/adjustments")
def create_adjustment(request: Request, payload: Dict[str, Any] = Body(...)):
    def fn(conn, ctx):
        adj = inventory.create_adjustment(conn, ctx, _dates(payload))
        if payload.get("post"):
            adj = inventory.post_adjustment(conn, ctx, str(adj["id"]))
        return adj
    return _run(request, fn)


@router.get("/inventory/adjustments/{adj_id}")
def get_adjustment(adj_id: str, request: Request):
    return _run(request, lambda c, x: inventory.get_adjustment(c, x.entity_id, adj_id), "inventory.view")


@router.post("/inventory/adjustments/{adj_id}/post")
def post_adjustment(adj_id: str, request: Request):
    return _run(request, lambda c, x: inventory.post_adjustment(c, x, adj_id))


@router.get("/inventory/counts")
def list_counts(request: Request):
    return _run(request, lambda c, x: q(c, """SELECT s.*, v.lines, v.counted, v.variance_lines, v.variance_qty
                                               FROM fin_stock_counts s
                                               LEFT JOIN LATERAL (SELECT COUNT(*) AS lines, COUNT(l.counted_qty) AS counted,
                                                                         COUNT(*) FILTER (WHERE l.counted_qty IS NOT NULL AND l.counted_qty <> l.system_qty) AS variance_lines,
                                                                         COALESCE(SUM(l.counted_qty - l.system_qty) FILTER (WHERE l.counted_qty IS NOT NULL), 0) AS variance_qty
                                                                  FROM fin_stock_count_lines l WHERE l.count_id=s.id) v ON TRUE
                                               WHERE s.legal_entity_id=%s ORDER BY s.count_date DESC, s.created_at DESC""",
                                         (x.entity_id,)), "inventory.view")


@router.get("/inventory/counts/overview")
def count_overview(request: Request):
    return _run(request, lambda c, x: inventory.count_overview(c, x.entity_id), "inventory.view")


@router.post("/inventory/counts")
def create_count(request: Request, payload: Dict[str, Any] = Body(...)):
    return _run(request, lambda c, x: inventory.create_count(c, x, _date(payload["count_date"]), payload.get("skus"), payload.get("notes")))


@router.get("/inventory/counts/{count_id}")
def get_count(count_id: str, request: Request):
    return _run(request, lambda c, x: inventory.get_count(c, x.entity_id, count_id), "inventory.view")


@router.put("/inventory/counts/{count_id}/lines")
def record_count(count_id: str, request: Request, payload: Dict[str, Any] = Body(...)):
    return _run(request, lambda c, x: inventory.record_count(c, x, count_id, payload.get("lines") or []))


@router.post("/inventory/counts/{count_id}/post")
def post_count(count_id: str, request: Request):
    return _run(request, lambda c, x: inventory.post_count(c, x, count_id))


@router.get("/inventory/loans")
def list_loans(request: Request, status: Optional[str] = None):
    def fn(conn, ctx):
        sf = " AND l.status = ANY(%s)" if status else ""
        p = [ctx.entity_id] + ([status.split(",")] if status else [])
        return q(conn, f"""SELECT l.*, c.name AS customer_name, b.batch_number, (l.quantity - l.quantity_returned) AS outstanding
                           FROM fin_stock_loans l LEFT JOIN customers c ON c.id=l.customer_id LEFT JOIN fin_batches b ON b.id=l.batch_id
                           WHERE l.legal_entity_id=%s {sf} ORDER BY l.loan_date DESC""", p)
    return _run(request, fn, "inventory.view")


@router.post("/inventory/loans")
def create_loan(request: Request, payload: Dict[str, Any] = Body(...)):
    return _run(request, lambda c, x: inventory.create_loan(c, x, _dates(payload)))


@router.get("/inventory/loans/{loan_id}")
def get_loan(loan_id: str, request: Request):
    return _run(request, lambda c, x: inventory.get_loan(c, x.entity_id, loan_id), "inventory.view")


@router.post("/inventory/loans/{loan_id}/return")
def return_loan(loan_id: str, request: Request, payload: Dict[str, Any] = Body(...)):
    return _run(request, lambda c, x: inventory.return_loan(c, x, loan_id, _dates(payload)))


@router.post("/inventory/loans/{loan_id}/write-off")
def write_off_loan(loan_id: str, request: Request, payload: Dict[str, Any] = Body(...)):
    return _run(request, lambda c, x: inventory.write_off_loan(c, x, loan_id, payload.get("reason", ""), _date(payload.get("on")) or _today()))


@router.get("/inventory/batches/{batch_id}/trace")
def trace_batch(batch_id: str, request: Request):
    return _run(request, lambda c, x: inventory.trace_batch(c, x.entity_id, batch_id), "inventory.view")


@router.get("/inventory/batch-search")
def batch_search(request: Request, search: str = ""):
    return _run(request, lambda c, x: q(c, """SELECT b.id, b.sku, b.batch_number, b.expiry_date, b.status, p.name AS product_name
                                               FROM fin_batches b LEFT JOIN fin_products p ON p.legal_entity_id=b.legal_entity_id AND p.sku=b.sku
                                               WHERE b.legal_entity_id=%s AND (b.batch_number ILIKE %s OR b.sku ILIKE %s)
                                               ORDER BY b.expiry_date NULLS LAST LIMIT 30""", (x.entity_id, f"%{search}%", f"%{search}%")),
                "inventory.view")


@router.post("/inventory/batches/{batch_id}/status")
def batch_status(batch_id: str, request: Request, payload: Dict[str, Any] = Body(...)):
    return _run(request, lambda c, x: inventory.set_batch_status(c, x, batch_id, payload["status"], payload.get("reason", "")))


@router.put("/inventory/batches/{batch_id}")
def batch_details(batch_id: str, request: Request, payload: Dict[str, Any] = Body(...)):
    """The manufacturer's batch number, manufacture and expiry dates (printed on invoices)."""
    return _run(request, lambda c, x: inventory.update_batch(c, x, batch_id, _dates(payload)))


@router.get("/sales/returnable-invoices")
def returnable_invoices(request: Request, customer_id: int, search: Optional[str] = None, sku: Optional[str] = None):
    return _run(request, lambda c, x: sales.returnable_invoices(c, x.entity_id, customer_id, search or None, sku or None),
                "receivables.view")


@router.get("/payables/returnable-bills")
def returnable_bills(request: Request, supplier_id: str, search: Optional[str] = None):
    return _run(request, lambda c, x: purchases.returnable_bills(c, x.entity_id, supplier_id, search or None), "payables.view")


@router.post("/inventory/recalls/{recall_id}/returns")
def recall_return(recall_id: str, request: Request, payload: Dict[str, Any] = Body(...)):
    return _run(request, lambda c, x: inventory.record_recall_return(c, x, recall_id, _dates(payload)))


@router.get("/settings/invoice-layout")
def invoice_layout(request: Request):
    return _run(request, lambda c, x: {"layout": setup.invoice_layout(c, x.entity_id),
                                       "next_invoice_number": numbering.next_invoice_preview(c, x.entity_id),
                                       "last_invoice": numbering.last_invoice(c, x.entity_id)})


@router.put("/settings/invoice-layout")
def save_invoice_layout(request: Request, payload: Dict[str, Any] = Body(...)):
    return _run(request, lambda c, x: setup.save_invoice_layout(c, x, payload))


@router.get("/inventory/recalls")
def list_recalls(request: Request):
    return _run(request, lambda c, x: q(c, """SELECT r.*, b.batch_number, s.customers, s.units_out, s.units_returned
                                               FROM fin_recalls r JOIN fin_batches b ON b.id=r.batch_id
                                               LEFT JOIN LATERAL (SELECT COUNT(*) AS customers, COALESCE(SUM(quantity_sold), 0) AS units_out,
                                                                         COALESCE(SUM(quantity_returned), 0) AS units_returned
                                                                  FROM fin_recall_items i WHERE i.recall_id=r.id) s ON TRUE
                                               WHERE r.legal_entity_id=%s ORDER BY r.opened_at DESC""", (x.entity_id,)), "inventory.view")


@router.post("/inventory/recalls")
def open_recall(request: Request, payload: Dict[str, Any] = Body(...)):
    def fn(conn, ctx):
        r = inventory.open_recall(conn, ctx, payload)
        from src.services import quality_hub
        quality_hub.case_for_fin_recall(conn, r, ctx.actor_id, payload)
        return inventory.get_recall(conn, ctx.entity_id, str(r["id"]))
    return _run(request, fn)


@router.get("/inventory/recalls/{recall_id}")
def get_recall(recall_id: str, request: Request):
    return _run(request, lambda c, x: inventory.get_recall(c, x.entity_id, recall_id), "inventory.view")


@router.post("/inventory/recalls/{recall_id}/invoices")
def recall_add_invoice(recall_id: str, request: Request, payload: Dict[str, Any] = Body(...)):
    return _run(request, lambda c, x: inventory.add_recall_invoice(c, x, recall_id, payload))


@router.post("/inventory/recalls/{recall_id}/supplier-return")
def recall_supplier_return(recall_id: str, request: Request, payload: Dict[str, Any] = Body(...)):
    return _run(request, lambda c, x: inventory.return_recall_to_supplier(c, x, recall_id, _dates(payload)))


@router.patch("/inventory/recalls/{recall_id}/items/{item_id}")
def update_recall_item(recall_id: str, item_id: str, request: Request, payload: Dict[str, Any] = Body(...)):
    return _run(request, lambda c, x: inventory.update_recall_item(c, x, recall_id, item_id, payload))


@router.post("/inventory/recalls/{recall_id}/void")
def void_recall(recall_id: str, request: Request, payload: Dict[str, Any] = Body(...)):
    return _run(request, lambda c, x: inventory.void_recall(c, x, recall_id, payload.get("reason", "")))


@router.post("/inventory/recalls/{recall_id}/close")
def close_recall(recall_id: str, request: Request, payload: Dict[str, Any] = Body(default={})):
    return _run(request, lambda c, x: inventory.close_recall(c, x, recall_id, payload.get("notes")))


# ---------------------------------------------------------------------------
# Banking
# ---------------------------------------------------------------------------

@router.get("/banking/accounts")
def bank_accounts(request: Request):
    return _run(request, lambda c, x: banking.list_accounts(c, x.entity_id), "banking.view")


@router.post("/banking/accounts")
def create_bank_account(request: Request, payload: Dict[str, Any] = Body(...)):
    return _run(request, lambda c, x: banking.create_account(c, x, payload))


@router.get("/banking/vouchers")
def list_vouchers(request: Request, kind: Optional[str] = None, bank_account_id: Optional[str] = None, search: Optional[str] = None,
                  date_from: Optional[str] = Query(None, alias="from"), date_to: Optional[str] = Query(None, alias="to"),
                  limit: int = 100, offset: int = 0):
    return _run(request, lambda c, x: banking.list_vouchers(c, x.entity_id, kind=kind, bank_account_id=bank_account_id, search=search,
                                                             date_from=_date(date_from), date_to=_date(date_to),
                                                             limit=limit, offset=offset), "banking.view")


@router.post("/banking/vouchers")
def create_voucher(request: Request, payload: Dict[str, Any] = Body(...)):
    return _run(request, lambda c, x: banking.create_voucher(c, x, _dates(payload)))


@router.get("/banking/vouchers/{voucher_id}")
def get_voucher(voucher_id: str, request: Request):
    return _run(request, lambda c, x: banking.get_voucher(c, x.entity_id, voucher_id), "banking.view")


@router.post("/banking/vouchers/{voucher_id}/void")
def void_voucher(voucher_id: str, request: Request, payload: Dict[str, Any] = Body(...)):
    return _run(request, lambda c, x: banking.void_voucher(c, x, voucher_id, payload.get("reason", "")))


@router.get("/banking/statements")
def list_statements(request: Request, bank_account_id: Optional[str] = None):
    return _run(request, lambda c, x: banking.list_statements(c, x.entity_id, bank_account_id), "banking.view")


@router.post("/banking/statements")
async def import_statement(request: Request, bank_account_id: str = Form(...), statement_date: str = Form(...),
                           closing_balance: str = Form(...), opening_balance: Optional[str] = Form(None),
                           file: UploadFile = File(...)):
    raw = await file.read()

    def fn(conn, ctx):
        lines = banking.parse_statement_csv(raw.decode("utf-8-sig", errors="replace"))
        return banking.import_statement(conn, ctx, bank_account_id, statement_date=_date(statement_date),
                                        closing_balance=closing_balance, opening_balance=opening_balance, lines=lines,
                                        source_file=file.filename)
    return _run(request, fn)


@router.get("/banking/statements/{statement_id}")
def get_statement(statement_id: str, request: Request):
    return _run(request, lambda c, x: banking.get_statement(c, x.entity_id, statement_id), "banking.view")


@router.post("/banking/statements/{statement_id}/auto-match")
def auto_match(statement_id: str, request: Request):
    def fn(conn, ctx):
        ctx.require("banking.reconcile")
        banking.auto_match(conn, ctx, statement_id)
        return banking.get_statement(conn, ctx.entity_id, statement_id)
    return _run(request, fn)


@router.post("/banking/statement-lines/{line_id}/match")
def match_line(line_id: str, request: Request, payload: Dict[str, Any] = Body(...)):
    return _run(request, lambda c, x: banking.match_line(c, x, line_id, payload.get("journal_line_id"),
                                                          payload.get("status", "MATCHED"), payload.get("note")))


@router.post("/banking/statements/{statement_id}/complete")
def complete_reconciliation(statement_id: str, request: Request):
    return _run(request, lambda c, x: banking.complete_reconciliation(c, x, statement_id))


# ---------------------------------------------------------------------------
# Fixed assets
# ---------------------------------------------------------------------------

@router.get("/assets/history")
def asset_history(request: Request, as_of: Optional[str] = None):
    return _run(request, lambda c, x: assets.asset_history(c, x.entity_id, _date(as_of) or _today()), "assets.view")


@router.get("/assets/categories")
def asset_categories(request: Request):
    return _run(request, lambda c, x: assets.list_categories(c, x.entity_id), "assets.view")


@router.post("/assets/categories")
def create_asset_category(request: Request, payload: Dict[str, Any] = Body(...)):
    return _run(request, lambda c, x: assets.create_category(c, x, payload))


@router.get("/assets")
def list_assets(request: Request):
    return _run(request, lambda c, x: assets.list_assets(c, x.entity_id), "assets.view")


@router.post("/assets")
def register_asset(request: Request, payload: Dict[str, Any] = Body(...)):
    return _run(request, lambda c, x: assets.register_asset(c, x, _dates(payload)))


@router.get("/assets/depreciation/preview")
def depreciation_preview(request: Request, period_id: str):
    return _run(request, lambda c, x: assets.preview_depreciation(c, x.entity_id, period_id), "assets.view")


@router.post("/assets/depreciation/run")
def depreciation_run(request: Request, payload: Dict[str, Any] = Body(...)):
    return _run(request, lambda c, x: assets.run_depreciation(c, x, payload["period_id"]))


@router.get("/assets/{asset_id}")
def get_asset(asset_id: str, request: Request):
    return _run(request, lambda c, x: assets.get_asset(c, x.entity_id, asset_id), "assets.view")


@router.post("/assets/{asset_id}/dispose")
def dispose_asset(asset_id: str, request: Request, payload: Dict[str, Any] = Body(...)):
    return _run(request, lambda c, x: assets.dispose_asset(c, x, asset_id, _dates(payload)))


# ---------------------------------------------------------------------------
# Budgets
# ---------------------------------------------------------------------------

@router.get("/budgets")
def list_budgets(request: Request):
    return _run(request, lambda c, x: closing.list_budgets(c, x.entity_id), "budget.view")


@router.post("/budgets")
def create_budget(request: Request, payload: Dict[str, Any] = Body(...)):
    return _run(request, lambda c, x: closing.create_budget(c, x, payload["fiscal_year_id"], payload["name"]))


@router.get("/budgets/{budget_id}")
def get_budget(budget_id: str, request: Request):
    return _run(request, lambda c, x: closing.get_budget(c, x.entity_id, budget_id), "budget.view")


@router.patch("/budgets/{budget_id}")
def update_budget(budget_id: str, request: Request, payload: Dict[str, Any] = Body(...)):
    return _run(request, lambda c, x: closing.update_budget(c, x, budget_id, payload))


@router.delete("/budgets/{budget_id}")
def delete_budget(budget_id: str, request: Request):
    return _run(request, lambda c, x: closing.delete_budget(c, x, budget_id))


@router.post("/budgets/{budget_id}/copy")
def copy_budget(budget_id: str, request: Request, payload: Dict[str, Any] = Body(default={})):
    return _run(request, lambda c, x: closing.copy_budget(c, x, budget_id, payload.get("name")))


@router.put("/budgets/{budget_id}/lines")
def set_budget_lines(budget_id: str, request: Request, payload: Dict[str, Any] = Body(...)):
    return _run(request, lambda c, x: closing.set_budget_lines(c, x, budget_id, payload.get("lines") or []))


@router.post("/budgets/{budget_id}/approve")
def approve_budget(budget_id: str, request: Request):
    return _run(request, lambda c, x: closing.approve_budget(c, x, budget_id))


# ---------------------------------------------------------------------------
# Controls, audit, integrations
# ---------------------------------------------------------------------------

@router.get("/controls/run")
def run_controls(request: Request, as_of: Optional[str] = None):
    return _run(request, lambda c, x: controls.run_and_store(c, x, _date(as_of) or _today()), "controls.view")


@router.get("/data-exceptions")
def data_exception_list(request: Request, status: Optional[str] = None, kind: Optional[str] = None):
    return _run(request, lambda c, x: {"items": data_exceptions.list_exceptions(c, x.entity_id, status, kind),
                                       **data_exceptions.summary(c, x.entity_id)}, "controls.view")


@router.post("/data-exceptions/refresh")
def data_exception_refresh(request: Request):
    return _run(request, lambda c, x: data_exceptions.refresh(c, x), "controls.view")


@router.get("/data-exceptions/{exc_id}")
def data_exception_get(request: Request, exc_id: str):
    return _run(request, lambda c, x: data_exceptions.get(c, x.entity_id, exc_id), "controls.view")


@router.post("/data-exceptions/{exc_id}/{action}")
def data_exception_resolve(request: Request, exc_id: str, action: str, payload: Dict[str, Any] = Body(default={})):
    return _run(request, lambda c, x: data_exceptions.resolve(c, x, exc_id, action, _dates(payload)))


@router.get("/controls/history")
def control_history(request: Request):
    return _run(request, lambda c, x: q(c, """SELECT id, as_of, fail_count, run_by, run_at FROM fin_control_runs
                                               WHERE legal_entity_id=%s ORDER BY run_at DESC LIMIT 30""", (x.entity_id,)),
                "controls.view")


@router.get("/validation-events")
def validation_events(request: Request, status: Optional[str] = None):
    def fn(conn, ctx):
        sf = " AND status=%s" if status else ""
        return q(conn, f"SELECT * FROM fin_validation_events WHERE legal_entity_id=%s {sf} ORDER BY created_at DESC LIMIT 200",
                 [ctx.entity_id] + ([status] if status else []))
    return _run(request, fn, "controls.view")


@router.get("/audit")
def audit_trail(request: Request, entity_type: Optional[str] = None, entity_id: Optional[str] = None,
                actor: Optional[str] = None, action: Optional[str] = None, search: Optional[str] = None,
                date_from: Optional[str] = Query(None, alias="from"), date_to: Optional[str] = Query(None, alias="to"),
                limit: int = 200, offset: int = 0):
    def fn(conn, ctx):
        where, p = ["legal_entity_id=%s"], [ctx.entity_id]
        for col, v in (("entity_type", entity_type), ("entity_id", entity_id), ("action", action)):
            if v:
                where.append(f"{col}=%s")
                p.append(v)
        if actor:
            where.append("(actor_id ILIKE %s OR actor_name ILIKE %s)")
            p += [f"%{actor}%"] * 2
        if search:
            where.append("(entity_ref ILIKE %s OR reason ILIKE %s OR action ILIKE %s)")
            p += [f"%{search}%"] * 3
        if date_from:
            where.append("created_at >= %s")
            p.append(_date(date_from))
        if date_to:
            where.append("created_at < %s::date + 1")
            p.append(_date(date_to))
        w = " AND ".join(where)
        total = q1(conn, f"SELECT COUNT(*) n FROM fin_audit_events WHERE {w}", p)["n"]
        rows = q(conn, f"SELECT * FROM fin_audit_events WHERE {w} ORDER BY id DESC LIMIT %s OFFSET %s", p + [limit, offset])
        return {"items": rows, "total": total}
    return _run(request, fn, "controls.view")


@router.get("/integrations/source-postings")
def source_postings(request: Request, status: Optional[str] = None):
    def fn(conn, ctx):
        sf = " AND status=%s" if status else ""
        return q(conn, f"""SELECT * FROM fin_source_postings WHERE legal_entity_id=%s {sf} ORDER BY updated_at DESC LIMIT 200""",
                 [ctx.entity_id] + ([status] if status else []))
    return _run(request, fn, "accounting.view")


@router.post("/integrations/frontdesk/{frontdesk_invoice_id}/post")
def retry_frontdesk(frontdesk_invoice_id: str, request: Request):
    _run(request, lambda c, x: x.require("sales.invoice.post"))
    return integrations.post_frontdesk_invoice(frontdesk_invoice_id, actor=request.state.user.get("sub", "user"))


@router.get("/integrations/frontdesk/unposted")
def frontdesk_unposted(request: Request):
    return _run(request, lambda c, x: integrations.unposted_frontdesk(c, x.entity_id), "accounting.view")


@router.post("/integrations/frontdesk/{frontdesk_invoice_id}/exclude")
def exclude_frontdesk(frontdesk_invoice_id: str, request: Request, payload: Dict[str, Any] = Body(...)):
    return _run(request, lambda c, x: integrations.exclude_frontdesk_invoice(c, x, frontdesk_invoice_id, payload.get("reason", "")))


@router.post("/integrations/frontdesk/backfill")
def backfill_frontdesk(request: Request, payload: Dict[str, Any] = Body(...)):
    _run(request, lambda c, x: x.require("sales.invoice.post"))
    return plain(integrations.backfill_frontdesk(_date(payload["from"]), _date(payload["to"]),
                                                 request.state.user.get("sub", "user")))


# ---------------------------------------------------------------------------
# Migration (Sage 50 -> ACE Books)
# ---------------------------------------------------------------------------

@router.get("/migration/batches")
def migration_batches(request: Request):
    return _run(request, lambda c, x: migration.list_batches(c, x.entity_id), "migration.stage")


@router.post("/migration/stage")
async def migration_stage(request: Request, kind: str = Form(...), as_of: Optional[str] = Form(None),
                          file: UploadFile = File(...)):
    raw = await file.read()
    return _run(request, lambda c, x: migration.stage(c, x, kind, file.filename or "upload", raw, _date(as_of)))


@router.get("/migration/batches/{batch_id}")
def migration_batch(batch_id: str, request: Request):
    return _run(request, lambda c, x: migration.get_batch(c, x.entity_id, batch_id), "migration.stage")


@router.post("/migration/batches/{batch_id}/load")
def migration_load(batch_id: str, request: Request):
    return _run(request, lambda c, x: migration.load(c, x, batch_id))


@router.post("/migration/batches/{batch_id}/discard")
def migration_discard(batch_id: str, request: Request):
    return _run(request, lambda c, x: migration.discard(c, x, batch_id))


@router.post("/migration/opening-dates/refresh")
def migration_refresh_dates(request: Request):
    return _run(request, lambda c, x: (x.require("migration.load"), migration.refresh_opening_dates(c, x))[1])


@router.post("/migration/opening-batches")
def migration_opening_batches(request: Request):
    return _run(request, lambda c, x: sage_history.assign_opening_batches(c, x))


@router.get("/sage-history/bills/{number:path}")
def sage_bill(number: str, request: Request, supplier_id: Optional[str] = None):
    return _run(request, lambda c, x: ledger_reports.sage_bill(c, x.entity_id, number, supplier_id), "payables.view")


@router.get("/sage-history/invoices/{number:path}")
def sage_invoice(number: str, request: Request):
    def fn(conn, ctx):
        out = ledger_reports.sage_invoice(conn, ctx.entity_id, number)
        out["recalls"] = inventory.recalls_for_invoice(conn, ctx.entity_id, invoice_number=number)
        return out
    return _run(request, fn, "receivables.view")


@router.post("/migration/products/sync")
def migration_products(request: Request):
    return _run(request, lambda c, x: migration.sync_products(c, x))
