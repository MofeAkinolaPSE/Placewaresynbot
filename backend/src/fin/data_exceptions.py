"""Data exceptions: what the Sage hand-over left unexplained, shown with its lineage and resolved
by a decision of the finance team (client meeting 7 Oct 2026).

Problems found by ``refresh``:
  STOCK_SHORT_LOT    a lot Sage sold below zero: its receipt was never entered, or the sales were
                     keyed against the wrong lot code. Lineage: Sage's item costing (received /
                     sold), the sales that took it below zero, the supplier bills for the product,
                     and the product's other lots that still hold stock.
  TB_GL_DIFFERENCE   Sage's Trial Balance disagrees with its General Ledger export. Lineage: the
                     source documents (Sales / Receipts / Disbursements / Purchase / General
                     journals) whose entries are missing from, or differ in, the General Ledger.
  AR_CONTROL / AP_CONTROL   the control account against the customer / supplier balances,
                     party by party (Sage's ledger against the open items ACE Books holds).
  INVENTORY_CONTROL  the inventory accounts against the valued stock, account by account.

Resolutions post through the posting service and are kept as overlays on Sage's history
(migration 131): an ACE Books journal dated the hand-over date, the same lines in the Sage-period
General Ledger (jrnl 'ADJ', no load) so reports for any date show them, and a quantity / value
overlay per lot that later roll-forwards add to Sage's valuation. Every decision is stored in
fin_data_exception_actions and the audit trail.
"""
from __future__ import annotations

import datetime as dt
import re
from decimal import Decimal
from typing import Any, Dict, List, Optional

from src.fin import audit, books_ledger, inventory, posting, rules, sage_history
from src.fin.db import ZERO, ex, jsonb, money, q, q1, qty
from src.fin.errors import FinError, invalid, not_found
from src.fin.numbering import next_number

CORRECTION_JRNL = "ADJ"
KINDS = ("STOCK_SHORT_LOT", "TB_GL_DIFFERENCE", "AR_CONTROL", "AP_CONTROL", "INVENTORY_CONTROL")
KIND_LABEL = {
    "STOCK_SHORT_LOT": "Lot sold below zero in Sage",
    "TB_GL_DIFFERENCE": "Trial Balance vs General Ledger",
    "AR_CONTROL": "Receivables control vs customer balances",
    "AP_CONTROL": "Payables control vs supplier balances",
    "INVENTORY_CONTROL": "Inventory accounts vs valued stock",
}
_FAMILY = re.compile(r"\s*\([^)]*\)\s*\w*$")


def family(sku: str) -> str:
    """'HEXAXIM (Q)' -> 'HEXAXIM' (the client's Sage uses one item code per lot)."""
    return _FAMILY.sub("", sku or "").strip()


# ---------------------------------------------------------------------------
# Sage "as at" snapshots
# ---------------------------------------------------------------------------

def save_snapshots(conn, ctx, snaps: Dict[str, Any], as_of: dt.date) -> None:
    for kind, s in snaps.items():
        p = s["parsed"]
        ex(conn, """INSERT INTO fin_sage_snapshots (legal_entity_id, kind, as_of, file_name, rows, summary, issues, loaded_by)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
                    ON CONFLICT (legal_entity_id, kind, as_of) DO UPDATE SET file_name=EXCLUDED.file_name, rows=EXCLUDED.rows,
                        summary=EXCLUDED.summary, issues=EXCLUDED.issues, loaded_by=EXCLUDED.loaded_by, loaded_at=now()""",
           (ctx.entity_id, kind, as_of, s.get("file"), jsonb(p.get("rows", [])), jsonb(p.get("summary", {})),
            jsonb(p.get("issues", [])), ctx.actor_id))


def snapshot(conn, entity_id: str, kind: str) -> Optional[Dict[str, Any]]:
    return q1(conn, """SELECT * FROM fin_sage_snapshots WHERE legal_entity_id=%s AND kind=%s
                       ORDER BY as_of DESC LIMIT 1""", (entity_id, kind))


# ---------------------------------------------------------------------------
# Overlays (corrections that later Sage loads and roll-forwards must keep)
# ---------------------------------------------------------------------------

def stock_overlays(conn, entity_id: str) -> Dict[str, Dict[str, Decimal]]:
    """Per lot: the quantity and value the finance team's corrections added to Sage's figures."""
    out: Dict[str, Dict[str, Decimal]] = {}
    for a in q(conn, "SELECT stock_delta FROM fin_data_exception_actions WHERE legal_entity_id=%s", (entity_id,)):
        for d in a["stock_delta"] or []:
            o = out.setdefault(d["sku"], {"quantity": ZERO, "value": ZERO})
            o["quantity"] += Decimal(str(d["quantity"]))
            o["value"] += Decimal(str(d["value"]))
    return out


def _post_correction(conn, ctx, exc: Dict[str, Any], lines: List[Dict[str, Any]], description: str,
                     number: Optional[str] = None) -> Dict[str, Any]:
    """Post a correction: an ACE Books journal on the hand-over date and the same lines in the
    Sage-period General Ledger, so every report (before or after the hand-over) includes it."""
    e = ctx.entity_id
    h = books_ledger.history_until(conn, e) or dt.date.today()
    number = number or next_number(conn, e, "DATA_CORRECTION")
    text = f"{number} {description}"[:240]
    j = posting.post_system(conn, ctx, event_type="DATA_CORRECTION", journal_date=h, lines=lines, description=text,
                            source_type="DATA_CORRECTION", source_id=f"{exc['id']}:{number}", source_ref=number,
                            journal_type="ADJUSTMENT", idempotency_key=f"DATA_CORRECTION:{e}:{number}")
    seq = int(q1(conn, "SELECT COALESCE(MAX(seq),0) s FROM fin_sage_gl_lines WHERE legal_entity_id=%s AND txn_date=%s",
                 (e, h))["s"])
    gl_delta = []
    for i, l in enumerate(j["lines"], start=1):
        ex(conn, """INSERT INTO fin_sage_gl_lines (legal_entity_id, load_id, account_code, txn_date, reference, jrnl,
                    description, debit, credit, seq) VALUES (%s,NULL,%s,%s,%s,%s,%s,%s,%s,%s)""",
           (e, l["account_code"], h, number, CORRECTION_JRNL, (l.get("description") or text)[:240],
            l["debit"], l["credit"], seq + i))
        gl_delta.append({"account_code": l["account_code"], "debit": str(l["debit"]), "credit": str(l["credit"])})
    return {"journal": j, "number": number, "gl_delta": gl_delta, "date": h}


def _log(conn, ctx, exc: Dict[str, Any], action: str, *, note: Optional[str], payload: Dict[str, Any],
         posted: Optional[Dict[str, Any]] = None, stock_delta: Optional[List[Dict[str, Any]]] = None) -> None:
    ex(conn, """INSERT INTO fin_data_exception_actions (exception_id, legal_entity_id, action, reference, note, payload,
                journal_id, gl_delta, stock_delta, created_by) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
       (exc["id"], ctx.entity_id, action, posted["number"] if posted else None, note, jsonb(payload),
        posted["journal"]["id"] if posted else None, jsonb(posted["gl_delta"] if posted else []),
        jsonb(stock_delta or []), ctx.actor_id))
    audit.record(conn, ctx, f"DATA_EXCEPTION_{action.upper()}", "data_exception", exc["id"], ref=exc["title"][:120],
                 reason=note, metadata={"payload": payload, "correction": posted["number"] if posted else None})


# ---------------------------------------------------------------------------
# Detection
# ---------------------------------------------------------------------------

def _upsert(conn, e: str, kind: str, key: str, *, title: str, summary: str, severity: str, amount: Any,
            quantity: Any, as_of: Optional[dt.date], detail: Dict[str, Any], cleared: bool) -> str:
    """Record what was found. A problem the data no longer shows is closed; one that comes back
    (e.g. after a new export) is reopened unless the team accepted it."""
    row = q1(conn, "SELECT id, status FROM fin_data_exceptions WHERE legal_entity_id=%s AND kind=%s AND key=%s", (e, kind, key))
    if not row:
        if cleared:
            return ""
        r = q1(conn, """INSERT INTO fin_data_exceptions (legal_entity_id, kind, key, title, summary, severity, amount, quantity,
                        as_of, detail) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id""",
               (e, kind, key, title, summary, severity, amount, quantity, as_of, jsonb(detail)))
        return str(r["id"])
    status = row["status"]
    if cleared and status == "OPEN":
        status = "RESOLVED"
    elif not cleared and status == "RESOLVED":
        status = "OPEN"
    ex(conn, """UPDATE fin_data_exceptions SET title=%s, summary=%s, severity=%s, amount=%s, quantity=%s, as_of=%s, detail=%s,
                status=%s, resolved_at=CASE WHEN %s='RESOLVED' AND status<>'RESOLVED' THEN now() ELSE resolved_at END,
                resolution=CASE WHEN %s='RESOLVED' AND status<>'RESOLVED' AND resolution IS NULL THEN 'CLEARED_BY_DATA'
                                WHEN %s='OPEN' THEN NULL ELSE resolution END,
                last_seen=now() WHERE id=%s""",
       (title, summary, severity, amount, quantity, as_of, jsonb(detail), status, status, status, status, row["id"]))
    return str(row["id"])


def _short_lots(conn, e: str) -> int:
    snap = snapshot(conn, e, "INVENTORY")
    if not snap:
        return 0
    overlays = stock_overlays(conn, e)
    seen = set()
    for i in snap["issues"] or []:
        sku = i.get("sku") or i.get("row")
        if not sku or i.get("quantity") is None:
            continue
        sage_q, sage_v = Decimal(str(i["quantity"])), Decimal(str(i["value"]))
        if sage_q >= 0 and abs(sage_v) < 1:
            continue  # rounding dust Sage leaves on a finished lot
        o = overlays.get(sku, {"quantity": ZERO, "value": ZERO})
        deficit = -(sage_q + o["quantity"])
        carried = sage_v + o["value"]
        unit = (sage_v / sage_q) if sage_q else ZERO
        ic = q1(conn, """SELECT MIN(txn_date) AS first_txn, MAX(txn_date) AS last_txn,
                                COALESCE(SUM(qty_received),0) AS received, COALESCE(SUM(qty_adjusted),0) AS adjusted,
                                COALESCE(SUM(qty_sold),0) AS sold, MIN(txn_date) FILTER (WHERE remaining_qty < 0) AS first_negative,
                                MAX(txn_date) FILTER (WHERE COALESCE(qty_received,0) > 0) AS last_receipt
                         FROM fin_sage_item_costing WHERE legal_entity_id=%s AND sku=%s""", (e, sku)) or {}
        never = not ic.get("received")
        name = q1(conn, "SELECT name FROM fin_products WHERE legal_entity_id=%s AND sku=%s", (e, sku))
        since = ic.get("first_negative")
        cause = ("Its receipt was never entered in Sage" if never else
                 f"Sage sold {money(ic.get('sold') or 0):,.0f} against {money(ic.get('received') or 0):,.0f} received")
        _upsert(conn, e, "STOCK_SHORT_LOT", sku,
                title=f"{sku}: sold {abs(sage_q):,.0f} more than Sage holds",
                summary=f"{cause}{f'; below zero since {since:%d %b %Y}' if since else ''}. "
                        f"Sage values the shortfall at ₦{abs(sage_v):,.2f}.",
                severity="HIGH" if abs(sage_v) >= 1_000_000 else ("MEDIUM" if abs(sage_v) >= 50_000 else "LOW"),
                amount=money(-carried) if deficit > 0 else ZERO, quantity=deficit if deficit > 0 else ZERO, as_of=snap["as_of"],
                detail={"sku": sku, "name": (name or {}).get("name") or i.get("name") or sku, "family": family(sku),
                        "sage_quantity": str(sage_q), "sage_value": str(sage_v), "sage_unit_cost": str(round(unit, 4)),
                        "corrected_quantity": str(o["quantity"]), "corrected_value": str(o["value"]),
                        "deficit": str(deficit), "never_received": never,
                        "costing": {k: str(v) if v is not None else None for k, v in ic.items()}},
                cleared=deficit <= 0)
        seen.add(sku)
    # lots corrected back above zero by a later export are cleared too
    for r in q(conn, "SELECT key FROM fin_data_exceptions WHERE legal_entity_id=%s AND kind='STOCK_SHORT_LOT' AND status='OPEN'", (e,)):
        if r["key"] not in seen:
            ex(conn, """UPDATE fin_data_exceptions SET status='RESOLVED', resolution='CLEARED_BY_DATA', resolved_at=now(),
                        last_seen=now() WHERE legal_entity_id=%s AND kind='STOCK_SHORT_LOT' AND key=%s""", (e, r["key"]))
    return len(seen)


def _tb_gl(conn, e: str) -> int:
    snap = snapshot(conn, e, "TRIAL_BALANCE")
    if not snap:
        return 0
    as_of = snap["as_of"]
    acc = books_ledger.accounts(conn, e)
    hist = books_ledger._hist_balances(conn, e, as_of)
    jan = books_ledger._hist_balances(conn, e, dt.date(as_of.year, 1, 1), start_of_day=True)
    # Sage's Trial Balance knows nothing of the stock corrections made here; only corrections
    # decided on this check count towards it.
    for a in q(conn, """SELECT a.gl_delta FROM fin_data_exception_actions a JOIN fin_data_exceptions x ON x.id=a.exception_id
                        WHERE a.legal_entity_id=%s AND x.kind <> 'TB_GL_DIFFERENCE'""", (e,)):
        for g in a["gl_delta"] or []:
            hist[g["account_code"]] = hist.get(g["account_code"], ZERO) - (Decimal(g["debit"]) - Decimal(g["credit"]))
    diffs = []
    for r in snap["rows"]:
        want = money(r["debit"]) - money(r["credit"])
        got = hist.get(r["code"], ZERO) - (jan.get(r["code"], ZERO) if acc.get(r["code"], {}).get("account_type")
                                           in books_ledger.PL_TYPES else ZERO)
        if got != want:
            diffs.append({"code": r["code"], "name": r.get("name") or acc.get(r["code"], {}).get("name"),
                          "trial_balance": str(want), "general_ledger": str(got), "difference": str(want - got)})
    key = str(as_of)
    total = sum((abs(Decimal(d["difference"])) for d in diffs), ZERO) / 2
    docs = _missing_documents(conn, e, as_of, [d["code"] for d in diffs]) if diffs else []
    _upsert(conn, e, "TB_GL_DIFFERENCE", key,
            title=f"Sage Trial Balance and General Ledger differ at {as_of:%d %b %Y}",
            summary=(f"{len(diffs)} account(s) differ by ₦{total:,.2f}. "
                     + (f"{len(docs)} source document(s) explain it." if docs else "No source document found - check the export."))
            if diffs else "The Trial Balance agrees with the General Ledger.",
            severity="MEDIUM", amount=total, quantity=None, as_of=as_of,
            detail={"accounts": diffs, "documents": docs}, cleared=not diffs)
    return 1 if diffs else 0


def _missing_documents(conn, e: str, as_of: dt.date, codes: List[str]) -> List[Dict[str, Any]]:
    """Source documents (Sage journals) whose entries on these accounts differ from the General
    Ledger export - e.g. an invoice edited in Sage after the ledger was exported."""
    rows = q(conn, """
        WITH j AS (SELECT kind, reference, account_code, MIN(txn_date) AS d, SUM(debit - credit) AS v
                   FROM fin_sage_journal_lines WHERE legal_entity_id=%(e)s AND kind <> 'COGS' AND account_code = ANY(%(c)s)
                     AND txn_date BETWEEN %(f)s AND %(t)s AND reference IS NOT NULL GROUP BY 1,2,3),
             g AS (SELECT reference, account_code, SUM(debit - credit) AS v FROM fin_sage_gl_lines
                   WHERE legal_entity_id=%(e)s AND account_code = ANY(%(c)s) AND txn_date BETWEEN %(f)s AND %(t)s
                     AND COALESCE(jrnl,'') <> 'ADJ' GROUP BY 1,2),
             fix AS (SELECT reference, account_code, SUM(debit - credit) AS v FROM fin_sage_gl_lines
                     WHERE legal_entity_id=%(e)s AND jrnl='ADJ' AND load_id IS NULL GROUP BY 1,2)
        SELECT j.kind, j.reference, j.account_code, j.d, j.v AS journal, COALESCE(g.v,0) AS ledger, j.v - COALESCE(g.v,0) AS difference
        FROM j LEFT JOIN g ON g.reference=j.reference AND g.account_code=j.account_code
        WHERE j.v <> COALESCE(g.v,0) ORDER BY j.d, j.reference""",
             {"e": e, "c": codes, "f": as_of - dt.timedelta(days=120), "t": as_of})
    # corrections already posted for a document (FIX lines quote the document in their description)
    fixed = {r["doc"] for r in q(conn, """SELECT DISTINCT a.payload->>'document' AS doc FROM fin_data_exception_actions a
                                          WHERE a.legal_entity_id=%s AND a.action='post_missing_entry'""", (e,))}
    docs: Dict[str, Dict[str, Any]] = {}
    for r in rows:
        d = docs.setdefault(f"{r['kind']}:{r['reference']}", {
            "kind": r["kind"], "reference": r["reference"], "date": str(r["d"]), "lines": [], "corrected": r["reference"] in fixed})
        d["lines"].append({"account_code": r["account_code"], "journal": str(r["journal"]), "ledger": str(r["ledger"]),
                           "difference": str(r["difference"])})
    out = list(docs.values())
    for d in out:
        p = q1(conn, """SELECT customer_name AS party, customer_id FROM fin_sage_sales_lines WHERE legal_entity_id=%s
                        AND invoice_number=%s LIMIT 1""", (e, d["reference"])) if d["kind"] == "SJ" else None
        d["party"] = p["party"] if p else None
        d["customer_id"] = p["customer_id"] if p else None
    return out


def _party_control(conn, e: str, kind: str) -> int:
    """Control account against the open items, party by party (Sage's ledger is the lineage)."""
    from src.fin import reports
    key_map = "AR_CONTROL" if kind == "AR_CONTROL" else "AP_CONTROL"
    acct = rules.optional(conn, e, key_map)
    if not acct:
        return 0
    today = dt.date.today()
    h = books_ledger.history_until(conn, e) or today
    as_of = max(today, h)
    gl = books_ledger.balances(conn, e, as_of, [acct["code"]]).get(acct["code"], ZERO)
    if kind == "AP_CONTROL":
        gl = -gl
    items = reports.ar_open_items(conn, e, as_of) if kind == "AR_CONTROL" else reports.ap_open_items(conn, e, as_of)
    party_col = "customer_id" if kind == "AR_CONTROL" else "supplier_id"
    sub = sum((money(i["open_amount"]) for i in items), ZERO)
    diff = gl - sub
    parties: List[Dict[str, Any]] = []
    ledger_total = ZERO
    if diff != 0:
        open_by: Dict[str, Decimal] = {}
        for i in items:
            pid = str(i.get(party_col))
            open_by[pid] = open_by.get(pid, ZERO) + money(i["open_amount"])
        pk = "CUSTOMER" if kind == "AR_CONTROL" else "VENDOR"
        led = q(conn, f"""SELECT DISTINCT ON (party_code) party_code, party_name, {party_col}::text AS pid, balance, txn_date
                          FROM fin_sage_party_ledger WHERE legal_entity_id=%s AND party_kind=%s AND txn_date <= %s
                          ORDER BY party_code, txn_date DESC, seq DESC""", (e, pk, h))
        for r in led:
            sage_bal = money(r["balance"] or 0)
            ace = open_by.get(r["pid"] or "", ZERO)
            if sage_bal != ace:
                parties.append({"party_code": r["party_code"], "party": r["party_name"], "party_id": r["pid"],
                                "sage_ledger_balance": str(sage_bal), "open_items": str(ace), "difference": str(sage_bal - ace),
                                "last_ledger_date": str(r["txn_date"])})
        ledger_total = sum((money(r["balance"] or 0) for r in led), ZERO)
        in_ledger = {r["pid"] for r in led}
        for pid, amt in open_by.items():
            if pid not in in_ledger and amt != 0:
                nm = q1(conn, "SELECT name FROM customers WHERE id::text=%s" if kind == "AR_CONTROL" else
                        "SELECT name FROM suppliers WHERE id::text=%s", (pid,))
                parties.append({"party_code": None, "party": (nm or {}).get("name") or pid, "party_id": pid,
                                "sage_ledger_balance": "0", "open_items": str(amt), "difference": str(-amt),
                                "last_ledger_date": None})
        parties.sort(key=lambda p: -abs(Decimal(p["difference"])))
    what = "customer" if kind == "AR_CONTROL" else "supplier"
    _upsert(conn, e, kind, "LIVE",
            title=f"{'Receivables' if kind == 'AR_CONTROL' else 'Payables'} control {acct['code']} vs {what} balances",
            summary=(f"The control account is ₦{gl:,.2f}; open {what} items total ₦{sub:,.2f} (difference ₦{diff:,.2f}). "
                     f"{len(parties)} {what}(s) differ between Sage's ledger and the open items.") if diff else
                    f"The control account agrees with the {what} balances.",
            severity="MEDIUM", amount=diff, quantity=None, as_of=as_of,
            detail={"account": acct["code"], "control": str(gl), "open_items": str(sub), "difference": str(diff),
                    "sage_ledgers_total": str(ledger_total), "parties": parties[:200]}, cleared=diff == 0)
    return 1 if diff else 0


def _inventory_control(conn, e: str) -> int:
    today = dt.date.today()
    h = books_ledger.history_until(conn, e) or today
    as_of = max(today, h)
    acc = books_ledger.accounts(conn, e)
    bal = books_ledger.balances(conn, e, as_of)
    gl_by = {c: v for c, v in bal.items() if acc.get(c, {}).get("subtype") == "INVENTORY" and v != 0}
    stock_by: Dict[str, Decimal] = {}
    for r in q(conn, """SELECT COALESCE(a.code, d.code) AS code, SUM(l.qty_remaining * l.unit_cost) AS v
                        FROM fin_cost_layers l JOIN fin_products p ON p.legal_entity_id=l.legal_entity_id AND p.sku=l.sku
                        LEFT JOIN fin_accounts a ON a.id=p.inventory_account_id
                        LEFT JOIN fin_account_mappings m ON m.legal_entity_id=l.legal_entity_id AND m.mapping_key='INVENTORY_DEFAULT'
                        LEFT JOIN fin_accounts d ON d.id=m.account_id
                        WHERE l.legal_entity_id=%s AND l.qty_remaining > 0 GROUP BY 1""", (e,)):
        stock_by[r["code"]] = money(r["v"])
    short = {}
    for r in q(conn, """SELECT x.id::text AS id, x.key AS sku, x.amount, COALESCE(a.code, d.code) AS code
                        FROM fin_data_exceptions x JOIN fin_products p ON p.legal_entity_id=x.legal_entity_id AND p.sku=x.key
                        LEFT JOIN fin_accounts a ON a.id=p.inventory_account_id
                        LEFT JOIN fin_account_mappings m ON m.legal_entity_id=x.legal_entity_id AND m.mapping_key='INVENTORY_DEFAULT'
                        LEFT JOIN fin_accounts d ON d.id=m.account_id
                        WHERE x.legal_entity_id=%s AND x.kind='STOCK_SHORT_LOT' AND x.status='OPEN'""", (e,)):
        short.setdefault(r["code"], []).append({"id": r["id"], "sku": r["sku"], "amount": str(r["amount"])})
    rows = []
    for code in sorted(set(gl_by) | set(stock_by)):
        g, s = gl_by.get(code, ZERO), stock_by.get(code, ZERO)
        if g != s:
            rows.append({"code": code, "name": acc.get(code, {}).get("name"), "general_ledger": str(g), "stock": str(s),
                         "difference": str(g - s), "short_lots": short.get(code, [])})
    gl, st = sum(gl_by.values(), ZERO), sum(stock_by.values(), ZERO)
    diff = gl - st
    explained = -sum((Decimal(x["amount"]) for v in short.values() for x in v), ZERO)
    _upsert(conn, e, "INVENTORY_CONTROL", "LIVE", title="Inventory accounts vs valued stock",
            summary=(f"Inventory accounts total ₦{gl:,.2f}; valued stock is ₦{st:,.2f} (difference ₦{diff:,.2f}). "
                     f"Open short lots account for ₦{explained:,.2f} of it.") if abs(diff) >= 1 else
                    "The inventory accounts agree with the valued stock.",
            severity="HIGH" if abs(diff) >= 1_000_000 else "MEDIUM", amount=diff, quantity=None, as_of=as_of,
            detail={"general_ledger": str(gl), "stock": str(st), "difference": str(diff), "explained_by_short_lots": str(explained),
                    "accounts": rows}, cleared=abs(diff) < 1)
    return 1 if abs(diff) >= 1 else 0


def refresh(conn, ctx) -> Dict[str, Any]:
    e = ctx.entity_id
    found = {"STOCK_SHORT_LOT": _short_lots(conn, e), "TB_GL_DIFFERENCE": _tb_gl(conn, e),
             "AR_CONTROL": _party_control(conn, e, "AR_CONTROL"), "AP_CONTROL": _party_control(conn, e, "AP_CONTROL")}
    found["INVENTORY_CONTROL"] = _inventory_control(conn, e)
    return {"found": found, **summary(conn, e)}


# ---------------------------------------------------------------------------
# Reading
# ---------------------------------------------------------------------------

def summary(conn, e: str) -> Dict[str, Any]:
    rows = q(conn, """SELECT kind, status, COUNT(*) n, COALESCE(SUM(ABS(amount)),0) amount FROM fin_data_exceptions
                      WHERE legal_entity_id=%s GROUP BY 1,2""", (e,))
    return {"by_kind": [{**r, "label": KIND_LABEL.get(r["kind"], r["kind"])} for r in rows],
            "open": sum(r["n"] for r in rows if r["status"] == "OPEN")}


def list_exceptions(conn, e: str, status: Optional[str] = None, kind: Optional[str] = None) -> List[Dict[str, Any]]:
    where, p = ["legal_entity_id=%s"], [e]
    if status:
        where.append("status=%s")
        p.append(status.upper())
    if kind:
        where.append("kind=%s")
        p.append(kind.upper())
    rows = q(conn, f"""SELECT id, kind, key, title, summary, severity, amount, quantity, as_of, status, resolution, resolution_note,
                              resolved_by, resolved_at, first_seen, last_seen
                       FROM fin_data_exceptions WHERE {' AND '.join(where)}
                       ORDER BY (status='OPEN') DESC, CASE severity WHEN 'HIGH' THEN 0 WHEN 'MEDIUM' THEN 1 ELSE 2 END,
                                ABS(COALESCE(amount,0)) DESC""", p)
    for r in rows:
        r["kind_label"] = KIND_LABEL.get(r["kind"], r["kind"])
    return rows


def get(conn, e: str, exc_id: str) -> Dict[str, Any]:
    x = q1(conn, "SELECT * FROM fin_data_exceptions WHERE id=%s AND legal_entity_id=%s", (exc_id, e))
    if not x:
        raise not_found("Data exception", exc_id)
    x["kind_label"] = KIND_LABEL.get(x["kind"], x["kind"])
    x["actions"] = q(conn, """SELECT a.*, j.journal_number FROM fin_data_exception_actions a
                              LEFT JOIN fin_journals j ON j.id=a.journal_id WHERE a.exception_id=%s ORDER BY a.created_at""", (exc_id,))
    x["lineage"] = _lineage(conn, e, x)
    x["options"] = _options(x)
    return x


def _lineage(conn, e: str, x: Dict[str, Any]) -> Dict[str, Any]:
    d = x["detail"] or {}
    if x["kind"] == "STOCK_SHORT_LOT":
        sku = x["key"]
        since = (d.get("costing") or {}).get("first_negative")
        sales = q(conn, """SELECT invoice_number, invoice_date, customer_id, customer_name, quantity, amount, cost
                           FROM fin_sage_sales_lines WHERE legal_entity_id=%s AND sku=%s AND invoice_date >= COALESCE(%s::date, '1900-01-01')
                           ORDER BY invoice_date, invoice_number LIMIT 500""", (e, sku, since))
        costing = q(conn, """SELECT txn_date, qty_received, received_cost, qty_adjusted, qty_sold, cost_of_sales, remaining_qty, remaining_value
                             FROM fin_sage_item_costing WHERE legal_entity_id=%s AND sku=%s ORDER BY txn_date DESC, id DESC LIMIT 60""", (e, sku))
        fam = family(sku)
        purchases = q(conn, """SELECT bill_number, bill_date, supplier_id::text AS supplier_id, supplier_name, sku, quantity, amount
                               FROM fin_sage_purchase_lines WHERE legal_entity_id=%s AND (sku=%s OR sku ILIKE %s)
                               ORDER BY bill_date DESC LIMIT 15""", (e, sku, f"{fam}%"))
        lots = q(conn, """SELECT p.sku, b.id::text AS batch_id, b.batch_number, b.expiry_date, b.status, SUM(l.qty_remaining) AS available,
                                 ROUND(SUM(l.qty_remaining*l.unit_cost)/NULLIF(SUM(l.qty_remaining),0),2) AS unit_cost
                          FROM fin_cost_layers l JOIN fin_products p ON p.legal_entity_id=l.legal_entity_id AND p.sku=l.sku
                          LEFT JOIN fin_batches b ON b.id=l.batch_id
                          WHERE l.legal_entity_id=%s AND l.qty_remaining > 0 AND p.sku <> %s AND p.sku ILIKE %s
                          GROUP BY p.sku, b.id ORDER BY b.expiry_date NULLS LAST""", (e, sku, f"{fam}%"))
        lots = [l for l in lots if family(l["sku"]) == fam]
        return {"sales_below_zero": sales, "item_costing": costing, "supplier_bills": purchases, "other_lots": lots}
    if x["kind"] == "TB_GL_DIFFERENCE":
        out = []
        for doc in d.get("documents") or []:
            jl = q(conn, """SELECT txn_date, account_code, account_description, description, qty, debit, credit FROM fin_sage_journal_lines
                            WHERE legal_entity_id=%s AND kind=%s AND reference=%s ORDER BY seq""", (e, doc["kind"], doc["reference"]))
            gl = q(conn, """SELECT txn_date, account_code, jrnl, description, debit, credit FROM fin_sage_gl_lines
                            WHERE legal_entity_id=%s AND reference=%s ORDER BY seq""", (e, doc["reference"]))
            out.append({**doc, "journal_lines": jl, "ledger_lines": gl})
        return {"documents": out}
    return {}


def _options(x: Dict[str, Any]) -> List[Dict[str, Any]]:
    """The resolutions the finance team can choose, with what each one does to the books."""
    if x["status"] != "OPEN":
        return [{"action": "reopen", "label": "Reopen", "effect": "Puts the problem back on the open list. Nothing is reversed."}]
    k = x["kind"]
    accept = {"action": "accept", "label": "Accept as it is",
              "effect": "Records the decision and the reason; nothing is posted. The difference stays in the books."}
    if k == "STOCK_SHORT_LOT":
        return [
            {"action": "record_receipt", "label": "Record the missing receipt",
             "effect": "The goods arrived but the receipt was never entered. Adds the quantity received to the lot at its "
                       "cost (credit: goods received accrual until the supplier's invoice is entered); what remains after "
                       "the sales already made becomes sellable stock."},
            {"action": "move_from_lot", "label": "Sold under the wrong lot",
             "effect": "The sales were keyed against this lot but the stock left another lot of the same product. Moves "
                       "the quantity from that lot to this one; no supplier is involved."},
            {"action": "physical_count", "label": "Use a physical count",
             "effect": "Sets the lot to what was counted on the shelf; the difference goes to Inventory Adjustments."},
            accept]
    if k == "TB_GL_DIFFERENCE":
        return [
            {"action": "post_missing_entry", "label": "The Trial Balance is right - post the missing entry",
             "effect": "Posts the document's lines that are missing from the General Ledger export (e.g. a line added to "
                       "an invoice after the ledger was exported), quoting the document."},
            {"action": "reduce_document", "label": "The General Ledger is right - correct the document",
             "effect": "Reduces the brought-forward invoice by the amount the ledger never had. No journal: the ledger "
                       "already excludes it."},
            accept]
    return [accept]


# ---------------------------------------------------------------------------
# Resolutions
# ---------------------------------------------------------------------------

def _lock(conn, e: str, exc_id: str) -> Dict[str, Any]:
    x = q1(conn, "SELECT * FROM fin_data_exceptions WHERE id=%s AND legal_entity_id=%s FOR UPDATE", (exc_id, e))
    if not x:
        raise not_found("Data exception", exc_id)
    return x


def _close(conn, ctx, x: Dict[str, Any], status: str, resolution: str, note: Optional[str]) -> None:
    ex(conn, """UPDATE fin_data_exceptions SET status=%s, resolution=%s, resolution_note=%s, resolved_by=%s, resolved_at=now()
                WHERE id=%s""", (status, resolution, note, ctx.actor_name or ctx.actor_id, x["id"]))


def resolve(conn, ctx, exc_id: str, action: str, data: Dict[str, Any]) -> Dict[str, Any]:
    ctx.require("controls.exception.resolve")
    e = ctx.entity_id
    x = _lock(conn, e, exc_id)
    note = (data.get("note") or "").strip() or None
    if action == "reopen":
        if x["status"] == "OPEN":
            raise invalid("This problem is already open")
        ex(conn, "UPDATE fin_data_exceptions SET status='OPEN', resolution=NULL, resolved_by=NULL, resolved_at=NULL WHERE id=%s", (x["id"],))
        _log(conn, ctx, x, "reopen", note=note, payload={})
        return get(conn, e, exc_id)
    if x["status"] != "OPEN":
        raise FinError("INVALID_STATE_TRANSITION", f"This problem is {x['status'].lower()}; reopen it first")
    if action == "accept":
        if not note:
            raise invalid("Give the reason for accepting it as it is (it is kept with the decision)")
        _log(conn, ctx, x, "accept", note=note, payload={})
        _close(conn, ctx, x, "ACCEPTED", "ACCEPTED", note)
        return get(conn, e, exc_id)
    fn = {("STOCK_SHORT_LOT", "record_receipt"): _record_receipt, ("STOCK_SHORT_LOT", "physical_count"): _physical_count,
          ("STOCK_SHORT_LOT", "move_from_lot"): _move_from_lot, ("TB_GL_DIFFERENCE", "post_missing_entry"): _post_missing_entry,
          ("TB_GL_DIFFERENCE", "reduce_document"): _reduce_document}.get((x["kind"], action))
    if not fn:
        raise invalid(f"'{action}' does not apply to this kind of problem")
    fn(conn, ctx, x, data, note)
    refresh(conn, ctx)
    x = q1(conn, "SELECT * FROM fin_data_exceptions WHERE id=%s", (exc_id,))
    if x["status"] == "RESOLVED" and x["resolution"] == "CLEARED_BY_DATA":
        ex(conn, "UPDATE fin_data_exceptions SET resolution=%s, resolution_note=%s, resolved_by=%s WHERE id=%s",
           (action.upper(), note, ctx.actor_name or ctx.actor_id, exc_id))
    return get(conn, e, exc_id)


def _lot_state(conn, e: str, x: Dict[str, Any]) -> Dict[str, Decimal]:
    d = x["detail"]
    o = stock_overlays(conn, e).get(x["key"], {"quantity": ZERO, "value": ZERO})
    sage_q, sage_v = Decimal(d["sage_quantity"]), Decimal(d["sage_value"])
    return {"deficit": -(sage_q + o["quantity"]), "carried": sage_v + o["value"],
            "sage_unit": (sage_v / sage_q) if sage_q else ZERO}


def _restock(conn, ctx, sku: str, qn: Decimal, unit: Decimal, txn_type: str, ref: str, reason: str, data: Dict[str, Any],
             supplier_id: Any = None) -> None:
    on = books_ledger.history_until(conn, ctx.entity_id) or dt.date.today()
    lot = (data.get("batch_number") or "").strip() or sage_history.lot_label(sku)
    p = q1(conn, "SELECT lot_expiry FROM fin_products WHERE legal_entity_id=%s AND sku=%s", (ctx.entity_id, sku)) or {}
    bid = inventory.ensure_batch(conn, ctx.entity_id, sku, lot, expiry_date=data.get("expiry_date") or p.get("lot_expiry"),
                                 manufacture_date=data.get("manufacture_date"), supplier_id=supplier_id)
    if data.get("expiry_date") or data.get("manufacture_date"):
        ex(conn, """UPDATE fin_batches SET expiry_date=COALESCE(%s, expiry_date), manufacture_date=COALESCE(%s, manufacture_date)
                    WHERE id=%s""", (data.get("expiry_date"), data.get("manufacture_date"), bid))
    inventory.receive(conn, ctx, sku=sku, quantity=qn, unit_cost=unit, txn_type=txn_type, txn_date=on, batch_id=bid,
                      source_type="DATA_CORRECTION", source_id=ref, reference=ref, reason=reason, supplier_id=supplier_id,
                      mirror=False)


def _receipt_like(conn, ctx, x, *, received: Decimal, unit: Decimal, credit_key: str, action: str, txn_type: str,
                  label: str, data: Dict[str, Any], note: Optional[str]) -> None:
    e, sku = ctx.entity_id, x["key"]
    st = _lot_state(conn, e, x)
    deficit = st["deficit"]
    remaining = received - deficit
    if remaining < 0:
        raise invalid(f"{sku} was sold {deficit:,.0f} more than Sage holds; {received:,.0f} still leaves it "
                      f"{-remaining:,.0f} short. Enter the full quantity (or use the physical count).")
    acc = rules.product_accounts(conn, e, sku)
    credit = rules.account(conn, e, credit_key)
    new_value = money(remaining * unit)
    d_inv = money(new_value - st["carried"])
    owed = money(received * unit)
    cogs = owed - d_inv  # Sage costed the sales already made at its own figure; this trues them up
    lines = []
    if d_inv:
        lines.append({"account_id": acc["inventory_account_id"], "debit": max(d_inv, ZERO), "credit": max(-d_inv, ZERO),
                      "product_sku": sku, "description": f"{sku}: {label}"})
    if cogs:
        lines.append({"account_id": acc["cogs_account_id"], "debit": max(cogs, ZERO), "credit": max(-cogs, ZERO),
                      "product_sku": sku, "description": f"{sku}: cost of the {deficit:,.0f} already sold at ₦{unit:,.2f}"})
    lines.append({"account_id": credit["id"], "credit": owed, "product_sku": sku, "supplier_id": data.get("supplier_id") or None,
                  "description": f"{sku}: {label}" + (f" (supplier ref {data['supplier_ref']})" if data.get("supplier_ref") else "")})
    posted = _post_correction(conn, ctx, x, lines, f"{sku}: {label}")
    if remaining > 0:
        _restock(conn, ctx, sku, remaining, unit, txn_type, posted["number"], label, data, data.get("supplier_id") or None)
    _log(conn, ctx, x, action, note=note, posted=posted,
         payload={k: (str(v) if isinstance(v, (Decimal, dt.date)) else v) for k, v in data.items()} |
                 {"received": str(received), "unit_cost": str(unit), "sellable_after": str(remaining)},
         stock_delta=[{"sku": sku, "quantity": str(received), "value": str(d_inv)}])


def _record_receipt(conn, ctx, x, data, note):
    received = qty(data.get("quantity") or 0)
    if received <= 0:
        raise invalid("Enter the quantity that was received")
    st = _lot_state(conn, ctx.entity_id, x)
    unit = Decimal(str(data.get("unit_cost") or 0)) or st["sage_unit"]
    if unit <= 0:
        raise invalid("Enter the unit cost on the supplier's invoice")
    when = data.get("receipt_date")
    label = f"receipt not entered in Sage{f' (received {when:%d %b %Y})' if isinstance(when, dt.date) else ''}"
    _receipt_like(conn, ctx, x, received=received, unit=unit, credit_key="GOODS_RECEIVED_ACCRUAL", action="record_receipt",
                  txn_type="PURCHASE", label=label, data=data, note=note)


def _physical_count(conn, ctx, x, data, note):
    counted = qty(data.get("on_hand") if data.get("on_hand") not in (None, "") else -1)
    if counted < 0:
        raise invalid("Enter the quantity counted on the shelf (0 if none)")
    st = _lot_state(conn, ctx.entity_id, x)
    unit = Decimal(str(data.get("unit_cost") or 0)) or st["sage_unit"]
    _receipt_like(conn, ctx, x, received=counted + st["deficit"], unit=unit, credit_key="INVENTORY_ADJUSTMENT",
                  action="physical_count", txn_type="STOCK_COUNT", label=f"physical count {counted:,.0f}", data=data, note=note)


def _move_from_lot(conn, ctx, x, data, note):
    e, sku = ctx.entity_id, x["key"]
    src = str(data.get("source_sku") or "").strip()
    moved = qty(data.get("quantity") or 0)
    if not src or src == sku:
        raise invalid("Choose the lot the stock actually came from")
    if family(src) != family(sku):
        raise invalid(f"{src} is not a lot of {family(sku)}")
    if moved <= 0:
        raise invalid("Enter the quantity to move")
    have = inventory.on_hand(conn, e, src)["quantity"]
    if have < moved:
        raise invalid(f"{src} holds {have:,.0f}; it cannot give {moved:,.0f}")
    st = _lot_state(conn, e, x)
    on = books_ledger.history_until(conn, e) or dt.date.today()
    number_hint = f"move {moved:,.0f} from {src}"
    number = next_number(conn, e, "DATA_CORRECTION")
    t = inventory.issue(conn, ctx, sku=src, quantity=moved, txn_type="TRANSFER_OUT", txn_date=on, source_type="DATA_CORRECTION",
                        source_id=number, reference=number, reason=f"Sold under {sku} in Sage", mirror=False)
    cost = money(t["cost"])
    unit = cost / moved
    remaining = moved - st["deficit"]
    new_value = money(max(remaining, ZERO) * unit)
    d_inv = money(new_value - st["carried"])
    a_src, a_dst = rules.product_accounts(conn, e, src), rules.product_accounts(conn, e, sku)
    lines = [{"account_id": a_src["inventory_account_id"], "credit": cost, "product_sku": src,
              "description": f"{src}: {moved:,.0f} sold in Sage under {sku}"}]
    if d_inv:
        lines.append({"account_id": a_dst["inventory_account_id"], "debit": max(d_inv, ZERO), "credit": max(-d_inv, ZERO),
                      "product_sku": sku, "description": f"{sku}: {number_hint}"})
    cogs = cost - d_inv
    if cogs:
        lines.append({"account_id": a_dst["cogs_account_id"], "debit": max(cogs, ZERO), "credit": max(-cogs, ZERO),
                      "product_sku": sku, "description": f"{sku}: cost of sales at {src}'s cost"})
    posted = _post_correction(conn, ctx, x, lines, f"{sku}: {number_hint}", number=number)
    inventory.link_journal(conn, [str(t["id"])], posted["journal"]["id"])
    if remaining > 0:
        _restock(conn, ctx, sku, remaining, unit, "TRANSFER_IN", posted["number"], number_hint, data)
    _log(conn, ctx, x, "move_from_lot", note=note, posted=posted,
         payload={"source_sku": src, "quantity": str(moved), "unit_cost": str(round(unit, 4))},
         stock_delta=[{"sku": src, "quantity": str(-moved), "value": str(-cost)},
                      {"sku": sku, "quantity": str(moved), "value": str(d_inv)}])


def _doc(x: Dict[str, Any], data: Dict[str, Any]) -> Dict[str, Any]:
    ref = str(data.get("document") or "").strip()
    docs = (x["detail"] or {}).get("documents") or []
    d = next((d for d in docs if d["reference"] == ref), None) if ref else (docs[0] if len(docs) == 1 else None)
    if not d:
        raise invalid("Choose the document this decision is about")
    if d.get("corrected"):
        raise invalid(f"{d['reference']} has already been corrected")
    return d


def _post_missing_entry(conn, ctx, x, data, note):
    e = ctx.entity_id
    d = _doc(x, data)
    ar = rules.optional(conn, e, "AR_CONTROL")
    lines = []
    for l in d["lines"]:
        v = Decimal(l["difference"])
        a = q1(conn, "SELECT id FROM fin_accounts WHERE legal_entity_id=%s AND code=%s", (e, l["account_code"]))
        if not a:
            raise invalid(f"Account {l['account_code']} is not in the chart of accounts")
        lines.append({"account_id": a["id"], "debit": max(v, ZERO), "credit": max(-v, ZERO),
                      "customer_id": d.get("customer_id") if ar and l["account_code"] == ar["code"] else None,
                      "description": f"{d['kind']} {d['reference']}{' ' + d['party'] if d.get('party') else ''}: "
                                     f"entry missing from Sage's General Ledger export"})
    posted = _post_correction(conn, ctx, x, lines, f"{d['kind']} {d['reference']} - missing from the General Ledger export")
    _log(conn, ctx, x, "post_missing_entry", note=note, posted=posted, payload={"document": d["reference"], "kind": d["kind"]})


def _reduce_document(conn, ctx, x, data, note):
    e = ctx.entity_id
    d = _doc(x, data)
    ar = rules.optional(conn, e, "AR_CONTROL")
    line = next((l for l in d["lines"] if ar and l["account_code"] == ar["code"]), None)
    if d["kind"] != "SJ" or not line:
        raise invalid("Only an invoice's receivable can be corrected this way; accept it with a note instead")
    v = Decimal(line["difference"])
    inv = q1(conn, """SELECT id, total, amount_settled FROM fin_sales_invoices WHERE legal_entity_id=%s AND is_opening
                      AND (invoice_number=%s OR split_part(source_id, ':', 3)=%s) FOR UPDATE""", (e, d["reference"], d["reference"]))
    if not inv:
        raise invalid(f"Invoice {d['reference']} is not among the open items brought forward")
    if money(inv["total"]) - v < money(inv["amount_settled"]):
        raise invalid(f"Invoice {d['reference']} has payments applied beyond the corrected amount")
    ex(conn, """UPDATE fin_sales_invoices SET total=total-%s, subtotal=subtotal-%s,
                original_total=CASE WHEN original_total IS NULL THEN NULL ELSE original_total-%s END WHERE id=%s""", (v, v, v, inv["id"]))
    _log(conn, ctx, x, "reduce_document", note=note, payload={"document": d["reference"], "reduced_by": str(v)})
    _close(conn, ctx, x, "ACCEPTED", "REDUCE_DOCUMENT", note or f"General Ledger is right; invoice {d['reference']} reduced by ₦{v:,.2f}")


# ---------------------------------------------------------------------------
# For the invoice form: lots whose receipt is still missing
# ---------------------------------------------------------------------------

def pending_lots(conn, e: str, families: List[str]) -> Dict[str, List[Dict[str, Any]]]:
    """Open short lots by product family, newest first: the invoice form shows them so a sale of
    the newest stock is never blocked silently - the user can record the receipt there."""
    if not families:
        return {}
    out: Dict[str, List[Dict[str, Any]]] = {}
    for r in q(conn, """SELECT id::text AS id, key AS sku, quantity, amount, detail FROM fin_data_exceptions
                        WHERE legal_entity_id=%s AND kind='STOCK_SHORT_LOT' AND status='OPEN'""", (e,)):
        f = family(r["sku"])
        if f in families:
            out.setdefault(f, []).append({"exception_id": r["id"], "sku": r["sku"], "short_by": r["quantity"],
                                          "sage_unit_cost": (r["detail"] or {}).get("sage_unit_cost"),
                                          "never_received": (r["detail"] or {}).get("never_received")})
    for v in out.values():
        v.sort(key=lambda p: p["sku"], reverse=True)
    return out
