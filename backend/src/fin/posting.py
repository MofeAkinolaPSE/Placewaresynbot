"""PostingService — the only way anything reaches the General Ledger.

    business event -> validate -> accounting event -> journal -> lines -> POST -> audit

Everything runs on the caller's connection inside one transaction; if any
step fails nothing is written. Posting is idempotent: the same idempotency
key returns the journal already posted instead of creating a second one.

Operational modules (sales, payables, inventory, banking, assets) call
`post_system()` with lines produced by `fin.rules`. People call the manual
journal workflow: draft -> submit -> approve -> post, and `reverse()` to
correct - posted history is never edited.
"""
from __future__ import annotations

import datetime as dt
from decimal import Decimal
from typing import Any, Dict, Iterable, List, Optional

import psycopg2

from src.fin import audit
from src.fin.db import ZERO, ex, jsonb, money, q, q1
from src.fin.errors import FinError, from_db_error, invalid, not_found
from src.fin.numbering import next_number
from src.fin.periods import period_for, require_open

LINE_DIMENSIONS = ("branch_id", "department_id", "cost_centre_id", "customer_id", "supplier_id", "product_sku")


# ---------------------------------------------------------------------------
# Line normalisation / validation
# ---------------------------------------------------------------------------

def _resolve_accounts(conn, entity_id: str, lines: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    ids = {str(l["account_id"]) for l in lines if l.get("account_id")}
    codes = {str(l["account_code"]).strip() for l in lines if l.get("account_code") and not l.get("account_id")}
    found: Dict[str, Dict[str, Any]] = {}
    if ids:
        for a in q(conn, "SELECT * FROM fin_accounts WHERE legal_entity_id=%s AND id = ANY(%s::uuid[])",
                   (entity_id, list(ids))):
            found[str(a["id"])] = a
    if codes:
        for a in q(conn, "SELECT * FROM fin_accounts WHERE legal_entity_id=%s AND code = ANY(%s)",
                   (entity_id, list(codes))):
            found["code:" + a["code"]] = a
    return found


def normalise_lines(conn, ctx, lines: Iterable[Dict[str, Any]], *, manual: bool,
                    require_balanced: bool = True) -> List[Dict[str, Any]]:
    raw = [dict(l) for l in lines]
    accounts = _resolve_accounts(conn, ctx.entity_id, raw)
    out: List[Dict[str, Any]] = []
    for i, l in enumerate(raw, start=1):
        key = str(l["account_id"]) if l.get("account_id") else "code:" + str(l.get("account_code") or "").strip()
        acct = accounts.get(key)
        if not acct:
            raise FinError("RESOURCE_NOT_FOUND", f"Line {i}: account not found in this company",
                           {"line": i, "account": l.get("account_id") or l.get("account_code")})
        debit, credit = money(l.get("debit")), money(l.get("credit"))
        if debit < 0 or credit < 0:
            raise invalid(f"Line {i}: amounts cannot be negative; use the other column", line=i)
        if debit > 0 and credit > 0:
            raise invalid(f"Line {i}: a line is either a debit or a credit, not both", line=i)
        if debit == 0 and credit == 0:
            continue  # zero lines carry no accounting meaning
        if acct["status"] != "ACTIVE":
            raise FinError("ACCOUNT_INACTIVE", f"Line {i}: account {acct['code']} {acct['name']} is inactive",
                           {"line": i, "account": acct["code"]})
        if not acct["is_postable"]:
            raise FinError("ACCOUNT_NOT_POSTABLE", f"Line {i}: {acct['code']} is a header account",
                           {"line": i, "account": acct["code"]})
        if manual and acct["is_control"] and not ctx.can("accounting.journal.control"):
            raise FinError("CONTROL_ACCOUNT",
                           f"Line {i}: {acct['code']} {acct['name']} is a control account fed by its subledger",
                           {"line": i, "account": acct["code"]})
        row = {"account_id": str(acct["id"]), "account_code": acct["code"], "account_name": acct["name"],
               "debit": debit, "credit": credit, "description": (l.get("description") or None)}
        for d in LINE_DIMENSIONS:
            row[d] = l.get(d) or None
        out.append(row)
    if require_balanced:
        check_balanced(out)
    return out


def check_balanced(lines: List[Dict[str, Any]]) -> None:
    dr = sum((l["debit"] for l in lines), ZERO)
    cr = sum((l["credit"] for l in lines), ZERO)
    if len(lines) < 2:
        raise FinError("UNBALANCED_JOURNAL", "A journal needs at least one debit and one credit line")
    if dr != cr:
        raise FinError("UNBALANCED_JOURNAL", f"Journal is out of balance by ₦{abs(dr - cr):,.2f}",
                       {"total_debit": str(dr), "total_credit": str(cr), "difference": str(dr - cr)})
    if dr == 0:
        raise FinError("UNBALANCED_JOURNAL", "Journal has no value")


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------

def _insert_journal(conn, ctx, *, journal_date: dt.date, period_id: str, lines: List[Dict[str, Any]],
                    journal_type: str, description: Optional[str], source_type: Optional[str],
                    source_id: Optional[str], source_ref: Optional[str], event_id: Optional[str],
                    idempotency_key: Optional[str]) -> Dict[str, Any]:
    number = next_number(conn, ctx.entity_id, "JOURNAL")
    dr = sum((l["debit"] for l in lines), ZERO)
    cr = sum((l["credit"] for l in lines), ZERO)
    j = q1(conn, """
        INSERT INTO fin_journals (legal_entity_id, journal_number, journal_date, period_id, event_id, journal_type,
                                  source_type, source_id, source_ref, description, status, total_debit, total_credit,
                                  idempotency_key, created_by)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'DRAFT',%s,%s,%s,%s) RETURNING *
    """, (ctx.entity_id, number, journal_date, period_id, event_id, journal_type, source_type,
          str(source_id) if source_id is not None else None, source_ref, description, dr, cr,
          idempotency_key, ctx.actor_id))
    _insert_lines(conn, j["id"], lines)
    return j


def _insert_lines(conn, journal_id: str, lines: List[Dict[str, Any]]) -> None:
    with conn.cursor() as cur:
        for n, l in enumerate(lines, start=1):
            cur.execute("""
                INSERT INTO fin_journal_lines (journal_id, line_no, account_id, description, debit, credit,
                    base_debit, base_credit, branch_id, department_id, cost_centre_id, customer_id, supplier_id, product_sku)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            """, (journal_id, n, l["account_id"], l.get("description"), l["debit"], l["credit"],
                  l["debit"], l["credit"], l.get("branch_id"), l.get("department_id"), l.get("cost_centre_id"),
                  l.get("customer_id"), l.get("supplier_id"), l.get("product_sku")))


def _mark_posted(conn, ctx, journal_id: str) -> Dict[str, Any]:
    """Flip to POSTED; the DB trigger re-verifies balance, accounts and period."""
    try:
        with conn.cursor() as cur:
            cur.execute("SAVEPOINT fin_post")
        j = q1(conn, """UPDATE fin_journals SET status='POSTED', posted_by=%s, posted_at=now()
                        WHERE id=%s RETURNING *""", (ctx.actor_id, journal_id))
        with conn.cursor() as cur:
            cur.execute("RELEASE SAVEPOINT fin_post")
        return j
    except psycopg2.Error as exc:
        err = from_db_error(exc)
        if err:
            raise err from exc
        raise


def get_journal(conn, entity_id: str, journal_id: str) -> Dict[str, Any]:
    j = q1(conn, """SELECT j.*, p.name AS period_name, p.status AS period_status
                    FROM fin_journals j JOIN fin_periods p ON p.id = j.period_id
                    WHERE j.id=%s AND j.legal_entity_id=%s""", (journal_id, entity_id))
    if not j:
        raise not_found("Journal", journal_id)
    j["lines"] = q(conn, """SELECT l.*, a.code AS account_code, a.name AS account_name, a.account_type
                            FROM fin_journal_lines l JOIN fin_accounts a ON a.id = l.account_id
                            WHERE l.journal_id=%s ORDER BY l.line_no""", (journal_id,))
    return j


def _existing_by_key(conn, entity_id: str, key: Optional[str]) -> Optional[Dict[str, Any]]:
    if not key:
        return None
    return q1(conn, "SELECT id FROM fin_journals WHERE legal_entity_id=%s AND idempotency_key=%s", (entity_id, key))


# ---------------------------------------------------------------------------
# System postings (sales, payables, inventory, banking, assets ...)
# ---------------------------------------------------------------------------

def post_system(conn, ctx, *, event_type: str, journal_date: dt.date, lines: List[Dict[str, Any]],
                description: str, source_type: str, source_id: Any, source_ref: Optional[str] = None,
                idempotency_key: Optional[str] = None, journal_type: str = "SYSTEM",
                metadata: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    key = idempotency_key or f"{event_type}:{source_type}:{source_id}"
    existing = _existing_by_key(conn, ctx.entity_id, key)
    if existing:
        return get_journal(conn, ctx.entity_id, existing["id"])
    period = require_open(conn, ctx.entity_id, journal_date)
    norm = normalise_lines(conn, ctx, lines, manual=False)
    amount = sum((l["debit"] for l in norm), ZERO)
    event = q1(conn, """
        INSERT INTO fin_accounting_events (legal_entity_id, event_type, source_type, source_id, event_date, period_id,
                                           amount, status, idempotency_key, metadata, created_by)
        VALUES (%s,%s,%s,%s,%s,%s,%s,'PENDING',%s,%s,%s) RETURNING id
    """, (ctx.entity_id, event_type, source_type, str(source_id), journal_date, period["id"], amount, key,
          jsonb(metadata or {}), ctx.actor_id))
    j = _insert_journal(conn, ctx, journal_date=journal_date, period_id=period["id"], lines=norm,
                        journal_type=journal_type, description=description, source_type=source_type,
                        source_id=source_id, source_ref=source_ref, event_id=event["id"], idempotency_key=key)
    _mark_posted(conn, ctx, j["id"])
    ex(conn, "UPDATE fin_accounting_events SET status='POSTED', posted_at=now() WHERE id=%s", (event["id"],))
    audit.record(conn, ctx, "JOURNAL_POSTED", "journal", j["id"], ref=j["journal_number"],
                 metadata={"event_type": event_type, "source_type": source_type, "source_id": str(source_id),
                           "source_ref": source_ref, "amount": str(amount)})
    return get_journal(conn, ctx.entity_id, j["id"])


# ---------------------------------------------------------------------------
# Manual journals: draft -> submit -> approve -> post ; reverse
# ---------------------------------------------------------------------------

def _settings(conn, entity_id: str) -> Dict[str, Any]:
    return q1(conn, "SELECT * FROM fin_settings WHERE legal_entity_id=%s", (entity_id,)) or {
        "journal_approval_required": False, "allow_self_approval": False}


def create_manual(conn, ctx, *, journal_date: dt.date, description: str, lines: List[Dict[str, Any]],
                  journal_type: str = "MANUAL", idempotency_key: Optional[str] = None) -> Dict[str, Any]:
    ctx.require("accounting.journal.create")
    if journal_type not in ("MANUAL", "ADJUSTMENT"):
        raise invalid("Manual journals are MANUAL or ADJUSTMENT")
    if not (description or "").strip():
        raise invalid("A journal needs a description (why it is being posted)")
    existing = _existing_by_key(conn, ctx.entity_id, idempotency_key)
    if existing:
        return get_journal(conn, ctx.entity_id, existing["id"])
    period = period_for(conn, ctx.entity_id, journal_date)
    norm = normalise_lines(conn, ctx, lines, manual=True, require_balanced=False)
    j = _insert_journal(conn, ctx, journal_date=journal_date, period_id=period["id"], lines=norm,
                        journal_type=journal_type, description=description, source_type="MANUAL_JOURNAL",
                        source_id=None, source_ref=None, event_id=None, idempotency_key=idempotency_key)
    audit.record(conn, ctx, "JOURNAL_CREATED", "journal", j["id"], ref=j["journal_number"],
                 after={"date": journal_date, "description": description, "lines": len(norm)})
    return get_journal(conn, ctx.entity_id, j["id"])


def update_manual(conn, ctx, journal_id: str, *, journal_date: dt.date, description: str,
                  lines: List[Dict[str, Any]]) -> Dict[str, Any]:
    ctx.require("accounting.journal.create")
    j = _lock(conn, ctx, journal_id)
    if j["status"] not in ("DRAFT", "REJECTED"):
        raise FinError("INVALID_STATE_TRANSITION", f"A {j['status'].lower()} journal cannot be edited")
    if j["journal_type"] not in ("MANUAL", "ADJUSTMENT"):
        raise FinError("INVALID_STATE_TRANSITION", "System journals are edited through their source document")
    period = period_for(conn, ctx.entity_id, journal_date)
    norm = normalise_lines(conn, ctx, lines, manual=True, require_balanced=False)
    ex(conn, "DELETE FROM fin_journal_lines WHERE journal_id=%s", (journal_id,))
    _insert_lines(conn, journal_id, norm)
    dr = sum((l["debit"] for l in norm), ZERO)
    cr = sum((l["credit"] for l in norm), ZERO)
    ex(conn, """UPDATE fin_journals SET journal_date=%s, period_id=%s, description=%s, total_debit=%s,
                total_credit=%s, status='DRAFT', rejected_reason=NULL WHERE id=%s""",
       (journal_date, period["id"], description, dr, cr, journal_id))
    audit.record(conn, ctx, "JOURNAL_EDITED", "journal", journal_id, ref=j["journal_number"],
                 before={"date": j["journal_date"], "total": j["total_debit"]}, after={"date": journal_date, "total": dr})
    return get_journal(conn, ctx.entity_id, journal_id)


def _lock(conn, ctx, journal_id: str) -> Dict[str, Any]:
    j = q1(conn, "SELECT * FROM fin_journals WHERE id=%s AND legal_entity_id=%s FOR UPDATE", (journal_id, ctx.entity_id))
    if not j:
        raise not_found("Journal", journal_id)
    return j


def _lines_of(conn, journal_id: str) -> List[Dict[str, Any]]:
    return q(conn, """SELECT l.account_id, a.code AS account_code, l.debit, l.credit, l.description,
                             l.branch_id, l.department_id, l.cost_centre_id, l.customer_id, l.supplier_id, l.product_sku
                      FROM fin_journal_lines l JOIN fin_accounts a ON a.id=l.account_id
                      WHERE l.journal_id=%s ORDER BY l.line_no""", (journal_id,))


def validate_journal(conn, ctx, journal_id: str) -> Dict[str, Any]:
    """Dry run of every posting check, returning issues instead of raising."""
    j = get_journal(conn, ctx.entity_id, journal_id)
    issues: List[Dict[str, str]] = []
    try:
        normalise_lines(conn, ctx, _lines_of(conn, journal_id), manual=j["journal_type"] in ("MANUAL", "ADJUSTMENT"))
    except FinError as e:
        issues.append({"code": e.code, "message": e.message})
    try:
        require_open(conn, ctx.entity_id, j["journal_date"])
    except FinError as e:
        issues.append({"code": e.code, "message": e.message})
    return {"journal_id": journal_id, "valid": not issues, "issues": issues,
            "total_debit": str(j["total_debit"]), "total_credit": str(j["total_credit"])}


def submit(conn, ctx, journal_id: str) -> Dict[str, Any]:
    ctx.require("accounting.journal.create")
    j = _lock(conn, ctx, journal_id)
    if j["status"] not in ("DRAFT", "REJECTED"):
        raise FinError("INVALID_STATE_TRANSITION", f"Cannot submit a {j['status'].lower()} journal")
    normalise_lines(conn, ctx, _lines_of(conn, journal_id), manual=True)
    ex(conn, "UPDATE fin_journals SET status='SUBMITTED', submitted_by=%s, submitted_at=now() WHERE id=%s",
       (ctx.actor_id, journal_id))
    audit.record(conn, ctx, "JOURNAL_SUBMITTED", "journal", journal_id, ref=j["journal_number"])
    return get_journal(conn, ctx.entity_id, journal_id)


def approve(conn, ctx, journal_id: str, comment: Optional[str] = None) -> Dict[str, Any]:
    ctx.require("accounting.journal.approve")
    j = _lock(conn, ctx, journal_id)
    if j["status"] != "SUBMITTED":
        raise FinError("INVALID_STATE_TRANSITION", "Only a submitted journal can be approved")
    if j["created_by"] == ctx.actor_id and not _settings(conn, ctx.entity_id)["allow_self_approval"]:
        raise FinError("PERMISSION_DENIED", "You cannot approve a journal you created (maker-checker)")
    ex(conn, "UPDATE fin_journals SET status='APPROVED', approved_by=%s, approved_at=now() WHERE id=%s",
       (ctx.actor_id, journal_id))
    audit.record(conn, ctx, "JOURNAL_APPROVED", "journal", journal_id, ref=j["journal_number"], reason=comment)
    return get_journal(conn, ctx.entity_id, journal_id)


def reject(conn, ctx, journal_id: str, reason: str) -> Dict[str, Any]:
    ctx.require("accounting.journal.approve")
    if not (reason or "").strip():
        raise invalid("A reason is required to reject a journal")
    j = _lock(conn, ctx, journal_id)
    if j["status"] != "SUBMITTED":
        raise FinError("INVALID_STATE_TRANSITION", "Only a submitted journal can be rejected")
    ex(conn, "UPDATE fin_journals SET status='REJECTED', rejected_reason=%s WHERE id=%s", (reason, journal_id))
    audit.record(conn, ctx, "JOURNAL_REJECTED", "journal", journal_id, ref=j["journal_number"], reason=reason)
    return get_journal(conn, ctx.entity_id, journal_id)


def post_manual(conn, ctx, journal_id: str) -> Dict[str, Any]:
    ctx.require("accounting.journal.post")
    j = _lock(conn, ctx, journal_id)
    if j["status"] == "POSTED":
        return get_journal(conn, ctx.entity_id, journal_id)  # idempotent re-post
    if j["journal_type"] not in ("MANUAL", "ADJUSTMENT"):
        raise FinError("INVALID_STATE_TRANSITION", "System journals are posted by their source document")
    settings = _settings(conn, ctx.entity_id)
    if settings["journal_approval_required"]:
        if j["status"] != "APPROVED":
            raise FinError("APPROVAL_REQUIRED", "Journals must be approved before posting (Setup > Controls)")
    elif j["status"] not in ("DRAFT", "SUBMITTED", "APPROVED"):
        raise FinError("INVALID_STATE_TRANSITION", f"Cannot post a {j['status'].lower()} journal")
    normalise_lines(conn, ctx, _lines_of(conn, journal_id), manual=True)
    require_open(conn, ctx.entity_id, j["journal_date"])
    event = q1(conn, """
        INSERT INTO fin_accounting_events (legal_entity_id, event_type, source_type, source_id, event_date, period_id,
                                           amount, status, created_by)
        VALUES (%s,'MANUAL_JOURNAL_POSTED','MANUAL_JOURNAL',%s,%s,%s,%s,'POSTED',%s) RETURNING id
    """, (ctx.entity_id, journal_id, j["journal_date"], j["period_id"], j["total_debit"], ctx.actor_id))
    ex(conn, "UPDATE fin_journals SET event_id=%s WHERE id=%s", (event["id"], journal_id))
    _mark_posted(conn, ctx, journal_id)
    audit.record(conn, ctx, "JOURNAL_POSTED", "journal", journal_id, ref=j["journal_number"],
                 metadata={"amount": str(j["total_debit"]), "type": j["journal_type"]})
    return get_journal(conn, ctx.entity_id, journal_id)


def delete_draft(conn, ctx, journal_id: str) -> None:
    ctx.require("accounting.journal.create")
    j = _lock(conn, ctx, journal_id)
    if j["status"] not in ("DRAFT", "REJECTED"):
        raise FinError("INVALID_STATE_TRANSITION", "Only an unposted draft can be discarded")
    ex(conn, "DELETE FROM fin_journal_lines WHERE journal_id=%s", (journal_id,))
    ex(conn, "DELETE FROM fin_journals WHERE id=%s", (journal_id,))
    audit.record(conn, ctx, "JOURNAL_DISCARDED", "journal", journal_id, ref=j["journal_number"])


def reverse(conn, ctx, journal_id: str, *, reversal_date: Optional[dt.date] = None, reason: str,
            allow_system: bool = False) -> Dict[str, Any]:
    """Correct posted history by posting its mirror image; the original stays intact."""
    if not allow_system:
        ctx.require("accounting.journal.reverse")
    if not (reason or "").strip():
        raise invalid("A reason is required to reverse a journal")
    j = _lock(conn, ctx, journal_id)
    if j["status"] == "REVERSED":
        raise FinError("TRANSACTION_ALREADY_POSTED", f"{j['journal_number']} has already been reversed")
    if j["status"] != "POSTED":
        raise FinError("INVALID_STATE_TRANSITION", "Only a posted journal can be reversed")
    if j["journal_type"] not in ("MANUAL", "ADJUSTMENT", "OPENING") and not allow_system:
        raise FinError("INVALID_STATE_TRANSITION",
                       "This journal belongs to a source document; void or credit the document instead",
                       {"source_type": j["source_type"], "source_ref": j["source_ref"]})
    on = reversal_date or j["journal_date"]
    period = require_open(conn, ctx.entity_id, on)
    mirrored = [{**l, "debit": l["credit"], "credit": l["debit"],
                 "description": f"Reversal: {l['description'] or ''}".strip()} for l in _lines_of(conn, journal_id)]
    norm = normalise_lines(conn, ctx, mirrored, manual=False)
    rev = _insert_journal(conn, ctx, journal_date=on, period_id=period["id"], lines=norm, journal_type="REVERSAL",
                          description=f"Reversal of {j['journal_number']}: {reason}", source_type=j["source_type"],
                          source_id=j["source_id"], source_ref=j["source_ref"], event_id=None,
                          idempotency_key=f"REVERSAL:{journal_id}")
    ex(conn, "UPDATE fin_journals SET reversal_of_id=%s WHERE id=%s", (journal_id, rev["id"]))
    _mark_posted(conn, ctx, rev["id"])
    ex(conn, "UPDATE fin_journals SET status='REVERSED', reversed_by_id=%s WHERE id=%s", (rev["id"], journal_id))
    audit.record(conn, ctx, "JOURNAL_REVERSED", "journal", journal_id, ref=j["journal_number"], reason=reason,
                 metadata={"reversal_journal": rev["journal_number"]})
    return get_journal(conn, ctx.entity_id, rev["id"])


def list_journals(conn, entity_id: str, *, status: Optional[str] = None, date_from: Optional[dt.date] = None,
                  date_to: Optional[dt.date] = None, search: Optional[str] = None, journal_type: Optional[str] = None,
                  source_type: Optional[str] = None, limit: int = 100, offset: int = 0) -> Dict[str, Any]:
    where, params = ["j.legal_entity_id=%s"], [entity_id]
    if status:
        where.append("j.status = ANY(%s)")
        params.append(status.split(","))
    if date_from:
        where.append("j.journal_date >= %s")
        params.append(date_from)
    if date_to:
        where.append("j.journal_date <= %s")
        params.append(date_to)
    if journal_type:
        where.append("j.journal_type = %s")
        params.append(journal_type)
    if source_type:
        where.append("j.source_type = %s")
        params.append(source_type)
    if search:
        where.append("(j.journal_number ILIKE %s OR j.description ILIKE %s OR j.source_ref ILIKE %s)")
        params += [f"%{search}%"] * 3
    w = " AND ".join(where)
    total = q1(conn, f"SELECT COUNT(*) n FROM fin_journals j WHERE {w}", params)["n"]
    rows = q(conn, f"""SELECT j.id, j.journal_number, j.journal_date, j.journal_type, j.description, j.status,
                              j.total_debit, j.total_credit, j.source_type, j.source_ref, j.created_by,
                              j.posted_at, j.reversal_of_id, j.reversed_by_id
                       FROM fin_journals j WHERE {w}
                       ORDER BY j.journal_date DESC, j.journal_number DESC LIMIT %s OFFSET %s""",
             params + [limit, offset])
    return {"items": rows, "total": total}
