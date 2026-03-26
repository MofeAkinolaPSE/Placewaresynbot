from fastapi.testclient import TestClient
import asyncio
import importlib
import sys
from pathlib import Path
import jwt
import json

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app import app  # noqa: E402
from app import _ifrs_finance_lineage_warnings  # noqa: E402
from app import _build_deterministic_lineage_key, _payroll_baseline_lineage_warnings  # noqa: E402
from app import _compute_import_control_rollup  # noqa: E402
from src.constants import JWT_SECRET  # noqa: E402
from src import db as db_module  # noqa: E402
from src.services.sage_adapter.schemas import ImportBundle, ImportMeta  # noqa: E402

client = TestClient(app)


def make_admin_token():
    import time
    now = int(time.time())
    return jwt.encode(
        {"sub": "admin-test", "roles": ["admin"], "iat": now, "exp": now + 7200},
        JWT_SECRET,
        algorithm="HS256",
    )


def test_sage_import_validation_headers():
    token = make_admin_token()
    files = {
        # minimal valid headers for customers and inventory
        "customers": ("customers.csv", b"customer_id,name\nC1,Acme\n"),
        "inventory": ("inventory.csv", b"sku,name,quantity\nSKU1,Item,10\n"),
    }
    r = client.post("/sage/import", headers={"Authorization": f"Bearer {token}"}, files=files)
    assert r.status_code == 200
    j = r.json()
    assert j["status"] in ("imported", "validated")
    assert j["counts"]["customers"] >= 1
    assert j["counts"]["inventory"] >= 1
    if j["status"] == "imported":
        assert j.get("kpi_promotion") == "promoted"


def test_sage_import_rejects_bad_headers():
    token = make_admin_token()
    files = {
        "customers": ("customers.csv", b"id,title\n1,Bad\n"),
    }
    r = client.post("/sage/import", headers={"Authorization": f"Bearer {token}"}, files=files)
    assert r.status_code == 400


def test_sage_import_accepts_header_aliases():
    token = make_admin_token()
    files = {
        "customers": ("customers.csv", b"Customer ID,Customer Name,Email Address\nC1,Acme,ops@acme.com\n"),
        "inventory": ("inventory.csv", b"item_code,product_name,qty\nSKU1,Item A,10\n"),
    }
    r = client.post("/sage/import", headers={"Authorization": f"Bearer {token}"}, files=files)
    assert r.status_code == 200
    body = r.json()
    assert body["counts"]["customers"] == 1
    assert body["counts"]["inventory"] == 1


def test_sage_import_accepts_json_payload():
    token = make_admin_token()
    customers_json = json.dumps([
        {"customer id": "C100", "customer_name": "Health Hub", "email": "hub@example.com"}
    ]).encode("utf-8")
    files = {
        "customers": ("customers.json", customers_json, "application/json"),
    }
    r = client.post("/sage/import", headers={"Authorization": f"Bearer {token}"}, files=files)
    assert r.status_code == 200
    assert r.json()["counts"]["customers"] == 1


def test_sage_import_accepts_prefixed_header_export():
    token = make_admin_token()
    files = {
        "customers": ("customers.csv", b"vcustomer_id,name\nC200,Regional Hub\n"),
    }
    r = client.post("/sage/import", headers={"Authorization": f"Bearer {token}"}, files=files)
    assert r.status_code == 200
    assert r.json()["counts"]["customers"] == 1


def test_sage_import_rejects_bad_row_but_keeps_valid_rows():
    token = make_admin_token()
    files = {
        "ar": (
            "ar.csv",
            b"invoice_id,customer_id,date,amount,balance\n"
            b"INV-1,CUST-1,2026-01-01,bad,20\n"
            b"INV-2,CUST-2,2026-01-02,100,50\n",
        ),
    }
    r = client.post("/sage/import", headers={"Authorization": f"Bearer {token}"}, files=files)
    assert r.status_code == 200
    body = r.json()
    assert body["counts"]["ar"] == 1
    assert body.get("rejected_rows", 0) >= 1
    assert body["status"] in ("partial_success", "imported")
    if body["status"] == "partial_success":
        assert body.get("kpi_promotion") == "preserved_previous"


def test_sage_import_async_mode_queues_job():
    token = make_admin_token()
    files = {
        "customers": ("customers.csv", b"customer_id,name\nC1,Acme\n"),
    }
    r = client.post("/sage/import?async_mode=true", headers={"Authorization": f"Bearer {token}"}, files=files)
    assert r.status_code == 202
    body = r.json()
    assert body["status"] == "queued"
    assert "batch_id" in body


def test_import_job_detail_not_found():
    token = make_admin_token()
    r = client.get("/imports/jobs/00000000-0000-0000-0000-000000000000", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 404


def test_hr_import_async_mode_queues_job():
    token = make_admin_token()
    files = {
        "payroll": (
            "payroll.csv",
            b"employee_id,salary,overtime_hours,overtime_rate\nEMP-1,1000,2,5\n",
        )
    }
    r = client.post("/hr/import?async_mode=true", headers={"Authorization": f"Bearer {token}"}, files=files)
    assert r.status_code == 202
    assert r.json()["status"] == "queued"


def test_ops_import_async_mode_queues_job():
    token = make_admin_token()
    files = {
        "orders": (
            "orders.csv",
            b"order_id,created_at,fulfilled_at,sku,quantity\nO1,2026-01-01T00:00:00Z,2026-01-02T00:00:00Z,SKU1,2\n",
        )
    }
    r = client.post("/ops/import?async_mode=true", headers={"Authorization": f"Bearer {token}"}, files=files)
    assert r.status_code == 202
    assert r.json()["status"] == "queued"


def test_crm_import_async_mode_queues_job():
    token = make_admin_token()
    files = {
        "pipeline": (
            "pipeline.csv",
            b"opportunity_id,customer_id,amount,stage,status,close_date\nOP1,C1,1000,Lead,Open,2026-02-01\n",
        )
    }
    r = client.post("/crm/import?async_mode=true", headers={"Authorization": f"Bearer {token}"}, files=files)
    assert r.status_code == 202
    assert r.json()["status"] == "queued"


def _assert_processor_retries(monkeypatch, processor_name, datasets):
    app_module = importlib.import_module("app")
    calls = []
    state = {"first": True}

    def fake_update_import_job(job_id, **kwargs):
        calls.append(kwargs)

    def fake_load_dataset_bytes(*args, **kwargs):
        if state["first"]:
            state["first"] = False
            raise RuntimeError("transient failure")
        return [], {"provided": True, "rows": 0, "quality_score": 1.0}

    async def fake_sleep(_):
        return None

    def fake_insert_snapshot(table, batch_id, imported_at, rows):
        return len(rows)

    monkeypatch.setattr(app_module, "update_import_job", fake_update_import_job)
    monkeypatch.setattr(app_module, "_load_dataset_bytes", fake_load_dataset_bytes)
    monkeypatch.setattr(app_module.asyncio, "sleep", fake_sleep)
    monkeypatch.setattr(app_module, "audit_event", lambda *args, **kwargs: None)
    monkeypatch.setattr(db_module, "insert_snapshot", fake_insert_snapshot)

    processor = getattr(app_module, processor_name)
    result = asyncio.run(
        processor(
            job_id="job-1",
            batch_id="batch-1",
            imported_at="2026-02-13T00:00:00Z",
            datasets=datasets,
            idempotency_key="idem-1",
            raise_on_error=False,
        )
    )

    assert result is not None
    assert result["status"] == "imported"
    max_attempts = 1 + len(app_module.IMPORT_RETRY_BACKOFF_SECONDS)
    running_attempts = [
        c.get("metadata", {}).get("attempt")
        for c in calls
        if c.get("metadata", {}).get("attempt") is not None
    ]
    assert running_attempts[:2] == [1, 2]
    final = [c for c in calls if c.get("metadata", {}).get("attempts")][-1]
    assert final.get("metadata", {}).get("max_attempts") == max_attempts
    attempt_log = final.get("metadata", {}).get("attempts") or []
    assert len(attempt_log) == 2
    assert attempt_log[0].get("status") == "failed"
    assert attempt_log[1].get("status") == "succeeded"


def test_hr_processor_retries_and_captures_attempt_metadata(monkeypatch):
    _assert_processor_retries(
        monkeypatch,
        "_process_hr_import_job",
        {"payroll": {"content": b"x", "filename": "payroll.csv", "content_type": "text/csv"}},
    )


def test_ops_processor_retries_and_captures_attempt_metadata(monkeypatch):
    _assert_processor_retries(
        monkeypatch,
        "_process_ops_import_job",
        {"orders": {"content": b"x", "filename": "orders.csv", "content_type": "text/csv"}},
    )


def test_crm_processor_retries_and_captures_attempt_metadata(monkeypatch):
    _assert_processor_retries(
        monkeypatch,
        "_process_crm_import_job",
        {"pipeline": {"content": b"x", "filename": "pipeline.csv", "content_type": "text/csv"}},
    )


def test_ifrs_warnings_detect_finance_anomalies():
    bundle = ImportBundle(
        meta=ImportMeta(batch_id="b1", imported_at="2026-02-13T00:00:00Z"),
        ar=[
            {
                "invoice_id": "INV-1",
                "customer_id": "C1",
                "date": "2026-01-01",
                "amount": 100,
                "balance": 150,
                "due_date": "2026-01-31",
                "status": "Open",
            }
        ],
        ap=[
            {
                "bill_id": "B1",
                "vendor_id": "V1",
                "date": "2026-01-01",
                "amount": 100,
                "balance": 150,
                "due_date": "2026-01-31",
                "status": "Open",
            }
        ],
        gl=[
            {"period": "2026-01", "account_code": "4000", "account_name": "Sales", "debit": 0, "credit": 100},
            {"period": "2026-01", "account_code": "5000", "account_name": "COGS", "debit": 20, "credit": 0},
        ],
        customers=[],
        inventory=[],
        staff=[],
    )
    warnings = _ifrs_finance_lineage_warnings(bundle)
    codes = {w.get("code") for w in warnings}
    assert "ifrs_ar_balance_exceeds_amount" in codes
    assert "ifrs_ap_balance_exceeds_amount" in codes
    assert "ifrs_gl_unbalanced_period_totals" in codes


def test_ifrs_warnings_empty_for_balanced_finance_data():
    bundle = ImportBundle(
        meta=ImportMeta(batch_id="b2", imported_at="2026-02-13T00:00:00Z"),
        ar=[
            {
                "invoice_id": "INV-2",
                "customer_id": "C1",
                "date": "2026-01-01",
                "amount": 100,
                "balance": 80,
                "due_date": "2026-01-31",
                "status": "Partial",
            }
        ],
        ap=[
            {
                "bill_id": "B2",
                "vendor_id": "V1",
                "date": "2026-01-01",
                "amount": 100,
                "balance": 50,
                "due_date": "2026-01-31",
                "status": "Partial",
            }
        ],
        gl=[
            {"period": "2026-01", "account_code": "4000", "account_name": "Sales", "debit": 0, "credit": 100},
            {"period": "2026-01", "account_code": "1000", "account_name": "Cash", "debit": 100, "credit": 0},
        ],
        customers=[],
        inventory=[],
        staff=[],
    )
    warnings = _ifrs_finance_lineage_warnings(bundle)
    assert warnings == []


def test_lineage_key_is_deterministic_across_dataset_order():
    datasets_a = {
        "payroll": {"content": b"employee_id,salary\nEMP-1,1000\n"},
        "absences": {"content": b"employee_id,date,hours\nEMP-1,2026-01-01,8\n"},
    }
    datasets_b = {
        "absences": {"content": b"employee_id,date,hours\nEMP-1,2026-01-01,8\n"},
        "payroll": {"content": b"employee_id,salary\nEMP-1,1000\n"},
    }
    key_a = _build_deterministic_lineage_key(
        source_system="hr_upload",
        batch_id="b-1",
        imported_at="2026-02-14T00:00:00Z",
        datasets=datasets_a,
        counts={"payroll": 1, "absences": 1},
    )
    key_b = _build_deterministic_lineage_key(
        source_system="hr_upload",
        batch_id="b-1",
        imported_at="2026-02-14T00:00:00Z",
        datasets=datasets_b,
        counts={"payroll": 1, "absences": 1},
    )
    assert key_a == key_b
    assert len(key_a) == 64


def test_payroll_baseline_warnings_detect_anomalies():
    payroll_rows = [
        {"employee_id": "EMP-1", "salary": -1000, "overtime_hours": 2, "overtime_rate": 5},
        {"employee_id": "EMP-2", "salary": 2000, "overtime_hours": -1, "overtime_rate": 10},
    ]
    absence_rows = [
        {"employee_id": "EMP-1", "date": "2026-02-01", "hours": 30},
    ]
    warnings = _payroll_baseline_lineage_warnings(payroll_rows, absence_rows)
    codes = {w.get("code") for w in warnings}
    assert "payroll_negative_salary" in codes
    assert "payroll_negative_overtime_values" in codes
    assert "absence_hours_out_of_range" in codes


def test_compute_import_control_rollup_returns_score_and_density():
    lineage = {
        "payroll": {"rows": 10, "quality_score": 1.0},
        "absences": {"rows": 5, "quality_score": 1.0},
        "compliance": {
            "warnings": [
                {"code": "payroll_negative_salary", "level": "warning", "count": 2},
                {"code": "absence_hours_out_of_range", "level": "error", "count": 1},
            ]
        },
    }
    rollup = _compute_import_control_rollup(lineage, rejected_rows=1)
    assert rollup["framework"] == "finance_payroll_controls_v1"
    assert rollup["rows_total"] == 15
    assert rollup["warning_instances"] == 3
    assert rollup["control_score"] < 100
    assert "payroll_negative_salary" in rollup["warning_codes"]


def test_compute_import_control_rollup_respects_policy_config():
    lineage = {
        "payroll": {"rows": 10},
        "compliance": {
            "warnings": [
                {"code": "warn-1", "level": "warning", "count": 2},
            ]
        },
    }
    finance_policy = {
        "density_penalty_cap": 70,
        "severity_penalty_cap": 30,
        "rejection_penalty_cap": 20,
        "severity_penalty_multiplier": 12,
        "severity_weights": {"warning": 3},
    }
    payroll_policy = {
        "density_penalty_cap": 40,
        "severity_penalty_cap": 50,
        "rejection_penalty_cap": 20,
        "severity_penalty_multiplier": 8,
        "severity_weights": {"warning": 1},
    }
    finance_score = _compute_import_control_rollup(lineage, policy_config=finance_policy)["control_score"]
    payroll_score = _compute_import_control_rollup(lineage, policy_config=payroll_policy)["control_score"]
    assert finance_score != payroll_score


def test_import_job_detail_exposes_control_rollup(monkeypatch):
    token = make_admin_token()

    monkeypatch.setattr(
        "app.get_import_job",
        lambda _job_id: {
            "id": _job_id,
            "domain": "hr",
            "status": "succeeded",
            "lineage": {
                "payroll": {"rows": 4, "quality_score": 1.0},
                "absences": {"rows": 2, "quality_score": 1.0},
                "compliance": {
                    "warnings": [
                        {"code": "payroll_negative_overtime_values", "level": "warning", "count": 1}
                    ]
                },
            },
            "counts": {"payroll": 4, "absences": 2, "rejected_rows": 0},
            "metadata": {},
        },
    )
    monkeypatch.setattr(
        "app.get_import_policy",
        lambda _domain: {
            "controls_config": {
                "severity_weights": {"info": 1, "warning": 2, "error": 4, "critical": 6},
                "density_penalty_cap": 55,
                "severity_penalty_cap": 45,
                "rejection_penalty_cap": 20,
                "severity_penalty_multiplier": 9,
            }
        },
    )

    r = client.get(
        "/imports/jobs/11111111-1111-1111-1111-111111111111",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 200
    body = r.json()
    assert "control_rollup" in body
    assert body["control_rollup"]["framework"] == "finance_payroll_controls_v1"


def test_import_policy_preview_returns_delta(monkeypatch):
    token = make_admin_token()

    monkeypatch.setattr(
        "app.get_import_policy",
        lambda _domain: {
            "controls_config": {
                "severity_weights": {"info": 1, "warning": 2, "error": 4, "critical": 6},
                "density_penalty_cap": 60,
                "severity_penalty_cap": 40,
                "rejection_penalty_cap": 20,
                "severity_penalty_multiplier": 10,
            }
        },
    )

    payload = {
        "domain": "hr",
        "lineage": {
            "payroll": {"rows": 10, "quality_score": 1.0},
            "compliance": {
                "warnings": [
                    {"code": "payroll_negative_salary", "level": "warning", "count": 2}
                ]
            },
        },
        "rejected_rows": 1,
        "policy_override": {
            "severity_penalty_multiplier": 6,
            "density_penalty_cap": 40,
        },
    }
    r = client.post(
        "/imports/policy/preview",
        json=payload,
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["domain"] == "hr"
    assert "baseline" in body and "preview" in body and "delta" in body
    assert "control_score" in body["delta"]
    assert body["effective_policy"]["severity_penalty_multiplier"] == 6


def test_import_policy_preview_rejects_unknown_domain():
    token = make_admin_token()
    r = client.post(
        "/imports/policy/preview",
        json={"domain": "unknown", "lineage": {}, "rejected_rows": 0},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 400


def test_import_policy_activate_success(monkeypatch):
    token = make_admin_token()
    captured = {}

    monkeypatch.setattr(
        "app.activate_import_controls_policy",
        lambda **kwargs: {
            "domain": kwargs["domain"],
            "policy_version": kwargs["policy_version"],
            "controls_config": kwargs["controls_config"],
            "approved_by": kwargs["approved_by"],
            "approval_reason": kwargs["approval_reason"],
            "signature_hash_ref": kwargs["signature_hash_ref"],
            "active": True,
        },
    )

    def _audit(event_type, details, **kwargs):
        captured["event_type"] = event_type
        captured["details"] = details
        captured["kwargs"] = kwargs

    monkeypatch.setattr("app.audit_event", _audit)

    payload = {
        "domain": "sage",
        "policy_version": "2026.2",
        "schema_version": "2026.1",
        "approval_reason": "regulatory_alignment",
        "attestation_text": "I attest this policy activation is authorized.",
        "controls_config": {
            "severity_weights": {"info": 1, "warning": 2, "error": 4, "critical": 6},
            "density_penalty_cap": 65,
            "severity_penalty_cap": 35,
            "rejection_penalty_cap": 20,
            "severity_penalty_multiplier": 11,
        },
    }

    r = client.post(
        "/imports/policy/activate",
        json=payload,
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "activated"
    assert body["domain"] == "sage"
    assert body["policy_version"] == "2026.2"
    assert body["signature_hash_ref"]
    assert captured["event_type"] == "import_policy_activated"
    assert captured["kwargs"]["approval_reason"] == "regulatory_alignment"


def test_import_policy_activate_rejects_bad_controls_config():
    token = make_admin_token()
    bad_payload = {
        "domain": "hr",
        "approval_reason": "policy_update",
        "controls_config": {
            "severity_weights": {"warning": 2},
            "density_penalty_cap": -1,
            "severity_penalty_cap": 40,
            "rejection_penalty_cap": 20,
            "severity_penalty_multiplier": 9,
        },
    }
    r = client.post(
        "/imports/policy/activate",
        json=bad_payload,
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 400


def test_import_policy_history_endpoint(monkeypatch):
    token = make_admin_token()
    monkeypatch.setattr(
        "app.list_import_policy_versions",
        lambda domain, limit=20: [
            {
                "domain": domain,
                "policy_version": "2026.2",
                "active": True,
            }
        ],
    )
    r = client.get(
        "/imports/policy/history?domain=sage&limit=10",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["data"][0]["domain"] == "sage"
    assert body["data"][0]["policy_version"] == "2026.2"


def test_import_policy_rollback_success(monkeypatch):
    token = make_admin_token()
    captured = {}

    monkeypatch.setattr(
        "app.get_import_policy_version",
        lambda domain, version: {
            "domain": domain,
            "policy_version": version,
            "schema_version": "2026.1",
            "controls_config": {
                "severity_weights": {"info": 1, "warning": 2, "error": 4, "critical": 6},
                "density_penalty_cap": 65,
                "severity_penalty_cap": 35,
                "rejection_penalty_cap": 20,
                "severity_penalty_multiplier": 11,
            },
        },
    )
    monkeypatch.setattr("app.get_import_policy", lambda _domain: {"policy_version": "2026.3"})
    monkeypatch.setattr(
        "app.activate_import_controls_policy",
        lambda **kwargs: {
            "domain": kwargs["domain"],
            "policy_version": kwargs["policy_version"],
            "active": True,
        },
    )

    def _audit(event_type, details, **kwargs):
        captured["event_type"] = event_type
        captured["details"] = details
        captured["kwargs"] = kwargs

    monkeypatch.setattr("app.audit_event", _audit)

    payload = {
        "domain": "sage",
        "target_policy_version": "2026.2",
        "rollback_policy_version": "2026.2.rollback1",
        "approval_reason": "rollback_validation",
        "attestation_text": "I attest rollback is approved.",
    }
    r = client.post(
        "/imports/policy/rollback",
        json=payload,
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "rolled_back"
    assert body["from_policy_version"] == "2026.3"
    assert body["to_policy_version"] == "2026.2"
    assert captured["event_type"] == "import_policy_rollback"


def test_import_policy_rollback_not_found(monkeypatch):
    token = make_admin_token()
    monkeypatch.setattr("app.get_import_policy_version", lambda _d, _v: None)
    r = client.post(
        "/imports/policy/rollback",
        json={
            "domain": "hr",
            "target_policy_version": "2026.0",
            "approval_reason": "rollback_validation",
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 404


def test_ml_features_export_json(monkeypatch):
    token = make_admin_token()
    monkeypatch.setattr("app.get_promoted_kpi_batch", lambda _domain: {"batch_id": "b-ml-1"})

    def _snapshot(table, batch_id, limit=50000):
        assert batch_id == "b-ml-1"
        if table == "sage_ar_snapshot":
            return [{"amount": 100, "balance": 70}, {"amount": 50, "balance": 20}]
        if table == "sage_ap_snapshot":
            return [{"amount": 80, "balance": 30}]
        if table == "sage_gl_snapshot":
            return [{"debit": 130, "credit": 120}]
        if table == "sage_inventory_snapshot":
            return [{"quantity": 2}, {"quantity": 10}]
        if table == "sage_staff_snapshot":
            return [{"employee_id": "E1"}, {"employee_id": "E2"}]
        return []

    monkeypatch.setattr("app.get_snapshot_rows", _snapshot)
    monkeypatch.setattr("app.audit_event", lambda *args, **kwargs: None)

    r = client.get(
        "/ml/features/export?domain=sage&format=json",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["domain"] == "sage"
    assert body["batch_id"] == "b-ml-1"
    assert body["contract"]["contract_version"] == "ml_baseline_2026.1"
    assert "ar_total_amount" in body["features"]
    assert body["features"]["staff_count"] == 2


def test_ml_features_export_not_found_when_no_batch(monkeypatch):
    token = make_admin_token()
    monkeypatch.setattr("app.get_promoted_kpi_batch", lambda _domain: None)
    monkeypatch.setattr("app.get_latest_successful_import_batch", lambda _domain: None)
    r = client.get(
        "/ml/features/export?domain=hr&format=json",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 404


def test_ml_features_drift_summary_with_prior_baseline(monkeypatch):
    token = make_admin_token()
    monkeypatch.setattr("app.get_promoted_kpi_batch", lambda _domain: {"batch_id": "b-current"})
    monkeypatch.setattr(
        "app.list_import_jobs",
        lambda limit=100, domain=None, status=None: [
            {"batch_id": "b-current", "status": "succeeded", "domain": domain},
            {"batch_id": "b-prior", "status": "succeeded", "domain": domain},
        ],
    )

    def _snapshot(table, batch_id, limit=50000):
        if table == "sage_ar_snapshot":
            if batch_id == "b-current":
                return [{"amount": 100, "balance": 50}, {"amount": 60, "balance": 30}]
            if batch_id == "b-prior":
                return [{"amount": 80, "balance": 40}]
        if table == "sage_ap_snapshot":
            if batch_id == "b-current":
                return [{"amount": 70, "balance": 35}]
            if batch_id == "b-prior":
                return [{"amount": 50, "balance": 20}]
        if table == "sage_gl_snapshot":
            if batch_id == "b-current":
                return [{"debit": 170, "credit": 170}]  # equal debit/credit => gl_balance_gap = 0.0 (zero feature)
            if batch_id == "b-prior":
                return [{"debit": 130, "credit": 130}]
        if table == "sage_inventory_snapshot":
            if batch_id == "b-current":
                return [{"quantity": 0}, {"quantity": 3}]
            if batch_id == "b-prior":
                return [{"quantity": 4}]
        if table == "sage_staff_snapshot":
            if batch_id == "b-current":
                return [{"employee_id": "E1"}, {"employee_id": "E2"}]
            if batch_id == "b-prior":
                return [{"employee_id": "E1"}]
        return []

    monkeypatch.setattr("app.get_snapshot_rows", _snapshot)
    monkeypatch.setattr("app.audit_event", lambda *args, **kwargs: None)

    r = client.get(
        "/ml/features/drift/summary?domain=sage",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["domain"] == "sage"
    assert body["current"]["batch_id"] == "b-current"
    assert body["baseline"]["batch_id"] == "b-prior"
    assert body["drift"]["comparison_available"] is True
    assert body["drift"]["comparable_feature_count"] > 0
    assert "ar_total_amount" in body["drift"]["feature_deltas"]
    assert body["current"]["quality"]["zero_feature_count"] >= 1


def test_ml_features_drift_summary_without_prior_baseline(monkeypatch):
    token = make_admin_token()
    monkeypatch.setattr("app.get_promoted_kpi_batch", lambda _domain: {"batch_id": "b-current"})
    monkeypatch.setattr(
        "app.list_import_jobs",
        lambda limit=100, domain=None, status=None: [
            {"batch_id": "b-current", "status": "succeeded", "domain": domain},
        ],
    )

    def _snapshot(table, batch_id, limit=50000):
        if table == "hr_payroll_snapshot":
            return [{"employee_id": "EMP-1", "salary": 1000, "overtime_hours": 0, "overtime_rate": 10}]
        if table == "hr_absence_snapshot":
            return [{"employee_id": "EMP-1", "hours": 0}]
        return []

    monkeypatch.setattr("app.get_snapshot_rows", _snapshot)
    monkeypatch.setattr("app.audit_event", lambda *args, **kwargs: None)

    r = client.get(
        "/ml/features/drift/summary?domain=hr",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["baseline"]["batch_id"] is None
    assert body["baseline"]["features"] is None
    assert body["drift"]["comparison_available"] is False
    assert body["drift"]["comparable_feature_count"] == 0


def test_ml_features_drift_summary_applies_policy_severity(monkeypatch):
    token = make_admin_token()
    monkeypatch.setattr("app.get_promoted_kpi_batch", lambda _domain: {"batch_id": "b-current"})
    monkeypatch.setattr(
        "app.list_import_jobs",
        lambda limit=100, domain=None, status=None: [
            {"batch_id": "b-current", "status": "succeeded", "domain": domain},
            {"batch_id": "b-prior", "status": "succeeded", "domain": domain},
        ],
    )

    monkeypatch.setattr(
        "app.get_import_policy",
        lambda _domain: {
            "controls_config": {
                "ml_drift": {
                    "delta_thresholds": {
                        "pct_delta": {"warning": 0.1, "error": 0.2, "critical": 0.4},
                    },
                    "quality_thresholds": {
                        "zero_feature_rate": {"warning": 0.05, "error": 0.1, "critical": 0.15},
                    },
                }
            }
        },
    )

    def _snapshot(table, batch_id, limit=50000):
        if table == "sage_ar_snapshot":
            if batch_id == "b-current":
                return [{"amount": 160, "balance": 60}]
            return [{"amount": 80, "balance": 40}]
        if table == "sage_ap_snapshot":
            if batch_id == "b-current":
                return [{"amount": 70, "balance": 35}]
            return [{"amount": 50, "balance": 20}]
        if table == "sage_gl_snapshot":
            if batch_id == "b-current":
                return [{"debit": 170, "credit": 170}]
            return [{"debit": 130, "credit": 130}]
        if table == "sage_inventory_snapshot":
            if batch_id == "b-current":
                return [{"quantity": 0}]
            return [{"quantity": 4}]
        if table == "sage_staff_snapshot":
            if batch_id == "b-current":
                return [{"employee_id": "E1"}]
            return [{"employee_id": "E1"}]
        return []

    monkeypatch.setattr("app.get_snapshot_rows", _snapshot)
    monkeypatch.setattr("app.audit_event", lambda *args, **kwargs: None)

    r = client.get(
        "/ml/features/drift/summary?domain=sage",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["alerts"]["highest_severity"] in {"error", "critical"}
    assert any(a.get("category") == "drift" for a in body["alerts"]["alerts"])


def test_ml_features_drift_history_filters_and_summarizes(monkeypatch):
    token = make_admin_token()
    monkeypatch.setattr("app.get_import_policy", lambda _domain: {"controls_config": {}})
    monkeypatch.setattr(
        "app.list_audit_logs_filtered",
        lambda **kwargs: [
            {
                "details": {
                    "domain": "sage",
                    "generated_at": "2026-02-14T00:00:00Z",
                    "current_batch_id": "b-2",
                    "baseline_batch_id": "b-1",
                    "comparison_available": True,
                    "comparable_feature_count": 12,
                    "mean_absolute_delta": 10.5,
                    "mean_absolute_pct_delta": 0.21,
                    "highest_severity": "warning",
                    "severity_counts": {"warning": 2, "error": 0, "critical": 0},
                },
                "signature_hash_ref": "sig-1",
                "created_at": "2026-02-14T00:00:00Z",
            },
            {
                "details": {
                    "domain": "sage",
                    "generated_at": "2026-02-13T00:00:00Z",
                    "current_batch_id": "b-1",
                    "baseline_batch_id": "b-0",
                    "comparison_available": True,
                    "comparable_feature_count": 12,
                    "mean_absolute_delta": 6.5,
                    "mean_absolute_pct_delta": 0.1,
                    "highest_severity": "error",
                    "severity_counts": {"warning": 0, "error": 1, "critical": 0},
                },
                "signature_hash_ref": "sig-2",
                "created_at": "2026-02-13T00:00:00Z",
            },
            {
                "details": {
                    "domain": "hr",
                    "generated_at": "2026-02-12T00:00:00Z",
                    "comparison_available": True,
                    "comparable_feature_count": 5,
                    "mean_absolute_delta": 3.0,
                    "mean_absolute_pct_delta": 0.08,
                    "highest_severity": "warning",
                    "severity_counts": {"warning": 1, "error": 0, "critical": 0},
                },
                "signature_hash_ref": "sig-3",
                "created_at": "2026-02-12T00:00:00Z",
            },
        ],
    )

    r = client.get(
        "/ml/features/drift/history?domain=sage&limit=2",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["domain"] == "sage"
    assert body["count"] == 2
    assert body["summary"]["comparison_count"] == 2
    assert body["summary"]["severity_counts"]["warning"] == 2
    assert body["summary"]["severity_counts"]["error"] == 1


def test_ml_features_drift_acknowledge_success(monkeypatch):
    token = make_admin_token()
    monkeypatch.setattr(
        "app.list_audit_logs_filtered",
        lambda **kwargs: [
            {
                "details": {
                    "domain": "sage",
                    "current_batch_id": "b-10",
                    "status": "triaged",
                },
                "created_at": "2026-02-13T00:00:00Z",
                "signature_hash_ref": "sig-old",
            }
        ],
    )
    monkeypatch.setattr("app.audit_event", lambda *args, **kwargs: None)

    payload = {
        "domain": "sage",
        "current_batch_id": "b-10",
        "status": "in_progress",
        "owner_id": "risk-owner-1",
        "remediation_notes": "Investigating variance and updating mappings.",
        "remediation_actions": ["Validate source extract", "Reconcile deltas"],
        "due_at": "2026-02-20T00:00:00Z",
        "reason_code": "drift_triage",
    }
    r = client.post(
        "/ml/features/drift/acknowledge",
        json=payload,
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "acknowledged"
    assert body["ack"]["status"] == "in_progress"
    assert body["ack"]["previous_status"] == "triaged"
    assert body["signature_hash_ref"]


def test_ml_features_drift_acknowledge_rejects_invalid_transition(monkeypatch):
    token = make_admin_token()
    monkeypatch.setattr(
        "app.list_audit_logs_filtered",
        lambda **kwargs: [
            {
                "details": {
                    "domain": "hr",
                    "current_batch_id": "b-20",
                    "status": "resolved",
                },
            }
        ],
    )

    payload = {
        "domain": "hr",
        "current_batch_id": "b-20",
        "status": "triaged",
        "reason_code": "reopen_check",
    }
    r = client.post(
        "/ml/features/drift/acknowledge",
        json=payload,
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 400


def test_ml_features_drift_remediation_export_json(monkeypatch):
    token = make_admin_token()
    monkeypatch.setattr(
        "app.list_audit_logs_filtered",
        lambda **kwargs: [
            {
                "details": {
                    "domain": "sage",
                    "current_batch_id": "b-10",
                    "status": "in_progress",
                    "previous_status": "triaged",
                    "owner_id": "risk-owner-1",
                    "due_at": "2026-02-20T00:00:00Z",
                    "reason_code": "drift_triage",
                    "remediation_notes": "Investigating variance.",
                    "remediation_actions": ["Reconcile delta", "Patch mapping"],
                    "acknowledged_at": "2026-02-14T00:00:00Z",
                },
                "signature_hash_ref": "sig-ack-1",
                "created_at": "2026-02-14T00:00:00Z",
            },
            {
                "details": {
                    "domain": "hr",
                    "current_batch_id": "b-11",
                    "status": "triaged",
                },
                "signature_hash_ref": "sig-ack-2",
                "created_at": "2026-02-13T00:00:00Z",
            },
        ],
    )
    monkeypatch.setattr("app.audit_event", lambda *args, **kwargs: None)

    r = client.get(
        "/ml/features/drift/remediation/export?domain=sage&format=json&limit=10",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["domain"] == "sage"
    assert body["count"] == 1
    assert body["data"][0]["current_batch_id"] == "b-10"
    assert body["data"][0]["owner_id"] == "risk-owner-1"


def test_ml_features_drift_scorecard_kpis_and_sla(monkeypatch):
    token = make_admin_token()

    monkeypatch.setattr(
        "app.get_import_policy",
        lambda _domain: {
            "controls_config": {
                "ml_drift": {
                    "sla_thresholds": {
                        "ack_hours_warning": 1,
                        "ack_hours_breach": 2,
                        "resolve_hours_warning": 2,
                        "resolve_hours_breach": 4,
                    }
                }
            }
        },
    )

    def _audit_rows(**kwargs):
        event_type = kwargs.get("event_type")
        if event_type == "ml_feature_drift_summarized":
            return [
                {
                    "details": {
                        "domain": "sage",
                        "current_batch_id": "b-2",
                        "generated_at": "2026-02-10T00:00:00Z",
                        "highest_severity": "critical",
                        "severity_counts": {"warning": 1, "error": 1, "critical": 1},
                    },
                    "signature_hash_ref": "sig-sum-2",
                },
                {
                    "details": {
                        "domain": "sage",
                        "current_batch_id": "b-1",
                        "generated_at": "2026-02-13T00:00:00Z",
                        "highest_severity": "warning",
                        "severity_counts": {"warning": 2, "error": 0, "critical": 0},
                    },
                    "signature_hash_ref": "sig-sum-1",
                },
            ]
        if event_type == "ml_feature_drift_acknowledged":
            return [
                {
                    "details": {
                        "domain": "sage",
                        "current_batch_id": "b-2",
                        "status": "triaged",
                        "acknowledged_at": "2026-02-10T03:00:00Z",
                        "owner_id": "owner-1",
                    },
                    "signature_hash_ref": "sig-ack-2",
                },
                {
                    "details": {
                        "domain": "sage",
                        "current_batch_id": "b-2",
                        "status": "resolved",
                        "acknowledged_at": "2026-02-10T06:00:00Z",
                        "owner_id": "owner-1",
                    },
                    "signature_hash_ref": "sig-ack-2r",
                },
            ]
        return []

    monkeypatch.setattr("app.list_audit_logs_filtered", _audit_rows)
    monkeypatch.setattr("app.audit_event", lambda *args, **kwargs: None)

    r = client.get(
        "/ml/features/drift/scorecard?domain=sage&limit=10",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["domain"] == "sage"
    assert body["count"] == 2
    assert body["kpis"]["open_high_severity_count"] == 0
    assert body["kpis"]["pending_ack_count"] == 1
    assert body["kpis"]["resolve_breach_count"] >= 1
    assert body["signature_hash_ref"]


def test_ml_features_drift_scorecard_rejects_invalid_domain():
    token = make_admin_token()
    r = client.get(
        "/ml/features/drift/scorecard?domain=ops",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 400


def test_ml_features_drift_escalations_groups_owner_alerts(monkeypatch):
    token = make_admin_token()

    monkeypatch.setattr(
        "app._build_ml_drift_scorecard",
        lambda domain, limit=50: {
            "domain": domain,
            "count": 3,
            "trend": [
                {
                    "batch_id": "b-1",
                    "highest_severity": "critical",
                    "current_status": "in_progress",
                    "owner_id": "owner-a",
                    "pending_resolve_age_hours": 200,
                    "pending_ack_age_hours": 5,
                    "generated_at": "2026-02-10T00:00:00Z",
                    "sla": {"resolve": "breach"},
                },
                {
                    "batch_id": "b-2",
                    "highest_severity": "error",
                    "current_status": "triaged",
                    "owner_id": None,
                    "pending_resolve_age_hours": 80,
                    "pending_ack_age_hours": 4,
                    "generated_at": "2026-02-11T00:00:00Z",
                    "sla": {"resolve": "warning"},
                },
                {
                    "batch_id": "b-3",
                    "highest_severity": "warning",
                    "current_status": "in_progress",
                    "owner_id": "owner-b",
                    "pending_resolve_age_hours": 20,
                    "pending_ack_age_hours": 2,
                    "generated_at": "2026-02-12T00:00:00Z",
                    "sla": {"resolve": "ok"},
                },
            ],
        },
    )
    monkeypatch.setattr("app.audit_event", lambda *args, **kwargs: None)

    r = client.get(
        "/ml/features/drift/escalations?domain=sage&limit=10",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["domain"] == "sage"
    assert body["count"] == 2
    assert len(body["owner_alerts"]) == 2
    assert body["owner_alerts"][0]["highest_severity"] in {"critical", "error"}


def test_ml_features_drift_reminders_preview_filters_threshold(monkeypatch):
    token = make_admin_token()
    monkeypatch.setattr(
        "app._build_ml_drift_scorecard",
        lambda domain, limit=50: {
            "domain": domain,
            "count": 3,
            "trend": [
                {
                    "batch_id": "b-1",
                    "current_status": "in_progress",
                    "owner_id": "owner-a",
                    "highest_severity": "critical",
                    "pending_resolve_age_hours": 50,
                },
                {
                    "batch_id": "b-2",
                    "current_status": "resolved",
                    "owner_id": "owner-b",
                    "highest_severity": "error",
                    "pending_resolve_age_hours": 100,
                },
                {
                    "batch_id": "b-3",
                    "current_status": "triaged",
                    "owner_id": None,
                    "highest_severity": "warning",
                    "pending_resolve_age_hours": 10,
                },
            ],
        },
    )
    monkeypatch.setattr("app.get_import_policy", lambda _domain: {"controls_config": {}})
    monkeypatch.setattr("app.audit_event", lambda *args, **kwargs: None)

    r = client.post(
        "/ml/features/drift/reminders/preview",
        json={"domain": "hr", "limit": 10, "min_open_hours": 24},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["domain"] == "hr"
    assert body["count"] == 1
    assert body["reminders"][0]["batch_id"] == "b-1"


def test_ml_train_demand_forecast_model_registers_manifest(monkeypatch):
    token = make_admin_token()
    monkeypatch.setattr(
        "app.stock_turnover_series",
        lambda periods=24: {
            "series": [
                {"period": "2026-01", "turnover": 10},
                {"period": "2026-02", "turnover": 11},
                {"period": "2026-03", "turnover": 12},
                {"period": "2026-04", "turnover": 13},
                {"period": "2026-05", "turnover": 14},
                {"period": "2026-06", "turnover": 15},
                {"period": "2026-07", "turnover": 16},
                {"period": "2026-08", "turnover": 17},
            ]
        },
    )
    monkeypatch.setattr(
        "app._build_ml_drift_scorecard",
        lambda domain, limit=30: {
            "domain": domain,
            "kpis": {
                "open_high_severity_count": 0,
                "resolve_breach_count": 0,
                "pending_ack_count": 0,
            },
        },
    )
    monkeypatch.setattr("app.audit_event", lambda *args, **kwargs: None)

    r = client.post(
        "/ml/models/demand-forecast/train",
        json={"domain": "ops", "approve_if_ready": True, "max_mae_ratio": 0.5},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["manifest"]["model_key"] == "demand_forecast_ops"
    assert body["manifest"]["domain"] == "ops"
    assert body["manifest"]["readiness"]["is_ready"] is True
    assert body["manifest"]["status"] in {"promoted", "registered_ready"}


def test_ml_predict_demand_forecast_uses_registered_manifest(monkeypatch):
    token = make_admin_token()
    monkeypatch.setattr(
        "app.list_audit_logs_filtered",
        lambda **kwargs: [
            {
                "details": {
                    "domain": "ops",
                    "model_key": "demand_forecast_ops",
                    "model_version": "20260214010101",
                    "status": "promoted",
                    "model": {"kind": "linear_trend_v1", "params": {"intercept": 2.0, "slope": 0.5}},
                },
                "created_at": "2026-02-14T01:01:01Z",
                "signature_hash_ref": "sig-model-1",
            }
        ],
    )
    monkeypatch.setattr(
        "app.stock_turnover_series",
        lambda periods=24: {"series": [{"period": "2026-01", "turnover": 1.0}] * 8},
    )
    monkeypatch.setattr("app.audit_event", lambda *args, **kwargs: None)

    r = client.post(
        "/ml/models/demand-forecast/predict",
        json={"domain": "ops", "horizon": 3},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["model_key"] == "demand_forecast_ops"
    assert body["model_version"] == "20260214010101"
    assert len(body["predictions"]) == 3


def test_ml_list_demand_forecast_manifests(monkeypatch):
    token = make_admin_token()
    monkeypatch.setattr(
        "app.list_audit_logs_filtered",
        lambda **kwargs: [
            {
                "details": {
                    "domain": "ops",
                    "model_key": "demand_forecast_ops",
                    "model_version": "20260214010101",
                    "status": "promoted",
                    "training": {"mae": 0.12},
                    "readiness": {"is_ready": True},
                    "registered_at": "2026-02-14T01:01:01Z",
                },
                "signature_hash_ref": "sig-model-1",
            }
        ],
    )
    r = client.get(
        "/ml/models/demand-forecast/manifests?domain=ops&limit=10",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["domain"] == "ops"
    assert body["count"] == 1
    assert body["data"][0]["model_version"] == "20260214010101"