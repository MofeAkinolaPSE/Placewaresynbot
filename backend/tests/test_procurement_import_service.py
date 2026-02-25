from src.services.procurement_import import (
    estimate_delay_impact,
    run_clearance_analysis,
    validate_transition,
)


def test_validate_transition_allows_expected_path():
    validate_transition("in_transit", "at_port")
    validate_transition("at_port", "under_clearance")
    validate_transition("under_clearance", "released")


def test_validate_transition_rejects_invalid_path():
    try:
        validate_transition("in_transit", "released")
    except ValueError as exc:
        assert "invalid transition" in str(exc)
    else:
        raise AssertionError("Expected ValueError for invalid transition")


def test_run_clearance_analysis_flags_delayed_shipments_and_impact():
    shipments = [
        {
            "id": "s1",
            "shipment_ref": "REF-1",
            "supplier_name": "Acme Pharma",
            "status": "under_clearance",
            "clearance_started_at": "2026-02-01T00:00:00Z",
            "released_at": None,
            "currency": "NGN",
            "metadata": {"rejected": False, "compliance_breach": False},
        },
        {
            "id": "s2",
            "shipment_ref": "REF-2",
            "supplier_name": "Acme Pharma",
            "status": "released",
            "clearance_started_at": "2026-02-20T00:00:00Z",
            "released_at": "2026-02-21T00:00:00Z",
            "currency": "NGN",
            "metadata": {"rejected": True, "compliance_breach": True},
        },
    ]

    result = run_clearance_analysis(shipments, threshold_days=3, daily_cost=1000)

    assert result["delayed_count"] >= 1
    assert result["estimated_total_impact"] >= 1000
    assert len(result["supplier_scorecard"]) == 1
    assert result["supplier_scorecard"][0]["supplier"] == "acme pharma"


def test_estimate_delay_impact_non_negative():
    assert estimate_delay_impact(-5, daily_cost=1000) == 0
    assert estimate_delay_impact(2.5, daily_cost=1000) == 2500
