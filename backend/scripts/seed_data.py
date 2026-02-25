"""Seed script to populate basic tables for local development.

Run:
    python backend/scripts/seed_data.py

Requires `SUPABASE_URL` and `SUPABASE_KEY` set in environment or .env.
"""
from src.db import supabase
import uuid
import datetime as dt

def now():
    return dt.datetime.utcnow().isoformat() + 'Z'

def seed_suppliers():
    suppliers = [
        {'id': str(uuid.uuid4()), 'name': 'ACME Pharma', 'contact_email': 'acme@example.com', 'created_at': now()},
        {'id': str(uuid.uuid4()), 'name': 'Health Supplies Ltd', 'contact_email': 'health@example.com', 'created_at': now()},
    ]
    for s in suppliers:
        try:
            supabase.table('suppliers').upsert(s).execute()
        except Exception:
            pass

def seed_items():
    items = [
        {'id': str(uuid.uuid4()), 'sku': 'MED-001', 'name': 'Paracetamol 500mg', 'created_at': now()},
        {'id': str(uuid.uuid4()), 'sku': 'MED-002', 'name': 'Amoxicillin 250mg', 'created_at': now()},
    ]
    for i in items:
        try:
            supabase.table('inventory_items').upsert(i).execute()
        except Exception:
            pass

def seed_riders():
    riders = [
        {'id': str(uuid.uuid4()), 'name': 'Rider One', 'active': True, 'created_at': now()},
        {'id': str(uuid.uuid4()), 'name': 'Rider Two', 'active': True, 'created_at': now()},
    ]
    for r in riders:
        try:
            supabase.table('riders').upsert(r).execute()
        except Exception:
            pass

def main():
    seed_suppliers()
    seed_items()
    seed_riders()
    print('Seed completed')

if __name__ == '__main__':
    main()
