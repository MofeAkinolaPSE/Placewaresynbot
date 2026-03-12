from __future__ import annotations
from typing import List, Set

# Department-Scoped Agent Routing
# Maps keywords to agent names per Agent_stack.md specification
_ROUTE_MAP = {
    # 1. Inventory Intelligence Agent
    "inventory": ["inventory_intelligence"],
    "stock": ["inventory_intelligence"],
    "expiry": ["inventory_intelligence", "expiry_monitoring"],
    "low stock": ["inventory_intelligence"],
    "batch": ["inventory_intelligence", "compliance_monitoring"],
    "restock": ["inventory_intelligence"],
    
    # 2. Import & Clearance Agent  
    "import": ["import_clearance"],
    "clearance": ["import_clearance"],
    "shipment": ["import_clearance"],
    "port": ["import_clearance"],
    "supplier": ["import_clearance"],
    "procurement": ["import_clearance"],
    
    # 3. Compliance Monitoring Agent
    "nafdac": ["compliance_monitoring"],
    "compliance": ["compliance_monitoring"],
    "regulatory": ["compliance_monitoring"],
    "approval": ["compliance_monitoring"],
    "audit": ["compliance_monitoring"],
    
    # 4. Cold-Chain Integrity Agent
    "cold chain": ["cold_chain_integrity"],
    "temperature": ["cold_chain_integrity"],
    "cold room": ["cold_chain_integrity", "cold_room_capacity"],
    "vaccine storage": ["cold_chain_integrity"],
    "cold box": ["cold_chain_integrity"],
    
    # 5. Cold Room Capacity Agent
    "capacity": ["cold_room_capacity"],
    "storage": ["cold_room_capacity"],
    
    # 6. Logistics Optimization Agent
    "logistics": ["logistics_optimization"],
    "delivery": ["logistics_optimization"],
    "dispatch": ["logistics_optimization"],
    "route": ["logistics_optimization"],
    "transport": ["logistics_optimization"],
    "sla": ["logistics_optimization"],
    
    # 7. Financial Analyst Agent
    "ar": ["financial_analyst"],
    "ap": ["financial_analyst"],
    "finance": ["financial_analyst"],
    "receivable": ["financial_analyst"],
    "payable": ["financial_analyst"],
    "margin": ["financial_analyst"],
    "credit": ["financial_analyst"],
    "overdue": ["financial_analyst"],
    
    # 8. Revenue Strategy Agent
    "revenue": ["revenue_strategy"],
    "sales": ["revenue_strategy"],
    "growth": ["revenue_strategy"],
    "forecast": ["revenue_strategy", "enterprise_risk"],
    "target": ["revenue_strategy"],
    "goal": ["revenue_strategy"],
    
    # 9. Enterprise Risk Agent
    "risk": ["enterprise_risk"],
    "scenario": ["enterprise_risk"],
    "simulation": ["enterprise_risk"],
    "contingency": ["enterprise_risk"],
    "heatmap": ["enterprise_risk"],
    
    # 10. Process Optimization Agent
    "process": ["process_optimization"],
    "bottleneck": ["process_optimization"],
    "efficiency": ["process_optimization"],
    "turnaround": ["process_optimization"],
    "cycle time": ["process_optimization"],
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
    # Default: for executive mode, include all core department agents
    if not agents and mode == "executive":
        exec_defaults = [
            "inventory_intelligence",
            "financial_analyst", 
            "compliance_monitoring",
            "import_clearance",
            "cold_chain_integrity",
            "logistics_optimization",
            "revenue_strategy",
            "enterprise_risk",
            "process_optimization",
        ]
        for default in exec_defaults:
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
