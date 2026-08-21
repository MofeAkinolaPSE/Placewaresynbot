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
import secrets
from src.services.routing_adapter import compute_route
from src.services.realtime import realtime_hub


async def _broadcast_logistics(event: str, delivery_id: str, status: str | None) -> None:
    """Best-effort realtime push for delivery lifecycle changes. Nothing in
    this router broadcast before, so a Logistics Monitor or dashboard
    Operations Queue open on another screen only ever showed a delivery's
    state as of its last manual load -- an assignment or confirmation made by
    someone else never appeared. Never allowed to fail the request."""
    try:
        await realtime_hub.broadcast('logistics_updates', {
            'event': event,
            'delivery_id': delivery_id,
            'status': status,
        })
    except Exception:
        pass

router = APIRouter()

# Excludes 0/O/1/I -- a rider is expected to actually type this on a phone,
# so avoiding look-alike characters matters more than raw entropy here.
_RIDER_CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"


def _generate_rider_code() -> str:
    return "".join(secrets.choice(_RIDER_CODE_ALPHABET) for _ in range(6))

# ---------------------------------------------------------------------------
# Geo helpers
# ---------------------------------------------------------------------------

def _complete_linked_invoice(delivery: dict, actor_id: str | None = None) -> None:
    """When a delivery reaches 'delivered' (geofence auto-detect or manual
    confirm), reflect that back on the originating frontdesk invoice --
    previously nothing wrote this back, so the invoice stayed at
    "dispatched" forever even after the rider actually confirmed delivery.
    "completed" is already a valid frontdesk_invoices.status value (migration
    099's CHECK constraint) -- no schema change needed.

    actor_id is None for the geofence auto-detect and rider-token-confirmed
    paths (there's no staff actor -- that's correct, not a gap) and the real
    staff user id when a logged-in ops/admin confirmed it manually."""
    if delivery.get('source') != 'frontdesk_walk_in':
        return
    invoice_id = delivery.get('source_ref_id')
    if not invoice_id:
        return
    try:
        db.table('frontdesk_invoices').update({'status': 'completed'}).eq('id', invoice_id).execute()
    except Exception:
        return
    # Every earlier lifecycle step (create/QC/finance/dispatch) already logs
    # to placeware_audit_logs via audit_event(subject_type="invoice") in
    # frontdesk.py -- this final step is the one exception, since it's
    # reached from this router instead. Without it, GET /frontdesk/invoices/
    # {id}/history's timeline stopped at "dispatched" even after a real
    # delivery confirmation completed the invoice.
    try:
        audit_event(
            'frontdesk_invoice_completed',
            {'invoice_id': invoice_id, 'delivery_id': delivery.get('id')},
            actor_id=actor_id,
            event_class='frontdesk',
            action='delivery_confirmed',
            subject_type='invoice',
            subject_id=invoice_id,
        )
    except Exception:
        pass


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
    r['access_code'] = _generate_rider_code()
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


@router.get('/logistics/riders')
async def list_riders(request: Request, active: bool | None = None):
    """All riders (any status), optionally filtered — unlike /logistics/live-positions
    (active + GPS-having only), this is the real "list every rider" endpoint the
    Riders tab needs. Added alongside /logistics/deliveries below: LogisticsMonitor.tsx
    previously had no way to list existing rows at all, only ever showing what was
    created in the current browser session."""
    verify_jwt(request)
    try:
        q = db.table('riders').select('id,name,phone,vehicle,active,last_lat,last_lng,last_seen_at,created_at,access_code')
        if active is not None:
            q = q.eq('active', active)
        resp = q.order('created_at', desc=True).execute()
        riders = resp.data or []
    except Exception:
        raise HTTPException(status_code=500, detail='Failed to fetch riders')
    return {'riders': riders, 'count': len(riders)}


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


@router.get('/logistics/deliveries')
async def list_deliveries(request: Request, status: str | None = None, limit: int = 100, offset: int = 0):
    """All deliveries (any status), optionally filtered, enriched with rider info —
    unlike /logistics/active-deliveries (assigned/in_transit only), this is the real
    "list every delivery" endpoint the Deliveries tab needs, including everything
    Frontdesk's send-for-delivery handoff writes directly into this table."""
    verify_jwt(request)
    try:
        q = db.table('deliveries').select(
            'id,reference,status,address,quantity,customer_id,dest_lat,dest_lng,eta_text,'
            'last_ping_at,picked_up_at,delivered_at,assigned_rider,source,source_ref_id,'
            'tracking_token,created_at'
        )
        if status:
            q = q.eq('status', status)
        resp = q.order('created_at', desc=True).range(offset, offset + limit - 1).execute()
        deliveries = resp.data or []
    except Exception:
        raise HTTPException(status_code=500, detail='Failed to fetch deliveries')

    rider_ids = list({d['assigned_rider'] for d in deliveries if d.get('assigned_rider')})
    rider_map: dict = {}
    if rider_ids:
        try:
            rresp = db.table('riders').select('id,name,phone,vehicle').in_('id', rider_ids).execute()
            for r in (rresp.data or []):
                rider_map[r['id']] = r
        except Exception:
            pass
    for d in deliveries:
        d['rider'] = rider_map.get(d.get('assigned_rider'))

    return {'deliveries': deliveries, 'count': len(deliveries)}


@router.post('/logistics/deliveries/{delivery_id}/assign')
async def assign_delivery(request: Request, delivery_id: str, payload: dict):
    """Manually assign one specific rider to one specific delivery -- the
    single-record counterpart to /logistics/assign's round-robin bulk
    assigner below. Staff need this to demo/operate the pipeline (create
    invoice -> QC -> finance -> dispatch -> assign a named rider) without
    relying on auto-assign picking an arbitrary rider."""
    verify_jwt(request, required_role='ops')
    rider_id = payload.get('rider_id')
    if not rider_id:
        raise HTTPException(status_code=400, detail='rider_id is required')
    try:
        rresp = db.table('riders').select('id,active').eq('id', rider_id).execute()
        rider = rresp.data[0] if rresp.data else None
    except Exception:
        raise HTTPException(status_code=500, detail='Failed to look up rider')
    if not rider:
        raise HTTPException(status_code=404, detail='Rider not found')
    if not rider.get('active'):
        raise HTTPException(status_code=400, detail='Rider is inactive')
    try:
        dresp = db.table('deliveries').select('id,status').eq('id', delivery_id).execute()
        delivery = dresp.data[0] if dresp.data else None
    except Exception:
        raise HTTPException(status_code=500, detail='Failed to look up delivery')
    if not delivery:
        raise HTTPException(status_code=404, detail='Delivery not found')
    if delivery.get('status') in ('delivered', 'failed'):
        raise HTTPException(status_code=409, detail=f"Cannot reassign a {delivery.get('status')} delivery")
    # Destination coordinates, optionally set at assign time. Frontdesk walk-ins
    # carry no street address at all (frontdesk_walk_ins has no address column),
    # so /frontdesk/invoices/{id}/send-for-delivery creates the delivery with
    # dest_lat/dest_lng NULL. The geofence auto-detect in /logistics/location-ping
    # is gated on both being non-NULL, which meant auto-delivery-on-arrival could
    # never fire for any invoice-originated delivery -- only the manual button
    # worked. Letting dispatch drop a pin when they assign the rider is the
    # smallest fix that makes the documented geofence behaviour reachable.
    update: dict = {'assigned_rider': rider_id, 'status': 'assigned'}
    dest_lat = payload.get('dest_lat')
    dest_lng = payload.get('dest_lng')
    if dest_lat is not None and dest_lng is not None:
        try:
            dest_lat = float(dest_lat)
            dest_lng = float(dest_lng)
        except (TypeError, ValueError):
            raise HTTPException(status_code=400, detail='dest_lat/dest_lng must be numeric')
        if not (-90 <= dest_lat <= 90) or not (-180 <= dest_lng <= 180):
            raise HTTPException(status_code=400, detail='dest_lat/dest_lng out of range')
        update['dest_lat'] = dest_lat
        update['dest_lng'] = dest_lng
    elif (dest_lat is None) != (dest_lng is None):
        raise HTTPException(status_code=400, detail='Provide both dest_lat and dest_lng, or neither')

    try:
        resp = db.table('deliveries').update(update).eq('id', delivery_id).execute()
        updated = resp.data[0] if resp.data else None
    except Exception:
        raise HTTPException(status_code=500, detail='Failed to assign delivery')
    if not updated:
        raise HTTPException(status_code=404, detail='Delivery not found')
    try:
        rresp2 = db.table('routes').select('*').eq('rider_id', rider_id).execute()
        routes = rresp2.data or []
        if routes:
            route = routes[0]
            deliveries_list = route.get('deliveries', [])
            if delivery_id not in deliveries_list:
                deliveries_list.append(delivery_id)
                db.table('routes').update({'deliveries': deliveries_list}).eq('id', route.get('id')).execute()
        else:
            route = {'id': str(uuid.uuid4()), 'rider_id': rider_id, 'deliveries': [delivery_id], 'route_meta': {}, 'created_at': dt.datetime.utcnow().isoformat() + 'Z'}
            db.table('routes').insert(route).execute()
    except Exception:
        pass
    try:
        actor = getattr(request.state, 'user', None)
        audit_event('assign_delivery', {'delivery_id': delivery_id, 'rider_id': rider_id}, actor_id=(actor.get('sub') if actor else None), event_class='logistics', action='assign', subject_type='delivery', subject_id=delivery_id)
    except Exception:
        pass
    await _broadcast_logistics('delivery_assigned', delivery_id, updated.get('status'))
    return {'status': 'assigned', 'delivery': updated}


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
    # Staff JWT (ops/admin) OR the delivery's own tracking_token authenticates
    # this call. RiderTrack.tsx's manual "Confirm Delivery" button is on a
    # public, unauthenticated page (the token IS the rider's credential,
    # same pattern as /logistics/location-ping) -- without this alternate
    # path it always required a staff JWT it doesn't have, so the button
    # silently 401'd and never worked.
    token = payload.get('token')
    actor_id = None
    if token:
        try:
            tok_resp = db.table('deliveries').select('id,tracking_token,status').eq('id', delivery_id).execute()
            tok_row = tok_resp.data[0] if tok_resp.data else None
        except Exception:
            tok_row = None
        if not tok_row or tok_row.get('tracking_token') != token:
            raise HTTPException(status_code=403, detail='Invalid tracking token for this delivery')
    else:
        jwt_payload = verify_jwt(request, required_role='ops')
        actor_id = jwt_payload.get('sub')
        try:
            tok_resp = db.table('deliveries').select('id,status').eq('id', delivery_id).execute()
            tok_row = tok_resp.data[0] if tok_resp.data else None
        except Exception:
            tok_row = None

    # Idempotency guard. The geofence auto-detect in /logistics/location-ping and
    # the rider's manual "Confirm Delivery" button race each other by design --
    # a rider arriving within 150 m is auto-delivered mid-ping while their thumb
    # is already on the button. Without this, the second writer overwrote
    # delivered_at and ran _complete_linked_invoice() a second time, emitting a
    # duplicate frontdesk_invoice_completed row into the invoice's audit
    # timeline. Re-confirming is now a no-op that reports the settled state.
    if tok_row and tok_row.get('status') == 'delivered' and payload.get('status') == 'delivered':
        return {'status': 'already_delivered', 'delivery_id': delivery_id}

    try:
        new_status = payload.get('status')
        update: dict = {'status': new_status}
        if new_status == 'delivered':
            update['delivered_at'] = dt.datetime.utcnow().isoformat() + 'Z'
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
        audit_event('update_delivery_status', {'delivery_id': delivery_id, 'status': updated.get('status')}, actor_id=actor_id, event_class='logistics', action='update_status', subject_type='delivery', subject_id=delivery_id)
    except Exception:
        pass
    if updated.get('status') == 'delivered':
        _complete_linked_invoice(updated, actor_id=actor_id)
    await _broadcast_logistics('delivery_status_changed', delivery_id, updated.get('status'))
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
    try:
        resp = db.table('deliveries').update({
            'status': 'in_transit',
            'tracking_token': token,
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
    await _broadcast_logistics('delivery_started', delivery_id, 'in_transit')
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
# ACE Riders sign-in: persistent access_code -> currently assigned delivery
# (no JWT -- the code IS the rider's credential, same trust model as the
# per-delivery tracking_token above, just durable across multiple trips
# instead of being reissued by staff every time).
# ---------------------------------------------------------------------------
@router.get('/logistics/riders/by-code/{code}')
async def resolve_rider_by_code(code: str):
    """Public, code-authenticated lookup. Resolves a rider's persistent
    access_code to whichever delivery is currently assigned to them,
    auto-starting it (minting a tracking_token, same effect as staff's
    "Start" button) the first time the rider opens their tracker for it --
    this is what lets a rider sign in once instead of waiting on staff to
    hand them a fresh link per delivery."""
    code = (code or "").strip().upper()
    if not code:
        raise HTTPException(status_code=400, detail='code is required')
    try:
        resp = db.table('riders').select('id,name,phone,vehicle,active').eq('access_code', code).execute()
        rows = resp.data or []
    except Exception:
        raise HTTPException(status_code=500, detail='Lookup failed')
    if not rows:
        raise HTTPException(status_code=404, detail='Invalid rider code')
    rider = rows[0]
    if not rider.get('active'):
        raise HTTPException(status_code=403, detail='Rider account is inactive')

    try:
        d_resp = (
            db.table('deliveries')
            .select('*')
            .eq('assigned_rider', rider['id'])
            .in_('status', ['assigned', 'in_transit'])
            .order('created_at', desc=True)
            .limit(1)
            .execute()
        )
        deliveries = d_resp.data or []
    except Exception:
        raise HTTPException(status_code=500, detail='Failed to look up assigned delivery')

    if not deliveries:
        return {'rider': rider, 'delivery': None}

    delivery = deliveries[0]
    if delivery.get('status') == 'assigned':
        token = str(uuid.uuid4())
        try:
            upd = db.table('deliveries').update({
                'status': 'in_transit',
                'tracking_token': token,
            }).eq('id', delivery['id']).execute()
            delivery = upd.data[0] if upd.data else delivery
        except Exception:
            raise HTTPException(status_code=500, detail='Failed to start delivery')

    return {'rider': rider, 'delivery': delivery}


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
        resp = db.table('deliveries').select('id,assigned_rider,status,dest_lat,dest_lng,source,source_ref_id').eq('tracking_token', token).execute()
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
                }).eq('id', delivery_id).execute()
                auto_delivered = True
                _complete_linked_invoice(delivery)
        except Exception:
            pass
    if auto_delivered:
        await _broadcast_logistics('delivery_status_changed', delivery_id, 'delivered')

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