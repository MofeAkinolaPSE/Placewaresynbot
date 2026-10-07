"""Chart of accounts.

The client can add new heads of income/expense/stock at any time (meeting 2)
without damaging the structure: type and subtype must agree, codes are unique
per entity, and an account with history is deactivated, never deleted.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from src.fin import audit
from src.fin.db import q, q1
from src.fin.errors import FinError, invalid, not_found

SUBTYPE_TYPE = {
    "CASH": "ASSET", "RECEIVABLE": "ASSET", "INVENTORY": "ASSET", "OTHER_CURRENT_ASSET": "ASSET",
    "FIXED_ASSET": "ASSET", "ACCUMULATED_DEPRECIATION": "ASSET", "OTHER_ASSET": "ASSET",
    "PAYABLE": "LIABILITY", "OTHER_CURRENT_LIABILITY": "LIABILITY", "LONG_TERM_LIABILITY": "LIABILITY",
    "EQUITY": "EQUITY", "RETAINED_EARNINGS": "EQUITY", "EQUITY_CLOSING": "EQUITY",
    "SALES": "REVENUE", "OTHER_INCOME": "REVENUE",
    "COST_OF_SALES": "EXPENSE", "OPERATING_EXPENSE": "EXPENSE", "OTHER_EXPENSE": "EXPENSE",
}

# Contra accounts carry the opposite of their type's usual balance.
CONTRA_CREDIT = {"ACCUMULATED_DEPRECIATION"}


def default_normal_balance(subtype: str) -> str:
    if subtype in CONTRA_CREDIT:
        return "CREDIT"
    return "DEBIT" if SUBTYPE_TYPE[subtype] in ("ASSET", "EXPENSE") else "CREDIT"


def list_accounts(conn, entity_id: str, *, search: Optional[str] = None, account_type: Optional[str] = None,
                  include_inactive: bool = True) -> List[Dict[str, Any]]:
    where, params = ["a.legal_entity_id = %s"], [entity_id]
    if search:
        where.append("(a.code ILIKE %s OR a.name ILIKE %s)")
        params += [f"%{search}%", f"%{search}%"]
    if account_type:
        where.append("a.account_type = %s")
        params.append(account_type)
    if not include_inactive:
        where.append("a.status = 'ACTIVE'")
    return q(conn, f"""
        SELECT a.*, p.code AS parent_code,
               COALESCE(b.debit,0) AS total_debit, COALESCE(b.credit,0) AS total_credit,
               COALESCE(b.debit,0) - COALESCE(b.credit,0) AS balance,
               COALESCE(b.n,0) AS posting_count
        FROM fin_accounts a
        LEFT JOIN fin_accounts p ON p.id = a.parent_id
        LEFT JOIN (
            SELECT account_id, SUM(debit) debit, SUM(credit) credit, COUNT(*) n
            FROM fin_v_general_ledger WHERE legal_entity_id = %s GROUP BY account_id
        ) b ON b.account_id = a.id
        WHERE {' AND '.join(where)}
        ORDER BY a.code
    """, [entity_id] + params)


def get_account(conn, entity_id: str, account_id: str) -> Dict[str, Any]:
    a = q1(conn, "SELECT * FROM fin_accounts WHERE id=%s AND legal_entity_id=%s", (account_id, entity_id))
    if not a:
        raise not_found("Account", account_id)
    return a


def by_code(conn, entity_id: str, code: str) -> Dict[str, Any]:
    a = q1(conn, "SELECT * FROM fin_accounts WHERE code=%s AND legal_entity_id=%s", (str(code).strip(), entity_id))
    if not a:
        raise not_found("Account", code)
    return a


def create_account(conn, ctx, data: Dict[str, Any]) -> Dict[str, Any]:
    ctx.require("accounting.account.create")
    code = str(data.get("code") or "").strip()
    name = str(data.get("name") or "").strip()
    subtype = str(data.get("subtype") or "").upper()
    if not code or not name:
        raise invalid("Account code and name are required")
    if subtype not in SUBTYPE_TYPE:
        raise invalid(f"Unknown account subtype {subtype!r}", allowed=sorted(SUBTYPE_TYPE))
    account_type = SUBTYPE_TYPE[subtype]
    if data.get("account_type") and data["account_type"].upper() != account_type:
        raise invalid(f"Subtype {subtype} belongs to {account_type}, not {data['account_type']}")
    normal = (data.get("normal_balance") or default_normal_balance(subtype)).upper()
    if q1(conn, "SELECT 1 FROM fin_accounts WHERE legal_entity_id=%s AND code=%s", (ctx.entity_id, code)):
        raise FinError("DUPLICATE_RESOURCE", f"Account code {code} already exists")
    parent_id = data.get("parent_id")
    if parent_id:
        parent = get_account(conn, ctx.entity_id, parent_id)
        if parent["is_postable"]:
            raise invalid("A parent must be a header (non-postable) account")
    row = q1(conn, """
        INSERT INTO fin_accounts (legal_entity_id, code, name, account_type, subtype, normal_balance, parent_id,
                                  is_postable, is_control, description, created_by)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING *
    """, (ctx.entity_id, code, name, account_type, subtype, normal, parent_id,
          bool(data.get("is_postable", True)), bool(data.get("is_control", False)),
          data.get("description"), ctx.actor_id))
    audit.record(conn, ctx, "ACCOUNT_CREATED", "account", row["id"], ref=f"{code} {name}", after=row)
    return row


def update_account(conn, ctx, account_id: str, data: Dict[str, Any]) -> Dict[str, Any]:
    ctx.require("accounting.account.edit")
    before = get_account(conn, ctx.entity_id, account_id)
    has_history = q1(conn, "SELECT 1 FROM fin_journal_lines WHERE account_id=%s LIMIT 1", (account_id,))
    changes: Dict[str, Any] = {}
    for k in ("name", "description", "parent_id", "is_control"):
        if k in data and data[k] != before.get(k):
            changes[k] = data[k]
    if "subtype" in data and data["subtype"] != before["subtype"]:
        st = data["subtype"].upper()
        if st not in SUBTYPE_TYPE:
            raise invalid(f"Unknown subtype {st}")
        # Moving between subtypes of the same type (e.g. Sales -> Other income) only
        # changes statement presentation, so it is allowed with history; changing
        # the type itself would rewrite what past balances mean.
        if has_history and SUBTYPE_TYPE[st] != before["account_type"]:
            raise FinError("INVALID_STATE_TRANSITION",
                           "This account has postings; it cannot move to a different account type. Create a new account and reclassify by journal.")
        changes.update(subtype=st, account_type=SUBTYPE_TYPE[st], normal_balance=default_normal_balance(st))
    if "is_postable" in data and bool(data["is_postable"]) != before["is_postable"]:
        if has_history and not data["is_postable"]:
            raise FinError("INVALID_STATE_TRANSITION", "An account with postings cannot become a header account")
        changes["is_postable"] = bool(data["is_postable"])
    if not changes:
        return before
    sets = ", ".join(f"{k} = %s" for k in changes)
    row = q1(conn, f"UPDATE fin_accounts SET {sets}, updated_at = now() WHERE id=%s RETURNING *",
             list(changes.values()) + [account_id])
    audit.record(conn, ctx, "ACCOUNT_UPDATED", "account", account_id, ref=row["code"],
                 before={k: before.get(k) for k in changes}, after=changes)
    return row


def set_status(conn, ctx, account_id: str, active: bool, reason: Optional[str] = None) -> Dict[str, Any]:
    ctx.require("accounting.account.edit")
    before = get_account(conn, ctx.entity_id, account_id)
    if not active:
        mapped = q(conn, "SELECT mapping_key FROM fin_account_mappings WHERE account_id=%s", (account_id,))
        if mapped:
            raise FinError("INVALID_STATE_TRANSITION",
                           "This account is used by posting rules; remap them before deactivating it",
                           {"mappings": [m["mapping_key"] for m in mapped]})
    status = "ACTIVE" if active else "INACTIVE"
    row = q1(conn, "UPDATE fin_accounts SET status=%s, updated_at=now() WHERE id=%s RETURNING *", (status, account_id))
    audit.record(conn, ctx, "ACCOUNT_ACTIVATED" if active else "ACCOUNT_DEACTIVATED", "account", account_id,
                 ref=row["code"], before={"status": before["status"]}, after={"status": status}, reason=reason)
    return row


def mapped_account(conn, entity_id: str, key: str) -> Dict[str, Any]:
    """Resolve a posting-rule role (e.g. AR_CONTROL) to its configured account."""
    a = q1(conn, """SELECT a.* FROM fin_account_mappings m JOIN fin_accounts a ON a.id = m.account_id
                    WHERE m.legal_entity_id=%s AND m.mapping_key=%s""", (entity_id, key))
    if not a:
        raise FinError("MAPPING_MISSING", f"No account is mapped for {key}. Set it in Finance > Setup > Posting rules.",
                       {"mapping_key": key})
    return a


def optional_mapped(conn, entity_id: str, key: str) -> Optional[Dict[str, Any]]:
    try:
        return mapped_account(conn, entity_id, key)
    except FinError:
        return None
