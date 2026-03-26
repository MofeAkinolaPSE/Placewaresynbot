from fastapi.testclient import TestClient
import sys
from pathlib import Path
import jwt
import datetime as dt

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app import app  # noqa: E402
from src.constants import JWT_SECRET  # noqa: E402
from assertions import assert_status  # noqa: E402

client = TestClient(app)


def make_admin_token():
    now = dt.datetime.now(tz=dt.timezone.utc)
    exp = now + dt.timedelta(minutes=120)
    return jwt.encode(
        {"sub": "admin-test", "roles": ["admin"], "iat": int(now.timestamp()), "exp": int(exp.timestamp())},
        JWT_SECRET,
        algorithm="HS256",
    )


def test_ar_trends_requires_admin():
    r = client.get("/analytics/ar_trends?periods=3")
    assert_status(r, (401, 403))


def test_ar_trends_with_admin_token():
    token = make_admin_token()
    r = client.get("/analytics/ar_trends?periods=2", headers={"Authorization": f"Bearer {token}"})
    assert_status(r, 200)
    j = r.json()
    assert "summary" in j
    assert "periods" in j["summary"]