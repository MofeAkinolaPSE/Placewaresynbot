"""ACE Books tests run against the real Postgres schema (triggers included),
each inside one transaction that is rolled back - the live books are never
touched. Every test builds its own throwaway organisation/entity.

Run inside the backend container, where DATABASE_URL reaches the docker DB:
    docker exec chat-backend.v1 python -m pytest tests/fin -q
(On the dev host, localhost:5432 is a separate native PostgreSQL.) Set
FIN_TEST_DATABASE_URL to point the tests at another database explicitly.
"""
import datetime as dt
import os
import uuid

import pytest

if os.environ.get("FIN_TEST_DATABASE_URL"):
    os.environ["DATABASE_URL"] = os.environ["FIN_TEST_DATABASE_URL"]

from src.db import db  # noqa: E402  (pool must be created with the URL above)
from src.fin import accounts, periods, setup  # noqa: E402
from src.fin.context import FinContext  # noqa: E402


def _ctx(entity_id, actor="tester", perms=("*",)):
    return FinContext(actor, actor, ["admin"], str(entity_id), set(perms), "test")


@pytest.fixture
def conn():
    c = db.pool.getconn()
    c.autocommit = False
    try:
        yield c
    finally:
        c.rollback()
        db.pool.putconn(c)


@pytest.fixture
def make_entity(conn):
    """Create an isolated company with FY 2026 and a small chart of accounts."""
    def _make(code=None):
        code = code or "T" + uuid.uuid4().hex[:8]
        ent = setup.ensure_entity(conn, org_code="ORG-" + code, org_name="Test Org " + code,
                                  entity_code=code, entity_name="Test Co " + code)
        ctx = _ctx(ent["id"])
        periods.create_fiscal_year(conn, ctx, dt.date(2026, 1, 1))
        accts = {}
        for c, n, st in [("10100", "Cash on Hand", "CASH"), ("10290", "Bank", "CASH"),
                         ("11000", "Accounts Receivable", "RECEIVABLE"), ("12000", "Inventory", "INVENTORY"),
                         ("20000", "Accounts Payable", "PAYABLE"), ("39005", "Retained Earnings", "RETAINED_EARNINGS"),
                         ("40000", "Sales", "SALES"), ("40800", "Delivery Income", "OTHER_INCOME"),
                         ("50000", "Cost of Sales", "COST_OF_SALES"), ("62200", "Bank Charges", "OPERATING_EXPENSE")]:
            accts[c] = accounts.create_account(conn, ctx, {"code": c, "name": n, "subtype": st,
                                                           "is_control": st in ("RECEIVABLE", "PAYABLE", "INVENTORY")})
        return ctx, accts
    return _make


@pytest.fixture
def ctx_for():
    return _ctx
