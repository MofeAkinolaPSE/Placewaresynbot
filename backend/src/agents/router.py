from __future__ import annotations
from typing import List, Set

_ROUTE_MAP = {
    "inventory": ["inventory_intelligence"],
    "stock": ["inventory_intelligence"],
    "expiry": ["inventory_intelligence"],
    "nafdac": ["compliance_monitoring"],
    "compliance": ["compliance_monitoring"],
    "ar": ["financial_analyst"],
    "finance": ["financial_analyst"],
    "revenue": ["financial_analyst"],
}


def route_question(question: str, roles: Set[str], mode: str) -> List[str]:
    """Simple keyword-based router returning agent names to run.

    - Scans for keywords present in the question and maps to agents.
    - Dedupes results while preserving order.
    """
    q = (question or "").lower()
    agents: List[str] = []
    seen = set()
    for kw, names in _ROUTE_MAP.items():
        if kw in q:
            for n in names:
                if n not in seen:
                    agents.append(n)
                    seen.add(n)
    # Default: for executive mode, include inventory + finance summaries
    if not agents and mode == "executive":
        for default in ["inventory_intelligence", "financial_analyst", "compliance_monitoring"]:
            if default not in seen:
                agents.append(default)
                seen.add(default)
    return agents


def merge_insights(insights: List[dict]) -> dict:
    """Merge list of insight dicts into a single combined insight dict.

    - Concatenates findings, risks, recommendations, supporting_refs.
    - Merges metrics by summing numeric values when possible.
    - Averages confidence_score.
    - Aggregates execution_metadata (sum query_count, average latency).
    """
    combined = {
        "metrics": {},
        "findings": [],
        "risks": [],
        "recommendations": [],
        "confidence_score": 0.0,
        "supporting_refs": [],
        "execution_metadata": {"query_count": 0, "latency_ms": 0},
    }
    if not insights:
        return combined

    total_conf = 0.0
    conf_count = 0
    total_latency = 0
    for ins in insights:
        metrics = ins.get("metrics") or {}
        for k, v in metrics.items():
            try:
                # sum numeric metrics
                if isinstance(v, (int, float)):
                    combined["metrics"][k] = combined["metrics"].get(k, 0) + v
                else:
                    combined["metrics"].setdefault(k, v)
            except Exception:
                combined["metrics"].setdefault(k, v)

        combined["findings"].extend(ins.get("findings") or [])
        combined["risks"].extend(ins.get("risks") or [])
        combined["recommendations"].extend(ins.get("recommendations") or [])
        combined["supporting_refs"].extend(ins.get("supporting_refs") or [])

        cs = ins.get("confidence_score")
        if isinstance(cs, (int, float)):
            total_conf += float(cs)
            conf_count += 1

        em = ins.get("execution_metadata") or {}
        try:
            total_latency += int(em.get("latency_ms", 0))
        except Exception:
            pass
        try:
            combined["execution_metadata"]["query_count"] += int(em.get("query_count", 0))
        except Exception:
            pass

    combined["confidence_score"] = round((total_conf / conf_count) if conf_count else 0.0, 3)
    combined["execution_metadata"]["latency_ms"] = total_latency
    return combined

__all__ = ["route_question", "merge_insights"]
