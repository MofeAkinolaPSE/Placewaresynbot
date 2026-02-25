from src.agents.router import route_question, merge_insights


def test_route_question_keywords():
    agents = route_question("show inventory levels and expiries", roles=set(), mode="user")
    assert "inventory_intelligence" in agents

    agents = route_question("NAFDAC approval status for batch", roles=set(), mode="user")
    assert "compliance_monitoring" in agents

    agents = route_question("revenue and AR aging", roles=set(), mode="user")
    assert "financial_analyst" in agents


def test_merge_insights_basic():
    a = {
        "metrics": {"low_stock_count": 2, "total_latency_ms": 50},
        "findings": ["A"],
        "risks": ["r1"],
        "recommendations": ["rec1"],
        "confidence_score": 0.8,
        "supporting_refs": [{"id": 1}],
        "execution_metadata": {"query_count": 1, "latency_ms": 50},
    }
    b = {
        "metrics": {"low_stock_count": 3, "total_latency_ms": 40},
        "findings": ["B"],
        "risks": ["r2"],
        "recommendations": ["rec2"],
        "confidence_score": 0.6,
        "supporting_refs": [{"id": 2}],
        "execution_metadata": {"query_count": 2, "latency_ms": 40},
    }
    merged = merge_insights([a, b])
    assert merged["metrics"]["low_stock_count"] == 5
    assert "A" in merged["findings"] and "B" in merged["findings"]
    assert merged["confidence_score"] == 0.7
    assert merged["execution_metadata"]["query_count"] == 3
