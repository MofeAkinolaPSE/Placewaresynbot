from fastapi import APIRouter, Request, HTTPException
from src.schemas.logistics import Rider, Delivery, Route
from src.middleware import verify_jwt, require_role
from src.db import audit_event, db
import datetime as dt
import uuid
import os
from src.services.routing_adapter import compute_route

router = APIRouter()


@router.post('/logistics/riders', status_code=201)
async def create_rider(request: Request, payload: Rider):
    verify_jwt(request, required_role='ops')
    r = payload.dict()
    r['id'] = str(uuid.uuid4())
    r['active'] = True
    r['created_at'] = dt.datetime.utcnow().isoformat() + 'Z'
    try:
        resp = db.table('riders').insert(r).execute()
        created = resp.data[0] if resp.data else r
    except Exception:
        raise HTTPException(status_code=500, detail='Failed to create rider')
    try:
        actor = getattr(request.state, 'user', None)
        audit_event('create_rider', {'rider_id': created.get('id')}, actor_id=(actor.get('sub') if actor else None), event_class='logistics', action='create', subject_type='rider', subject_id=created.get('id'))
    except Exception:
        pass
    return {'status': 'created', 'rider': created}


@router.post('/logistics/deliveries', status_code=201)
async def create_delivery(request: Request, payload: Delivery):
    verify_jwt(request, required_role='ops')
    d = payload.dict()
    d['id'] = str(uuid.uuid4())
    d['status'] = 'unassigned'
    d['created_at'] = dt.datetime.utcnow().isoformat() + 'Z'
    try:
        resp = db.table('deliveries').insert(d).execute()
        created = resp.data[0] if resp.data else d
    except Exception:
        raise HTTPException(status_code=500, detail='Failed to create delivery')
    try:
        actor = getattr(request.state, 'user', None)
        audit_event('create_delivery', {'delivery_id': created.get('id')}, actor_id=(actor.get('sub') if actor else None), event_class='logistics', action='create', subject_type='delivery', subject_id=created.get('id'))
    except Exception:
        pass
    return {'status': 'created', 'delivery': created}


@router.post('/logistics/assign')
async def assign_routes(request: Request):
    # simple round-robin assigner
    verify_jwt(request, required_role='ops')
    try:
        resp = db.table('deliveries').select('*').eq('status', 'unassigned').execute()
        deliveries = resp.data or []
        resp2 = db.table('riders').select('*').eq('active', True).execute()
        riders = resp2.data or []
    except Exception:
        raise HTTPException(status_code=500, detail='Failed to fetch deliveries or riders')
    if not riders:
        raise HTTPException(status_code=400, detail='No active riders')
    idx = 0
    assigned_count = 0
    for d in deliveries:
        rider = riders[idx % len(riders)]
        assigned_rider = rider.get('id')
        try:
            db.table('deliveries').update({'assigned_rider': assigned_rider, 'status': 'assigned'}).eq('id', d.get('id')).execute()
        except Exception:
            idx += 1
            continue
        try:
            rresp = db.table('routes').select('*').eq('rider_id', assigned_rider).execute()
            routes = rresp.data or []
            if routes:
                route = routes[0]
                deliveries_list = route.get('deliveries', [])
                deliveries_list.append(d.get('id'))
                db.table('routes').update({'deliveries': deliveries_list}).eq('id', route.get('id')).execute()
            else:
                route = {'id': str(uuid.uuid4()), 'rider_id': assigned_rider, 'deliveries': [d.get('id')], 'route_meta': {}, 'created_at': dt.datetime.utcnow().isoformat() + 'Z'}
                db.table('routes').insert(route).execute()
        except Exception:
            pass
        idx += 1
        assigned_count += 1
    try:
        actor = getattr(request.state, 'user', None)
        audit_event('assign_routes', {'assigned_count': assigned_count}, actor_id=(actor.get('sub') if actor else None), event_class='logistics', action='assign')
    except Exception:
        pass
    return {'assigned_count': assigned_count}


@router.get('/logistics/riders/{rider_id}/route')
async def get_rider_route(request: Request, rider_id: str):
    verify_jwt(request)
    try:
        rresp = db.table('routes').select('*').eq('rider_id', rider_id).execute()
        routes = rresp.data or []
        route = routes[0] if routes else None
    except Exception:
        raise HTTPException(status_code=500, detail='Failed to fetch routes')
    if not route:
        return {'deliveries': []}
    try:
        dresp = db.table('deliveries').select('*').in_('id', route.get('deliveries', [])).execute()
        items = dresp.data or []
    except Exception:
        items = []
    try:
        actor = getattr(request.state, 'user', None)
        audit_event('view_route', {'rider_id': rider_id}, actor_id=(actor.get('sub') if actor else None), event_class='logistics', action='view_route', subject_type='rider', subject_id=rider_id)
    except Exception:
        pass
    return {'route': route, 'deliveries': items}


@router.post('/logistics/deliveries/{delivery_id}/status')
async def update_delivery_status(request: Request, delivery_id: str, payload: dict):
    verify_jwt(request, required_role='ops')
    try:
        update = {'status': payload.get('status')}
        update['last_update'] = dt.datetime.utcnow().isoformat() + 'Z'
        resp = db.table('deliveries').update(update).eq('id', delivery_id).execute()
        updated = resp.data[0] if resp.data else None
    except Exception:
        raise HTTPException(status_code=500, detail='Failed to update delivery')
    if not updated:
        raise HTTPException(status_code=404, detail='Delivery not found')
    try:
        from src.routers.inventory_module import _append_ledger_event
        ev = {'department': 'logistics', 'event_type': 'DeliveryStatus', 'payload': {'delivery_id': delivery_id, 'status': updated.get('status')}, 'created_by': None}
        _append_ledger_event(ev)
    except Exception:
        pass
    try:
        actor = getattr(request.state, 'user', None)
        audit_event('update_delivery_status', {'delivery_id': delivery_id, 'status': updated.get('status')}, actor_id=(actor.get('sub') if actor else None), event_class='logistics', action='update_status', subject_type='delivery', subject_id=delivery_id)
    except Exception:
        pass
    return {'status': 'updated', 'delivery_id': delivery_id}


@router.post('/logistics/compute-route')
async def compute_route_endpoint(request: Request, payload: dict):
    """Compute a route (uses Google Maps when API key available; otherwise returns a mock route)."""
    verify_jwt(request)
    origin = payload.get('origin')
    destinations = payload.get('destinations') or []
    optimize = bool(payload.get('optimize', False))
    if not origin:
        raise HTTPException(status_code=400, detail='origin is required')
    api_key = os.getenv('GOOGLE_MAPS_API_KEY', None)
    route = compute_route(origin, destinations, api_key=api_key, optimize=optimize)
    try:
        actor = getattr(request.state, 'user', None)
        audit_event('compute_route', {'origin': origin, 'destinations_count': len(destinations), 'provider': route.get('provider')}, actor_id=(actor.get('sub') if actor else None), event_class='logistics', action='compute_route')
    except Exception:
        pass
    return route
