"""Customer 360 — live composite view of a customer across all data layers.

Combines:
  • customers                 — profile, contact details, credit limit, terms
  • ACE Books (books_analytics, once live):
      v_ar_open               — outstanding receivables, overdue position (= ACE Books ageing)
      v_customer_sales_summary— lifetime sales / cost / gross margin (Sage history + ACE Books)
      v_sales_lines           — top purchased items, dated
  • Sage snapshots            — fallback before ACE Books is live
"""
import datetime
import logging
from fastapi import APIRouter, HTTPException, Request
from src.middleware import verify_jwt
import src.db as db
from src.services import books_analytics
from src.fin.readmodel import live as _books_live
from src.services.customer_reorder import get_customer_reorder_profile, get_reorder_priority_queue

log = logging.getLogger(__name__)
router = APIRouter(prefix='/crm', tags=['crm'])

# Standard trade terms fallback when the Sage export carries no due_date
# (kept in sync with sage_adapter service / agents_exec).
DEFAULT_AR_TERMS_DAYS = 30


def _parse_date(raw) -> datetime.date | None:
    if not raw:
        return None
    try:
        return datetime.date.fromisoformat(str(raw)[:10])
    except Exception:
        return None


@router.get('/customers/{customer_id}/360')
def customer_360(customer_id: int, request: Request):
    verify_jwt(request)
    try:
        cust_rows = (
            db.db.table('customers').select('*').eq('id', customer_id).limit(1).execute().data or []
        )
        if not cust_rows:
            raise HTTPException(status_code=404, detail='Customer not found')
        c = cust_rows[0]
        code = str(c.get('customer_code') or '').strip()
        cd = c.get('contact_details') or {}
        meta = c.get('metadata') or {}
        today = datetime.date.today()

        books = _books_live()
        # ── Receivables ────────────────────────────────────────────────────
        outstanding = 0.0
        overdue_amount = 0.0
        overdue_count = 0
        invoice_count = 0
        last_invoice_date = None
        if books:
            rec = books_analytics.customer_receivables(customer_id)
            outstanding, overdue_amount = rec['outstanding'], rec['overdue_amount']
            overdue_count, invoice_count = rec['overdue_count'], rec['invoice_count']
            last_invoice_date = rec['last_invoice_date']
        elif code:
            ar_rows = (
                db.db.table('sage_ar_snapshot')
                .select('amount,balance,due_date,date')
                .eq('customer_id', code)
                .gt('balance', 0)
                .limit(20000)
                .execute()
                .data
                or []
            )
            for r in ar_rows:
                bal = float(r.get('balance') or 0)
                outstanding += bal
                invoice_count += 1
                inv_date = _parse_date(r.get('date'))
                if inv_date and (last_invoice_date is None or inv_date > last_invoice_date):
                    last_invoice_date = inv_date
                due = _parse_date(r.get('due_date'))
                if due is None and inv_date:
                    due = inv_date + datetime.timedelta(days=DEFAULT_AR_TERMS_DAYS)
                if due and due < today:
                    overdue_count += 1
                    overdue_amount += bal

        credit_limit = float(c.get('credit_limit') or 0)
        credit_utilization_pct = (
            round(outstanding / credit_limit * 100, 1) if credit_limit > 0 else None
        )

        # ── Profitability (lifetime, from Sage sales history) ─────────────
        profitability = None
        if books:
            profitability = books_analytics.customer_profitability(customer_id)
        elif code:
            ps = (
                db.db.table('sage_customer_sales_snapshot')
                .select('amount,cost_of_sales,gross_profit,gross_margin')
                .eq('customer_id', code)
                .order('imported_at', desc=True)
                .limit(1)
                .execute()
                .data
                or []
            )
            if ps:
                p = ps[0]
                profitability = {
                    'sales': float(p.get('amount') or 0),
                    'cost_of_sales': float(p.get('cost_of_sales') or 0),
                    'gross_profit': float(p.get('gross_profit') or 0),
                    'gross_margin_pct': float(p.get('gross_margin') or 0),
                }

        # ── Top purchased items ────────────────────────────────────────────
        top_items = []
        if books:
            top_items = books_analytics.customer_top_items(customer_id)
        elif code:
            lines = (
                db.db.table('sage_invoice_lines_snapshot')
                .select('item_id,quantity,line_total,gross_profit')
                .eq('invoice_id', f'SOLD_{code}')
                .limit(5000)
                .execute()
                .data
                or []
            )
            agg: dict = {}
            for ln in lines:
                iid = str(ln.get('item_id') or '').strip()
                if not iid:
                    continue
                a = agg.setdefault(iid, {'item_id': iid, 'quantity': 0.0, 'amount': 0.0, 'gross_profit': 0.0})
                a['quantity'] += float(ln.get('quantity') or 0)
                a['amount'] += float(ln.get('line_total') or 0)
                a['gross_profit'] += float(ln.get('gross_profit') or 0)
            top_items = sorted(agg.values(), key=lambda x: x['amount'], reverse=True)[:8]
            for t in top_items:
                t['amount'] = round(t['amount'], 2)
                t['gross_profit'] = round(t['gross_profit'], 2)

        # ── Recent orders (Frontdesk) ───────────────────────────────────────
        # "Customer Context Engine" -- translates the RoyanHealth Patient
        # Context Engine pattern (one aggregated backend object, not many
        # separate frontend calls) onto this app's existing 360 read model.
        # Additive only -- does not change any of the 4 keys CRM.tsx's 360
        # dialog already reads. Requires migration 100
        # (frontdesk_walk_ins.customer_id); fails soft to [] otherwise.
        orders = []
        try:
            wi_rows = (
                db.db.table('frontdesk_walk_ins').select('id')
                .eq('customer_id', customer_id).limit(500).execute().data or []
            )
            walk_in_ids = [w['id'] for w in wi_rows]
            if walk_in_ids:
                orders = (
                    db.db.table('frontdesk_invoices')
                    .select('id,invoice_number,walk_in_id,status,total_amount,created_at')
                    .in_('walk_in_id', walk_in_ids)
                    .order('created_at', desc=True)
                    .limit(20)
                    .execute()
                    .data
                    or []
                )
        except Exception:
            log.exception('customer_360 orders lookup failed for id=%s', customer_id)
            orders = []

        # ── Invoices (ACE Books + Sage history), deals and CRM activity ──────
        # "Recent orders" above is Frontdesk requests only, so most customers showed nothing.
        invoices, deals, activity = [], [], []
        try:
            from src.fin.db import q as _q, tx as _tx
            with _tx() as conn:
                invoices = _q(conn, """SELECT source, invoice_id, date, due_date, amount, balance, status, ace_invoice_id::text AS ace_invoice_id
                                       FROM v_customer_invoices WHERE customer_pk=%s ORDER BY date DESC LIMIT 12""", (customer_id,))
                deals = _q(conn, """SELECT id, company_name, stage::text AS stage, expected_value, won_at, created_at FROM leads
                                    WHERE customer_id=%s AND stage::text <> 'archived' ORDER BY updated_at DESC LIMIT 10""", (customer_id,))
                activity = _q(conn, """SELECT i.interaction_type, i.summary, i.outcome, i.occurred_at FROM crm_interaction_log i
                                       LEFT JOIN leads l ON l.id=i.lead_id WHERE i.customer_id=%s OR l.customer_id=%s
                                       ORDER BY i.occurred_at DESC LIMIT 10""", (customer_id, customer_id))
        except Exception:
            log.exception('customer_360 invoices/deals lookup failed for id=%s', customer_id)

        return {
            'invoices': invoices,
            'deals': deals,
            'activity': activity,
            'customer': {
                'id': c.get('id'),
                'name': c.get('name'),
                'customer_code': code,
                'phone': cd.get('phone'),
                'email': cd.get('email'),
                'address': cd.get('address'),
                'city': cd.get('city'),
                'contact_person': cd.get('contact_person'),
                'terms': meta.get('terms'),
                'customer_since': meta.get('customer_since'),
                'client_type': c.get('client_type'),
                'facility_type': c.get('facility_type'),
                'credit_limit': credit_limit,
                'payment_terms_days': c.get('payment_terms_days'),
                'last_ordered_at': c.get('last_ordered_at'),
                'risk_score': float(c.get('risk_score') or 0),
            },
            'receivables': {
                'outstanding': round(outstanding, 2),
                'invoice_count': invoice_count,
                'overdue_count': overdue_count,
                'overdue_amount': round(overdue_amount, 2),
                'credit_utilization_pct': credit_utilization_pct,
                'last_invoice_date': last_invoice_date.isoformat() if last_invoice_date else None,
            },
            'profitability': profitability,
            'top_items': top_items,
            'orders': orders,
            'reorder_profile': get_customer_reorder_profile(code) if code else None,
        }
    except HTTPException:
        raise
    except Exception:
        log.exception('customer_360 failed for id=%s', customer_id)
        raise HTTPException(status_code=500, detail='Internal server error')


@router.get('/reorder-queue')
def reorder_queue(request: Request, limit: int = 50):
    """Priority queue of customers ranked by reorder urgency, computed from
    real dated AR ledger history. Same read-only gate as customer_360 --
    this is CRM data, not a new access tier.

    Deliberately NOT nested under /customers/ -- crm.py's
    GET /customers/{customer_id} (customer_id: int) is registered before
    this router in app.py, so /customers/reorder-queue would 422 trying to
    coerce "reorder-queue" to int before ever reaching this handler (the
    same path-shape collision crm.py's own /customers/search comment
    documents, just across router files instead of within one)."""
    verify_jwt(request)
    try:
        return {'data': get_reorder_priority_queue(limit=limit)}
    except Exception:
        log.exception('reorder_queue failed')
        raise HTTPException(status_code=500, detail='Internal server error')
