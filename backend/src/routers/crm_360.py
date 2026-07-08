"""Customer 360 — live composite view of a customer across all data layers.

Combines:
  • customers            — profile, contact details, credit limit, terms
  • sage_ar_snapshot     — outstanding receivables, overdue position
  • sage_customer_sales_snapshot — lifetime sales / gross profit / margin
  • sage_invoice_lines_snapshot  — top purchased items (invoice_id = SOLD_<code>)
"""
import datetime
import logging
from fastapi import APIRouter, HTTPException, Request
from src.middleware import verify_jwt
import src.db as db

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

        # ── Receivables ────────────────────────────────────────────────────
        outstanding = 0.0
        overdue_amount = 0.0
        overdue_count = 0
        invoice_count = 0
        last_invoice_date = None
        if code:
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
        if code:
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
        if code:
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

        return {
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
        }
    except HTTPException:
        raise
    except Exception:
        log.exception('customer_360 failed for id=%s', customer_id)
        raise HTTPException(status_code=500, detail='Internal server error')
