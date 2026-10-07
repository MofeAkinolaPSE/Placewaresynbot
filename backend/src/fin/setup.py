"""Organisation / legal entity bootstrap and entity settings."""
from __future__ import annotations

from typing import Any, Dict, Optional

from src.fin import audit
from src.fin.db import ex, q, q1
from src.fin.errors import FinError, invalid

SETTING_FIELDS = ("journal_approval_required", "allow_self_approval", "credit_limit_mode", "negative_stock_policy",
                  "aging_buckets", "cutover_date", "auto_post_frontdesk", "default_customer_code")


def ensure_entity(conn, *, org_code: str, org_name: str, entity_code: str, entity_name: str,
                  fiscal_year_start_month: int = 1, base_currency: str = "NGN") -> Dict[str, Any]:
    org = q1(conn, "SELECT * FROM fin_organizations WHERE code=%s", (org_code,))
    if not org:
        org = q1(conn, "INSERT INTO fin_organizations (code, name, base_currency) VALUES (%s,%s,%s) RETURNING *",
                 (org_code, org_name, base_currency))
    ent = q1(conn, "SELECT * FROM fin_legal_entities WHERE organization_id=%s AND code=%s", (org["id"], entity_code))
    if not ent:
        ent = q1(conn, """INSERT INTO fin_legal_entities (organization_id, code, name, base_currency, fiscal_year_start_month)
                          VALUES (%s,%s,%s,%s,%s) RETURNING *""",
                 (org["id"], entity_code, entity_name, base_currency, fiscal_year_start_month))
    ex(conn, "INSERT INTO fin_settings (legal_entity_id) VALUES (%s) ON CONFLICT DO NOTHING", (ent["id"],))
    return ent


def get_settings(conn, entity_id: str) -> Dict[str, Any]:
    s = q1(conn, "SELECT * FROM fin_settings WHERE legal_entity_id=%s", (entity_id,))
    if not s:
        ex(conn, "INSERT INTO fin_settings (legal_entity_id) VALUES (%s) ON CONFLICT DO NOTHING", (entity_id,))
        s = q1(conn, "SELECT * FROM fin_settings WHERE legal_entity_id=%s", (entity_id,))
    return s


def update_settings(conn, ctx, changes: Dict[str, Any]) -> Dict[str, Any]:
    ctx.require("finance.settings.edit")
    before = get_settings(conn, ctx.entity_id)
    fields = {k: v for k, v in changes.items() if k in SETTING_FIELDS}
    if "aging_buckets" in fields:
        b = [int(x) for x in fields["aging_buckets"]]
        if not b or b != sorted(set(b)) or b[0] <= 0:
            raise invalid("Aging buckets must be increasing positive day counts, e.g. 30, 60, 90, 120")
        fields["aging_buckets"] = b
    if not fields:
        return before
    sets = ", ".join(f"{k}=%s" for k in fields)
    row = q1(conn, f"UPDATE fin_settings SET {sets}, updated_by=%s, updated_at=now() WHERE legal_entity_id=%s RETURNING *",
             list(fields.values()) + [ctx.actor_id, ctx.entity_id])
    audit.record(conn, ctx, "SETTINGS_UPDATED", "settings", ctx.entity_id,
                 before={k: before.get(k) for k in fields}, after=fields)
    return row


def list_mappings(conn, entity_id: str):
    return q(conn, """SELECT m.mapping_key, m.account_id, a.code, a.name, a.status, m.note, m.updated_at
                      FROM fin_account_mappings m JOIN fin_accounts a ON a.id = m.account_id
                      WHERE m.legal_entity_id=%s ORDER BY m.mapping_key""", (entity_id,))


def set_mapping(conn, ctx, key: str, account_id: str, note: Optional[str] = None) -> Dict[str, Any]:
    ctx.require("finance.settings.edit")
    acct = q1(conn, "SELECT * FROM fin_accounts WHERE id=%s AND legal_entity_id=%s", (account_id, ctx.entity_id))
    if not acct:
        raise FinError("RESOURCE_NOT_FOUND", "Account not found in this company")
    if acct["status"] != "ACTIVE" or not acct["is_postable"]:
        raise FinError("ACCOUNT_NOT_POSTABLE", f"{acct['code']} cannot receive postings")
    before = q1(conn, "SELECT account_id FROM fin_account_mappings WHERE legal_entity_id=%s AND mapping_key=%s",
                (ctx.entity_id, key))
    ex(conn, """INSERT INTO fin_account_mappings (legal_entity_id, mapping_key, account_id, note, updated_by)
                VALUES (%s,%s,%s,%s,%s)
                ON CONFLICT (legal_entity_id, mapping_key)
                DO UPDATE SET account_id=EXCLUDED.account_id, note=EXCLUDED.note, updated_by=EXCLUDED.updated_by,
                              updated_at=now()""", (ctx.entity_id, key, account_id, note, ctx.actor_id))
    audit.record(conn, ctx, "POSTING_RULE_MAPPED", "account_mapping", key,
                 before={"account_id": before["account_id"]} if before else None,
                 after={"account_id": account_id, "account": acct["code"]})
    return {"mapping_key": key, "account_id": account_id, "code": acct["code"], "name": acct["name"]}


# The client's printed invoice (from their Sage invoice form) - editable in Setup.
DEFAULT_INVOICE_LAYOUT = {
    "company_name": "PLACEWARE NIGERIA LIMITED",
    "address_lines": ["72, Aina Street, Ojodu, Lagos"],
    "phones": ["08023246113", "08127541803"],
    "email": "placewarenig@hotmail.com",
    "website": "www.placewarenigeria.com",
    "footer_left": "Goods received in good condition with cold chain maintained not returnable",
    "payment_note": "All Payments Should be made by cheque or transfer to:",
    "bank_lines": ["PLACEWARE NIG. LTD.", "Fidelity Bank Account No: 5620012346", "Cash Payment is not allowed."],
    "default_shipping_method": "Hand Delivery",
}


def invoice_layout(conn, entity_id: str) -> Dict[str, Any]:
    s = get_settings(conn, entity_id)
    return {**DEFAULT_INVOICE_LAYOUT, **(s.get("invoice_layout") or {})}


def save_invoice_layout(conn, ctx, layout: Dict[str, Any]) -> Dict[str, Any]:
    from src.fin.db import jsonb
    ctx.require("finance.settings.edit")
    clean = {k: v for k, v in layout.items() if k in DEFAULT_INVOICE_LAYOUT}
    ex(conn, "UPDATE fin_settings SET invoice_layout=%s, updated_by=%s, updated_at=now() WHERE legal_entity_id=%s",
       (jsonb(clean), ctx.actor_id, ctx.entity_id))
    audit.record(conn, ctx, "INVOICE_LAYOUT_UPDATED", "settings", ctx.entity_id, after=clean)
    return invoice_layout(conn, ctx.entity_id)
