"""Hand-over: ACE Books takes the record from Sage at a new date (e.g. 30 Jun -> 7 Oct 2026).

Sage stayed the record after the first transfer, so ACE Books must be brought forward to the
date of the latest Sage export before it is used for real. Inputs are that export's folder:
the General Ledger history (already loaded by sage_ledger), the Trial Balance, Aged
Receivables, Aged Payables and Inventory Valuation, all as of the same date.

    1. Documents ACE Books itself recorded inside the Sage period (tests) are listed; invoices
       among them are voided with a reason when asked (they would otherwise count twice).
    2. One journal per month brings every account to Sage's balance (General Ledger history):
       first the changes Sage made up to the old hand-over date after the first export, then
       July, August, ... to the new date. Journal type ADJUSTMENT, source MIGRATION.
    3. Open receivables / payables are replaced by the export's aged reports, under the real
       Sage invoice numbers, with their real dates and original amounts.
    4. Stock is replaced by Sage's valuation: each item (lot) with its expiry.
    5. Invoice numbers continue Sage's sequence; history_until / cutover move to the new date.

``plan`` shows all of it without changing anything; ``run`` does it in one transaction.
"""
from __future__ import annotations

import datetime as dt
import re
from decimal import Decimal
from typing import Any, Dict, List, Optional

from src.fin import audit, books_ledger, inventory, migration, posting, sage_history, sage_ledger, sales
from src.fin.db import ZERO, ex, jsonb, money, q, q1, qty
from src.fin.errors import FinError, invalid

ONE = dt.timedelta(days=1)


def _month_ends(f: dt.date, t: dt.date) -> List[dt.date]:
    out, m = [], f.replace(day=1)
    while m <= t:
        nxt = (m.replace(day=28) + dt.timedelta(days=4)).replace(day=1)
        out.append(min(nxt - ONE, t))
        m = nxt
    return [d for d in out if d >= f]


def _snapshots(folder: str) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    for f in sage_ledger.scan_folder(folder):
        if f["kind"] in sage_ledger.SNAPSHOT_KINDS:
            out[f["kind"]] = {"file": f["file"], "parsed": migration.parse(f["kind"], [list(r) for r in f["rows"]])}
    missing = [k for k in sage_ledger.SNAPSHOT_KINDS if k not in out]
    if missing:
        raise invalid(f"The export folder is missing: {', '.join(missing)}")
    return out


def _ace_docs_in_period(conn, entity_id: str, after: dt.date, until: dt.date) -> List[Dict[str, Any]]:
    """Documents ACE Books recorded itself (not brought forward) dated inside the Sage period."""
    return q(conn, """
        SELECT 'invoice' AS kind, id::text AS id, invoice_number AS number, invoice_date AS date, total, status FROM fin_sales_invoices
         WHERE legal_entity_id=%(e)s AND NOT is_opening AND status <> 'VOID' AND invoice_date > %(a)s AND invoice_date <= %(u)s
        UNION ALL SELECT 'receipt', id::text, receipt_number, receipt_date, amount, status FROM fin_customer_receipts
         WHERE legal_entity_id=%(e)s AND status='POSTED' AND receipt_date > %(a)s AND receipt_date <= %(u)s
        UNION ALL SELECT 'credit note', id::text, credit_note_number, note_date, total, status FROM fin_credit_notes
         WHERE legal_entity_id=%(e)s AND status='POSTED' AND journal_id IS NOT NULL AND note_date > %(a)s AND note_date <= %(u)s
        UNION ALL SELECT 'bill', id::text, bill_number, bill_date, total, status FROM fin_supplier_bills
         WHERE legal_entity_id=%(e)s AND NOT is_opening AND status <> 'VOID' AND bill_date > %(a)s AND bill_date <= %(u)s
        UNION ALL SELECT 'payment', id::text, payment_number, payment_date, amount, status FROM fin_supplier_payments
         WHERE legal_entity_id=%(e)s AND status='POSTED' AND payment_date > %(a)s AND payment_date <= %(u)s
        UNION ALL SELECT 'journal', id::text, journal_number, journal_date, total_debit, status FROM fin_journals
         WHERE legal_entity_id=%(e)s AND status='POSTED' AND source_type='MANUAL_JOURNAL' AND journal_date > %(a)s AND journal_date <= %(u)s
        ORDER BY date""", {"e": entity_id, "a": after, "u": until})


def _next_invoice_number(conn, entity_id: str, as_of: dt.date) -> Optional[int]:
    """Sage's running invoice sequence: the highest plain invoice number used in the last 30
    days of the export (other series - '0058437', '00068', 58xxx - are left alone)."""
    r = q1(conn, r"""SELECT MAX(reference::bigint) n FROM fin_sage_journal_lines
                     WHERE legal_entity_id=%s AND kind='SJ' AND reference ~ '^[1-9][0-9]{3,6}$'
                       AND txn_date BETWEEN %s AND %s""", (entity_id, as_of - dt.timedelta(days=30), as_of))
    return int(r["n"]) + 1 if r and r["n"] else None


def plan(conn, ctx, as_of: dt.date, folder: str) -> Dict[str, Any]:
    e = ctx.entity_id
    snaps = _snapshots(folder)
    old_h = books_ledger.history_until(conn, e)
    cov = q1(conn, "SELECT MAX(date_to) d FROM fin_sage_loads WHERE legal_entity_id=%s AND kind='GENERAL_LEDGER'", (e,))
    if not cov or not cov["d"] or cov["d"] < as_of:
        raise invalid(f"Load the General Ledger up to {as_of} first (Sage history ends {cov['d'] if cov else 'nowhere'})")
    hist = books_ledger._hist_balances(conn, e, as_of)
    jan = books_ledger._hist_balances(conn, e, dt.date(as_of.year, 1, 1), start_of_day=True)
    acc = books_ledger.accounts(conn, e)
    tb_diff = []
    for r in snaps["TRIAL_BALANCE"]["parsed"]["rows"]:
        want = money(r["debit"]) - money(r["credit"])
        got = hist.get(r["code"], ZERO) - (jan.get(r["code"], ZERO) if acc.get(r["code"], {}).get("account_type") in
                                           books_ledger.PL_TYPES else ZERO)
        if got != want:
            tb_diff.append({"account": r["code"], "name": r["name"], "trial_balance": want, "general_ledger": got,
                            "difference": want - got})
    maps = {m["mapping_key"]: m["code"] for m in q(conn, """SELECT m.mapping_key, a.code FROM fin_account_mappings m
                                                           JOIN fin_accounts a ON a.id=m.account_id WHERE m.legal_entity_id=%s""", (e,))}
    ar_total = snaps["OPEN_AR"]["parsed"]["summary"]["total"]
    ap_total = snaps["OPEN_AP"]["parsed"]["summary"]["total"]
    inv = snaps["INVENTORY"]["parsed"]
    inv_gl = sum((v for c, v in hist.items() if acc.get(c, {}).get("subtype") == "INVENTORY"), ZERO)
    months = [old_h] + _month_ends(old_h + ONE, as_of) if old_h and old_h < as_of else [as_of]
    return {
        "as_of": as_of, "previous_hand_over": old_h, "journals": [str(d) for d in months],
        "documents_inside_sage_period": _ace_docs_in_period(conn, e, old_h or dt.date(1900, 1, 1), as_of),
        "trial_balance_vs_general_ledger": tb_diff,
        "receivables": {"aged_report_total": ar_total, "control_account": hist.get(maps.get("AR_CONTROL"), ZERO),
                        "documents": snaps["OPEN_AR"]["parsed"]["summary"]["documents"]},
        "payables": {"aged_report_total": ap_total, "control_account": -hist.get(maps.get("AP_CONTROL"), ZERO),
                     "documents": snaps["OPEN_AP"]["parsed"]["summary"]["documents"]},
        "stock": {"items_loaded": inv["summary"]["items"], "value_loaded": inv["summary"]["total_value"],
                  "items_not_loaded": inv["issues"], "inventory_accounts_in_gl": inv_gl,
                  "sage_report_total": inv["summary"].get("sage_report_total")},
        "next_invoice_number": _next_invoice_number(conn, e, as_of),
        "files": {k: v["file"] for k, v in snaps.items()},
    }


# ---------------------------------------------------------------------------
# Run
# ---------------------------------------------------------------------------

def _post_to_target(conn, ctx, on: dt.date, label: str) -> Optional[Dict[str, Any]]:
    """Bring every account's ACE Books balance at `on` to Sage's General Ledger balance."""
    e = ctx.entity_id
    hist = books_ledger._hist_balances(conn, e, on)
    ace = books_ledger._ace_balances(conn, e, on)
    acc = books_ledger.accounts(conn, e)
    lines = []
    for code in sorted(set(hist) | set(ace)):
        diff = hist.get(code, ZERO) - ace.get(code, ZERO)
        if diff == 0:
            continue
        a = acc.get(code)
        if not a:
            raise FinError("RESOURCE_NOT_FOUND", f"Account {code} is in Sage's ledger but not in the chart of accounts")
        if a["status"] != "ACTIVE":
            ex(conn, "UPDATE fin_accounts SET status='ACTIVE' WHERE id=%s", (a["id"],))
        lines.append({"account_id": a["id"], "debit": diff if diff > 0 else ZERO, "credit": -diff if diff < 0 else ZERO,
                      "description": f"Sage {label}"})
    if not lines:
        return None
    j = posting.post_system(conn, ctx, event_type="SAGE_ROLLFORWARD", journal_date=on, lines=lines,
                            description=f"Sage 50 activity brought into ACE Books: {label}", source_type="MIGRATION",
                            source_id=f"ROLLFORWARD:{on}", source_ref="SAGE-ROLLFORWARD", journal_type="ADJUSTMENT",
                            idempotency_key=f"ROLLFORWARD:{e}:{on}")
    # Sage reconciled these bank movements already: they are the reconciliation baseline.
    for l in q(conn, """SELECT l.id, ba.id AS bank_id FROM fin_journal_lines l JOIN fin_bank_accounts ba ON ba.gl_account_id=l.account_id
                        WHERE l.journal_id=%s""", (j["id"],)):
        ex(conn, """INSERT INTO fin_cleared_lines (journal_line_id, bank_account_id, cleared_date, cleared_by)
                    VALUES (%s,%s,%s,%s) ON CONFLICT DO NOTHING""", (l["id"], l["bank_id"], on, ctx.actor_id))
    return {"journal": j["journal_number"], "date": str(on), "lines": len(lines), "total": str(j["total_debit"])}


def _ledger_date(conn, e: str, kind: str, code: str, doc: str) -> Optional[dt.date]:
    r = q1(conn, """SELECT txn_date FROM fin_sage_party_ledger WHERE legal_entity_id=%s AND party_kind=%s AND party_code=%s
                    AND trans_no=%s AND row_kind='TXN' ORDER BY txn_date LIMIT 1""", (e, kind, code, doc))
    return r["txn_date"] if r else None


def _replace_receivables(conn, ctx, rows: List[Dict[str, Any]], as_of: dt.date, load: str) -> Dict[str, Any]:
    e = ctx.entity_id
    # Old brought-forward items carry no journal; nothing else points at them unless used since.
    used = q1(conn, """SELECT COUNT(*) n FROM fin_sales_invoices i WHERE i.legal_entity_id=%s AND i.is_opening
                       AND (EXISTS (SELECT 1 FROM fin_ar_allocations a WHERE a.invoice_id=i.id)
                            OR EXISTS (SELECT 1 FROM fin_credit_notes n WHERE n.invoice_id=i.id))""", (e,))["n"]
    if used:
        raise FinError("INVALID_STATE_TRANSITION", f"{used} brought-forward invoices already have payments or credits applied in ACE Books")
    ex(conn, "DELETE FROM fin_credit_notes WHERE legal_entity_id=%s AND journal_id IS NULL AND amount_settled=0", (e,))
    ex(conn, "DELETE FROM fin_sales_invoices WHERE legal_entity_id=%s AND is_opening", (e,))
    sj_total = {r["reference"]: money(r["v"]) for r in q(conn, """
        SELECT reference, SUM(debit - credit) v FROM fin_sage_journal_lines WHERE legal_entity_id=%s AND kind='SJ'
        AND account_code=(SELECT a.code FROM fin_account_mappings m JOIN fin_accounts a ON a.id=m.account_id
                          WHERE m.legal_entity_id=%s AND m.mapping_key='AR_CONTROL') GROUP BY reference""", (e, e))}
    terms = {r["id"]: r["payment_terms_days"] for r in q(conn, "SELECT id, payment_terms_days FROM customers")}
    inv = cred = 0
    used_numbers: Dict[str, int] = {}
    for r in rows:
        cid = migration._party_customer(conn, r["party_code"], r["party_name"])
        amt = money(r["amount"])
        doc = r["document"]
        date = _ledger_date(conn, e, "CUSTOMER", r["party_code"], doc)
        if not date:
            s = q1(conn, "SELECT MIN(invoice_date) d FROM fin_sage_sales_lines WHERE legal_entity_id=%s AND invoice_number=%s", (e, doc))
            date = s["d"] if s and s["d"] else migration._bucket_date(as_of, r.get("age_bucket"))
        date = min(date, as_of)
        if amt > 0:
            number = doc if doc not in used_numbers else f"{doc}/{r['party_code']}"[:60]
            used_numbers[doc] = 1
            orig = sj_total.get(doc)
            ex(conn, """INSERT INTO fin_sales_invoices (legal_entity_id, invoice_number, customer_id, invoice_date, due_date, terms_days,
                        subtotal, total, original_total, status, source_type, source_id, is_opening, created_by, posted_at)
                        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,'POSTED','OPENING',%s,TRUE,%s,now())""",
               (e, number, cid, date, date + dt.timedelta(days=int(terms.get(cid) or 30)), int(terms.get(cid) or 30),
                amt, amt, orig if orig and orig >= amt else None, f"{load}:{cid}:{doc}", ctx.actor_id))
            inv += 1
        elif amt < 0:
            what = "Payment received, not yet applied to an invoice" if not re.search(r"\d{4,}", doc) or doc.isupper() and " " not in doc and not doc.isdigit() and "INV" not in doc else f"Credit {doc}"
            number = doc if not q1(conn, "SELECT 1 FROM fin_credit_notes WHERE legal_entity_id=%s AND credit_note_number=%s", (e, doc)) \
                else f"{doc}/{r['party_code']}"[:60]
            if q1(conn, "SELECT 1 FROM fin_credit_notes WHERE legal_entity_id=%s AND credit_note_number=%s", (e, number)):
                number = f"{doc}/{r['party_code']}/{cred}"[:60]
            ex(conn, """INSERT INTO fin_credit_notes (legal_entity_id, credit_note_number, customer_id, note_date, reason, total,
                        sage_invoice_number, created_by) VALUES (%s,%s,%s,%s,%s,%s,%s,%s)""",
               (e, number, cid, date, f"{what} (Sage {doc})", -amt, doc, ctx.actor_id))
            cred += 1
    sage_history.resolve(conn, e)
    return {"open_invoices": inv, "open_credits": cred}


def _replace_payables(conn, ctx, rows: List[Dict[str, Any]], as_of: dt.date) -> Dict[str, Any]:
    e = ctx.entity_id
    used = q1(conn, """SELECT COUNT(*) n FROM fin_supplier_bills b WHERE b.legal_entity_id=%s AND b.is_opening
                       AND (EXISTS (SELECT 1 FROM fin_ap_allocations a WHERE a.bill_id=b.id)
                            OR EXISTS (SELECT 1 FROM fin_debit_notes d WHERE d.bill_id=b.id))""", (e,))["n"]
    if used:
        raise FinError("INVALID_STATE_TRANSITION", f"{used} brought-forward supplier bills already have payments applied in ACE Books")
    ex(conn, "UPDATE replenishment_requests SET bill_id=NULL WHERE bill_id IN (SELECT id FROM fin_supplier_bills WHERE legal_entity_id=%s AND is_opening)", (e,))
    ex(conn, "DELETE FROM fin_debit_notes WHERE legal_entity_id=%s AND journal_id IS NULL AND amount_settled=0", (e,))
    ex(conn, "DELETE FROM fin_supplier_bills WHERE legal_entity_id=%s AND is_opening", (e,))
    bills = debits = 0
    for r in rows:
        sid = migration._party_supplier(conn, r["party_code"], r["party_name"])
        amt = money(r["amount"])
        doc = r["document"]
        date = _ledger_date(conn, e, "VENDOR", r["party_code"], doc) or migration._bucket_date(as_of, r.get("age_bucket"))
        date = min(date, as_of)
        terms = q1(conn, "SELECT payment_terms FROM suppliers WHERE id=%s", (sid,))
        days = int(re.search(r"\d+", (terms or {}).get("payment_terms") or "30").group()) if re.search(r"\d+", (terms or {}).get("payment_terms") or "") else 30
        if amt > 0:
            number = doc if not q1(conn, "SELECT 1 FROM fin_supplier_bills WHERE legal_entity_id=%s AND bill_number=%s", (e, doc)) \
                else f"{doc}/{r['party_code']}"[:60]
            ex(conn, """INSERT INTO fin_supplier_bills (legal_entity_id, bill_number, supplier_id, supplier_invoice_number, bill_date,
                        due_date, subtotal, total, is_opening, created_by) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,TRUE,%s)""",
               (e, number, sid, doc, date, date + dt.timedelta(days=days), amt, amt, ctx.actor_id))
            bills += 1
        elif amt < 0:
            ex(conn, """INSERT INTO fin_debit_notes (legal_entity_id, debit_note_number, supplier_id, note_date, reason, total,
                        sage_bill_number, created_by) VALUES (%s,%s,%s,%s,%s,%s,%s,%s)""",
               (e, f"{doc}/{r['party_code']}/{debits}"[:60], sid, date, f"Supplier balance in our favour (Sage {doc})", -amt, doc,
                ctx.actor_id))
            debits += 1
    return {"open_bills": bills, "open_debits": debits}


def _replace_stock(conn, ctx, rows: List[Dict[str, Any]], as_of: dt.date,
                   negative: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
    e = ctx.entity_id
    out = removed = 0
    for l in q(conn, """SELECT sku, batch_id, SUM(qty_remaining) q FROM fin_cost_layers WHERE legal_entity_id=%s AND qty_remaining > 0
                        GROUP BY sku, batch_id""", (e,)):
        inventory.issue(conn, ctx, sku=l["sku"], quantity=l["q"], txn_type="ADJUSTMENT", txn_date=as_of,
                        batch_id=str(l["batch_id"]) if l["batch_id"] else None, source_type="MIGRATION",
                        source_id=f"ROLLFORWARD:{as_of}", reference="SAGE-VALUATION",
                        reason=f"Replaced by Sage's stock valuation at {as_of:%d %b %Y}", mirror=False)
        removed += 1
    skipped = []
    # Corrections the finance team made in Data exceptions (a missing receipt, a lot mix-up, a
    # count) are added to Sage's figures, so a new export does not undo them.
    from src.fin import data_exceptions
    overlays = data_exceptions.stock_overlays(conn, e)
    merged: Dict[str, Dict[str, Any]] = {}
    for r in list(rows) + list(negative or []):
        sku = r.get("sku") or r.get("row")
        if not sku or r.get("quantity") is None:
            continue
        m = merged.setdefault(sku, {"sku": sku, "quantity": ZERO, "value": ZERO})
        m["quantity"] += Decimal(str(r["quantity"]))
        m["value"] += Decimal(str(r["value"]))
    for sku, o in overlays.items():
        m = merged.setdefault(sku, {"sku": sku, "quantity": ZERO, "value": ZERO})
        m["quantity"] += o["quantity"]
        m["value"] += o["value"]
    rows = [m for m in merged.values() if m["quantity"] > 0 and m["value"] >= 0]
    for r in rows:
        p = q1(conn, "SELECT sku, lot_expiry FROM fin_products WHERE legal_entity_id=%s AND sku=%s", (e, r["sku"]))
        if not p:
            skipped.append(r["sku"])
            continue
        lot = sage_history.lot_label(r["sku"])
        bid = inventory.ensure_batch(conn, e, r["sku"], lot, expiry_date=p["lot_expiry"])
        ex(conn, "UPDATE fin_batches SET lot_code=COALESCE(lot_code, %s), expiry_date=COALESCE(expiry_date, %s) WHERE id=%s",
           (lot, p["lot_expiry"], bid))
        unit = Decimal(str(r["value"])) / Decimal(str(r["quantity"]))
        inventory.receive(conn, ctx, sku=r["sku"], quantity=r["quantity"], unit_cost=unit, txn_type="OPENING_BALANCE",
                          txn_date=as_of, batch_id=bid, source_type="MIGRATION", source_id=f"ROLLFORWARD:{as_of}",
                          reference="SAGE-VALUATION", reason=f"Stock at {as_of:%d %b %Y} from Sage's inventory valuation",
                          mirror=False, total_cost=money(r["value"]))
        out += 1
    return {"layers_replaced": removed, "items_loaded": out, "skipped_unknown_items": skipped}


def run(conn, ctx, as_of: dt.date, folder: str, *, void_test_invoices: bool = False,
        void_reason: Optional[str] = None) -> Dict[str, Any]:
    ctx.require("migration.load")
    e = ctx.entity_id
    p = plan(conn, ctx, as_of, folder)
    old_h = p["previous_hand_over"]
    docs = p["documents_inside_sage_period"]
    if docs:
        non_invoice = [d for d in docs if d["kind"] != "invoice"]
        if non_invoice or not void_test_invoices:
            raise FinError("INVALID_STATE_TRANSITION",
                           "ACE Books has its own documents inside the Sage period; void them first (or pass void_test_invoices)",
                           {"documents": docs})
        for d in docs:
            sales.void_invoice(conn, ctx, d["id"], void_reason or "Test invoice inside the Sage period (before ACE Books took over)",
                               on=d["date"])
    journals = []
    for d in p["journals"]:
        dd = dt.date.fromisoformat(d) if isinstance(d, str) else d
        label = (f"changes to periods up to {dd:%d %b %Y} after the first export" if dd == old_h else f"{dd:%B %Y}")
        r = _post_to_target(conn, ctx, dd, label)
        if r:
            journals.append(r)
    # Every account now equals Sage's General Ledger at the hand-over date.
    hist = books_ledger._hist_balances(conn, e, as_of)
    ace = books_ledger._ace_balances(conn, e, as_of)
    off = {c: str(hist.get(c, ZERO) - ace.get(c, ZERO)) for c in set(hist) | set(ace) if hist.get(c, ZERO) != ace.get(c, ZERO)}
    if off:
        raise FinError("RECONCILIATION_FAILED", "ACE Books does not equal Sage after the roll-forward", {"accounts": off})
    snaps = _snapshots(folder)
    load = str(q1(conn, "SELECT gen_random_uuid() id")["id"])
    ar = _replace_receivables(conn, ctx, snaps["OPEN_AR"]["parsed"]["rows"], as_of, load)
    ap = _replace_payables(conn, ctx, snaps["OPEN_AP"]["parsed"]["rows"], as_of)
    stock = _replace_stock(conn, ctx, snaps["INVENTORY"]["parsed"]["rows"], as_of, snaps["INVENTORY"]["parsed"]["issues"])
    nxt = p["next_invoice_number"]
    if nxt:
        ex(conn, """INSERT INTO fin_number_sequences (legal_entity_id, doc_type, prefix, next_value, pad)
                    VALUES (%s,'SALES_INVOICE','',%s,0)
                    ON CONFLICT (legal_entity_id, doc_type) DO UPDATE SET prefix='', next_value=EXCLUDED.next_value, pad=0""", (e, nxt))
    ex(conn, "UPDATE fin_settings SET history_until=%s, cutover_date=%s, updated_by=%s, updated_at=now() WHERE legal_entity_id=%s",
       (as_of, as_of + ONE, ctx.actor_id, e))
    result = {"as_of": str(as_of), "journals": journals, "receivables": ar, "payables": ap, "stock": stock,
              "next_invoice_number": nxt, "voided": [d["number"] for d in docs] if docs else [],
              "trial_balance_vs_general_ledger": p["trial_balance_vs_general_ledger"],
              "receivables_check": p["receivables"], "payables_check": p["payables"], "stock_check": p["stock"]}
    audit.record(conn, ctx, "SAGE_ROLLFORWARD", "migration", e, ref=f"Sage -> ACE Books at {as_of}", metadata=result)
    # What the export leaves unexplained goes to Data exceptions, with its lineage.
    from src.fin import data_exceptions
    data_exceptions.save_snapshots(conn, ctx, snaps, as_of)
    result["data_exceptions"] = data_exceptions.refresh(conn, ctx)
    return result
