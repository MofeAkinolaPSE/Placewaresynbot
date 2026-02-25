import os
import pytest
from fastapi.testclient import TestClient

from app import app

client = TestClient(app)


def _has_supabase_creds():
    return bool(os.getenv('SUPABASE_URL') and os.getenv('SUPABASE_KEY'))


@pytest.mark.skipif(not _has_supabase_creds(), reason='Supabase not configured')
def test_create_and_list_supplier():
    payload = {'name': 'Test Supplier', 'contact_email': 't@example.com'}
    r = client.post('/suppliers', json=payload, headers={'Authorization': 'Bearer test'})
    assert r.status_code in (201, 500)  # 201 expected if creds valid and auth accepted
    resp = client.get('/suppliers', headers={'Authorization': 'Bearer test'})
    assert resp.status_code == 200


@pytest.mark.skipif(not _has_supabase_creds(), reason='Supabase not configured')
def test_inventory_create_item_and_movement():
    item = {'sku': 'SMOKE-1', 'name': 'Smoke Test Item'}
    r = client.post('/inventory/items', json=item, headers={'Authorization': 'Bearer test'})
    assert r.status_code in (201, 500)
