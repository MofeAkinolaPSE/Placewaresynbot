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


def test_forecast_requires_admin():
    r = client.get("/analytics/forecast/ar_balance")
    assert_status(r, (401, 403))


def test_forecast_with_admin_token():
    token = make_admin_token()
    r = client.get("/analytics/forecast/ar_balance?window=3&horizon=2", headers={"Authorization": f"Bearer {token}"})
    assert_status(r, 200)
    j = r.json()
    assert "series" in j and "rolling" in j and "forecast" in j
