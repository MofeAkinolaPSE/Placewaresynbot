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
    import time
    now = int(time.time())
    return jwt.encode(
        {"sub": "admin-test", "roles": ["admin"], "iat": now, "exp": now + 7200},
        JWT_SECRET,
        algorithm="HS256",
    )


def test_ar_aging_requires_admin():
    r = client.get("/reports/ar_aging")
    assert_status(r, (401, 403))


def test_ar_aging_with_admin_token():
    token = make_admin_token()
    r = client.get("/reports/ar_aging", headers={"Authorization": f"Bearer {token}"})
    assert_status(r, 200)
    j = r.json()
    assert "aging" in j
    assert all(k in j["aging"] for k in ["0_30", "31_60", "61_90", "91_plus"])


def test_ar_aging_csv_export():
    token = make_admin_token()
    r = client.get("/reports/ar_aging?format=csv", headers={"Authorization": f"Bearer {token}"})
    assert_status(r, 200)
    assert r.headers.get("content-type", "").startswith("text/csv")
    assert "bucket,amount" in r.text