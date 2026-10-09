"""Fixed assets & depreciation.

The client depreciates straight-line (meeting 1: a ₦4m vehicle over 4 years
= ₦1m a year) and posts it by journal: DR depreciation expense / CR
accumulated depreciation. Here that journal is produced by a monthly run.
Useful lives and residual values are entered per asset - they are the
accountant's policy (research gate R6), never defaulted by the system.
"""
from __future__ import annotations

import datetime as dt
from decimal import ROUND_HALF_UP, Decimal
from typing import Any, Dict, List, Optional

from src.fin import audit, posting
from src.fin.db import ZERO, ex, money, q, q1
from src.fin.errors import FinError, invalid, not_found
from src.fin.numbering import next_number
from src.fin.periods import require_open
from src.fin.sales import bank_account


def list_categories(conn, entity_id: str) -> List[Dict[str, Any]]:
    return q(conn, """SELECT c.*, a.code AS asset_code_gl, a.name AS asset_account_name, d.code AS accum_code,
                             e.code AS expense_code
                      FROM fin_asset_categories c JOIN fin_accounts a ON a.id=c.asset_account_id
                      LEFT JOIN fin_accounts d ON d.id=c.accum_dep_account_id LEFT JOIN fin_accounts e ON e.id=c.dep_expense_account_id
                      WHERE c.legal_entity_id=%s ORDER BY c.code""", (entity_id,))


def create_category(conn, ctx, data: Dict[str, Any]) -> Dict[str, Any]:
    ctx.require("assets.category.edit")
    depreciable = bool(data.get("depreciable", True))
    if depreciable and not (data.get("accum_dep_account_id") and data.get("dep_expense_account_id")):
        raise invalid("A depreciable category needs accumulated-depreciation and depreciation-expense accounts")
    c = q1(conn, """INSERT INTO fin_asset_categories (legal_entity_id, code, name, asset_account_id, accum_dep_account_id,
                    dep_expense_account_id, disposal_account_id, default_life_months, depreciable)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING *""",
           (ctx.entity_id, data["code"], data["name"], data["asset_account_id"], data.get("accum_dep_account_id"),
            data.get("dep_expense_account_id"), data.get("disposal_account_id"), data.get("default_life_months"), depreciable))
    audit.record(conn, ctx, "ASSET_CATEGORY_CREATED", "asset_category", c["id"], ref=c["name"])
    return c


def _category(conn, entity_id: str, cid: str) -> Dict[str, Any]:
    c = q1(conn, "SELECT * FROM fin_asset_categories WHERE id=%s AND legal_entity_id=%s", (cid, entity_id))
    if not c:
        raise not_found("Asset category", cid)
    return c


def monthly_charge(asset: Dict[str, Any], accumulated: Decimal) -> Decimal:
    life = asset.get("useful_life_months")
    if not life:
        return ZERO
    base = money(asset["cost"]) - money(asset["residual_value"])
    per = (base / Decimal(life)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    remaining = base - accumulated
    return max(min(per, remaining), ZERO)


def accumulated(conn, asset_id: str) -> Decimal:
    a = q1(conn, "SELECT opening_accumulated_depreciation FROM fin_fixed_assets WHERE id=%s", (asset_id,))
    run = q1(conn, "SELECT COALESCE(SUM(amount),0) s FROM fin_depreciation_lines WHERE asset_id=%s", (asset_id,))["s"]
    return money(a["opening_accumulated_depreciation"]) + money(run)


def register_asset(conn, ctx, data: Dict[str, Any]) -> Dict[str, Any]:
    """Add an asset to the register. `funding` says how it was paid:
       BANK (bank_account_id), CLEARING (an account, e.g. from a supplier bill line),
       OPENING (already in the migrated balances - register only, no journal) or
       POSTED (already posted to the asset account by a payment / voucher - register only)."""
    ctx.require("assets.asset.create")
    cat = _category(conn, ctx.entity_id, data["category_id"])
    cost = money(data.get("cost"))
    residual = money(data.get("residual_value"))
    if cost <= 0 or residual < 0 or residual >= cost:
        raise invalid("Cost must be positive and residual value lower than cost")
    life = data.get("useful_life_months") or cat["default_life_months"]
    if cat["depreciable"] and not life:
        raise invalid("Enter the useful life in months (the accountant's depreciation policy)")
    acquired = data["acquisition_date"]
    dep_start = data.get("depreciation_start") or acquired.replace(day=1)
    funding = str(data.get("funding") or "BANK").upper()
    opening_acc = money(data.get("opening_accumulated_depreciation")) if funding in ("OPENING", "POSTED") else ZERO
    if data.get("source_line") and q1(conn, "SELECT 1 FROM fin_fixed_assets WHERE legal_entity_id=%s AND source_line=%s",
                                      (ctx.entity_id, data["source_line"])):
        raise FinError("DUPLICATE_RESOURCE", "That purchase is already in the asset register")
    number = data.get("asset_code") or next_number(conn, ctx.entity_id, "ASSET")
    a = q1(conn, """INSERT INTO fin_fixed_assets (legal_entity_id, asset_code, name, category_id, serial_number, location,
                    department_id, acquisition_date, depreciation_start, cost, residual_value, useful_life_months,
                    opening_accumulated_depreciation, is_opening, notes, created_by, source_line)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING *""",
           (ctx.entity_id, number, data["name"], cat["id"], data.get("serial_number"), data.get("location"),
            data.get("department_id"), acquired, dep_start, cost, residual, life, opening_acc, funding == "OPENING",
            data.get("notes"), ctx.actor_id, data.get("source_line")))
    if funding not in ("OPENING", "POSTED"):
        if funding == "BANK":
            credit_acct = bank_account(conn, ctx.entity_id, data["bank_account_id"])["gl_account_id"]
        elif funding == "CLEARING":
            credit_acct = data["credit_account_id"]
        else:
            raise invalid("Funding must be BANK, CLEARING or OPENING")
        j = posting.post_system(conn, ctx, event_type="ASSET_ACQUIRED", journal_date=acquired, lines=[
            {"account_id": cat["asset_account_id"], "debit": cost, "description": data["name"]},
            {"account_id": credit_acct, "credit": cost, "description": f"Purchase of {data['name']}"}],
            description=f"Acquisition of asset {number} {data['name']}", source_type="FIXED_ASSET", source_id=a["id"],
            source_ref=number)
        ex(conn, "UPDATE fin_fixed_assets SET acquisition_journal_id=%s WHERE id=%s", (j["id"], a["id"]))
    audit.record(conn, ctx, "ASSET_REGISTERED", "fixed_asset", a["id"], ref=number,
                 after={"cost": cost, "life_months": life, "funding": funding})
    return get_asset(conn, ctx.entity_id, a["id"])


def get_asset(conn, entity_id: str, asset_id: str) -> Dict[str, Any]:
    a = q1(conn, """SELECT f.*, c.name AS category_name FROM fin_fixed_assets f JOIN fin_asset_categories c ON c.id=f.category_id
                    WHERE f.id=%s AND f.legal_entity_id=%s""", (asset_id, entity_id))
    if not a:
        raise not_found("Asset", asset_id)
    acc = accumulated(conn, asset_id)
    a["accumulated_depreciation"] = acc
    a["net_book_value"] = money(a["cost"]) - acc
    a["monthly_charge"] = monthly_charge(a, acc) if a["status"] == "ACTIVE" else ZERO
    a["depreciation"] = q(conn, """SELECT r.run_number, p.name AS period, l.amount FROM fin_depreciation_lines l
                                   JOIN fin_depreciation_runs r ON r.id=l.run_id JOIN fin_periods p ON p.id=r.period_id
                                   WHERE l.asset_id=%s ORDER BY p.start_date""", (asset_id,))
    return a


def list_assets(conn, entity_id: str) -> List[Dict[str, Any]]:
    rows = q(conn, """SELECT f.*, c.name AS category_name,
                             f.opening_accumulated_depreciation + COALESCE((SELECT SUM(amount) FROM fin_depreciation_lines l
                                                                           WHERE l.asset_id=f.id),0) AS accumulated_depreciation
                      FROM fin_fixed_assets f JOIN fin_asset_categories c ON c.id=f.category_id
                      WHERE f.legal_entity_id=%s ORDER BY f.asset_code""", (entity_id,))
    for r in rows:
        r["net_book_value"] = money(r["cost"]) - money(r["accumulated_depreciation"])
    return rows


def preview_depreciation(conn, entity_id: str, period_id: str) -> Dict[str, Any]:
    p = q1(conn, "SELECT * FROM fin_periods WHERE id=%s AND legal_entity_id=%s", (period_id, entity_id))
    if not p:
        raise not_found("Period", period_id)
    lines = []
    for a in q(conn, """SELECT f.*, c.accum_dep_account_id, c.dep_expense_account_id, c.depreciable
                        FROM fin_fixed_assets f JOIN fin_asset_categories c ON c.id=f.category_id
                        WHERE f.legal_entity_id=%s AND f.status='ACTIVE' AND f.depreciation_start <= %s""",
                     (entity_id, p["end_date"])):
        if not a["depreciable"]:
            continue
        charge = monthly_charge(a, accumulated(conn, str(a["id"])))
        if charge > 0:
            lines.append({"asset_id": str(a["id"]), "asset_code": a["asset_code"], "name": a["name"], "amount": charge,
                          "expense_account_id": str(a["dep_expense_account_id"]),
                          "accum_account_id": str(a["accum_dep_account_id"])})
    return {"period": p, "lines": lines, "total": sum((l["amount"] for l in lines), ZERO),
            "already_run": bool(q1(conn, "SELECT 1 FROM fin_depreciation_runs WHERE period_id=%s", (period_id,)))}


def run_depreciation(conn, ctx, period_id: str) -> Dict[str, Any]:
    ctx.require("assets.depreciation.run")
    pv = preview_depreciation(conn, ctx.entity_id, period_id)
    if pv["already_run"]:
        raise FinError("TRANSACTION_ALREADY_POSTED", f"Depreciation for {pv['period']['name']} has already been posted")
    require_open(conn, ctx.entity_id, pv["period"]["end_date"])
    if not pv["lines"]:
        raise invalid("Nothing to depreciate in this period")
    number = next_number(conn, ctx.entity_id, "DEPRECIATION")
    run = q1(conn, """INSERT INTO fin_depreciation_runs (legal_entity_id, period_id, run_number, total, created_by)
                      VALUES (%s,%s,%s,%s,%s) RETURNING *""", (ctx.entity_id, period_id, number, pv["total"], ctx.actor_id))
    jl = []
    for l in pv["lines"]:
        ex(conn, "INSERT INTO fin_depreciation_lines (run_id, asset_id, amount) VALUES (%s,%s,%s)", (run["id"], l["asset_id"], l["amount"]))
        jl += [{"account_id": l["expense_account_id"], "debit": l["amount"], "description": f"Depreciation {l['asset_code']} {l['name']}"},
               {"account_id": l["accum_account_id"], "credit": l["amount"], "description": f"Depreciation {l['asset_code']}"}]
    j = posting.post_system(conn, ctx, event_type="DEPRECIATION_POSTED", journal_date=pv["period"]["end_date"], lines=jl,
                            description=f"Depreciation {pv['period']['name']} ({len(pv['lines'])} assets)",
                            source_type="DEPRECIATION_RUN", source_id=run["id"], source_ref=number)
    ex(conn, "UPDATE fin_depreciation_runs SET journal_id=%s WHERE id=%s", (j["id"], run["id"]))
    for l in pv["lines"]:
        a = q1(conn, "SELECT * FROM fin_fixed_assets WHERE id=%s", (l["asset_id"],))
        if monthly_charge(a, accumulated(conn, l["asset_id"])) == 0:
            ex(conn, "UPDATE fin_fixed_assets SET status='FULLY_DEPRECIATED' WHERE id=%s", (l["asset_id"],))
    audit.record(conn, ctx, "DEPRECIATION_POSTED", "depreciation_run", run["id"], ref=number,
                 metadata={"period": pv["period"]["name"], "total": str(pv["total"])})
    return {**run, "journal_number": j["journal_number"], "lines": pv["lines"]}


def dispose_asset(conn, ctx, asset_id: str, data: Dict[str, Any]) -> Dict[str, Any]:
    ctx.require("assets.asset.dispose")
    a = q1(conn, """SELECT f.*, c.asset_account_id, c.accum_dep_account_id FROM fin_fixed_assets f
                    JOIN fin_asset_categories c ON c.id=f.category_id WHERE f.id=%s AND f.legal_entity_id=%s FOR UPDATE""",
           (asset_id, ctx.entity_id))
    if not a:
        raise not_found("Asset", asset_id)
    if a["status"] == "DISPOSED":
        raise FinError("INVALID_STATE_TRANSITION", "Asset already disposed")
    on = data["disposal_date"]
    proceeds = money(data.get("proceeds"))
    acc = accumulated(conn, asset_id)
    nbv = money(a["cost"]) - acc
    gain = proceeds - nbv
    gl_acct = q1(conn, "SELECT disposal_account_id FROM fin_asset_categories WHERE id=%s", (a["category_id"],))["disposal_account_id"]
    if not gl_acct:
        from src.fin import rules
        gl_acct = rules.account(conn, ctx.entity_id, "ASSET_DISPOSAL")["id"]
    jl = [{"account_id": a["asset_account_id"], "credit": money(a["cost"]), "description": f"Dispose {a['asset_code']}"}]
    if acc > 0:
        jl.append({"account_id": a["accum_dep_account_id"], "debit": acc, "description": "Clear accumulated depreciation"})
    if proceeds > 0:
        jl.append({"account_id": bank_account(conn, ctx.entity_id, data["bank_account_id"])["gl_account_id"], "debit": proceeds,
                   "description": f"Proceeds from {a['name']}"})
    if gain > 0:
        jl.append({"account_id": gl_acct, "credit": gain, "description": "Gain on disposal"})
    elif gain < 0:
        jl.append({"account_id": gl_acct, "debit": -gain, "description": "Loss on disposal"})
    j = posting.post_system(conn, ctx, event_type="ASSET_DISPOSED", journal_date=on, lines=jl,
                            description=f"Disposal of {a['asset_code']} {a['name']}", source_type="FIXED_ASSET_DISPOSAL",
                            source_id=asset_id, source_ref=a["asset_code"])
    ex(conn, """UPDATE fin_fixed_assets SET status='DISPOSED', disposal_date=%s, disposal_proceeds=%s, disposal_journal_id=%s
                WHERE id=%s""", (on, proceeds, j["id"], asset_id))
    audit.record(conn, ctx, "ASSET_DISPOSED", "fixed_asset", asset_id, ref=a["asset_code"],
                 metadata={"proceeds": str(proceeds), "nbv": str(nbv), "gain_loss": str(gain)})
    return get_asset(conn, ctx.entity_id, asset_id)


# ---------------------------------------------------------------------------
# Assets in the books (client meeting 7 Oct: "when did we buy it, what do we have")
# ---------------------------------------------------------------------------

def asset_history(conn, entity_id: str, as_of: dt.date) -> Dict[str, Any]:
    """Every fixed-asset account as the ledger has it (the Sage years and ACE Books): cost,
    accumulated depreciation and net book value at `as_of`, and every purchase, disposal and
    depreciation charge with its date, supplier and description. Purchases show whether they are
    in the depreciation register yet."""
    from src.fin import books_ledger
    e = entity_id
    start = books_ledger.history_start(conn, e) or dt.date(2017, 1, 1)
    bal = books_ledger.balances(conn, e, as_of)
    cats = {str(c["asset_account_id"]): c for c in q(conn, """SELECT c.*, d.code AS accum_code FROM fin_asset_categories c
                                                              LEFT JOIN fin_accounts d ON d.id=c.accum_dep_account_id
                                                              WHERE c.legal_entity_id=%s AND c.status='ACTIVE'""", (e,))}
    registered = {r["source_line"]: r for r in q(conn, """SELECT id::text AS id, asset_code, source_line FROM fin_fixed_assets
                                                         WHERE legal_entity_id=%s AND source_line IS NOT NULL""", (e,))}
    out = []
    for a in q(conn, """SELECT id::text AS id, code, name FROM fin_accounts WHERE legal_entity_id=%s AND subtype='FIXED_ASSET'
                        ORDER BY code""", (e,)):
        cat = cats.get(a["id"])
        lines = [l for l in books_ledger.lines(conn, e, a["code"], start, as_of) if money(l["debit"]) or money(l["credit"])]
        cost = bal.get(a["code"], ZERO)
        if not lines and not cost:
            continue
        acc_lines, accum = [], ZERO
        if cat and cat.get("accum_code"):
            accum = -bal.get(cat["accum_code"], ZERO)
            acc_lines = [l for l in books_ledger.lines(conn, e, cat["accum_code"], start, as_of) if money(l["debit"]) or money(l["credit"])]
        purchases, disposals = [], []
        for l in lines:
            key = f"sage:{l['sage_line_id']}" if l["source"] == "sage" else f"ace:{l.get('line_id')}"
            desc = (l["description"] or "").strip()
            row = {"date": l["date"], "reference": l["reference"], "jrnl": l["jrnl"], "description": desc,
                   "amount": money(l["debit"]) - money(l["credit"]), "source": l["source"], "source_line": key,
                   "journal_id": l.get("journal_id"),
                   "brought_forward": "closing" in desc.lower() and "trial balance" in desc.lower()}
            if money(l["debit"]) > 0:
                reg = registered.get(key)
                row["registered"] = {"id": reg["id"], "asset_code": reg["asset_code"]} if reg else None
                purchases.append(row)
            else:
                disposals.append(row)
        out.append({"account_id": a["id"], "code": a["code"], "name": a["name"], "category_id": str(cat["id"]) if cat else None,
                    "category": cat["name"] if cat else None, "depreciable": bool(cat and cat["depreciable"]),
                    "default_life_months": cat["default_life_months"] if cat else None,
                    "cost": cost, "accumulated_depreciation": accum, "net_book_value": cost - accum,
                    "purchases": sorted(purchases, key=lambda r: r["date"], reverse=True),
                    "disposals": sorted(disposals, key=lambda r: r["date"], reverse=True),
                    "depreciation": [{"date": l["date"], "description": l["description"], "reference": l["reference"],
                                      "amount": money(l["credit"]) - money(l["debit"]), "source": l["source"],
                                      "journal_id": l.get("journal_id"), "jrnl": l["jrnl"]}
                                     for l in sorted(acc_lines, key=lambda r: r["date"], reverse=True)]})

    def tot(k):
        return sum((money(x[k]) for x in out), ZERO)

    return {"as_of": as_of, "accounts": out, "cost": tot("cost"), "accumulated_depreciation": tot("accumulated_depreciation"),
            "net_book_value": tot("net_book_value"),
            "register_count": q1(conn, "SELECT COUNT(*) n FROM fin_fixed_assets WHERE legal_entity_id=%s", (e,))["n"]}
