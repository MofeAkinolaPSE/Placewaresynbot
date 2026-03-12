from __future__ import annotations

import hashlib
from collections import deque
from typing import Any

from src.db import db


def _stable_ref_key(ref_table: str, ref_value: Any) -> str:
    return f"{(ref_table or '').strip()}:{str(ref_value)}"


def _coerce_ref_id(ref_value: Any) -> int | None:
    try:
        if ref_value is None:
            return None
        if isinstance(ref_value, bool):
            return None
        if isinstance(ref_value, int):
            return ref_value
        text = str(ref_value).strip()
        if text.isdigit() or (text.startswith("-") and text[1:].isdigit()):
            return int(text)
        return None
    except Exception:
        return None


def _hashed_bigint(ref_key: str) -> int:
    digest = hashlib.sha256(ref_key.encode("utf-8")).hexdigest()[:15]
    return int(digest, 16)


def ensure_node(
    *,
    node_type: str,
    ref_table: str,
    ref_value: Any,
    properties: dict[str, Any] | None = None,
) -> int | None:
    ref_key = _stable_ref_key(ref_table, ref_value)
    ref_id = _coerce_ref_id(ref_value)

    try:
        existing = (
            db.table("kg_nodes")
            .select("id")
            .eq("node_type", node_type)
            .eq("ref_table", ref_table)
            .eq("ref_key", ref_key)
            .limit(1)
            .execute()
        )
        rows = existing.data or []
        if rows:
            return rows[0].get("id")

        payload = {
            "node_type": node_type,
            "ref_table": ref_table,
            "ref_key": ref_key,
            "ref_id": ref_id,
            "properties": properties or {},
        }
        created = db.table("kg_nodes").insert(payload).execute()
        inserted = created.data or []
        if inserted:
            return inserted[0].get("id")
    except Exception:
        pass

    try:
        fallback_id = ref_id if ref_id is not None else _hashed_bigint(ref_key)
        existing = (
            db.table("kg_nodes")
            .select("id")
            .eq("node_type", node_type)
            .eq("ref_table", ref_table)
            .eq("ref_id", fallback_id)
            .limit(1)
            .execute()
        )
        rows = existing.data or []
        if rows:
            return rows[0].get("id")

        payload = {
            "node_type": node_type,
            "ref_table": ref_table,
            "ref_id": fallback_id,
            "properties": properties or {},
        }
        created = db.table("kg_nodes").insert(payload).execute()
        inserted = created.data or []
        if inserted:
            return inserted[0].get("id")
    except Exception:
        return None
    return None


def ensure_edge(
    *,
    from_node: int | None,
    to_node: int | None,
    edge_type: str,
    properties: dict[str, Any] | None = None,
) -> bool:
    if not from_node or not to_node:
        return False
    try:
        existing = (
            db.table("kg_edges")
            .select("id")
            .eq("from_node", from_node)
            .eq("to_node", to_node)
            .eq("edge_type", edge_type)
            .limit(1)
            .execute()
        )
        if (existing.data or []):
            return True
        db.table("kg_edges").insert(
            {
                "from_node": from_node,
                "to_node": to_node,
                "edge_type": edge_type,
                "properties": properties or {},
            }
        ).execute()
        return True
    except Exception:
        return False


def get_node_by_identity(node_type: str, ref_table: str, ref_value: Any) -> dict[str, Any] | None:
    ref_key = _stable_ref_key(ref_table, ref_value)
    try:
        res = (
            db.table("kg_nodes")
            .select("*")
            .eq("node_type", node_type)
            .eq("ref_table", ref_table)
            .eq("ref_key", ref_key)
            .limit(1)
            .execute()
        )
        rows = res.data or []
        if rows:
            return rows[0]
    except Exception:
        pass
    try:
        ref_id = _coerce_ref_id(ref_value)
        if ref_id is None:
            ref_id = _hashed_bigint(ref_key)
        res = (
            db.table("kg_nodes")
            .select("*")
            .eq("node_type", node_type)
            .eq("ref_table", ref_table)
            .eq("ref_id", ref_id)
            .limit(1)
            .execute()
        )
        rows = res.data or []
        return rows[0] if rows else None
    except Exception:
        return None


def list_nodes(node_type: str | None = None, search: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
    bounded = max(1, min(limit, 500))
    query = db.table("kg_nodes").select("*").order("created_at", desc=True).limit(bounded)
    if node_type:
        query = query.eq("node_type", node_type)
    rows = query.execute().data or []
    if search:
        term = search.lower().strip()
        rows = [
            r
            for r in rows
            if term in str(r.get("ref_key") or "").lower()
            or term in str(r.get("ref_table") or "").lower()
            or term in str(r.get("properties") or "").lower()
        ]
    return rows


def _all_nodes_edges(max_nodes: int = 5000, max_edges: int = 10000) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    nodes = db.table("kg_nodes").select("*").order("id", desc=False).limit(max_nodes).execute().data or []
    edges = db.table("kg_edges").select("*").order("id", desc=False).limit(max_edges).execute().data or []
    return nodes, edges


def subgraph(seed_node_id: int, depth: int = 2, limit: int = 200) -> dict[str, Any]:
    bounded_depth = max(1, min(depth, 4))
    nodes, edges = _all_nodes_edges()
    node_map = {int(n.get("id")): n for n in nodes if n.get("id") is not None}
    adjacency: dict[int, list[tuple[int, dict[str, Any]]]] = {}
    for edge in edges:
        try:
            src = int(edge.get("from_node"))
            dst = int(edge.get("to_node"))
        except Exception:
            continue
        adjacency.setdefault(src, []).append((dst, edge))
        adjacency.setdefault(dst, []).append((src, edge))

    visited = {seed_node_id}
    selected_edges: list[dict[str, Any]] = []
    q = deque([(seed_node_id, 0)])
    while q and len(visited) < limit:
        current, d = q.popleft()
        if d >= bounded_depth:
            continue
        for nxt, edge in adjacency.get(current, []):
            selected_edges.append(edge)
            if nxt not in visited:
                visited.add(nxt)
                q.append((nxt, d + 1))
            if len(visited) >= limit:
                break

    selected_nodes = [node_map[nid] for nid in visited if nid in node_map]
    unique_edges = {int(e.get("id")): e for e in selected_edges if e.get("id") is not None}
    return {
        "seed_node_id": seed_node_id,
        "depth": bounded_depth,
        "nodes": selected_nodes,
        "edges": list(unique_edges.values()),
    }


def reason_paths(
    source_node_id: int,
    target_node_id: int,
    *,
    max_depth: int = 4,
    edge_types: list[str] | None = None,
    limit: int = 5,
) -> dict[str, Any]:
    bounded_depth = max(1, min(max_depth, 6))
    bounded_limit = max(1, min(limit, 20))
    nodes, edges = _all_nodes_edges()
    node_map = {int(n.get("id")): n for n in nodes if n.get("id") is not None}

    allow = {e for e in (edge_types or []) if e}
    adjacency: dict[int, list[tuple[int, dict[str, Any]]]] = {}
    for edge in edges:
        et = str(edge.get("edge_type") or "")
        if allow and et not in allow:
            continue
        try:
            src = int(edge.get("from_node"))
            dst = int(edge.get("to_node"))
        except Exception:
            continue
        adjacency.setdefault(src, []).append((dst, edge))
        adjacency.setdefault(dst, []).append((src, edge))

    paths: list[dict[str, Any]] = []
    q = deque([(source_node_id, [source_node_id], [])])
    seen = {(source_node_id, tuple([source_node_id]))}
    while q and len(paths) < bounded_limit:
        node, path_nodes, path_edges = q.popleft()
        if len(path_nodes) - 1 > bounded_depth:
            continue
        if node == target_node_id:
            paths.append(
                {
                    "node_path": path_nodes,
                    "edge_path": [e.get("edge_type") for e in path_edges],
                    "trace": [
                        {
                            "from": pe.get("from_node"),
                            "to": pe.get("to_node"),
                            "edge_type": pe.get("edge_type"),
                            "properties": pe.get("properties") or {},
                        }
                        for pe in path_edges
                    ],
                }
            )
            continue

        for nxt, edge in adjacency.get(node, []):
            if nxt in path_nodes:
                continue
            next_nodes = path_nodes + [nxt]
            sig = (nxt, tuple(next_nodes))
            if sig in seen:
                continue
            seen.add(sig)
            q.append((nxt, next_nodes, path_edges + [edge]))

    return {
        "source_node": node_map.get(source_node_id),
        "target_node": node_map.get(target_node_id),
        "paths": paths,
        "path_count": len(paths),
    }


def event_graph_snapshot(event_id: str) -> dict[str, Any]:
    event_node = get_node_by_identity("event", "event_ledger", event_id)
    if not event_node:
        return {"event_node": None, "nodes": [], "edges": []}
    sg = subgraph(int(event_node["id"]), depth=2, limit=250)
    return {
        "event_node": event_node,
        "nodes": sg.get("nodes") or [],
        "edges": sg.get("edges") or [],
    }
