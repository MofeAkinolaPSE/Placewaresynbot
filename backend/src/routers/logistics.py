from fastapi import APIRouter, Request, HTTPException
from fastapi.responses import StreamingResponse
from src.schemas.logistics import Rider, Delivery, Route
from src.middleware import verify_jwt, require_role
from src.db import audit_event, db
import datetime as dt
import uuid
import os
import asyncio
import json
import math
from src.services.routing_adapter import compute_route

router = APIRouter()

# ---------------------------------------------------------------------------
# Geo helpers
# ---------------------------------------------------------------------------

def _haversine_m(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """Return distance in metres between two WGS-84 coordinates."""
    R = 6_371_000.0
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlam = math.radians(lng2 - lng1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlam / 2) ** 2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


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


# =============================================================================
# REAL-TIME TRACKING ENDPOINTS  (Migration 084)
# =============================================================================

# ---------------------------------------------------------------------------
# Start a delivery — generates tracking_token and returns the rider PWA URL
# ---------------------------------------------------------------------------
@router.post('/logistics/deliveries/{delivery_id}/start')
async def start_delivery(request: Request, delivery_id: str):
    """Mark delivery in_transit, mint a tracking token, return the PWA URL."""
    verify_jwt(request, required_role='ops')
    token = str(uuid.uuid4())
    now = dt.datetime.utcnow().isoformat() + 'Z'
    try:
        resp = db.table('deliveries').update({
            'status': 'in_transit',
            'tracking_token': token,
            'last_update': now,
        }).eq('id', delivery_id).execute()
        updated = resp.data[0] if resp.data else None
    except Exception:
        raise HTTPException(status_code=500, detail='Failed to start delivery')
    if not updated:
        raise HTTPException(status_code=404, detail='Delivery not found')
    try:
        actor = getattr(request.state, 'user', None)
        audit_event('start_delivery', {'delivery_id': delivery_id}, actor_id=(actor.get('sub') if actor else None),
                    event_class='logistics', action='start', subject_type='delivery', subject_id=delivery_id)
    except Exception:
        pass
    base_url = os.getenv('FRONTEND_URL', 'http://localhost:5173')
    return {
        'status': 'in_transit',
        'tracking_token': token,
        'tracking_url': f"{base_url}/rider-track/{token}",
        'delivery': updated,
    }


# ---------------------------------------------------------------------------
# Rider PWA: look up delivery info by token (no JWT — token IS the credential)
# ---------------------------------------------------------------------------
@router.get('/logistics/track/{token}')
async def get_delivery_by_token(token: str):
    """Public endpoint — rider page fetches delivery details using its token."""
    try:
        resp = db.table('deliveries').select('*').eq('tracking_token', token).execute()
        rows = resp.data or []
    except Exception:
        raise HTTPException(status_code=500, detail='Lookup failed')
    if not rows:
        raise HTTPException(status_code=404, detail='Invalid or expired tracking token')
    d = rows[0]
    if d.get('status') not in ('assigned', 'in_transit'):
        raise HTTPException(status_code=410, detail='Delivery is no longer active')
    return {'delivery': d}


# ---------------------------------------------------------------------------
# GPS ping — called by the rider PWA every 5 seconds
# ---------------------------------------------------------------------------
@router.post('/logistics/location-ping')
async def location_ping(request: Request):
    """
    Token-authenticated GPS ingestion endpoint.
    Body: { token, lat, lng, speed_kmh?, accuracy_m?, battery_pct? }
    No JWT required — tracking_token is the credential.
    """
    body = await request.json()
    token   = body.get('token')
    lat     = body.get('lat')
    lng     = body.get('lng')

    if not token:
        raise HTTPException(status_code=400, detail='token is required')
    if lat is None or lng is None:
        raise HTTPException(status_code=400, detail='lat and lng are required')
    try:
        lat = float(lat)
        lng = float(lng)
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail='lat/lng must be numeric')

    # Validate token
    try:
        resp = db.table('deliveries').select('id,assigned_rider,status,dest_lat,dest_lng').eq('tracking_token', token).execute()
        rows = resp.data or []
    except Exception:
        raise HTTPException(status_code=500, detail='Token validation failed')
    if not rows:
        raise HTTPException(status_code=403, detail='Invalid tracking token')
    delivery = rows[0]
    if delivery.get('status') not in ('assigned', 'in_transit'):
        raise HTTPException(status_code=410, detail='Delivery is no longer active')

    delivery_id = delivery['id']
    rider_id    = delivery.get('assigned_rider')
    now         = dt.datetime.utcnow()
    now_iso     = now.isoformat() + 'Z'

    # Insert ping
    ping = {
        'id':          str(uuid.uuid4()),
        'rider_id':    rider_id,
        'delivery_id': delivery_id,
        'lat':         lat,
        'lng':         lng,
        'speed_kmh':   body.get('speed_kmh'),
        'accuracy_m':  body.get('accuracy_m'),
        'battery_pct': body.get('battery_pct'),
        'ts':          now_iso,
    }
    try:
        db.table('location_pings').insert(ping).execute()
    except Exception:
        raise HTTPException(status_code=500, detail='Failed to store ping')

    # Update rider denorm + delivery last_ping_at in parallel (best-effort)
    try:
        db.table('riders').update({
            'last_lat':     lat,
            'last_lng':     lng,
            'last_seen_at': now_iso,
        }).eq('id', rider_id).execute()
    except Exception:
        pass
    try:
        db.table('deliveries').update({'last_ping_at': now_iso}).eq('id', delivery_id).execute()
    except Exception:
        pass

    # ---- Geofence: auto-delivery detection (within 150 m of destination) ----
    auto_delivered = False
    dest_lat = delivery.get('dest_lat')
    dest_lng = delivery.get('dest_lng')
    if dest_lat is not None and dest_lng is not None:
        try:
            dist = _haversine_m(lat, lng, float(dest_lat), float(dest_lng))
            if dist <= 150 and delivery.get('status') == 'in_transit':
                db.table('deliveries').update({
                    'status':       'delivered',
                    'delivered_at': now_iso,
                    'last_update':  now_iso,
                }).eq('id', delivery_id).execute()
                auto_delivered = True
        except Exception:
            pass

    return {
        'received': True,
        'ts': now_iso,
        'auto_delivered': auto_delivered,
    }


# ---------------------------------------------------------------------------
# Live positions — dashboard poll (replaces map on SSE-unsupported clients)
# ---------------------------------------------------------------------------
@router.get('/logistics/live-positions')
async def live_positions(request: Request):
    """Return latest position for every active rider (from denorm columns)."""
    verify_jwt(request)
    try:
        resp = db.table('riders').select(
            'id,name,phone,vehicle,active,last_lat,last_lng,last_seen_at'
        ).eq('active', True).execute()
        riders = resp.data or []
    except Exception:
        raise HTTPException(status_code=500, detail='Failed to fetch live positions')
    # Attach current delivery if any
    active_riders = [r for r in riders if r.get('last_lat') is not None]
    return {'riders': active_riders, 'ts': dt.datetime.utcnow().isoformat() + 'Z'}


# ---------------------------------------------------------------------------
# Active deliveries snapshot (for map overlay)
# ---------------------------------------------------------------------------
@router.get('/logistics/active-deliveries')
async def active_deliveries(request: Request):
    """All in-transit/assigned deliveries with rider location snapshot."""
    verify_jwt(request)
    try:
        resp = db.table('deliveries').select(
            'id,reference,status,address,dest_lat,dest_lng,eta_text,last_ping_at,'
            'picked_up_at,delivered_at,assigned_rider'
        ).in_('status', ['assigned', 'in_transit']).execute()
        deliveries = resp.data or []
    except Exception:
        raise HTTPException(status_code=500, detail='Failed to fetch active deliveries')

    # Enrich with rider location
    rider_ids = list({d['assigned_rider'] for d in deliveries if d.get('assigned_rider')})
    rider_map: dict = {}
    if rider_ids:
        try:
            rresp = db.table('riders').select(
                'id,name,last_lat,last_lng,last_seen_at'
            ).in_('id', rider_ids).execute()
            for r in (rresp.data or []):
                rider_map[r['id']] = r
        except Exception:
            pass

    for d in deliveries:
        rid = d.get('assigned_rider')
        d['rider'] = rider_map.get(rid)

    return {'deliveries': deliveries, 'ts': dt.datetime.utcnow().isoformat() + 'Z'}


# ---------------------------------------------------------------------------
# Ping history for a single delivery (route replay / audit trail)
# ---------------------------------------------------------------------------
@router.get('/logistics/deliveries/{delivery_id}/pings')
async def delivery_pings(request: Request, delivery_id: str):
    """Return ordered GPS ping history for a delivery. JWT required."""
    verify_jwt(request)
    try:
        resp = db.table('location_pings').select(
            'id,lat,lng,speed_kmh,accuracy_m,battery_pct,ts'
        ).eq('delivery_id', delivery_id).order('ts', desc=False).execute()
        pings = resp.data or []
    except Exception:
        raise HTTPException(status_code=500, detail='Failed to fetch pings')
    return {'delivery_id': delivery_id, 'pings': pings, 'count': len(pings)}


# ---------------------------------------------------------------------------
# SSE live feed — pushes position snapshot every 4 seconds
# ---------------------------------------------------------------------------
@router.get('/logistics/live-feed')
async def live_feed(request: Request):
    """
    Server-Sent Events stream.
    Emits a 'positions' event every 4 s with the latest rider snapshot.
    Falls back to no-op if the client disconnects.
    """
    verify_jwt(request)

    async def event_generator():
        while True:
            if await request.is_disconnected():
                break
            try:
                resp = db.table('riders').select(
                    'id,name,last_lat,last_lng,last_seen_at,vehicle'
                ).eq('active', True).execute()
                riders = [r for r in (resp.data or []) if r.get('last_lat') is not None]
                payload = json.dumps({
                    'ts': dt.datetime.utcnow().isoformat() + 'Z',
                    'riders': riders,
                })
                yield f"event: positions\ndata: {payload}\n\n"
            except Exception:
                yield f"event: error\ndata: {{}}\n\n"
            await asyncio.sleep(4)

    return StreamingResponse(
        event_generator(),
        media_type='text/event-stream',
        headers={
            'Cache-Control': 'no-cache',
            'X-Accel-Buffering': 'no',   # disable nginx buffering
        },
    )