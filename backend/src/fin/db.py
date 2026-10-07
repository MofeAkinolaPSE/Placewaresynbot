"""Transaction helpers for ACE Books.

Financial posting must be atomic: every service function takes an open
connection and never commits on its own. The outermost caller (an API
handler, via `tx()`) commits once, or rolls back on any exception.
"""
from __future__ import annotations

import datetime as dt
import decimal
from contextlib import contextmanager
from decimal import ROUND_HALF_UP, Decimal
from typing import Any, Dict, Iterator, List, Optional

from psycopg2.extras import Json, RealDictCursor

from src.db import db

ZERO = Decimal("0.00")
CENT = Decimal("0.01")


def money(x: Any) -> Decimal:
    """Exact 2dp money. Never floats for financial amounts."""
    if x is None or x == "":
        return ZERO
    if isinstance(x, Decimal):
        return x.quantize(CENT, rounding=ROUND_HALF_UP)
    try:
        return Decimal(str(x)).quantize(CENT, rounding=ROUND_HALF_UP)
    except decimal.InvalidOperation as exc:
        raise ValueError(f"not a valid amount: {x!r}") from exc


def qty(x: Any) -> Decimal:
    if x is None or x == "":
        return Decimal("0")
    return Decimal(str(x)).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)


@contextmanager
def tx() -> Iterator[Any]:
    """One database transaction. Commits on success, rolls back on error."""
    conn = db.pool.getconn()
    try:
        conn.autocommit = False
        yield conn
        conn.commit()
    except BaseException:
        conn.rollback()
        raise
    finally:
        db.pool.putconn(conn)


def q(conn, sql: str, params: Any = None) -> List[Dict[str, Any]]:
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(sql, params)
        return [dict(r) for r in cur.fetchall()] if cur.description else []


def q1(conn, sql: str, params: Any = None) -> Optional[Dict[str, Any]]:
    rows = q(conn, sql, params)
    return rows[0] if rows else None


def ex(conn, sql: str, params: Any = None) -> int:
    with conn.cursor() as cur:
        cur.execute(sql, params)
        return cur.rowcount


def jsonb(v: Any) -> Json:
    return Json(v, dumps=_dumps)


def _default(o: Any) -> Any:
    if isinstance(o, Decimal):
        return str(o)
    if isinstance(o, (dt.date, dt.datetime)):
        return o.isoformat()
    return str(o)


def _dumps(v: Any) -> str:
    import json
    return json.dumps(v, default=_default)


def plain(v: Any) -> Any:
    """Make DB rows JSON-safe for API responses (Decimal -> str keeps precision)."""
    if isinstance(v, dict):
        return {k: plain(x) for k, x in v.items()}
    if isinstance(v, (list, tuple)):
        return [plain(x) for x in v]
    if isinstance(v, Decimal):
        return str(v)
    if isinstance(v, (dt.date, dt.datetime)):
        return v.isoformat()
    if hasattr(v, "hex") and v.__class__.__name__ == "UUID":
        return str(v)
    return v
