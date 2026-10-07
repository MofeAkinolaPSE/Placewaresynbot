"""ACE's live-data tools over the rebuilt modules (ACE Books, Operations, Inventory &
Quality, CRM, HR, My Workspace). Each returns a small, already-summarised result so ACE
answers from facts, not from page directions (backend/docs/ACe guide/02: tools return
structured data, never raw dumps).

Entity tools (customer, supplier, product) find the name inside the user's question and
return {"matched": False} when nothing matches, so ACE says it didn't find it.
"""
from __future__ import annotations

import datetime as dt
import re
from typing import Any, Dict, List, Optional

from src.fin.db import q, q1, tx


def _f(v: Any) -> float:
    return float(v or 0)


def _words(s: str) -> List[str]:
    return [w for w in re.sub(r"[^a-z0-9 ]", " ", (s or "").lower()).split() if w]


_STOP = {"the", "ltd", "limited", "nig", "nigeria", "plc", "and", "of", "co", "company", "pharmacy", "hospital", "clinic", "enterprises"}


def _key(n: str) -> List[str]:
    return [w for w in _words(n) if w not in _STOP and len(w) > 2]


def _resolve(question: str, names: List[str]) -> tuple[Optional[str], List[str]]:
    """(the one name the question means, other candidates when it could mean several).
    Whole name in the question wins; then a name whose distinctive words are all there; if
    only part of a name matches, or several match equally, nothing is picked - ACE asks."""
    qw = " " + " ".join(_words(question)) + " "
    best, best_len = None, 0
    for n in names:
        nw = _words(n)
        phrase = " " + " ".join(nw) + " "
        if nw and phrase in qw and len(phrase) > best_len:
            best, best_len = n, len(phrase)
    if best:
        return best, []
    full = [n for n in names if _key(n) and all(f" {w} " in qw for w in _key(n))]
    if full:
        top = max(sum(len(w) for w in _key(n)) for n in full)
        tops = sorted({n for n in full if sum(len(w) for w in _key(n)) == top})
        return (tops[0], []) if len(tops) == 1 else (None, tops[:6])
    part = sorted({n for n in names if len(_key(n)) > 1 and sum(f" {w} " in qw for w in _key(n)) >= 2}
                  | {n for n in names if len(_key(n)) > 1 and any(len(w) > 5 and f" {w} " in qw for w in _key(n))})
    # exactly one partial match is the one reasonable reading: use it (the result says so)
    return (part[0], ["(matched on part of the name)"]) if len(part) == 1 else (None, part[:6])


def _best_match(question: str, names: List[str]) -> Optional[str]:
    return _resolve(question, names)[0]


def _partial(extra: List[str]) -> Dict[str, Any]:
    return {"matched_on_part_of_name": True} if extra else {}


def _unresolved(kind: str, candidates: List[str]) -> Dict[str, Any]:
    if candidates:
        return {"matched": False, "ambiguous": True, "candidates": candidates,
                "note": f"The question could mean more than one {kind}; ask which one."}
    return {"matched": False, "note": f"No {kind} named in the question was found."}


# ---------------------------------------------------------------------------

def executive_overview() -> Dict[str, Any]:
    from src.services.executive import overview
    o = overview()
    f, s, st, ql, p, c = (o.get(k) or {} for k in ("finance", "sales", "stock", "quality", "people", "customers"))
    return {
        "books_complete_to": str(f.get("aged_on")), "note": "Trading after the 1 Jul 2026 cut-over is not yet loaded" if (f.get("books") or {}).get("stale") else "",
        "revenue_ytd": f.get("revenue_ytd"), "gross_profit_ytd": f.get("gross_profit_ytd"), "gross_margin_pct": f.get("gross_margin_pct"),
        "net_profit_ytd": f.get("net_profit_ytd"), "cash": f.get("cash"),
        "receivables": (f.get("receivables") or {}).get("total"), "receivables_over_90": (f.get("receivables") or {}).get("over_90"),
        "payables": (f.get("payables") or {}).get("total"), "payables_overdue": (f.get("payables") or {}).get("overdue"),
        "stock_value": st.get("value"), "stock_cover_days": st.get("cover_days"), "out_of_stock": st.get("out_of_stock"),
        "sales_last_12m": s.get("last365"), "sales_ytd_growth_pct": s.get("ytd_growth_pct"), "top10_customer_share_pct": s.get("top10_share_pct"),
        "compliance_score": ql.get("compliance_score"), "expired_stock_value": ql.get("expired_value"),
        "slipping_customers": c.get("at_risk"), "open_pipeline": c.get("pipeline_value"),
        "headcount": p.get("headcount"), "on_clock_now": p.get("on_clock"),
        "needs_attention": [a["title"] for a in o.get("attention") or []][:8],
    }


def cash_position() -> Dict[str, Any]:
    from src.services.executive import _finance
    f = _finance()
    return {"total_cash": f["cash"], "by_account": [{"account": b["name"], "balance": b["balance"]} for b in f["banks"]],
            "reconciled_accounts": (f.get("controls") or {}).get("reconciled"), "last_reconciliation": str((f.get("controls") or {}).get("last_reconciled"))}


def customer_account(question: str) -> Dict[str, Any]:
    from src.services import crm_hub
    d = crm_hub.customer_directory()
    names = [c["name"] for c in d.get("customers") or []]
    name, extra = _resolve(question, names)
    if not name:
        return _unresolved("customer", extra)
    c = next(x for x in d["customers"] if x["name"] == name)
    same = [x for x in d["customers"] if x["name"].strip().lower() == name.strip().lower()]
    prof = crm_hub.customer_profile(int(c["id"]))
    cu = prof.get("customer") or {}
    return {
        "matched": True, **_partial(extra), "customer": name, "duplicates_with_same_name": len(same) - 1, "segment": c.get("segment"),
        "sales_last_12m": c.get("sales_12m"), "sales_previous_12m": c.get("sales_prev_12m"), "trend_pct": c.get("trend_pct"),
        "margin_pct": c.get("margin_pct"), "last_order": str(c.get("last_order")), "days_since_order": c.get("days_since_order"),
        "usual_gap_days": c.get("avg_gap_days"), "next_order_due_in_days": c.get("reorder_due_in"),
        "balance_owed": c.get("balance"), "past_due": c.get("overdue"), "oldest_overdue_days": c.get("max_days"),
        "credit_limit": cu.get("credit_limit"), "payment_terms_days": cu.get("payment_terms_days"), "account_owner": cu.get("owner_name"),
        "risk": c.get("risk_reasons"),
        "top_products": [{"product": p.get("name") or p.get("sku"), "sales": p.get("sales"), "last_bought": str(p.get("last_bought"))}
                         for p in (prof.get("products") or [])[:6]],
        "recent_invoices": [{"invoice": i.get("invoice_id"), "date": str(i.get("date")), "amount": i.get("amount"), "balance": i.get("balance")}
                            for i in (prof.get("invoices") or [])[:6]],
        "open_deals": [{"deal": x.get("company_name"), "stage": x.get("stage"), "value": x.get("expected_value")}
                       for x in prof.get("deals") or [] if x.get("stage") not in ("won", "lost")],
        "sales_data_as_of": str(prof.get("as_of")),
    }


def supplier_account(question: str) -> Dict[str, Any]:
    from src.services.stock_orders import supplier_directory
    d = supplier_directory()
    rows = d.get("suppliers") or []
    tot = d.get("totals") or {}
    name, extra = _resolve(question, [r.get("name") or "" for r in rows])
    if not name:
        return {**_unresolved("supplier", extra), "all_suppliers": {"on_file": len(rows), "we_owe_total": tot.get("balance"),
                "overdue_total": tot.get("overdue"), "with_balance": tot.get("with_balance")}, "as_of": str(d.get("as_of"))}
    r = next(x for x in rows if x.get("name") == name)
    return {"matched": True, **_partial(extra), "as_of": str(d.get("as_of")),
            **{k: (str(v) if isinstance(v, (dt.date, dt.datetime)) else v) for k, v in r.items() if k != "id" and v is not None}}


def product_stock(question: str) -> Dict[str, Any]:
    from src.services.report_subjects import _dossier_product, _list_products
    fams = [p["id"] for p in _list_products("")]
    name, extra = _resolve(question, fams)
    if not name:
        return _unresolved("product", extra)
    d = _dossier_product(name)
    lots = next((t for t in d["tables"] if t["title"] == "Lots in stock"), {"rows": []})
    orders = next((t for t in d["tables"] if t["title"] == "Stock orders"), {"rows": []})
    return {"matched": True, **_partial(extra), "product": name, **{f["label"]: f["value"] for f in d["facts"]},
            "lots": [dict(zip(lots.get("columns", []), r)) for r in lots["rows"]],
            "stock_orders": [dict(zip(orders.get("columns", []), r)) for r in orders["rows"][:5]]}


def quality_status() -> Dict[str, Any]:
    from src.services import quality_hub
    o = quality_hub.overview()
    recalls = [r for r in quality_hub.list_recalls() if r["status"] in quality_hub.OPEN_RECALL]
    devs = [x for x in quality_hub.list_deviations() if x["status"] in quality_hub.OPEN_DEVIATION]
    return {
        "compliance_score": o.get("compliance_score"),
        "open_recalls": [{"recall": r["recall_id"], "product": r["product_name"], "batch": r["batch_number"], "status": r["status"],
                          "linked_to_ace_books": bool(r.get("fin_recall_id"))} for r in recalls],
        "open_deviations": [{"deviation": x["deviation_id"], "class": x["classification"], "status": x["status"],
                             "target_close": str(x.get("target_close_date")), "overdue": x.get("overdue")} for x in devs],
        "audits": o.get("audits"), "maintenance": o.get("maintenance"), "batches_awaiting_release": (o.get("batches") or {}).get("pending"),
        "expiry": o.get("expiry"), "expired_unsellable_value": o.get("expiry_unsellable_value"),
        "held_stock": {k: v for k, v in (o.get("stock") or {}).items() if k.startswith("held")},
        "overdue_items": [i["title"] for i in o.get("attention") or []][:10],
    }


def stock_orders_status(question: str = "") -> Dict[str, Any]:
    from src.services import stock_orders
    s = stock_orders.summary()
    orders = stock_orders.list_orders(limit=40)
    plan = stock_orders.reorder_plan()
    items = plan.get("items") or []
    need = [r for r in items if r.get("status") in ("out_of_stock", "reorder_now")]
    if question:   # a named product goes first, whatever its status
        name, _ = _resolve(question, [r.get("family") or r.get("name") or "" for r in items])
        if name:
            need = [r for r in items if (r.get("family") or r.get("name")) == name] + [r for r in need if (r.get("family") or r.get("name")) != name]
    need = need[:12]
    cnt = plan.get("counts") or {}
    return {
        # three separate numbers - don't merge them: out of stock + running low = total to order
        "products_to_order_total": plan.get("to_order_count"),
        "of_which_out_of_stock": cnt.get("out_of_stock", s.get("out_of_stock")),
        "of_which_running_low": cnt.get("reorder_now", s.get("reorder_now")),
        "order_soon_next": cnt.get("reorder_soon"), "to_order_value": s.get("to_order_value"),
        "requested": s.get("requested"), "approved": s.get("approved"), "with_supplier": s.get("ordered"),
        "overdue_deliveries": s.get("overdue_orders"), "received_last_30d": s.get("received_30d"),
        "we_owe_suppliers": s.get("open_payables"), "overdue_to_suppliers": s.get("overdue_payables"),
        "needs_ordering": [{"product": r.get("family") or r.get("name"), "status": r.get("status"), "on_hand": r.get("on_hand"),
                            "suggested_qty": r.get("suggested_qty"), "est_cost": r.get("est_cost"), "supplier": r.get("supplier_name")}
                           for r in need],
        "needs_ordering_list_note": f"needs_ordering shows the top {len(need)} of {plan.get('to_order_count')} products to order (largest first); it is not the full count",
        "plan_as_of": str(plan.get("as_of")),
        "open_orders": [{"product": o["name"], "qty": o["requested_qty"], "status": o["status"], "supplier": o.get("supplier_name"),
                         "expected": str(o.get("expected_date")), "overdue": o.get("overdue")}
                        for o in orders if o["status"] in ("recommended", "approved", "ordered")][:15],
    }


def stock_loans() -> Dict[str, Any]:
    with tx() as c:
        rows = q(c, """SELECT l.loan_number, l.loan_date, l.expected_return_date, l.status, l.sku, c.name AS customer,
                              l.quantity, l.quantity_returned, (l.quantity - l.quantity_returned) AS outstanding
                       FROM fin_stock_loans l LEFT JOIN customers c ON c.id=l.customer_id
                       WHERE l.status IN ('OPEN','PARTIALLY_RETURNED') ORDER BY l.expected_return_date NULLS LAST""")
    today = dt.date.today()
    return {"loans_outstanding": len(rows), "loans": [{"loan": r["loan_number"], "customer": r["customer"], "product": r["sku"],
                                                       "out": _f(r["outstanding"]), "lent": str(r["loan_date"]),
                                                       "due_back": str(r["expected_return_date"]),
                                                       "overdue": bool(r["expected_return_date"] and r["expected_return_date"] < today)} for r in rows[:30]]}


def pipeline_status() -> Dict[str, Any]:
    from src.services import crm_hub
    o = crm_hub.overview()
    b = crm_hub.pipeline()
    return {"open_pipeline_value": o.get("open_pipeline_value"), "open_deals": o.get("open_deals"), "win_rate_90d": o.get("win_rate_90d"),
            "new_leads_7d": o.get("new_leads_7d"), "follow_ups_overdue": (o.get("reminders") or {}).get("overdue"),
            "follow_ups_today": (o.get("reminders") or {}).get("today"),
            "deals": [{"company": x.get("company_name") or x.get("customer_name") or "(no company recorded)", "stage": st, "value": x.get("expected_value"), "owner": x.get("rep_name")}
                      for st, xs in (b.get("board") or {}).items() for x in xs[:15]],
            "recently_won": [{"company": x.get("company_name"), "value": x.get("expected_value"), "won": str(x.get("won_at"))} for x in o.get("recently_won") or []]}


def team_status() -> Dict[str, Any]:
    from src.services import hr_hub
    o = hr_hub.overview()
    return {"headcount": o["headcount"], "online_now": [x["name"] for x in o["online"]],
            "on_the_clock": [{"name": x["name"], "status": x["status"], "since": str(x["clocked_in_at"])} for x in o["on_clock"]],
            "hours_this_week_total": o["hours_total"], "hours_by_person": [{"name": r["name"], "hours": r["total"]} for r in o["grid"] if r["total"]],
            "timesheets_awaiting_approval": o["pending_approval"]["entries"]}


def my_work(user_id: str = "", roles: Optional[List[str]] = None) -> Dict[str, Any]:
    if not user_id:
        return {"note": "No signed-in user."}
    from src.services import staff_workspace as sw
    d = sw.my_day({"sub": user_id, "roles": roles or []})
    return {"counts": d["counts"], "clock": d["clock"]["status"],
            "due_today": [{"title": i["task"]["title"], "when": str(i["at"]), "overdue": i["task"]["overdue"]} for i in d["timeline"] if i["type"] == "task"],
            "to_answer": [{"from": r["from_name"], "subject": r["subject"]} for r in d["to_answer"]],
            "waiting_on_others": [{"to": r["to_name"], "subject": r["subject"]} for r in d["waiting_on_others"]],
            "for_your_role": [{"item": g["label"], "count": g["count"], "late": g["overdue"]} for g in (d.get("operational") or {}).get("groups") or []]}
