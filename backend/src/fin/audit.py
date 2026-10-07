"""Append-only audit trail (who / what / when / before / after / why).

Written inside the same transaction as the change it describes, so a
rolled-back posting leaves no audit record claiming it happened.
"""
from __future__ import annotations

from typing import Any, Dict, Optional

from src.fin.db import ex, jsonb


def record(conn, ctx, action: str, entity_type: str, entity_id: Any, *,
           ref: Optional[str] = None, before: Any = None, after: Any = None,
           reason: Optional[str] = None, metadata: Optional[Dict[str, Any]] = None) -> None:
    ex(conn, """
        INSERT INTO fin_audit_events
            (legal_entity_id, actor_id, actor_name, action, entity_type, entity_id, entity_ref,
             before_state, after_state, reason, request_id, ip_address, metadata)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
    """, (ctx.entity_id, ctx.actor_id, ctx.actor_name, action, entity_type,
          str(entity_id) if entity_id is not None else None, ref,
          jsonb(before) if before is not None else None,
          jsonb(after) if after is not None else None,
          reason, ctx.request_id, ctx.ip, jsonb(metadata or {})))
