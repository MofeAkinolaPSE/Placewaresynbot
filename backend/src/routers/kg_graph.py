from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field

from src.middleware import verify_jwt, require_role
from src.services import kg_graph

router = APIRouter(prefix="/kg", tags=["knowledge-graph"])


def _require_authorized(request: Request) -> dict[str, Any]:
    payload = verify_jwt(request)
    roles = set(payload.get("roles") or [])
    allowed = {
        "admin",
        "management",
        "finance",
        "ops",
        "crm",
        "hr",
        "staff",
        "compliance",
        "procurement",
        "sales",
    }
    if not roles.intersection(allowed):
        raise HTTPException(status_code=403, detail="Insufficient role for knowledge graph")
    return payload


class ReasoningQuery(BaseModel):
    source_node_id: int = Field(..., gt=0)
    target_node_id: int = Field(..., gt=0)
    max_depth: int = Field(4, ge=1, le=6)
    edge_types: list[str] | None = None
    limit: int = Field(5, ge=1, le=20)


@router.get("/nodes")
def list_nodes(
    request: Request,
    node_type: str | None = Query(default=None),
    search: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
):
    _require_authorized(request)
    rows = kg_graph.list_nodes(node_type=node_type, search=search, limit=limit)
    return {"count": len(rows), "nodes": rows}


@router.get("/subgraph/{node_id}")
def get_subgraph(
    node_id: int,
    request: Request,
    depth: int = Query(default=2, ge=1, le=4),
    limit: int = Query(default=200, ge=10, le=1000),
):
    _require_authorized(request)
    graph = kg_graph.subgraph(seed_node_id=node_id, depth=depth, limit=limit)
    return graph


@router.post("/reason")
def reason_paths(request: Request, payload: ReasoningQuery):
    _require_authorized(request)
    result = kg_graph.reason_paths(
        source_node_id=payload.source_node_id,
        target_node_id=payload.target_node_id,
        max_depth=payload.max_depth,
        edge_types=payload.edge_types,
        limit=payload.limit,
    )
    return result
