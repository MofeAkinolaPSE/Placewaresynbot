from fastapi import APIRouter, Request, HTTPException
from src.schemas.supplier import Supplier, SupplierDelivery
from src.middleware import verify_jwt, require_role
from src.db import audit_event, db
import statistics
import datetime as dt
import logging
from src.services.supplier_intel import compute_supplier_metrics

logger = logging.getLogger("suppliers")

router = APIRouter()


def _snapshot_row_to_supplier(row: dict) -> dict:
    """Translate a sage_vendors_snapshot row into the suppliers schema expected by the frontend."""
    return {
        "id": row.get("id"),
        "name": row.get("vendor_name") or "Unknown",
        "contact_name": row.get("contact_name"),
        "contact_email": row.get("email"),
        "phone": row.get("phone"),
        "address": row.get("address"),
        "payment_terms": row.get("payment_terms"),
        "tax_id": row.get("tax_id"),
        "bank_details": row.get("bank_details"),
        "current_balance": row.get("current_balance"),
        "status": row.get("status") or "active",
        "external_vendor_id": row.get("vendor_id"),
        "created_at": row.get("imported_at"),
    }


@router.get('/suppliers')
def list_suppliers(request: Request):
    """Return all suppliers from the suppliers table.

    Populated by the vendors CSV import (POST /sage/import/csv, file_type=vendors)
    which upserts on external_vendor_id.  Agent-owned metric columns
    (reliability_score, avg_delay_days, etc.) are written separately by SupplierAgent.
    """
    verify_jwt(request)
    try:
        resp = (
            db.table('suppliers')
            .select('*')
            .order('created_at', desc=True)
            .execute()
        )
        data = resp.data or []
    except Exception as exc:
        logger.error(f"list_suppliers: suppliers table query failed: {exc}")
        raise HTTPException(status_code=500, detail='Failed to load suppliers from DB')

    # Fallback to Silver view when live suppliers table is empty
    if not data:
        try:
            snap = db.table('v_vendors').select('*').limit(200).execute()
            for r in (snap.data or []):
                data.append(_snapshot_row_to_supplier(r))
        except Exception as exc:
            logger.warning(f"list_suppliers: v_vendors fallback failed: {exc}")

    try:
        actor = getattr(request.state, 'user', None)
        audit_event('list_suppliers', {'count': len(data)}, actor_id=(actor.get('sub') if actor else None), event_class='supplier', subject_type='suppliers')
    except Exception:
        pass
    return data


@router.post('/suppliers', status_code=201)
def create_supplier(request: Request, payload: Supplier):
    verify_jwt(request, required_role='admin')
    s = payload.dict()
    s['created_at'] = dt.datetime.utcnow().isoformat() + 'Z'
    try:
        resp = db.table('suppliers').insert(s).execute()
        created = resp.data[0] if resp.data else s
    except Exception:
        raise HTTPException(status_code=500, detail='Failed to create supplier')
    try:
        actor = getattr(request.state, 'user', None)
        audit_event('create_supplier', {'supplier': created.get('name')}, actor_id=(actor.get('sub') if actor else None), event_class='supplier', action='create', subject_type='supplier', subject_id=created.get('id') or created.get('name'))
    except Exception:
        pass
    return {'status': 'created', 'supplier': created}


@router.post('/suppliers/{supplier_name}/deliveries', status_code=201)
def record_delivery(request: Request, supplier_name: str, payload: SupplierDelivery):
    verify_jwt(request, required_role='ops')
    d = payload.dict()
    d['supplier_name'] = supplier_name
    d['created_at'] = dt.datetime.utcnow().isoformat() + 'Z'
    try:
        resp = db.table('supplier_deliveries').insert(d).execute()
        created = resp.data[0] if resp.data else d
    except Exception:
        raise HTTPException(status_code=500, detail='Failed to record supplier delivery')
    try:
        actor = getattr(request.state, 'user', None)
        audit_event('record_supplier_delivery', {'supplier': supplier_name, 'delivery_id': created.get('delivery_id') or created.get('id')}, actor_id=(actor.get('sub') if actor else None), event_class='supplier', action='delivery_recorded', subject_type='supplier_delivery', subject_id=created.get('delivery_id') or created.get('id'))
    except Exception:
        pass
    return {'status': 'recorded', 'delivery': created}


@router.get('/suppliers/{supplier_name}/metrics')
def supplier_metrics(request: Request, supplier_name: str):
    verify_jwt(request)
    try:
        resp = db.table('supplier_deliveries').select('*').eq('supplier_name', supplier_name).execute()
        deliveries = resp.data or []
    except Exception:
        raise HTTPException(status_code=500, detail='Failed to fetch deliveries')
    if not deliveries:
        raise HTTPException(status_code=404, detail='No deliveries found for supplier')
    # compute on-time rate
    on_time = [1 if d.get('on_time') else 0 for d in deliveries if d.get('on_time') is not None]
    on_time_rate = sum(on_time) / len(on_time) if on_time else None
    # avg delivery time if scheduled_at and delivered_at present
    deltas = []
    for d in deliveries:
        sa = d.get('scheduled_at')
        da = d.get('delivered_at')
        if sa and da:
            try:
                t1 = dt.datetime.fromisoformat(sa.replace('Z',''))
                t2 = dt.datetime.fromisoformat(da.replace('Z',''))
                deltas.append((t2 - t1).total_seconds() / 3600.0)
            except Exception:
                pass
    avg_delivery_time = statistics.mean(deltas) if deltas else None
    prices = [d.get('price') for d in deliveries if isinstance(d.get('price'), (int, float))]
    price_variance = statistics.pstdev(prices) if len(prices) > 1 else 0.0
    reliability_score = (on_time_rate or 0.0) * 100
    try:
        actor = getattr(request.state, 'user', None)
        audit_event('view_supplier_metrics', {'supplier': supplier_name}, actor_id=(actor.get('sub') if actor else None), event_class='supplier', action='metrics_view', subject_type='supplier', subject_id=supplier_name)
    except Exception:
        pass
    return {
        'supplier': supplier_name,
        'on_time_rate': on_time_rate,
        'avg_delivery_time_hours': avg_delivery_time,
        'price_variance_index': price_variance,
        'reliability_score': reliability_score,
        'deliveries_count': len(deliveries),
    }


@router.post('/suppliers/compute-metrics')
def compute_metrics_endpoint(request: Request):
    verify_jwt(request, required_role='admin')
    ok = compute_supplier_metrics()
    try:
        actor = getattr(request.state, 'user', None)
        audit_event('compute_supplier_metrics', {'status': 'started' if ok else 'failed'}, actor_id=(actor.get('sub') if actor else None), event_class='supplier', action='compute')
    except Exception:
        pass
    return {'status': 'ok' if ok else 'error'}
