"""Seed script to populate basic tables for local development.

Run:
    python backend/scripts/seed_data.py

Requires `SUPABASE_URL` and `SUPABASE_KEY` set in environment or .env.
"""
from src.db import db
import uuid
import datetime as dt

def now():
    return dt.datetime.utcnow().isoformat() + 'Z'

def iso_days_ago(days: int):
    return (dt.datetime.utcnow() - dt.timedelta(days=days)).replace(microsecond=0).isoformat() + 'Z'

def seed_suppliers():
    suppliers = [
        {
            'id': str(uuid.uuid4()),
            'name': 'BioFreeze Cold Chain Logistics',
            'category': 'cold_chain',
            'contact': {'email': 'ops@biofreeze.ng', 'phone': '+2348011111111'},
            'reliability_score': 92,
            'avg_delivery_time': 36,
            'price_variance_index': 4.2,
            'created_at': now(),
        },
        {
            'id': str(uuid.uuid4()),
            'name': 'Prime Vaccines Distribution',
            'category': 'vaccines',
            'contact': {'email': 'service@primevaccines.ng', 'phone': '+2348022222222'},
            'reliability_score': 88,
            'avg_delivery_time': 42,
            'price_variance_index': 6.8,
            'created_at': now(),
        },
        {
            'id': str(uuid.uuid4()),
            'name': 'MediPort Import Services',
            'category': 'import',
            'contact': {'email': 'clearance@mediport.ng', 'phone': '+2348033333333'},
            'reliability_score': 81,
            'avg_delivery_time': 54,
            'price_variance_index': 8.9,
            'created_at': now(),
        },
    ]
    for s in suppliers:
        try:
            db.table('suppliers').upsert(s).execute()
        except Exception:
            pass
    return suppliers

def seed_supplier_deliveries(suppliers):
    if not suppliers:
        return

    deliveries = []
    for idx, supplier in enumerate(suppliers):
        supplier_id = supplier['id']
        for n in range(1, 4):
            scheduled = iso_days_ago(14 * n + idx)
            delivered = iso_days_ago(14 * n + idx - 1)
            on_time = (n % 3) != 0
            deliveries.append({
                'id': str(uuid.uuid4()),
                'supplier_id': supplier_id,
                'scheduled_at': scheduled,
                'delivered_at': delivered,
                'on_time': on_time,
                'price': 150000 + (idx * 25000) + (n * 10000),
                'delay_minutes': 0 if on_time else 240,
                'sla_minutes': 2880,
                'fuel_cost': 18000 + (n * 1000),
                'route': 'Lagos Port -> Placeware Cold Room',
                'origin_to_dest': 'Apapa Port to Lagos Mainland',
                'customer_id': f'PO-{1000 + n + idx}',
                'created_at': now(),
            })

    for d in deliveries:
        try:
            db.table('supplier_deliveries').upsert(d).execute()
        except Exception:
            pass

def seed_items():
    items = [
        {'id': str(uuid.uuid4()), 'sku': 'MED-001', 'name': 'Paracetamol 500mg', 'created_at': now()},
        {'id': str(uuid.uuid4()), 'sku': 'MED-002', 'name': 'Amoxicillin 250mg', 'created_at': now()},
    ]
    for i in items:
        try:
            db.table('inventory_items').upsert(i).execute()
        except Exception:
            pass

def seed_riders():
    riders = [
        {'id': str(uuid.uuid4()), 'name': 'Rider One', 'active': True, 'created_at': now()},
        {'id': str(uuid.uuid4()), 'name': 'Rider Two', 'active': True, 'created_at': now()},
    ]
    for r in riders:
        try:
            db.table('riders').upsert(r).execute()
        except Exception:
            pass

def main():
    suppliers = seed_suppliers()
    seed_supplier_deliveries(suppliers)
    seed_items()
    seed_riders()
    print('Seed completed')

if __name__ == '__main__':
    main()
