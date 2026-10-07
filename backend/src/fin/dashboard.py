"""Finance Control Tower - figures come from the same ledger queries as the
reports (never a separate calculation), plus the exceptions that need a person."""
from __future__ import annotations

import datetime as dt
from typing import Any, Dict

from src.fin import controls, periods, reports
from src.fin.db import ZERO, money, q, q1


def control_tower(conn, entity_id: str, as_of: dt.date) -> Dict[str, Any]:
    month_start = as_of.replace(day=1)
    fy_start = reports._fy_start(conn, entity_id, as_of)
    mtd = reports.income_statement(conn, entity_id, month_start, as_of)
    ytd = reports.income_statement(conn, entity_id, fy_start, as_of)
    cash = q(conn, """SELECT b.id, b.name, b.kind, COALESCE(SUM(g.debit-g.credit),0) AS balance
                      FROM fin_bank_accounts b LEFT JOIN fin_v_general_ledger g ON g.account_id=b.gl_account_id AND g.journal_date<=%s
                      WHERE b.legal_entity_id=%s AND b.status='ACTIVE' GROUP BY b.id ORDER BY balance DESC""", (as_of, entity_id))
    ar = reports.aged_receivables(conn, entity_id, as_of)
    ap = reports.aged_payables(conn, entity_id, as_of)
    # Overdue is net of unapplied receipts / credits (open-item subledger, as in the ageing),
    # so it can never exceed the balance owed.
    overdue_ar = sum((money(i["open_amount"]) for i in reports.ar_open_items(conn, entity_id, as_of) if i["due_date"] < as_of), ZERO)
    overdue_ap = sum((money(i["open_amount"]) for i in reports.ap_open_items(conn, entity_id, as_of) if i["due_date"] < as_of), ZERO)
    inv_value = money(q1(conn, """SELECT COALESCE(SUM(total_cost),0) v FROM fin_inventory_transactions WHERE legal_entity_id=%s
                                  AND txn_type NOT IN ('LOAN_OUT','LOAN_RETURN')""", (entity_id,))["v"])
    trend = q(conn, """SELECT to_char(date_trunc('month', journal_date), 'YYYY-MM') AS month,
                              SUM(CASE WHEN subtype='SALES' THEN credit-debit ELSE 0 END) AS revenue,
                              SUM(CASE WHEN account_type='REVENUE' THEN credit-debit ELSE -(debit-credit) END) AS net_profit
                       FROM fin_v_general_ledger WHERE legal_entity_id=%s AND account_type IN ('REVENUE','EXPENSE')
                         AND journal_type NOT IN ('CLOSING','OPENING') AND journal_date > %s - interval '12 months'
                       GROUP BY 1 ORDER BY 1""", (entity_id, as_of))
    top_customers = [{"customer_id": r["customer_id"], "name": r["customer_name"], "balance": r["total"]} for r in ar["rows"][:5]]
    pending = {
        "journals_awaiting_approval": q1(conn, "SELECT COUNT(*) n FROM fin_journals WHERE legal_entity_id=%s AND status='SUBMITTED'", (entity_id,))["n"],
        "draft_journals": q1(conn, "SELECT COUNT(*) n FROM fin_journals WHERE legal_entity_id=%s AND status IN ('DRAFT','REJECTED')", (entity_id,))["n"],
        "draft_adjustments": q1(conn, "SELECT COUNT(*) n FROM fin_stock_adjustments WHERE legal_entity_id=%s AND status='DRAFT'", (entity_id,))["n"],
        "draft_invoices": q1(conn, "SELECT COUNT(*) n FROM fin_sales_invoices WHERE legal_entity_id=%s AND status='DRAFT'", (entity_id,))["n"],
        "failed_frontdesk_postings": (lambda d: len(d["failed"]) + len(d["not_posted"]))(controls._frontdesk(conn, entity_id, as_of)[2]),
        "open_recalls": q1(conn, "SELECT COUNT(*) n FROM fin_recalls WHERE legal_entity_id=%s AND status='OPEN'", (entity_id,))["n"],
        "open_stock_loans": q1(conn, "SELECT COUNT(*) n FROM fin_stock_loans WHERE legal_entity_id=%s AND status IN ('OPEN','PARTIALLY_RETURNED')", (entity_id,))["n"],
    }
    health = controls.run_checks(conn, entity_id, as_of)
    return {
        "as_of": as_of, "period": periods.current_period(conn, entity_id, as_of),
        "kpis": {
            "cash": sum((money(c["balance"]) for c in cash), ZERO),
            "receivables": ar["total"], "overdue_receivables": overdue_ar,
            "payables": ap["total"], "overdue_payables": overdue_ap,
            "inventory_value": inv_value,
            "revenue_mtd": mtd["revenue"], "revenue_ytd": ytd["revenue"],
            "gross_margin_ytd_pct": ytd["gross_margin_pct"], "net_profit_mtd": mtd["net_profit"],
            "net_profit_ytd": ytd["net_profit"],
        },
        "cash_accounts": cash, "ar_aging": {"buckets": ar["buckets"], "totals": ar["bucket_totals"]},
        "ap_aging": {"buckets": ap["buckets"], "totals": ap["bucket_totals"]},
        "trend": trend, "top_customers": top_customers, "pending": pending, "health": health,
        "health_failures": sum(1 for h in health if h["status"] == "FAIL"),
    }
