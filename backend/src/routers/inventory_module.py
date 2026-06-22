from fastapi import APIRouter, HTTPException, Request
from src.schemas.inventory import InventoryItem, StockLevel, InventoryMovement, InventoryRequest
from src.middleware import verify_jwt, require_role
from src.db import db, audit_event
from src.services.inventory import record_inventory_event
from src.services.realtime import realtime_hub
from src.cache import invalidate_cache_tags
from src.services.oeis import process_operational_event
from src.constants import TABLE_INVENTORY_EVENTS
import os, json, hashlib, logging

logger = logging.getLogger(__name__)
import datetime as dt

LEDGER_PATH = os.path.join(os.path.dirname(__file__), "..", "..", "data", "event_ledger.jsonl")

router = APIRouter()

# DB table names (migrations create these names)
TABLE_INV_ITEMS = "inventory_items"
TABLE_STOCK = "stock_levels"
TABLE_MOVES = "inventory_movements"
TABLE_REQUESTS = "inventory_requests"


def _append_ledger_event(event: dict):
    e = dict(event)
    e.pop("version_hash", None)
    serialized = json.dumps(e, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    vh = hashlib.sha256(serialized).hexdigest()
    e["version_hash"] = vh
    if not e.get("timestamp"):
        e["timestamp"] = dt.datetime.utcnow().replace(microsecond=0).isoformat() + "Z"
    parent = os.path.dirname(LEDGER_PATH)
    if not os.path.exists(parent):
        os.makedirs(parent, exist_ok=True)
    with open(LEDGER_PATH, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(e, default=str) + "\n")
    return vh


def _get_item_by_id(item_id: str):
    resp = db.table(TABLE_INV_ITEMS).select("*").eq("id", item_id).limit(1).execute()
    rows = resp.data or []
    return rows[0] if rows else None


@router.post('/inventory/items', status_code=201)
async def create_item(request: Request, payload: InventoryItem):
    verify_jwt(request, required_role='ops')
    item = payload.dict()
    try:
        resp = db.table(TABLE_INV_ITEMS).insert(item).execute()
        created = resp.data[0] if resp.data else item
        try:
            actor = getattr(request.state, 'user', None)
            audit_event('create_inventory_item', {'sku': created.get('sku')}, actor_id=(actor.get('sub') if actor else None), event_class='inventory', action='create', subject_type='inventory_item', subject_id=created.get('id'))
        except Exception:
            pass
        return {'status': 'created', 'item': created}
    except Exception as e:
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get('/inventory/stock')
async def list_stock(request: Request):
    verify_jwt(request)
    resp = db.table(TABLE_STOCK).select("*").execute()
    data = resp.data or []
    try:
        actor = getattr(request.state, 'user', None)
        audit_event('list_stock_levels', {'count': len(data)}, actor_id=(actor.get('sub') if actor else None), event_class='inventory')
    except Exception:
        pass
    return data


@router.post('/inventory/movements', status_code=201)
async def create_movement(request: Request, payload: InventoryMovement):
    verify_jwt(request, required_role='ops')
    m = payload.dict()
    m.setdefault('created_at', dt.datetime.utcnow().replace(microsecond=0).isoformat() + 'Z')
    # insert movement row
    try:
        mv_resp = db.table(TABLE_MOVES).insert(m).execute()
        created = mv_resp.data[0] if mv_resp.data else m
    except Exception as e:
        raise HTTPException(status_code=500, detail="Internal server error")

    # update stock_levels: decrement source and increment destination or apply to 'main'
    item_id = m.get('item_id')
    change = float(m.get('change') or 0)
    src = m.get('source')
    dst = m.get('destination')

    def _upsert_stock(item_id, location, delta):
        try:
            sel = db.table(TABLE_STOCK).select("id,quantity").eq("item_id", item_id).eq("location", location).limit(1).execute()
            rows = sel.data or []
            if rows:
                cur = float(rows[0].get('quantity') or 0) + float(delta)
                db.table(TABLE_STOCK).update({"quantity": cur, "updated_at": dt.datetime.utcnow().isoformat()}).eq("id", rows[0]["id"]).execute()
            else:
                db.table(TABLE_STOCK).insert({"item_id": item_id, "location": location, "quantity": delta}).execute()
        except Exception:
            pass

    if src:
        _upsert_stock(item_id, src, -change)
    if dst:
        _upsert_stock(item_id, dst, change)
    if not src and dst is None:
        _upsert_stock(item_id, 'main', change)

    # Try to emit inventory event to inventory_events table for cross-service realtime
    try:
        item = _get_item_by_id(item_id)
        sku = item.get('sku') if item else None
        if sku:
            # record_inventory_event expects sku and quantity change
            try:
                record_inventory_event(sku=sku, change=change, event_type=m.get('movement_type') or 'movement', reference=created.get('id') if isinstance(created, dict) else None, user_id=m.get('created_by') or 'system')
            except Exception:
                pass
    except Exception:
        pass

    # append dev ledger for immutability/debug
    try:
        ev = {
            'department': 'inventory',
            'event_type': 'InventoryMovement',
            'payload': m,
            'created_by': m.get('created_by'),
            'approval_status': None,
        }
        vh = _append_ledger_event(ev)
        try:
            actor = None
            try:
                payload_auth = request.state.user
                actor = payload_auth.get('sub') or payload_auth.get('user_id')
            except Exception:
                actor = None
            audit_event(
                'inventory_movement_recorded',
                {'item_id': m.get('item_id'), 'change': m.get('change'), 'movement_type': m.get('movement_type')},
                actor_id=actor,
                event_class='inventory',
                action='movement',
                outcome='recorded',
                subject_type='inventory_movement',
                subject_id=vh,
            )
        except Exception:
            pass
    except Exception:
        vh = None

    await realtime_hub.broadcast('inventory_updates', {
        'event': 'inventory_movement_recorded',
        'item_id': item_id,
        'change': change,
        'movement_type': m.get('movement_type'),
        'at': dt.datetime.utcnow().replace(microsecond=0).isoformat() + 'Z',
    })
    await realtime_hub.broadcast('logistics_updates', {
        'event': 'stock_movement_changed',
        'item_id': item_id,
        'change': change,
        'movement_type': m.get('movement_type'),
        'at': dt.datetime.utcnow().replace(microsecond=0).isoformat() + 'Z',
    })
    await realtime_hub.broadcast('finance_updates', {
        'event': 'inventory_cost_impact',
        'item_id': item_id,
        'change': change,
        'movement_type': m.get('movement_type'),
        'at': dt.datetime.utcnow().replace(microsecond=0).isoformat() + 'Z',
    })
    invalidate_cache_tags(
        'inventory',
        'inventory_dashboard',
        'logistics',
        'ops_kpis',
        'finance',
        'finance_kpis',
        'finance_trend',
        'finance_gl',
        'executive',
    )

    try:
        actor = None
        try:
            auth_payload = request.state.user
            actor = auth_payload.get('sub') or auth_payload.get('user_id')
        except Exception:
            actor = m.get('created_by')

        await process_operational_event(
            {
                "department": "inventory",
                "event_type": "inventory_movement_recorded",
                "payload": {
                    "item_id": item_id,
                    "change": change,
                    "movement_type": m.get('movement_type'),
                    "reference": created.get('id') if isinstance(created, dict) else None,
                },
                "created_by": actor,
                "status": "submitted",
            },
            actor_id=actor,
        )
    except Exception:
        pass

    return {'status': 'recorded', 'movement': created, 'version_hash': vh}


@router.post('/inventory/requests', status_code=201)
async def create_request(request: Request, payload: InventoryRequest):
    verify_jwt(request, required_role='ops')
    r = payload.dict()
    try:
        resp = db.table(TABLE_REQUESTS).insert(r).execute()
        created = resp.data[0] if resp.data else r
        try:
            actor = getattr(request.state, 'user', None)
            audit_event('create_inventory_request', {'item_id': created.get('item_id'), 'quantity': created.get('quantity')}, actor_id=(actor.get('sub') if actor else None), event_class='inventory', action='request', subject_type='inventory_request', subject_id=created.get('id'))
        except Exception:
            pass
        return {'status': 'created', 'request': created}
    except Exception as e:
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get('/inventory/movements/incoming')
async def list_incoming(request: Request):
    verify_jwt(request)
    resp = db.table(TABLE_MOVES).select("*").gt("change", 0).order("created_at", desc=True).limit(200).execute()
    return resp.data or []


@router.get('/inventory/movements/outgoing')
async def list_outgoing(request: Request):
    verify_jwt(request)
    resp = db.table(TABLE_MOVES).select("*").lt("change", 0).order("created_at", desc=True).limit(200).execute()
    return resp.data or []
