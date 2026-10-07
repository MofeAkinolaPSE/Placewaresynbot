"""Sage 50 -> ACE Books cutover (Development Engine spec §62-63).

Controlled, auditable, one-way: each Sage report is uploaded, parsed into a
STAGED batch with totals and issues shown for review, and only loaded when a
person approves it. Nothing silently becomes accounting policy.

Load order: Chart of Accounts -> products (from Sage item list) -> Trial
Balance (opening journal) -> open AR -> open AP -> inventory valuation.
Opening AR/AP/stock are subledger detail *behind* the trial balance, so they
load without journals; the integrity monitor then shows whether Sage's own
subledgers agreed with its GL (they don't, by ₦55,190 on AR - the client's
known problem).
"""
from __future__ import annotations

import csv
import datetime as dt
import io
import re
from decimal import Decimal
from typing import Any, Dict, List, Optional, Tuple

from src.fin import audit, inventory, posting, sage_history, setup
from src.fin.accounts import SUBTYPE_TYPE, default_normal_balance
from src.fin.db import ZERO, ex, jsonb, money, q, q1, qty
from src.fin.errors import FinError, invalid, not_found
from src.fin.periods import period_for

SAGE_TYPE = {
    "cash": "CASH", "accounts receivable": "RECEIVABLE", "inventory": "INVENTORY",
    "other current assets": "OTHER_CURRENT_ASSET", "fixed assets": "FIXED_ASSET",
    "accumulated depreciation": "ACCUMULATED_DEPRECIATION", "other assets": "OTHER_ASSET",
    "accounts payable": "PAYABLE", "other current liabilities": "OTHER_CURRENT_LIABILITY",
    "long term liabilities": "LONG_TERM_LIABILITY", "equity-doesn't close": "EQUITY",
    "equity-gets closed": "EQUITY_CLOSING", "equity-retained earnings": "RETAINED_EARNINGS",
    "income": "SALES", "cost of sales": "COST_OF_SALES", "expenses": "OPERATING_EXPENSE",
}
OTHER_INCOME_WORDS = ("other income", "interest income", "discounts received", "gain on", "dividend income")
OTHER_EXPENSE_WORDS = ("interest expense", "gain/loss", "loss on")

# Evidence-based defaults from the client's own Sage data (see ACE-Books.md).
DEFAULT_MAPPINGS = {
    "AR_CONTROL": "11000", "AP_CONTROL": "20000",
    "SALES_DEFAULT": "40000", "INVENTORY_DEFAULT": "12000", "COGS_DEFAULT": "50000",   # Sage's own item defaults
    "DELIVERY_INCOME": "40800", "OTHER_CHARGE_INCOME": "40800",   # SALES.CSV delivery lines post to 40800
    "SALES_DISCOUNT": "49000", "SALES_RETURNS": "48000", "INVENTORY_ADJUSTMENT": "58500",
    "WHT_SUFFERED": "78200", "WHT_PAYABLE": "23700", "BANK_CHARGES": "62200",
    "RETAINED_EARNINGS": "39005", "OPENING_BALANCE_EQUITY": "39004", "ASSET_DISPOSAL": "90000",
    "STOCK_ON_LOAN": "12990",
}
ASSET_CATEGORIES = [  # (code, name, asset, accumulated, expense)
    ("FURN", "Furniture & fixtures", "15000", "17000", "90100"),
    ("OFFEQ", "Office equipment", "15100", "17100", "90200"),
    ("MV", "Motor vehicles", "15150", "17200", "90300"),
    ("PM", "Plant & machinery", "15050", "17250", "90400"),
    ("OTHER", "Other depreciable property", "15300", "17300", "64500"),
    ("LAND", "Land & building", "16900", None, None),
    ("INVEST", "Investments", "16950", None, None),
]


# ---------------------------------------------------------------------------
# File reading
# ---------------------------------------------------------------------------

def read_rows(filename: str, raw: bytes) -> List[List[Any]]:
    if filename.lower().endswith(".xlsx"):
        import openpyxl
        wb = openpyxl.load_workbook(io.BytesIO(raw), read_only=True, data_only=True)
        return [list(r) for r in wb.worksheets[0].iter_rows(values_only=True) if any(v not in (None, "") for v in r)]
    text = raw.decode("utf-8-sig", errors="replace")
    return [r for r in csv.reader(io.StringIO(text)) if any(c.strip() for c in r)]


def _s(v: Any) -> str:
    return "" if v is None else str(v).strip()


def _dec(v: Any) -> Decimal:
    if v in (None, ""):
        return ZERO
    return money(str(v).replace(",", ""))


def _header_index(rows: List[List[Any]], must: Tuple[str, ...]) -> Tuple[int, Dict[str, int]]:
    for i, r in enumerate(rows[:10]):
        names = [re.sub(r"\s+", " ", _s(c)).lower() for c in r]
        if all(any(m in n for n in names) for m in must):
            return i, {n: j for j, n in enumerate(names)}
    raise invalid(f"Could not find the header row (expected columns: {', '.join(must)})")


def _col(idx: Dict[str, int], *names: str) -> Optional[int]:
    for n in names:  # exact header first ("customer" must not grab "customer id")
        if n in idx:
            return idx[n]
    for n in names:
        for k, j in idx.items():
            if k.startswith(n):
                return j
    return None


# ---------------------------------------------------------------------------
# Parsers: one per Sage report layout
# ---------------------------------------------------------------------------

def parse(kind: str, rows: List[List[Any]]) -> Dict[str, Any]:
    if kind in sage_history.PARSERS:
        return sage_history.PARSERS[kind](rows, _header_index, _col)
    fn = {"COA": _parse_coa, "TRIAL_BALANCE": _parse_tb, "OPEN_AR": _parse_aged, "OPEN_AP": _parse_aged,
          "INVENTORY": _parse_inventory}.get(kind)
    if not fn:
        raise invalid(f"Unknown migration kind {kind}")
    return fn(rows)


def _parse_coa(rows):
    h, idx = _header_index(rows, ("account id", "account type"))
    c_id, c_name, c_act, c_type = _col(idx, "account id"), _col(idx, "account description", "description"), \
        _col(idx, "active"), _col(idx, "account type")
    out, issues = [], []
    for r in rows[h + 1:]:
        code = _s(r[c_id])
        if not code:
            continue
        stype = _s(r[c_type]).lower()
        subtype = SAGE_TYPE.get(stype)
        name = _s(r[c_name])
        if not subtype:
            issues.append({"row": code, "message": f"Unknown Sage account type {r[c_type]!r}"})
            continue
        n = name.lower()
        if subtype == "SALES" and any(w in n for w in OTHER_INCOME_WORDS):
            subtype = "OTHER_INCOME"
        if subtype == "OPERATING_EXPENSE" and any(w in n for w in OTHER_EXPENSE_WORDS):
            subtype = "OTHER_EXPENSE"
        normal = default_normal_balance(subtype)
        if subtype in ("RECEIVABLE", "OTHER_ASSET", "FIXED_ASSET") and ("allowance" in n or "accum" in n):
            normal = "CREDIT"
        out.append({"code": code, "name": name, "subtype": subtype, "normal_balance": normal,
                    "active": _s(r[c_act]).lower() in ("yes", "true", "y", ""), "legacy_type": _s(r[c_type])})
    counts: Dict[str, int] = {}
    for a in out:
        counts[a["subtype"]] = counts.get(a["subtype"], 0) + 1
    return {"rows": out, "issues": issues, "summary": {"accounts": len(out), "by_subtype": counts}}


def _parse_tb(rows):
    h, idx = _header_index(rows, ("account id", "debit", "credit"))
    c_id, c_name, c_dr, c_cr = _col(idx, "account id"), _col(idx, "account description"), _col(idx, "debit"), _col(idx, "credit")
    out, dr, cr = [], ZERO, ZERO
    for r in rows[h + 1:]:
        code = _s(r[c_id])
        if not code or not re.match(r"^[\w.\-]+$", code):
            continue
        d, c = _dec(r[c_dr]), _dec(r[c_cr])
        if d == 0 and c == 0:
            continue
        out.append({"code": code, "name": _s(r[c_name]), "debit": d, "credit": c})
        dr += d
        cr += c
    issues = [] if dr == cr else [{"message": f"Trial balance does not balance: debits ₦{dr:,.2f}, credits ₦{cr:,.2f}"}]
    return {"rows": out, "issues": issues, "summary": {"accounts": len(out), "total_debit": dr, "total_credit": cr,
                                                       "balanced": dr == cr}}


def _parse_aged(rows):
    """Sage Aged Receivables / Aged Payables: one row per open document plus
    per-party subtotal rows (blank document number) and a 'Report Total'."""
    h, idx = _header_index(rows, ("invoice/cm", "amount due"))
    c_party = _col(idx, "customer id", "vendor id")
    c_name = _col(idx, "customer", "vendor")
    c_doc, c_amt = _col(idx, "invoice/cm"), _col(idx, "amount due")
    bucket_cols = [j for n, j in idx.items() if re.match(r"^(\d+\s*-\s*\d+|over \d+)", n)]
    out, total, report_total = [], ZERO, None
    # Group consecutive rows per party: the LAST row of a group with no document
    # number is the party subtotal; any other number-less row is a real open item
    # (Sage allows invoices without a number - e.g. Premier Hospital's).
    groups: List[Tuple[str, List[List[Any]]]] = []
    for r in rows[h + 1:]:
        party = _s(r[c_party])
        if party.lower() == "report total":
            report_total = _dec(r[c_amt])
            continue
        if not party:
            continue
        if groups and groups[-1][0] == party:
            groups[-1][1].append(r)
        else:
            groups.append((party, [r]))
    for party, grp in groups:
        last_blank = max((i for i, r in enumerate(grp) if not _s(r[c_doc])), default=None)
        n_blank = 0
        for i, r in enumerate(grp):
            doc = _s(r[c_doc])
            if not doc:
                if i == last_blank:
                    continue  # subtotal row
                n_blank += 1
                doc = f"NO-REF-{n_blank}"
            amt = _dec(r[c_amt])
            if amt == 0:
                continue
            # Oldest non-empty bucket tells us roughly how old the item is.
            age_bucket = next((rows[h][j] for j in reversed(bucket_cols) if _dec(r[j]) != 0), None)
            out.append({"party_code": party, "party_name": _s(r[c_name]) if c_name is not None else party, "document": doc,
                        "amount": amt, "age_bucket": _s(age_bucket)})
            total += amt
    issues = []
    if report_total is not None and report_total != total:
        issues.append({"message": f"Items total ₦{total:,.2f} but the report total is ₦{report_total:,.2f}"})
    return {"rows": out, "issues": issues, "summary": {"documents": len(out), "total": total, "report_total": report_total,
                                                       "parties": len({r['party_code'] for r in out}),
                                                       "credits": sum(1 for r in out if r["amount"] < 0)}}


def _parse_inventory(rows):
    h, idx = _header_index(rows, ("item id", "qty on hand", "item value"))
    c_id, c_desc = _col(idx, "item id"), _col(idx, "item description")
    c_qty, c_val = _col(idx, "qty on hand"), _col(idx, "item value")
    out, issues, total, excluded, report_total = [], [], ZERO, ZERO, None
    for r in rows[h + 1:]:
        sku = _s(r[c_id])
        if not sku:
            if _dec(r[c_val]) != 0:
                report_total = _dec(r[c_val])  # Sage's closing total row
            continue
        qn = qty(_s(r[c_qty]).replace(",", "") or 0)
        val = _dec(r[c_val])
        if qn == 0 and val == 0:
            continue
        if qn <= 0 or val < 0:
            # Sage allowed selling before receiving; negative stock is not a real
            # cost layer - it needs a stock count at cutover.
            issues.append({"row": sku, "sku": sku, "name": _s(r[c_desc]), "quantity": str(qn), "value": str(val),
                           "message": f"{sku}: quantity {qn:g} valued ₦{val:,.2f} in Sage - not loaded; count this item"})
            excluded += val
            continue
        out.append({"sku": sku, "name": _s(r[c_desc]), "quantity": qn, "value": val})
        total += val
    return {"rows": out, "issues": issues, "summary": {"items": len(out), "total_value": total,
                                                       "excluded_negative_or_zero_items": len(issues),
                                                       "excluded_value": excluded, "sage_report_total": report_total}}


# ---------------------------------------------------------------------------
# Staging
# ---------------------------------------------------------------------------

def stage(conn, ctx, kind: str, filename: str, raw: bytes, as_of: Optional[dt.date]) -> Dict[str, Any]:
    ctx.require("migration.stage")
    kind = kind.upper()
    parsed = parse(kind, read_rows(filename, raw))
    if kind in ("TRIAL_BALANCE", "OPEN_AR", "OPEN_AP", "INVENTORY") and not as_of:
        raise invalid("Give the 'as of' date the report was run for (the cutover date)")
    extra = _compare(conn, ctx.entity_id, kind, parsed)
    b = q1(conn, """INSERT INTO fin_migration_batches (legal_entity_id, kind, file_name, as_of_date, row_count, summary,
                    issues, rows, created_by) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id""",
           (ctx.entity_id, kind, filename, as_of, len(parsed["rows"]), jsonb({**parsed["summary"], **extra}),
            jsonb(parsed["issues"]), jsonb(parsed["rows"]), ctx.actor_id))
    audit.record(conn, ctx, "MIGRATION_STAGED", "migration_batch", b["id"], ref=f"{kind} {filename}",
                 metadata={"rows": len(parsed["rows"]), "issues": len(parsed["issues"])})
    return get_batch(conn, ctx.entity_id, str(b["id"]))


def _compare(conn, entity_id: str, kind: str, parsed: Dict[str, Any]) -> Dict[str, Any]:
    """Tie the subledger file to the loaded trial balance, the way an auditor would."""
    tb = q1(conn, "SELECT summary, rows FROM fin_migration_batches WHERE legal_entity_id=%s AND kind='TRIAL_BALANCE' "
                  "AND status='LOADED' ORDER BY loaded_at DESC LIMIT 1", (entity_id,))
    if not tb or kind not in ("OPEN_AR", "OPEN_AP", "INVENTORY"):
        return {}
    accts = {a["code"]: a for a in q(conn, "SELECT code, subtype FROM fin_accounts WHERE legal_entity_id=%s", (entity_id,))}
    maps = {m["mapping_key"]: m["code"] for m in setup.list_mappings(conn, entity_id)}

    def tb_total(pred):
        return sum((money(r["debit"]) - money(r["credit"]) for r in tb["rows"] if pred(r["code"])), ZERO)
    if kind == "OPEN_AR":
        gl, sub = tb_total(lambda c: c == maps.get("AR_CONTROL")), parsed["summary"]["total"]
    elif kind == "OPEN_AP":
        gl, sub = -tb_total(lambda c: c == maps.get("AP_CONTROL")), parsed["summary"]["total"]
    else:
        gl, sub = tb_total(lambda c: accts.get(c, {}).get("subtype") == "INVENTORY"), parsed["summary"]["total_value"]
    return {"trial_balance_control": gl, "difference_to_trial_balance": gl - sub}


def get_batch(conn, entity_id: str, batch_id: str, include_rows: bool = False) -> Dict[str, Any]:
    cols = "*" if include_rows else "id, kind, file_name, as_of_date, status, row_count, summary, issues, created_by, created_at, loaded_by, loaded_at"
    b = q1(conn, f"SELECT {cols} FROM fin_migration_batches WHERE id=%s AND legal_entity_id=%s", (batch_id, entity_id))
    if not b:
        raise not_found("Migration batch", batch_id)
    if not include_rows:
        sample = q1(conn, "SELECT jsonb_path_query_array(rows, '$[0 to 24]') AS s FROM fin_migration_batches WHERE id=%s", (batch_id,))["s"]
        b["sample"] = sample
    return b


def list_batches(conn, entity_id: str) -> List[Dict[str, Any]]:
    return q(conn, """SELECT id, kind, file_name, as_of_date, status, row_count, summary, jsonb_array_length(issues) AS issue_count,
                             created_by, created_at, loaded_by, loaded_at
                      FROM fin_migration_batches WHERE legal_entity_id=%s ORDER BY created_at DESC""", (entity_id,))


def discard(conn, ctx, batch_id: str) -> Dict[str, Any]:
    ctx.require("migration.stage")
    b = get_batch(conn, ctx.entity_id, batch_id)
    if b["status"] != "STAGED":
        raise FinError("INVALID_STATE_TRANSITION", f"A {b['status'].lower()} batch cannot be discarded")
    ex(conn, "UPDATE fin_migration_batches SET status='DISCARDED' WHERE id=%s", (batch_id,))
    audit.record(conn, ctx, "MIGRATION_DISCARDED", "migration_batch", batch_id, ref=b["kind"])
    return get_batch(conn, ctx.entity_id, batch_id)


# ---------------------------------------------------------------------------
# Loading (approval)
# ---------------------------------------------------------------------------

def load(conn, ctx, batch_id: str) -> Dict[str, Any]:
    ctx.require("migration.load")
    b = q1(conn, "SELECT * FROM fin_migration_batches WHERE id=%s AND legal_entity_id=%s FOR UPDATE", (batch_id, ctx.entity_id))
    if not b:
        raise not_found("Migration batch", batch_id)
    if b["status"] != "STAGED":
        raise FinError("INVALID_STATE_TRANSITION", f"Batch is {b['status'].lower()}")
    fn = {"COA": _load_coa, "TRIAL_BALANCE": _load_tb, "OPEN_AR": _load_ar, "OPEN_AP": _load_ap,
          "INVENTORY": _load_inventory, **sage_history.LOADERS}[b["kind"]]
    result = fn(conn, ctx, b)
    ex(conn, "UPDATE fin_migration_batches SET status='LOADED', loaded_by=%s, loaded_at=now(), summary = summary || %s WHERE id=%s",
       (ctx.actor_id, jsonb({"load_result": result}), batch_id))
    audit.record(conn, ctx, "MIGRATION_LOADED", "migration_batch", batch_id, ref=b["kind"], metadata=result)
    return {**get_batch(conn, ctx.entity_id, batch_id), "result": result}


def _load_coa(conn, ctx, b) -> Dict[str, Any]:
    created = updated = 0
    for a in b["rows"]:
        existing = q1(conn, "SELECT id FROM fin_accounts WHERE legal_entity_id=%s AND code=%s", (ctx.entity_id, a["code"]))
        if existing:
            ex(conn, "UPDATE fin_accounts SET legacy_type=%s, legacy_code=%s WHERE id=%s", (a["legacy_type"], a["code"], existing["id"]))
            updated += 1
            continue
        ex(conn, """INSERT INTO fin_accounts (legal_entity_id, code, name, account_type, subtype, normal_balance, status,
                    legacy_code, legacy_type, created_by) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
           (ctx.entity_id, a["code"], a["name"], SUBTYPE_TYPE[a["subtype"]], a["subtype"], a["normal_balance"],
            "ACTIVE" if a["active"] else "INACTIVE", a["code"], a["legacy_type"], ctx.actor_id))
        created += 1
    extra = bootstrap_defaults(conn, ctx)
    return {"created": created, "updated": updated, **extra}


def bootstrap_defaults(conn, ctx) -> Dict[str, Any]:
    """Posting rules, control flags, bank/cash accounts and asset categories from the client's chart."""
    if not q1(conn, "SELECT 1 FROM fin_accounts WHERE legal_entity_id=%s AND code='12990'", (ctx.entity_id,)):
        ex(conn, """INSERT INTO fin_accounts (legal_entity_id, code, name, account_type, subtype, normal_balance, description, created_by)
                    VALUES (%s,'12990','Stock on Loan','ASSET','OTHER_CURRENT_ASSET','DEBIT',
                    'Added by ACE Books: stock lent to customers (not a sale). Confirm with the accountant.',%s)""",
           (ctx.entity_id, ctx.actor_id))
    mapped = []
    for key, code in DEFAULT_MAPPINGS.items():
        a = q1(conn, "SELECT id FROM fin_accounts WHERE legal_entity_id=%s AND code=%s AND status='ACTIVE'", (ctx.entity_id, code))
        if a and not q1(conn, "SELECT 1 FROM fin_account_mappings WHERE legal_entity_id=%s AND mapping_key=%s", (ctx.entity_id, key)):
            ex(conn, """INSERT INTO fin_account_mappings (legal_entity_id, mapping_key, account_id, note, updated_by)
                        VALUES (%s,%s,%s,'Default from the client''s Sage chart',%s)""", (ctx.entity_id, key, a["id"], ctx.actor_id))
            mapped.append(key)
    for key in ("AR_CONTROL", "AP_CONTROL"):
        ex(conn, """UPDATE fin_accounts SET is_control=TRUE WHERE id=(SELECT account_id FROM fin_account_mappings
                    WHERE legal_entity_id=%s AND mapping_key=%s)""", (ctx.entity_id, key))
    ex(conn, "UPDATE fin_accounts SET is_control=TRUE WHERE legal_entity_id=%s AND subtype='INVENTORY'", (ctx.entity_id,))
    banks = 0
    for a in q(conn, "SELECT * FROM fin_accounts WHERE legal_entity_id=%s AND subtype='CASH' AND status='ACTIVE'", (ctx.entity_id,)):
        n = a["name"].lower()
        if "suspense" in n:
            continue
        kind = "PETTY_CASH" if "petty" in n else ("CASH" if "cash" in n or "cheq" in n else "BANK")
        r = q1(conn, """INSERT INTO fin_bank_accounts (legal_entity_id, gl_account_id, name, kind) VALUES (%s,%s,%s,%s)
                        ON CONFLICT (legal_entity_id, gl_account_id) DO NOTHING RETURNING id""", (ctx.entity_id, a["id"], a["name"], kind))
        banks += 1 if r else 0
    cats = 0
    for code, name, asset, accum, expense in ASSET_CATEGORIES:
        ids = {}
        for k, c in (("asset", asset), ("accum", accum), ("expense", expense)):
            if c:
                row = q1(conn, "SELECT id FROM fin_accounts WHERE legal_entity_id=%s AND code=%s", (ctx.entity_id, c))
                ids[k] = row["id"] if row else None
        if not ids.get("asset"):
            continue
        r = q1(conn, """INSERT INTO fin_asset_categories (legal_entity_id, code, name, asset_account_id, accum_dep_account_id,
                        dep_expense_account_id, depreciable) VALUES (%s,%s,%s,%s,%s,%s,%s)
                        ON CONFLICT (legal_entity_id, code) DO NOTHING RETURNING id""",
               (ctx.entity_id, code, name, ids["asset"], ids.get("accum"), ids.get("expense"),
                bool(ids.get("accum") and ids.get("expense"))))
        cats += 1 if r else 0
    return {"mappings": mapped, "bank_accounts": banks, "asset_categories": cats}


def sync_products(conn, ctx) -> Dict[str, Any]:
    """Products from the Sage item list already in ACE (ITEM.CSV import + item snapshot)."""
    ctx.require("migration.load")
    codes = {a["code"]: a["id"] for a in q(conn, "SELECT id, code FROM fin_accounts WHERE legal_entity_id=%s", (ctx.entity_id,))}
    rows = q(conn, """SELECT a.item_id, COALESCE(a.item_description, s.name, a.item_id) AS name, a.sales_account,
                             a.inventory_account, a.cogs_account, a.sales_price_1, a.item_class, a.inactive, a.stocking_um
                      FROM v_sage_item_accounts a
                      LEFT JOIN (SELECT sku, MAX(name) AS name FROM v_inventory GROUP BY sku) s ON s.sku = a.item_id""")
    created = updated = 0
    for r in rows:
        ptype = "SERVICE" if str(r["item_class"] or "") in ("3", "4", "Service", "Non-stock item") else "INVENTORY"
        vals = (r["name"], codes.get(r["sales_account"]), codes.get(r["inventory_account"]), codes.get(r["cogs_account"]),
                r["sales_price_1"], "INACTIVE" if r["inactive"] else "ACTIVE", r["stocking_um"] or "Each")
        existing = q1(conn, "SELECT id FROM fin_products WHERE legal_entity_id=%s AND sku=%s", (ctx.entity_id, r["item_id"]))
        if existing:
            ex(conn, """UPDATE fin_products SET name=%s, revenue_account_id=%s, inventory_account_id=%s, cogs_account_id=%s,
                        standard_price=%s, status=%s, uom=%s WHERE id=%s""", vals + (existing["id"],))
            updated += 1
        else:
            ex(conn, """INSERT INTO fin_products (legal_entity_id, sku, name, revenue_account_id, inventory_account_id,
                        cogs_account_id, standard_price, status, uom, product_type, legacy_class)
                        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
               (ctx.entity_id, r["item_id"]) + vals + (ptype, str(r["item_class"] or "")))
            created += 1
    audit.record(conn, ctx, "PRODUCTS_SYNCED", "products", ctx.entity_id, metadata={"created": created, "updated": updated})
    return {"created": created, "updated": updated, "total": len(rows)}


def _load_tb(conn, ctx, b) -> Dict[str, Any]:
    if q1(conn, "SELECT 1 FROM fin_journals WHERE legal_entity_id=%s AND journal_type='OPENING' AND status='POSTED'", (ctx.entity_id,)):
        raise FinError("DUPLICATE_RESOURCE", "Opening balances are already posted; reverse that journal first to reload")
    as_of = b["as_of_date"]
    period_for(conn, ctx.entity_id, as_of)
    codes = {a["code"]: a for a in q(conn, "SELECT id, code, status FROM fin_accounts WHERE legal_entity_id=%s", (ctx.entity_id,))}
    missing = [r["code"] for r in b["rows"] if r["code"] not in codes]
    if missing:
        raise FinError("RESOURCE_NOT_FOUND", f"{len(missing)} trial-balance account(s) are not in the chart of accounts",
                       {"accounts": missing[:50]})
    inactive = [r["code"] for r in b["rows"] if codes[r["code"]]["status"] != "ACTIVE"]
    for code in inactive:  # a balance must be able to land; the accountant can deactivate later
        ex(conn, "UPDATE fin_accounts SET status='ACTIVE' WHERE id=%s", (codes[code]["id"],))
    lines = [{"account_id": codes[r["code"]]["id"], "debit": r["debit"], "credit": r["credit"],
              "description": f"Opening balance (Sage TB {as_of:%d %b %Y})"} for r in b["rows"]]
    j = posting.post_system(conn, ctx, event_type="OPENING_BALANCES_LOADED", journal_date=as_of, lines=lines,
                            description=f"Opening balances from Sage 50 trial balance as at {as_of:%d %b %Y}",
                            source_type="MIGRATION", source_id=b["id"], source_ref="SAGE-TB", journal_type="OPENING",
                            idempotency_key=f"OPENING:{ctx.entity_id}")
    # Bank balances at cutover are the reconciliation baseline.
    for l in q(conn, """SELECT l.id, ba.id AS bank_id FROM fin_journal_lines l JOIN fin_bank_accounts ba ON ba.gl_account_id=l.account_id
                        WHERE l.journal_id=%s""", (j["id"],)):
        ex(conn, """INSERT INTO fin_cleared_lines (journal_line_id, bank_account_id, cleared_date, cleared_by)
                    VALUES (%s,%s,%s,%s) ON CONFLICT DO NOTHING""", (l["id"], l["bank_id"], as_of, ctx.actor_id))
    s = setup.get_settings(conn, ctx.entity_id)
    if not s.get("cutover_date"):
        ex(conn, "UPDATE fin_settings SET cutover_date=%s WHERE legal_entity_id=%s", (as_of + dt.timedelta(days=1), ctx.entity_id))
    return {"journal": j["journal_number"], "lines": len(lines), "total": str(j["total_debit"]), "reactivated": inactive}


def _party_customer(conn, code: str, name: str) -> int:
    c = q1(conn, "SELECT id FROM customers WHERE customer_code=%s", (code,))
    if c:
        return c["id"]
    return q1(conn, "INSERT INTO customers (name, customer_code, metadata) VALUES (%s,%s,%s) RETURNING id",
              (name or code, code, jsonb({"source": "sage_open_ar_migration"})))["id"]


def _party_supplier(conn, code: str, name: str) -> str:
    s = q1(conn, "SELECT id FROM suppliers WHERE external_vendor_id=%s", (code,))
    if s:
        return str(s["id"])
    return str(q1(conn, "INSERT INTO suppliers (name, external_vendor_id, status) VALUES (%s,%s,'active') RETURNING id",
                  (name or code, code))["id"])


def _load_ar(conn, ctx, b) -> Dict[str, Any]:
    as_of = b["as_of_date"]
    inv = cred = new_customers = 0
    known = {r["customer_code"] for r in q(conn, "SELECT customer_code FROM customers WHERE customer_code IS NOT NULL")}
    for r in b["rows"]:
        if r["party_code"] not in known:
            new_customers += 1
            known.add(r["party_code"])
        cid = _party_customer(conn, r["party_code"], r["party_name"])
        amt = money(r["amount"])
        if amt > 0:
            number = f"OB-{r['document']}"[:60]
            if q1(conn, "SELECT 1 FROM fin_sales_invoices WHERE legal_entity_id=%s AND invoice_number=%s", (ctx.entity_id, number)):
                number = f"{number}-{cid}"
            ex(conn, """INSERT INTO fin_sales_invoices (legal_entity_id, invoice_number, customer_id, invoice_date, due_date,
                        subtotal, total, status, source_type, source_id, is_opening, notes, created_by, posted_at)
                        VALUES (%s,%s,%s,%s,%s,%s,%s,'POSTED','OPENING',%s,TRUE,%s,%s,now())""",
               (ctx.entity_id, number, cid, as_of, as_of, amt, amt, f"{b['id']}:{cid}:{r['document']}",
                f"Sage open item {r['document']} ({r['age_bucket'] or 'aged'}) at cutover", ctx.actor_id))
            inv += 1
        else:
            ex(conn, """INSERT INTO fin_credit_notes (legal_entity_id, credit_note_number, customer_id, note_date, reason,
                        total, created_by) VALUES (%s,%s,%s,%s,%s,%s,%s)""",
               (ctx.entity_id, f"OB-CR-{r['document']}-{cid}"[:60], cid, as_of,
                f"Unapplied credit from Sage ({r['document']}) at cutover", -amt, ctx.actor_id))
            cred += 1
    dated = refresh_opening_dates(conn, ctx, b)
    return {"open_invoices": inv, "open_credits": cred, "customers_created": new_customers, **dated}


_BUCKET_DAYS = [("over", 91), ("61", 75), ("31", 45), ("0", 15)]


def _bucket_date(as_of: dt.date, bucket: Optional[str]) -> dt.date:
    b = (bucket or "").lower()
    for key, days in _BUCKET_DAYS:
        if b.startswith(key):
            return as_of - dt.timedelta(days=days)
    return as_of


def refresh_opening_dates(conn, ctx, batch: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Give migrated open items their real Sage invoice / due dates so ageing
    matches Sage's Aged Receivables. Uses the Sage AR data ACE already holds
    (v_ar_invoices); where an item is not there, the Sage ageing bucket from the
    report places it (noted as approximate). Opening items carry no journals,
    so re-dating them changes ageing only, never the ledger."""
    if batch is None:
        batch = q1(conn, """SELECT * FROM fin_migration_batches WHERE legal_entity_id=%s AND kind='OPEN_AR'
                            AND status IN ('LOADED','STAGED') ORDER BY created_at DESC LIMIT 1""", (ctx.entity_id,))
        if not batch:
            raise not_found("Loaded open-AR migration batch")
    as_of = batch["as_of_date"]
    buckets = {(r["party_code"], r["document"]): r.get("age_bucket") for r in batch["rows"]}
    exact = approx = 0
    for inv in q(conn, """SELECT i.id, i.source_id, c.customer_code FROM fin_sales_invoices i JOIN customers c ON c.id=i.customer_id
                          WHERE i.legal_entity_id=%s AND i.is_opening""", (ctx.entity_id,)):
        doc = (inv["source_id"] or "").split(":", 2)[-1]
        sage = q1(conn, """SELECT invoice_date, due_date FROM v_ar_invoices WHERE invoice_id=%s AND customer_id=%s
                           AND invoice_date IS NOT NULL ORDER BY invoice_date LIMIT 1""", (doc, inv["customer_code"]))
        if sage and sage["invoice_date"] <= as_of:
            d, due = sage["invoice_date"], sage["due_date"] or sage["invoice_date"]
            exact += 1
        else:
            d = due = _bucket_date(as_of, buckets.get((inv["customer_code"], doc)))
            approx += 1
        ex(conn, "UPDATE fin_sales_invoices SET invoice_date=%s, due_date=%s WHERE id=%s", (d, due, inv["id"]))
    for cn in q(conn, """SELECT n.id, n.credit_note_number, c.customer_code FROM fin_credit_notes n JOIN customers c ON c.id=n.customer_id
                         WHERE n.legal_entity_id=%s AND n.journal_id IS NULL AND n.credit_note_number LIKE 'OB-CR-%%'""", (ctx.entity_id,)):
        doc = cn["credit_note_number"][6:].rsplit("-", 1)[0]
        ex(conn, "UPDATE fin_credit_notes SET note_date=%s WHERE id=%s",
           (_bucket_date(as_of, buckets.get((cn["customer_code"], doc))), cn["id"]))
    audit.record(conn, ctx, "OPENING_ITEMS_DATED", "migration_batch", batch["id"],
                 metadata={"sage_dates": exact, "approximated_from_bucket": approx})
    return {"dated_from_sage": exact, "dated_from_bucket": approx}


def _load_ap(conn, ctx, b) -> Dict[str, Any]:
    as_of = b["as_of_date"]
    bills = debits = 0
    for r in b["rows"]:
        sid = _party_supplier(conn, r["party_code"], r["party_name"])
        amt = money(r["amount"])
        if amt > 0:
            number = f"OB-{r['document']}"[:60]
            if q1(conn, "SELECT 1 FROM fin_supplier_bills WHERE legal_entity_id=%s AND bill_number=%s", (ctx.entity_id, number)):
                number = f"{number}-{bills}"
            # Sage ages payables by due date; its bucket is all the report gives us.
            due = _bucket_date(as_of, r.get("age_bucket"))
            ex(conn, """INSERT INTO fin_supplier_bills (legal_entity_id, bill_number, supplier_id, supplier_invoice_number,
                        bill_date, due_date, subtotal, total, is_opening, notes, created_by)
                        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,TRUE,%s,%s)""",
               (ctx.entity_id, number, sid, r["document"], due, due, amt, amt,
                f"Sage open item ({r['age_bucket'] or 'aged'}) at cutover", ctx.actor_id))
            bills += 1
        else:
            ex(conn, """INSERT INTO fin_debit_notes (legal_entity_id, debit_note_number, supplier_id, note_date, reason, total, created_by)
                        VALUES (%s,%s,%s,%s,%s,%s,%s)""",
               (ctx.entity_id, f"OB-DR-{r['document']}-{debits}"[:60], sid, _bucket_date(as_of, r.get("age_bucket")),
                f"Supplier debit balance from Sage ({r['document']}) at cutover", -amt, ctx.actor_id))
            debits += 1
    return {"open_bills": bills, "open_debits": debits}


def _load_inventory(conn, ctx, b) -> Dict[str, Any]:
    as_of = b["as_of_date"]
    loaded, skipped = 0, []
    for r in b["rows"]:
        if not q1(conn, "SELECT 1 FROM fin_products WHERE legal_entity_id=%s AND sku=%s", (ctx.entity_id, r["sku"])):
            skipped.append(r["sku"])
            continue
        unit = Decimal(str(r["value"])) / Decimal(str(r["quantity"]))
        inventory.receive(conn, ctx, sku=r["sku"], quantity=r["quantity"], unit_cost=unit, txn_type="OPENING_BALANCE",
                          txn_date=as_of, source_type="MIGRATION", source_id=b["id"], reference="SAGE-VALUATION",
                          reason="Opening stock from Sage inventory valuation", mirror=False,
                          total_cost=money(r["value"]))
        loaded += 1
    return {"items": loaded, "skipped_unknown_products": skipped, **sage_history.assign_opening_batches(conn, ctx)}
