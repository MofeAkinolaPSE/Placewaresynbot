"""Operations -> accounting: postings triggered by other ACE modules.

Frontdesk finance approval calls `post_frontdesk_invoice_safe`. It runs in
its own transaction so a books problem (closed period, unknown product,
missing stock) can never block the operational workflow - instead the
failure is recorded in fin_source_postings, shown on the Control Tower and
in the period-close checklist, and can be retried once fixed.
"""
from __future__ import annotations

import datetime as dt
import logging
from typing import Any, Dict, Optional

from src.fin import sales
from src.fin.context import system_context
from src.fin.db import ex, q, q1, tx
from src.fin.errors import FinError

log = logging.getLogger(__name__)


# document_type marks an invoice a user deliberately kept out of the books (e.g. a test);
# such an invoice is never posted, not even by retry or backfill.
EXCLUDED_MARK = "EXCLUDED"


def _record(conn, entity_id: str, source_id: str, source_ref: Optional[str], status: str,
            document_id: Optional[str] = None, message: Optional[str] = None, document_type: str = "SALES_INVOICE") -> None:
    ex(conn, """INSERT INTO fin_source_postings (legal_entity_id, source_type, source_id, source_ref, status, document_type,
                document_id, message) VALUES (%s,'FRONTDESK',%s,%s,%s,%s,%s,%s)
                ON CONFLICT (legal_entity_id, source_type, source_id) DO UPDATE SET status=EXCLUDED.status,
                document_type=EXCLUDED.document_type, document_id=EXCLUDED.document_id, message=EXCLUDED.message,
                source_ref=EXCLUDED.source_ref, attempts=fin_source_postings.attempts + 1, updated_at=now()""",
       (entity_id, source_id, source_ref, status, document_type, document_id, message))


def exclude_frontdesk_invoice(conn, ctx, frontdesk_invoice_id: str, reason: str) -> Dict[str, Any]:
    """Keep an operational invoice out of the books for good (tests, duplicates of Sage records)."""
    ctx.require("sales.invoice.post")
    if not (reason or "").strip():
        from src.fin.errors import invalid
        raise invalid("Give a reason for excluding this invoice from the books")
    fd = q1(conn, "SELECT invoice_number FROM frontdesk_invoices WHERE id=%s", (frontdesk_invoice_id,))
    if not fd:
        raise FinError("RESOURCE_NOT_FOUND", "Frontdesk invoice not found")
    done = q1(conn, """SELECT status FROM fin_source_postings WHERE legal_entity_id=%s AND source_type='FRONTDESK' AND source_id=%s""",
              (ctx.entity_id, str(frontdesk_invoice_id)))
    if done and done["status"] == "POSTED":
        raise FinError("INVALID_STATE_TRANSITION", f"{fd['invoice_number']} is already in the books - void its sales invoice instead")
    _record(conn, ctx.entity_id, str(frontdesk_invoice_id), fd["invoice_number"], "SKIPPED",
            message=f"Excluded from the books: {reason.strip()}", document_type=EXCLUDED_MARK)
    from src.fin import audit
    audit.record(conn, ctx, "FRONTDESK_INVOICE_EXCLUDED", "frontdesk_invoice", str(frontdesk_invoice_id), ref=fd["invoice_number"], reason=reason)
    return {"id": str(frontdesk_invoice_id), "invoice_number": fd["invoice_number"], "status": "SKIPPED"}


def unposted_frontdesk(conn, entity_id: str) -> list:
    """Approved Frontdesk invoices on/after cut-over with no posting record at all."""
    return q(conn, """SELECT f.id, f.invoice_number, f.status, f.customer_name, f.total_amount AS total, (f.created_at AT TIME ZONE 'Africa/Lagos')::date AS invoice_date
                      FROM frontdesk_invoices f, fin_settings s
                      WHERE s.legal_entity_id=%s AND s.cutover_date IS NOT NULL
                        AND f.status IN ('finance_approved','dispatched','completed')
                        AND (f.created_at AT TIME ZONE 'Africa/Lagos')::date >= s.cutover_date
                        AND NOT EXISTS (SELECT 1 FROM fin_source_postings p WHERE p.legal_entity_id=s.legal_entity_id
                                        AND p.source_type='FRONTDESK' AND p.source_id=f.id::text)
                      ORDER BY f.created_at""", (entity_id,))


def post_frontdesk_invoice(frontdesk_invoice_id: str, actor: str = "frontdesk", automatic: bool = False) -> Dict[str, Any]:
    """Post (or retry) one Frontdesk invoice. Raises nothing: returns the outcome.
    `automatic` is the Frontdesk approval hook; it respects the auto-post setting
    (paused while a period is being loaded from Sage). Manual retry/backfill does not."""
    ref = None
    try:
        with tx() as conn:
            ctx = system_context(conn, actor=actor)
            s = q1(conn, "SELECT auto_post_frontdesk, cutover_date FROM fin_settings WHERE legal_entity_id=%s", (ctx.entity_id,))
            fd = q1(conn, """SELECT invoice_number, status, (created_at AT TIME ZONE 'Africa/Lagos')::date AS d
                             FROM frontdesk_invoices WHERE id=%s""", (frontdesk_invoice_id,))
            if not fd:
                return {"status": "SKIPPED", "message": "Frontdesk invoice not found"}
            ref = fd["invoice_number"]
            prior = q1(conn, """SELECT document_type FROM fin_source_postings WHERE legal_entity_id=%s AND source_type='FRONTDESK'
                                AND source_id=%s""", (ctx.entity_id, str(frontdesk_invoice_id)))
            if prior and prior["document_type"] == EXCLUDED_MARK:
                return {"status": "SKIPPED", "message": "Excluded from the books"}
            if automatic and s and not s["auto_post_frontdesk"]:
                return {"status": "SKIPPED", "message": "Automatic posting to ACE Books is paused (Setup > Settings)"}
            if fd["status"] not in ("finance_approved", "dispatched", "completed"):
                return {"status": "SKIPPED", "message": f"Invoice is {fd['status']}"}
            if not s or not s["cutover_date"]:
                return {"status": "SKIPPED", "message": "ACE Books is not live yet (no cut-over date)"}
            if s and s["cutover_date"] and fd["d"] < s["cutover_date"]:
                _record(conn, ctx.entity_id, str(frontdesk_invoice_id), ref, "SKIPPED",
                        message=f"Dated before the ACE Books cut-over ({s['cutover_date']}) - already in the opening balances")
                return {"status": "SKIPPED", "message": "Before cut-over"}
            inv = sales.post_from_frontdesk(conn, ctx, str(frontdesk_invoice_id))
            _record(conn, ctx.entity_id, str(frontdesk_invoice_id), ref, "POSTED", str(inv["id"]),
                    f"Posted as {inv['invoice_number']}")
            return {"status": "POSTED", "invoice_id": str(inv["id"]), "invoice_number": inv["invoice_number"]}
    except FinError as e:
        message = e.message
    except Exception as e:  # never break the operational workflow
        log.exception("ACE Books posting failed for frontdesk invoice %s", frontdesk_invoice_id)
        message = f"Unexpected error: {e}"
    try:
        with tx() as conn:
            ctx = system_context(conn, actor=actor)
            _record(conn, ctx.entity_id, str(frontdesk_invoice_id), ref, "FAILED", message=message)
    except Exception:
        log.exception("Could not record failed posting for %s", frontdesk_invoice_id)
    return {"status": "FAILED", "message": message}


def backfill_frontdesk(date_from: dt.date, date_to: dt.date, actor: str) -> Dict[str, Any]:
    with tx() as conn:
        ids = [r["id"] for r in q(conn, """SELECT i.id FROM frontdesk_invoices i WHERE i.status IN ('finance_approved','dispatched','completed')
                                           AND (i.created_at AT TIME ZONE 'Africa/Lagos')::date BETWEEN %s AND %s
                                           ORDER BY i.created_at""", (date_from, date_to))]
    results = [post_frontdesk_invoice(str(i), actor) for i in ids]
    summary: Dict[str, int] = {}
    for r in results:
        summary[r["status"]] = summary.get(r["status"], 0) + 1
    return {"processed": len(ids), "summary": summary, "results": results}
