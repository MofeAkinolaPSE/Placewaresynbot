"""CRM on real data: customers and sales from ACE Books, a lean deal pipeline, prospecting that
finds real businesses near the rep, reminders, targets and the weekly report.

Pipeline   new -> qualified -> proposal (proposal, negotiation, payment plan) -> won | lost.
           A lead links to the customer it becomes. `customers` is the same master ACE Books
           invoices, so:
             * marking a lead won creates (or links) the customer, ready to invoice;
             * a lead whose customer gets a posted ACE Books invoice is won automatically
               (sync_auto_won), valued at that invoice.
           Won / lost columns show deals closed in the last 90 days, not every customer.
Prospects  search() returns what the rep asked for, near where they are (GPS or a typed area),
           from OpenStreetMap - nothing is stored until the rep acts (save, called, not
           interested, add to pipeline). Existing customers are flagged, not offered as prospects.
Numbers    customers / sales / receivables come from the ACE Books views (v_sales_lines,
           v_ar_open); pipeline, reminders and activity from the CRM tables.
"""
from __future__ import annotations

import datetime as dt
import json
import math
import re
from collections import defaultdict
from typing import Any, Dict, List, Optional

from src.fin.db import ex, q, q1, tx

SALES_ROLES = {"admin", "sales", "management", "crm"}
STAGES = ["new", "qualified", "proposal", "won", "lost"]
OPEN_STAGES = ("new", "qualified", "proposal")
TRANSITIONS = {
    "new": {"qualified", "proposal", "lost"},
    "qualified": {"proposal", "new", "lost", "won"},
    "proposal": {"won", "lost", "qualified"},
    "won": set(),
    "lost": {"new"},
}
STAGE_LABEL = {"new": "New lead", "qualified": "Qualified", "proposal": "Proposal & terms", "won": "Won", "lost": "Lost"}
CLOSED_WINDOW_DAYS = 90


class CrmError(ValueError):
    pass


def _f(v: Any) -> float:
    return float(v or 0)


def _now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def _uid(v: Any) -> Optional[str]:
    """User ids are stored in uuid columns; anything else (system actors) is stored as NULL."""
    s = str(v or "")
    return s if re.fullmatch(r"[0-9a-fA-F-]{36}", s) else None


def _norm(name: Optional[str]) -> str:
    return re.sub(r"[^a-z0-9]", "", (name or "").lower())


def _sales_as_of(conn) -> dt.date:
    r = q1(conn, "SELECT MAX(invoice_date) AS d FROM v_sales_lines")
    return r["d"] or dt.date.today()


def _names(ids) -> Dict[str, str]:
    from src.services.people import names_for
    return names_for(ids)


def _log(conn, user_id: Optional[str], lead_id: Optional[int], kind: str, summary: str, outcome: Optional[str] = None,
         next_step: Optional[str] = None, customer_id: Optional[int] = None) -> None:
    ex(conn, """INSERT INTO crm_interaction_log (lead_id, customer_id, interaction_type, summary, outcome, next_step, occurred_at, logged_by)
                VALUES (%s,%s,%s,%s,%s,%s,now(),%s)""",
       (lead_id, customer_id, kind, summary, outcome, next_step, _uid(user_id)))


# ---------------------------------------------------------------------------
# Overview
# ---------------------------------------------------------------------------

def overview() -> Dict[str, Any]:
    from src.services.customer_reorder import get_reorder_priority_queue
    with tx() as conn:
        sync_auto_won(conn)
        as_of = _sales_as_of(conn)
        cust = q1(conn, """
            WITH inv AS (SELECT customer_pk, invoice_date FROM v_sales_lines WHERE customer_pk IS NOT NULL GROUP BY 1,2),
                 first AS (SELECT customer_pk, MIN(invoice_date) AS first_date, MAX(invoice_date) AS last_date FROM inv GROUP BY 1)
            SELECT (SELECT COUNT(*) FROM customers) AS on_file,
                   COUNT(*) FILTER (WHERE last_date > %(d)s::date - 90) AS active_90,
                   COUNT(*) FILTER (WHERE last_date > %(d)s::date - 365) AS active_365,
                   COUNT(*) FILTER (WHERE first_date > %(d)s::date - 90) AS new_90,
                   COUNT(*) FILTER (WHERE last_date <= %(d)s::date - 90 AND last_date > %(d)s::date - 365) AS lapsed
            FROM first""", {"d": as_of})
        sales = q1(conn, """SELECT COALESCE(SUM(amount) FILTER (WHERE invoice_date > %(d)s::date - 30), 0) AS last30,
                                   COALESCE(SUM(amount) FILTER (WHERE invoice_date <= %(d)s::date - 30 AND invoice_date > %(d)s::date - 60), 0) AS prev30,
                                   COALESCE(SUM(amount) FILTER (WHERE invoice_date > %(d)s::date - 365), 0) AS last365,
                                   COALESCE(SUM(gross_profit) FILTER (WHERE invoice_date > %(d)s::date - 365), 0) AS gp365
                            FROM v_sales_lines""", {"d": as_of})
        monthly = q(conn, """SELECT to_char(invoice_date, 'YYYY-MM') AS period, SUM(amount) AS sales, COUNT(DISTINCT customer_pk) AS customers,
                                    COUNT(DISTINCT invoice_number) AS invoices
                             FROM v_sales_lines WHERE invoice_date >= (date_trunc('month', %s::date) - interval '11 months')::date AND invoice_date <= %s
                             GROUP BY 1 ORDER BY 1""", (as_of, as_of))
        ar = q1(conn, """SELECT COALESCE(SUM(balance),0) AS owed, COALESCE(SUM(balance) FILTER (WHERE due_date < current_date),0) AS overdue,
                                COUNT(DISTINCT customer_pk) FILTER (WHERE doc_type='INVOICE' AND due_date < current_date) AS overdue_customers
                         FROM v_ar_open""")
        top = q(conn, """SELECT customer_pk AS id, MAX(customer_name) AS name, SUM(amount) AS sales, COUNT(DISTINCT invoice_number) AS invoices,
                                MAX(invoice_date) AS last_date
                         FROM v_sales_lines WHERE customer_pk IS NOT NULL AND invoice_date > %s::date - 90
                         GROUP BY customer_pk ORDER BY sales DESC LIMIT 8""", (as_of,))
        overdue = q(conn, """SELECT customer_pk AS id, MAX(customer_name) AS name, SUM(balance) AS balance,
                                    SUM(balance) FILTER (WHERE due_date < current_date) AS overdue, MAX(days_overdue) AS days
                             FROM v_ar_open GROUP BY customer_pk HAVING SUM(balance) FILTER (WHERE due_date < current_date) > 0
                             ORDER BY overdue DESC LIMIT 8""")
        pipe = q(conn, """SELECT stage::text AS stage, COUNT(*) AS n, COALESCE(SUM(expected_value),0) AS value FROM leads
                          WHERE stage::text IN ('new','qualified','proposal')
                             OR (stage::text IN ('won','lost') AND COALESCE(won_at, lost_at, stage_changed_at) > now() - interval '90 days')
                          GROUP BY 1""")
        leads_week = q1(conn, "SELECT COUNT(*) AS n FROM leads WHERE stage::text <> 'archived' AND created_at > now() - interval '7 days'")["n"]
        rem = q1(conn, """SELECT COUNT(*) FILTER (WHERE due_at < now()) AS overdue,
                                 COUNT(*) FILTER (WHERE due_at::date = current_date) AS today
                          FROM crm_follow_up_reminders WHERE status IN ('pending','snoozed')""")
        won_recent = q(conn, """SELECT l.id, l.company_name, l.expected_value, l.won_at, l.customer_id, l.assigned_rep
                                FROM leads l WHERE l.stage::text='won' AND l.won_at > now() - interval '90 days'
                                ORDER BY l.won_at DESC LIMIT 6""")
    by = {p["stage"]: p for p in pipe}
    closed = _f(by.get("won", {}).get("n")) + _f(by.get("lost", {}).get("n"))
    try:
        reorder = get_reorder_priority_queue(limit=8)
    except Exception:
        reorder = []
    return {
        "as_of": as_of,
        "customers": {k: int(v or 0) for k, v in cust.items()},
        "sales": {"last30": _f(sales["last30"]), "prev30": _f(sales["prev30"]), "last365": _f(sales["last365"]),
                  "margin_pct": round(_f(sales["gp365"]) / _f(sales["last365"]) * 100, 1) if _f(sales["last365"]) else None},
        "monthly": [{"period": m["period"], "sales": _f(m["sales"]), "customers": m["customers"], "invoices": m["invoices"]} for m in monthly],
        "receivables": {"owed": _f(ar["owed"]), "overdue": max(0.0, min(_f(ar["overdue"]), _f(ar["owed"]))), "overdue_customers": ar["overdue_customers"]},
        "pipeline": {s: {"count": int(by.get(s, {}).get("n") or 0), "value": _f(by.get(s, {}).get("value"))} for s in STAGES},
        "open_pipeline_value": sum(_f(by.get(s, {}).get("value")) for s in OPEN_STAGES),
        "open_deals": sum(int(by.get(s, {}).get("n") or 0) for s in OPEN_STAGES),
        "win_rate_90d": round(_f(by.get("won", {}).get("n")) / closed * 100, 1) if closed else None,
        "new_leads_7d": leads_week,
        "reminders": {"overdue": rem["overdue"], "today": rem["today"]},
        "top_customers": top, "overdue_customers": overdue, "reorder_due": reorder, "recently_won": won_recent,
    }


# ---------------------------------------------------------------------------
# Pipeline
# ---------------------------------------------------------------------------

def sync_auto_won(conn) -> int:
    """A lead whose customer now has a posted ACE Books invoice (dated on/after the lead) is won."""
    rows = q(conn, """SELECT DISTINCT ON (l.id) l.id, i.invoice_number, i.total, i.invoice_date
                      FROM leads l JOIN fin_sales_invoices i ON i.customer_id=l.customer_id
                      WHERE l.stage::text IN ('new','qualified','proposal') AND l.customer_id IS NOT NULL
                        AND i.status NOT IN ('DRAFT','VOID') AND NOT i.is_opening AND i.invoice_date >= l.created_at::date
                      ORDER BY l.id, i.invoice_date""")
    for r in rows:
        ex(conn, """UPDATE leads SET stage='won', won_at=%s, stage_changed_at=now(), updated_at=now(),
                           expected_value=CASE WHEN COALESCE(expected_value,0)=0 THEN %s ELSE expected_value END WHERE id=%s""",
           (r["invoice_date"], r["total"], r["id"]))
        _log(conn, None, r["id"], "stage_change", f"Won automatically: first invoice {r['invoice_number']} posted in ACE Books", "won")
    return len(rows)


def pipeline(rep: Optional[str] = None) -> Dict[str, Any]:
    with tx() as conn:
        sync_auto_won(conn)
        rows = q(conn, f"""
            SELECT l.id, l.company_name, l.contact_person, l.contact_phone, l.stage::text AS stage, l.expected_value, l.payment_terms,
                   l.product_interest, l.next_action, l.notes, l.assigned_rep, l.source, l.customer_id, l.created_at, l.updated_at,
                   COALESCE(l.stage_changed_at, l.updated_at) AS stage_changed_at, l.last_contacted_at, l.won_at, l.lost_at, l.lost_reason,
                   c.name AS customer_name,
                   (SELECT MIN(r.due_at) FROM crm_follow_up_reminders r WHERE r.lead_id=l.id AND r.status IN ('pending','snoozed')) AS next_reminder,
                   (SELECT COUNT(*) FROM crm_interaction_log i WHERE i.lead_id=l.id AND i.interaction_type <> 'stage_change') AS touches
            FROM leads l LEFT JOIN customers c ON c.id=l.customer_id
            WHERE (l.stage::text IN ('new','qualified','proposal')
                   OR (l.stage::text IN ('won','lost') AND COALESCE(l.won_at, l.lost_at, l.stage_changed_at, l.updated_at) > now() - interval '{CLOSED_WINDOW_DAYS} days'))
              AND (%s::text IS NULL OR l.assigned_rep::text=%s)
            ORDER BY l.updated_at DESC""", (rep, rep))
    names = _names([r["assigned_rep"] for r in rows])
    now = _now()
    board: Dict[str, List[Dict[str, Any]]] = {s: [] for s in STAGES}
    for r in rows:
        r["rep_name"] = names.get(str(r["assigned_rep"])) if r["assigned_rep"] else None
        r["days_in_stage"] = (now - r["stage_changed_at"]).days if r["stage_changed_at"] else None
        r["reminder_overdue"] = bool(r["next_reminder"] and r["next_reminder"] < now)
        r["stale"] = bool(r["stage"] in OPEN_STAGES and r["days_in_stage"] is not None and r["days_in_stage"] > 14 and not r["next_reminder"])
        board.setdefault(r["stage"], []).append(r)
    return {
        "stages": STAGES, "labels": STAGE_LABEL, "board": board, "closed_window_days": CLOSED_WINDOW_DAYS,
        "counts": {s: len(board[s]) for s in STAGES},
        "values": {s: round(sum(_f(x["expected_value"]) for x in board[s]), 2) for s in STAGES},
    }


def _ensure_customer(conn, lead: Dict[str, Any], rep: Optional[str]) -> int:
    """The customer a won lead becomes (same master ACE Books invoices)."""
    if lead.get("customer_id"):
        return int(lead["customer_id"])
    name = (lead.get("company_name") or "").strip()
    if not name:
        raise CrmError("Give the lead a company name before marking it won")
    existing = [c for c in q(conn, "SELECT id, name FROM customers WHERE lower(name) LIKE %s LIMIT 50", (f"%{name[:6].lower()}%",))
                if _norm(c["name"]) == _norm(name)]
    if existing:
        return int(existing[0]["id"])
    contact = {k: v for k, v in {"phone": lead.get("contact_phone"), "contact_person": lead.get("contact_person")}.items() if v}
    r = q1(conn, """INSERT INTO customers (name, contact_details, account_manager, metadata, payment_terms_days)
                    VALUES (%s, %s::jsonb, %s, %s::jsonb, 30) RETURNING id""",
           (name, json.dumps(contact), rep, json.dumps({"source": "crm_pipeline", "lead_id": lead["id"]})))
    return int(r["id"])


def move_stage(user: Dict[str, Any], lead_id: int, stage: str, data: Dict[str, Any]) -> Dict[str, Any]:
    stage = (stage or "").strip().lower()
    if stage not in STAGES:
        raise CrmError(f"Unknown stage '{stage}'")
    actor = _uid(user.get("sub"))
    with tx() as conn:
        lead = q1(conn, "SELECT *, stage::text AS stage FROM leads WHERE id=%s FOR UPDATE", (lead_id,))
        if not lead:
            raise LookupError("Lead not found")
        cur = lead["stage"]
        if stage == cur:
            return {"id": lead_id, "stage": cur}
        if stage not in TRANSITIONS.get(cur, set()):
            raise CrmError(f"A lead cannot move from {STAGE_LABEL.get(cur, cur)} to {STAGE_LABEL[stage]}")
        sets = ["stage=%s", "stage_changed_at=now()", "updated_at=now()"]
        params: List[Any] = [stage]
        if data.get("expected_value") is not None:
            sets.append("expected_value=%s"); params.append(data["expected_value"])
        if data.get("payment_terms"):
            sets.append("payment_terms=%s"); params.append(data["payment_terms"])
        customer_id = None
        if stage == "won":
            customer_id = _ensure_customer(conn, lead, lead.get("assigned_rep") or actor)
            sets += ["won_at=now()", "customer_id=%s"]; params.append(customer_id)
        if stage == "lost":
            if len((data.get("lost_reason") or "").strip()) < 3:
                raise CrmError("Say why the deal was lost")
            sets += ["lost_at=now()", "lost_reason=%s"]; params.append(data["lost_reason"].strip())
        ex(conn, f"UPDATE leads SET {', '.join(sets)} WHERE id=%s", params + [lead_id])
        _log(conn, actor, lead_id, "stage_change", f"{STAGE_LABEL.get(cur, cur)} → {STAGE_LABEL[stage]}",
             stage, data.get("lost_reason") or data.get("note"), customer_id)
    return {"id": lead_id, "stage": stage, "customer_id": customer_id}


def create_lead(user: Dict[str, Any], data: Dict[str, Any]) -> Dict[str, Any]:
    name = (data.get("company_name") or "").strip()
    if not name:
        raise CrmError("Company name is required")
    actor = _uid(user.get("sub"))
    with tx() as conn:
        dup = q1(conn, """SELECT id, stage::text AS stage FROM leads WHERE stage::text IN ('new','qualified','proposal')
                          AND regexp_replace(lower(company_name), '[^a-z0-9]', '', 'g') = %s LIMIT 1""", (_norm(name),))
        if dup:
            raise CrmError(f"{name} is already in the pipeline ({STAGE_LABEL.get(dup['stage'], dup['stage'])})")
        cust = data.get("customer_id")
        if not cust:
            m = [c for c in q(conn, "SELECT id, name FROM customers WHERE lower(name) LIKE %s LIMIT 50", (f"%{name[:6].lower()}%",))
                 if _norm(c["name"]) == _norm(name)]
            cust = m[0]["id"] if m else None
        meta = {k: v for k, v in {"email": data.get("contact_email"), "address": data.get("address"), "inbound_id": data.get("inbound_id"),
                                   "place_id": data.get("place_id")}.items() if v}
        r = q1(conn, """INSERT INTO leads (company_name, contact_person, contact_phone, product_interest, stage, expected_value, payment_terms,
                                           notes, next_action, assigned_rep, source, industry, customer_id, prospect_id, metadata, stage_changed_at,
                                           created_at, updated_at, score)
                        VALUES (%s,%s,%s,%s,'new',%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb,now(),now(),now(),%s) RETURNING id""",
                 (name, data.get("contact_person"), data.get("contact_phone"), data.get("product_interest") or [],
                  data.get("expected_value") or 0, data.get("payment_terms"), data.get("notes"), data.get("next_action"),
                  data.get("assigned_rep") or actor or None, data.get("source") or "manual", data.get("industry") or "pharma",
                  cust, data.get("prospect_id"), json.dumps(meta), data.get("score") or 0))
        _log(conn, actor, r["id"], "created", f"Lead added ({data.get('source') or 'manual'})", None, data.get("next_action"), cust)
        if data.get("prospect_id"):
            ex(conn, "UPDATE crm_prospects SET status='converted', converted_lead_id=%s, updated_at=now() WHERE id=%s", (r["id"], data["prospect_id"]))
    return {"id": r["id"], "customer_id": cust, "existing_customer": bool(cust)}


def lead_detail(lead_id: int) -> Dict[str, Any]:
    with tx() as conn:
        lead = q1(conn, """SELECT l.*, l.stage::text AS stage, c.name AS customer_name FROM leads l
                           LEFT JOIN customers c ON c.id=l.customer_id WHERE l.id=%s""", (lead_id,))
        if not lead:
            raise LookupError("Lead not found")
        acts = q(conn, "SELECT * FROM crm_interaction_log WHERE lead_id=%s ORDER BY occurred_at DESC LIMIT 100", (lead_id,))
        rems = q(conn, "SELECT * FROM crm_follow_up_reminders WHERE lead_id=%s ORDER BY due_at DESC LIMIT 50", (lead_id,))
        books = None
        if lead["customer_id"]:
            books = q1(conn, """SELECT (SELECT COALESCE(SUM(balance),0) FROM v_ar_open WHERE customer_pk=%s) AS balance,
                                       (SELECT MAX(invoice_date) FROM v_sales_lines WHERE customer_pk=%s) AS last_invoice,
                                       (SELECT COALESCE(SUM(amount),0) FROM v_sales_lines WHERE customer_pk=%s AND invoice_date > current_date - 365) AS sales_12m""",
                       (lead["customer_id"],) * 3)
    names = _names([lead["assigned_rep"]] + [a["logged_by"] for a in acts])
    lead["rep_name"] = names.get(str(lead["assigned_rep"])) if lead["assigned_rep"] else None
    for a in acts:
        a["by"] = names.get(str(a["logged_by"])) if a["logged_by"] else "ACE"
    return {"lead": lead, "activity": acts, "reminders": rems, "books": books}


def update_lead(user: Dict[str, Any], lead_id: int, data: Dict[str, Any]) -> Dict[str, Any]:
    allowed = ("company_name", "contact_person", "contact_phone", "expected_value", "payment_terms", "notes", "next_action", "assigned_rep", "product_interest")
    fields = {k: data[k] for k in allowed if k in data}
    if not fields:
        return {"id": lead_id}
    with tx() as conn:
        n = ex(conn, f"UPDATE leads SET {', '.join(f'{k}=%s' for k in fields)}, updated_at=now() WHERE id=%s", list(fields.values()) + [lead_id])
        if not n:
            raise LookupError("Lead not found")
    return {"id": lead_id, "updated": list(fields)}


def log_activity(user: Dict[str, Any], data: Dict[str, Any]) -> Dict[str, Any]:
    """A call / visit / message with a lead (or customer). An optional follow-up date creates a reminder."""
    lead_id, cust = data.get("lead_id"), data.get("customer_id")
    if not lead_id and not cust:
        raise CrmError("Choose the lead or customer")
    if len((data.get("summary") or "").strip()) < 3:
        raise CrmError("Say what happened")
    actor = _uid(user.get("sub"))
    with tx() as conn:
        _log(conn, actor, lead_id, data.get("interaction_type") or "call", data["summary"].strip(), data.get("outcome"), data.get("next_step"), cust)
        if lead_id:
            ex(conn, "UPDATE leads SET last_contacted_at=now(), updated_at=now(), next_action=COALESCE(%s, next_action) WHERE id=%s",
               (data.get("next_step"), lead_id))
        if data.get("follow_up_at"):
            _insert_reminder(conn, actor, {"lead_id": lead_id, "customer_id": cust, "due_at": data["follow_up_at"],
                                           "title": data.get("next_step") or "Follow up", "reminder_type": "follow_up"})
    return {"ok": True}


# ---------------------------------------------------------------------------
# Reminders
# ---------------------------------------------------------------------------

def _insert_reminder(conn, actor: Optional[str], data: Dict[str, Any]) -> Dict[str, Any]:
    if not data.get("due_at"):
        raise CrmError("Choose when")
    if not data.get("lead_id") and not data.get("customer_id") and not data.get("title"):
        raise CrmError("Say what the reminder is for")
    return q1(conn, """INSERT INTO crm_follow_up_reminders (lead_id, customer_id, assigned_rep, reminder_type, due_at, note, title, status, created_by)
                       VALUES (%s,%s,%s,%s,%s,%s,%s,'pending',%s) RETURNING id::text AS id""",
              (data.get("lead_id"), data.get("customer_id"), _uid(data.get("assigned_rep")) or actor, data.get("reminder_type") or "follow_up",
               data["due_at"], data.get("note"), data.get("title"), actor or None))


def create_reminder(user: Dict[str, Any], data: Dict[str, Any]) -> Dict[str, Any]:
    with tx() as conn:
        return _insert_reminder(conn, _uid(user.get("sub")), data)


def reminders(user: Dict[str, Any], scope: str = "mine") -> Dict[str, Any]:
    me = str(user.get("sub") or "")
    with tx() as conn:
        rows = q(conn, """SELECT r.id::text AS id, r.lead_id, r.customer_id, r.assigned_rep, r.reminder_type, r.due_at, r.note, r.title, r.status,
                                 r.completed_at, r.created_at, l.company_name AS lead_name, l.stage::text AS lead_stage, l.contact_phone,
                                 c.name AS customer_name
                          FROM crm_follow_up_reminders r LEFT JOIN leads l ON l.id=r.lead_id LEFT JOIN customers c ON c.id=r.customer_id
                          WHERE (r.status IN ('pending','snoozed') OR r.completed_at > now() - interval '14 days')
                            AND (%s = 'all' OR r.assigned_rep::text = %s OR r.created_by::text = %s)
                          ORDER BY r.status IN ('done','dismissed'), r.due_at""", (scope, me, me))
    names = _names([r["assigned_rep"] for r in rows])
    now = _now()
    out = {"overdue": [], "today": [], "upcoming": [], "done": []}
    for r in rows:
        r["rep_name"] = names.get(str(r["assigned_rep"])) if r["assigned_rep"] else None
        if r["status"] in ("done", "dismissed"):
            out["done"].append(r)
        elif r["due_at"] < now:
            out["overdue"].append(r)
        elif r["due_at"].date() == now.date():
            out["today"].append(r)
        else:
            out["upcoming"].append(r)
    return out


def update_reminder(user: Dict[str, Any], reminder_id: str, action: str, days: int = 1) -> Dict[str, Any]:
    with tx() as conn:
        if action == "done":
            n = ex(conn, "UPDATE crm_follow_up_reminders SET status='done', completed_at=now() WHERE id::text=%s", (reminder_id,))
        elif action == "snooze":
            n = ex(conn, """UPDATE crm_follow_up_reminders SET status='snoozed', due_at=GREATEST(due_at, now()) + (%s || ' days')::interval
                            WHERE id::text=%s""", (str(max(1, days)), reminder_id))
        elif action == "dismiss":
            n = ex(conn, "UPDATE crm_follow_up_reminders SET status='dismissed', completed_at=now() WHERE id::text=%s", (reminder_id,))
        else:
            raise CrmError("Unknown action")
        if not n:
            raise LookupError("Reminder not found")
    return {"id": reminder_id, "action": action}


# ---------------------------------------------------------------------------
# Prospecting (real places near the rep) and inbound leads
# ---------------------------------------------------------------------------

def _haversine(lat1, lng1, lat2, lng2) -> float:
    r = 6371000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = math.radians(lat2 - lat1), math.radians(lng2 - lng1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def search(user: Dict[str, Any], data: Dict[str, Any]) -> Dict[str, Any]:
    from src.services.places_service import search_places_near
    limit = max(1, min(int(data.get("limit") or 10), 50))
    radius_m = int(max(0.5, min(float(data.get("radius_km") or 5), 50)) * 1000)
    btype = (data.get("business_type") or "pharmacy").strip().lower()
    res = search_places_near(lat=data.get("lat"), lng=data.get("lng"), location=(data.get("location") or "").strip(),
                             business_type=btype, radius_m=radius_m, limit=limit)
    places = res["places"]
    with tx() as conn:
        ids = [p["place_id"] for p in places]
        worked = {r["place_id"]: r for r in q(conn, """SELECT id::text AS id, place_id, status, converted_lead_id, last_note FROM crm_prospects
                                                     WHERE place_id = ANY(%s)""", (ids,))} if ids else {}
        customers = {_norm(c["name"]): c for c in q(conn, "SELECT id, name FROM customers")}
        open_leads = {_norm(l["company_name"]): l for l in q(conn, """SELECT id, company_name, stage::text AS stage FROM leads
                                                                    WHERE stage::text IN ('new','qualified','proposal')""")}
    for p in places:
        w = worked.get(p["place_id"])
        c = customers.get(_norm(p["company_name"]))
        ld = open_leads.get(_norm(p["company_name"]))
        p["prospect_id"] = w["id"] if w else None
        p["status"] = w["status"] if w else "new"
        p["note"] = w["last_note"] if w else None
        p["customer"] = {"id": c["id"], "name": c["name"]} if c else None
        p["lead"] = ld
    return {"origin": res["origin"], "origin_label": res["origin_label"], "radius_m": radius_m, "business_type": btype,
            "requested": limit, "found": len(places), "places": places, "source": res["source"]}


def save_prospect(user: Dict[str, Any], place: Dict[str, Any], status: str = "saved", note: Optional[str] = None) -> Dict[str, Any]:
    if status not in ("saved", "contacted", "not_interested"):
        raise CrmError("Unknown prospect status")
    actor = _uid(user.get("sub"))
    with tx() as conn:
        row = q1(conn, "SELECT id::text AS id FROM crm_prospects WHERE place_id=%s", (place.get("place_id"),)) if place.get("place_id") else None
        if row:
            ex(conn, """UPDATE crm_prospects SET status=CASE WHEN status='converted' THEN status ELSE %s END, last_note=COALESCE(%s, last_note),
                               contacted_at=CASE WHEN %s='contacted' THEN now() ELSE contacted_at END, assigned_rep=COALESCE(assigned_rep, %s),
                               updated_at=now() WHERE id=%s""", (status, note, status, actor or None, row["id"]))
            pid = row["id"]
        else:
            pid = q1(conn, """INSERT INTO crm_prospects (company_name, industry, region, contact_phone, phone_number, website, formatted_address,
                                                         lat, lng, place_id, source, status, score, places_score, distance_m, search_query, last_note,
                                                         contacted_at, assigned_rep, created_by)
                              VALUES (%s,'pharma',%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,CASE WHEN %s='contacted' THEN now() END,%s,%s)
                              RETURNING id::text AS id""",
                         (place.get("company_name"), place.get("region"), place.get("phone_number"), place.get("phone_number"), place.get("website"),
                          place.get("formatted_address"), place.get("lat"), place.get("lng"), place.get("place_id"),
                          place.get("source") or "openstreetmap", status, place.get("places_score") or 0, place.get("places_score") or 0,
                          place.get("distance_m"), place.get("search_query"), note, status, actor or None, actor or None))["id"]
    return {"prospect_id": pid, "status": status}


def prospect_to_lead(user: Dict[str, Any], place: Dict[str, Any], extra: Dict[str, Any]) -> Dict[str, Any]:
    pid = place.get("prospect_id") or save_prospect(user, place, "contacted", extra.get("notes"))["prospect_id"]
    return create_lead(user, {"company_name": place.get("company_name"), "contact_phone": extra.get("contact_phone") or place.get("phone_number"),
                              "contact_person": extra.get("contact_person"), "address": place.get("formatted_address"),
                              "expected_value": extra.get("expected_value"), "notes": extra.get("notes"), "next_action": extra.get("next_action"),
                              "source": "lead_finder", "prospect_id": pid, "place_id": place.get("place_id")})


def prospects(user: Dict[str, Any], status: Optional[str] = None) -> List[Dict[str, Any]]:
    with tx() as conn:
        rows = q(conn, """SELECT p.id::text AS id, p.company_name, p.formatted_address, p.phone_number, p.contact_phone, p.website, p.lat, p.lng,
                                 p.place_id, p.status, p.last_note, p.contacted_at, p.assigned_rep, p.distance_m, p.search_query, p.created_at,
                                 p.converted_lead_id, l.stage::text AS lead_stage
                          FROM crm_prospects p LEFT JOIN leads l ON l.id=p.converted_lead_id
                          WHERE p.status IN ('saved','contacted','not_interested','converted') AND (%s::text IS NULL OR p.status=%s)
                          ORDER BY p.updated_at DESC NULLS LAST, p.created_at DESC LIMIT 300""", (status, status))
    names = _names([r["assigned_rep"] for r in rows])
    for r in rows:
        r["rep_name"] = names.get(str(r["assigned_rep"])) if r["assigned_rep"] else None
    return rows


def inbound() -> List[Dict[str, Any]]:
    """Website enquiries (contact form) - each can be added to the pipeline once."""
    with tx() as conn:
        rows = q(conn, """SELECT p.*, (SELECT l.id FROM leads l WHERE l.metadata->>'inbound_id' = p.id::text LIMIT 1) AS lead_id
                          FROM placeware_leads p ORDER BY p.created_at DESC LIMIT 200""")
    return rows


# ---------------------------------------------------------------------------
# Weekly report, targets, leaderboard
# ---------------------------------------------------------------------------

def weekly_report(week_start: Optional[dt.date] = None) -> Dict[str, Any]:
    today = dt.date.today()
    ws = week_start or (today - dt.timedelta(days=today.weekday()))
    we = ws + dt.timedelta(days=6)
    rng = (ws, we + dt.timedelta(days=1))
    with tx() as conn:
        new_leads = q(conn, """SELECT id, company_name, source, assigned_rep, expected_value, stage::text AS stage, created_at FROM leads
                               WHERE stage::text <> 'archived' AND created_at >= %s AND created_at < %s ORDER BY created_at""", rng)
        acts = q(conn, """SELECT i.interaction_type, i.summary, i.outcome, i.logged_by, i.occurred_at, i.lead_id, l.company_name
                          FROM crm_interaction_log i LEFT JOIN leads l ON l.id=i.lead_id
                          WHERE i.occurred_at >= %s AND i.occurred_at < %s ORDER BY i.occurred_at""", rng)
        won = q(conn, """SELECT id, company_name, expected_value, assigned_rep, won_at FROM leads WHERE stage::text='won' AND won_at >= %s AND won_at < %s""", rng)
        lost = q(conn, """SELECT id, company_name, expected_value, assigned_rep, lost_reason FROM leads WHERE stage::text='lost' AND lost_at >= %s AND lost_at < %s""", rng)
        prospects_n = q1(conn, """SELECT COUNT(*) FILTER (WHERE created_at >= %s AND created_at < %s) AS saved,
                                         COUNT(*) FILTER (WHERE contacted_at >= %s AND contacted_at < %s) AS contacted
                                  FROM crm_prospects WHERE status <> 'archived'""", rng + rng)
        rem = q1(conn, """SELECT COUNT(*) FILTER (WHERE completed_at >= %s AND completed_at < %s AND status='done') AS done,
                                 COUNT(*) FILTER (WHERE status IN ('pending','snoozed') AND due_at < %s) AS overdue
                          FROM crm_follow_up_reminders""", rng + (rng[1],))
        sales = q1(conn, """SELECT COALESCE(SUM(amount),0) AS sales, COUNT(DISTINCT invoice_number) AS invoices, COUNT(DISTINCT customer_pk) AS customers
                            FROM v_sales_lines WHERE invoice_date >= %s AND invoice_date < %s""", rng)
        open_pipe = q1(conn, """SELECT COUNT(*) AS n, COALESCE(SUM(expected_value),0) AS value FROM leads WHERE stage::text IN ('new','qualified','proposal')""")
    names = _names([x["assigned_rep"] for x in new_leads + won + lost] + [a["logged_by"] for a in acts])
    per_rep: Dict[str, Dict[str, Any]] = defaultdict(lambda: {"new_leads": 0, "activities": 0, "won": 0, "won_value": 0.0, "lost": 0})
    for l in new_leads:
        per_rep[names.get(str(l["assigned_rep"]), "Unassigned") if l["assigned_rep"] else "Unassigned"]["new_leads"] += 1
    for a in acts:
        if a["interaction_type"] != "stage_change":
            per_rep[names.get(str(a["logged_by"]), "System") if a["logged_by"] else "System"]["activities"] += 1
    for w in won:
        k = names.get(str(w["assigned_rep"]), "Unassigned") if w["assigned_rep"] else "Unassigned"
        per_rep[k]["won"] += 1; per_rep[k]["won_value"] += _f(w["expected_value"])
    for l in lost:
        per_rep[names.get(str(l["assigned_rep"]), "Unassigned") if l["assigned_rep"] else "Unassigned"]["lost"] += 1
    for x in new_leads + won + lost:
        x["rep_name"] = names.get(str(x["assigned_rep"])) if x.get("assigned_rep") else None
    touches = [a for a in acts if a["interaction_type"] != "stage_change"]
    for a in acts:
        a["by"] = names.get(str(a["logged_by"])) if a["logged_by"] else "ACE"
    return {
        "week_start": ws, "week_end": we,
        "summary": {"new_leads": len(new_leads), "activities": len(touches), "won": len(won), "won_value": round(sum(_f(w["expected_value"]) for w in won), 2),
                    "lost": len(lost), "prospects_saved": prospects_n["saved"], "prospects_contacted": prospects_n["contacted"],
                    "reminders_done": rem["done"], "reminders_overdue": rem["overdue"], "sales": _f(sales["sales"]), "invoices": sales["invoices"],
                    "customers_invoiced": sales["customers"], "open_pipeline": open_pipe["n"], "open_pipeline_value": _f(open_pipe["value"])},
        "per_rep": [{"rep": k, **v} for k, v in sorted(per_rep.items(), key=lambda kv: -(kv[1]["won_value"] + kv[1]["activities"]))],
        "new_leads": new_leads, "won": won, "lost": lost, "activity": acts,
    }


def _period_range(period: str) -> tuple:
    p = period.strip().upper()
    if re.fullmatch(r"\d{4}-\d{2}", p):
        y, m = int(p[:4]), int(p[5:])
        start = dt.date(y, m, 1)
        end = dt.date(y + (m == 12), m % 12 + 1, 1)
    elif re.fullmatch(r"\d{4}-Q[1-4]", p):
        y, qn = int(p[:4]), int(p[-1])
        start = dt.date(y, 3 * qn - 2, 1)
        end = dt.date(y + (qn == 4), (3 * qn) % 12 + 1, 1)
    else:
        raise CrmError("Period is YYYY-MM or YYYY-Qn")
    return start, end


def targets(period: str) -> Dict[str, Any]:
    start, end = _period_range(period)
    with tx() as conn:
        ts = q(conn, "SELECT id::text AS id, rep_id::text AS rep_id, period, period_type, target_value, target_deals FROM crm_sales_targets WHERE upper(period)=%s",
               (period.upper(),))
        sales = q1(conn, """SELECT COALESCE(SUM(amount),0) AS sales, COUNT(DISTINCT invoice_number) AS invoices,
                                   COUNT(DISTINCT customer_pk) AS customers, MAX(invoice_date) AS last_date
                            FROM v_sales_lines WHERE invoice_date >= %s AND invoice_date < %s""", (start, end))
        won = q(conn, """SELECT assigned_rep::text AS rep, COUNT(*) AS deals, COALESCE(SUM(expected_value),0) AS value
                         FROM leads WHERE stage::text='won' AND won_at >= %s AND won_at < %s GROUP BY 1""", (start, end))
    names = _names([t["rep_id"] for t in ts] + [w["rep"] for w in won])
    won_by = {w["rep"]: w for w in won}
    rows = []
    for t in ts:
        if t["rep_id"]:
            w = won_by.get(t["rep_id"], {})
            actual, basis = _f(w.get("value")), "deals won"
        else:
            actual, basis = _f(sales["sales"]), "ACE Books sales"
        rows.append({**t, "who": names.get(t["rep_id"], t["rep_id"]) if t["rep_id"] else "Whole team", "actual": round(actual, 2), "basis": basis,
                     "deals": int((won_by.get(t["rep_id"]) or {}).get("deals") or 0) if t["rep_id"] else None,
                     "attainment_pct": round(actual / _f(t["target_value"]) * 100, 1) if _f(t["target_value"]) else None})
    today = dt.date.today()
    elapsed = max(0, min((min(today, end) - start).days, (end - start).days)) / max(1, (end - start).days)
    return {"period": period, "start": start, "end": end - dt.timedelta(days=1), "elapsed_pct": round(elapsed * 100, 1),
            "sales": {"value": _f(sales["sales"]), "invoices": sales["invoices"], "customers": sales["customers"], "last_date": sales["last_date"]},
            "won_by_rep": [{"rep": names.get(w["rep"], w["rep"]) if w["rep"] else "Unassigned", "deals": w["deals"], "value": _f(w["value"])} for w in won],
            "targets": rows}


def set_target(user: Dict[str, Any], data: Dict[str, Any]) -> Dict[str, Any]:
    period = (data.get("period") or "").strip().upper()
    _period_range(period)
    if _f(data.get("target_value")) <= 0:
        raise CrmError("Target must be more than zero")
    with tx() as conn:
        ex(conn, "DELETE FROM crm_sales_targets WHERE upper(period)=%s AND rep_id IS NOT DISTINCT FROM %s::uuid", (period, data.get("rep_id") or None))
        r = q1(conn, """INSERT INTO crm_sales_targets (rep_id, period, period_type, target_value, target_deals)
                        VALUES (%s::uuid,%s,%s,%s,%s) RETURNING id::text AS id""",
               (data.get("rep_id") or None, period, "quarterly" if "Q" in period else "monthly", data["target_value"], data.get("target_deals")))
    return r


def leaderboard(days: int = 30) -> List[Dict[str, Any]]:
    with tx() as conn:
        rows = q(conn, """
            WITH reps AS (SELECT assigned_rep::text AS rep FROM leads WHERE assigned_rep IS NOT NULL AND stage::text <> 'archived'
                          UNION SELECT logged_by::text FROM crm_interaction_log WHERE logged_by IS NOT NULL)
            SELECT r.rep,
                   (SELECT COUNT(*) FROM leads l WHERE l.assigned_rep::text=r.rep AND l.stage::text <> 'archived' AND l.created_at > now() - make_interval(days => %(d)s)) AS leads_added,
                   (SELECT COUNT(*) FROM crm_interaction_log i WHERE i.logged_by::text=r.rep AND i.interaction_type <> 'stage_change' AND i.occurred_at > now() - make_interval(days => %(d)s)) AS activities,
                   (SELECT COUNT(*) FROM leads l WHERE l.assigned_rep::text=r.rep AND l.stage::text='won' AND l.won_at > now() - make_interval(days => %(d)s)) AS won,
                   (SELECT COALESCE(SUM(expected_value),0) FROM leads l WHERE l.assigned_rep::text=r.rep AND l.stage::text='won' AND l.won_at > now() - make_interval(days => %(d)s)) AS won_value,
                   (SELECT COUNT(*) FROM leads l WHERE l.assigned_rep::text=r.rep AND l.stage::text='lost' AND l.lost_at > now() - make_interval(days => %(d)s)) AS lost,
                   (SELECT COALESCE(SUM(expected_value),0) FROM leads l WHERE l.assigned_rep::text=r.rep AND l.stage::text IN ('new','qualified','proposal')) AS open_value
            FROM reps r""", {"d": days})
    names = _names([r["rep"] for r in rows])
    for r in rows:
        r["name"] = names.get(r["rep"], r["rep"])
        r["won_value"] = _f(r["won_value"]); r["open_value"] = _f(r["open_value"])
    rows.sort(key=lambda r: (-r["won_value"], -r["won"], -r["activities"]))
    return rows


def reps() -> List[Dict[str, Any]]:
    """Team members who can own deals (sales, management, admin), by name."""
    with tx() as conn:
        rows = q(conn, """SELECT u.id::text AS id, COALESCE(s.full_name, u.email) AS name, u.email, u.roles
                          FROM placeware_users u LEFT JOIN placeware_staff s ON lower(s.email)=lower(u.email)
                          WHERE u.is_active AND u.roles && ARRAY['sales','management','admin']::text[]
                          ORDER BY 2""")
    return rows


def create_customer(user: Dict[str, Any], data: Dict[str, Any]) -> Dict[str, Any]:
    """A new customer in the shared master (ACE Books invoices the same table), refusing duplicates."""
    name = (data.get("name") or "").strip()
    if len(name) < 2:
        raise CrmError("Customer name is required")
    with tx() as conn:
        dup = [c for c in q(conn, "SELECT id, name FROM customers WHERE lower(name) LIKE %s LIMIT 50", (f"%{name[:6].lower()}%",))
               if _norm(c["name"]) == _norm(name)]
        if dup:
            raise CrmError(f"{dup[0]['name']} already exists (customer #{dup[0]['id']})")
        contact = {k: v for k, v in {"phone": data.get("phone"), "email": data.get("email"), "address": data.get("address"),
                                     "city": data.get("city"), "contact_person": data.get("contact_person")}.items() if v}
        r = q1(conn, """INSERT INTO customers (name, contact_details, account_manager, payment_terms_days, credit_limit, facility_type, metadata)
                        VALUES (%s,%s::jsonb,%s,%s,%s,%s,%s::jsonb) RETURNING id, name""",
               (name, json.dumps(contact), _uid(data.get("account_manager")) or _uid(user.get("sub")), int(data.get("payment_terms_days") or 30),
                data.get("credit_limit") or 0, data.get("facility_type"), json.dumps({"source": "crm", "created_by": user.get("sub")})))
    return r



# ---------------------------------------------------------------------------
# Customer directory & profile (ACE Books + CRM, one row per customer)
# ---------------------------------------------------------------------------

def customer_directory() -> Dict[str, Any]:
    """Every customer with its real numbers: sales (12m / previous 12m / lifetime), orders, margin,
    last order and usual cycle (ACE Books sales history), balance and overdue (ACE Books open items),
    and CRM state (owner, open deal, last contact, next reminder)."""
    with tx() as conn:
        as_of = _sales_as_of(conn)
        rows = q(conn, """
            WITH inv AS (SELECT customer_pk, invoice_number, MIN(invoice_date) AS d, SUM(amount) AS amt, SUM(gross_profit) AS gp
                         FROM v_sales_lines WHERE customer_pk IS NOT NULL GROUP BY customer_pk, invoice_number),
                 s AS (SELECT customer_pk,
                              SUM(amt) FILTER (WHERE d > %(d)s::date - 365) AS sales_12m,
                              SUM(amt) FILTER (WHERE d <= %(d)s::date - 365 AND d > %(d)s::date - 730) AS sales_prev_12m,
                              SUM(gp)  FILTER (WHERE d > %(d)s::date - 365) AS gp_12m,
                              COUNT(*) FILTER (WHERE d > %(d)s::date - 365) AS orders_12m,
                              SUM(amt) AS lifetime, COUNT(*) AS orders, MIN(d) AS first_order, MAX(d) AS last_order
                       FROM inv GROUP BY customer_pk),
                 gaps AS (SELECT customer_pk, AVG(g) AS avg_gap FROM (
                              SELECT customer_pk, d - LAG(d) OVER (PARTITION BY customer_pk ORDER BY d) AS g
                              FROM (SELECT DISTINCT customer_pk, d FROM inv WHERE d > %(d)s::date - 730) x) y
                          WHERE g IS NOT NULL GROUP BY customer_pk),
                 ar AS (SELECT customer_pk, SUM(balance) AS balance, SUM(balance) FILTER (WHERE due_date < current_date) AS overdue,
                               MAX(days_overdue) AS max_days FROM v_ar_open GROUP BY customer_pk),
                 deal AS (SELECT DISTINCT ON (customer_id) customer_id, id AS deal_id, stage::text AS deal_stage, expected_value AS deal_value
                          FROM leads WHERE customer_id IS NOT NULL AND stage::text IN ('new','qualified','proposal') ORDER BY customer_id, updated_at DESC),
                 contact AS (SELECT COALESCE(i.customer_id, l.customer_id) AS customer_id, MAX(i.occurred_at) AS last_contact
                             FROM crm_interaction_log i LEFT JOIN leads l ON l.id=i.lead_id
                             WHERE i.interaction_type NOT IN ('stage_change','created') GROUP BY 1),
                 rem AS (SELECT customer_id, MIN(due_at) AS next_reminder FROM crm_follow_up_reminders
                         WHERE status IN ('pending','snoozed') AND customer_id IS NOT NULL GROUP BY 1)
            SELECT c.id, c.name, c.customer_code, c.facility_type, c.credit_limit, c.payment_terms_days, c.account_manager::text AS owner,
                   c.contact_details->>'phone' AS phone, COALESCE(c.contact_details->>'city', '') AS city, c.contact_details->>'address' AS address,
                   c.contact_details->>'contact_person' AS contact_person,
                   COALESCE(s.sales_12m,0) AS sales_12m, COALESCE(s.sales_prev_12m,0) AS sales_prev_12m, COALESCE(s.gp_12m,0) AS gp_12m,
                   COALESCE(s.orders_12m,0) AS orders_12m, COALESCE(s.lifetime,0) AS lifetime, COALESCE(s.orders,0) AS orders,
                   s.first_order, s.last_order, round(g.avg_gap::numeric, 0) AS avg_gap_days,
                   COALESCE(ar.balance,0) AS balance, GREATEST(0, LEAST(COALESCE(ar.overdue,0), COALESCE(ar.balance,0))) AS overdue, ar.max_days,
                   dl.deal_id, dl.deal_stage, dl.deal_value, ct.last_contact, rm.next_reminder
            FROM customers c
            LEFT JOIN s ON s.customer_pk=c.id LEFT JOIN gaps g ON g.customer_pk=c.id LEFT JOIN ar ON ar.customer_pk=c.id
            LEFT JOIN deal dl ON dl.customer_id=c.id LEFT JOIN contact ct ON ct.customer_id=c.id LEFT JOIN rem rm ON rm.customer_id=c.id
            ORDER BY COALESCE(s.sales_12m,0) DESC, c.name""", {"d": as_of})
    names = _names([r["owner"] for r in rows])
    counts: Dict[str, int] = defaultdict(int)
    for r in rows:
        last = r["last_order"]
        since = (as_of - last).days if last else None
        r["days_since_order"] = since
        r["segment"] = ("never" if not last else "new" if r["first_order"] and (as_of - r["first_order"]).days <= 90
                        else "active" if since <= 90 else "lapsing" if since <= 365 else "lapsed")
        s12, p12 = _f(r["sales_12m"]), _f(r["sales_prev_12m"])
        r["trend_pct"] = round((s12 - p12) / p12 * 100, 1) if p12 > 0 else None
        r["margin_pct"] = round(_f(r["gp_12m"]) / s12 * 100, 1) if s12 else None
        gap = _f(r["avg_gap_days"])
        r["reorder_due_in"] = round(gap - since) if gap and since is not None and r["segment"] in ("active", "new", "lapsing") else None
        reasons = []
        if r["segment"] in ("active", "new", "lapsing"):
            if r["trend_pct"] is not None and r["trend_pct"] <= -30:
                reasons.append(f"sales down {abs(r['trend_pct']):g}% on last year")
            if r["reorder_due_in"] is not None and gap and r["reorder_due_in"] < -gap:
                reasons.append(f"{-r['reorder_due_in']} days past their usual reorder")
            if _f(r["overdue"]) > 0 and (r["max_days"] or 0) > 60:
                reasons.append(f"owes money {r['max_days']} days overdue")
        r["risk_reasons"] = reasons
        r["at_risk"] = bool(reasons)
        cl = _f(r["credit_limit"])
        r["credit_used_pct"] = round(_f(r["balance"]) / cl * 100, 1) if cl > 0 else None
        r["owner_name"] = names.get(str(r["owner"])) if r["owner"] else None
        counts[r["segment"]] += 1
        if r["at_risk"]:
            counts["at_risk"] += 1
    return {"as_of": as_of, "customers": rows, "counts": dict(counts), "total": len(rows),
            "totals": {"sales_12m": round(sum(_f(r["sales_12m"]) for r in rows), 2), "balance": round(sum(max(_f(r["balance"]), 0.0) for r in rows), 2),
                       "credits": round(-sum(min(_f(r["balance"]), 0.0) for r in rows), 2),
                       "overdue": round(sum(_f(r["overdue"]) for r in rows), 2)}}


def customer_profile(customer_id: int) -> Dict[str, Any]:
    """One customer's full picture: monthly sales (24 months), what they buy, invoices, CRM history."""
    with tx() as conn:
        as_of = _sales_as_of(conn)
        c = q1(conn, "SELECT *, account_manager::text AS owner FROM customers WHERE id=%s", (customer_id,))
        if not c:
            raise LookupError("Customer not found")
        monthly = q(conn, """SELECT to_char(invoice_date,'YYYY-MM') AS period, SUM(amount) AS sales, SUM(gross_profit) AS gp,
                                    COUNT(DISTINCT invoice_number) AS orders
                             FROM v_sales_lines WHERE customer_pk=%s AND invoice_date >= (date_trunc('month', %s::date) - interval '23 months')::date
                             GROUP BY 1 ORDER BY 1""", (customer_id, as_of))
        products = q(conn, """SELECT sku, MAX(description) AS name, SUM(quantity) AS qty, SUM(amount) AS sales, COUNT(DISTINCT invoice_number) AS orders,
                                     MAX(invoice_date) AS last_bought, SUM(amount) / NULLIF(SUM(quantity),0) AS avg_price
                              FROM v_sales_lines WHERE customer_pk=%s AND invoice_date > %s::date - 730 AND sku IS NOT NULL
                              GROUP BY sku ORDER BY sales DESC LIMIT 30""", (customer_id, as_of))
        invoices = q(conn, """SELECT source, invoice_id, date, due_date, amount, balance, status, ace_invoice_id::text AS ace_invoice_id
                              FROM v_customer_invoices WHERE customer_pk=%s ORDER BY date DESC LIMIT 60""", (customer_id,))
        deals = q(conn, """SELECT id, company_name, stage::text AS stage, expected_value, won_at, lost_reason, created_at, assigned_rep::text AS rep
                           FROM leads WHERE customer_id=%s AND stage::text <> 'archived' ORDER BY updated_at DESC""", (customer_id,))
        activity = q(conn, """SELECT i.id, i.interaction_type, i.summary, i.outcome, i.next_step, i.occurred_at, i.logged_by::text AS by_id
                              FROM crm_interaction_log i LEFT JOIN leads l ON l.id=i.lead_id
                              WHERE i.customer_id=%s OR l.customer_id=%s ORDER BY i.occurred_at DESC LIMIT 50""", (customer_id, customer_id))
        reminders = q(conn, """SELECT id::text AS id, title, reminder_type, due_at, status FROM crm_follow_up_reminders
                               WHERE customer_id=%s AND status IN ('pending','snoozed') ORDER BY due_at""", (customer_id,))
    d = next((r for r in customer_directory()["customers"] if r["id"] == customer_id), {})
    names = _names([a["by_id"] for a in activity] + [x["rep"] for x in deals] + [c["owner"]])
    for a in activity:
        a["by"] = names.get(a["by_id"]) if a["by_id"] else "ACE"
    for x in deals:
        x["rep_name"] = names.get(x["rep"]) if x["rep"] else None
    cd = c.get("contact_details") or {}
    cust = {"id": c["id"], "name": c["name"], "customer_code": c["customer_code"], "facility_type": c["facility_type"],
            "client_type": c["client_type"], "credit_limit": _f(c["credit_limit"]), "payment_terms_days": c["payment_terms_days"],
            "owner": c["owner"], "owner_name": names.get(c["owner"]) if c["owner"] else None, "competing_supplier": c.get("competing_supplier")}
    cust.update({k: cd.get(k) for k in ("phone", "email", "address", "city", "contact_person")})
    return {"as_of": as_of, "customer": cust, "metrics": d, "monthly": monthly, "products": products, "invoices": invoices,
            "deals": deals, "activity": activity, "reminders": reminders}


def update_customer(user: Dict[str, Any], customer_id: int, data: Dict[str, Any]) -> Dict[str, Any]:
    """Contacts, owner, type and terms. The credit limit (enforced by ACE Books at invoicing) only by finance/management/admin."""
    roles = {str(r).lower() for r in (user.get("roles") or [])}
    with tx() as conn:
        c = q1(conn, "SELECT contact_details FROM customers WHERE id=%s FOR UPDATE", (customer_id,))
        if not c:
            raise LookupError("Customer not found")
        sets, params = [], []
        contact = dict(c["contact_details"] or {})
        for k in ("phone", "email", "address", "city", "contact_person"):
            if k in data:
                contact[k] = data[k] or None
        sets.append("contact_details=%s::jsonb"); params.append(json.dumps({k: v for k, v in contact.items() if v}))
        for k in ("facility_type", "client_type", "competing_supplier", "name"):
            if data.get(k) is not None:
                sets.append(f"{k}=%s"); params.append(data[k])
        if data.get("payment_terms_days") is not None:
            sets.append("payment_terms_days=%s"); params.append(int(data["payment_terms_days"]))
        if "owner" in data:
            sets.append("account_manager=%s::uuid"); params.append(_uid(data["owner"]))
        if data.get("credit_limit") is not None:
            if not roles & {"admin", "finance", "management"}:
                raise CrmError("Only Finance or management can change a credit limit")
            sets.append("credit_limit=%s"); params.append(_f(data["credit_limit"]))
        ex(conn, f"UPDATE customers SET {', '.join(sets)}, updated_at=now() WHERE id=%s", params + [customer_id])
        _log(conn, user.get("sub"), None, "note", "Customer details updated: " + ", ".join(sorted(k for k in data)), None, None, customer_id)
    return {"id": customer_id, "updated": list(data)}
