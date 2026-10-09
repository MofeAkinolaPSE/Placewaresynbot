"""Sage 50 full history: load the client's Sage reports line for line (display + lineage only).

Sage was the record until ``fin_settings.history_until``; this module brings in everything it
holds so ACE Books reports can go back as far as Sage does, in Sage's own layouts:

    General Ledger          -> fin_sage_gl_lines + fin_sage_gl_balances (Beginning Balance per
                               account per month, the "Current Period Change" totals)
    Customer / Vendor Ledgers -> fin_sage_party_ledger
    Sales, Cash Receipts, Cash Disbursements, Purchase, COGS, General journals
                            -> fin_sage_journal_lines (the journal exactly as exported)
                               (+ the sales / purchase line history the lineage sheets use)
    Item Costing            -> fin_sage_item_costing
    Item Master List        -> fin_products (new lots, GL accounts, prices) + lot expiry
    Customer List / Vendor Master File -> customers / suppliers (adds new ones, fills blanks)

Every file is recognised from its header row, so a folder of exports can be loaded as is
(``ingest_folder``). Loading a file replaces that kind's rows inside the file's own date range:
an export that overlaps an earlier one (June in both, say) never duplicates anything.
Nothing here posts to the ledger.
"""
from __future__ import annotations

import datetime as dt
import io
import os
import re
from decimal import Decimal
from typing import Any, Callable, Dict, List, Optional, Tuple

from psycopg2.extras import execute_values

from src.fin import audit, sage_history
from src.fin.db import ZERO, ex, jsonb, money, q, q1, qty
from src.fin.errors import invalid

# ---------------------------------------------------------------------------
# Reading
# ---------------------------------------------------------------------------


def read_rows(path_or_name: str, raw: Optional[bytes] = None) -> List[Tuple[Any, ...]]:
    import openpyxl
    src = io.BytesIO(raw) if raw is not None else path_or_name
    if str(path_or_name).lower().endswith(".csv"):
        import csv
        text = (raw or open(path_or_name, "rb").read()).decode("utf-8-sig", errors="replace")
        return [tuple(r) for r in csv.reader(io.StringIO(text))]
    wb = openpyxl.load_workbook(src, read_only=True, data_only=True)
    try:
        return [tuple(r) for r in wb.worksheets[0].iter_rows(values_only=True)]
    finally:
        wb.close()


def _s(v: Any) -> str:
    return "" if v is None else str(v).strip()


def _n(v: Any) -> str:
    return re.sub(r"\s+", " ", _s(v)).lower()


def _dec(v: Any) -> Decimal:
    if v in (None, ""):
        return ZERO
    try:
        return money(str(v).replace(",", ""))
    except Exception:
        return ZERO


def _date(v: Any) -> Optional[dt.date]:
    if isinstance(v, dt.datetime):
        return v.date()
    if isinstance(v, dt.date):
        return v
    s = _s(v)
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%m/%d/%y", "%d/%m/%Y"):
        try:
            return dt.datetime.strptime(s[:10], fmt).date()
        except ValueError:
            continue
    return None


# Each Sage report is recognised by the columns of its header row.
SIGNATURES: List[Tuple[str, Tuple[str, ...], Tuple[str, ...]]] = [
    # kind, required header words, words that must NOT be present
    ("GENERAL_LEDGER", ("account id", "date", "reference", "jrnl", "trans description", "balance"), ()),
    ("CUSTOMER_LEDGER", ("customer id", "date", "trans no", "type", "balance"), ()),
    ("VENDOR_LEDGER", ("vendor id", "date", "trans no", "type", "balance"), ()),
    ("TRIAL_BALANCE", ("account id", "account description", "debit amt", "credit amt"), ("date",)),
    ("PURCHASE_JOURNAL", ("date", "account id", "account description", "invoice/cm #", "line description"), ()),
    ("SALES_JOURNAL", ("date", "account id", "invoice/cm #", "line description"), ("account description",)),
    ("CASH_RECEIPTS_JOURNAL", ("date", "account id", "transaction ref", "line description"), ()),
    ("CASH_DISBURSEMENTS_JOURNAL", ("date", "check #", "account id", "line description"), ()),
    ("COGS_JOURNAL", ("date", "gl acct id", "reference", "qty"), ()),
    ("GENERAL_JOURNAL", ("date", "account id", "reference", "trans description"), ("jrnl", "balance")),
    ("OPEN_AR", ("customer id", "invoice/cm #", "amount due"), ()),
    ("OPEN_AP", ("vendor id", "invoice/cm #", "amount due"), ()),
    ("INVENTORY", ("item id", "qty on hand", "item value"), ()),
    ("ITEM_COSTING", ("item id", "qty received", "cost of sales"), ()),
    ("ITEM_MASTER", ("item id", "item description", "item class", "sales acct"), ()),
    ("CUSTOMER_LIST", ("customer id", "customer", "telephone 1"), ("invoice/cm #", "date", "amount due")),
    ("VENDOR_LIST", ("vendor id", "vendor", "address line 1"), ("date",)),
]


def detect(rows: List[Tuple[Any, ...]]) -> Tuple[Optional[str], int, Dict[str, int]]:
    for i, r in enumerate(rows[:12]):
        names = [_n(c) for c in r]
        joined = "|".join(names)
        if not any(names):
            continue
        for kind, must, never in SIGNATURES:
            if all(any(m == n or n.startswith(m) for n in names) for m in must) and not any(nv in joined for nv in never):
                return kind, i, {n: j for j, n in enumerate(names) if n}
    return None, -1, {}


def _col(idx: Dict[str, int], *names: str) -> Optional[int]:
    for n in names:
        if n in idx:
            return idx[n]
    for n in names:
        for k, j in idx.items():
            if k.startswith(n):
                return j
    return None


def _get(r: Tuple[Any, ...], j: Optional[int]) -> Any:
    return r[j] if j is not None and j < len(r) else None


def _register(conn, ctx, kind: str, file_name: str, f: Optional[dt.date], t: Optional[dt.date], n: int,
              summary: Dict[str, Any]) -> str:
    row = q1(conn, """INSERT INTO fin_sage_loads (legal_entity_id, kind, file_name, date_from, date_to, row_count, summary, loaded_by)
                      VALUES (%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id""",
             (ctx.entity_id, kind, file_name, f, t, n, jsonb(summary), ctx.actor_id))
    return str(row["id"])


def _finish(conn, ctx, load_id: str, kind: str, file_name: str, summary: Dict[str, Any]) -> Dict[str, Any]:
    ex(conn, "UPDATE fin_sage_loads SET summary=%s WHERE id=%s", (jsonb(summary), load_id))
    audit.record(conn, ctx, "SAGE_HISTORY_LOADED", "sage_load", load_id, ref=f"{kind} {file_name}", metadata=summary)
    return {"kind": kind, "file": file_name, "load_id": load_id, **summary}


# ---------------------------------------------------------------------------
# General Ledger
# ---------------------------------------------------------------------------

def load_general_ledger(conn, ctx, rows, h: int, idx: Dict[str, int], file_name: str) -> Dict[str, Any]:
    """Sage 'General Ledger' (detail): per account, per month a Beginning Balance row, the
    transactions, a 'Current Period Change' row; an 'Ending Balance' row closes each account."""
    c_acct, c_date, c_ref = _col(idx, "account id"), _col(idx, "date"), _col(idx, "reference")
    c_j, c_desc = _col(idx, "jrnl"), _col(idx, "trans description")
    c_dr, c_cr, c_bal = _col(idx, "debit amt", "debit"), _col(idx, "credit amt", "credit"), _col(idx, "balance")
    lines: List[tuple] = []
    anchors: Dict[Tuple[str, dt.date], List[Any]] = {}
    endings: Dict[str, Decimal] = {}
    acct, period = None, None
    seq = 0
    for r in rows[h + 1:]:
        seq += 1
        code = _s(_get(r, c_acct))
        desc = _s(_get(r, c_desc))
        d = _date(_get(r, c_date))
        if code:
            acct = code
        if not acct:
            continue
        low = desc.lower()
        if low == "beginning balance" and d:
            period = d.replace(day=1)
            anchors[(acct, period)] = [_dec(_get(r, c_bal)), None, None]
            continue
        if low == "current period change":
            if (acct, period) in anchors:
                anchors[(acct, period)][1] = _dec(_get(r, c_dr))
                anchors[(acct, period)][2] = _dec(_get(r, c_cr))
            continue
        if low == "ending balance":
            endings[acct] = _dec(_get(r, c_bal))
            continue
        if not d:
            continue
        dr, cr = _dec(_get(r, c_dr)), _dec(_get(r, c_cr))
        if dr == 0 and cr == 0 and not desc:
            continue
        lines.append((acct, d, _s(_get(r, c_ref)) or None, _s(_get(r, c_j)) or None, desc or None, dr, cr, seq))
    if not anchors:
        raise invalid(f"{file_name}: no 'Beginning Balance' rows - export the General Ledger in detail with beginning balances")
    f = min(p for _, p in anchors)
    last_period = max(p for _, p in anchors)
    t = max([l[1] for l in lines] + [(last_period.replace(day=28) + dt.timedelta(days=4)).replace(day=1) - dt.timedelta(days=1)])
    load_id = _register(conn, ctx, "GENERAL_LEDGER", file_name, f, t, len(lines), {})
    # corrections posted from Data exceptions (jrnl 'ADJ', no load) are ours, not the file's: keep them
    ex(conn, """DELETE FROM fin_sage_gl_lines WHERE legal_entity_id=%s AND txn_date BETWEEN %s AND %s
                AND NOT (jrnl='ADJ' AND load_id IS NULL)""", (ctx.entity_id, f, t))
    ex(conn, "DELETE FROM fin_sage_gl_balances WHERE legal_entity_id=%s AND period_start BETWEEN %s AND %s", (ctx.entity_id, f, t))
    with conn.cursor() as cur:
        execute_values(cur, """INSERT INTO fin_sage_gl_lines (legal_entity_id, load_id, account_code, txn_date, reference, jrnl,
                               description, debit, credit, seq) VALUES %s""",
                       [(ctx.entity_id, load_id) + l for l in lines], page_size=5000)
        execute_values(cur, """INSERT INTO fin_sage_gl_balances (legal_entity_id, account_code, period_start, beginning_balance,
                               period_debit, period_credit, load_id) VALUES %s""",
                       [(ctx.entity_id, a, p, v[0], v[1], v[2], load_id) for (a, p), v in anchors.items()], page_size=5000)
    # Sage's own check: beginning balance + every line = the report's ending balance.
    mismatched = []
    for a, end in endings.items():
        b = q1(conn, """SELECT beginning_balance, period_start FROM fin_sage_gl_balances WHERE legal_entity_id=%s AND account_code=%s
                        AND period_start=%s""", (ctx.entity_id, a, last_period))
        if not b:
            continue
        m = q1(conn, """SELECT COALESCE(SUM(debit-credit),0) v FROM fin_sage_gl_lines WHERE legal_entity_id=%s AND account_code=%s
                        AND txn_date >= %s""", (ctx.entity_id, a, last_period))["v"]
        if money(b["beginning_balance"]) + money(m) != end:
            mismatched.append({"account": a, "computed": str(money(b["beginning_balance"]) + money(m)), "sage": str(end)})
    summary = {"lines": len(lines), "accounts": len({a for a, _ in anchors}), "months": len({p for _, p in anchors}),
               "from": str(f), "to": str(t), "ending_balance_mismatches": mismatched[:20]}
    return _finish(conn, ctx, load_id, "GENERAL_LEDGER", file_name, summary)


# ---------------------------------------------------------------------------
# Customer / vendor ledgers
# ---------------------------------------------------------------------------

def _party_maps(conn) -> Tuple[Dict[str, int], Dict[str, str]]:
    cust: Dict[str, int] = {}
    for r in q(conn, "SELECT id, name, customer_code FROM customers ORDER BY id"):
        for k in (r["customer_code"], r["name"]):
            if k:
                cust.setdefault(_n(k), r["id"])
    supp: Dict[str, str] = {}
    for r in q(conn, "SELECT id, name, external_vendor_id FROM suppliers ORDER BY created_at"):
        for k in (r["external_vendor_id"], r["name"]):
            if k:
                supp.setdefault(_n(k), str(r["id"]))
    return cust, supp


def load_party_ledger(conn, ctx, rows, h: int, idx: Dict[str, int], file_name: str, kind: str) -> Dict[str, Any]:
    vendor = kind == "VENDOR_LEDGER"
    c_id = _col(idx, "vendor id" if vendor else "customer id")
    c_name = _col(idx, "vendor" if vendor else "customer")
    c_date, c_no, c_type = _col(idx, "date"), _col(idx, "trans no"), _col(idx, "type")
    c_paid = _col(idx, "paid") if vendor else None
    c_dr, c_cr, c_bal = _col(idx, "debit amt", "debit"), _col(idx, "credit amt", "credit"), _col(idx, "balance")
    cust, supp = _party_maps(conn)
    out = []
    seq = 0
    for r in rows[h + 1:]:
        seq += 1
        code = _s(_get(r, c_id))
        d = _date(_get(r, c_date))
        if not code or not d or code.lower() == "report total":
            continue
        no = _s(_get(r, c_no))
        name = _s(_get(r, c_name))
        balfwd = no.lower() == "balance fwd"
        cid = None if vendor else (cust.get(_n(code)) or cust.get(_n(name)))
        sid = (supp.get(_n(code)) or supp.get(_n(name))) if vendor else None
        out.append((code, name or None, cid, sid, d, None if balfwd else (no or None), _s(_get(r, c_type)) or None,
                    _s(_get(r, c_paid)) or None if c_paid is not None else None,
                    _dec(_get(r, c_dr)), _dec(_get(r, c_cr)),
                    _dec(_get(r, c_bal)) if _get(r, c_bal) not in (None, "") else None, "BALFWD" if balfwd else "TXN", seq))
    if not out:
        raise invalid(f"{file_name}: no dated ledger rows found")
    f, t = min(o[4] for o in out), max(o[4] for o in out)
    pk = "VENDOR" if vendor else "CUSTOMER"
    load_id = _register(conn, ctx, kind, file_name, f, t, len(out), {})
    ex(conn, "DELETE FROM fin_sage_party_ledger WHERE legal_entity_id=%s AND party_kind=%s AND txn_date BETWEEN %s AND %s",
       (ctx.entity_id, pk, f, t))
    with conn.cursor() as cur:
        execute_values(cur, """INSERT INTO fin_sage_party_ledger (legal_entity_id, load_id, party_kind, party_code, party_name,
                               customer_id, supplier_id, txn_date, trans_no, jrnl, paid, debit, credit, balance, row_kind, seq)
                               VALUES %s""", [(ctx.entity_id, load_id, pk) + o for o in out], page_size=5000)
    matched = sum(1 for o in out if (o[3] if vendor else o[2]))
    summary = {"rows": len(out), "parties": len({o[0] for o in out}), "matched_to_ace": matched, "from": str(f), "to": str(t)}
    return _finish(conn, ctx, load_id, kind, file_name, summary)


# ---------------------------------------------------------------------------
# Journals (as exported)
# ---------------------------------------------------------------------------

JOURNAL_KIND = {"SALES_JOURNAL": "SJ", "CASH_RECEIPTS_JOURNAL": "CRJ", "CASH_DISBURSEMENTS_JOURNAL": "CDJ",
                "PURCHASE_JOURNAL": "PJ", "COGS_JOURNAL": "COGS", "GENERAL_JOURNAL": "GENJ"}


def load_journal(conn, ctx, rows, h: int, idx: Dict[str, int], file_name: str, kind: str) -> Dict[str, Any]:
    jk = JOURNAL_KIND[kind]
    c = {"date": _col(idx, "date"), "account": _col(idx, "account id", "gl acct id"),
         "acct_desc": _col(idx, "account description"),
         "ref": _col(idx, "invoice/cm #", "transaction ref", "check #", "reference"),
         "desc": _col(idx, "line description", "trans description"), "qty": _col(idx, "qty"), "um": _col(idx, "u/m id"),
         "debit": _col(idx, "debit amnt", "debit amount", "debit amt", "debit"),
         "credit": _col(idx, "credit amnt", "credit amount", "credit amt", "credit")}
    out = []
    seq = 0
    for r in rows[h + 1:]:
        seq += 1
        d = _date(_get(r, c["date"]))
        if not d:
            continue
        dr, cr = _dec(_get(r, c["debit"])), _dec(_get(r, c["credit"]))
        acct = _s(_get(r, c["account"]))
        if not acct and dr == 0 and cr == 0:
            continue
        q_ = _get(r, c["qty"])
        out.append((jk, d, acct or None, _s(_get(r, c["acct_desc"])) or None, _s(_get(r, c["ref"])) or None,
                    _s(_get(r, c["desc"])) or None, qty(q_) if q_ not in (None, "") else None, _s(_get(r, c["um"])) or None,
                    dr, cr, seq))
    if not out:
        raise invalid(f"{file_name}: no dated journal lines found")
    f, t = min(o[1] for o in out), max(o[1] for o in out)
    load_id = _register(conn, ctx, kind, file_name, f, t, len(out), {})
    ex(conn, "DELETE FROM fin_sage_journal_lines WHERE legal_entity_id=%s AND kind=%s AND txn_date BETWEEN %s AND %s",
       (ctx.entity_id, jk, f, t))
    with conn.cursor() as cur:
        execute_values(cur, """INSERT INTO fin_sage_journal_lines (legal_entity_id, load_id, kind, txn_date, account_code,
                               account_description, reference, description, qty, um, debit, credit, seq) VALUES %s""",
                       [(ctx.entity_id, load_id) + o for o in out], page_size=5000)
    summary: Dict[str, Any] = {"lines": len(out), "from": str(f), "to": str(t),
                               "debits": str(sum((o[8] for o in out), ZERO)), "credits": str(sum((o[9] for o in out), ZERO))}
    # The sales / purchase line history behind invoices and bills (what was sold, to whom, qty, cost).
    from src.fin import migration
    hist = {"SALES_JOURNAL": ("SALES_JOURNAL", sage_history.load_sales_journal),
            "COGS_JOURNAL": ("COGS_JOURNAL", sage_history.load_cogs_journal),
            "PURCHASE_JOURNAL": ("PURCHASE_JOURNAL", sage_history.load_purchase_journal)}.get(kind)
    if hist:
        parsed = sage_history.PARSERS[hist[0]]([list(r) for r in rows], migration._header_index, migration._col)
        res = hist[1](conn, ctx, {"id": load_id, "rows": parsed["rows"]})
        summary["line_history"] = {k: v for k, v in res.items() if k != "history"}
    return _finish(conn, ctx, load_id, kind, file_name, summary)


def load_item_costing(conn, ctx, rows, h, idx, file_name) -> Dict[str, Any]:
    from src.fin import migration
    parsed = sage_history.parse_item_costing([list(r) for r in rows], migration._header_index, migration._col)
    f, t = parsed["summary"]["from"], parsed["summary"]["to"]
    load_id = _register(conn, ctx, "ITEM_COSTING", file_name, f, t, len(parsed["rows"]), {})
    res = sage_history.load_item_costing(conn, ctx, {"id": load_id, "rows": parsed["rows"]})
    return _finish(conn, ctx, load_id, "ITEM_COSTING", file_name, {k: v for k, v in res.items() if k != "history"})


# ---------------------------------------------------------------------------
# Masters: items, customers, vendors
# ---------------------------------------------------------------------------

_EXP = re.compile(r"(\d{1,2})\s*/+\s*(\d{2,4})")


def expiry_from_text(v: Any) -> Optional[dt.date]:
    """Sage item 'Item Type' holds the lot's expiry as typed: '12/25,', '07//23', '11/  22', '04/24...'."""
    m = _EXP.search(_s(v))
    if not m:
        return None
    mo, yr = int(m.group(1)), int(m.group(2))
    if not 1 <= mo <= 12:
        return None
    yr = yr + 2000 if yr < 100 else yr
    if not 2000 <= yr <= 2100:
        return None
    nxt = dt.date(yr + (mo == 12), mo % 12 + 1, 1)
    return nxt - dt.timedelta(days=1)


def load_item_master(conn, ctx, rows, h, idx, file_name) -> Dict[str, Any]:
    c = {k: _col(idx, *v) for k, v in {"sku": ("item id",), "name": ("item description",), "sales_desc": ("description for sales",),
                                         "cls": ("item class",), "itype": ("item type",), "cost": ("cost method",),
                                         "um": ("stocking u/m",), "sales": ("sales acct",), "inv": ("inv acct",),
                                         "cos": ("cos acct",), "price": ("price level 1",), "min": ("min stock",),
                                         "vendor": ("preferred vendor id",)}.items()}
    codes = {a["code"]: str(a["id"]) for a in q(conn, "SELECT id, code FROM fin_accounts WHERE legal_entity_id=%s", (ctx.entity_id,))}
    load_id = _register(conn, ctx, "ITEM_MASTER", file_name, None, None, 0, {})
    created = updated = expiries = 0
    for r in rows[h + 1:]:
        sku = _s(_get(r, c["sku"]))
        if not sku:
            continue
        cls = _s(_get(r, c["cls"]))
        ptype = "SERVICE" if cls.lower() in ("service", "non-stock item", "description only", "labor", "charge") else "INVENTORY"
        name = _s(_get(r, c["name"])) or sku
        price = _dec(_get(r, c["price"])) or None
        accs = [codes.get(_s(_get(r, c[k]))) for k in ("sales", "inv", "cos")]
        existing = q1(conn, "SELECT id FROM fin_products WHERE legal_entity_id=%s AND sku=%s", (ctx.entity_id, sku))
        if existing:
            ex(conn, """UPDATE fin_products SET name=%s, revenue_account_id=COALESCE(%s, revenue_account_id),
                        inventory_account_id=COALESCE(%s, inventory_account_id), cogs_account_id=COALESCE(%s, cogs_account_id),
                        standard_price=COALESCE(%s, standard_price), uom=COALESCE(NULLIF(%s,''), uom), legacy_class=%s
                        WHERE id=%s""", (name, accs[0], accs[1], accs[2], price, _s(_get(r, c["um"])), cls, existing["id"]))
            updated += 1
        else:
            ex(conn, """INSERT INTO fin_products (legal_entity_id, sku, name, revenue_account_id, inventory_account_id,
                        cogs_account_id, standard_price, status, uom, product_type, legacy_class)
                        VALUES (%s,%s,%s,%s,%s,%s,%s,'ACTIVE',%s,%s,%s)""",
               (ctx.entity_id, sku, name, accs[0], accs[1], accs[2], price, _s(_get(r, c["um"])) or "Each", ptype, cls))
            created += 1
        exp = expiry_from_text(_get(r, c["itype"]))
        ex(conn, "UPDATE fin_products SET lot_expiry=%s, sales_description=NULLIF(%s,'') WHERE legal_entity_id=%s AND sku=%s",
           (exp, _s(_get(r, c["sales_desc"])), ctx.entity_id, sku))
        if exp:
            expiries += 1
            # the lot's own batch gets the expiry if it has none yet
            ex(conn, """UPDATE fin_batches SET expiry_date=%s WHERE legal_entity_id=%s AND sku=%s AND expiry_date IS NULL""",
               (exp, ctx.entity_id, sku))
    summary = {"created": created, "updated": updated, "with_expiry": expiries}
    return _finish(conn, ctx, load_id, "ITEM_MASTER", file_name, summary)


def load_customer_list(conn, ctx, rows, h, idx, file_name) -> Dict[str, Any]:
    c_id, c_name = _col(idx, "customer id"), _col(idx, "customer")
    c_contact, c_phone = _col(idx, "bill to contact"), _col(idx, "telephone 1")
    load_id = _register(conn, ctx, "CUSTOMER_LIST", file_name, None, None, 0, {})
    created = 0
    for r in rows[h + 1:]:
        code = _s(_get(r, c_id))
        if not code or code in ("-",):
            continue
        name = _s(_get(r, c_name)) or code
        if q1(conn, "SELECT 1 FROM customers WHERE customer_code=%s", (code,)):
            ex(conn, """UPDATE customers SET contact_details = COALESCE(contact_details,'{}'::jsonb)
                        || jsonb_strip_nulls(jsonb_build_object('contact', NULLIF(%s,''), 'phone', NULLIF(%s,'')))
                        WHERE customer_code=%s AND (contact_details->>'phone' IS NULL OR contact_details->>'contact' IS NULL)""",
               (_s(_get(r, c_contact)), _s(_get(r, c_phone)), code))
            continue
        ex(conn, """INSERT INTO customers (name, customer_code, contact_details, metadata) VALUES (%s,%s,%s,%s)""",
           (name, code, jsonb({k: v for k, v in (("contact", _s(_get(r, c_contact))), ("phone", _s(_get(r, c_phone)))) if v}),
            jsonb({"source": "sage_customer_list"})))
        created += 1
    return _finish(conn, ctx, load_id, "CUSTOMER_LIST", file_name, {"created": created})


def load_vendor_list(conn, ctx, rows, h, idx, file_name) -> Dict[str, Any]:
    c = {k: _col(idx, *v) for k, v in {"id": ("vendor id",), "name": ("vendor",), "a1": ("address line 1",), "a2": ("address line 2",),
                                         "city": ("city st zip",), "contact": ("contact",), "phone": ("telephone 1",),
                                         "tax": ("tax id no",), "terms": ("terms",)}.items()}
    load_id = _register(conn, ctx, "VENDOR_LIST", file_name, None, None, 0, {})
    created = 0
    for r in rows[h + 1:]:
        code = _s(_get(r, c["id"]))
        if not code:
            continue
        addr = ", ".join(x for x in (_s(_get(r, c["a1"])), _s(_get(r, c["a2"])), _s(_get(r, c["city"]))) if x) or None
        if q1(conn, "SELECT 1 FROM suppliers WHERE external_vendor_id=%s", (code,)):
            ex(conn, """UPDATE suppliers SET address=COALESCE(address,%s), contact_name=COALESCE(contact_name,NULLIF(%s,'')),
                        phone=COALESCE(phone,NULLIF(%s,'')), tax_id=COALESCE(tax_id,NULLIF(%s,'')),
                        payment_terms=COALESCE(payment_terms,NULLIF(%s,'')) WHERE external_vendor_id=%s""",
               (addr, _s(_get(r, c["contact"])), _s(_get(r, c["phone"])), _s(_get(r, c["tax"])), _s(_get(r, c["terms"])), code))
            continue
        ex(conn, """INSERT INTO suppliers (name, external_vendor_id, address, contact_name, phone, tax_id, payment_terms, status)
                    VALUES (%s,%s,%s,NULLIF(%s,''),NULLIF(%s,''),NULLIF(%s,''),NULLIF(%s,''),'active')""",
           (_s(_get(r, c["name"])) or code, code, addr, _s(_get(r, c["contact"])), _s(_get(r, c["phone"])),
            _s(_get(r, c["tax"])), _s(_get(r, c["terms"]))))
        created += 1
    return _finish(conn, ctx, load_id, "VENDOR_LIST", file_name, {"created": created})


# ---------------------------------------------------------------------------
# Entry points
# ---------------------------------------------------------------------------

LOADERS: Dict[str, Callable[..., Dict[str, Any]]] = {
    "GENERAL_LEDGER": load_general_ledger,
    "CUSTOMER_LEDGER": lambda conn, ctx, rows, h, idx, fn: load_party_ledger(conn, ctx, rows, h, idx, fn, "CUSTOMER_LEDGER"),
    "VENDOR_LEDGER": lambda conn, ctx, rows, h, idx, fn: load_party_ledger(conn, ctx, rows, h, idx, fn, "VENDOR_LEDGER"),
    **{k: (lambda kk: (lambda conn, ctx, rows, h, idx, fn: load_journal(conn, ctx, rows, h, idx, fn, kk)))(k) for k in JOURNAL_KIND},
    "ITEM_COSTING": load_item_costing,
    "ITEM_MASTER": load_item_master,
    "CUSTOMER_LIST": load_customer_list,
    "VENDOR_LIST": load_vendor_list,
}
# The balances at the hand-over date (trial balance, open AR/AP, stock valuation) are not history:
# they are read by rollover.py when ACE Books takes over from Sage.
SNAPSHOT_KINDS = ("TRIAL_BALANCE", "OPEN_AR", "OPEN_AP", "INVENTORY")

# Masters first (so ledgers can match parties and items), the GL, then journals (sales before COGS).
ORDER = ["ITEM_MASTER", "CUSTOMER_LIST", "VENDOR_LIST", "GENERAL_LEDGER", "CUSTOMER_LEDGER", "VENDOR_LEDGER",
         "SALES_JOURNAL", "COGS_JOURNAL", "PURCHASE_JOURNAL", "CASH_RECEIPTS_JOURNAL", "CASH_DISBURSEMENTS_JOURNAL",
         "GENERAL_JOURNAL", "ITEM_COSTING"]


def load_file(conn, ctx, file_name: str, raw: Optional[bytes] = None, path: Optional[str] = None) -> Dict[str, Any]:
    ctx.require("migration.load")
    rows = read_rows(path or file_name, raw)
    kind, h, idx = detect(rows)
    if not kind:
        raise invalid(f"{file_name}: not a Sage report ACE recognises (check the header row)")
    if kind in SNAPSHOT_KINDS:
        return {"kind": kind, "file": file_name, "note": "Balances at a date - used when ACE Books takes over (rollover)"}
    return LOADERS[kind](conn, ctx, rows, h, idx, file_name)


# Where each kind's dated rows land (to find rows the books must not take: after the hand-over).
_DATED = {"GENERAL_LEDGER": ("fin_sage_gl_lines", "txn_date"), "CUSTOMER_LEDGER": ("fin_sage_party_ledger", "txn_date"),
          "VENDOR_LEDGER": ("fin_sage_party_ledger", "txn_date")}
KIND_LABEL = {"GENERAL_LEDGER": "General Ledger", "CUSTOMER_LEDGER": "Customer Ledger", "VENDOR_LEDGER": "Vendor Ledger",
              "SALES_JOURNAL": "Sales Journal", "COGS_JOURNAL": "Cost of Goods Sold Journal", "PURCHASE_JOURNAL": "Purchase Journal",
              "CASH_RECEIPTS_JOURNAL": "Cash Receipts Journal", "CASH_DISBURSEMENTS_JOURNAL": "Cash Disbursements Journal",
              "GENERAL_JOURNAL": "General Journal", "ITEM_COSTING": "Item Costing Report", "ITEM_MASTER": "Item Master List",
              "CUSTOMER_LIST": "Customer List", "VENDOR_LIST": "Vendor Master File", "TRIAL_BALANCE": "Trial Balance",
              "OPEN_AR": "Aged Receivables", "OPEN_AP": "Aged Payables", "INVENTORY": "Inventory Valuation"}


def _after_handover(conn, entity_id: str, kind: str, load_id: str, h: Optional[dt.date]) -> int:
    if not h or not load_id:
        return 0
    table, col = _DATED.get(kind, ("fin_sage_journal_lines", "txn_date") if kind in JOURNAL_KIND else (None, None))
    if not table:
        return 0
    return int(q1(conn, f"SELECT COUNT(*) AS n FROM {table} WHERE legal_entity_id=%s AND load_id=%s AND {col} > %s",
                  (entity_id, load_id, h))["n"])


def check_upload(conn, ctx, file_name: str, raw: bytes, *, keep: bool) -> Dict[str, Any]:
    """The Sage Import page's door into ACE Books' history. The file is recognised from its header,
    loaded, and checked; with keep=False (preview) everything is undone, so the user sees exactly
    what loading would do before anything changes. Refused:
      - a file ACE does not recognise;
      - rows dated after the hand-over: from the day after ``history_until`` ACE Books keeps the
        books, so Sage rows for those days would count twice;
      - a General Ledger that does not tie (beginning balance + lines must equal Sage's ending
        balance for every account) - the export is incomplete.
    Hand-over balance reports (trial balance, aged AR/AP, stock valuation) are recognised but not
    loaded: they are only read when ACE Books takes over from Sage (roll-forward)."""
    from src.fin import books_ledger
    ctx.require("migration.load")
    rows = read_rows(file_name, raw)
    kind, h_row, idx = detect(rows)
    out: Dict[str, Any] = {"file": file_name, "kind": kind, "label": KIND_LABEL.get(kind or "", None)}
    if not kind:
        raise invalid(f"{file_name}: not a Sage report ACE Books recognises. Export it from Sage with its header row "
                      "(General Ledger, Customer/Vendor Ledger, a journal, Item Costing, Item Master, Customer List, Vendor Master File).")
    if kind in SNAPSHOT_KINDS:
        return {**out, "status": "NOT_LOADED", "message": "Balances at a date: used only when ACE Books takes over from Sage, not loaded as history."}
    h = books_ledger.history_until(conn, ctx.entity_id)
    before = coverage(conn, ctx.entity_id)
    with conn.cursor() as cur:
        cur.execute("SAVEPOINT sage_upload")
    try:
        res = LOADERS[kind](conn, ctx, rows, h_row, idx, file_name)
        late = _after_handover(conn, ctx.entity_id, kind, res.get("load_id"), h)
        problems = []
        if late:
            problems.append(f"{late} row(s) are dated after the hand-over ({h:%d %b %Y}). A single report cannot move the books past it: "
                            "to bring later Sage activity into ACE, export the full set of reports as of one date and use "
                            "'Bring ACE up to date' (it moves the hand-over to that date).")
        if res.get("ending_balance_mismatches"):
            problems.append(f"{len(res['ending_balance_mismatches'])} account(s) do not tie to Sage's ending balance - the export looks incomplete.")
        replaced = [c for c in before if c["kind"] == kind and res.get("from") and res.get("to")
                    and str(c["date_from"]) <= str(res["to"]) and str(c["date_to"]) >= str(res["from"])]
        out.update({k: v for k, v in res.items() if k not in ("kind", "file")})
        out["after_handover"] = late
        out["history_until"] = h
        out["replaces"] = bool(replaced)
        out["problems"] = problems
        if problems or not keep:
            with conn.cursor() as cur:
                cur.execute("ROLLBACK TO SAVEPOINT sage_upload")
            out["status"] = "REFUSED" if problems else "PREVIEW"
            if problems and keep:
                raise invalid(" ".join(problems), **{k: str(v) for k, v in out.items() if k in ("file", "kind")})
            return out
        with conn.cursor() as cur:
            cur.execute("RELEASE SAVEPOINT sage_upload")
    except Exception:
        with conn.cursor() as cur:
            cur.execute("ROLLBACK TO SAVEPOINT sage_upload")
        raise
    out["status"] = "LOADED"
    # the Data issues register is refreshed from the new history (negative lots, TB/GL, control accounts)
    try:
        from src.fin import data_exceptions
        out["data_issues"] = data_exceptions.refresh(conn, ctx)
    except Exception as exc:  # the load stands; the register can be refreshed from Close & Controls
        out["data_issues_note"] = f"Data issues not refreshed: {exc}"
    return out


def scan_folder(folder: str) -> List[Dict[str, Any]]:
    out = []
    for name in sorted(os.listdir(folder)):
        if name.startswith("~$") or not name.lower().endswith((".xlsx", ".csv")):
            continue
        path = os.path.join(folder, name)
        rows = read_rows(path)
        kind, h, idx = detect(rows)
        out.append({"file": name, "path": path, "kind": kind, "rows": rows, "header": h, "idx": idx})
    return out


def ingest_folders(conn, ctx, folders: List[str]) -> List[Dict[str, Any]]:
    """Load every recognised history file in the given folders, oldest folder first."""
    ctx.require("migration.load")
    results = []
    for folder in folders:
        files = scan_folder(folder)
        for kind in ORDER:
            for f in [x for x in files if x["kind"] == kind]:
                results.append(LOADERS[kind](conn, ctx, f["rows"], f["header"], f["idx"], f["file"]))
        for f in files:
            if f["kind"] is None:
                results.append({"file": f["file"], "kind": None, "note": "not recognised - skipped"})
            elif f["kind"] in SNAPSHOT_KINDS:
                results.append({"file": f["file"], "kind": f["kind"], "note": "hand-over balances (rollover)"})
    return results


def coverage(conn, entity_id: str) -> List[Dict[str, Any]]:
    return q(conn, """SELECT kind, MIN(date_from) AS date_from, MAX(date_to) AS date_to, SUM(row_count) AS rows,
                             MAX(loaded_at) AS last_loaded, COUNT(*) AS loads
                      FROM fin_sage_loads WHERE legal_entity_id=%s GROUP BY kind ORDER BY kind""", (entity_id,))
