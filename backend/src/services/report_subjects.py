"""Reports about a specific record: pick the exact deviation, recall, audit, sale, customer,
product, batch, stock order or period - the system gathers everything it knows about it -
the person reviews it - the report is written from that record summary only.

  REPORT_TYPES   what can be reported on, and which kinds of record each type accepts
  list_subjects  the recent records of a kind, searchable (what the person picks from)
  dossier        every fact linked to the chosen record, from the module that owns it:
                 facts (label/value), long texts, tables, gaps (what is NOT recorded, so
                 the report says so instead of inventing it) and links back to the record
  sections_for   the sections of a report on that kind of record

Nothing here writes. The report writer (agents/report_generation_agent.py) receives the
dossier as its only data, and the dossier is attached to the report as its appendix.
"""
from __future__ import annotations

import datetime as dt
import json
import re
from collections import defaultdict
from typing import Any, Callable, Dict, List, Optional, Tuple

from src.fin.db import q, q1, tx
from src.report_templates import _section

# ---------------------------------------------------------------------------
# what can be reported on
# ---------------------------------------------------------------------------

REPORT_TYPES: List[Dict[str, Any]] = [
    {"type": "deviation", "name": "Deviation report", "group": "Quality & compliance", "kinds": ["deviation"],
     "about": "One deviation: what happened, classification, impact, investigation, CAPA and status."},
    {"type": "capa", "name": "CAPA report", "group": "Quality & compliance", "kinds": ["capa"],
     "about": "The corrective and preventive actions raised on a deviation: owners, due dates, progress."},
    {"type": "recall", "name": "Recall report", "group": "Quality & compliance", "kinds": ["recall"],
     "about": "One recall: product and batch, reason, authority, customers traced, stock returned."},
    {"type": "audit", "name": "Audit report", "group": "Quality & compliance", "kinds": ["audit"],
     "about": "One audit: scope, schedule, outcome, deviations raised, follow-up."},
    {"type": "maintenance", "name": "Maintenance report", "group": "Quality & compliance", "kinds": ["maintenance"],
     "about": "One equipment maintenance / calibration job and the equipment's history."},
    {"type": "batch", "name": "Batch release (QC) report", "group": "Quality & compliance", "kinds": ["batch"],
     "about": "One incoming batch: registration, QC decision, stock, expiry, movements."},
    {"type": "compliance", "name": "Compliance summary", "group": "Quality & compliance", "kinds": ["period"],
     "about": "Deviations, recalls, audits, maintenance and compliance activity over a period."},
    {"type": "sales", "name": "Sales report", "group": "Sales & finance", "kinds": ["sale", "customer", "period"],
     "about": "A single sale (invoice), a customer's buying, or sales over a period."},
    {"type": "customer", "name": "Customer account report", "group": "Sales & finance", "kinds": ["customer"],
     "about": "One customer: buying pattern, products, margin, balance, deals and contact."},
    {"type": "ar_aging", "name": "Receivables report", "group": "Sales & finance", "kinds": ["customer", "period"],
     "about": "What a customer owes and how late, or all receivables as at a date."},
    {"type": "pl", "name": "Profit & loss report", "group": "Sales & finance", "kinds": ["period"],
     "about": "Income statement for a period from ACE Books, with comparison."},
    {"type": "inventory", "name": "Stock & movement report", "group": "Stock & operations", "kinds": ["product", "batch", "period"],
     "about": "A product's stock, lots, movements and sales; a batch; or stock movements over a period."},
    {"type": "procurement", "name": "Stock order report", "group": "Stock & operations", "kinds": ["stock_order"],
     "about": "One stock order from request to receipt, with supplier and bill."},
    {"type": "frontdesk", "name": "Frontdesk activity report", "group": "Stock & operations", "kinds": ["period"],
     "about": "Walk-ins and requests over a period."},
    {"type": "executive", "name": "Executive report", "group": "Management", "kinds": ["current"],
     "about": "The company now: finance, sales, stock, quality, people and what needs attention."},
]
TYPE_BY_KEY = {t["type"]: t for t in REPORT_TYPES}

KIND_LABEL = {
    "deviation": "a deviation", "capa": "a deviation's CAPA", "recall": "a recall", "audit": "an audit",
    "maintenance": "a maintenance job", "batch": "a batch", "sale": "a sale (invoice)", "customer": "a customer",
    "product": "a product", "stock_order": "a stock order", "period": "a period", "current": "the company today",
}


def _f(v: Any) -> float:
    return float(v or 0)


def _n(v: Any) -> str:
    return f"₦{_f(v):,.2f}"


def _d(v: Any) -> str:
    if v in (None, ""):
        return "not recorded"
    if isinstance(v, dt.datetime):
        return v.strftime("%d %b %Y %H:%M")
    if isinstance(v, dt.date):
        return v.strftime("%d %b %Y")
    return str(v)


def _txt(v: Any) -> str:
    return "not recorded" if v in (None, "", [], {}) else str(v)


def _like(s: str) -> str:
    return f"%{(s or '').strip()}%"


def _dossier(kind: str, id_: str, title: str, subtitle: str = "", facts: Optional[List[Tuple[str, Any]]] = None,
             texts: Optional[List[Tuple[str, Any]]] = None, tables: Optional[List[Dict[str, Any]]] = None,
             gaps: Optional[List[str]] = None, links: Optional[List[Tuple[str, str]]] = None) -> Dict[str, Any]:
    return {"kind": kind, "id": id_, "title": title, "subtitle": subtitle,
            "facts": [{"label": k, "value": _txt(v)} for k, v in (facts or [])],
            "texts": [{"label": k, "value": str(v)} for k, v in (texts or []) if v not in (None, "", [], {})],
            "tables": [t for t in (tables or []) if t.get("rows")],
            "gaps": gaps or [], "links": [{"label": k, "href": h} for k, h in (links or [])],
            "gathered_at": dt.datetime.now(dt.timezone.utc).isoformat()}


def _table(title: str, columns: List[str], rows: List[List[Any]]) -> Dict[str, Any]:
    return {"title": title, "columns": columns, "rows": [[_txt(c) if not isinstance(c, str) else c for c in r] for r in rows]}


def _people(ids) -> Dict[str, str]:
    from src.services.people import names_for
    try:
        return names_for([i for i in ids if i])
    except Exception:
        return {}


# ---------------------------------------------------------------------------
# Quality records
# ---------------------------------------------------------------------------

def _capa_list(raw) -> List[Dict[str, Any]]:
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except Exception:
            return []
    return [a for a in raw if isinstance(a, dict)] if isinstance(raw, list) else []


def _list_deviations(search: str, capa_only: bool = False) -> List[Dict[str, Any]]:
    with tx() as c:
        rows = q(c, """SELECT id::text AS id, deviation_id, classification, status, observation, created_at, target_close_date,
                              capa_actions FROM deviation_reports
                       WHERE (%s = '' OR deviation_id ILIKE %s OR observation ILIKE %s)
                       ORDER BY created_at DESC LIMIT 60""", (search, _like(search), _like(search)))
    out = []
    for r in rows:
        capa = _capa_list(r["capa_actions"])
        if capa_only and not capa:
            continue
        out.append({"id": r["id"], "title": f"{r['deviation_id']} · {r['classification']}",
                    "subtitle": (r["observation"] or "")[:110] + (f" · {len(capa)} CAPA" if capa else ""),
                    "date": r["created_at"], "status": r["status"]})
    return out


def _dossier_deviation(id_: str, capa_focus: bool = False) -> Dict[str, Any]:
    with tx() as c:
        d = q1(c, "SELECT * FROM deviation_reports WHERE id=%s::uuid", (id_,))
        if not d:
            raise LookupError("Deviation not found")
        acts = q(c, """SELECT activity_name, scheduled_date, completion_date, status, department FROM compliance_activity_log
                       WHERE deviation_id=%s::uuid""", (id_,))
        trig = None
        if d.get("trigger_ref"):
            ref = str(d["trigger_ref"])
            for sql in ("SELECT 'Audit: ' || audit_type || ' (' || department || ', ' || COALESCE(scheduled_date::text,'') || ')' AS t FROM audit_schedule WHERE id::text=%s",
                        "SELECT 'Maintenance: ' || e.equipment_name || ' - ' || m.maintenance_type AS t FROM maintenance_schedule m JOIN equipment_registry e ON e.id=m.equipment_id WHERE m.id::text=%s",
                        "SELECT 'Batch: ' || product_name || ' ' || batch_number AS t FROM nafdac_batch_registry WHERE id::text=%s"):
                try:
                    r = q1(c, sql, (ref,))
                except Exception:
                    r = None
                if r:
                    trig = r["t"]
                    break
    today = dt.date.today()
    capa = _capa_list(d.get("capa_actions"))
    days_open = ((d["closed_at"].date() if d.get("closed_at") else today) - d["created_at"].date()).days if d.get("created_at") else None
    overdue = bool(d.get("target_close_date") and d["status"] != "closed" and d["target_close_date"] < today)
    capa_rows = []
    for a in capa:
        due = a.get("due_date")
        st = str(a.get("status") or "open")
        late = bool(due and st.lower() not in ("done", "completed", "closed") and str(due)[:10] < str(today))
        capa_rows.append([a.get("action") or a.get("description") or "—", a.get("type") or a.get("kind") or "—", a.get("owner") or "—",
                          str(due or "—")[:10], st + (" (overdue)" if late else "")])
    gaps = []
    if not d.get("impact_assessment"):
        gaps.append("No impact assessment has been recorded.")
    if not capa:
        gaps.append("No CAPA actions have been recorded.")
    if not d.get("responsible_person"):
        gaps.append("No responsible person is recorded.")
    if not d.get("recommendations"):
        gaps.append("No investigation findings / recommendations are recorded (root cause is not documented).")
    kind = "capa" if capa_focus else "deviation"
    return _dossier(
        kind, id_, f"{'CAPA - ' if capa_focus else ''}Deviation {d['deviation_id']}",
        f"{str(d['classification']).title()} deviation · {str(d['status']).replace('_', ' ')}",
        facts=[("Deviation ID", d["deviation_id"]), ("Classification", d["classification"]), ("Status", str(d["status"]).replace("_", " ")),
               ("Raised", _d(d.get("created_at"))), ("Trigger", f"{d.get('trigger_type') or 'not recorded'}" + (f" - {trig}" if trig else "")),
               ("Investigation started", _d(d.get("investigation_start_date"))), ("Target close date", _d(d.get("target_close_date"))
                                                                                    + (" (OVERDUE)" if overdue else "")),
               ("Closed", _d(d.get("closed_at"))), ("Days open", days_open),
               ("Responsible department", d.get("responsible_department")), ("Responsible person", d.get("responsible_person")),
               ("CAPA actions", f"{len(capa)} ({sum(1 for r in capa_rows if 'overdue' in r[4])} overdue)")],
        texts=[("Observation", d.get("observation")), ("Impact assessment", d.get("impact_assessment")),
               ("Investigation findings / recommendations", d.get("recommendations"))],
        tables=[_table("CAPA actions", ["Action", "Type", "Owner", "Due", "Status"], capa_rows),
                _table("Linked compliance activities", ["Activity", "Scheduled", "Completed", "Status", "Department"],
                       [[a["activity_name"], _d(a["scheduled_date"]), _d(a["completion_date"]), a["status"], a["department"]] for a in acts])],
        gaps=gaps, links=[("Open in Compliance & QMS", "/compliance?tab=deviations")])


def _list_recalls(search: str) -> List[Dict[str, Any]]:
    with tx() as c:
        rows = q(c, """SELECT id::text AS id, recall_id, product_name, batch_number, status, initiation_date, created_at, severity
                       FROM recall_cases WHERE (%s = '' OR recall_id ILIKE %s OR product_name ILIKE %s OR batch_number ILIKE %s)
                       ORDER BY created_at DESC LIMIT 60""", (search, _like(search), _like(search), _like(search)))
    return [{"id": r["id"], "title": f"{r['recall_id']} · {r['product_name']}", "subtitle": f"batch {r['batch_number']}"
             + (f" · {r['severity']}" if r.get("severity") else ""), "date": r["initiation_date"] or r["created_at"], "status": r["status"]}
            for r in rows]


def _dossier_recall(id_: str) -> Dict[str, Any]:
    with tx() as c:
        r = q1(c, "SELECT * FROM recall_cases WHERE id=%s::uuid", (id_,))
        if not r:
            raise LookupError("Recall not found")
        fr = q1(c, "SELECT * FROM fin_recalls WHERE id=%s::uuid", (r["fin_recall_id"],)) if r.get("fin_recall_id") else None
        items = q(c, """SELECT i.*, cu.name AS customer FROM fin_recall_items i LEFT JOIN customers cu ON cu.id=i.customer_id
                        WHERE i.recall_id=%s::uuid ORDER BY i.quantity_sold DESC""", (fr["id"],)) if fr else []
        batch = q1(c, "SELECT batch_number, expiry_date, status, manufacture_date FROM fin_batches WHERE id=%s", (fr["batch_id"],)) if fr and fr.get("batch_id") else None
        held = q1(c, "SELECT COALESCE(SUM(qty_remaining),0) AS q, COALESCE(SUM(qty_remaining*unit_cost),0) AS v FROM fin_cost_layers WHERE batch_id=%s",
                  (fr["batch_id"],)) if fr and fr.get("batch_id") else None
    sold = sum(_f(i["quantity_sold"]) for i in items)
    ret = sum(_f(i["quantity_returned"]) for i in items)
    contacted = sum(1 for i in items if str(i.get("contact_status") or "").lower() not in ("", "pending", "not_contacted"))
    gaps = []
    if not fr:
        gaps.append("This recall is not linked to ACE Books - customers have not been traced there and the batch may not be frozen.")
    if not r.get("regulatory_authority"):
        gaps.append("No regulatory authority is recorded.")
    if not r.get("nafdac_notified"):
        gaps.append("NAFDAC notification is not recorded as done.")
    return _dossier(
        "recall", id_, f"Recall {r['recall_id']} - {r['product_name']}", f"batch {r['batch_number']} · {r['status']}",
        facts=[("Recall ID", r["recall_id"]), ("Product", r["product_name"]), ("SKU", r.get("sku")), ("Batch", r["batch_number"]),
               ("Severity", r.get("severity")), ("Status", r["status"]), ("Initiated", _d(r.get("initiation_date") or r.get("created_at"))),
               ("Scope", r.get("scope")), ("Regulatory authority", r.get("regulatory_authority")),
               ("NAFDAC notified", "yes" if r.get("nafdac_notified") else "no"), ("Stock due back by", _d(r.get("expected_return_date"))),
               ("Resolved", _d(r.get("resolved_at"))), ("ACE Books recall", fr["recall_number"] if fr else "not linked"),
               ("Batch expiry", _d(batch["expiry_date"]) if batch else None), ("Batch status in ACE Books", batch["status"] if batch else None),
               ("Units still held (frozen)", f"{_f(held['q']):g} units, {_n(held['v'])} at cost" if held else None),
               ("Customers who bought it", len(items)), ("Customers contacted", f"{contacted} of {len(items)}"),
               ("Units sold / returned", f"{sold:g} sold, {ret:g} returned ({round(100 * ret / sold) if sold else 0}%)")],
        texts=[("Reason", r.get("recall_reason")), ("ACE Books notes", fr.get("notes") if fr else None)],
        tables=[_table("Customer trace", ["Customer", "Invoice", "Sold", "Returned", "Contact status", "Notes"],
                       [[i["customer"] or i["customer_id"], i["invoice_number"], f"{_f(i['quantity_sold']):g}", f"{_f(i['quantity_returned']):g}",
                         i["contact_status"], i["notes"] or ""] for i in items])],
        gaps=gaps, links=[("Open in Quality Control", "/quality-control?tab=recalls")])


def _list_audits(search: str) -> List[Dict[str, Any]]:
    with tx() as c:
        rows = q(c, """SELECT id::text AS id, audit_type, department, status, scheduled_date, completed_at, risk_level FROM audit_schedule
                       WHERE (%s = '' OR audit_type ILIKE %s OR department ILIKE %s)
                       ORDER BY COALESCE(completed_at::date, scheduled_date) DESC NULLS LAST LIMIT 60""", (search, _like(search), _like(search)))
    return [{"id": r["id"], "title": f"{r['audit_type']} · {r['department']}", "subtitle": f"risk {r['risk_level'] or '—'}",
             "date": r["completed_at"] or r["scheduled_date"], "status": r["status"]} for r in rows]


def _dossier_audit(id_: str) -> Dict[str, Any]:
    with tx() as c:
        a = q1(c, "SELECT * FROM audit_schedule WHERE id=%s::uuid", (id_,))
        if not a:
            raise LookupError("Audit not found")
        devs = q(c, """SELECT deviation_id, classification, status, observation, created_at FROM deviation_reports
                       WHERE trigger_ref=%s ORDER BY created_at""", (id_,))
        prev = q(c, """SELECT scheduled_date, status, completed_at FROM audit_schedule WHERE audit_type=%s AND department=%s AND id<>%s::uuid
                       ORDER BY scheduled_date DESC NULLS LAST LIMIT 6""", (a["audit_type"], a["department"], id_))
    gaps = [] if a.get("notes") else ["No audit findings / notes are recorded on the audit."]
    if a["status"] != "completed":
        gaps.append("The audit is not marked completed.")
    return _dossier(
        "audit", id_, f"Audit - {a['audit_type']} ({a['department']})", str(a["status"]),
        facts=[("Audit type", a["audit_type"]), ("Department", a["department"]), ("Risk level", a.get("risk_level")),
               ("Frequency", a.get("frequency")), ("Scheduled", _d(a.get("scheduled_date"))), ("Status", a["status"]),
               ("Completed", _d(a.get("completed_at"))), ("Assigned to", a.get("assigned_to")), ("Deviations raised from it", len(devs))],
        texts=[("Audit notes / findings", a.get("notes"))],
        tables=[_table("Deviations raised", ["Deviation", "Class", "Status", "Observation", "Raised"],
                       [[x["deviation_id"], x["classification"], x["status"], (x["observation"] or "")[:120], _d(x["created_at"])] for x in devs]),
                _table("Other audits of this type", ["Scheduled", "Status", "Completed"],
                       [[_d(p["scheduled_date"]), p["status"], _d(p["completed_at"])] for p in prev])],
        gaps=gaps, links=[("Open in Compliance & QMS", "/compliance?tab=audits")])


def _list_maintenance(search: str) -> List[Dict[str, Any]]:
    with tx() as c:
        rows = q(c, """SELECT m.id::text AS id, e.equipment_name, e.location, m.maintenance_type, m.status, m.next_maintenance_date, m.completed_at
                       FROM maintenance_schedule m JOIN equipment_registry e ON e.id=m.equipment_id
                       WHERE (%s = '' OR e.equipment_name ILIKE %s OR m.maintenance_type ILIKE %s)
                       ORDER BY COALESCE(m.completed_at::date, m.next_maintenance_date) DESC NULLS LAST LIMIT 60""", (search, _like(search), _like(search)))
    return [{"id": r["id"], "title": f"{r['equipment_name']} · {r['maintenance_type']}", "subtitle": r["location"] or "",
             "date": r["completed_at"] or r["next_maintenance_date"], "status": r["status"]} for r in rows]


def _dossier_maintenance(id_: str) -> Dict[str, Any]:
    with tx() as c:
        m = q1(c, """SELECT m.*, e.equipment_name, e.equipment_type, e.location, e.serial_number, e.model, e.status AS equipment_status,
                            e.last_calibration_date, e.calibration_interval_days
                     FROM maintenance_schedule m JOIN equipment_registry e ON e.id=m.equipment_id WHERE m.id=%s::uuid""", (id_,))
        if not m:
            raise LookupError("Maintenance job not found")
        hist = q(c, """SELECT maintenance_type, last_maintenance_date, next_maintenance_date, status, performed_by, completion_notes
                       FROM maintenance_schedule WHERE equipment_id=%s ORDER BY COALESCE(completed_at, created_at) DESC LIMIT 10""", (m["equipment_id"],))
        devs = q(c, "SELECT deviation_id, classification, status, observation FROM deviation_reports WHERE trigger_ref=%s", (id_,))
    today = dt.date.today()
    overdue = bool(m.get("next_maintenance_date") and m["next_maintenance_date"] < today and m["status"] not in ("completed", "cancelled"))
    return _dossier(
        "maintenance", id_, f"Maintenance - {m['equipment_name']} ({m['maintenance_type']})", str(m["status"]),
        facts=[("Equipment", m["equipment_name"]), ("Type", m.get("equipment_type")), ("Location", m.get("location")),
               ("Serial / model", f"{m.get('serial_number') or '—'} / {m.get('model') or '—'}"), ("Maintenance type", m["maintenance_type"]),
               ("Interval (days)", m.get("interval_days")), ("Last done", _d(m.get("last_maintenance_date"))),
               ("Next due", _d(m.get("next_maintenance_date")) + (" (OVERDUE)" if overdue else "")), ("Status", m["status"]),
               ("Performed by", m.get("performed_by")), ("Completed", _d(m.get("completed_at"))),
               ("Last calibration", _d(m.get("last_calibration_date"))), ("Deviations raised", len(devs))],
        texts=[("Completion notes", m.get("completion_notes"))],
        tables=[_table("Maintenance history for this equipment", ["Type", "Last done", "Next due", "Status", "By", "Notes"],
                       [[h["maintenance_type"], _d(h["last_maintenance_date"]), _d(h["next_maintenance_date"]), h["status"], h["performed_by"] or "",
                         (h["completion_notes"] or "")[:80]] for h in hist]),
                _table("Deviations raised", ["Deviation", "Class", "Status", "Observation"],
                       [[x["deviation_id"], x["classification"], x["status"], (x["observation"] or "")[:100]] for x in devs])],
        gaps=[] if m.get("completion_notes") else ["No completion notes recorded."],
        links=[("Open in Compliance & QMS", "/compliance?tab=maintenance")])


def _list_batches(search: str) -> List[Dict[str, Any]]:
    with tx() as c:
        rows = q(c, """SELECT id::text AS id, product_name, batch_number, status, created_at, expected_arrival_date, quantity
                       FROM nafdac_batch_registry WHERE (%s = '' OR product_name ILIKE %s OR batch_number ILIKE %s)
                       ORDER BY created_at DESC LIMIT 60""", (search, _like(search), _like(search)))
    return [{"id": r["id"], "title": f"{r['product_name']} · batch {r['batch_number']}",
             "subtitle": f"{_f(r['quantity']):g} units" if r["quantity"] else "", "date": r["created_at"], "status": r["status"]} for r in rows]


def _dossier_batch(id_: str) -> Dict[str, Any]:
    with tx() as c:
        b = q1(c, "SELECT * FROM nafdac_batch_registry WHERE id=%s::uuid", (id_,))
        if not b:
            raise LookupError("Batch not found")
        fb = q1(c, "SELECT * FROM fin_batches WHERE id=%s", (b["fin_batch_id"],)) if b.get("fin_batch_id") else None
        stock = q1(c, "SELECT COALESCE(SUM(qty_remaining),0) AS q, COALESCE(SUM(qty_remaining*unit_cost),0) AS v FROM fin_cost_layers WHERE batch_id=%s",
                   (b["fin_batch_id"],)) if b.get("fin_batch_id") else None
        moves = q(c, """SELECT txn_date, txn_type, quantity, total_cost, reference, reason FROM fin_inventory_transactions
                        WHERE batch_id=%s ORDER BY txn_date, created_at LIMIT 60""", (b["fin_batch_id"],)) if b.get("fin_batch_id") else []
        so = q1(c, """SELECT r.status, r.requested_qty, r.ordered_at, s.name AS supplier FROM replenishment_requests r
                      LEFT JOIN suppliers s ON s.id=r.supplier_id WHERE r.id=%s""", (b["stock_order_id"],)) if b.get("stock_order_id") else None
        devs = q(c, "SELECT deviation_id, classification, status, observation FROM deviation_reports WHERE trigger_ref=%s", (id_,))
        recs = q(c, "SELECT recall_id, status, recall_reason FROM recall_cases WHERE batch_number=%s", (b["batch_number"],))
    names = _people([b.get("registered_by"), b.get("approved_by")])
    return _dossier(
        "batch", id_, f"Batch {b['batch_number']} - {b['product_name']}", str(b["status"]),
        facts=[("Product", b["product_name"]), ("SKU", b.get("sku")), ("Batch", b["batch_number"]), ("NAFDAC reg. no.", b.get("nafdac_reg_number")),
               ("Supplier", b.get("supplier")), ("Quantity", f"{_f(b.get('quantity')):g}" if b.get("quantity") else None),
               ("Expected arrival", _d(b.get("expected_arrival_date"))), ("Expiry", _d(b.get("expiry_date") or (fb or {}).get("expiry_date"))),
               ("QC status", b["status"]), ("Registered", f"{_d(b.get('created_at'))} by {names.get(str(b.get('registered_by')), b.get('registered_by') or '—')}"),
               ("Decision", f"{_d(b.get('approved_at'))} by {names.get(str(b.get('approved_by')), b.get('approved_by') or '—')}" if b.get("approved_at") else "not yet decided"),
               ("Status in ACE Books", fb["status"] if fb else "not received into stock"),
               ("In stock now", f"{_f(stock['q']):g} units, {_n(stock['v'])} at cost" if stock else None),
               ("Stock order", f"{so['status']} · {_f(so['requested_qty']):g} units from {so['supplier'] or '—'}" if so else None),
               ("Deviations raised", len(devs)), ("Recalls", len(recs))],
        texts=[("Rejection reason", b.get("rejection_reason")), ("Notes", b.get("notes"))],
        tables=[_table("Movements of this batch (ACE Books)", ["Date", "Type", "Qty", "Cost", "Reference", "Reason"],
                       [[_d(m["txn_date"]), m["txn_type"], f"{_f(m['quantity']):g}", _n(m["total_cost"]), m["reference"] or "", m["reason"] or ""] for m in moves]),
                _table("Deviations", ["Deviation", "Class", "Status", "Observation"],
                       [[x["deviation_id"], x["classification"], x["status"], (x["observation"] or "")[:100]] for x in devs]),
                _table("Recalls", ["Recall", "Status", "Reason"], [[x["recall_id"], x["status"], (x["recall_reason"] or "")[:100]] for x in recs])],
        links=[("Open in Quality Control", "/quality-control?tab=release")])


# ---------------------------------------------------------------------------
# Sales, customers, products, orders
# ---------------------------------------------------------------------------

def _list_sales(search: str) -> List[Dict[str, Any]]:
    with tx() as c:
        rows = q(c, """SELECT invoice_number, MAX(invoice_date) AS d, MAX(customer_name) AS customer, SUM(amount) AS total, COUNT(*) AS lines
                       FROM v_sales_lines WHERE (%s = '' OR invoice_number ILIKE %s OR customer_name ILIKE %s)
                         AND invoice_date >= (SELECT MAX(invoice_date) FROM v_sales_lines) - 400
                       GROUP BY invoice_number ORDER BY d DESC, invoice_number DESC LIMIT 60""", (search, _like(search), _like(search)))
    return [{"id": r["invoice_number"], "title": f"{r['invoice_number']} · {r['customer']}", "subtitle": f"{_n(r['total'])} · {r['lines']} lines",
             "date": r["d"], "status": ""} for r in rows]


def _dossier_sale(id_: str) -> Dict[str, Any]:
    with tx() as c:
        lines = q(c, """SELECT source, invoice_date, customer_pk, customer_name, sku, description, quantity, amount, cost, gross_profit
                        FROM v_sales_lines WHERE invoice_number=%s ORDER BY amount DESC""", (id_,))
        if not lines:
            raise LookupError("Invoice not found")
        inv = q1(c, "SELECT * FROM v_customer_invoices WHERE invoice_id::text=%s LIMIT 1", (id_,))
        cust = lines[0]["customer_pk"]
        ctx = q1(c, """SELECT SUM(amount) FILTER (WHERE invoice_date > %s::date - 365) AS s12, COUNT(DISTINCT invoice_number) AS n
                       FROM v_sales_lines WHERE customer_pk=%s""", (lines[0]["invoice_date"], cust))
    tot = sum(_f(l["amount"]) for l in lines)
    gp = sum(_f(l["gross_profit"]) for l in lines)
    return _dossier(
        "sale", id_, f"Sale {id_} - {lines[0]['customer_name']}", f"{_d(lines[0]['invoice_date'])} · {_n(tot)}",
        facts=[("Invoice", id_), ("Date", _d(lines[0]["invoice_date"])), ("Customer", lines[0]["customer_name"]), ("Recorded in", lines[0]["source"]),
               ("Lines", len(lines)), ("Units", f"{sum(_f(l['quantity']) for l in lines):g}"), ("Total (excl. tax)", _n(tot)),
               ("Cost of goods", _n(sum(_f(l["cost"]) for l in lines))), ("Gross profit", _n(gp)),
               ("Gross margin", f"{round(gp / tot * 100, 1)}%" if tot else None),
               ("Due date", _d(inv.get("due_date")) if inv else None), ("Balance outstanding", _n(inv.get("balance")) if inv else None),
               ("Status", inv.get("status") if inv else None),
               ("Customer's sales, 12 months to this invoice", _n(ctx["s12"])), ("Customer's invoices on record", ctx["n"])],
        tables=[_table("Lines", ["SKU", "Description", "Qty", "Amount", "Cost", "Margin %"],
                       [[l["sku"], l["description"] or "", f"{_f(l['quantity']):g}", _n(l["amount"]), _n(l["cost"]),
                         f"{round(_f(l['gross_profit']) / _f(l['amount']) * 100, 1)}%" if _f(l["amount"]) else "—"] for l in lines])],
        links=[("Open the customer", f"/crm/customers?customer={cust}")])


def _list_customers(search: str) -> List[Dict[str, Any]]:
    with tx() as c:
        rows = q(c, """SELECT c.id, c.name, c.customer_code, s.s12, s.last FROM customers c
                       LEFT JOIN (SELECT customer_pk, SUM(amount) FILTER (WHERE invoice_date > (SELECT MAX(invoice_date) FROM v_sales_lines) - 365) AS s12,
                                         MAX(invoice_date) AS last FROM v_sales_lines GROUP BY 1) s ON s.customer_pk=c.id
                       WHERE (%s = '' OR c.name ILIKE %s OR c.customer_code ILIKE %s)
                       ORDER BY s.s12 DESC NULLS LAST, c.name LIMIT 60""", (search, _like(search), _like(search)))
    return [{"id": str(r["id"]), "title": r["name"], "subtitle": f"{_n(r['s12'])} in 12 months" if r["s12"] else "no sales in 12 months",
             "date": r["last"], "status": r["customer_code"] or ""} for r in rows]


def _dossier_customer(id_: str, receivables_focus: bool = False) -> Dict[str, Any]:
    from src.services import crm_hub
    p = crm_hub.customer_profile(int(id_))
    cu, m = p.get("customer") or {}, p.get("metrics") or {}
    with tx() as c:
        aged = q(c, """SELECT doc_type, doc_number, doc_date, due_date, amount, balance, days_overdue FROM v_ar_open
                       WHERE customer_pk=%s ORDER BY due_date""", (int(id_),))
    buckets = defaultdict(float)
    for a in aged:
        d = int(a["days_overdue"] or 0)
        buckets["current" if d <= 0 else "1-30" if d <= 30 else "31-60" if d <= 60 else "61-90" if d <= 90 else "90+"] += _f(a["balance"])
    facts = [("Customer", cu.get("name")), ("Code", cu.get("customer_code")), ("Phone", cu.get("phone")), ("Email", cu.get("email")),
             ("Address / city", cu.get("address") or cu.get("city")), ("Account owner", cu.get("owner_name")),
             ("Payment terms", f"{cu.get('payment_terms_days')} days" if cu.get("payment_terms_days") is not None else None),
             ("Credit limit", _n(cu.get("credit_limit")) if cu.get("credit_limit") else "none set")]
    facts += [("Facility / client type", " / ".join(x for x in (cu.get("facility_type"), cu.get("client_type")) if x) or None),
              ("Segment", m.get("segment")), ("Sales, last 12 months", _n(m.get("sales_12m"))), ("Sales, previous 12 months", _n(m.get("sales_prev_12m"))),
              ("Trend", f"{m['trend_pct']}%" if m.get("trend_pct") is not None else None),
              ("Gross margin, 12 months", f"{m['margin_pct']}%" if m.get("margin_pct") is not None else None),
              ("Orders, 12 months", m.get("orders_12m") or m.get("orders")), ("Lifetime sales", _n(m.get("lifetime"))),
              ("First order", _d(m.get("first_order"))), ("Last order", _d(m.get("last_order"))),
              ("Usual gap between orders", f"{round(_f(m['avg_gap_days']))} days" if m.get("avg_gap_days") else None),
              ("Next order expected", (f"in {m['reorder_due_in']} days" if m["reorder_due_in"] >= 0 else f"{-m['reorder_due_in']} days late")
               if m.get("reorder_due_in") is not None else None),
              ("Balance owed", _n(m.get("balance"))), ("Past due", _n(m.get("overdue"))), ("Oldest item overdue", f"{m.get('max_days')} days" if m.get("max_days") else None),
              ("Credit limit used", f"{m['credit_used_pct']}%" if m.get("credit_used_pct") is not None else None),
              ("Risk", "; ".join(m.get("risk_reasons") or []) or "none flagged"), ("Competing supplier", cu.get("competing_supplier")),
              ("Owed, by age", ", ".join(f"{k}: {_n(v)}" for k, v in buckets.items()) or "nothing owed")]
    tables = [
        _table("Open items", ["Type", "Number", "Date", "Due", "Amount", "Balance", "Days overdue"],
               [[a["doc_type"], a["doc_number"], _d(a["doc_date"]), _d(a["due_date"]), _n(a["amount"]), _n(a["balance"]), a["days_overdue"]] for a in aged]),
    ]
    if not receivables_focus:
        tables += [
            _table("Sales by month", ["Month", "Sales", "Gross profit", "Orders"],
                   [[x["period"], _n(x["sales"]), _n(x["gp"]), x["orders"]] for x in (p.get("monthly") or [])]),
            _table("What they buy (2 years)", ["Code", "Product", "Units", "Sales", "Orders", "Last bought"],
                   [[x["sku"], x["name"] or "", f"{_f(x['qty']):g}", _n(x["sales"]), x["orders"], _d(x["last_bought"])] for x in (p.get("products") or [])[:20]]),
            _table("Deals", ["Deal", "Stage", "Value", "Won", "Lost reason", "Rep"],
                   [[x["company_name"], x["stage"], _n(x["expected_value"]), _d(x["won_at"]), x["lost_reason"] or "", x.get("rep_name") or ""]
                    for x in (p.get("deals") or [])]),
            _table("Recent contact", ["When", "Type", "Summary", "Next step", "By"],
                   [[_d(x["occurred_at"]), x["interaction_type"], (x["summary"] or "")[:120], x["next_step"] or "", x.get("by") or ""]
                    for x in (p.get("activity") or [])[:15]]),
            _table("Open follow-ups", ["Due", "Type", "Title"],
                   [[_d(x["due_at"]), x["reminder_type"], x["title"] or ""] for x in (p.get("reminders") or [])]),
        ]
    return _dossier("customer", id_, f"{'Receivables - ' if receivables_focus else ''}{cu.get('name')}", cu.get("customer_code") or "",
                    facts=facts, tables=tables, links=[("Open the customer", f"/crm/customers?customer={id_}")])


def _list_products(search: str) -> List[Dict[str, Any]]:
    from src.services.stock_orders import FAMILY_SQL
    fam = FAMILY_SQL.format(name="fp.name", sku="fp.sku")
    with tx() as c:
        rows = q(c, f"""WITH f AS (SELECT {fam} AS family, fp.sku FROM fin_products fp),
                        st AS (SELECT f.family, SUM(l.qty_remaining) AS q, SUM(l.qty_remaining*l.unit_cost) AS v
                               FROM fin_cost_layers l JOIN f ON f.sku=l.sku GROUP BY 1),
                        sa AS (SELECT f.family, SUM(s.amount) AS s12 FROM v_sales_lines s JOIN f ON f.sku=s.sku
                               WHERE s.invoice_date > (SELECT MAX(invoice_date) FROM v_sales_lines) - 365 GROUP BY 1)
                        SELECT DISTINCT f.family, st.q, st.v, sa.s12 FROM f LEFT JOIN st USING (family) LEFT JOIN sa USING (family)
                        WHERE (st.q > 0 OR sa.s12 > 0) AND (%s = '' OR f.family ILIKE %s)
                        ORDER BY sa.s12 DESC NULLS LAST LIMIT 80""", (search, _like(search)))
    return [{"id": r["family"], "title": r["family"], "subtitle": f"{_f(r['q']):g} in stock ({_n(r['v'])}) · {_n(r['s12'])} sold in 12 months",
             "date": None, "status": ""} for r in rows]


def _dossier_product(id_: str) -> Dict[str, Any]:
    from src.services.stock_orders import FAMILY_SQL
    fam = FAMILY_SQL.format(name="fp.name", sku="fp.sku")
    today = dt.date.today()
    with tx() as c:
        skus = [r["sku"] for r in q(c, f"SELECT fp.sku FROM fin_products fp WHERE {fam} = %s", (id_,))]
        if not skus:
            raise LookupError("Product not found")
        lots = q(c, """SELECT l.sku, b.batch_number, b.expiry_date, b.status, SUM(l.qty_remaining) AS q, SUM(l.qty_remaining*l.unit_cost) AS v
                       FROM fin_cost_layers l LEFT JOIN fin_batches b ON b.id=l.batch_id WHERE l.sku = ANY(%s)
                       GROUP BY 1,2,3,4 HAVING SUM(l.qty_remaining) > 0 ORDER BY b.expiry_date NULLS LAST""", (skus,))
        moves = q(c, """SELECT txn_type, COUNT(*) AS n, SUM(quantity) AS qty, SUM(total_cost) AS cost, MAX(txn_date) AS last
                        FROM fin_inventory_transactions WHERE sku = ANY(%s) AND txn_date > %s GROUP BY 1 ORDER BY 1""",
                  (skus, today - dt.timedelta(days=365)))
        recent = q(c, """SELECT t.txn_date, t.txn_type, t.sku, t.quantity, t.total_cost, t.reference, t.reason FROM fin_inventory_transactions t
                         WHERE t.sku = ANY(%s) AND t.txn_type <> 'OPENING_BALANCE' ORDER BY t.txn_date DESC, t.created_at DESC LIMIT 25""", (skus,))
        monthly = q(c, """SELECT to_char(invoice_date,'YYYY-MM') AS m, SUM(quantity) AS units, SUM(amount) AS sales, SUM(gross_profit) AS gp
                          FROM v_sales_lines WHERE sku = ANY(%s) AND invoice_date > (SELECT MAX(invoice_date) FROM v_sales_lines) - 365
                          GROUP BY 1 ORDER BY 1""", (skus,))
        tops = q(c, """SELECT MAX(customer_name) AS c, SUM(quantity) AS units, SUM(amount) AS sales FROM v_sales_lines
                       WHERE sku = ANY(%s) AND invoice_date > (SELECT MAX(invoice_date) FROM v_sales_lines) - 365
                       GROUP BY customer_pk ORDER BY 3 DESC LIMIT 10""", (skus,))
        orders = q(c, """SELECT r.status, r.requested_qty, r.created_at, r.expected_date, s.name AS supplier FROM replenishment_requests r
                         LEFT JOIN suppliers s ON s.id=r.supplier_id WHERE r.sku = ANY(%s) AND r.status <> 'cancelled'
                         ORDER BY r.created_at DESC LIMIT 10""", (skus,))
    on_hand = sum(_f(l["q"]) for l in lots)
    units12 = sum(_f(m["units"]) for m in monthly)
    daily = units12 / 365 if units12 else 0
    expired = sum(_f(l["v"]) for l in lots if l["expiry_date"] and l["expiry_date"] < today)
    sales12 = sum(_f(m["sales"]) for m in monthly)
    return _dossier(
        "product", id_, f"Product - {id_}", f"{on_hand:g} units in stock",
        facts=[("Product family", id_), ("Codes (lots)", ", ".join(skus[:12]) + (" …" if len(skus) > 12 else "")),
               ("Units in stock", f"{on_hand:g}"), ("Stock value (cost)", _n(sum(_f(l['v']) for l in lots))),
               ("Lots in stock", len(lots)), ("Expired stock value", _n(expired)),
               ("Nearest expiry", _d(next((l["expiry_date"] for l in lots if l["expiry_date"] and l["expiry_date"] >= today), None))),
               ("Units sold, 12 months", f"{units12:g}"), ("Sales, 12 months", _n(sales12)),
               ("Margin, 12 months", f"{round(sum(_f(m['gp']) for m in monthly) / sales12 * 100, 1)}%" if sales12 else None),
               ("Days of cover at 12-month rate", round(on_hand / daily) if daily else None), ("Open stock orders", sum(1 for o in orders if o["status"] in ("recommended", "approved", "ordered")))],
        tables=[_table("Lots in stock", ["Code", "Batch", "Expiry", "Status", "Units", "Value"],
                       [[l["sku"], l["batch_number"] or "", _d(l["expiry_date"]), l["status"] or "", f"{_f(l['q']):g}", _n(l["v"])] for l in lots]),
                _table("Movements, last 12 months", ["Type", "Count", "Quantity", "Cost", "Last"],
                       [[m["txn_type"], m["n"], f"{_f(m['qty']):g}", _n(m["cost"]), _d(m["last"])] for m in moves]),
                _table("Most recent movements", ["Date", "Type", "Code", "Qty", "Cost", "Reference", "Reason"],
                       [[_d(r["txn_date"]), r["txn_type"], r["sku"], f"{_f(r['quantity']):g}", _n(r["total_cost"]), r["reference"] or "", r["reason"] or ""] for r in recent]),
                _table("Sales by month", ["Month", "Units", "Sales", "Margin %"],
                       [[m["m"], f"{_f(m['units']):g}", _n(m["sales"]), f"{round(_f(m['gp']) / _f(m['sales']) * 100, 1)}%" if _f(m["sales"]) else "—"] for m in monthly]),
                _table("Top customers, 12 months", ["Customer", "Units", "Sales"], [[t["c"], f"{_f(t['units']):g}", _n(t["sales"])] for t in tops]),
                _table("Stock orders", ["Status", "Qty", "Raised", "Expected", "Supplier"],
                       [[o["status"], f"{_f(o['requested_qty']):g}", _d(o["created_at"]), _d(o["expected_date"]), o["supplier"] or ""] for o in orders])],
        links=[("Open Stock", "/inventory")])


def _list_stock_orders(search: str) -> List[Dict[str, Any]]:
    with tx() as c:
        rows = q(c, """SELECT r.id::text AS id, COALESCE(fp.name, r.sku) AS name, r.requested_qty, r.status, r.created_at, s.name AS supplier
                       FROM replenishment_requests r LEFT JOIN fin_products fp ON fp.sku=r.sku LEFT JOIN suppliers s ON s.id=r.supplier_id
                       WHERE r.status <> 'cancelled' AND (%s = '' OR fp.name ILIKE %s OR r.sku ILIKE %s OR s.name ILIKE %s)
                       ORDER BY r.created_at DESC LIMIT 60""", (search, _like(search), _like(search), _like(search)))
    return [{"id": r["id"], "title": f"{r['name']} · {_f(r['requested_qty']):g} units", "subtitle": r["supplier"] or "no supplier yet",
             "date": r["created_at"], "status": r["status"]} for r in rows]


def _dossier_stock_order(id_: str) -> Dict[str, Any]:
    with tx() as c:
        r = q1(c, """SELECT r.*, COALESCE(fp.name, r.sku) AS name, s.name AS supplier, b.bill_number, b.bill_date, b.total AS bill_total
                     FROM replenishment_requests r LEFT JOIN fin_products fp ON fp.sku=r.sku LEFT JOIN suppliers s ON s.id=r.supplier_id
                     LEFT JOIN fin_supplier_bills b ON b.id=r.bill_id WHERE r.id=%s::uuid""", (id_,))
        if not r:
            raise LookupError("Stock order not found")
    names = _people([r.get("created_by"), r.get("approved_by")])
    lead = (r["received_at"].date() - r["ordered_at"].date()).days if r.get("received_at") and r.get("ordered_at") else None
    return _dossier(
        "stock_order", id_, f"Stock order - {r['name']}", str(r["status"]),
        facts=[("Product", r["name"]), ("Code", r["sku"]), ("Quantity requested", f"{_f(r['requested_qty']):g}"), ("Status", r["status"]),
               ("Raised", f"{_d(r['created_at'])} by {names.get(str(r.get('created_by')), r.get('created_by') or '—')}"),
               ("Approved", f"{_d(r.get('approved_at'))} by {names.get(str(r.get('approved_by')), '—')}" if r.get("approved_at") else "not yet"),
               ("Ordered", _d(r.get("ordered_at"))), ("Supplier", r.get("supplier")), ("Supplier reference", r.get("po_id")),
               ("Expected", _d(r.get("expected_date"))), ("Unit cost", _n(r.get("unit_cost")) if r.get("unit_cost") else None),
               ("Estimated value", _n(_f(r.get("unit_cost")) * _f(r["requested_qty"])) if r.get("unit_cost") else None),
               ("Received", _d(r.get("received_at"))), ("Quantity received", f"{_f(r.get('received_qty')):g}" if r.get("received_qty") else None),
               ("Supplier bill", f"{r['bill_number']} ({_d(r['bill_date'])}, {_n(r['bill_total'])})" if r.get("bill_number") else "not yet"),
               ("Lead time (ordered to received)", f"{lead} days" if lead is not None else None)],
        texts=[("Notes", r.get("notes"))], links=[("Open Stock Orders", "/operations/purchase-orders?tab=orders")])


# ---------------------------------------------------------------------------
# Periods
# ---------------------------------------------------------------------------

def _period_range(pid: str) -> Tuple[dt.date, dt.date, str]:
    today = dt.date.today()
    if re.fullmatch(r"\d{4}-\d{2}", pid):
        a = dt.date(int(pid[:4]), int(pid[5:]), 1)
        b = (a.replace(day=28) + dt.timedelta(days=4)).replace(day=1) - dt.timedelta(days=1)
        return a, b, a.strftime("%B %Y")
    m = re.fullmatch(r"(\d{4})-Q([1-4])", pid)
    if m:
        y, qn = int(m.group(1)), int(m.group(2))
        a = dt.date(y, 3 * qn - 2, 1)
        b = (dt.date(y, 3 * qn, 28) + dt.timedelta(days=4)).replace(day=1) - dt.timedelta(days=1)
        return a, b, f"Q{qn} {y}"
    if re.fullmatch(r"\d{4}", pid):
        return dt.date(int(pid), 1, 1), dt.date(int(pid), 12, 31), f"Year {pid}"
    m = re.fullmatch(r"(\d{4}-\d{2}-\d{2})_(\d{4}-\d{2}-\d{2})", pid)
    if m:
        a, b = dt.date.fromisoformat(m.group(1)), dt.date.fromisoformat(m.group(2))
        return a, b, f"{a:%d %b %Y} – {b:%d %b %Y}"
    raise ValueError("Unknown period")


def _list_periods(search: str) -> List[Dict[str, Any]]:
    with tx() as c:
        last = q1(c, "SELECT MAX(invoice_date) AS d FROM v_sales_lines")["d"] or dt.date.today()
    out = []
    d = last.replace(day=1)
    for _ in range(12):
        out.append({"id": f"{d:%Y-%m}", "title": d.strftime("%B %Y"), "subtitle": "month", "date": d, "status": ""})
        d = (d - dt.timedelta(days=1)).replace(day=1)
    qn = (last.month - 1) // 3 + 1
    y = last.year
    for _ in range(6):
        out.append({"id": f"{y}-Q{qn}", "title": f"Q{qn} {y}", "subtitle": "quarter", "date": dt.date(y, 3 * qn - 2, 1), "status": ""})
        qn -= 1
        if qn == 0:
            qn, y = 4, y - 1
    for yy in (last.year, last.year - 1, last.year - 2):
        out.append({"id": str(yy), "title": f"Year {yy}", "subtitle": "year", "date": dt.date(yy, 1, 1), "status": ""})
    if search:
        out = [o for o in out if search.lower() in o["title"].lower()]
    return out


def _dossier_period(report_type: str, pid: str) -> Dict[str, Any]:
    a, b, label = _period_range(pid)
    today = dt.date.today()
    span = (b - a).days + 1
    pa, pb = a - dt.timedelta(days=span), a - dt.timedelta(days=1)
    facts: List[Tuple[str, Any]] = [("Period", f"{label} ({a:%d %b %Y} to {b:%d %b %Y})")]
    tables: List[Dict[str, Any]] = []
    gaps: List[str] = []
    with tx() as c:
        last_sale = q1(c, "SELECT MAX(invoice_date) AS d FROM v_sales_lines")["d"]
        if last_sale and b > last_sale:
            gaps.append(f"Sales in the books run to {last_sale:%d %b %Y}; anything after that date in this period is not loaded yet.")
        if report_type in ("sales", "pl", "ar_aging", "executive"):
            s = q1(c, """SELECT SUM(amount) AS s, SUM(gross_profit) AS gp, COUNT(DISTINCT invoice_number) AS inv, COUNT(DISTINCT customer_pk) AS cust,
                                SUM(quantity) AS units FROM v_sales_lines WHERE invoice_date BETWEEN %s AND %s""", (a, b))
            p = q1(c, "SELECT SUM(amount) AS s FROM v_sales_lines WHERE invoice_date BETWEEN %s AND %s", (pa, pb))
            ly = q1(c, "SELECT SUM(amount) AS s FROM v_sales_lines WHERE invoice_date BETWEEN %s AND %s",
                    (a.replace(year=a.year - 1), b.replace(year=b.year - 1, day=min(b.day, 28)) if b.month == 2 else b.replace(year=b.year - 1)))
            facts += [("Sales", _n(s["s"])), ("Gross profit", _n(s["gp"])),
                      ("Gross margin", f"{round(_f(s['gp']) / _f(s['s']) * 100, 1)}%" if _f(s["s"]) else None),
                      ("Invoices", s["inv"]), ("Customers who bought", s["cust"]), ("Units sold", f"{_f(s['units']):g}"),
                      ("Previous period of equal length", _n(p["s"])), ("Same period last year", _n(ly["s"])),
                      ("Change vs last year", f"{round((_f(s['s']) - _f(ly['s'])) / _f(ly['s']) * 100, 1)}%" if _f(ly["s"]) else None)]
            tables.append(_table("Sales by month", ["Month", "Sales", "Gross profit", "Invoices", "Customers"],
                                 [[r["m"], _n(r["s"]), _n(r["gp"]), r["inv"], r["cu"]] for r in q(c, """
                                     SELECT to_char(invoice_date,'YYYY-MM') AS m, SUM(amount) AS s, SUM(gross_profit) AS gp,
                                            COUNT(DISTINCT invoice_number) AS inv, COUNT(DISTINCT customer_pk) AS cu
                                     FROM v_sales_lines WHERE invoice_date BETWEEN %s AND %s GROUP BY 1 ORDER BY 1""", (a, b))]))
            tables.append(_table("Top customers", ["Customer", "Sales", "Margin %"],
                                 [[r["c"], _n(r["s"]), f"{round(_f(r['gp']) / _f(r['s']) * 100, 1)}%" if _f(r["s"]) else "—"] for r in q(c, """
                                     SELECT MAX(customer_name) AS c, SUM(amount) AS s, SUM(gross_profit) AS gp FROM v_sales_lines
                                     WHERE invoice_date BETWEEN %s AND %s GROUP BY customer_pk ORDER BY 2 DESC LIMIT 15""", (a, b))]))
            from src.services.stock_orders import FAMILY_SQL
            tables.append(_table("Top products", ["Product", "Units", "Sales", "Margin %"],
                                 [[r["p"], f"{_f(r['u']):g}", _n(r["s"]), f"{round(_f(r['gp']) / _f(r['s']) * 100, 1)}%" if _f(r["s"]) else "—"] for r in q(c, f"""
                                     SELECT {FAMILY_SQL.format(name="fp.name", sku="s.sku")} AS p, SUM(s.quantity) AS u, SUM(s.amount) AS s, SUM(s.gross_profit) AS gp
                                     FROM v_sales_lines s LEFT JOIN fin_products fp ON fp.sku=s.sku
                                     WHERE s.invoice_date BETWEEN %s AND %s GROUP BY 1 ORDER BY 3 DESC LIMIT 15""", (a, b))]))
        if report_type in ("inventory",):
            mv = q(c, """SELECT txn_type, COUNT(*) AS n, SUM(quantity) AS qty, SUM(total_cost) AS cost FROM fin_inventory_transactions
                         WHERE txn_date BETWEEN %s AND %s AND txn_type <> 'OPENING_BALANCE' GROUP BY 1 ORDER BY 1""", (a, b))
            facts += [(f"{m['txn_type'].replace('_', ' ').title()} movements", f"{m['n']} ({_f(m['qty']):g} units, {_n(m['cost'])})") for m in mv]
            if not mv:
                gaps.append("No stock movements are recorded in ACE Books for this period (movements before the cut-over are held as opening balances and sales history).")
            su = q1(c, "SELECT SUM(quantity) AS u, SUM(cost) AS c FROM v_sales_lines WHERE invoice_date BETWEEN %s AND %s", (a, b))
            facts += [("Units sold (sales lines)", f"{_f(su['u']):g}"), ("Cost of goods sold", _n(su["c"]))]
            adj = q(c, """SELECT adjustment_number, adjustment_date, reason_code, status, total_value, notes FROM fin_stock_adjustments
                          WHERE adjustment_date BETWEEN %s AND %s ORDER BY adjustment_date""", (a, b))
            tables.append(_table("Stock adjustments", ["Number", "Date", "Reason", "Status", "Value", "Notes"],
                                 [[x["adjustment_number"], _d(x["adjustment_date"]), x["reason_code"], x["status"], _n(x["total_value"]), x["notes"] or ""] for x in adj]))
        if report_type in ("compliance",):
            dv = q(c, """SELECT deviation_id, classification, status, created_at, closed_at, target_close_date FROM deviation_reports
                         WHERE created_at::date BETWEEN %s AND %s OR closed_at::date BETWEEN %s AND %s ORDER BY created_at""", (a, b, a, b))
            rc = q(c, """SELECT recall_id, product_name, batch_number, status, initiation_date FROM recall_cases
                         WHERE COALESCE(initiation_date, created_at::date) BETWEEN %s AND %s""", (a, b))
            au = q(c, """SELECT audit_type, department, scheduled_date, status, completed_at FROM audit_schedule
                         WHERE scheduled_date BETWEEN %s AND %s OR completed_at::date BETWEEN %s AND %s""", (a, b, a, b))
            mt = q(c, """SELECT e.equipment_name, m.maintenance_type, m.next_maintenance_date, m.status, m.completed_at FROM maintenance_schedule m
                         JOIN equipment_registry e ON e.id=m.equipment_id WHERE m.next_maintenance_date BETWEEN %s AND %s OR m.completed_at::date BETWEEN %s AND %s""", (a, b, a, b))
            ca = q(c, """SELECT activity_name, scheduled_date, status, department FROM compliance_activity_log
                         WHERE scheduled_date BETWEEN %s AND %s""", (a, b))
            facts += [("Deviations raised", sum(1 for x in dv if x["created_at"].date() >= a)),
                      ("Deviations closed", sum(1 for x in dv if x["closed_at"] and a <= x["closed_at"].date() <= b)),
                      ("Recalls opened", len(rc)), ("Audits scheduled / completed", f"{len(au)} / {sum(1 for x in au if x['status'] == 'completed')}"),
                      ("Maintenance jobs due / completed", f"{len(mt)} / {sum(1 for x in mt if x['completed_at'])}"),
                      ("Compliance activities", len(ca))]
            try:
                from src.services.quality_hub import overview
                o = overview()
                facts.append(("Compliance score today", o["compliance_score"]))
            except Exception:
                pass
            tables += [_table("Deviations", ["ID", "Class", "Status", "Raised", "Closed", "Target"],
                              [[x["deviation_id"], x["classification"], x["status"], _d(x["created_at"]), _d(x["closed_at"]), _d(x["target_close_date"])] for x in dv]),
                       _table("Recalls", ["Recall", "Product", "Batch", "Status", "Initiated"],
                              [[x["recall_id"], x["product_name"], x["batch_number"], x["status"], _d(x["initiation_date"])] for x in rc]),
                       _table("Audits", ["Type", "Department", "Scheduled", "Status", "Completed"],
                              [[x["audit_type"], x["department"], _d(x["scheduled_date"]), x["status"], _d(x["completed_at"])] for x in au]),
                       _table("Maintenance", ["Equipment", "Type", "Due", "Status", "Completed"],
                              [[x["equipment_name"], x["maintenance_type"], _d(x["next_maintenance_date"]), x["status"], _d(x["completed_at"])] for x in mt]),
                       _table("Compliance activities", ["Activity", "Scheduled", "Status", "Department"],
                              [[x["activity_name"], _d(x["scheduled_date"]), x["status"], x["department"]] for x in ca])]
        if report_type == "frontdesk":
            w = q(c, """SELECT status, purpose, COUNT(*) AS n FROM frontdesk_walk_ins WHERE created_at::date BETWEEN %s AND %s
                        GROUP BY 1,2 ORDER BY 3 DESC""", (a, b))
            facts.append(("Walk-ins", sum(x["n"] for x in w)))
            tables.append(_table("Walk-ins by status and purpose", ["Status", "Purpose", "Count"], [[x["status"], x["purpose"] or "", x["n"]] for x in w]))
    if report_type == "pl":
        from src.fin import reports
        from src.fin.context import resolve_entity
        with tx() as c:
            e = resolve_entity(c, None)
            inc = reports.income_statement(c, e, a, min(b, today), pa, pb)
        facts += [("Revenue (ACE Books)", _n(inc["revenue"])), ("Cost of sales", _n(inc["cost_of_sales"])), ("Gross profit (books)", _n(inc["gross_profit"])),
                  ("Operating profit", _n(inc["operating_profit"])), ("Net profit", _n(inc["net_profit"]))]
        for sec in inc.get("sections") or []:
            tables.append(_table(f"P&L - {sec['title']}", ["Account", "This period", "Previous period"],
                                 [[l.get("name") or l.get("account") or l.get("code"), _n(l.get("amount")), _n(l.get("compare_amount") or l.get("compare"))]
                                  for l in sec.get("lines") or []]))
        if not _f(inc["revenue"]):
            gaps.append("ACE Books holds the months before the 1 Jul 2026 cut-over as one migrated opening figure, so a monthly P&L for them "
                        "comes from the sales lines above rather than the ledger.")
    if report_type == "ar_aging":
        from src.fin.readmodel import ar_rows
        on = min(b, today)
        rows = ar_rows(on)
        bk = defaultdict(float)
        per = defaultdict(lambda: {"b": 0.0, "o": 0.0})
        for r in rows:
            bk[r["bucket"]] += r["balance"]
            per[r["name"] or r["customer_id"]]["b"] += r["balance"]
            if r["days_overdue"] > 90:
                per[r["name"] or r["customer_id"]]["o"] += r["balance"]
        facts += [(f"Owed {k.replace('_', '-').replace('91-plus', '90+')} days", _n(v)) for k, v in sorted(bk.items())]
        facts.append(("Total owed", _n(sum(bk.values()))))
        tables.append(_table(f"Largest balances at {on:%d %b %Y}", ["Customer", "Balance", "Over 90 days"],
                             [[k, _n(v["b"]), _n(v["o"])] for k, v in sorted(per.items(), key=lambda kv: -kv[1]["b"])[:25]]))
    return _dossier("period", pid, f"{TYPE_BY_KEY.get(report_type, {}).get('name', 'Report')} - {label}", label,
                    facts=facts, tables=tables, gaps=gaps)


def _dossier_current() -> Dict[str, Any]:
    from src.services.executive import overview
    o = overview()
    f, s, st, ql, p = o.get("finance") or {}, o.get("sales") or {}, o.get("stock") or {}, o.get("quality") or {}, o.get("people") or {}
    facts = [("Revenue this year", _n(f.get("revenue_ytd"))), ("Gross profit this year", _n(f.get("gross_profit_ytd"))),
             ("Net profit this year", _n(f.get("net_profit_ytd"))), ("Cash & bank", _n(f.get("cash"))),
             ("Customers owe", _n((f.get("receivables") or {}).get("total"))), ("Over 90 days", _n((f.get("receivables") or {}).get("over_90"))),
             ("Owed to suppliers", _n((f.get("payables") or {}).get("total"))), ("Stock value", _n(st.get("value"))),
             ("Days of stock cover", st.get("cover_days")), ("Sales, last 12 months", _n(s.get("last365"))),
             ("Sales growth year to date", f"{s.get('ytd_growth_pct')}%"), ("Compliance score", ql.get("compliance_score")),
             ("Expired stock", _n(ql.get("expired_value"))), ("Team members", p.get("headcount")), ("Working capital", _n(o.get("working_capital"))),
             ("Books as at", _d(f.get("aged_on")))]
    return _dossier("current", "now", "Executive report - the company today", _d(dt.date.today()), facts=facts,
                    tables=[_table("Needs attention", ["Level", "Item", "Detail"], [[a["level"], a["title"], a["detail"]] for a in o.get("attention") or []]),
                            _table("Top customers, 12 months", ["Customer", "Sales", "Share"],
                                   [[c["name"], _n(c["sales"]), f"{c['share_pct']}%"] for c in s.get("top_customers") or []])],
                    links=[("Open Executive Overview", "/executive")])


# ---------------------------------------------------------------------------
# dispatch
# ---------------------------------------------------------------------------

LISTERS: Dict[str, Callable[[str], List[Dict[str, Any]]]] = {
    "deviation": _list_deviations, "capa": lambda s: _list_deviations(s, capa_only=True), "recall": _list_recalls,
    "audit": _list_audits, "maintenance": _list_maintenance, "batch": _list_batches, "sale": _list_sales,
    "customer": _list_customers, "product": _list_products, "stock_order": _list_stock_orders, "period": _list_periods,
    "current": lambda s: [{"id": "now", "title": "The company today", "subtitle": "all departments", "date": dt.date.today(), "status": ""}],
}


def list_subjects(kind: str, search: str = "") -> List[Dict[str, Any]]:
    if kind not in LISTERS:
        raise ValueError("Unknown record type")
    return LISTERS[kind]((search or "").strip())


def dossier(report_type: str, kind: str, id_: str) -> Dict[str, Any]:
    t = TYPE_BY_KEY.get(report_type)
    if not t or kind not in t["kinds"]:
        raise ValueError(f"A {t['name'] if t else report_type} is not written on {KIND_LABEL.get(kind, kind)}")
    if kind == "deviation":
        return _dossier_deviation(id_)
    if kind == "capa":
        return _dossier_deviation(id_, capa_focus=True)
    if kind == "recall":
        return _dossier_recall(id_)
    if kind == "audit":
        return _dossier_audit(id_)
    if kind == "maintenance":
        return _dossier_maintenance(id_)
    if kind == "batch":
        return _dossier_batch(id_)
    if kind == "sale":
        return _dossier_sale(id_)
    if kind == "customer":
        return _dossier_customer(id_, receivables_focus=report_type == "ar_aging")
    if kind == "product":
        return _dossier_product(id_)
    if kind == "stock_order":
        return _dossier_stock_order(id_)
    if kind == "period":
        return _dossier_period(report_type, id_)
    if kind == "current":
        return _dossier_current()
    raise ValueError("Unknown record type")


# ---------------------------------------------------------------------------
# report sections by what the report is about
# ---------------------------------------------------------------------------

_S = _section
SECTIONS: Dict[str, List[Dict[str, Any]]] = {
    "deviation": [
        _S("summary", "Summary", "In 3-4 sentences: which deviation, classification, what happened, current status and whether it is on time.", order=1),
        _S("event", "Description of the Event", "Describe the observation, when it was raised, what triggered it and the department/person responsible, strictly from the record.", order=2),
        _S("impact", "Impact Assessment", "State the recorded impact assessment. If none is recorded, say so and list what should be assessed (product quality, patient safety, stock, regulatory).", order=3),
        _S("investigation", "Investigation & Root Cause", "Summarise the recorded investigation findings. If root cause is not documented, state that plainly.", order=4),
        _S("capa", "CAPA Plan & Status", "Go through each recorded CAPA action with owner, due date and status; flag overdue ones. If none, say CAPA must be defined.", order=5),
        _S("timeline", "Timeline", "Chronological list of the recorded dates: raised, investigation start, target close, CAPA due dates, closure.", order=6),
        _S("conclusion", "Conclusion & Next Steps", "What is needed to close this deviation, by whom, based on the gaps and open items in the record.", order=7),
    ],
    "capa": [
        _S("summary", "Summary", "Which deviation the CAPA belongs to, how many actions, how many complete and overdue.", order=1),
        _S("background", "Background", "Brief description of the deviation that required corrective and preventive action.", order=2),
        _S("actions", "Corrective & Preventive Actions", "Each action: what, type, owner, due date, status. Separate corrective from preventive where recorded.", order=3),
        _S("effectiveness", "Progress & Effectiveness", "What is complete, what is late, and whether effectiveness can be judged from the record.", order=4),
        _S("next", "Next Steps", "What must happen to complete the CAPA and close the deviation.", order=5),
    ],
    "recall": [
        _S("summary", "Summary", "Recall ID, product and batch, reason, severity, status and progress in one paragraph.", order=1),
        _S("product", "Product & Batch", "Product, SKU, batch, expiry, status in ACE Books and units still held.", order=2),
        _S("reason", "Reason & Regulatory Notification", "The recorded reason, regulatory authority and whether NAFDAC was notified.", order=3),
        _S("trace", "Distribution & Customer Trace", "Customers who received the batch, quantities, contact status - from the customer trace table.", order=4),
        _S("returns", "Returns Progress", "Units sold versus returned, customers contacted, what remains outstanding.", order=5),
        _S("closeout", "Status & Close-out", "What is needed to close the recall, based on the record's gaps.", order=6),
    ],
    "audit": [
        _S("summary", "Summary", "Audit type, department, date, status and headline outcome.", order=1),
        _S("scope", "Scope & Schedule", "Risk level, frequency, schedule and who was assigned.", order=2),
        _S("findings", "Findings", "The recorded audit notes/findings; if none, say findings were not recorded.", order=3),
        _S("deviations", "Deviations Raised", "Deviations raised from this audit and their status.", order=4),
        _S("followup", "Follow-up", "Next audit and actions needed, from the record.", order=5),
    ],
    "maintenance": [
        _S("summary", "Summary", "Equipment, maintenance type, status and whether it is on schedule.", order=1),
        _S("equipment", "Equipment Details", "Equipment identity, location, calibration status.", order=2),
        _S("work", "Work Performed / Due", "What was done (completion notes, performer) or what is due.", order=3),
        _S("history", "Maintenance History", "The equipment's past jobs and any deviations.", order=4),
        _S("next", "Next Steps", "Next due date and actions.", order=5),
    ],
    "batch": [
        _S("summary", "Summary", "Product, batch, QC decision and current stock status.", order=1),
        _S("registration", "Registration & Documents", "Supplier, NAFDAC registration, quantities, expiry, who registered it.", order=2),
        _S("decision", "QC Decision", "Release/reject decision, date, by whom, rejection reason if any.", order=3),
        _S("stock", "Stock & Movements", "Units in stock, value, and the batch's movements in ACE Books.", order=4),
        _S("issues", "Deviations & Recalls", "Any deviations or recalls on this batch; otherwise state none.", order=5),
    ],
    "sale": [
        _S("summary", "Summary", "Invoice, customer, date, value, margin and payment status.", order=1),
        _S("lines", "What Was Sold", "The lines: products, quantities, amounts, with the best and weakest margins.", order=2),
        _S("profit", "Profitability", "Cost, gross profit and margin, and how this sale compares with the customer's normal buying.", order=3),
        _S("payment", "Payment Status", "Due date, balance outstanding and status.", order=4),
    ],
    "customer": [
        _S("summary", "Summary", "Who the customer is, how much they buy, trend, margin and what they owe.", order=1),
        _S("buying", "Buying Pattern", "Sales by month, order frequency and trend.", order=2),
        _S("products", "Products", "What they buy most and margins.", order=3),
        _S("account", "Account & Receivables", "Balance, ageing of open items, credit limit and terms.", order=4),
        _S("relationship", "Relationship", "Deals, recent contact and owner.", order=5),
        _S("actions", "Recommended Actions", "Specific next steps for this account from the facts above.", order=6),
    ],
    "customer_ar": [
        _S("summary", "Summary", "What the customer owes, how much is overdue and how late.", order=1),
        _S("items", "Open Items", "Each open invoice/credit with dates, balance and days overdue.", order=2),
        _S("terms", "Terms & Credit", "Payment terms and credit limit against the balance.", order=3),
        _S("actions", "Collection Actions", "Specific collection steps from the facts.", order=4),
    ],
    "product": [
        _S("summary", "Summary", "Product, stock on hand and value, cover, sales and margin.", order=1),
        _S("stock", "Stock & Lots", "Lots in stock with expiry and status; expired or near-expiry stock.", order=2),
        _S("movements", "Movements", "Stock movements by type and the most recent movements.", order=3),
        _S("demand", "Sales & Demand", "Sales by month, top customers.", order=4),
        _S("supply", "Replenishment", "Open stock orders and whether cover is enough.", order=5),
    ],
    "stock_order": [
        _S("summary", "Summary", "Product, quantity, supplier, status.", order=1),
        _S("timeline", "Timeline", "Raised, approved, ordered, expected, received - with who.", order=2),
        _S("cost", "Cost & Bill", "Unit cost, value, supplier bill.", order=3),
        _S("performance", "Supplier Performance", "Lead time and whether it arrived on time, from the record.", order=4),
    ],
    "period": [
        _S("summary", "Summary", "The headline figures for the period and the comparison.", order=1),
        _S("detail", "Detail", "Walk through the tables for the period - what drove the result.", order=2),
        _S("comparison", "Comparison", "Versus the previous period and last year where given.", order=3),
        _S("issues", "Points to Note", "Risks, gaps in the data and notable items.", order=4),
        _S("actions", "Recommendations", "Specific actions from the figures.", order=5),
    ],
    "current": [
        _S("summary", "Summary", "The company today in one paragraph.", order=1),
        _S("finance", "Finance", "Profit, cash, receivables, payables.", order=2),
        _S("operations", "Sales, Stock & Quality", "Sales trend, stock position, quality and compliance.", order=3),
        _S("attention", "What Needs Attention", "The attention list, most serious first.", order=4),
        _S("actions", "Recommendations", "Specific actions for management.", order=5),
    ],
}


def sections_for(report_type: str, kind: str) -> List[Dict[str, Any]]:
    if kind == "customer" and report_type == "ar_aging":
        return SECTIONS["customer_ar"]
    return SECTIONS.get(kind) or SECTIONS["period"]


def dossier_markdown(d: Dict[str, Any]) -> str:
    """The gathered record, as the report's appendix (exactly what the report was written from)."""
    out = ["## Appendix: Record details (as gathered from ACE)", ""]
    out += ["| Item | Value |", "|---|---|"] + [f"| {f['label']} | {str(f['value']).replace('|', '/')} |" for f in d["facts"]]
    for t in d["texts"]:
        out += ["", f"**{t['label']}:** {t['value']}"]
    for t in d["tables"]:
        out += ["", f"### {t['title']}", "", "| " + " | ".join(t["columns"]) + " |", "|" + "---|" * len(t["columns"])]
        out += ["| " + " | ".join(str(c).replace("|", "/") for c in r) + " |" for r in t["rows"][:60]]
    if d["gaps"]:
        out += ["", "**Not recorded in the system:**"] + [f"- {g}" for g in d["gaps"]]
    out += ["", f"_Gathered {d['gathered_at'][:16].replace('T', ' ')} UTC._"]
    return "\n".join(out)
