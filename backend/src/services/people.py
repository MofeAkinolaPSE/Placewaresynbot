"""Display names for the user / staff ids stored on operational records.

Projects, stock orders and audit rows store the actor's user id (a UUID) or a
staff id. Screens show the person: the staff member's full name when the login
belongs to a staff record (matched on email), otherwise the login email.
"""
from __future__ import annotations

from typing import Dict, Iterable

from src.fin.db import q, tx


def names_for(ids: Iterable[object]) -> Dict[str, str]:
    wanted = sorted({str(i) for i in ids if i})
    if not wanted:
        return {}
    with tx() as conn:
        rows = q(conn, """SELECT u.id::text AS id, COALESCE(s.full_name, u.email) AS name
                          FROM placeware_users u LEFT JOIN placeware_staff s ON lower(s.email)=lower(u.email)
                          WHERE u.id::text = ANY(%s)
                          UNION ALL
                          SELECT s.staff_id::text, s.full_name FROM placeware_staff s WHERE s.staff_id::text = ANY(%s)""",
                 (wanted, wanted))
    out = {r["id"]: r["name"] for r in rows if r["name"]}
    for i in wanted:
        # system actors ("auto_low_stock", "system_backfill") read as they are
        out.setdefault(i, i.replace("_", " ") if not _is_uuid(i) else "Unknown user")
    return out


def _is_uuid(s: str) -> bool:
    return len(s) == 36 and s.count("-") == 4
