from fastapi import APIRouter, Depends
from typing import Any

import src.db as db

router = APIRouter(prefix="/ui", tags=["ui"])


def auth_stub():
    # Placeholder auth dependency — in real app use JWT verification
    return True


@router.get('/metrics/summary')
def metrics_summary(_=Depends(auth_stub)) -> Any:
    """Return a small set of metrics for UI cards."""
    try:
        res = db.db.table('placeware_kpis').select('*').execute()
        kpis = res.data or []
    except Exception:
        kpis = []

    # Build a dictionary of common cards
    out = {
        'total_leads': next((int(x['value']) for x in kpis if x.get('metric') == 'leads.total'), 0),
        'pipeline_value': next((float(x['value']) for x in kpis if x.get('metric') == 'pipeline.value'), 0.0),
        'forecast': next((float(x['value']) for x in kpis if x.get('metric') == 'financial.forecast'), 0.0),
        'pending_routes': next((int(x['value']) for x in kpis if x.get('metric') == 'logistics.pending_routes'), 0),
    }
    return out
