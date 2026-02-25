from fastapi.testclient import TestClient
import sys
from pathlib import Path
import jwt

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app import app  # noqa: E402
from src.constants import JWT_SECRET  # noqa: E402

client = TestClient(app)

def make_admin_token():
    return jwt.encode({"roles": ["admin"]}, JWT_SECRET, algorithm="HS256")


def test_kpis_requires_admin():
    r = client.get("/analytics/kpis")
    assert r.status_code in (401, 403)


def test_kpis_with_admin_token():
    token = make_admin_token()
    r = client.get("/analytics/kpis", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200
    j = r.json()
    assert "kpis" in j
    assert "ar" in j["kpis"]
    assert "ap" in j["kpis"]
