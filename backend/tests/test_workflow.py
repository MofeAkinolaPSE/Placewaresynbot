from fastapi.testclient import TestClient
import sys
from pathlib import Path
import jwt

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app import app  # noqa: E402
from src.constants import JWT_SECRET  # noqa: E402
from assertions import assert_status  # noqa: E402

client = TestClient(app)

def make_admin_token():
    return jwt.encode({"roles": ["admin"]}, JWT_SECRET, algorithm="HS256")


def test_workflow_intent_and_approve():
    token = make_admin_token()
    payload = {"intent_type": "order_restock", "payload": {"sku": "SKU1", "qty": 5}}
    r = client.post("/workflow/intent", json=payload, headers={"Authorization": f"Bearer {token}"})
    assert_status(r, 200)
    intent_id = r.json()["intent_id"]
    ar = client.post("/workflow/approve", json={"intent_id": intent_id, "approved": True}, headers={"Authorization": f"Bearer {token}"})
    assert_status(ar, 200)
    assert ar.json()["status"] == "approved"
