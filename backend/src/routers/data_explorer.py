"""data_explorer.py — Commercial Data Explorer API.

See data-assimilation/docs.md/ACE-Data-Intelligence-Layer.md Chapter 4.
Deliberately NOT cached (unlike data_intelligence.py's Auditor/Coverage
endpoints) — this is a live investigation tool, staleness would be
misleading mid-lookup.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query

from src.middleware import require_role
from src.services import explorer_service

router = APIRouter(prefix="/explorer", tags=["data-intelligence"])

_require_admin = require_role("admin")


@router.get("/search")
def explorer_search(
    q: str = Query(..., min_length=1),
    limit_per_entity: int = Query(default=8, ge=1, le=50),
    _u=Depends(_require_admin),
):
    return {"query": q, "results": explorer_service.search(q, limit_per_entity=limit_per_entity)}


@router.get("/record/{entity_type}/{key}")
def explorer_record(entity_type: str, key: str, _u=Depends(_require_admin)):
    try:
        return explorer_service.get_record(entity_type, key)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
