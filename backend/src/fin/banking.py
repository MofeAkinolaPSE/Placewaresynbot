"""Cash & banking.

* Vouchers are the day-to-day cash book the accountant showed in the
  meeting: spend money (petty cash "transportation ₦4,000" -> DR expense /
  CR cash), receive money that is not a customer receipt, and transfers such
  as lodging cash at the bank (DR Bank / CR Cash on Hand).
* Reconciliation proves the bank GL account against the bank statement:
  statement lines are matched to posted GL lines on that account; matched
  lines are marked cleared (journal lines themselves stay immutable).
"""
from __future__ import annotations

import csv
import datetime as dt
import io
from decimal import Decimal
from typing import Any, Dict, List, Optional

from src.fin import audit, posting
from src.fin.db import ZERO, ex, money, q, q1
from src.fin.errors import FinError, invalid, not_found
from src.fin import numbering
from src.fin.numbering import next_number
from src.fin.sales import bank_account


def list_accounts(conn, entity_id: str) -> List[Dict[str, Any]]:
    return q(conn, """
        SELECT b.*, a.code AS gl_code, a.name AS gl_name,
               COALESCE((SELECT SUM(g.debit - g.credit) FROM fin_v_general_ledger g WHERE g.account_id=b.gl_account_id), 0) AS book_balance,
               (SELECT COUNT(*) FROM fin_v_general_ledger g WHERE g.account_id=b.gl_account_id
                  AND NOT EXISTS (SELECT 1 FROM fin_cleared_lines c WHERE c.journal_line_id=g.line_id)) AS uncleared_count,
               (SELECT MAX(r.as_of) FROM fin_reconciliations r WHERE r.bank_account_id=b.id AND r.status='COMPLETED') AS last_reconciled
        FROM fin_bank_accounts b JOIN fin_accounts a ON a.id=b.gl_account_id
        WHERE b.legal_entity_id=%s ORDER BY b.kind, b.name""", (entity_id,))


def create_account(conn, ctx, data: Dict[str, Any]) -> Dict[str, Any]:
    ctx.require("banking.account.create")
    gl = q1(conn, "SELECT * FROM fin_accounts WHERE id=%s AND legal_entity_id=%s", (data["gl_account_id"], ctx.entity_id))
    if not gl or gl["subtype"] != "CASH":
        raise invalid("A bank or cash account must point at a Cash-type GL account")
    kind = str(data.get("kind") or "BANK").upper()
    b = q1(conn, """INSERT INTO fin_bank_accounts (legal_entity_id, gl_account_id, name, kind, bank_name, account_number)
                    VALUES (%s,%s,%s,%s,%s,%s) ON CONFLICT (legal_entity_id, gl_account_id) DO NOTHING RETURNING *""",
           (ctx.entity_id, gl["id"], data.get("name") or gl["name"], kind, data.get("bank_name"), data.get("account_number")))
    if not b:
        raise FinError("DUPLICATE_RESOURCE", f"{gl['code']} is already set up as a bank/cash account")
    audit.record(conn, ctx, "BANK_ACCOUNT_CREATED", "bank_account", b["id"], ref=b["name"])
    return b


# ---------------------------------------------------------------------------
# Vouchers
# ---------------------------------------------------------------------------

def create_voucher(conn, ctx, data: Dict[str, Any]) -> Dict[str, Any]:
    kind = str(data.get("kind") or "").upper()
    if kind not in ("SPEND", "RECEIVE", "TRANSFER"):
        raise invalid("Voucher kind must be spend, receive or transfer")
    ctx.require("banking.voucher.create")
    bank = bank_account(conn, ctx.entity_id, data["bank_account_id"])
    on = data["voucher_date"]
    reference = (data.get("reference") or "").strip() or None
    if kind == "TRANSFER":
        to = bank_account(conn, ctx.entity_id, data["to_bank_account_id"])
        if str(to["id"]) == str(bank["id"]):
            raise invalid("Choose two different accounts for a transfer")
        amount = money(data.get("amount"))
        if amount <= 0:
            raise invalid("Transfer amount must be positive")
        lines = [{"account_id": to["gl_account_id"], "debit": amount, "description": data.get("description") or f"From {bank['name']}"},
                 {"account_id": bank["gl_account_id"], "credit": amount, "description": data.get("description") or f"To {to['name']}"}]
        detail = []
    else:
        detail = data.get("lines") or []
        if not detail:
            raise invalid("Add at least one line (what the money was for)")
        amount = ZERO
        lines = []
        for i, l in enumerate(detail, start=1):
            amt = money(l.get("amount"))
            if amt <= 0:
                raise invalid(f"Line {i}: amount must be positive")
            if not l.get("account_id"):
                raise invalid(f"Line {i}: choose an account")
            amount += amt
            side = "debit" if kind == "SPEND" else "credit"
            lines.append({"account_id": l["account_id"], side: amt, "description": l.get("description") or data.get("description"),
                          "department_id": l.get("department_id"), "cost_centre_id": l.get("cost_centre_id")})
        bank_line = {"account_id": bank["gl_account_id"], ("credit" if kind == "SPEND" else "debit"): amount,
                     "description": data.get("payee") or data.get("description")}
        lines.append(bank_line)
    number = next_number(conn, ctx.entity_id, "CASH_VOUCHER")
    v = q1(conn, """INSERT INTO fin_cash_vouchers (legal_entity_id, voucher_number, kind, voucher_date, bank_account_id,
                    to_bank_account_id, payee, reference, description, amount, created_by)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING *""",
           (ctx.entity_id, number, kind, on, bank["id"], data.get("to_bank_account_id") if kind == "TRANSFER" else None,
            data.get("payee"), reference, data.get("description"), amount, ctx.actor_id))
    for i, l in enumerate(detail, start=1):
        ex(conn, """INSERT INTO fin_cash_voucher_lines (voucher_id, line_no, account_id, description, amount, department_id,
                    cost_centre_id) VALUES (%s,%s,%s,%s,%s,%s,%s)""",
           (v["id"], i, l["account_id"], l.get("description"), money(l["amount"]), l.get("department_id"), l.get("cost_centre_id")))
    event = {"SPEND": "CASH_PAYMENT_POSTED", "RECEIVE": "CASH_RECEIPT_POSTED", "TRANSFER": "BANK_TRANSFER_POSTED"}[kind]
    j = posting.post_system(conn, ctx, event_type=event, journal_date=on, lines=lines,
                            description=f"{kind.title()} {number}: {data.get('description') or data.get('payee') or ''}".strip(),
                            source_type="CASH_VOUCHER", source_id=v["id"], source_ref=number)
    ex(conn, "UPDATE fin_cash_vouchers SET journal_id=%s WHERE id=%s", (j["id"], v["id"]))
    audit.record(conn, ctx, "VOUCHER_POSTED", "cash_voucher", v["id"], ref=number,
                 metadata={"kind": kind, "amount": str(amount), "journal": j["journal_number"]})
    return get_voucher(conn, ctx.entity_id, v["id"])


def get_voucher(conn, entity_id: str, voucher_id: str) -> Dict[str, Any]:
    v = q1(conn, """SELECT v.*, b.name AS bank_account_name, t.name AS to_bank_account_name, j.journal_number,
                           rb.voucher_number AS replaced_by_number, rp.voucher_number AS replaces_number
                    FROM fin_cash_vouchers v JOIN fin_bank_accounts b ON b.id=v.bank_account_id
                    LEFT JOIN fin_bank_accounts t ON t.id=v.to_bank_account_id LEFT JOIN fin_journals j ON j.id=v.journal_id
                    LEFT JOIN fin_cash_vouchers rb ON rb.id=v.replaced_by_id LEFT JOIN fin_cash_vouchers rp ON rp.id=v.replaces_id
                    WHERE v.id=%s AND v.legal_entity_id=%s""", (voucher_id, entity_id))
    if not v:
        raise not_found("Voucher", voucher_id)
    v["lines"] = q(conn, """SELECT l.*, a.code AS account_code, a.name AS account_name FROM fin_cash_voucher_lines l
                            JOIN fin_accounts a ON a.id=l.account_id WHERE l.voucher_id=%s ORDER BY l.line_no""", (voucher_id,))
    return v


def void_voucher(conn, ctx, voucher_id: str, reason: str) -> Dict[str, Any]:
    ctx.require("banking.voucher.void")
    v = q1(conn, "SELECT * FROM fin_cash_vouchers WHERE id=%s AND legal_entity_id=%s FOR UPDATE", (voucher_id, ctx.entity_id))
    if not v:
        raise not_found("Voucher", voucher_id)
    if v["status"] != "POSTED":
        raise FinError("INVALID_STATE_TRANSITION", "Voucher is already void")
    if not (reason or "").strip():
        raise invalid("A reason is required")
    if q1(conn, "SELECT 1 FROM fin_cleared_lines c JOIN fin_journal_lines l ON l.id=c.journal_line_id WHERE l.journal_id=%s",
          (v["journal_id"],)):
        raise FinError("INVALID_STATE_TRANSITION", "This voucher is already reconciled against a bank statement")
    rev = posting.reverse(conn, ctx, str(v["journal_id"]), reversal_date=v["voucher_date"],
                          reason=f"Void {v['voucher_number']}: {reason}", allow_system=True)
    ex(conn, "UPDATE fin_cash_vouchers SET status='VOID', void_journal_id=%s, void_reason=%s WHERE id=%s", (rev["id"], reason, voucher_id))
    numbering.release_if_last(conn, ctx, "CASH_VOUCHER", v["voucher_number"], "fin_cash_vouchers", "voucher_number", voucher_id)
    audit.record(conn, ctx, "VOUCHER_VOIDED", "cash_voucher", voucher_id, ref=v["voucher_number"], reason=reason)
    return get_voucher(conn, ctx.entity_id, voucher_id)


def correct_voucher(conn, ctx, voucher_id: str, data: Dict[str, Any]) -> Dict[str, Any]:
    """A voucher posted with a mistake (payee, amount, account, bank, date): the wrong one is voided
    (journal reversed) and the right one posted in the same transaction, each pointing at the other."""
    ctx.require("banking.voucher.void")
    reason = (data.get("reason") or "").strip()
    if not reason:
        raise invalid("Say what was wrong")
    old = q1(conn, "SELECT * FROM fin_cash_vouchers WHERE id=%s AND legal_entity_id=%s", (voucher_id, ctx.entity_id))
    if not old:
        raise not_found("Voucher", voucher_id)
    void_voucher(conn, ctx, voucher_id, f"Corrected: {reason}")
    new = create_voucher(conn, ctx, {**data, "kind": data.get("kind") or old["kind"],
                                     "description": data.get("description") or old["description"]})
    ex(conn, "UPDATE fin_cash_vouchers SET replaced_by_id=%s WHERE id=%s", (new["id"], voucher_id))
    ex(conn, "UPDATE fin_cash_vouchers SET replaces_id=%s WHERE id=%s", (voucher_id, new["id"]))
    audit.record(conn, ctx, "VOUCHER_CORRECTED", "cash_voucher", new["id"], ref=new["voucher_number"], reason=reason,
                 metadata={"replaces": old["voucher_number"]})
    return get_voucher(conn, ctx.entity_id, str(new["id"]))


def list_vouchers(conn, entity_id: str, *, kind: Optional[str] = None, bank_account_id: Optional[str] = None,
                  search: Optional[str] = None, date_from=None, date_to=None, limit: int = 100, offset: int = 0):
    where, params = ["v.legal_entity_id=%s"], [entity_id]
    if kind:
        where.append("v.kind=%s")
        params.append(kind.upper())
    if bank_account_id:
        where.append("(v.bank_account_id=%s OR v.to_bank_account_id=%s)")
        params += [bank_account_id, bank_account_id]
    if date_from:
        where.append("v.voucher_date >= %s")
        params.append(date_from)
    if date_to:
        where.append("v.voucher_date <= %s")
        params.append(date_to)
    if search:
        where.append("(v.voucher_number ILIKE %s OR v.payee ILIKE %s OR v.description ILIKE %s OR v.reference ILIKE %s)")
        params += [f"%{search}%"] * 4
    w = " AND ".join(where)
    union = f"""SELECT v.id::text AS id, v.voucher_number, v.kind, v.voucher_date, b.name AS bank_account_name,
                       t.name AS to_bank_account_name, v.payee, v.reference, v.description, v.amount, v.status, 'ACE' AS source,
                       NULL::text AS jrnl
                FROM fin_cash_vouchers v JOIN fin_bank_accounts b ON b.id=v.bank_account_id
                LEFT JOIN fin_bank_accounts t ON t.id=v.to_bank_account_id WHERE {w}"""
    sp: List[Any] = []
    if bank_account_id:
        # Money in and out of this bank in Sage that was not a customer receipt or a supplier
        # payment: spends, bank charges, transfers - what ACE Books records as vouchers.
        sw = ["l.legal_entity_id=%s", "a.id=(SELECT gl_account_id FROM fin_bank_accounts WHERE id=%s)",
              "l.jrnl IN ('CDJ','CRJ','GENJ')", "(l.debit <> 0 OR l.credit <> 0)",
              """NOT EXISTS (SELECT 1 FROM fin_sage_party_ledger p WHERE p.legal_entity_id=l.legal_entity_id
                             AND p.trans_no=l.reference AND p.txn_date=l.txn_date)"""]
        sp = [entity_id, bank_account_id]
        k = (kind or "").upper()
        if k == "SPEND":
            sw.append("l.credit > 0")
        elif k == "RECEIVE":
            sw.append("l.debit > 0")
        elif k == "TRANSFER":
            sw.append("FALSE")
        if date_from:
            sw.append("l.txn_date >= %s")
            sp.append(date_from)
        if date_to:
            sw.append("l.txn_date <= %s")
            sp.append(date_to)
        if search:
            sw.append("(l.reference ILIKE %s OR l.description ILIKE %s)")
            sp += [f"%{search}%"] * 2
        union += f"""
                UNION ALL
                SELECT NULL, l.reference, CASE WHEN l.credit > 0 THEN 'SPEND' ELSE 'RECEIVE' END, l.txn_date, a.name, NULL,
                       l.description, l.reference, l.description, CASE WHEN l.credit > 0 THEN l.credit ELSE l.debit END,
                       'POSTED', 'SAGE', l.jrnl
                FROM fin_sage_gl_lines l JOIN fin_accounts a ON a.legal_entity_id=l.legal_entity_id AND a.code=l.account_code
                WHERE {' AND '.join(sw)}"""
    total = q1(conn, f"SELECT COUNT(*) n FROM ({union}) u", params + sp)["n"]
    rows = q(conn, f"SELECT * FROM ({union}) u ORDER BY voucher_date DESC, voucher_number DESC LIMIT %s OFFSET %s",
             params + sp + [limit, offset])
    return {"items": rows, "total": total}


# ---------------------------------------------------------------------------
# Bank statements & reconciliation
# ---------------------------------------------------------------------------

def _num(s: Any) -> Decimal:
    t = str(s or "").replace(",", "").replace("₦", "").strip()
    if t.startswith("(") and t.endswith(")"):
        t = "-" + t[1:-1]
    return money(t) if t not in ("", "-") else ZERO


def parse_statement_csv(text: str) -> List[Dict[str, Any]]:
    """Accepts the common bank export shapes: Date, Description, Reference and either
    Amount (signed) or Debit/Credit (withdrawal/deposit) columns."""
    rows = list(csv.DictReader(io.StringIO(text)))
    if not rows:
        raise invalid("The statement file has no rows")
    keys = {k.lower().strip(): k for k in rows[0].keys() if k}

    def col(*names):
        for n in names:
            for k, orig in keys.items():
                if n in k:
                    return orig
        return None
    c_date = col("date")
    c_desc = col("description", "narration", "details", "remarks")
    c_ref = col("reference", "ref", "cheque", "check")
    c_amt = col("amount")
    c_dr = col("debit", "withdrawal", "payment")
    c_cr = col("credit", "deposit", "lodg")
    if not c_date or not (c_amt or (c_dr and c_cr)):
        raise invalid("Statement needs a Date column and either Amount or Debit/Credit columns")
    out = []
    for r in rows:
        raw = (r.get(c_date) or "").strip()
        if not raw:
            continue
        d = None
        for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%d-%b-%Y", "%d %b %Y", "%m/%d/%Y", "%d/%m/%y"):
            try:
                d = dt.datetime.strptime(raw[:11].strip(), fmt).date()
                break
            except ValueError:
                continue
        if not d:
            raise invalid(f"Cannot read the date {raw!r}")
        amt = _num(r.get(c_amt)) if c_amt else _num(r.get(c_cr)) - _num(r.get(c_dr))
        if amt == 0:
            continue
        out.append({"line_date": d, "description": (r.get(c_desc) or "").strip() if c_desc else None,
                    "reference": (r.get(c_ref) or "").strip() if c_ref else None, "amount": amt})
    return out


def import_statement(conn, ctx, bank_account_id: str, *, statement_date: dt.date, closing_balance: Any,
                     opening_balance: Any = None, lines: List[Dict[str, Any]], source_file: Optional[str] = None):
    ctx.require("banking.reconcile")
    bank = bank_account(conn, ctx.entity_id, bank_account_id)
    st = q1(conn, """INSERT INTO fin_bank_statements (legal_entity_id, bank_account_id, statement_date, opening_balance,
                     closing_balance, source_file, created_by) VALUES (%s,%s,%s,%s,%s,%s,%s) RETURNING *""",
            (ctx.entity_id, bank["id"], statement_date, money(opening_balance) if opening_balance not in (None, "") else None,
             money(closing_balance), source_file, ctx.actor_id))
    for i, l in enumerate(lines, start=1):
        ex(conn, """INSERT INTO fin_bank_statement_lines (statement_id, line_no, line_date, description, reference, amount)
                    VALUES (%s,%s,%s,%s,%s,%s)""", (st["id"], i, l["line_date"], l.get("description"), l.get("reference"), money(l["amount"])))
    auto_match(conn, ctx, str(st["id"]))
    audit.record(conn, ctx, "BANK_STATEMENT_IMPORTED", "bank_statement", st["id"], ref=bank["name"],
                 metadata={"lines": len(lines), "closing_balance": str(money(closing_balance))})
    return get_statement(conn, ctx.entity_id, str(st["id"]))


def _open_book_lines(conn, gl_account_id: str, upto: dt.date) -> List[Dict[str, Any]]:
    return q(conn, """SELECT g.line_id, g.journal_number, g.journal_date, g.source_ref,
                             COALESCE(g.description, g.journal_description) AS description, (g.debit - g.credit) AS amount
                      FROM fin_v_general_ledger g
                      WHERE g.account_id=%s AND g.journal_date <= %s
                        AND NOT EXISTS (SELECT 1 FROM fin_cleared_lines c WHERE c.journal_line_id=g.line_id)
                        AND NOT EXISTS (SELECT 1 FROM fin_bank_statement_lines s WHERE s.matched_journal_line_id=g.line_id)
                      ORDER BY g.journal_date""", (gl_account_id, upto + dt.timedelta(days=7)))


def auto_match(conn, ctx, statement_id: str) -> Dict[str, int]:
    """Exact amount + (same reference, or within 7 days). Ambiguity is left for a person."""
    st = q1(conn, """SELECT s.*, b.gl_account_id FROM fin_bank_statements s JOIN fin_bank_accounts b ON b.id=s.bank_account_id
                     WHERE s.id=%s AND s.legal_entity_id=%s""", (statement_id, ctx.entity_id))
    book = _open_book_lines(conn, str(st["gl_account_id"]), st["statement_date"])
    used, matched = set(), 0
    for sl in q(conn, "SELECT * FROM fin_bank_statement_lines WHERE statement_id=%s AND match_status='UNMATCHED' ORDER BY line_no",
                (statement_id,)):
        amt = money(sl["amount"])
        cands = [b for b in book if b["line_id"] not in used and money(b["amount"]) == amt]
        ref = (sl["reference"] or "").strip().lower()
        by_ref = [b for b in cands if ref and ref in ((b["description"] or "") + " " + (b["source_ref"] or "")).lower()]
        near = [b for b in cands if abs((b["journal_date"] - sl["line_date"]).days) <= 7]
        pick = by_ref[0] if len(by_ref) == 1 else (near[0] if len(near) == 1 else None)
        if pick:
            used.add(pick["line_id"])
            ex(conn, "UPDATE fin_bank_statement_lines SET match_status='MATCHED', matched_journal_line_id=%s WHERE id=%s",
               (pick["line_id"], sl["id"]))
            matched += 1
    return {"matched": matched}


def get_statement(conn, entity_id: str, statement_id: str) -> Dict[str, Any]:
    st = q1(conn, """SELECT s.*, b.name AS bank_account_name, b.gl_account_id FROM fin_bank_statements s
                     JOIN fin_bank_accounts b ON b.id=s.bank_account_id WHERE s.id=%s AND s.legal_entity_id=%s""",
            (statement_id, entity_id))
    if not st:
        raise not_found("Statement", statement_id)
    st["lines"] = q(conn, """SELECT l.*, g.journal_number, g.journal_date AS book_date,
                                    COALESCE(g.description, g.journal_description) AS book_description
                             FROM fin_bank_statement_lines l LEFT JOIN fin_v_general_ledger g ON g.line_id=l.matched_journal_line_id
                             WHERE l.statement_id=%s ORDER BY l.line_no""", (statement_id,))
    st["unmatched_book"] = _open_book_lines(conn, str(st["gl_account_id"]), st["statement_date"])
    return st


def match_line(conn, ctx, statement_line_id: str, journal_line_id: Optional[str], status: str = "MATCHED",
               note: Optional[str] = None) -> Dict[str, Any]:
    ctx.require("banking.reconcile")
    sl = q1(conn, """SELECT l.*, s.bank_account_id, s.legal_entity_id, s.status AS statement_status, b.gl_account_id
                     FROM fin_bank_statement_lines l JOIN fin_bank_statements s ON s.id=l.statement_id
                     JOIN fin_bank_accounts b ON b.id=s.bank_account_id WHERE l.id=%s""", (statement_line_id,))
    if not sl or str(sl["legal_entity_id"]) != ctx.entity_id:
        raise not_found("Statement line", statement_line_id)
    if sl["statement_status"] == "RECONCILED":
        raise FinError("INVALID_STATE_TRANSITION", "This statement is already reconciled")
    status = status.upper()
    if status == "MATCHED":
        g = q1(conn, "SELECT * FROM fin_v_general_ledger WHERE line_id=%s", (journal_line_id,))
        if not g or str(g["account_id"]) != str(sl["gl_account_id"]):
            raise invalid("That ledger line is not on this bank account")
        if money(g["debit"] - g["credit"]) != money(sl["amount"]):
            raise invalid(f"Amounts differ: statement ₦{money(sl['amount']):,.2f} vs book ₦{money(g['debit'] - g['credit']):,.2f}")
        ex(conn, "UPDATE fin_bank_statement_lines SET match_status='MATCHED', matched_journal_line_id=%s, note=%s WHERE id=%s",
           (journal_line_id, note, statement_line_id))
    elif status in ("UNMATCHED", "EXCEPTION", "IGNORED"):
        ex(conn, "UPDATE fin_bank_statement_lines SET match_status=%s, matched_journal_line_id=NULL, note=%s WHERE id=%s",
           (status, note, statement_line_id))
    else:
        raise invalid("Unknown match status")
    return {"id": statement_line_id, "match_status": status}


def complete_reconciliation(conn, ctx, statement_id: str) -> Dict[str, Any]:
    """Book balance = statement balance + uncleared book items; must agree to the kobo."""
    ctx.require("banking.reconcile")
    st = get_statement(conn, ctx.entity_id, statement_id)
    if st["status"] == "RECONCILED":
        raise FinError("INVALID_STATE_TRANSITION", "Already reconciled")
    open_lines = [l for l in st["lines"] if l["match_status"] in ("UNMATCHED", "EXCEPTION")]
    if open_lines:
        raise FinError("RECONCILIATION_EXCEPTION",
                       f"{len(open_lines)} statement line(s) are not matched. Record them (e.g. bank charges) or mark as ignored.",
                       {"lines": [str(l["id"]) for l in open_lines]})
    gl = str(st["gl_account_id"])
    book = money(q1(conn, "SELECT COALESCE(SUM(debit-credit),0) b FROM fin_v_general_ledger WHERE account_id=%s AND journal_date<=%s",
                    (gl, st["statement_date"]))["b"])
    matched_ids = [str(l["matched_journal_line_id"]) for l in st["lines"] if l["match_status"] == "MATCHED"]
    uncleared = money(q1(conn, """SELECT COALESCE(SUM(debit-credit),0) b FROM fin_v_general_ledger g
                                  WHERE account_id=%s AND journal_date<=%s AND NOT (line_id = ANY(%s::uuid[]))
                                  AND NOT EXISTS (SELECT 1 FROM fin_cleared_lines c WHERE c.journal_line_id=g.line_id)""",
                         (gl, st["statement_date"], matched_ids or [None]))["b"])
    statement_bal = money(st["closing_balance"])
    difference = book - uncleared - statement_bal
    if difference != 0:
        raise FinError("RECONCILIATION_EXCEPTION",
                       f"Out by ₦{difference:,.2f}: book ₦{book:,.2f} less uncleared ₦{uncleared:,.2f} should equal the statement ₦{statement_bal:,.2f}",
                       {"book_balance": str(book), "uncleared": str(uncleared), "statement_balance": str(statement_bal),
                        "difference": str(difference)})
    number = next_number(conn, ctx.entity_id, "RECONCILIATION")
    rec = q1(conn, """INSERT INTO fin_reconciliations (legal_entity_id, reconciliation_number, bank_account_id, statement_id,
                      as_of, statement_balance, book_balance, cleared_balance, difference, status, created_by, completed_by, completed_at)
                      VALUES (%s,%s,%s,%s,%s,%s,%s,%s,0,'COMPLETED',%s,%s,now()) RETURNING *""",
              (ctx.entity_id, number, st["bank_account_id"], statement_id, st["statement_date"], statement_bal, book,
               book - uncleared, ctx.actor_id, ctx.actor_id))
    for l in st["lines"]:
        if l["match_status"] == "MATCHED":
            ex(conn, """INSERT INTO fin_cleared_lines (journal_line_id, bank_account_id, reconciliation_id, statement_line_id,
                        cleared_date, cleared_by) VALUES (%s,%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING""",
               (l["matched_journal_line_id"], st["bank_account_id"], rec["id"], l["id"], l["line_date"], ctx.actor_id))
    ex(conn, "UPDATE fin_bank_statements SET status='RECONCILED' WHERE id=%s", (statement_id,))
    audit.record(conn, ctx, "BANK_RECONCILED", "reconciliation", rec["id"], ref=number,
                 metadata={"bank": st["bank_account_name"], "as_of": st["statement_date"], "statement_balance": str(statement_bal)})
    return rec


def list_statements(conn, entity_id: str, bank_account_id: Optional[str] = None):
    params: List[Any] = [entity_id]
    bf = ""
    if bank_account_id:
        bf = " AND s.bank_account_id=%s"
        params.append(bank_account_id)
    return q(conn, f"""SELECT s.id, s.statement_date, s.closing_balance, s.status, b.name AS bank_account_name,
                              COUNT(l.id) AS lines, COUNT(l.id) FILTER (WHERE l.match_status='MATCHED') AS matched
                       FROM fin_bank_statements s JOIN fin_bank_accounts b ON b.id=s.bank_account_id
                       LEFT JOIN fin_bank_statement_lines l ON l.statement_id=s.id
                       WHERE s.legal_entity_id=%s {bf} GROUP BY s.id, b.name ORDER BY s.statement_date DESC""", params)
