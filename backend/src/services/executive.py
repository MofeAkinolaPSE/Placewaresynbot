"""Executive overview: the state of the company on one page, read from the modules that own it.

  Finance      ACE Books - P&L year to date, cash by bank account, receivables and
               payables with ageing, working capital.
  Sales        ACE Books sales lines - monthly trend with margin and last year, top
               customers and products, concentration.
  Customers    CRM directory and pipeline (services/crm_hub.py).
  Stock        ACE Books stock value, cover, expiry; stock orders (services/stock_orders.py).
  Quality      recalls, deviations, audits, compliance score (services/quality_hub.py).
  People       headcount, on the clock, hours, open work (services/hr_hub.py, staff_workspace.py).

Nothing is stored or estimated here. Sales windows are measured to the last day the
books hold sales (data_as_of), and the page says so, so a gap in loaded data is never
mistaken for a collapse in trade. Each figure carries the link to the page that owns it.
"""
from __future__ import annotations

import datetime as dt
import logging
import time
from typing import Any, Callable, Dict, List, Optional

from src.fin.db import q, q1, tx

log = logging.getLogger(__name__)
TTL = 300


def _f(v: Any) -> float:
    return float(v or 0)


def _safe(name: str, fn: Callable[[], Any], default: Any = None) -> Any:
    """One module being unavailable must not blank the whole page."""
    try:
        return fn()
    except Exception as exc:
        log.warning("executive: %s unavailable: %s", name, exc)
        return default


def _pct(a: float, b: float) -> Optional[float]:
    return round((a - b) / b * 100, 1) if b else None


def _add_years(d: dt.date, n: int) -> dt.date:
    try:
        return d.replace(year=d.year + n)
    except ValueError:
        return d.replace(year=d.year + n, day=28)


# ---------------------------------------------------------------------------

def _finance() -> Dict[str, Any]:
    from src.fin import reports
    from src.fin.context import resolve_entity
    from src.fin.readmodel import ap_rows, ar_rows, cutover, monthly_pl
    today = dt.date.today()
    with tx() as conn:
        e = resolve_entity(conn, None)
        fy0 = reports._fy_start(conn, e, today)
        inc = reports.income_statement(conn, e, fy0, today)
        banks = q(conn, """SELECT account_code AS code, account_name AS name, SUM(debit-credit) AS balance
                           FROM fin_v_general_ledger WHERE legal_entity_id=%s AND subtype='CASH'
                           GROUP BY 1,2 HAVING ABS(SUM(debit-credit)) > 0.005 ORDER BY 3 DESC""", (e,))
        last_post = q1(conn, """SELECT MAX(journal_date) AS d FROM fin_journals
                                WHERE legal_entity_id=%s AND journal_type NOT IN ('OPENING','CLOSING') AND status='POSTED'""", (e,))
        periods = q(conn, """SELECT status, COUNT(*) AS n FROM fin_periods WHERE legal_entity_id=%s GROUP BY 1""", (e,))
        controls = q1(conn, """SELECT
              (SELECT COUNT(*) FROM fin_bank_accounts WHERE legal_entity_id=%(e)s) AS bank_accounts,
              (SELECT COUNT(DISTINCT bank_account_id) FROM fin_reconciliations WHERE legal_entity_id=%(e)s AND status='COMPLETED') AS reconciled,
              (SELECT MAX(as_of) FROM fin_reconciliations WHERE legal_entity_id=%(e)s AND status='COMPLETED') AS last_reconciled,
              (SELECT COUNT(*) FROM fin_sales_invoices WHERE legal_entity_id=%(e)s AND status='DRAFT') AS draft_invoices,
              (SELECT COUNT(*) FROM fin_supplier_bills WHERE legal_entity_id=%(e)s AND status='DRAFT') AS draft_bills,
              (SELECT COUNT(*) FROM fin_journals WHERE legal_entity_id=%(e)s AND status='DRAFT') AS draft_journals,
              (SELECT COUNT(*) FROM fin_periods WHERE legal_entity_id=%(e)s AND status='OPEN' AND end_date < %(t)s) AS past_periods_open""",
                      {"e": e, "t": today})
        credit = q1(conn, """WITH bal AS (SELECT customer_pk, SUM(balance) AS b FROM v_ar_open GROUP BY 1)
                             SELECT COUNT(*) AS n, COALESCE(SUM(b.b - c.credit_limit),0) AS excess
                             FROM bal b JOIN customers c ON c.id=b.customer_pk
                             WHERE c.credit_limit > 0 AND b.b > c.credit_limit""")
    cut = cutover()
    # While trading after the cut-over is not yet loaded, no receipt or payment after it exists in the
    # books, so ageing to today would show every balance as long overdue. Age as at the last loaded day.
    stale = bool(cut and (not last_post["d"] or last_post["d"] < cut) and today >= cut)
    age_on = cut - dt.timedelta(days=1) if stale else today
    ar = {"0_30": 0.0, "31_60": 0.0, "61_90": 0.0, "91_plus": 0.0}
    for r in ar_rows(age_on):
        ar[r["bucket"]] += r["balance"]
    ar = {k: round(v, 2) for k, v in ar.items()}
    ar_total = sum(ar.values())
    ap = ap_rows(age_on)
    ap_owed = sum(r["balance"] for r in ap if r["balance"] > 0)
    ap_overdue = sum(r["balance"] for r in ap if r["balance"] > 0 and r["due_date"] and r["due_date"] < age_on)
    ap_due_30 = sum(r["balance"] for r in ap if r["balance"] > 0 and r["due_date"] and age_on <= r["due_date"] <= age_on + dt.timedelta(days=30))
    cash = sum(_f(b["balance"]) for b in banks)
    status = {p["status"]: int(p["n"]) for p in periods}
    return {
        "fy_start": fy0, "to": today,
        "revenue_ytd": _f(inc["revenue"]), "cost_of_sales_ytd": _f(inc["cost_of_sales"]), "gross_profit_ytd": _f(inc["gross_profit"]),
        "gross_margin_pct": _f(inc["gross_margin_pct"]) if inc["gross_margin_pct"] is not None else None,
        "operating_profit_ytd": _f(inc["operating_profit"]), "net_profit_ytd": _f(inc["net_profit"]),
        "net_margin_pct": round(_f(inc["net_profit"]) / _f(inc["revenue"]) * 100, 1) if _f(inc["revenue"]) else None,
        "cash": round(cash, 2), "banks": [{"code": b["code"], "name": b["name"], "balance": _f(b["balance"])} for b in banks],
        "receivables": {"total": round(ar_total, 2), "buckets": ar, "over_90": ar.get("91_plus", 0.0),
                        "over_90_pct": round(ar.get("91_plus", 0.0) / ar_total * 100, 1) if ar_total else None},
        "payables": {"total": round(ap_owed, 2), "overdue": round(ap_overdue, 2), "due_30": round(ap_due_30, 2)},
        "credit_breaches": {"customers": int(credit["n"] or 0), "excess": _f(credit["excess"])},
        "books": {"cutover": cut, "last_posting": last_post["d"], "periods": status, "stale": stale,
                  "missing_months": ((today.year - cut.year) * 12 + today.month - cut.month + 1) if stale else 0},
        "aged_on": age_on,
        "controls": {k: (v if v is None or isinstance(v, dt.date) else int(v)) for k, v in controls.items()},
        "monthly_pl": _safe("monthly P&L", lambda: [m for m in monthly_pl() if m["period"] >= f"{fy0:%Y-%m}"], []),
    }


def _sales() -> Dict[str, Any]:
    from src.services.stock_orders import FAMILY_SQL
    with tx() as conn:
        as_of = q1(conn, "SELECT MAX(invoice_date) AS d FROM v_sales_lines")["d"]
        if not as_of:
            return {"as_of": None}
        y0 = as_of.replace(month=1, day=1)
        ly_as_of = _add_years(as_of, -1)
        m0 = as_of.replace(day=1)
        agg = q1(conn, """SELECT
              SUM(amount) FILTER (WHERE invoice_date BETWEEN %(y0)s AND %(a)s) AS ytd,
              SUM(gross_profit) FILTER (WHERE invoice_date BETWEEN %(y0)s AND %(a)s) AS ytd_gp,
              SUM(amount) FILTER (WHERE invoice_date BETWEEN %(ly0)s AND %(lya)s) AS ly_ytd,
              SUM(amount) FILTER (WHERE invoice_date > %(a)s::date - 90) AS last90,
              SUM(cost) FILTER (WHERE invoice_date > %(a)s::date - 90) AS cost90,
              SUM(amount) FILTER (WHERE invoice_date > %(a)s::date - 180 AND invoice_date <= %(a)s::date - 90) AS prev90,
              SUM(amount) FILTER (WHERE invoice_date > %(a)s::date - 365) AS last365,
              SUM(gross_profit) FILTER (WHERE invoice_date > %(a)s::date - 365) AS gp365,
              COUNT(DISTINCT customer_pk) FILTER (WHERE invoice_date > %(a)s::date - 365) AS buyers365,
              COUNT(DISTINCT invoice_number) FILTER (WHERE invoice_date > %(a)s::date - 365) AS invoices365
            FROM v_sales_lines""", {"y0": y0, "a": as_of, "ly0": _add_years(y0, -1), "lya": ly_as_of})
        monthly = q(conn, """SELECT to_char(invoice_date,'YYYY-MM') AS period, SUM(amount) AS sales, SUM(gross_profit) AS gp,
                                    COUNT(DISTINCT customer_pk) AS customers
                             FROM v_sales_lines WHERE invoice_date >= %s GROUP BY 1 ORDER BY 1""",
                    (_add_years(m0, -2),))
        top_c = q(conn, """SELECT customer_pk AS id, MAX(customer_name) AS name, SUM(amount) AS sales, SUM(gross_profit) AS gp
                           FROM v_sales_lines WHERE invoice_date > %s::date - 365 GROUP BY 1 ORDER BY 3 DESC LIMIT 10""", (as_of,))
        top_p = q(conn, f"""SELECT {FAMILY_SQL.format(name="fp.name", sku="s.sku")} AS product, SUM(s.amount) AS sales,
                                   SUM(s.gross_profit) AS gp, SUM(s.quantity) AS units
                            FROM v_sales_lines s LEFT JOIN fin_products fp ON fp.sku=s.sku
                            WHERE s.invoice_date > %s::date - 365 GROUP BY 1 ORDER BY 2 DESC LIMIT 10""", (as_of,))
    by_m = {m["period"]: m for m in monthly}
    trend = []
    for m in monthly:
        if m["period"] < f"{_add_years(m0, -1):%Y-%m}":
            continue
        ly = by_m.get(f"{int(m['period'][:4]) - 1}{m['period'][4:]}")
        trend.append({"period": m["period"], "sales": _f(m["sales"]), "gp": _f(m["gp"]),
                      "margin_pct": round(_f(m["gp"]) / _f(m["sales"]) * 100, 1) if _f(m["sales"]) else None,
                      "customers": m["customers"], "last_year": _f(ly["sales"]) if ly else None})
    last365 = _f(agg["last365"])
    top10 = sum(_f(c["sales"]) for c in top_c)
    this_m = by_m.get(f"{m0:%Y-%m}")
    prev_m = by_m.get(f"{(m0 - dt.timedelta(days=1)):%Y-%m}")
    ly_m = by_m.get(f"{_add_years(m0, -1):%Y-%m}")
    return {
        "as_of": as_of,
        "ytd": _f(agg["ytd"]), "ytd_gp": _f(agg["ytd_gp"]), "ly_ytd": _f(agg["ly_ytd"]), "ytd_growth_pct": _pct(_f(agg["ytd"]), _f(agg["ly_ytd"])),
        "last90": _f(agg["last90"]), "prev90": _f(agg["prev90"]), "q_growth_pct": _pct(_f(agg["last90"]), _f(agg["prev90"])),
        "cost90": _f(agg["cost90"]),
        "last365": last365, "margin_365_pct": round(_f(agg["gp365"]) / last365 * 100, 1) if last365 else None,
        "buyers_365": agg["buyers365"], "invoices_365": agg["invoices365"],
        "avg_invoice": round(last365 / agg["invoices365"], 2) if agg["invoices365"] else None,
        "month": {"period": f"{m0:%Y-%m}", "sales": _f(this_m["sales"]) if this_m else 0.0,
                  "prev": _f(prev_m["sales"]) if prev_m else None, "last_year": _f(ly_m["sales"]) if ly_m else None,
                  "partial_to": as_of},
        "trend": trend,
        "top_customers": [{"id": c["id"], "name": c["name"], "sales": _f(c["sales"]), "share_pct": round(_f(c["sales"]) / last365 * 100, 1) if last365 else None,
                           "margin_pct": round(_f(c["gp"]) / _f(c["sales"]) * 100, 1) if _f(c["sales"]) else None} for c in top_c],
        "top10_share_pct": round(top10 / last365 * 100, 1) if last365 else None,
        "top_products": [{"product": p["product"], "sales": _f(p["sales"]), "units": _f(p["units"]),
                          "margin_pct": round(_f(p["gp"]) / _f(p["sales"]) * 100, 1) if _f(p["sales"]) else None} for p in top_p],
    }


def _customers() -> Dict[str, Any]:
    from src.services import crm_hub
    ov = crm_hub.overview()
    d = _safe("crm directory", crm_hub.customer_directory, {}) or {}
    # slipping = buying less than last year or late for their usual reorder (debt alone is a finance matter,
    # and is inflated while receipts after the cut-over are not loaded)
    slipping = [c for c in d.get("customers") or []
                if any(not r.startswith("owes money") for r in c.get("risk_reasons") or [])]
    return {
        "counts": d.get("counts") or {}, "total": d.get("total"), "at_risk": len(slipping),
        "at_risk_sales": round(sum(_f(c.get("sales_12m")) for c in slipping), 2),
        "at_risk_top": [{"id": c["id"], "name": c["name"], "sales_12m": _f(c.get("sales_12m")), "why": "; ".join(
            r for r in c["risk_reasons"] if not r.startswith("owes money"))} for c in sorted(slipping, key=lambda c: -_f(c.get("sales_12m")))[:6]],
        "pipeline_value": ov.get("open_pipeline_value"), "open_deals": ov.get("open_deals"), "win_rate_90d": ov.get("win_rate_90d"),
        "won_recent": ov.get("recently_won") or [], "new_leads_7d": ov.get("new_leads_7d"),
        "reminders_overdue": (ov.get("reminders") or {}).get("overdue"),
    }


def _stock(sales: Dict[str, Any]) -> Dict[str, Any]:
    from src.services import books_analytics, stock_orders
    st = books_analytics.stock_totals()
    so = _safe("stock orders", stock_orders.summary, {}) or {}
    cost90 = _f(sales.get("cost90"))
    cover = round(_f(st["value"]) / (cost90 / 90)) if cost90 else None
    return {"value": round(_f(st["value"]), 2), "units": st["units"], "skus_in_stock": st["skus_in_stock"], "cover_days": cover,
            "reorder_now": so.get("reorder_now"), "out_of_stock": so.get("out_of_stock"), "to_order_value": so.get("to_order_value"),
            "open_orders": (so.get("requested") or 0) + (so.get("approved") or 0) + (so.get("ordered") or 0),
            "ordered_value": so.get("ordered_value"), "overdue_orders": so.get("overdue_orders"),
            "expiry_risk_value": so.get("expiry_risk_value"), "purchases_12m": so.get("purchases_12m")}


def _quality() -> Dict[str, Any]:
    from src.services import quality_hub
    o = quality_hub.overview()
    exp = o.get("expiry") or {}
    return {"compliance_score": o.get("compliance_score"), "recalls": o.get("recalls"), "deviations": o.get("deviations"),
            "audits": o.get("audits"), "maintenance": o.get("maintenance"), "batches": o.get("batches"),
            "expired_value": _f((exp.get("expired") or {}).get("value")), "expired_products": (exp.get("expired") or {}).get("products"),
            "expiring_90_value": _f((exp.get("critical") or {}).get("value")) + _f((exp.get("soon") or {}).get("value")),
            "held_value": (o.get("stock") or {}).get("held_value")}


def _people() -> Dict[str, Any]:
    from src.services import hr_hub
    from src.services.staff_workspace import OPEN_STATUSES, now
    h = hr_hub.overview()
    with tx() as conn:
        w = q1(conn, """SELECT COUNT(*) FILTER (WHERE status IN %s AND kind<>'note') AS open,
                               COUNT(*) FILTER (WHERE status IN %s AND kind<>'note' AND COALESCE(due_date, reminder_at) < %s) AS overdue,
                               COUNT(*) FILTER (WHERE status='completed' AND completed_at > now() - interval '7 days') AS done_7d
                        FROM placeware_tasks""", (OPEN_STATUSES, OPEN_STATUSES, now()))
        r = q1(conn, """SELECT COUNT(*) FILTER (WHERE status IN ('sent','acknowledged','in_progress')) AS open,
                               COUNT(*) FILTER (WHERE status IN ('sent','acknowledged','in_progress') AND due_at < now()) AS overdue
                        FROM staff_requests""")
    return {"headcount": h["headcount"], "online": len(h["online"]), "on_clock": len(h["on_clock"]),
            "hours_week": h["hours_total"], "people_with_hours": h["people_with_hours"],
            "pending_timesheets": h["pending_approval"]["entries"], "long_clocks": len(h["long_clocks"]),
            "open_tasks": int(w["open"] or 0), "overdue_tasks": int(w["overdue"] or 0), "done_7d": int(w["done_7d"] or 0),
            "open_requests": int(r["open"] or 0), "overdue_requests": int(r["overdue"] or 0)}


def _attention(fin, sales, cust, stock, qual, ppl) -> List[Dict[str, Any]]:
    """Exceptions an owner should know about, most serious first. Each links to where it is dealt with."""
    out: List[Dict[str, Any]] = []

    def add(level: str, title: str, detail: str, link: str) -> None:
        out.append({"level": level, "title": title, "detail": detail, "link": link})

    money = lambda v: f"₦{_f(v) / 1e6:,.1f}M" if abs(_f(v)) >= 1e6 else f"₦{_f(v):,.0f}"
    if fin:
        b = fin["books"]
        on = f"{fin['aged_on']:%d %b}"
        if b.get("stale"):
            n = b["missing_months"]
            first = b["cutover"]
            last_m = dt.date.today()
            add("critical", f"{n} month{'s' if n != 1 else ''} of trading not yet in the books ({first:%B}–{last_m:%B})",
                f"Nothing has been entered since the cut-over on {first:%d %b %Y}. Sales, cash, receivables and payables on this page "
                f"are as at {on} until the Sage import for those months is loaded.", "/finance/sage-import")
        r = fin["receivables"]
        if r["over_90_pct"] and r["over_90_pct"] >= 20:
            add("critical" if r["over_90_pct"] >= 40 else "action", f"{r['over_90_pct']}% of receivables were over 90 days at {on}",
                f"{money(r['over_90'])} of {money(r['total'])} owed by customers.", "/finance/ar")
        if fin["payables"]["overdue"] > 0:
            add("action", f"Supplier invoices past due at {on}: {money(fin['payables']['overdue'])}",
                f"{money(fin['payables']['due_30'])} more fell due in the following 30 days; cash in the books {money(fin['cash'])}.", "/finance/books/purchases")
        c = fin["controls"]
        holding = len(fin["banks"])
        if holding and (c.get("reconciled") or 0) < holding:
            add("action", f"{holding - (c.get('reconciled') or 0)} of {holding} bank and cash accounts holding money are not reconciled in ACE Books",
                "Reconcile each to its bank statement so the cash figure can be relied on.", "/finance/books/banking")
        if c.get("past_periods_open"):
            add("info", f"{c['past_periods_open']} past months still open in the books",
                "Close them once the accountant has signed off, so they cannot be changed.", "/finance/books/close")
        drafts = (c.get("draft_invoices") or 0) + (c.get("draft_bills") or 0) + (c.get("draft_journals") or 0)
        if drafts:
            add("info", f"{drafts} documents in draft, not yet posted", "Drafts do not count in the figures until posted.", "/finance/books")
        cb = fin["credit_breaches"]
        if cb["customers"]:
            add("action", f"{cb['customers']} customers are over their credit limit",
                f"{money(cb['excess'])} above limits. Limits from Sage look unreliable - review them, as ACE Books enforces them when invoicing.", "/crm/customers")
    if qual:
        if qual["expired_value"]:
            add("critical", f"Expired stock worth {money(qual['expired_value'])} ({qual['expired_products']} products)",
                "Write off or return to supplier; it is excluded from sale automatically.", "/quality-control?tab=expiry")
        rc = qual.get("recalls") or {}
        if rc.get("open"):
            add("critical", f"{rc['open']} recall{'s' if rc['open'] > 1 else ''} open",
                f"{rc.get('customers_to_contact', 0)} customers still to contact.", "/quality-control?tab=recalls")
        dv = qual.get("deviations") or {}
        if dv.get("overdue"):
            add("action", f"{dv['overdue']} deviation{'s' if dv['overdue'] > 1 else ''} past target close date", "", "/compliance?tab=deviations")
        if (qual.get("audits") or {}).get("overdue"):
            add("action", f"{qual['audits']['overdue']} audit(s) overdue", "", "/compliance?tab=audits")
    if stock:
        if stock.get("overdue_orders"):
            add("action", f"{stock['overdue_orders']} supplier deliveries overdue", "", "/operations/purchase-orders?tab=orders")
        if stock.get("out_of_stock"):
            add("action", f"{stock['out_of_stock']} products out of stock", f"{stock.get('reorder_now') or 0} need reordering now.",
                "/operations/purchase-orders")
    if cust and cust.get("at_risk"):
        add("action" if cust["at_risk_sales"] >= 1e8 else "info", f"{cust['at_risk']} regular customers are slipping",
            f"Buying less than last year or late for their usual reorder; together {money(cust['at_risk_sales'])} of sales in the last 12 months.",
            "/crm/customers")
    if sales and sales.get("top10_share_pct") and sales["top10_share_pct"] >= 50:
        add("info", f"Top 10 customers are {sales['top10_share_pct']}% of sales", "High concentration - losing one would be felt.", "/crm/customers")
    if ppl:
        if ppl["overdue_tasks"]:
            add("info", f"{ppl['overdue_tasks']} team tasks overdue", f"{ppl['open_tasks']} open across the team.", "/workspace?tab=team")
        if ppl["pending_timesheets"]:
            add("info", f"{ppl['pending_timesheets']} timesheet entries awaiting HR approval", "", "/hr?tab=timesheets")
    rank = {"critical": 0, "action": 1, "info": 2}
    return sorted(out, key=lambda a: rank[a["level"]])


def overview(refresh: bool = False) -> Dict[str, Any]:
    # Shared by every worker and built once when several people open it together; any save
    # drops it (src/utils/shared_response.py). refresh=True always rebuilds.
    if refresh:
        return _build_overview()
    from src.utils.shared_response import shared_response
    return shared_response("executive:overview", TTL, _build_overview)


def _build_overview() -> Dict[str, Any]:
    t0 = time.monotonic()
    fin = _safe("finance", _finance)
    sales = _safe("sales", _sales, {}) or {}
    cust = _safe("customers", _customers)
    stock = _safe("stock", lambda: _stock(sales))
    qual = _safe("quality", _quality)
    ppl = _safe("people", _people)
    wc = None
    if fin and stock:
        wc = round(fin["cash"] + fin["receivables"]["total"] + stock["value"] - fin["payables"]["total"], 2)
    out = {
        "generated_at": dt.datetime.now(dt.timezone.utc), "build_seconds": round(time.monotonic() - t0, 2),
        "data_as_of": sales.get("as_of"),
        "finance": fin, "sales": sales, "customers": cust, "stock": stock, "quality": qual, "people": ppl,
        "working_capital": wc,
        "attention": _attention(fin, sales, cust, stock, qual, ppl),
    }
    return out
