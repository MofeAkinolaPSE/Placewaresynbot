# --- Tracking Webhook Models (registered after app is created below) ---
from pydantic import BaseModel as _BaseModel


class TrackingWebhookPayload(_BaseModel):
    tracking_id: str
    status: str
    eta: str | None = None
    signature: str | None = None
    event_time: str | None = None
    provider: str | None = None
    idempotency_key: str | None = None

def _verify_signature(payload: dict, signature: str | None) -> bool:
    try:
        from src.constants import WEBHOOK_SECRET
        import hmac, hashlib, json

        if not signature:
            return False
        if not WEBHOOK_SECRET:
            # No secret configured -> reject by default
            return False
        # Create canonical payload without signature
        p = dict(payload)
        p.pop("signature", None)
        serialized = json.dumps(p, sort_keys=True, separators=(",", ":")).encode("utf-8")
        digest = hmac.new(WEBHOOK_SECRET.encode("utf-8"), serialized, hashlib.sha256).hexdigest()
        return hmac.compare_digest(digest, signature)
    except Exception:
        return False


def _is_idempotent(tracking_id: str, idempotency_key: str | None) -> bool:
    try:
        if not idempotency_key:
            return False
        from src.db import is_webhook_idempotent

        return is_webhook_idempotent(idempotency_key)
    except Exception:
        return False

# --- Webhook Endpoint (registered on real app after FastAPI() below) ---
async def webhook_tracking_update(payload: TrackingWebhookPayload):
    # Signature verification
    if not _verify_signature(payload.dict(), payload.signature):
        raise HTTPException(status_code=401, detail="Invalid signature")
    # Idempotency check
    if payload.idempotency_key and _is_idempotent(payload.tracking_id, payload.idempotency_key):
        return {"status": "duplicate", "tracking_id": payload.tracking_id}
    # Validate status
    from src.constants import ORDER_STATUS_ALLOWED
    new_status = payload.status.strip().lower()
    if new_status not in ORDER_STATUS_ALLOWED:
        raise HTTPException(status_code=400, detail=f"Invalid tracking status: {new_status}")
    # Update tracking record
    from src.db import db, TABLE_TRACKING
    now_iso = payload.event_time or dt.datetime.utcnow().replace(microsecond=0).isoformat() + "Z"
    resp = db.table(TABLE_TRACKING).select("id").eq("id", payload.tracking_id).limit(1).execute()
    rows = resp.data or []
    if not rows:
        raise HTTPException(status_code=404, detail="Tracking record not found")
    db.table(TABLE_TRACKING).update({"status": new_status, "last_update": now_iso, "eta": payload.eta or "pending"}).eq("id", payload.tracking_id).execute()
    # Audit event
    from src.db import audit_event
    audit_event(
        "tracking_webhook_update",
        {
            "tracking_id": payload.tracking_id,
            "status": new_status,
            "provider": payload.provider,
            "idempotency_key": payload.idempotency_key,
        },
        event_class="tracking_webhook",
        action="webhook_tracking_update",
        outcome="success",
        subject_type="tracking",
        subject_id=payload.tracking_id,
    )
    # Record idempotency key for fast future checks
    try:
        if payload.idempotency_key:
            from src.db import record_webhook_idempotency

            record_webhook_idempotency(payload.idempotency_key, payload.tracking_id, payload.provider, payload.dict())
    except Exception:
        pass
    return {"status": "updated", "tracking_id": payload.tracking_id, "new_status": new_status}
from dotenv import load_dotenv

# Load env immediately; override=True ensures .env always wins over stale
# Windows system environment variables (e.g. old EMAIL_FROM set in a prior session).
load_dotenv(override=True)

from fastapi import FastAPI, HTTPException, Request, UploadFile, File, Depends, BackgroundTasks
from fastapi.exceptions import RequestValidationError
from fastapi.exception_handlers import request_validation_exception_handler
from fastapi.responses import JSONResponse, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import OAuth2PasswordRequestForm
from pydantic import BaseModel, Field
from typing import Optional, Any
from src.retrieval import QnARetriever
from src.db import store_lead
from src.embed_proxy import get_embedding
from src.constants import (
    EMBEDDING_DIM,
    DEFAULT_TOP_K,
    append_disclaimer,
    MATCH_THRESHOLD,
    BOT_NAME,
    BOT_BRAND,
    DEV_TOKEN_ENABLED,
    JWT_SECRET,
    CORS_ALLOW_ORIGINS,
    PROJECT_STATUS_ALLOWED,
    PROJECT_WORKFLOW_STAGES,
    PROJECT_STAGE_TRANSITIONS,
    PROJECT_QC_STATUS_ALLOWED,
    PROJECT_QC_APPROVED_STATUSES,
    PROJECT_QC_GATED_STAGES,
    SCOPE_STATUS_ALLOWED,
    COST_STATUS_ALLOWED,
    RISK_STATUS_ALLOWED,
    CHANGE_STATUS_ALLOWED,
    SCOPE_STATUS_TRANSITIONS,
    COST_STATUS_TRANSITIONS,
    RISK_STATUS_TRANSITIONS,
    CHANGE_STATUS_TRANSITIONS,
    ORDER_STATUS_ALLOWED,
    ORDER_STATUS_TRANSITIONS,
    HIGH_IMPACT_SCOPE_LEVELS,
    HIGH_IMPACT_COST_THRESHOLD,
    HIGH_IMPACT_SCHEDULE_DAYS_THRESHOLD,
    HIGH_IMPACT_APPROVAL_REASONS,
    RISK_SCORE_MITIGATION_THRESHOLD,
    RISK_SCORE_OWNER_THRESHOLD,
    WIDGET_SITE_KEYS,
)
from pydantic import BaseModel

# --- Order Status Update Models ---
class OrderStatusUpdateRequest(BaseModel):
    status: str
    reason_code: str | None = None

def _is_allowed_order_transition(current_status: str, target_status: str) -> bool:
    if current_status == target_status:
        return True
    return target_status in ORDER_STATUS_TRANSITIONS.get(current_status, set())

# --- Order Status Update Endpoint (registered on real app after FastAPI() below) ---
async def update_order_status(request: Request, order_id: str, payload: OrderStatusUpdateRequest):
    require_role(request, "admin")
    # Fetch current order
    from src.db import db, TABLE_ORDERS, TABLE_TRACKING
    resp = db.table(TABLE_ORDERS).select("id,status").eq("id", order_id).limit(1).execute()
    rows = resp.data or []
    if not rows:
        raise HTTPException(status_code=404, detail="Order not found")
    current_status = str(rows[0].get("status") or "").strip().lower()
    new_status = payload.status.strip().lower()
    if new_status not in ORDER_STATUS_ALLOWED:
        raise HTTPException(status_code=400, detail=f"Invalid order status: {new_status}")
    if not _is_allowed_order_transition(current_status, new_status):
        raise HTTPException(status_code=409, detail=f"Transition not allowed: {current_status} -> {new_status}")
    # Update order status
    db.table(TABLE_ORDERS).update({"status": new_status}).eq("id", order_id).execute()
    # Update tracking status if exists
    tracking_resp = db.table(TABLE_TRACKING).select("id").eq("order_id", order_id).limit(1).execute()
    tracking_rows = tracking_resp.data or []
    if tracking_rows:
        tracking_id = tracking_rows[0]["id"]
        now_iso = dt.datetime.utcnow().replace(microsecond=0).isoformat() + "Z"
        db.table(TABLE_TRACKING).update({"status": new_status, "last_update": now_iso}).eq("id", tracking_id).execute()
    # Audit event
    actor_id = request.state.user.get("sub") if hasattr(request.state, "user") else None
    audit_event(
        "order_status_updated",
        {
            "order_id": order_id,
            "from": current_status,
            "to": new_status,
            "reason_code": payload.reason_code,
        },
        actor_id=actor_id,
        event_class="order_workflow",
        action="update_order_status",
        outcome="success",
        reason_code=payload.reason_code or new_status,
        subject_type="order",
        subject_id=order_id,
    )
    return {"order_id": order_id, "from": current_status, "to": new_status, "status": "updated"}
from src.llm_client import LLMClient  # new microservice-based LLM abstraction (to be added)
from src.middleware import verify_jwt, rate_limit, RequestTimingMiddleware
from src.db import (
    db,
    audit_event, 
    insert_snapshot,
    SnapshotInsertError,
    save_intent, 
    save_approval, 
    list_pending_intents, 
    is_duplicate_import, 
    save_chat_history, 
    get_chat_history,
    get_audit_logs,
    create_import_job,
    update_import_job,
    insert_import_rejections,
    set_promoted_kpi_batch,
    find_import_job_by_idempotency,
    get_import_job,
    get_import_policy,
    activate_import_controls_policy,
    list_import_policy_versions,
    get_import_policy_version,
    get_promoted_kpi_batch,
    get_latest_successful_import_batch,
    get_snapshot_rows,
    list_import_jobs,
    get_user_by_email,
    get_user_by_id,
    insert_refresh_token,
    get_refresh_token_record,
    revoke_refresh_token,
    list_users,
    create_user,
    update_user_password,
    toggle_user_active,
    store_order,
    get_tracking,
    create_project_record,
    list_projects,
    get_project,
    update_project_stage,
    create_scope_item,
    list_scope_items,
    get_scope_item,
    update_scope_item_status,
    create_cost_item,
    list_cost_items,
    get_cost_item,
    update_cost_item_status,
    create_risk_item,
    list_risk_items,
    get_risk_item,
    update_risk_item_status,
    create_change_request,
    list_change_requests,
    get_change_request,
    decide_change_request,
    get_controls_rollup,
    list_audit_logs_filtered,
    _compute_signature_hash_ref,
    AuthStoreUnavailableError,
    get_psycopg_dsn,
)
from src.auth_utils import (
    create_access_token,
    create_refresh_token,
    hash_refresh_token,
    parse_iso8601,
    verify_password,
    hash_password,
)
from src.services.sage_adapter.schemas import ImportBundle, ImportMeta
from src.services.sage_adapter.validators import (
    resolve_headers,
    canonicalize_rows,
    REQUIRED_CUSTOMERS,
    REQUIRED_AR,
    REQUIRED_AP,
    REQUIRED_GL,
    REQUIRED_INVENTORY,
    REQUIRED_STAFF,
    ALIASES_CUSTOMERS,
    ALIASES_AR,
    ALIASES_AP,
    ALIASES_GL,
    ALIASES_INVENTORY,
    ALIASES_STAFF,
    ALIASES_HR_PAYROLL,
    ALIASES_HR_ABSENCES,
    ALIASES_OPS_ORDERS,
    ALIASES_OPS_DOWNTIME,
    ALIASES_CRM_PIPELINE,
)
from src.services.sage_adapter.parser import parse_tabular_upload
from src.services.sage_adapter.normalizer import (
    to_customers,
    to_ar,
    to_ap,
    to_gl,
    to_inventory,
    to_staff,
)
from src.services.sage_adapter.service import latest_inventory_snapshot, inventory_by_skus, ar_trend_summary, kpis, ar_aging_buckets, ar_aging_customers
from src.services.forecasting import forecast_ar_balance
from src.services.hr import payroll_and_absence_summary
from src.services.ops import kpis as ops_kpis, forecast_stock_turnover, stock_turnover_series
from src.services.crm import risk_scores as crm_risk_scores
from src.services.staff_ops import sync_staff_batch
from src.services.inventory import get_expiring_inventory, schedule_expiry_monitor
from src.services.intelligence import executive_summary, compute_change_pct, trend_label, risk_signals, opportunities_from_risks, recommendations, anomaly_signals
from src.services.tool_registry import (
    build_default_tool_registry,
    ToolExecutionError,
    ToolPermissionError,
)
from src.routers import analytics, inventory, staff_ops, dashboard, procurement_import
from src.deepseek import DeepSeek
from src.constants import LLM_PROVIDER, DEEPSEEK_API_KEY

import os
import asyncio
import csv
from io import StringIO
import hashlib
import json
from dotenv import load_dotenv
import logging
import yaml
import requests
import jwt
import datetime as dt
import re
import uuid
from urllib.parse import urlparse
import socket

# Optional: local embedding for text queries
# try:
#     from sentence_transformers import SentenceTransformer
#     _st_model: Any | None = None
# except Exception:
#     SentenceTransformer = None  # type: ignore
#     _st_model = None

load_dotenv(override=True)

app = FastAPI()

# Prometheus metrics — exposes /metrics for Grafana scraping (internal network only).
# Tracks request rate, latency histograms (P50/P95/P99), and error rates per endpoint.
from prometheus_fastapi_instrumentator import Instrumentator as _Instrumentator
_Instrumentator().instrument(app).expose(app, include_in_schema=False)

# ── Pending email draft store (confirmation-before-send flow) ─────────────────
# Keyed by user_id (or IP fallback). Draft expires after 10 minutes.
# Structure: { user_key → {subject, body, to_email, department, original_request, expires_at} }
_PENDING_EMAIL_DRAFTS: dict = {}
_EMAIL_DRAFT_TTL_SECONDS = 600  # 10 minutes


def _draft_key(auth_payload: dict, request: "Request") -> str:  # type: ignore[name-defined]
    uid = (auth_payload or {}).get("sub") or (auth_payload or {}).get("id")
    if uid:
        return str(uid)
    client = getattr(request, "client", None)
    return str(getattr(client, "host", "anonymous"))


def _is_email_confirmation(text: str) -> bool:
    """Return True if the message is a short affirmative confirming a pending draft."""
    tl = text.strip().lower()
    if len(tl) > 120:
        return False
    phrases = [
        "yes", "send it", "send the email", "go ahead", "looks good", "approved",
        "confirm", "confirmed", "proceed", "ok send", "that's fine", "that's good",
        "send that", "yes send", "yes please", "yep", "yeah", "okay", "ok",
        "do it", "send now", "sure", "correct", "right", "fine", "good",
        "sounds good", "perfect", "great", "send", "approve", "ship it",
    ]
    return any(tl == p or tl.startswith(p + " ") or tl.endswith(" " + p) for p in phrases)


def _is_email_rejection(text: str) -> bool:
    """Return True if the message cancels a pending draft."""
    tl = text.strip().lower()
    if len(tl) > 120:
        return False
    phrases = ["no", "don't send", "dont send", "cancel", "nevermind", "never mind",
               "abort", "stop", "discard", "scratch that", "forget it"]
    return any(tl == p or tl.startswith(p + " ") or tl.endswith(" " + p) for p in phrases)


@app.exception_handler(RequestValidationError)
async def _log_validation_error(request: Request, exc: RequestValidationError):
    logging.error(
        "422 Unprocessable Entity: %s %s — errors: %s",
        request.method,
        request.url.path,
        exc.errors(),
    )
    return await request_validation_exception_handler(request, exc)


app.include_router(analytics.router)
app.include_router(inventory.router)
app.include_router(staff_ops.router)
app.include_router(dashboard.router)
app.include_router(procurement_import.router)
from src.routers.workflow import router as workflow_router
app.include_router(workflow_router)
from src.routers.custody import router as custody_router
app.include_router(custody_router)
from src.routers.promotions import router as promotions_router
app.include_router(promotions_router)
from src.routers.cache_ui import router as cache_router
app.include_router(cache_router)
from src.routers.replenishment import router as replenishment_router
from src.routers.billing import router as billing_router
from src.routers.agents_exec import router as agents_exec_router
from src.routers.iot import router as iot_router
from src.routers.operational_events import router as operational_events_router
from src.routers.staff_dashboard import router as staff_dashboard_router
from src.routers.schema_registry import router as schema_registry_router
from src.routers.workflow_engine import router as workflow_engine_router
from src.routers.reconciliation import router as reconciliation_router
from src.routers.inventory_module import router as inventory_module_router
from src.routers.suppliers import router as suppliers_router
from src.routers.logistics import router as logistics_router
from src.routers.documents import router as documents_router
from src.routers.compliance import router as compliance_router
from src.routers.threads import router as threads_router
from src.routers.form_schemas import router as form_schemas_router
from src.routers.crm import router as crm_router
from src.routers.eos import router as eos_router
from src.routers.crm_360 import router as crm_360_router
from src.routers.calendar_tasks import router as calendar_router, tasks_router
from src.routers.realtime_ws import router as realtime_ws_router
from src.routers.kg_graph import router as kg_graph_router
from src.routers.data_ingest import router as data_ingest_router
from src.routers.sage_csv_import import router as sage_csv_import_router
from src.routers.knowledge_router import router as knowledge_router
from src.routers.maintenance_tracking import router as maintenance_tracking_router
from src.routers.digital_twin import router as digital_twin_router
from src.routers.capability_discovery import router as capability_discovery_router
from src.routers.crm_sales import router as crm_sales_router
from src.routers.frontdesk import router as frontdesk_router
from src.routers.finance import router as finance_router
from src.routers.qc import router as qc_router
from src.routers.reports import router as reports_router

app.include_router(crm_sales_router)
app.include_router(frontdesk_router)
app.include_router(qc_router)
app.include_router(finance_router)
app.include_router(reports_router)
app.include_router(sage_csv_import_router)
app.include_router(replenishment_router)
app.include_router(billing_router)
app.include_router(agents_exec_router)
app.include_router(iot_router)
app.include_router(operational_events_router)
app.include_router(staff_dashboard_router)
app.include_router(schema_registry_router)
app.include_router(workflow_engine_router)
app.include_router(reconciliation_router)
app.include_router(inventory_module_router)
app.include_router(suppliers_router)
app.include_router(logistics_router)
app.include_router(documents_router)
app.include_router(compliance_router)
app.include_router(threads_router)
app.include_router(form_schemas_router)
app.include_router(crm_router)
app.include_router(eos_router)
app.include_router(crm_360_router)
app.include_router(calendar_router)
app.include_router(tasks_router)
app.include_router(realtime_ws_router)
app.include_router(kg_graph_router)
app.include_router(data_ingest_router)
app.include_router(knowledge_router)
app.include_router(maintenance_tracking_router)
app.include_router(digital_twin_router)
app.include_router(capability_discovery_router)

# Sage 50 live integration routers
from src.routers.sage_live import router as sage_live_router, webhook_router as sage_webhook_router
app.include_router(sage_live_router)
app.include_router(sage_webhook_router)

# Register tracking webhook + order status endpoints on the real app
app.add_api_route("/webhook/tracking", webhook_tracking_update, methods=["POST"])
app.add_api_route("/orders/{order_id}/status", update_order_status, methods=["POST"])


@app.on_event("startup")
async def _start_weekly_report_scheduler():
    try:
        from src.services.scheduler import start_scheduler
        start_scheduler()
    except Exception:
        pass


@app.on_event("startup")
async def _start_kpi_watchdog():
    import os
    import asyncio
    if os.getenv("KPI_WATCHDOG_ENABLED", "1") not in ("0", "false", "False"):
        try:
            from src.services.kpi_watchdog import get_watchdog
            watchdog = get_watchdog()
            asyncio.create_task(watchdog.run_loop())
        except Exception:
            pass


@app.on_event("startup")
async def _start_workflow_processor():
    try:
        import asyncio
        from src.workflow.engine import engine

        loop = asyncio.get_event_loop()
        # run background processor as a task
        loop.create_task(engine.run_processor())
    except Exception:
        pass


@app.on_event("startup")
async def _start_supplier_intel():
    try:
        import asyncio
        from src.services.supplier_intel import compute_supplier_metrics

        async def _work():
            while True:
                try:
                    compute_supplier_metrics()
                except Exception:
                    pass
                await asyncio.sleep(60 * 10)

        loop = asyncio.get_event_loop()
        loop.create_task(_work())
    except Exception:
        pass


@app.on_event("startup")
async def _start_agent_subscriptions():
    try:
        import asyncio
        from src.services.agent_subscriptions import start_processor

        loop = asyncio.get_event_loop()
        start_processor(loop, interval=5)
    except Exception:
        pass


@app.on_event("startup")
async def _start_maintenance_monitor():
    try:
        import asyncio
        from src.services.maintenance_service import MaintenanceMonitor

        loop = asyncio.get_event_loop()
        loop.create_task(MaintenanceMonitor(interval_seconds=300).run_loop())
    except Exception:
        pass


@app.on_event("startup")
async def _start_digital_twin_engine():
    try:
        import asyncio
        from src.services.digital_twin_service import DigitalTwinEngine

        loop = asyncio.get_event_loop()
        loop.create_task(DigitalTwinEngine(interval_seconds=600).run_loop())
    except Exception:
        pass


@app.on_event("startup")
async def _start_capability_discovery_engine():
    try:
        import asyncio
        from src.services.capability_engine import CapabilityDiscoveryEngine

        loop = asyncio.get_event_loop()
        loop.create_task(CapabilityDiscoveryEngine().run_loop())
    except Exception:
        pass


@app.on_event("startup")
async def _start_crm_and_metrics_agents():
    """Start lightweight CRM and Metrics agents in background threads if available."""
    try:
        import threading
        from src.agents.crm_agents import CRMEventAgent
        from src.agents.metrics_agent import start_in_thread as start_metrics
        # Start CRMEventAgent in a background thread
        def _run_crm():
            try:
                agent = CRMEventAgent()
                agent.run()
            except Exception:
                pass

        t = threading.Thread(target=_run_crm, daemon=True)
        t.start()
        # Start MetricsAgent
        start_metrics()
        # Start RiskAgent and InventoryAgent
        try:
            from src.agents.risk_agent import start_in_thread as start_risk
            from src.agents.inventory_agent import start_in_thread as start_inventory

            # Start CRM realtime enrichment agent
            try:
                from src.agents.crm_realtime_agent import start_in_thread as start_crm_realtime
                start_crm_realtime()
            except Exception:
                pass

            start_risk()
            start_inventory()
        except Exception:
            pass
    except Exception:
        pass


@app.on_event("startup")
async def _seed_superadmin():
    """Auto-seed superadmin user from env vars if not exists."""
    import os
    try:
        from src.db import db
        from src.auth_utils import hash_password

        admin_email = (os.getenv("ADMIN_EMAIL") or "").strip().lower()
        admin_password = os.getenv("ADMIN_PASSWORD")
        if not admin_email or not admin_password:
            logging.info("ADMIN_EMAIL/ADMIN_PASSWORD not set; skipping admin seed.")
            return

        hashed = hash_password(admin_password)
        existing = db.table("placeware_users").select("id").eq("email", admin_email).limit(1).execute()
        if existing.data:
            user_id = existing.data[0]["id"]
            db.table("placeware_users").update({
                "hashed_password": hashed,
                "roles": ["admin"],
                "is_active": True,
            }).eq("id", user_id).execute()
            logging.info(f"Superadmin {admin_email} already exists; reconciled credentials and role.")
            return

        try:
            db.table("placeware_users").insert({
                "email": admin_email,
                "hashed_password": hashed,
                "roles": ["admin"],
                "is_active": True,
            }).execute()
        except Exception as insert_exc:
            msg = str(insert_exc).lower()
            if "duplicate key" not in msg and "already exists" not in msg:
                raise
            # Another worker inserted first; reconcile to desired state.
            existing = db.table("placeware_users").select("id").eq("email", admin_email).limit(1).execute()
            if not existing.data:
                raise
            user_id = existing.data[0]["id"]
            db.table("placeware_users").update({
                "hashed_password": hashed,
                "roles": ["admin"],
                "is_active": True,
            }).eq("id", user_id).execute()
        logging.info(f"Superadmin {admin_email} seeded successfully.")
    except Exception as e:
        logging.warning(f"Auto-seed superadmin failed: {e}")


@app.on_event("startup")
async def _start_workflow_automation():
    """Start the workflow automation scheduler for low-stock, expiry, and credit risk checks."""
    try:
        from src.workflow.automation import start_workflow_automation
        await start_workflow_automation()
        logging.info("Workflow automation scheduler started")
    except Exception as e:
        logging.warning(f"Workflow automation startup failed: {e}")


app.add_middleware(RequestTimingMiddleware)
allow_credentials = CORS_ALLOW_ORIGINS != ["*"]
app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ALLOW_ORIGINS,
    allow_credentials=allow_credentials,
    allow_methods=["*"],
    allow_headers=["*"],
)
logging.basicConfig(level=logging.INFO)
retriever = QnARetriever(match_threshold=MATCH_THRESHOLD)
MAX_IMPORT_FILE_BYTES = 10 * 1024 * 1024
IMPORT_RETRY_BACKOFF_SECONDS = [1, 2]
IMPORT_MIN_QUALITY_SCORE = float(os.getenv("IMPORT_MIN_QUALITY_SCORE", "0.80"))
IMPORT_MAX_REJECTION_RATE = float(os.getenv("IMPORT_MAX_REJECTION_RATE", "0.20"))

# Select LLM brain implementation:
# - "deepseek" (default) uses DeepSeek chat completions directly
# - "service" uses an external microservice defined by LLM_SERVICE_URL
if LLM_PROVIDER == "deepseek":
    llm_client = DeepSeek(DEEPSEEK_API_KEY)
else:
    llm_client = LLMClient()

tool_registry = build_default_tool_registry()


def _load_company_profile_context() -> str:
    cfg_path = os.path.join(os.path.dirname(__file__), "config.yaml")
    fallback = (
        f"{BOT_BRAND} verified company profile:\n"
        "Services: Vaccine Distribution, Pharma Supply, Cold Chain Logistics, Regulatory Support.\n"
        "Focus: Nigeria pharmaceutical operations."
    )
    try:
        with open(cfg_path, "r", encoding="utf-8") as f:
            cfg = yaml.safe_load(f) or {}
        company = cfg.get("company") if isinstance(cfg, dict) else {}
        if not isinstance(company, dict):
            return fallback
        name = str(company.get("name") or BOT_BRAND).strip()
        services = company.get("services") if isinstance(company.get("services"), list) else []
        locations = company.get("locations") if isinstance(company.get("locations"), list) else []
        certifications = str(company.get("certifications") or "").strip()
        country_focus = str(company.get("country_focus") or "").strip()

        lines = [f"{name} verified company profile:"]
        if services:
            lines.append("Services: " + ", ".join(str(s).strip() for s in services if str(s).strip()))
        if locations:
            lines.append("Locations: " + " | ".join(str(l).strip() for l in locations if str(l).strip()))
        if country_focus:
            lines.append(f"Country focus: {country_focus}")
        if certifications:
            lines.append(f"Compliance: {certifications}")
        return "\n".join(lines)
    except Exception as e:
        logging.error(f"Failed to load company context from config.yaml: {e}")
        return fallback


COMPANY_PROFILE_CONTEXT = _load_company_profile_context()


def _normalize_roles(payload: dict[str, Any] | None) -> set[str]:
    if not isinstance(payload, dict):
        return set()
    roles = payload.get("roles")
    if not isinstance(roles, list):
        return set()
    return {str(r).strip().lower() for r in roles if str(r).strip()}


def _detect_chat_mode(question: str, roles: set[str]) -> str:
    q = (question or "").lower()
    if not roles:
        return "customer"
    if any(x in roles for x in {"admin", "management"}) and any(
        k in q for k in ["executive", "brief", "board", "leadership", "health", "overview", "summary"]
    ):
        return "executive"
    return "assistant"


def _resolve_chat_mode(question: str, roles: set[str], requested_mode: str | None) -> str:
    requested = str(requested_mode or "").strip().lower()
    if not roles:
        return "customer"

    if requested in {"customer", "assistant", "executive"}:
        if requested == "executive" and not any(r in roles for r in {"admin", "management"}):
            return "assistant"
        return requested

    return _detect_chat_mode(question=question, roles=roles)


def _validate_public_widget_access(request: Request, auth_payload: dict[str, Any]) -> None:
    if auth_payload:
        return
    if not WIDGET_SITE_KEYS:
        return
    site_key = (request.headers.get("X-Site-Key") or "").strip()
    if not site_key or site_key not in set(WIDGET_SITE_KEYS):
        raise HTTPException(status_code=401, detail="Unauthorized widget origin")


def _tool_payload(tool_outputs: list[dict[str, Any]], tool_name: str) -> Any:
    for entry in (tool_outputs or []):
        if str(entry.get("tool") or "") == tool_name:
            data = entry.get("data") if isinstance(entry.get("data"), dict) else {}
            return data.get("payload") if isinstance(data, dict) else None
    return None


def _build_tool_sources(tool_outputs: list[dict[str, Any]]) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    for entry in (tool_outputs or []):
        tool = str(entry.get("tool") or "").strip()
        source = str(entry.get("source") or "").strip()
        ts = str(entry.get("timestamp") or "").strip()
        if not tool:
            continue
        label = f"tool:{tool}"
        detail = source or "backend.orchestration"
        if ts:
            detail = f"{detail} @ {ts}"
        out.append({"question": label, "answer": detail})
    return out


def _is_executive_analytical_question(question: str, mode: str) -> bool:
    if mode != "executive":
        return False
    q = (question or "").lower()
    keywords = [
        "revenue",
        "margin",
        "profit",
        "cashflow",
        "ar",
        "ap",
        "inventory",
        "stock",
        "kpi",
        "forecast",
        "risk",
        "recommend",
        "focus",
        "executive",
        "summary",
        "quarter",
        "performance",
        "health",
    ]
    return any(k in q for k in keywords)


def _build_missing_evidence_answer(tool_errors: list[str]) -> str:
    msg = (
        "I can’t provide a reliable executive answer yet because no verified backend evidence was returned "
        "for this question. Please refresh the relevant data imports (finance, inventory, ops, HR, CRM) "
        "or retry after backend tool access is confirmed."
    )
    if tool_errors:
        msg += " Tool notes: " + "; ".join(str(e) for e in tool_errors[:2])
    return msg


def _safe_float(value: Any) -> float:
    try:
        return float(value)
    except Exception:
        return 0.0


def _build_grounded_direct_answer(question: str, tool_outputs: list[dict[str, Any]], mode: str) -> str | None:
    q = (question or "").lower()

    if any(k in q for k in ["revenue", "ar total", "accounts receivable", "current revenue", "total revenue"]):
        finance = _tool_payload(tool_outputs, "getFinancialKpis")
        if isinstance(finance, dict):
            ar = finance.get("ar") if isinstance(finance.get("ar"), dict) else {}
            total_amount = _safe_float(ar.get("total_amount"))
            outstanding = _safe_float(ar.get("total_balance"))
            overdue = int(_safe_float(ar.get("overdue_count")))
            return (
                f"AR total is ₦{total_amount:,.0f} with ₦{outstanding:,.0f} outstanding "
                f"across {overdue} overdue invoice{'s' if overdue != 1 else ''}."
            )

    if any(k in q for k in ["total stock", "number of stock", "how many stock", "stock units", "current stock total"]):
        inventory = _tool_payload(tool_outputs, "getLatestInventorySnapshot")
        if isinstance(inventory, list):
            total_units = sum(_safe_float(x.get("quantity")) for x in inventory if isinstance(x, dict))
            sku_count = len({str(x.get("sku") or "").strip() for x in inventory if isinstance(x, dict) and str(x.get("sku") or "").strip()})
            return f"We have {int(total_units):,} units across {sku_count} active SKUs right now."

    if mode == "executive" and any(k in q for k in ["focus", "this quarter", "priority", "what should we focus"]):
        recs = _tool_payload(tool_outputs, "getRecommendations")
        if isinstance(recs, dict) and isinstance(recs.get("recommendations"), list) and recs.get("recommendations"):
            top = []
            for rec in recs.get("recommendations", [])[:3]:
                if isinstance(rec, dict):
                    action = str(rec.get("action") or "").strip()
                    reason = str(rec.get("reason") or "").strip()
                    if action:
                        top.append(f"- {action}" + (f" ({reason})" if reason else ""))
            if top:
                return "Top priorities based on current data:\n" + "\n".join(top)

    return None


# ---------------------------------------------------------------------------
# Intent classification — determines if a query needs a report/list or
# just a short conversational reply.
# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------
# Action-intent detection — all keywords and handlers are declared ONCE in
# src/eos/tool_manifest.py.  Do NOT duplicate keyword lists here.
# ---------------------------------------------------------------------------
try:
    from src.eos.tool_manifest import ORDERED_ACTION_KEYWORDS as _ORDERED_ACTION_KEYWORDS
except Exception:
    # Graceful degradation if manifest is unavailable at import time
    _ORDERED_ACTION_KEYWORDS = []


def _detect_action_intent(question: str) -> str | None:
    """Return the action intent_type if the question triggers an EOS action handler,
    else None.  Detection uses the manifest's ordered keyword table (longest phrase
    wins) so adding new intents only requires updating tool_manifest.py."""
    q = (question or "").lower()
    for keyword, intent_type in _ORDERED_ACTION_KEYWORDS:
        if keyword in q:
            return intent_type
    return None


_REPORT_KEYWORDS = {
    # report triggers
    "report", "summary", "summarize", "summarise", "breakdown", "analysis",
    "analyze", "analyse", "overview", "dashboard", "brief", "briefing",
    # list / table triggers
    "list", "show me all", "show all", "give me all", "all inventory",
    "all staff", "all orders", "all customers", "all sku", "all items",
    "table", "enumerate", "what are all",
    # explicit data pulls
    "inventory report", "stock report", "ar report", "hr report",
    "payroll report", "sales report", "finance report",
    "top 10", "top 5", "full list",
}


def _classify_query_intent(question: str) -> str:
    """Return 'report' for explicit report/list requests, else 'conversational'."""
    q = (question or "").lower()
    if any(kw in q for kw in _REPORT_KEYWORDS):
        return "report"
    return "conversational"


def _build_chat_instruction(mode: str, question: str = "") -> str:
    intent = _classify_query_intent(question)

    if mode == "customer":
        return (
            f"You are {BOT_NAME} for {BOT_BRAND} serving external customers. "
            "Only provide safe public-facing information (availability, order guidance, contact/lead support). "
            "Do not reveal internal financial, operational, HR, or strategic metrics. "
            "If asked for restricted internal data, politely refuse and offer next safe step. "
            "Reply naturally and briefly — 1-2 sentences unless the user explicitly asks for a list or detailed breakdown. "
            "Use warm, service-oriented language suitable for clients."
        )

    # Internal (executive / assistant) mode
    base = (
        f"You are {BOT_NAME}, an internal business copilot for {BOT_BRAND}. "
        "Use ONLY the provided backend context and tool results as source of truth. "
        "Do not invent numbers, trends, or claims not present in the context. "
        "If a metric is missing, briefly say it is unavailable. "
        "Do NOT include customer support copy, ordering instructions, sales CTAs, or contact blocks. "
        # ── EOS action capabilities (prevents LLM from saying "I can't") ────
        f"You have FULL built-in ability to execute the following actions via {BOT_BRAND}'s EOS backend: "
        "sending emails to internal departments, scheduling and managing calendar meetings, "
        "creating workflow tasks, generating structured business reports (deviation, maintenance, "
        "compliance, audit, financial, inventory, executive), and triggering inventory replenishment orders. "
        "When the user asks you to perform any of these actions, CONFIRM that you are executing it and "
        "report the result back. NEVER say you cannot send emails, cannot access the calendar, "
        "cannot create tasks, or cannot generate reports — these capabilities are fully operational "
        f"through {BOT_NAME}'s agent backend. "
    )

    if intent == "report":
        return (
            base
            + "The user is asking for a structured report or list. "
            + "Respond with a clear, well-organised answer using the available data: "
            + "current state, key findings, notable risks, and a recommended action. "
            + "Use bullet points or sections where it aids clarity."
        )

    # Conversational intent — the default ─────────────────────────────────────
    return (
        base
        + "The user is asking a conversational question. "
        + "Reply naturally and concisely — 1 to 2 sentences maximum unless the data genuinely "
        + "warrants more. Do NOT produce a structured report, bullet-point breakdown, or "
        + "analyst summary unless the user explicitly asked for one. "
        + "Speak like a knowledgeable teammate giving a quick verbal answer."
    )


def _enforce_mode_tone(answer: str, mode: str, question: str = "") -> str:
    text = (answer or "").strip()
    if not text or mode != "executive":
        return text

    lowered = text.lower()
    disallowed_markers = [
        "next steps for ordering",
        "contact for orders",
        "orders & inquiries",
        "place an order",
        "thank you for your patronage",
        "email:",
        "phone:",
    ]
    if any(marker in lowered for marker in disallowed_markers):
        filtered_lines: list[str] = []
        skip_line_markers = [
            "next steps for ordering",
            "contact for orders",
            "orders & inquiries",
            "place an order",
            "thank you for your patronage",
            "email:",
            "phone:",
            "contact our team",
        ]
        for line in text.splitlines():
            line_lower = line.strip().lower()
            if any(marker in line_lower for marker in skip_line_markers):
                continue
            filtered_lines.append(line)
        text = "\n".join(filtered_lines).strip()
        if not text:
            text = "Inventory snapshot reviewed from current backend data."

    # Only append the prudent-action footer for explicit report/analytical responses.
    # Conversational replies must stay short.
    intent = _classify_query_intent(question)
    if intent == "report":
        action_markers = [
            "recommend",
            "should",
            "next",
            "action",
            "priorit",
            "validate",
            "mitigat",
            "monitor",
        ]
        if not any(marker in text.lower() for marker in action_markers):
            text = (
                f"{text}\n\n"
                "Recommended next step: validate critical exposure, prioritise replenishment "
                "or escalation, and monitor the next data refresh."
            )

    return text


def _extract_email(text: str) -> str | None:
    m = re.search(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}", text or "")
    return m.group(0).strip() if m else None


def _extract_phone(text: str) -> str | None:
    m = re.search(r"\+?[0-9][0-9\-\s]{7,14}[0-9]", text or "")
    return re.sub(r"\s+", "", m.group(0)).strip() if m else None


def _extract_customer_name(text: str) -> str | None:
    m = re.search(r"(?:my name is|i am|i'm)\s+([A-Za-z][A-Za-z\s\-]{1,60})", text or "", re.IGNORECASE)
    return m.group(1).strip() if m else None


def _extract_order_items_from_text(text: str) -> list["OrderItem"]:
    matches = re.findall(r"\b([A-Za-z]{1,8}-\d{1,8})\b(?:\s*(?:x|qty|quantity)\s*(\d+))?", text or "", re.IGNORECASE)
    items: list[OrderItem] = []
    seen: set[str] = set()
    for sku_raw, qty_raw in matches:
        sku = sku_raw.upper().strip()
        if not sku or sku in seen:
            continue
        seen.add(sku)
        qty = int(qty_raw) if str(qty_raw or "").isdigit() else 1
        qty = max(1, min(qty, 10000))
        items.append(OrderItem(sku=sku, quantity=qty))
    return items


def _create_order_record(order: "SubmitOrder") -> dict[str, Any]:
    if not order.items:
        raise HTTPException(status_code=400, detail="At least one item required")
    for item in order.items:
        if item.quantity <= 0:
            raise HTTPException(status_code=400, detail=f"Invalid quantity for {item.sku}")
    payload = order.model_dump(exclude_none=True)
    payload["source"] = str(order.source or "direct").strip().lower()
    saved = store_order(payload)
    if not saved:
        raise HTTPException(status_code=503, detail="Order service temporarily unavailable")
    return saved


def _handle_customer_transaction_intent(question: str) -> str | None:
    q = (question or "").lower()

    if any(k in q for k in ["contact me", "reach me", "call me", "speak to sales", "lead"]):
        email = _extract_email(question)
        if not email:
            return "To register your request, please include an email address so our team can follow up."
        lead_payload = Lead(
            name=_extract_customer_name(question) or "Website Visitor",
            email=email,
            phone=_extract_phone(question) or "N/A",
            message=question.strip(),
        )
        lead_id = store_lead(lead_payload.model_dump(exclude_none=True))
        return (
            f"Your request has been received successfully (Lead ID: {lead_id}). "
            "Our team will contact you shortly. Thank you for your patronage."
        )

    if any(k in q for k in ["place order", "submit order", "order now", "process order"]):
        items = _extract_order_items_from_text(question)
        email = _extract_email(question)
        if not items:
            return "To process your order, include SKU and quantity (example: VAC-100 x 2)."
        if not email:
            return "To process your order, include your contact email in the message."
        lead_payload = Lead(
            name=_extract_customer_name(question) or "Website Customer",
            email=email,
            phone=_extract_phone(question) or "N/A",
            message=question.strip(),
            service="orders",
        )
        lead_id = store_lead(lead_payload.model_dump(exclude_none=True))
        order_payload = SubmitOrder(
            customer_name=_extract_customer_name(question) or "Website Customer",
            customer_email=email,
            customer_phone=_extract_phone(question),
            items=items,
            notes=question.strip(),
            source="synbot",
            lead_id=lead_id,
        )
        accepted = _create_order_record(order_payload)
        return (
            f"Your order has been processed successfully. Order ID: {accepted.get('order_id')}. "
            f"Tracking ID: {accepted.get('tracking_id')}. "
            "Thank you for your patronage."
        )

    return None


def _extract_skus(question: str) -> list[str]:
    tokens = re.findall(r"\b[A-Za-z]{1,6}-\d{1,6}\b", question or "")
    uniq: list[str] = []
    seen = set()
    for t in tokens:
        s = t.upper()
        if s not in seen:
            seen.add(s)
            uniq.append(s)
    return uniq[:10]


def _plan_tools(question: str, mode: str) -> list[tuple[str, dict[str, Any]]]:
    q = (question or "").lower()
    plan: list[tuple[str, dict[str, Any]]] = []

    if any(k in q for k in ["inventory", "stock", "availability", "available", "sku"]):
        skus = _extract_skus(question)
        if skus:
            plan.append(("getInventoryBySkus", {"skus": skus}))
        else:
            plan.append(("getLatestInventorySnapshot", {"limit": 30}))

    if any(k in q for k in ["expiry", "expiring", "expire", "shelf life"]):
        plan.append(("getExpiringInventory", {}))

    if mode != "customer" and any(k in q for k in ["finance", "cashflow", "ar", "ap", "receivable", "payable", "revenue", "sales", "income"]):
        plan.append(("getFinancialKpis", {}))
        if any(k in q for k in ["trend", "period", "monthly"]):
            plan.append(("getArTrendSummary", {"periods": 6}))
        if any(k in q for k in ["aging", "overdue", "bucket"]):
            plan.append(("getArAgingBuckets", {}))

    if mode != "customer" and any(k in q for k in ["ops", "operations", "downtime", "fulfillment", "turnover", "forecast"]):
        plan.append(("getOpsKpis", {}))
        if any(k in q for k in ["forecast", "predict", "projection"]):
            plan.append(("runStockTurnoverForecast", {"window": 3, "horizon": 3}))

    if mode != "customer" and any(k in q for k in ["project", "controls", "scope", "change request", "risk register"]):
        plan.append(("getProjectControlsRollup", {"project_id": None}))

    if mode != "customer" and any(k in q for k in ["risk", "alert", "issue", "threat"]):
        plan.append(("getRiskSignals", {}))

    if mode != "customer" and any(k in q for k in ["recommend", "action", "next step", "what should we do", "focus", "quarter", "priority"]):
        plan.append(("getRecommendations", {}))

    if mode == "executive" or (mode != "customer" and any(k in q for k in ["executive", "overview", "health", "summary", "brief"])):
        plan.append(("getExecutiveSummary", {}))

    # Dedupe while preserving first-seen order; keep orchestration lightweight.
    deduped: list[tuple[str, dict[str, Any]]] = []
    seen_names: set[str] = set()
    for name, args in plan:
        if name in seen_names:
            continue
        seen_names.add(name)
        deduped.append((name, args))
    return deduped[:5]


def _audit_compact(value: Any, max_len: int = 1200) -> str:
    try:
        text = json.dumps(value, default=str)
    except Exception:
        text = str(value)
    if len(text) <= max_len:
        return text
    return text[:max_len] + "..."


def _audit_orchestration_event(
    *,
    event_type: str,
    actor_id: str | None,
    actor_role: str | None,
    trace_id: str,
    details: dict[str, Any],
    outcome: str = "success",
    event_class: str = "workflow",
    action: str | None = None,
) -> None:
    try:
        audit_event(
            event_type,
            details,
            event_class=event_class,
            action=action or event_type,
            outcome=outcome,
            actor_id=actor_id,
            actor_role=actor_role,
            subject_type="chat_orchestration",
            trace_id=trace_id,
        )
    except Exception as e:
        logging.error(f"orchestration audit log failed: {e}")


def _run_orchestration_plan(
    question: str,
    *,
    roles: set[str],
    mode: str,
    actor_id: str | None,
    actor_role: str | None,
    trace_id: str,
) -> tuple[list[dict[str, Any]], list[str]]:
    plan = _plan_tools(question, mode)
    outputs: list[dict[str, Any]] = []
    errors: list[str] = []

    _audit_orchestration_event(
        event_type="ai_orchestration_plan",
        actor_id=actor_id,
        actor_role=actor_role,
        trace_id=trace_id,
        action="orchestration_plan",
        details={
            "mode": mode,
            "roles": sorted(list(roles)),
            "planned_tools": [name for name, _ in plan],
            "question_preview": (question or "")[:180],
        },
    )

    for tool_name, args in plan:
        try:
            out = tool_registry.execute(tool_name, args, roles=roles, mode=mode)
            outputs.append(out)
            _audit_orchestration_event(
                event_type="ai_tool_call",
                actor_id=actor_id,
                actor_role=actor_role,
                trace_id=trace_id,
                action="tool_execute",
                details={
                    "tool": tool_name,
                    "mode": mode,
                    "args": _audit_compact(args),
                    "result_preview": _audit_compact(out.get("data")),
                },
            )
        except ToolPermissionError as e:
            logging.info(f"tool permission blocked: {e}")
            errors.append(str(e))
            _audit_orchestration_event(
                event_type="ai_tool_denied",
                actor_id=actor_id,
                actor_role=actor_role,
                trace_id=trace_id,
                action="tool_execute",
                outcome="failed",
                event_class="security",
                details={
                    "tool": tool_name,
                    "mode": mode,
                    "args": _audit_compact(args),
                    "reason": str(e),
                },
            )
        except ToolExecutionError as e:
            logging.error(f"tool execution error: {e}")
            errors.append(str(e))
            _audit_orchestration_event(
                event_type="ai_tool_error",
                actor_id=actor_id,
                actor_role=actor_role,
                trace_id=trace_id,
                action="tool_execute",
                outcome="failed",
                details={
                    "tool": tool_name,
                    "mode": mode,
                    "args": _audit_compact(args),
                    "reason": str(e),
                },
            )

    _audit_orchestration_event(
        event_type="ai_orchestration_summary",
        actor_id=actor_id,
        actor_role=actor_role,
        trace_id=trace_id,
        action="orchestration_summary",
        outcome="success" if not errors else "failed",
        details={
            "mode": mode,
            "executed_tools": [x.get("tool") for x in outputs],
            "tool_count": len(outputs),
            "error_count": len(errors),
            "errors": errors[:5],
        },
    )

    # Agent routing + execution: determine relevant agents and run them
    try:
        from src.agents.router import route_question, merge_insights
        from src.agent_registry import get_agent

        agent_names = route_question(question, roles, mode)
        agent_insights = []
        for name in agent_names:
            try:
                from src.routers.agents_exec import create_db_executor, _get_default_specs_for_agent, workflow_engine as _wf_engine, shared_cache as _cache
                agent = get_agent(name, context={
                    "db_executor": create_db_executor(),
                    "query_specs": _get_default_specs_for_agent(name),
                    "cache": _cache,
                    "workflow_engine": _wf_engine,
                    "auto_trigger_workflow": False,  # safe default in chat path
                    "actor_id": actor_id,
                    "actor_role": actor_role,
                })
                if agent is None:
                    errors.append(f"agent_not_registered:{name}")
                    continue
                insight = agent.run()
                # convert dataclass to dict if needed
                ins_dict = getattr(insight, "__dict__", insight)
                agent_insights.append(ins_dict)
                outputs.append({"tool": f"agent:{name}", "data": ins_dict})
            except Exception as e:
                logging.error(f"agent {name} execution failed: {e}")
                errors.append(str(e))

        # Merge insights for higher-level summary and attach as a synthetic tool output
        if agent_insights:
            merged = merge_insights(agent_insights)
            outputs.append({"tool": "agents_merged", "data": merged})
    except Exception as e:
        logging.error(f"agent routing failed: {e}")

    return outputs, errors


def _normalize_tool_catalog(mode: str, tools: list[dict[str, Any]]) -> "ToolCatalogResponse":
    normalized_items: list[ToolCatalogItem] = []
    for t in tools:
        normalized_items.append(
            ToolCatalogItem(
                name=str(t.get("name") or ""),
                description=str(t.get("description") or ""),
                department=str(t.get("department") or ""),
                source=str(t.get("source") or ""),
                required_roles=[str(x) for x in (t.get("required_roles") or [])],
                allowed_modes=[str(x) for x in (t.get("allowed_modes") or [])],
                parameters=[str(x) for x in (t.get("parameters") or [])],
            )
        )
    return ToolCatalogResponse(mode=str(mode or "customer"), count=len(normalized_items), tools=normalized_items)


def _normalize_chat_contract(
    *,
    answer: str,
    bot: str,
    sources: list[dict[str, Any]],
    mode: str,
    trace_id: str,
    tool_outputs: list[dict[str, Any]],
    tool_errors: list[str],
) -> "ChatResponse":
    normalized_sources = [
        ChatSource(
            question=str(s.get("question") or ""),
            answer=str(s.get("answer") or ""),
        )
        for s in (sources or [])
    ]
    normalized_tools = [str(x.get("tool") or "") for x in (tool_outputs or []) if str(x.get("tool") or "").strip()]
    normalized_errors = [str(e) for e in (tool_errors or []) if str(e).strip()]
    return ChatResponse(
        answer=str(answer or ""),
        bot=str(bot or BOT_NAME),
        sources=normalized_sources,
        orchestration=ChatOrchestrationMeta(
            mode=str(mode or "assistant"),
            trace_id=str(trace_id or ""),
            tool_count=len(normalized_tools),
            tools=normalized_tools,
            errors=normalized_errors,
        ),
    )


async def _load_dataset_file(
    name: str,
    file: UploadFile | None,
    required: list[str],
    aliases: dict[str, list[str]] | None = None,
):
    if not file:
        return [], {"provided": False, "rows": 0}

    content = await file.read()
    return _load_dataset_bytes(name=name, content=content, filename=file.filename, content_type=file.content_type, required=required, aliases=aliases)


def _load_dataset_bytes(
    name: str,
    content: bytes,
    filename: str | None,
    content_type: str | None,
    required: list[str],
    aliases: dict[str, list[str]] | None = None,
):
    if len(content) > MAX_IMPORT_FILE_BYTES:
        raise HTTPException(status_code=413, detail=f"{name} file exceeds 10MB limit")

    try:
        rows = parse_tabular_upload(content=content, filename=filename, content_type=content_type)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"{name}: {exc}") from exc

    diagnostics = {
        "provided": True,
        "filename": filename,
        "content_type": content_type,
        "rows": len(rows),
    }

    if not rows:
        diagnostics.update({"header_map": {}, "unknown_headers": [], "duplicate_mapped_headers": []})
        return rows, diagnostics

    headers = list(rows[0].keys())
    header_map, missing, unknown, duplicates = resolve_headers(headers, required, aliases)
    if missing:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Invalid headers for {name}. Missing required fields: {', '.join(missing)}"
            ),
        )

    canonical_rows = canonicalize_rows(rows, header_map)
    diagnostics.update(
        {
            "header_map": header_map,
            "unknown_headers": unknown,
            "duplicate_mapped_headers": duplicates,
            "quality_score": max(0.0, 1.0 - (len(unknown) / max(1, len(headers)))),
        }
    )
    return canonical_rows, diagnostics


async def _run_import_with_retry(
    *,
    job_id: str | None,
    source_system: str,
    idempotency_key: str | None,
    raise_on_error: bool,
    run_attempt,
) -> dict | None:
    attempts: list[dict] = []
    max_attempts = 1 + len(IMPORT_RETRY_BACKOFF_SECONDS)

    for attempt in range(1, max_attempts + 1):
        update_import_job(
            job_id,
            status="running",
            metadata={
                "source_system": source_system,
                "idempotency_key": idempotency_key,
                "attempt": attempt,
                "max_attempts": max_attempts,
            },
        )
        try:
            return await run_attempt(attempt=attempt, attempts=attempts, max_attempts=max_attempts)
        except HTTPException as exc:
            attempts.append({"attempt": attempt, "status": "failed", "error": str(exc.detail)})
            update_import_job(
                job_id,
                status="failed",
                error_message=str(exc.detail),
                metadata={
                    "source_system": source_system,
                    "idempotency_key": idempotency_key,
                    "attempts": attempts,
                    "max_attempts": max_attempts,
                },
            )
            if raise_on_error:
                raise
            return None
        except Exception as exc:
            attempts.append({"attempt": attempt, "status": "failed", "error": str(exc)})
            if attempt < max_attempts:
                await asyncio.sleep(IMPORT_RETRY_BACKOFF_SECONDS[attempt - 1])
                continue
            update_import_job(
                job_id,
                status="failed",
                error_message=str(exc),
                metadata={
                    "source_system": source_system,
                    "idempotency_key": idempotency_key,
                    "attempts": attempts,
                    "max_attempts": max_attempts,
                },
            )
            if raise_on_error:
                raise
            return None

    return None


def _ifrs_finance_lineage_warnings(bundle: ImportBundle) -> list[dict]:
    """Return non-blocking IFRS baseline warnings for finance datasets.

    Warnings are designed for lineage/compliance visibility and do not block import.
    """
    warnings: list[dict] = []
    tolerance = 0.01

    ar_negatives = 0
    ar_balance_gt_amount = 0
    for row in bundle.ar:
        amount = float(row.amount or 0)
        balance = float(row.balance or 0)
        if amount < 0 or balance < 0:
            ar_negatives += 1
        if balance - amount > tolerance:
            ar_balance_gt_amount += 1
    if ar_negatives:
        warnings.append(
            {
                "code": "ifrs_ar_negative_values",
                "dataset": "ar",
                "level": "warning",
                "count": ar_negatives,
                "message": "AR contains negative amount/balance values that may violate IFRS receivable presentation assumptions.",
            }
        )
    if ar_balance_gt_amount:
        warnings.append(
            {
                "code": "ifrs_ar_balance_exceeds_amount",
                "dataset": "ar",
                "level": "warning",
                "count": ar_balance_gt_amount,
                "message": "AR balance exceeds invoice amount for one or more rows.",
            }
        )

    ap_negatives = 0
    ap_balance_gt_amount = 0
    for row in bundle.ap:
        amount = float(row.amount or 0)
        balance = float(row.balance or 0)
        if amount < 0 or balance < 0:
            ap_negatives += 1
        if balance - amount > tolerance:
            ap_balance_gt_amount += 1
    if ap_negatives:
        warnings.append(
            {
                "code": "ifrs_ap_negative_values",
                "dataset": "ap",
                "level": "warning",
                "count": ap_negatives,
                "message": "AP contains negative amount/balance values that may violate IFRS payable presentation assumptions.",
            }
        )
    if ap_balance_gt_amount:
        warnings.append(
            {
                "code": "ifrs_ap_balance_exceeds_amount",
                "dataset": "ap",
                "level": "warning",
                "count": ap_balance_gt_amount,
                "message": "AP balance exceeds bill amount for one or more rows.",
            }
        )

    gl_negatives = 0
    gl_by_period: dict[str, dict[str, float]] = {}
    for row in bundle.gl:
        debit = float(row.debit or 0)
        credit = float(row.credit or 0)
        if debit < 0 or credit < 0:
            gl_negatives += 1
        period = str(row.period)
        bucket = gl_by_period.setdefault(period, {"debit": 0.0, "credit": 0.0})
        bucket["debit"] += debit
        bucket["credit"] += credit

    if gl_negatives:
        warnings.append(
            {
                "code": "ifrs_gl_negative_values",
                "dataset": "gl",
                "level": "warning",
                "count": gl_negatives,
                "message": "GL contains negative debit/credit values.",
            }
        )

    unbalanced_periods: list[dict] = []
    for period, totals in gl_by_period.items():
        debit_total = totals["debit"]
        credit_total = totals["credit"]
        diff = abs(debit_total - credit_total)
        if diff > tolerance:
            unbalanced_periods.append(
                {
                    "period": period,
                    "debit_total": round(debit_total, 2),
                    "credit_total": round(credit_total, 2),
                    "difference": round(diff, 2),
                }
            )
    if unbalanced_periods:
        warnings.append(
            {
                "code": "ifrs_gl_unbalanced_period_totals",
                "dataset": "gl",
                "level": "warning",
                "count": len(unbalanced_periods),
                "message": "GL period totals are not balanced between debit and credit.",
                "details": unbalanced_periods[:12],
            }
        )

    return warnings


def _build_deterministic_lineage_key(
    *,
    source_system: str,
    batch_id: str,
    imported_at: str,
    datasets: dict[str, dict],
    counts: dict[str, int] | None = None,
) -> str:
    dataset_hashes: dict[str, str] = {}
    for name in sorted(datasets.keys()):
        payload = datasets.get(name) or {}
        content = payload.get("content") or b""
        if isinstance(content, str):
            content = content.encode("utf-8")
        if not isinstance(content, (bytes, bytearray)):
            content = str(content).encode("utf-8")
        dataset_hashes[name] = hashlib.sha256(content).hexdigest()

    canonical = {
        "source_system": source_system,
        "batch_id": batch_id,
        "imported_at": imported_at,
        "dataset_hashes": dataset_hashes,
        "counts": counts or {},
    }
    payload = json.dumps(canonical, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _payroll_baseline_lineage_warnings(payroll_rows: list[dict], absence_rows: list[dict]) -> list[dict]:
    warnings: list[dict] = []

    negative_salary = 0
    negative_overtime = 0
    for row in payroll_rows:
        salary = float(row.get("salary") or 0)
        overtime_hours = float(row.get("overtime_hours") or 0)
        overtime_rate = float(row.get("overtime_rate") or 0)
        if salary < 0:
            negative_salary += 1
        if overtime_hours < 0 or overtime_rate < 0:
            negative_overtime += 1

    if negative_salary:
        warnings.append(
            {
                "code": "payroll_negative_salary",
                "dataset": "payroll",
                "level": "warning",
                "count": negative_salary,
                "message": "Payroll contains negative salary values.",
            }
        )
    if negative_overtime:
        warnings.append(
            {
                "code": "payroll_negative_overtime_values",
                "dataset": "payroll",
                "level": "warning",
                "count": negative_overtime,
                "message": "Payroll contains negative overtime hours or overtime rates.",
            }
        )

    excessive_absence_hours = 0
    for row in absence_rows:
        hours = float(row.get("hours") or 0)
        if hours < 0 or hours > 24:
            excessive_absence_hours += 1
    if excessive_absence_hours:
        warnings.append(
            {
                "code": "absence_hours_out_of_range",
                "dataset": "absences",
                "level": "warning",
                "count": excessive_absence_hours,
                "message": "Absence records include hours outside expected 0-24 range.",
            }
        )

    return warnings


def _compute_import_control_rollup(lineage: dict | None, rejected_rows: int = 0, policy_config: dict | None = None) -> dict:
    lineage = lineage or {}
    rows_total = 0
    for dataset, diag in lineage.items():
        if dataset == "compliance":
            continue
        if isinstance(diag, dict):
            rows_total += int(diag.get("rows") or 0)

    compliance = lineage.get("compliance") if isinstance(lineage, dict) else {}
    warnings = []
    if isinstance(compliance, dict):
        warnings.extend(compliance.get("ifrs_warnings") or [])
        warnings.extend(compliance.get("warnings") or [])

    severity_weights = {
        "info": 1,
        "warning": 2,
        "error": 4,
        "critical": 6,
    }
    density_penalty_cap = 60.0
    severity_penalty_cap = 40.0
    rejection_penalty_cap = 20.0
    severity_penalty_multiplier = 10.0

    policy_source = policy_config or {}
    if isinstance(policy_source.get("severity_weights"), dict):
        severity_weights = {
            **severity_weights,
            **{str(k): int(v) for k, v in policy_source.get("severity_weights", {}).items() if isinstance(v, (int, float))},
        }
    density_penalty_cap = float(policy_source.get("density_penalty_cap", density_penalty_cap))
    severity_penalty_cap = float(policy_source.get("severity_penalty_cap", severity_penalty_cap))
    rejection_penalty_cap = float(policy_source.get("rejection_penalty_cap", rejection_penalty_cap))
    severity_penalty_multiplier = float(policy_source.get("severity_penalty_multiplier", severity_penalty_multiplier))
    severity_breakdown: dict[str, int] = {}
    warning_instances = 0
    weighted_total = 0
    warning_codes: list[str] = []
    for warning in warnings:
        level = str((warning or {}).get("level") or "warning").lower()
        count = int((warning or {}).get("count") or 1)
        code = str((warning or {}).get("code") or "")
        warning_instances += max(1, count)
        weight = severity_weights.get(level, 2)
        weighted_total += max(1, count) * weight
        severity_breakdown[level] = int(severity_breakdown.get(level, 0)) + max(1, count)
        if code:
            warning_codes.append(code)

    denominator = max(1, rows_total)
    warning_density = warning_instances / denominator
    severity_index = weighted_total / denominator

    density_penalty = min(density_penalty_cap, warning_density * 100)
    severity_penalty = min(severity_penalty_cap, severity_index * severity_penalty_multiplier)
    rejection_penalty = min(rejection_penalty_cap, (max(0, rejected_rows) / denominator) * 100)
    control_score = round(max(0.0, 100.0 - density_penalty - severity_penalty - rejection_penalty), 2)

    return {
        "framework": "finance_payroll_controls_v1",
        "rows_total": rows_total,
        "warning_instances": warning_instances,
        "rejected_rows": max(0, int(rejected_rows)),
        "warning_density": round(warning_density, 4),
        "severity_index": round(severity_index, 4),
        "severity_breakdown": severity_breakdown,
        "warning_codes": sorted(set(warning_codes)),
        "policy": {
            "density_penalty_cap": density_penalty_cap,
            "severity_penalty_cap": severity_penalty_cap,
            "rejection_penalty_cap": rejection_penalty_cap,
            "severity_penalty_multiplier": severity_penalty_multiplier,
        },
        "control_score": control_score,
    }


def _resolve_controls_policy_config(domain: str) -> dict:
    default = {
        "severity_weights": {"info": 1, "warning": 2, "error": 4, "critical": 6},
        "density_penalty_cap": 60,
        "severity_penalty_cap": 40,
        "rejection_penalty_cap": 20,
        "severity_penalty_multiplier": 10,
    }
    try:
        policy = get_import_policy(domain)
        cfg = policy.get("controls_config") if isinstance(policy, dict) else None
        if isinstance(cfg, dict):
            merged = {**default, **cfg}
            if isinstance(default.get("severity_weights"), dict):
                merged["severity_weights"] = {
                    **default["severity_weights"],
                    **(cfg.get("severity_weights") or {}),
                }
            return merged
    except Exception as e:
        logging.info(f"controls policy fallback for {domain}: {e}")
    return default


def _validate_controls_config(config: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(config, dict) or not config:
        raise HTTPException(status_code=400, detail="controls_config must be a non-empty object")

    required_numeric = [
        "density_penalty_cap",
        "severity_penalty_cap",
        "rejection_penalty_cap",
        "severity_penalty_multiplier",
    ]
    for key in required_numeric:
        value = config.get(key)
        if value is None or not isinstance(value, (int, float)):
            raise HTTPException(status_code=400, detail=f"controls_config.{key} must be numeric")
        if float(value) < 0:
            raise HTTPException(status_code=400, detail=f"controls_config.{key} must be non-negative")

    severity_weights = config.get("severity_weights")
    if not isinstance(severity_weights, dict) or not severity_weights:
        raise HTTPException(status_code=400, detail="controls_config.severity_weights must be a non-empty object")
    for level, weight in severity_weights.items():
        if not isinstance(level, str) or not isinstance(weight, (int, float)):
            raise HTTPException(status_code=400, detail="controls_config.severity_weights entries must be string:number")
        if float(weight) < 0:
            raise HTTPException(status_code=400, detail="controls_config.severity_weights must be non-negative")

    return config


def _ml_feature_contract(domain: str) -> dict[str, Any]:
    normalized = (domain or "").strip().lower()
    if normalized == "sage":
        features = [
            {"name": "ar_invoice_count", "type": "int"},
            {"name": "ar_total_amount", "type": "float"},
            {"name": "ar_total_balance", "type": "float"},
            {"name": "ap_bill_count", "type": "int"},
            {"name": "ap_total_amount", "type": "float"},
            {"name": "ap_total_balance", "type": "float"},
            {"name": "gl_entry_count", "type": "int"},
            {"name": "gl_total_debit", "type": "float"},
            {"name": "gl_total_credit", "type": "float"},
            {"name": "gl_balance_gap", "type": "float"},
            {"name": "inventory_sku_count", "type": "int"},
            {"name": "inventory_total_quantity", "type": "float"},
            {"name": "inventory_low_stock_count", "type": "int"},
            {"name": "staff_count", "type": "int"},
        ]
    elif normalized == "hr":
        features = [
            {"name": "payroll_employee_count", "type": "int"},
            {"name": "payroll_total_salary", "type": "float"},
            {"name": "payroll_total_overtime_hours", "type": "float"},
            {"name": "payroll_total_overtime_cost", "type": "float"},
            {"name": "absences_record_count", "type": "int"},
            {"name": "absences_total_hours", "type": "float"},
            {"name": "absences_over_8h_count", "type": "int"},
        ]
    else:
        features = []

    return {
        "contract_version": "ml_baseline_2026.1",
        "domain": normalized,
        "features": features,
    }


def _compute_ml_feature_snapshot(domain: str, batch_id: str, row_limit: int = 50000) -> dict[str, float | int]:
    normalized = (domain or "").strip().lower()
    if normalized == "sage":
        ar_rows = get_snapshot_rows("sage_ar_snapshot", batch_id, limit=row_limit)
        ap_rows = get_snapshot_rows("sage_ap_snapshot", batch_id, limit=row_limit)
        gl_rows = get_snapshot_rows("sage_gl_snapshot", batch_id, limit=row_limit)
        inv_rows = get_snapshot_rows("sage_inventory_snapshot", batch_id, limit=row_limit)
        staff_rows = get_snapshot_rows("sage_staff_snapshot", batch_id, limit=row_limit)

        ar_total_amount = sum(float(r.get("amount") or 0) for r in ar_rows)
        ar_total_balance = sum(float(r.get("balance") or 0) for r in ar_rows)
        ap_total_amount = sum(float(r.get("amount") or 0) for r in ap_rows)
        ap_total_balance = sum(float(r.get("balance") or 0) for r in ap_rows)
        gl_total_debit = sum(float(r.get("debit") or 0) for r in gl_rows)
        gl_total_credit = sum(float(r.get("credit") or 0) for r in gl_rows)
        inventory_total_quantity = sum(float(r.get("quantity") or 0) for r in inv_rows)
        inventory_low_stock_count = sum(1 for r in inv_rows if float(r.get("quantity") or 0) <= 5)

        return {
            "ar_invoice_count": len(ar_rows),
            "ar_total_amount": round(ar_total_amount, 4),
            "ar_total_balance": round(ar_total_balance, 4),
            "ap_bill_count": len(ap_rows),
            "ap_total_amount": round(ap_total_amount, 4),
            "ap_total_balance": round(ap_total_balance, 4),
            "gl_entry_count": len(gl_rows),
            "gl_total_debit": round(gl_total_debit, 4),
            "gl_total_credit": round(gl_total_credit, 4),
            "gl_balance_gap": round(abs(gl_total_debit - gl_total_credit), 4),
            "inventory_sku_count": len(inv_rows),
            "inventory_total_quantity": round(inventory_total_quantity, 4),
            "inventory_low_stock_count": inventory_low_stock_count,
            "staff_count": len(staff_rows),
        }

    if normalized == "hr":
        payroll_rows = get_snapshot_rows("hr_payroll_snapshot", batch_id, limit=row_limit)
        abs_rows = get_snapshot_rows("hr_absence_snapshot", batch_id, limit=row_limit)

        employee_ids = {str(r.get("employee_id") or "") for r in payroll_rows if r.get("employee_id")}
        payroll_total_salary = sum(float(r.get("salary") or 0) for r in payroll_rows)
        payroll_total_overtime_hours = sum(float(r.get("overtime_hours") or 0) for r in payroll_rows)
        payroll_total_overtime_cost = sum(
            float(r.get("overtime_hours") or 0) * float(r.get("overtime_rate") or 0)
            for r in payroll_rows
        )
        absences_total_hours = sum(float(r.get("hours") or 0) for r in abs_rows)
        absences_over_8h_count = sum(1 for r in abs_rows if float(r.get("hours") or 0) > 8)

        return {
            "payroll_employee_count": len(employee_ids),
            "payroll_total_salary": round(payroll_total_salary, 4),
            "payroll_total_overtime_hours": round(payroll_total_overtime_hours, 4),
            "payroll_total_overtime_cost": round(payroll_total_overtime_cost, 4),
            "absences_record_count": len(abs_rows),
            "absences_total_hours": round(absences_total_hours, 4),
            "absences_over_8h_count": absences_over_8h_count,
        }

    raise HTTPException(status_code=400, detail="ML feature export currently supports only sage or hr domains")


def _resolve_prior_ml_baseline_batch(domain: str, current_batch_id: str, search_limit: int = 100) -> str | None:
    jobs = list_import_jobs(
        limit=max(10, min(search_limit, 500)),
        domain=(domain or "").strip().lower(),
        status="succeeded",
    )
    ordered_batch_ids: list[str] = []
    seen: set[str] = set()
    for job in jobs or []:
        batch_id = str((job or {}).get("batch_id") or "").strip()
        if not batch_id or batch_id in seen:
            continue
        seen.add(batch_id)
        ordered_batch_ids.append(batch_id)

    if not ordered_batch_ids:
        return None

    if current_batch_id in ordered_batch_ids:
        current_idx = ordered_batch_ids.index(current_batch_id)
        for candidate in ordered_batch_ids[current_idx + 1 :]:
            if candidate != current_batch_id:
                return candidate

    for candidate in ordered_batch_ids:
        if candidate != current_batch_id:
            return candidate
    return None


def _compute_ml_feature_quality_summary(features: dict[str, Any]) -> dict[str, Any]:
    values = list((features or {}).values())
    feature_count = len(values)
    null_feature_count = sum(1 for value in values if value is None)

    numeric_values = [float(value) for value in values if isinstance(value, (int, float))]
    numeric_feature_count = len(numeric_values)
    zero_feature_count = sum(1 for value in numeric_values if abs(value) < 1e-9)

    denominator = feature_count if feature_count > 0 else 1
    numeric_denominator = numeric_feature_count if numeric_feature_count > 0 else 1

    return {
        "feature_count": feature_count,
        "null_feature_count": null_feature_count,
        "null_feature_rate": round(null_feature_count / denominator, 4),
        "numeric_feature_count": numeric_feature_count,
        "zero_feature_count": zero_feature_count,
        "zero_feature_rate": round(zero_feature_count / numeric_denominator, 4),
    }


def _compute_ml_feature_distribution_deltas(
    current_features: dict[str, Any],
    baseline_features: dict[str, Any],
) -> dict[str, Any]:
    deltas: dict[str, dict[str, Any]] = {}
    absolute_deltas: list[float] = []
    absolute_pct_deltas: list[float] = []

    for feature_name in sorted(set((current_features or {}).keys()) & set((baseline_features or {}).keys())):
        current_value = (current_features or {}).get(feature_name)
        baseline_value = (baseline_features or {}).get(feature_name)
        if not isinstance(current_value, (int, float)) or not isinstance(baseline_value, (int, float)):
            continue

        current_num = float(current_value)
        baseline_num = float(baseline_value)
        delta = current_num - baseline_num
        abs_delta = abs(delta)
        pct_delta = None if abs(baseline_num) < 1e-9 else delta / abs(baseline_num)

        deltas[feature_name] = {
            "current": round(current_num, 4),
            "baseline": round(baseline_num, 4),
            "delta": round(delta, 4),
            "absolute_delta": round(abs_delta, 4),
            "pct_delta": round(pct_delta, 6) if pct_delta is not None else None,
        }
        absolute_deltas.append(abs_delta)
        if pct_delta is not None:
            absolute_pct_deltas.append(abs(pct_delta))

    comparable_feature_count = len(deltas)
    return {
        "comparison_available": comparable_feature_count > 0,
        "comparable_feature_count": comparable_feature_count,
        "mean_absolute_delta": round(sum(absolute_deltas) / comparable_feature_count, 4)
        if comparable_feature_count
        else 0.0,
        "mean_absolute_pct_delta": round(sum(absolute_pct_deltas) / len(absolute_pct_deltas), 6)
        if absolute_pct_deltas
        else 0.0,
        "feature_deltas": deltas,
    }


def _resolve_ml_drift_policy_config(domain: str) -> dict[str, Any]:
    default = {
        "delta_thresholds": {
            "pct_delta": {"warning": 0.1, "error": 0.2, "critical": 0.35},
            "absolute_delta": {"warning": 100.0, "error": 500.0, "critical": 1000.0},
        },
        "quality_thresholds": {
            "null_feature_rate": {"warning": 0.05, "error": 0.15, "critical": 0.3},
            "zero_feature_rate": {"warning": 0.2, "error": 0.45, "critical": 0.7},
        },
        "sla_thresholds": {
            "ack_hours_warning": 24,
            "ack_hours_breach": 72,
            "resolve_hours_warning": 72,
            "resolve_hours_breach": 168,
        },
        "reminder_hours_threshold": 24,
        "history_limit_default": 20,
    }
    try:
        policy = get_import_policy((domain or "").strip().lower())
        controls_cfg = policy.get("controls_config") if isinstance(policy, dict) else None
        ml_cfg = controls_cfg.get("ml_drift") if isinstance(controls_cfg, dict) else None
        if isinstance(ml_cfg, dict):
            merged = {
                **default,
                **{k: v for k, v in ml_cfg.items() if k not in {"delta_thresholds", "quality_thresholds", "sla_thresholds"}},
            }
            delta_cfg = ml_cfg.get("delta_thresholds") if isinstance(ml_cfg.get("delta_thresholds"), dict) else {}
            quality_cfg = ml_cfg.get("quality_thresholds") if isinstance(ml_cfg.get("quality_thresholds"), dict) else {}
            sla_cfg = ml_cfg.get("sla_thresholds") if isinstance(ml_cfg.get("sla_thresholds"), dict) else {}
            merged["delta_thresholds"] = {
                "pct_delta": {
                    **default["delta_thresholds"]["pct_delta"],
                    **(delta_cfg.get("pct_delta") or {}),
                },
                "absolute_delta": {
                    **default["delta_thresholds"]["absolute_delta"],
                    **(delta_cfg.get("absolute_delta") or {}),
                },
            }
            merged["quality_thresholds"] = {
                "null_feature_rate": {
                    **default["quality_thresholds"]["null_feature_rate"],
                    **(quality_cfg.get("null_feature_rate") or {}),
                },
                "zero_feature_rate": {
                    **default["quality_thresholds"]["zero_feature_rate"],
                    **(quality_cfg.get("zero_feature_rate") or {}),
                },
            }
            merged["sla_thresholds"] = {
                **default["sla_thresholds"],
                **sla_cfg,
            }
            return merged
    except Exception as e:
        logging.info(f"ml drift policy fallback for {domain}: {e}")
    return default


def _severity_rank(level: str) -> int:
    order = {"info": 0, "warning": 1, "error": 2, "critical": 3}
    return order.get((level or "").lower(), 0)


def _classify_threshold_severity(value: float, thresholds: dict[str, Any]) -> str | None:
    triggered: str | None = None
    for level in ("warning", "error", "critical"):
        threshold = thresholds.get(level) if isinstance(thresholds, dict) else None
        if isinstance(threshold, (int, float)) and value >= float(threshold):
            triggered = level
    return triggered


def _compute_ml_drift_alerts(
    drift: dict[str, Any],
    current_quality: dict[str, Any],
    policy_config: dict[str, Any],
) -> dict[str, Any]:
    alerts: list[dict[str, Any]] = []
    severity_counts = {"warning": 0, "error": 0, "critical": 0}

    quality_cfg = policy_config.get("quality_thresholds") if isinstance(policy_config, dict) else {}
    for metric_name in ("null_feature_rate", "zero_feature_rate"):
        value = current_quality.get(metric_name)
        if not isinstance(value, (int, float)):
            continue
        severity = _classify_threshold_severity(float(value), quality_cfg.get(metric_name) or {})
        if severity:
            severity_counts[severity] += 1
            alerts.append(
                {
                    "category": "quality",
                    "metric": metric_name,
                    "severity": severity,
                    "value": round(float(value), 6),
                    "thresholds": quality_cfg.get(metric_name) or {},
                }
            )

    delta_cfg = policy_config.get("delta_thresholds") if isinstance(policy_config, dict) else {}
    feature_deltas = drift.get("feature_deltas") if isinstance(drift, dict) else {}
    for feature_name, payload in (feature_deltas or {}).items():
        pct_abs = abs(float(payload.get("pct_delta"))) if isinstance(payload.get("pct_delta"), (int, float)) else None
        abs_delta = abs(float(payload.get("absolute_delta"))) if isinstance(payload.get("absolute_delta"), (int, float)) else None

        pct_sev = (
            _classify_threshold_severity(pct_abs, delta_cfg.get("pct_delta") or {})
            if pct_abs is not None
            else None
        )
        abs_sev = (
            _classify_threshold_severity(abs_delta, delta_cfg.get("absolute_delta") or {})
            if abs_delta is not None
            else None
        )
        severity = None
        if pct_sev and abs_sev:
            severity = pct_sev if _severity_rank(pct_sev) >= _severity_rank(abs_sev) else abs_sev
        else:
            severity = pct_sev or abs_sev

        if severity:
            severity_counts[severity] += 1
            alerts.append(
                {
                    "category": "drift",
                    "feature": feature_name,
                    "severity": severity,
                    "pct_delta": round(pct_abs, 6) if pct_abs is not None else None,
                    "absolute_delta": round(abs_delta, 4) if abs_delta is not None else None,
                    "thresholds": {
                        "pct_delta": delta_cfg.get("pct_delta") or {},
                        "absolute_delta": delta_cfg.get("absolute_delta") or {},
                    },
                }
            )

    highest_severity = "none"
    for level in ("critical", "error", "warning"):
        if severity_counts[level] > 0:
            highest_severity = level
            break

    return {
        "policy": policy_config,
        "highest_severity": highest_severity,
        "severity_counts": severity_counts,
        "alerts": alerts,
    }


def _drift_ack_allowed_transitions() -> dict[str, set[str]]:
    return {
        "triaged": {"in_progress", "accepted_risk", "resolved"},
        "in_progress": {"accepted_risk", "resolved"},
        "accepted_risk": {"in_progress", "resolved"},
        "resolved": {"in_progress"},
    }


def _resolve_latest_drift_ack(domain: str, current_batch_id: str, search_limit: int = 200) -> dict[str, Any] | None:
    rows = list_audit_logs_filtered(
        limit=max(10, min(search_limit, 500)),
        event_type="ml_feature_drift_acknowledged",
        subject_type="ml_feature_drift",
    )
    normalized_domain = (domain or "").strip().lower()
    normalized_batch_id = (current_batch_id or "").strip()
    for row in rows or []:
        details = row.get("details") if isinstance(row, dict) else {}
        if not isinstance(details, dict):
            continue
        row_domain = (details.get("domain") or "").strip().lower()
        row_batch = (details.get("current_batch_id") or "").strip()
        if row_domain == normalized_domain and row_batch == normalized_batch_id:
            return {
                "status": str(details.get("status") or "").strip().lower(),
                "details": details,
                "created_at": row.get("created_at"),
                "signature_hash_ref": row.get("signature_hash_ref"),
            }
    return None


def _validate_drift_ack_transition(previous_status: str | None, next_status: str) -> None:
    allowed_statuses = set(_drift_ack_allowed_transitions().keys())
    if next_status not in allowed_statuses:
        raise HTTPException(status_code=400, detail="status must be one of triaged|in_progress|accepted_risk|resolved")
    if previous_status and previous_status != next_status:
        allowed_next = _drift_ack_allowed_transitions().get(previous_status, set())
        if next_status not in allowed_next:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid drift ack transition: {previous_status} -> {next_status}",
            )


def _to_utc_datetime(value: str | None) -> dt.datetime | None:
    parsed = parse_iso8601(value)
    if parsed is None:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=dt.timezone.utc)
    return parsed.astimezone(dt.timezone.utc)


def _hours_between(start: dt.datetime | None, end: dt.datetime | None) -> float | None:
    if start is None or end is None:
        return None
    delta = end - start
    return round(max(0.0, delta.total_seconds() / 3600.0), 4)


def _sla_level(hours_value: float | None, warning_threshold: float, breach_threshold: float, pending: bool) -> str:
    if hours_value is None:
        return "pending" if pending else "none"
    if hours_value >= float(breach_threshold):
        return "breach"
    if hours_value >= float(warning_threshold):
        return "warning"
    return "ok"


def _build_ml_drift_scorecard(domain: str, limit: int = 50) -> dict[str, Any]:
    normalized_domain = (domain or "").strip().lower()
    policy = _resolve_ml_drift_policy_config(normalized_domain)
    sla = policy.get("sla_thresholds") if isinstance(policy, dict) else {}

    ack_warning = float((sla or {}).get("ack_hours_warning", 24))
    ack_breach = float((sla or {}).get("ack_hours_breach", 72))
    resolve_warning = float((sla or {}).get("resolve_hours_warning", 72))
    resolve_breach = float((sla or {}).get("resolve_hours_breach", 168))

    safe_limit = max(1, min(limit, 200))
    summary_rows = list_audit_logs_filtered(
        limit=safe_limit * 5,
        event_type="ml_feature_drift_summarized",
        subject_type="ml_feature_drift",
    )
    ack_rows = list_audit_logs_filtered(
        limit=safe_limit * 10,
        event_type="ml_feature_drift_acknowledged",
        subject_type="ml_feature_drift",
    )

    summary_by_batch: dict[str, dict[str, Any]] = {}
    for row in summary_rows or []:
        details = row.get("details") if isinstance(row, dict) else {}
        if not isinstance(details, dict):
            continue
        if (details.get("domain") or "").strip().lower() != normalized_domain:
            continue
        batch_id = str(details.get("current_batch_id") or "").strip()
        if not batch_id or batch_id in summary_by_batch:
            continue
        summary_by_batch[batch_id] = {
            "batch_id": batch_id,
            "generated_at": details.get("generated_at") or row.get("created_at"),
            "highest_severity": details.get("highest_severity") or "none",
            "severity_counts": details.get("severity_counts") or {},
            "signature_hash_ref": row.get("signature_hash_ref"),
        }

    ack_by_batch: dict[str, list[dict[str, Any]]] = {}
    for row in ack_rows or []:
        details = row.get("details") if isinstance(row, dict) else {}
        if not isinstance(details, dict):
            continue
        if (details.get("domain") or "").strip().lower() != normalized_domain:
            continue
        batch_id = str(details.get("current_batch_id") or "").strip()
        if not batch_id:
            continue
        ack_by_batch.setdefault(batch_id, []).append(
            {
                "status": str(details.get("status") or "").strip().lower(),
                "acknowledged_at": details.get("acknowledged_at") or row.get("created_at"),
                "owner_id": details.get("owner_id"),
                "reason_code": details.get("reason_code"),
                "signature_hash_ref": row.get("signature_hash_ref"),
            }
        )

    now_utc = dt.datetime.utcnow().replace(tzinfo=dt.timezone.utc)
    trend: list[dict[str, Any]] = []
    for batch_id, summary in summary_by_batch.items():
        generated_at_dt = _to_utc_datetime(summary.get("generated_at"))
        events = ack_by_batch.get(batch_id) or []
        event_pairs: list[tuple[dt.datetime, dict[str, Any]]] = []
        for event in events:
            ack_dt = _to_utc_datetime(event.get("acknowledged_at"))
            if ack_dt is None:
                continue
            event_pairs.append((ack_dt, event))
        event_pairs.sort(key=lambda pair: pair[0])

        first_ack_dt = event_pairs[0][0] if event_pairs else None
        resolved_dt = None
        latest_event = None
        for ack_dt, event in event_pairs:
            latest_event = event
            if event.get("status") == "resolved":
                resolved_dt = ack_dt
                break
        if latest_event is None and events:
            latest_event = events[-1]

        ack_age_hours = _hours_between(generated_at_dt, first_ack_dt)
        resolve_age_hours = _hours_between(generated_at_dt, resolved_dt)
        pending_ack_hours = _hours_between(generated_at_dt, now_utc) if first_ack_dt is None else ack_age_hours
        pending_resolve_hours = _hours_between(generated_at_dt, now_utc) if resolved_dt is None else resolve_age_hours

        ack_sla = _sla_level(pending_ack_hours, ack_warning, ack_breach, pending=first_ack_dt is None)
        resolve_sla = _sla_level(pending_resolve_hours, resolve_warning, resolve_breach, pending=resolved_dt is None)

        latest_status = str((latest_event or {}).get("status") or "unacknowledged").strip().lower()
        trend.append(
            {
                "batch_id": batch_id,
                "generated_at": summary.get("generated_at"),
                "highest_severity": summary.get("highest_severity"),
                "severity_counts": summary.get("severity_counts") or {},
                "current_status": latest_status,
                "owner_id": (latest_event or {}).get("owner_id"),
                "age_to_acknowledge_hours": ack_age_hours,
                "age_to_resolve_hours": resolve_age_hours,
                "pending_ack_age_hours": pending_ack_hours,
                "pending_resolve_age_hours": pending_resolve_hours,
                "sla": {
                    "ack": ack_sla,
                    "resolve": resolve_sla,
                },
                "signature_hash_ref": summary.get("signature_hash_ref"),
            }
        )

    trend.sort(key=lambda item: str(item.get("generated_at") or ""), reverse=True)
    trend = trend[:safe_limit]

    ack_values = [float(item.get("age_to_acknowledge_hours")) for item in trend if isinstance(item.get("age_to_acknowledge_hours"), (int, float))]
    resolve_values = [float(item.get("age_to_resolve_hours")) for item in trend if isinstance(item.get("age_to_resolve_hours"), (int, float))]

    open_high_severity_count = sum(
        1
        for item in trend
        if str(item.get("highest_severity") or "none") in {"error", "critical"}
        and str(item.get("current_status") or "") != "resolved"
    )
    ack_breach_count = sum(1 for item in trend if (item.get("sla") or {}).get("ack") == "breach")
    resolve_breach_count = sum(1 for item in trend if (item.get("sla") or {}).get("resolve") == "breach")
    pending_ack_count = sum(1 for item in trend if str(item.get("current_status") or "") == "unacknowledged")
    pending_resolution_count = sum(1 for item in trend if str(item.get("current_status") or "") != "resolved")

    return {
        "domain": normalized_domain,
        "count": len(trend),
        "policy": {
            "sla_thresholds": {
                "ack_hours_warning": ack_warning,
                "ack_hours_breach": ack_breach,
                "resolve_hours_warning": resolve_warning,
                "resolve_hours_breach": resolve_breach,
            }
        },
        "kpis": {
            "avg_age_to_acknowledge_hours": round(sum(ack_values) / len(ack_values), 4) if ack_values else None,
            "avg_age_to_resolve_hours": round(sum(resolve_values) / len(resolve_values), 4) if resolve_values else None,
            "open_high_severity_count": open_high_severity_count,
            "ack_breach_count": ack_breach_count,
            "resolve_breach_count": resolve_breach_count,
            "pending_ack_count": pending_ack_count,
            "pending_resolution_count": pending_resolution_count,
        },
        "trend": trend,
    }


def _build_ml_drift_escalation_artifacts(domain: str, limit: int = 50) -> dict[str, Any]:
    scorecard = _build_ml_drift_scorecard(domain, limit=limit)
    policy = _resolve_ml_drift_policy_config(domain)
    sla = policy.get("sla_thresholds") if isinstance(policy, dict) else {}
    resolve_warning = float((sla or {}).get("resolve_hours_warning", 72))
    resolve_breach = float((sla or {}).get("resolve_hours_breach", 168))

    queue: list[dict[str, Any]] = []
    owner_alerts: dict[str, dict[str, Any]] = {}

    for item in scorecard.get("trend") or []:
        severity = str(item.get("highest_severity") or "none")
        status = str(item.get("current_status") or "unacknowledged")
        if severity not in {"error", "critical"}:
            continue
        if status == "resolved":
            continue

        open_hours = item.get("pending_resolve_age_hours")
        open_hours_num = float(open_hours) if isinstance(open_hours, (int, float)) else 0.0
        escalation_level = "monitor"
        if open_hours_num >= resolve_breach:
            escalation_level = "breach"
        elif open_hours_num >= resolve_warning:
            escalation_level = "warning"

        owner_id = str(item.get("owner_id") or "").strip() or "unassigned"
        payload = {
            "batch_id": item.get("batch_id"),
            "severity": severity,
            "status": status,
            "escalation_level": escalation_level,
            "pending_resolve_age_hours": open_hours_num,
            "pending_ack_age_hours": item.get("pending_ack_age_hours"),
            "generated_at": item.get("generated_at"),
            "sla": item.get("sla") or {},
        }
        queue.append(payload)

        owner_bucket = owner_alerts.setdefault(
            owner_id,
            {
                "owner_id": owner_id,
                "count": 0,
                "highest_severity": "none",
                "items": [],
            },
        )
        owner_bucket["count"] += 1
        if _severity_rank(severity) > _severity_rank(owner_bucket.get("highest_severity") or "none"):
            owner_bucket["highest_severity"] = severity
        owner_bucket["items"].append(payload)

    owner_alert_list = list(owner_alerts.values())
    owner_alert_list.sort(
        key=lambda row: (
            -_severity_rank(str(row.get("highest_severity") or "none")),
            -int(row.get("count") or 0),
            str(row.get("owner_id") or ""),
        )
    )

    return {
        "domain": scorecard.get("domain"),
        "count": len(queue),
        "queue": queue,
        "owner_alerts": owner_alert_list,
        "policy": {
            "resolve_hours_warning": resolve_warning,
            "resolve_hours_breach": resolve_breach,
        },
    }


def _build_ml_drift_reminder_preview(domain: str, limit: int = 50, min_open_hours: float | None = None) -> dict[str, Any]:
    scorecard = _build_ml_drift_scorecard(domain, limit=limit)
    policy = _resolve_ml_drift_policy_config(domain)
    default_threshold = float((policy or {}).get("reminder_hours_threshold", 24))
    threshold = default_threshold if min_open_hours is None else max(0.0, float(min_open_hours))

    reminders: list[dict[str, Any]] = []
    for item in scorecard.get("trend") or []:
        status = str(item.get("current_status") or "unacknowledged")
        if status == "resolved":
            continue
        open_hours = item.get("pending_resolve_age_hours")
        open_hours_num = float(open_hours) if isinstance(open_hours, (int, float)) else 0.0
        if open_hours_num < threshold:
            continue
        reminders.append(
            {
                "batch_id": item.get("batch_id"),
                "owner_id": item.get("owner_id") or "unassigned",
                "status": status,
                "highest_severity": item.get("highest_severity") or "none",
                "pending_resolve_age_hours": open_hours_num,
                "recommended_action": "send_reminder",
            }
        )

    return {
        "domain": scorecard.get("domain"),
        "count": len(reminders),
        "threshold_hours": threshold,
        "reminders": reminders,
    }


def _fit_linear_trend(values: list[float]) -> dict[str, float]:
    n = len(values)
    if n == 0:
        return {"intercept": 0.0, "slope": 0.0}
    if n == 1:
        return {"intercept": float(values[0]), "slope": 0.0}

    sum_x = float(sum(range(n)))
    sum_y = float(sum(values))
    sum_xy = float(sum(i * float(values[i]) for i in range(n)))
    sum_x2 = float(sum(i * i for i in range(n)))
    denom = (n * sum_x2) - (sum_x * sum_x)
    if abs(denom) < 1e-9:
        return {"intercept": float(values[-1]), "slope": 0.0}

    slope = ((n * sum_xy) - (sum_x * sum_y)) / denom
    intercept = (sum_y - (slope * sum_x)) / n
    return {"intercept": round(intercept, 6), "slope": round(slope, 6)}


def _predict_linear_trend(intercept: float, slope: float, start_index: int, horizon: int) -> list[float]:
    safe_horizon = max(1, min(horizon, 24))
    return [round((intercept + (slope * (start_index + i))), 6) for i in range(safe_horizon)]


def _evaluate_forecast_mae(actual: list[float], predicted: list[float]) -> float:
    if not actual or not predicted:
        return 0.0
    size = min(len(actual), len(predicted))
    if size <= 0:
        return 0.0
    return round(sum(abs(float(actual[i]) - float(predicted[i])) for i in range(size)) / size, 6)


def _resolve_latest_model_manifest(
    *,
    model_key: str,
    domain: str,
    model_version: str | None = None,
    limit: int = 200,
) -> dict[str, Any] | None:
    rows = list_audit_logs_filtered(
        limit=max(20, min(limit, 500)),
        event_type="ml_model_manifest_registered",
        subject_type="ml_model_manifest",
    )
    normalized_domain = (domain or "").strip().lower()
    normalized_key = (model_key or "").strip().lower()
    desired_version = (model_version or "").strip()

    for row in rows or []:
        details = row.get("details") if isinstance(row, dict) else {}
        if not isinstance(details, dict):
            continue
        if (details.get("domain") or "").strip().lower() != normalized_domain:
            continue
        if (details.get("model_key") or "").strip().lower() != normalized_key:
            continue
        if desired_version and str(details.get("model_version") or "").strip() != desired_version:
            continue
        return {
            **details,
            "registered_at": details.get("registered_at") or row.get("created_at"),
            "signature_hash_ref": row.get("signature_hash_ref"),
        }
    return None


def _list_model_manifests(*, model_key: str, domain: str, limit: int = 20) -> list[dict[str, Any]]:
    rows = list_audit_logs_filtered(
        limit=max(20, min(limit * 6, 500)),
        event_type="ml_model_manifest_registered",
        subject_type="ml_model_manifest",
    )
    normalized_domain = (domain or "").strip().lower()
    normalized_key = (model_key or "").strip().lower()
    manifests: list[dict[str, Any]] = []
    seen_versions: set[str] = set()
    for row in rows or []:
        details = row.get("details") if isinstance(row, dict) else {}
        if not isinstance(details, dict):
            continue
        if (details.get("domain") or "").strip().lower() != normalized_domain:
            continue
        if (details.get("model_key") or "").strip().lower() != normalized_key:
            continue
        version = str(details.get("model_version") or "").strip()
        if version and version in seen_versions:
            continue
        if version:
            seen_versions.add(version)
        manifests.append(
            {
                "model_version": version,
                "status": details.get("status"),
                "training": details.get("training") or {},
                "readiness": details.get("readiness") or {},
                "registered_at": details.get("registered_at") or row.get("created_at"),
                "signature_hash_ref": row.get("signature_hash_ref"),
            }
        )
        if len(manifests) >= limit:
            break
    return manifests


def _build_demand_forecast_manifest(
    *,
    domain: str,
    model_key: str,
    training_values: list[float],
    holdout_values: list[float],
    holdout_predictions: list[float],
    trend_params: dict[str, float],
    posture_domain: str,
    max_mae_ratio: float,
    approve_if_ready: bool,
) -> dict[str, Any]:
    import uuid

    baseline = max(1e-6, (sum(abs(v) for v in training_values) / len(training_values)) if training_values else 1.0)
    mae = _evaluate_forecast_mae(holdout_values, holdout_predictions)
    mae_ratio = round(float(mae) / float(baseline), 6)

    posture = _build_ml_drift_scorecard(posture_domain, limit=30)
    posture_kpis = posture.get("kpis") or {}

    readiness_checks = {
        "mae_ratio_ok": mae_ratio <= float(max_mae_ratio),
        "drift_open_high_severity_ok": int(posture_kpis.get("open_high_severity_count") or 0) == 0,
        "drift_resolve_breach_ok": int(posture_kpis.get("resolve_breach_count") or 0) == 0,
        "drift_pending_ack_ok": int(posture_kpis.get("pending_ack_count") or 0) == 0,
    }
    is_ready = all(readiness_checks.values())
    status = "promoted" if (approve_if_ready and is_ready) else ("registered_ready" if is_ready else "registered_blocked")

    now_iso = dt.datetime.utcnow().replace(microsecond=0).isoformat() + "Z"
    model_version = dt.datetime.utcnow().strftime("%Y%m%d%H%M%S")
    model_id = str(uuid.uuid4())

    return {
        "model_id": model_id,
        "model_key": model_key,
        "model_version": model_version,
        "domain": (domain or "").strip().lower(),
        "registered_at": now_iso,
        "status": status,
        "training": {
            "series_points": len(training_values) + len(holdout_values),
            "train_points": len(training_values),
            "holdout_points": len(holdout_values),
            "mae": mae,
            "mae_ratio": mae_ratio,
            "max_mae_ratio": float(max_mae_ratio),
        },
        "readiness": {
            "is_ready": is_ready,
            "checks": readiness_checks,
            "posture_domain": posture_domain,
            "posture_kpis": {
                "open_high_severity_count": int(posture_kpis.get("open_high_severity_count") or 0),
                "resolve_breach_count": int(posture_kpis.get("resolve_breach_count") or 0),
                "pending_ack_count": int(posture_kpis.get("pending_ack_count") or 0),
            },
        },
        "model": {
            "kind": "linear_trend_v1",
            "params": {
                "intercept": float(trend_params.get("intercept") or 0.0),
                "slope": float(trend_params.get("slope") or 0.0),
            },
        },
        "feature_contract": {
            "contract_version": "demand_forecast_contract_2026.1",
            "metric": "stock_turnover",
            "source": "ops_orders_snapshot + sage_inventory_snapshot",
        },
    }


async def _process_sage_import_job(
    *,
    job_id: str | None,
    batch_id: str,
    imported_at: str,
    meta: ImportMeta,
    datasets: dict[str, dict],
    idempotency_key: str | None,
    raise_on_error: bool,
) -> dict | None:
    async def _run_attempt(*, attempt: int, attempts: list[dict], max_attempts: int):
            hasher = hashlib.sha256()
            for dataset_name in sorted(datasets.keys()):
                payload = datasets.get(dataset_name) or {}
                raw = payload.get("content") or b""
                if raw:
                    hasher.update(raw)

            customers_rows, customers_diag = _load_dataset_bytes(
                "customers",
                (datasets.get("customers") or {}).get("content") or b"",
                (datasets.get("customers") or {}).get("filename"),
                (datasets.get("customers") or {}).get("content_type"),
                REQUIRED_CUSTOMERS,
                ALIASES_CUSTOMERS,
            ) if "customers" in datasets else ([], {"provided": False, "rows": 0})

            ar_rows, ar_diag = _load_dataset_bytes(
                "ar",
                (datasets.get("ar") or {}).get("content") or b"",
                (datasets.get("ar") or {}).get("filename"),
                (datasets.get("ar") or {}).get("content_type"),
                REQUIRED_AR,
                ALIASES_AR,
            ) if "ar" in datasets else ([], {"provided": False, "rows": 0})

            ap_rows, ap_diag = _load_dataset_bytes(
                "ap",
                (datasets.get("ap") or {}).get("content") or b"",
                (datasets.get("ap") or {}).get("filename"),
                (datasets.get("ap") or {}).get("content_type"),
                REQUIRED_AP,
                ALIASES_AP,
            ) if "ap" in datasets else ([], {"provided": False, "rows": 0})

            gl_rows, gl_diag = _load_dataset_bytes(
                "gl",
                (datasets.get("gl") or {}).get("content") or b"",
                (datasets.get("gl") or {}).get("filename"),
                (datasets.get("gl") or {}).get("content_type"),
                REQUIRED_GL,
                ALIASES_GL,
            ) if "gl" in datasets else ([], {"provided": False, "rows": 0})

            inventory_rows, inventory_diag = _load_dataset_bytes(
                "inventory",
                (datasets.get("inventory") or {}).get("content") or b"",
                (datasets.get("inventory") or {}).get("filename"),
                (datasets.get("inventory") or {}).get("content_type"),
                REQUIRED_INVENTORY,
                ALIASES_INVENTORY,
            ) if "inventory" in datasets else ([], {"provided": False, "rows": 0})

            staff_rows, staff_diag = _load_dataset_bytes(
                "staff",
                (datasets.get("staff") or {}).get("content") or b"",
                (datasets.get("staff") or {}).get("filename"),
                (datasets.get("staff") or {}).get("content_type"),
                REQUIRED_STAFF,
                ALIASES_STAFF,
            ) if "staff" in datasets else ([], {"provided": False, "rows": 0})

            customers_models, customers_rej = _normalize_rows_with_rejections("customers", customers_rows, to_customers)
            ar_models, ar_rej = _normalize_rows_with_rejections("ar", ar_rows, to_ar)
            ap_models, ap_rej = _normalize_rows_with_rejections("ap", ap_rows, to_ap)
            gl_models, gl_rej = _normalize_rows_with_rejections("gl", gl_rows, to_gl)
            inv_models, inv_rej = _normalize_rows_with_rejections("inventory", inventory_rows, to_inventory)
            staff_models, staff_rej = _normalize_rows_with_rejections("staff", staff_rows, to_staff)

            bundle = ImportBundle(
                meta=meta,
                customers=customers_models,
                ar=ar_models,
                ap=ap_models,
                gl=gl_models,
                inventory=inv_models,
                staff=staff_models,
            )

            counts_preview = {
                "customers": len(bundle.customers),
                "ar": len(bundle.ar),
                "ap": len(bundle.ap),
                "gl": len(bundle.gl),
                "inventory": len(bundle.inventory),
                "staff": len(bundle.staff),
            }
            hasher.update(str(counts_preview).encode("utf-8"))
            import_hash = hasher.hexdigest()
            lineage_key = _build_deterministic_lineage_key(
                source_system="sage50",
                batch_id=batch_id,
                imported_at=imported_at,
                datasets=datasets,
                counts=counts_preview,
            )

            if is_duplicate_import(import_hash):
                raise HTTPException(status_code=409, detail="Duplicate import detected within recent window")

            # Insert snapshots with proper error handling - fail fast if persistence fails
            try:
                c_count = insert_snapshot("sage_customers_snapshot", batch_id, imported_at, [x.model_dump() for x in bundle.customers])
                ar_count = insert_snapshot("sage_ar_snapshot", batch_id, imported_at, [x.model_dump() for x in bundle.ar])
                ap_count = insert_snapshot("sage_ap_snapshot", batch_id, imported_at, [x.model_dump() for x in bundle.ap])
                gl_count = insert_snapshot("sage_gl_snapshot", batch_id, imported_at, [x.model_dump() for x in bundle.gl])
                inv_count = insert_snapshot("sage_inventory_snapshot", batch_id, imported_at, [x.model_dump() for x in bundle.inventory])
                staff_dicts = [x.model_dump() for x in bundle.staff]
                staff_count = insert_snapshot("sage_staff_snapshot", batch_id, imported_at, staff_dicts)
            except SnapshotInsertError as e:
                logging.error(f"Sage import failed during snapshot insert: {e}")
                update_import_job(job_id, status="failed", metadata={"error": str(e), "table": e.table})
                raise HTTPException(status_code=500, detail=f"Database insert failed for {e.table}: {e.original_error}")

            # Validate insert counts match expected
            expected_counts = {
                "customers": len(bundle.customers),
                "ar": len(bundle.ar),
                "ap": len(bundle.ap),
                "gl": len(bundle.gl),
                "inventory": len(bundle.inventory),
                "staff": len(bundle.staff),
            }
            actual_counts = {
                "customers": c_count,
                "ar": ar_count,
                "ap": ap_count,
                "gl": gl_count,
                "inventory": inv_count,
                "staff": staff_count,
            }
            mismatches = {k: {"expected": expected_counts[k], "actual": actual_counts[k]} 
                         for k in expected_counts if expected_counts[k] != actual_counts[k]}
            if mismatches:
                logging.error(f"Insert count mismatch detected: {mismatches}")
                update_import_job(job_id, status="failed", metadata={"error": "count_mismatch", "mismatches": mismatches})
                raise HTTPException(status_code=500, detail=f"Insert count mismatch: {mismatches}")

            synced_count = 0
            if staff_dicts:
                try:
                    synced_count = sync_staff_batch(staff_dicts)
                except Exception as e:
                    logging.error(f"Post-import staff sync failed: {e}")

            lineage = {
                "customers": customers_diag,
                "ar": ar_diag,
                "ap": ap_diag,
                "gl": gl_diag,
                "inventory": inventory_diag,
                "staff": staff_diag,
            }
            ifrs_warnings = _ifrs_finance_lineage_warnings(bundle)
            if ifrs_warnings:
                lineage["compliance"] = {
                    "framework": "IFRS-baseline-2026.1",
                    "ifrs_warnings": ifrs_warnings,
                }
            rejections = _header_level_rejections(lineage) + customers_rej + ar_rej + ap_rej + gl_rej + inv_rej + staff_rej
            rejected_count = insert_import_rejections(job_id, rejections)
            controls_policy = _resolve_controls_policy_config("sage")
            control_rollup = _compute_import_control_rollup(
                lineage,
                rejected_rows=rejected_count,
                policy_config=controls_policy,
            )
            lineage["control_rollup"] = control_rollup
            final_status, gate = _quality_gate_status(lineage=lineage, rejected_count=rejected_count)
            quality_score = gate["quality_score"]
            if final_status == "succeeded":
                set_promoted_kpi_batch(
                    domain="sage",
                    batch_id=batch_id,
                    job_id=job_id,
                    quality_score=quality_score,
                    rejection_rate=gate.get("rejection_rate"),
                    reason="quality_gate_passed",
                )

            counts = {
                "customers": c_count,
                "ar": ar_count,
                "ap": ap_count,
                "gl": gl_count,
                "inventory": inv_count,
                "staff": staff_count,
                "staff_synced": synced_count,
                "rejected_rows": rejected_count,
            }

            attempts.append({"attempt": attempt, "status": "succeeded"})
            update_import_job(
                job_id,
                status=final_status,
                counts=counts,
                lineage=lineage,
                quality_score=quality_score,
                metadata={
                    "source_system": "sage50",
                    "idempotency_key": idempotency_key,
                    "lineage_key": lineage_key,
                    "control_rollup": control_rollup,
                    "attempts": attempts,
                    "max_attempts": max_attempts,
                    "quality_gate": gate,
                },
            )

            audit_event(
                "sage_import_validated",
                {
                    "batch_id": batch_id,
                    "job_id": job_id,
                    "counts": counts,
                    "hash": import_hash,
                    "lineage_key": lineage_key,
                    "lineage": lineage,
                },
            )
            # Bust in-process TTL caches so the dashboard reflects fresh data immediately
            from src.cache import invalidate_cache_tags
            invalidate_cache_tags(
                "inventory", "inventory_dashboard",
                "finance", "finance_kpis", "finance_trend", "finance_gl", "executive",
            )
            return {
                "batch_id": batch_id,
                "job_id": job_id,
                "imported_at": imported_at,
                "counts": {
                    "customers": c_count,
                    "ar": ar_count,
                    "ap": ap_count,
                    "gl": gl_count,
                    "inventory": inv_count,
                    "staff": staff_count,
                },
                "rejected_rows": rejected_count,
                "status": "imported" if final_status == "succeeded" else "partial_success",
                "quality_gate": gate,
                "kpi_promotion": "promoted" if final_status == "succeeded" else "preserved_previous",
                "lineage_key": lineage_key,
                "control_rollup": control_rollup,
                "notes": f"Synced {synced_count} active staff references." if synced_count else None,
            }

    return await _run_import_with_retry(
        job_id=job_id,
        source_system="sage50",
        idempotency_key=idempotency_key,
        raise_on_error=raise_on_error,
        run_attempt=_run_attempt,
    )


async def _process_hr_import_job(
    *,
    job_id: str | None,
    batch_id: str,
    imported_at: str,
    datasets: dict[str, dict],
    idempotency_key: str | None,
    raise_on_error: bool,
) -> dict | None:
    async def _run_attempt(*, attempt: int, attempts: list[dict], max_attempts: int):
            payroll_rows, payroll_diag = _load_dataset_bytes(
                "payroll",
                (datasets.get("payroll") or {}).get("content") or b"",
                (datasets.get("payroll") or {}).get("filename"),
                (datasets.get("payroll") or {}).get("content_type"),
                ["employee_id", "salary", "overtime_hours", "overtime_rate"],
                ALIASES_HR_PAYROLL,
            ) if "payroll" in datasets else ([], {"provided": False, "rows": 0})
            abs_rows, abs_diag = _load_dataset_bytes(
                "absences",
                (datasets.get("absences") or {}).get("content") or b"",
                (datasets.get("absences") or {}).get("filename"),
                (datasets.get("absences") or {}).get("content_type"),
                ["employee_id", "date", "hours"],
                ALIASES_HR_ABSENCES,
            ) if "absences" in datasets else ([], {"provided": False, "rows": 0})

            from src.db import insert_snapshot as _ins, SnapshotInsertError

            try:
                pc = _ins("hr_payroll_snapshot", batch_id, imported_at, payroll_rows)
                ac = _ins("hr_absence_snapshot", batch_id, imported_at, abs_rows)
            except SnapshotInsertError as e:
                logging.error(f"HR import failed during snapshot insert: {e}")
                update_import_job(job_id, status="failed", metadata={"error": str(e), "table": e.table})
                raise HTTPException(status_code=500, detail=f"Database insert failed for {e.table}: {e.original_error}")
            lineage = {"payroll": payroll_diag, "absences": abs_diag}
            payroll_warnings = _payroll_baseline_lineage_warnings(payroll_rows, abs_rows)
            if payroll_warnings:
                lineage["compliance"] = {
                    "framework": "Payroll-baseline-2026.1",
                    "warnings": payroll_warnings,
                }

            controls_policy = _resolve_controls_policy_config("hr")
            control_rollup = _compute_import_control_rollup(
                lineage,
                rejected_rows=0,
                policy_config=controls_policy,
            )
            lineage["control_rollup"] = control_rollup

            lineage_key = _build_deterministic_lineage_key(
                source_system="hr_upload",
                batch_id=batch_id,
                imported_at=imported_at,
                datasets=datasets,
                counts={"payroll": pc, "absences": ac},
            )
            final_status, gate = _quality_gate_status(lineage=lineage, rejected_count=0)
            attempts.append({"attempt": attempt, "status": "succeeded"})
            update_import_job(
                job_id,
                status=final_status,
                counts={"payroll": pc, "absences": ac},
                lineage=lineage,
                quality_score=gate["quality_score"],
                metadata={"source_system": "hr_upload", "idempotency_key": idempotency_key, "lineage_key": lineage_key, "control_rollup": control_rollup, "attempts": attempts, "max_attempts": max_attempts, "quality_gate": gate},
            )
            audit_event("hr_import", {"batch_id": batch_id, "job_id": job_id, "counts": {"payroll": pc, "absences": ac}, "lineage_key": lineage_key, "lineage": lineage})
            return {
                "batch_id": batch_id,
                "job_id": job_id,
                "imported_at": imported_at,
                "counts": {"payroll": pc, "absences": ac},
                "status": "imported" if final_status == "succeeded" else "partial_success",
                "quality_gate": gate,
                "lineage_key": lineage_key,
                "control_rollup": control_rollup,
            }

    return await _run_import_with_retry(
        job_id=job_id,
        source_system="hr_upload",
        idempotency_key=idempotency_key,
        raise_on_error=raise_on_error,
        run_attempt=_run_attempt,
    )


async def _process_ops_import_job(
    *,
    job_id: str | None,
    batch_id: str,
    imported_at: str,
    datasets: dict[str, dict],
    idempotency_key: str | None,
    raise_on_error: bool,
) -> dict | None:
    async def _run_attempt(*, attempt: int, attempts: list[dict], max_attempts: int):
            ord_rows, orders_diag = _load_dataset_bytes(
                "orders",
                (datasets.get("orders") or {}).get("content") or b"",
                (datasets.get("orders") or {}).get("filename"),
                (datasets.get("orders") or {}).get("content_type"),
                ["order_id", "created_at", "fulfilled_at", "sku", "quantity"],
                ALIASES_OPS_ORDERS,
            ) if "orders" in datasets else ([], {"provided": False, "rows": 0})
            down_rows, downtime_diag = _load_dataset_bytes(
                "downtime",
                (datasets.get("downtime") or {}).get("content") or b"",
                (datasets.get("downtime") or {}).get("filename"),
                (datasets.get("downtime") or {}).get("content_type"),
                ["machine_id", "started_at", "ended_at", "minutes"],
                ALIASES_OPS_DOWNTIME,
            ) if "downtime" in datasets else ([], {"provided": False, "rows": 0})
            from src.db import insert_snapshot as _ins, SnapshotInsertError

            try:
                oc = _ins("ops_orders_snapshot", batch_id, imported_at, ord_rows)
                dc = _ins("ops_downtime_snapshot", batch_id, imported_at, down_rows)
            except SnapshotInsertError as e:
                logging.error(f"OPS import failed during snapshot insert: {e}")
                update_import_job(job_id, status="failed", metadata={"error": str(e), "table": e.table})
                raise HTTPException(status_code=500, detail=f"Database insert failed for {e.table}: {e.original_error}")
            lineage = {"orders": orders_diag, "downtime": downtime_diag}
            final_status, gate = _quality_gate_status(lineage=lineage, rejected_count=0)
            attempts.append({"attempt": attempt, "status": "succeeded"})
            update_import_job(
                job_id,
                status=final_status,
                counts={"orders": oc, "downtime": dc},
                lineage=lineage,
                quality_score=gate["quality_score"],
                metadata={"source_system": "ops_upload", "idempotency_key": idempotency_key, "attempts": attempts, "max_attempts": max_attempts, "quality_gate": gate},
            )
            audit_event("ops_import", {"batch_id": batch_id, "job_id": job_id, "counts": {"orders": oc, "downtime": dc}, "lineage": lineage})
            return {
                "batch_id": batch_id,
                "job_id": job_id,
                "imported_at": imported_at,
                "counts": {"orders": oc, "downtime": dc},
                "status": "imported" if final_status == "succeeded" else "partial_success",
                "quality_gate": gate,
            }

    return await _run_import_with_retry(
        job_id=job_id,
        source_system="ops_upload",
        idempotency_key=idempotency_key,
        raise_on_error=raise_on_error,
        run_attempt=_run_attempt,
    )


async def _process_crm_import_job(
    *,
    job_id: str | None,
    batch_id: str,
    imported_at: str,
    datasets: dict[str, dict],
    idempotency_key: str | None,
    raise_on_error: bool,
) -> dict | None:
    async def _run_attempt(*, attempt: int, attempts: list[dict], max_attempts: int):
            pl_rows, pipeline_diag = _load_dataset_bytes(
                "pipeline",
                (datasets.get("pipeline") or {}).get("content") or b"",
                (datasets.get("pipeline") or {}).get("filename"),
                (datasets.get("pipeline") or {}).get("content_type"),
                ["opportunity_id", "customer_id", "amount", "stage", "status", "close_date"],
                ALIASES_CRM_PIPELINE,
            ) if "pipeline" in datasets else ([], {"provided": False, "rows": 0})
            from src.db import insert_snapshot as _ins, SnapshotInsertError

            try:
                pc = _ins("crm_pipeline_snapshot", batch_id, imported_at, pl_rows)
            except SnapshotInsertError as e:
                logging.error(f"CRM import failed during snapshot insert: {e}")
                update_import_job(job_id, status="failed", metadata={"error": str(e), "table": e.table})
                raise HTTPException(status_code=500, detail=f"Database insert failed for {e.table}: {e.original_error}")
            lineage = {"pipeline": pipeline_diag}
            final_status, gate = _quality_gate_status(lineage=lineage, rejected_count=0)
            attempts.append({"attempt": attempt, "status": "succeeded"})
            update_import_job(
                job_id,
                status=final_status,
                counts={"pipeline": pc},
                lineage=lineage,
                quality_score=gate["quality_score"],
                metadata={"source_system": "crm_upload", "idempotency_key": idempotency_key, "attempts": attempts, "max_attempts": max_attempts, "quality_gate": gate},
            )
            audit_event("crm_import", {"batch_id": batch_id, "job_id": job_id, "counts": {"pipeline": pc}, "lineage": lineage})
            return {
                "batch_id": batch_id,
                "job_id": job_id,
                "imported_at": imported_at,
                "counts": {"pipeline": pc},
                "status": "imported" if final_status == "succeeded" else "partial_success",
                "quality_gate": gate,
            }

    return await _run_import_with_retry(
        job_id=job_id,
        source_system="crm_upload",
        idempotency_key=idempotency_key,
        raise_on_error=raise_on_error,
        run_attempt=_run_attempt,
    )


def _normalize_rows_with_rejections(name: str, rows: list[dict], normalizer) -> tuple[list[Any], list[dict]]:
    accepted: list[Any] = []
    rejected: list[dict] = []
    for idx, row in enumerate(rows, start=2):
        try:
            converted = normalizer([row])
            if converted:
                accepted.append(converted[0])
        except Exception as exc:
            rejected.append(
                {
                    "dataset": name,
                    "row_number": idx,
                    "reason": "normalization_error",
                    "raw_row": row,
                    "details": {"error": str(exc)},
                }
            )
    return accepted, rejected


def _header_level_rejections(diags: dict[str, dict]) -> list[dict]:
    out: list[dict] = []
    for dataset, diag in diags.items():
        for header in (diag.get("unknown_headers") or []):
            out.append(
                {
                    "dataset": dataset,
                    "row_number": None,
                    "reason": "unknown_header",
                    "details": {"header": header},
                }
            )
        for header in (diag.get("duplicate_mapped_headers") or []):
            out.append(
                {
                    "dataset": dataset,
                    "row_number": None,
                    "reason": "duplicate_mapped_header",
                    "details": {"header": header},
                }
            )
    return out


def _quality_gate_status(lineage: dict[str, dict], rejected_count: int) -> tuple[str, dict]:
    dataset_count = max(1, len(lineage))
    quality_score = sum((x.get("quality_score") or 1.0) for x in lineage.values()) / dataset_count
    total_rows = sum(int((x.get("rows") or 0)) for x in lineage.values())
    rejection_rate = (rejected_count / total_rows) if total_rows > 0 else 0.0
    gate_passed = quality_score >= IMPORT_MIN_QUALITY_SCORE and rejection_rate <= IMPORT_MAX_REJECTION_RATE
    return (
        "succeeded" if gate_passed else "partial_success",
        {
            "quality_score": quality_score,
            "rejection_rate": rejection_rate,
            "min_quality_score": IMPORT_MIN_QUALITY_SCORE,
            "max_rejection_rate": IMPORT_MAX_REJECTION_RATE,
            "total_rows": total_rows,
            "rejected_rows": rejected_count,
            "gate_passed": gate_passed,
        },
    )


def _extract_idempotency_key(request: Request) -> str | None:
    value = (request.headers.get("Idempotency-Key") or request.headers.get("X-Idempotency-Key") or "").strip()
    if not value:
        return None
    if len(value) > 128:
        raise HTTPException(status_code=400, detail="Idempotency-Key too long")
    return value


def _replay_or_busy_response(existing_job: dict, imported_default: str):
    status = (existing_job.get("status") or "").lower()
    if status in ("running", "queued"):
        return JSONResponse(
            status_code=202,
            content={
                "status": "processing",
                "job_id": existing_job.get("id"),
                "batch_id": existing_job.get("batch_id"),
                "imported_at": existing_job.get("imported_at") or imported_default,
            },
        )
    if status in ("succeeded", "partial_success"):
        counts = existing_job.get("counts") or {}
        return {
            "batch_id": existing_job.get("batch_id"),
            "job_id": existing_job.get("id"),
            "imported_at": existing_job.get("imported_at") or imported_default,
            "counts": counts,
            "replayed": True,
            "status": "imported",
        }
    raise HTTPException(status_code=409, detail="Previous import with this Idempotency-Key failed. Use a new key to retry.")


@app.on_event("startup")
async def _start_background_monitors():
    enabled = os.getenv("ENABLE_EXPIRY_MONITOR", "0") in ("1", "true", "True")
    if not enabled:
        logging.info("Expiry monitor disabled (set ENABLE_EXPIRY_MONITOR=1 to enable).")
        return
    try:
        # Scan every 6 hours by default
        schedule_expiry_monitor(interval_minutes=360, thresholds=[90, 60, 30])
    except Exception as e:
        logging.error(f"Failed to start expiry monitor: {e}")


@app.on_event("startup")
async def _log_auth_store_resolution_status():
    """Log a clearer diagnostic for auth-store DNS connectivity issues."""
    try:
        # If a local `DATABASE_URL` is configured, prefer that and skip Supabase host check.
        if os.getenv("DATABASE_URL"):
            return
        from src.constants import ENV_SUPABASE_URL
        supabase_url = os.getenv(ENV_SUPABASE_URL, "")
        host = urlparse(supabase_url).hostname
        if not host:
            logging.warning("SUPABASE_URL is missing or invalid; auth refresh/login may fail.")
            return
        socket.getaddrinfo(host, 443)
    except Exception as e:
        logging.warning(f"Supabase host resolution check failed: {e}")

def require_admin_token(request: Request):
    # Prefer JWT-based admin verification
    verify_jwt(request, required_role="admin")
    return True

def require_role(request: Request, role: str):
    verify_jwt(request, required_role=role)
    return True

def require_roles(request: Request, roles: list[str]):
    payload = verify_jwt(request)
    have = set((payload or {}).get("roles", []))
    if not any(r in have for r in roles):
        raise HTTPException(status_code=403, detail="Insufficient role")
    return True


def _is_allowed_change_transition(current_status: str, target_status: str) -> bool:
    if current_status == target_status:
        return True
    return target_status in CHANGE_STATUS_TRANSITIONS.get(current_status, set())


def _is_allowed_transition(current_status: str, target_status: str, transitions: dict[str, set[str]]) -> bool:
    if current_status == target_status:
        return True
    return target_status in transitions.get(current_status, set())


def _audit_transition_denied(
    *,
    actor_id: str | None,
    subject_type: str,
    subject_id: str,
    current_status: str,
    target_status: str,
    policy_code: str,
    rejection_reason: str,
) -> None:
    audit_event(
        "controls_transition_denied",
        {
            "subject_type": subject_type,
            "subject_id": subject_id,
            "current_status": current_status,
            "target_status": target_status,
            "policy_code": policy_code,
            "rejection_reason": rejection_reason,
        },
        actor_id=actor_id,
        event_class="project_controls",
        action="status_transition",
        outcome="denied",
        reason_code=policy_code,
        subject_type=subject_type,
        subject_id=subject_id,
    )


def _is_high_impact_change(change_row: dict | None) -> bool:
    row = change_row or {}
    scope_level = str(row.get("impact_scope") or "").strip().lower()
    impact_cost = float(row.get("impact_cost") or 0)
    impact_days = int(row.get("impact_schedule_days") or 0)
    return (
        scope_level in HIGH_IMPACT_SCOPE_LEVELS
        or impact_cost >= HIGH_IMPACT_COST_THRESHOLD
        or impact_days >= HIGH_IMPACT_SCHEDULE_DAYS_THRESHOLD
    )


EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
ALLOWED_ROLES = {"admin", "ops", "hr", "sales", "viewer", "finance", "management"}


def normalize_email(value: str) -> str:
    email = (value or "").strip().lower()
    if not EMAIL_PATTERN.match(email):
        raise HTTPException(status_code=400, detail="Invalid email format")
    return email


def validate_password_strength(password: str) -> None:
    pwd = password or ""
    if len(pwd) < 10:
        raise HTTPException(status_code=400, detail="Password must be at least 10 characters")
    if not any(c.islower() for c in pwd):
        raise HTTPException(status_code=400, detail="Password must include a lowercase letter")
    if not any(c.isupper() for c in pwd):
        raise HTTPException(status_code=400, detail="Password must include an uppercase letter")
    if not any(c.isdigit() for c in pwd):
        raise HTTPException(status_code=400, detail="Password must include a number")
    if not any(c in "!@#$%^&*()-_=+[]{};:,.?/" for c in pwd):
        raise HTTPException(status_code=400, detail="Password must include a special character")


def normalize_roles(roles: list[str] | None) -> list[str]:
    values = [r.strip().lower() for r in (roles or []) if isinstance(r, str) and r.strip()]
    if not values:
        return ["viewer"]
    invalid = [r for r in values if r not in ALLOWED_ROLES]
    if invalid:
        raise HTTPException(status_code=400, detail=f"Invalid roles: {', '.join(invalid)}")
    return sorted(set(values))

class Lead(BaseModel):
    name: str
    email: str
    phone: str
    message: str
    service: str | None = None
    company_size: str | None = None
    contact_pref: str | None = None


class StockQuery(BaseModel):
    skus: list[str] | None = None  # If None → return top cached snapshot


class OrderItem(BaseModel):
    sku: str
    quantity: int


class SubmitOrder(BaseModel):
    customer_name: str
    customer_email: str
    customer_phone: str | None = None
    items: list[OrderItem]
    notes: str | None = None
    source: str | None = None
    lead_id: int | None = None


class TrackingResponse(BaseModel):
    id: str
    status: str
    last_update: str | None = None
    eta: str | None = None


class ToolCatalogItem(BaseModel):
    name: str
    description: str
    department: str
    source: str
    required_roles: list[str] = Field(default_factory=list)
    allowed_modes: list[str] = Field(default_factory=list)
    parameters: list[str] = Field(default_factory=list)


class ToolCatalogResponse(BaseModel):
    mode: str
    count: int
    tools: list[ToolCatalogItem] = Field(default_factory=list)


class ChatSource(BaseModel):
    question: str = ""
    answer: str = ""


class ChatOrchestrationMeta(BaseModel):
    mode: str
    trace_id: str
    tool_count: int
    tools: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)


class ChatResponse(BaseModel):
    answer: str
    bot: str
    sources: list[ChatSource] = Field(default_factory=list)
    orchestration: ChatOrchestrationMeta


class ChatRequest(BaseModel):
    question: str
    embedding: list[float] | None = None
    mode: str | None = None


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int
    roles: list[str]


class RefreshRequest(BaseModel):
    refresh_token: str


class LogoutRequest(BaseModel):
    refresh_token: str


# ---- Workflow Models --------------------------------------------------------

class IntentRequest(BaseModel):
    intent_type: str  # e.g., "order_restock", "send_reminder"
    payload: dict  # arbitrary details (e.g., sku, qty, customer_id)


class ApprovalRequest(BaseModel):
    intent_id: str
    approved: bool
    approver_note: str | None = None
    approval_reason: str | None = None
    attestation_text: str | None = None


class ProjectCreate(BaseModel):
    name: str
    description: str | None = None
    status: str = "active"
    activity_type: str | None = None
    supplier_name: str | None = None
    assigned_staff_id: str | None = None
    workflow_stage: str | None = None
    po_reference: str | None = None
    temperature_profile: str | None = None
    nafdac_sampling_status: str | None = None
    quality_check_status: str | None = "pending"
    quality_notes: str | None = None


class ScopeItemCreate(BaseModel):
    project_id: str
    title: str
    description: str | None = None
    priority: str = "medium"
    status: str = "planned"


class CostItemCreate(BaseModel):
    project_id: str
    cost_type: str
    amount: float
    currency: str = "NGN"
    status: str = "planned"
    note: str | None = None


class RiskItemCreate(BaseModel):
    project_id: str
    title: str
    description: str | None = None
    probability: int
    impact: int
    mitigation_plan: str | None = None
    owner_id: str | None = None
    status: str = "open"


class ChangeRequestCreate(BaseModel):
    project_id: str
    title: str
    description: str
    reason_code: str | None = None
    impact_scope: str | None = None
    impact_cost: float | None = None
    impact_schedule_days: int | None = None


class ChangeDecisionRequest(BaseModel):
    status: str  # approved | rejected | under_review | implemented
    approval_note: str | None = None
    approval_reason: str | None = None
    attestation_text: str | None = None


class StatusUpdateRequest(BaseModel):
    status: str
    reason_code: str | None = None


class ProjectStageUpdateRequest(BaseModel):
    workflow_stage: str
    reason_code: str | None = None
    nafdac_sampling_status: str | None = None
    quality_check_status: str | None = None
    quality_notes: str | None = None


class ImportPolicyPreviewRequest(BaseModel):
    domain: str
    lineage: dict[str, Any]
    rejected_rows: int = 0
    policy_override: dict[str, Any] | None = None


class ImportPolicyActivateRequest(BaseModel):
    domain: str
    controls_config: dict[str, Any]
    policy_version: str | None = None
    schema_version: str = "2026.1"
    approval_reason: str
    attestation_text: str | None = None
    notes: str | None = None


class ImportPolicyRollbackRequest(BaseModel):
    domain: str
    target_policy_version: str
    rollback_policy_version: str | None = None
    approval_reason: str
    attestation_text: str | None = None
    notes: str | None = None


class DriftAcknowledgeRequest(BaseModel):
    domain: str
    current_batch_id: str
    status: str
    owner_id: str | None = None
    remediation_notes: str | None = None
    remediation_actions: list[str] | None = None
    due_at: str | None = None
    reason_code: str | None = None
    attestation_text: str | None = None


class DriftReminderPreviewRequest(BaseModel):
    domain: str
    limit: int = 50
    min_open_hours: float | None = None


class DemandForecastTrainRequest(BaseModel):
    domain: str = "ops"
    min_points: int = 6
    holdout_points: int = 3
    posture_domain: str = "sage"
    max_mae_ratio: float = 0.35
    approve_if_ready: bool = False


class DemandForecastPredictRequest(BaseModel):
    domain: str = "ops"
    horizon: int = 3
    model_version: str | None = None


@app.get("/ai/tools", response_model=ToolCatalogResponse)
async def ai_tools_catalog(request: Request, mode: str | None = None):
    rate_limit(request)
    payload: dict[str, Any] = {}
    auth_header = request.headers.get("Authorization", "").strip()
    if auth_header.lower().startswith("bearer "):
        payload = verify_jwt(request)

    roles = {str(r).strip().lower() for r in ((payload or {}).get("roles") or []) if str(r).strip()}
    requested_mode = (mode or "").strip().lower() or None
    if not roles:
        effective_mode = "customer"
    else:
        effective_mode = requested_mode or "assistant"
    tools = tool_registry.list_tools(roles=roles, mode=effective_mode)
    return _normalize_tool_catalog(mode=effective_mode, tools=tools).model_dump()

@app.get("/")
def read_root():
    return {"message": "Chat API is running. Use /chat endpoint."}


@app.get("/health")
def health_check():
    """Structured health check for EOS and monitoring systems.

    Returns DB connectivity, latest Sage import timestamp, row counts for
    the two primary snapshot tables, and a stale_pipeline_alert flag that
    fires when no import has run in PIPELINE_STALE_HOURS hours.
    """
    from src.constants import PIPELINE_STALE_HOURS
    import datetime

    db_connected = False
    last_sage_import: str | None = None
    sage_ar_row_count = 0
    sage_gl_row_count = 0
    stale_pipeline_alert = True

    try:
        from src.db import db as _db
        # Lightweight connectivity probe
        probe = _db.table("placeware_alerts").select("id", count="exact").limit(1).execute()
        db_connected = True

        # Most recent successful import timestamp
        try:
            from src.db import get_latest_successful_import_batch
            batch_id = get_latest_successful_import_batch("sage")
            if batch_id:
                import_row = (
                    _db.table("placeware_import_jobs")
                    .select("completed_at")
                    .eq("batch_id", batch_id)
                    .order("completed_at", desc=True)
                    .limit(1)
                    .execute()
                    .data
                )
                if import_row:
                    last_sage_import = import_row[0].get("completed_at")
        except Exception:
            pass

        # AR snapshot row count
        try:
            ar_resp = _db.table("sage_ar_snapshot").select("id", count="exact").limit(1).execute()
            sage_ar_row_count = ar_resp.count or 0
        except Exception:
            pass

        # GL snapshot row count
        try:
            gl_resp = _db.table("sage_gl_snapshot").select("id", count="exact").limit(1).execute()
            sage_gl_row_count = gl_resp.count or 0
        except Exception:
            pass

        # Staleness check
        if last_sage_import:
            try:
                ts = datetime.datetime.fromisoformat(last_sage_import.replace("Z", "+00:00"))
                age_hours = (datetime.datetime.now(datetime.timezone.utc) - ts).total_seconds() / 3600
                stale_pipeline_alert = age_hours > PIPELINE_STALE_HOURS
            except Exception:
                stale_pipeline_alert = True
        else:
            stale_pipeline_alert = sage_ar_row_count == 0

        # Upsert a heartbeat row in agent_registry so EOS can query DB directly
        try:
            _db.table("agent_registry").upsert(
                {
                    "agent_name": "system",
                    "description": "Backend health heartbeat",
                    "last_heartbeat": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                    "enabled": True,
                },
                on_conflict="agent_name",
            ).execute()
        except Exception:
            pass

    except Exception as exc:
        logging.error(f"/health DB probe failed: {exc}")

    status = "ok" if db_connected and not stale_pipeline_alert else ("degraded" if db_connected else "error")

    return {
        "status": status,
        "db_connected": db_connected,
        "last_sage_import": last_sage_import,
        "sage_ar_row_count": sage_ar_row_count,
        "sage_gl_row_count": sage_gl_row_count,
        "stale_pipeline_alert": stale_pipeline_alert,
        "pipeline_stale_threshold_hours": PIPELINE_STALE_HOURS,
        "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
    }

@app.post("/chat", response_model=ChatResponse)
async def chat(request: Request):  # RAG + LLM answer with disclaimer
    rate_limit(request)
    auth_payload: dict[str, Any] = {}
    auth_header = request.headers.get("Authorization", "").strip()
    if auth_header.lower().startswith("bearer "):
        try:
            auth_payload = verify_jwt(request)
        except HTTPException as e:
            logging.warning(f"Optional chat auth ignored: {e.detail}")
    _validate_public_widget_access(request, auth_payload)
    data = await request.json()
    logging.info(f"/chat payload: {data}")
    question = data.get("question")
    embedding = data.get("embedding")
    requested_mode = data.get("mode")

    if not question or not isinstance(question, str) or not question.strip():
        return JSONResponse({"error": "'question' must be a non-empty string."}, status_code=400)

    roles = _normalize_roles(auth_payload)
    mode = _resolve_chat_mode(question=question, roles=roles, requested_mode=requested_mode)
    actor_id = (auth_payload or {}).get("sub") or (auth_payload or {}).get("id")
    actor_role = sorted(list(roles))[0] if roles else None
    trace_id = str(uuid.uuid4())

    if mode == "customer":
        try:
            intent_answer = _handle_customer_transaction_intent(question)
            if intent_answer:
                return _normalize_chat_contract(
                    answer=intent_answer,
                    bot=BOT_NAME,
                    sources=[],
                    mode=mode,
                    trace_id=trace_id,
                    tool_outputs=[],
                    tool_errors=[],
                ).model_dump()
        except Exception as e:
            logging.error(f"customer transaction intent failed: {e}")

    # --- Action intent intercept (all 6 action types) --------
    # For internal staff (mode != customer), detect and handle action phrases
    # before handing off to the LLM so the action actually gets executed.
    # Email uses a two-phase flow: compose → preview → user confirms → send.
    if mode != "customer":
        import time as _time_mod
        _dkey = _draft_key(auth_payload, request)
        _pending = _PENDING_EMAIL_DRAFTS.get(_dkey)

        # ── Phase 2: user is confirming or rejecting a pending draft ──────────
        if _pending:
            _expired = _pending.get("expires_at", 0) < _time_mod.time()
            if _expired:
                del _PENDING_EMAIL_DRAFTS[_dkey]
            elif _is_email_confirmation(question):
                # Send the stored draft without re-composing
                try:
                    from src.agent_registry import get_agent as _get_agent_ea
                    _send_agent = _get_agent_ea("email_agent", context={
                        "intent_text":         _pending["original_request"],
                        "department":          _pending["department"],
                        "precomposed_subject": _pending["subject"],
                        "precomposed_body":    _pending["body"],
                        "actor_id":            actor_id or "eos_chat",
                        "simulation":          False,
                        "enable_memory":       True,
                    })
                    _send_insight = _send_agent.run() if _send_agent else None
                    del _PENDING_EMAIL_DRAFTS[_dkey]
                    _send_answer = (
                        "\n".join(_send_insight.findings)
                        if _send_insight and _send_insight.findings
                        else f"Email sent to {_pending['department']} ({_pending['to_email']})."
                    )
                    try:
                        save_chat_history(user_id=actor_id, question=question, answer=_send_answer, sources=[])
                    except Exception:
                        pass
                    return _normalize_chat_contract(
                        answer=_send_answer, bot=BOT_NAME, sources=[], mode=mode,
                        trace_id=trace_id, tool_outputs=[], tool_errors=[],
                    ).model_dump()
                except Exception as _ce:
                    logging.error(f"Email confirm-send failed: {_ce}")
                    del _PENDING_EMAIL_DRAFTS[_dkey]
            elif _is_email_rejection(question):
                del _PENDING_EMAIL_DRAFTS[_dkey]
                _cancel_answer = "Email cancelled. Let me know if you'd like to send a different message."
                try:
                    save_chat_history(user_id=actor_id, question=question, answer=_cancel_answer, sources=[])
                except Exception:
                    pass
                return _normalize_chat_contract(
                    answer=_cancel_answer, bot=BOT_NAME, sources=[], mode=mode,
                    trace_id=trace_id, tool_outputs=[], tool_errors=[],
                ).model_dump()

        # ── Phase 1: detect action intent and dispatch ────────────────────────
        _action_type = _detect_action_intent(question)
        if _action_type:
            try:
                from src.eos.service import (
                    IntentParser as _IntentParser,
                    _handle_send_email_action,
                    _handle_send_whatsapp_action,
                    _handle_schedule_meeting_action,
                    _handle_task_creation,
                    _handle_generate_report_action,
                    _handle_trigger_replenishment_action,
                )
                _parser = _IntentParser()
                _intent = _parser._fallback_parse(question)

                # Email: compose a draft and ask for confirmation before sending
                if _action_type == "send_email":
                    try:
                        from src.agent_registry import get_agent as _get_agent_preview
                        _preview_agent = _get_agent_preview("email_agent", context={
                            "intent_text": question,
                            "department":  (_intent.get("parameters") or {}).get("department", "operations"),
                            "actor_id":    actor_id or "eos_chat",
                            "simulation":  True,
                            "enable_memory": True,
                        })
                        _preview_insight = _preview_agent.run() if _preview_agent else None
                        if _preview_insight and _preview_insight.metrics.get("subject"):
                            _dept   = _preview_insight.metrics.get("department", "operations")
                            _to     = _preview_insight.metrics.get("to_email", "")
                            _subj   = _preview_insight.metrics.get("subject", "")
                            _body   = _preview_insight.metrics.get("body", "")
                            # Store draft (TTL 10 min)
                            _PENDING_EMAIL_DRAFTS[_dkey] = {
                                "subject":          _subj,
                                "body":             _body,
                                "to_email":         _to,
                                "department":       _dept,
                                "original_request": question,
                                "expires_at":       _time_mod.time() + _EMAIL_DRAFT_TTL_SECONDS,
                            }
                            _preview_answer = (
                                f"Here's the draft email to **{_dept}** ({_to}):\n\n"
                                f"**Subject:** {_subj}\n\n"
                                f"{_body}\n\n"
                                f"---\n"
                                f"Reply **\"send it\"** to confirm, or tell me what to change."
                            )
                            try:
                                save_chat_history(user_id=actor_id, question=question, answer=_preview_answer, sources=[])
                            except Exception:
                                pass
                            return _normalize_chat_contract(
                                answer=_preview_answer, bot=BOT_NAME, sources=[], mode=mode,
                                trace_id=trace_id, tool_outputs=[], tool_errors=[],
                            ).model_dump()
                    except Exception as _pe:
                        logging.error(f"Email preview compose failed: {_pe}")
                        # Fall through to immediate send if preview fails

                # All other actions execute immediately
                _ACTION_DISPATCH = {
                    "send_email":            _handle_send_email_action,
                    "send_whatsapp":         _handle_send_whatsapp_action,
                    "schedule_meeting":      _handle_schedule_meeting_action,
                    "create_task":           _handle_task_creation,
                    "generate_report":       _handle_generate_report_action,
                    "trigger_replenishment": _handle_trigger_replenishment_action,
                }
                _handler = _ACTION_DISPATCH.get(_action_type)
                if _handler:
                    _result = await _handler(_intent, question, False)
                    _action_answer = (_result.get("report") or {}).get("summary") or "Action completed."
                    try:
                        save_chat_history(user_id=actor_id, question=question, answer=_action_answer, sources=[])
                    except Exception:
                        pass
                    return _normalize_chat_contract(
                        answer=_action_answer, bot=BOT_NAME, sources=[], mode=mode,
                        trace_id=trace_id, tool_outputs=[], tool_errors=[],
                    ).model_dump()
            except Exception as _ae:
                logging.error(f"action intent handler failed [{_action_type}]: {_ae}")
                # Fall through to normal LLM path if handler errors

    tool_outputs, tool_errors = _run_orchestration_plan(
        question=question,
        roles=roles,
        mode=mode,
        actor_id=actor_id,
        actor_role=actor_role,
        trace_id=trace_id,
    )

    if _is_executive_analytical_question(question=question, mode=mode) and not tool_outputs:
        answer = _build_missing_evidence_answer(tool_errors=tool_errors)
        tool_sources = _build_tool_sources(tool_outputs)
        return _normalize_chat_contract(
            answer=answer,
            bot=BOT_NAME,
            sources=tool_sources,
            mode=mode,
            trace_id=trace_id,
            tool_outputs=tool_outputs,
            tool_errors=tool_errors,
        ).model_dump()
    live_context_parts = []
    if tool_outputs:
        live_context_parts.append("ORCHESTRATION TOOL RESULTS:\n" + json.dumps(tool_outputs, indent=2))
    if tool_errors:
        live_context_parts.append("ORCHESTRATION TOOL WARNINGS:\n" + "\n".join(tool_errors))
    live_context_str = "\n\n".join(live_context_parts)
    results: list[tuple[str | None, str | None]] = []

    if not embedding:
        try:
            embedding = get_embedding(question)
        except Exception as e:
            logging.error(f"Embedding service error: {e}")
            embedding = None

    if embedding is None:
         # Proceed with non-vector context when embedding is unavailable.
         if live_context_str:
             logging.warning("Embedding unavailable; proceeding with live backend context only.")
             context = live_context_str
         else:
             logging.warning("Embedding unavailable and no live context; falling back to verified company profile context.")
             context = ""
    else:
        # Validate embedding
        if not isinstance(embedding, list) or len(embedding) != EMBEDDING_DIM or not all(isinstance(x, (float, int)) for x in embedding):
            return JSONResponse({"error": f"'embedding' must be a list of {EMBEDDING_DIM} floats."}, status_code=400)

        logging.info(f"Embedding OK. Querying Supabase…")
        results = retriever.retrieve(embedding, k=DEFAULT_TOP_K)
        retrieved_context = "\n\n".join(filter(None, [r[1] for r in results])) if results else ""

        # ── Knowledge base retrieval (compliance docs / ingested templates) ──────
        kb_context = ""
        try:
            from src.services.knowledge_service import KnowledgeService
            _kb_svc = KnowledgeService(llm=llm_client)
            _kb_result = _kb_svc.search(question, agent="chat", top_k=3)
            if _kb_result.context:
                kb_context = f"COMPLIANCE KNOWLEDGE BASE:\n{_kb_result.context}"
        except Exception as _kb_exc:
            logging.warning("Knowledge base search failed (non-fatal): %s", _kb_exc)

        # Combine Retrieved Docs + Knowledge Base + Live Data
        context = "\n\n".join(filter(None, [retrieved_context, kb_context, live_context_str])).strip()

    if context:
        context = f"{COMPANY_PROFILE_CONTEXT}\n\n{context}".strip()
    else:
        logging.warning("No retrieval/live context found; using verified company profile context only.")
        context = f"{COMPANY_PROFILE_CONTEXT}\n\nUser question: {question}".strip()

    # ── Conversation history — inject last 6 turns so LLM remembers prior actions ──
    try:
        _hist_user_id = (auth_payload or {}).get("sub") or (auth_payload or {}).get("id")
        if _hist_user_id:
            _prior = get_chat_history(user_id=_hist_user_id, limit=6)
            if _prior:
                _hist_lines = []
                for _h in reversed(_prior):  # oldest first
                    _hist_lines.append(f"User: {_h.get('question', '')}")
                    _hist_lines.append(f"Assistant: {_h.get('answer', '')}")
                context = context + "\n\n--- Recent Conversation ---\n" + "\n".join(_hist_lines)
    except Exception as _he:
        logging.warning(f"Chat history inject failed (non-fatal): {_he}")

    direct_answer = _build_grounded_direct_answer(question=question, tool_outputs=tool_outputs, mode=mode)
    if direct_answer:
        answer = direct_answer
    else:
        answer = llm_client.generate_response(
            context=context,
            question=question,
            instruction=_build_chat_instruction(mode=mode, question=question),
        )
    if not answer:
        answer = (
            f"{BOT_BRAND} supports Vaccine Distribution, Pharma Supply, Cold Chain Logistics, and Regulatory Support in Nigeria. "
            "Please ask a specific company or operations question and I will answer with available backend data."
        )
    answer = _enforce_mode_tone(answer=answer, mode=mode, question=question)
    # answer = append_disclaimer(answer)  # Removed per user request: disclaimer at bottom of chat, not per response
    sources = []
    try:
        user = getattr(request.state, "user", None)
        user_id = None
        if isinstance(user, dict):
            user_id = user.get("sub") or user.get("id")
        retrieval_sources = [{"question": q or "", "answer": a or ""} for (q, a) in (results or [])]
        tool_sources = _build_tool_sources(tool_outputs)
        sources = tool_sources + retrieval_sources
        save_chat_history(user_id=user_id, question=question, answer=answer, sources=sources)
    except Exception as e:
        logging.error(f"/chat history save failed: {e}")
    return _normalize_chat_contract(
        answer=answer,
        bot=BOT_NAME,
        sources=sources,
        mode=mode,
        trace_id=trace_id,
        tool_outputs=tool_outputs,
        tool_errors=tool_errors,
    ).model_dump()


@app.get("/chat/history")
async def chat_history(request: Request, limit: int = 30):
    rate_limit(request)
    payload = verify_jwt(request)
    user_id = payload.get("sub") or payload.get("id")
    if not user_id:
        raise HTTPException(status_code=401, detail="Missing user identity in token")
    safe_limit = max(1, min(limit, 200))
    rows = get_chat_history(user_id=user_id, limit=safe_limit)
    return {"history": rows, "count": len(rows)}

@app.post("/submit_lead")
async def submit_lead(lead: Lead):
    # Public form; consider separate rate limit bucket
    lead_id = store_lead(lead.model_dump(exclude_none=True))
    return {"success": True, "lead_id": lead_id}


# ---- New Endpoint Scaffolds -------------------------------------------------

@app.get("/stock")
async def stock_list(request: Request):
    rate_limit(request)
    """Return latest inventory snapshot (read-only) via GET."""
    try:
        rows = latest_inventory_snapshot()
        return {"stock": rows, "source": "snapshot", "disclaimer": "Availability subject to change."}
    except Exception as e:
        logging.error(f"/stock GET service error: {e}")
        return {"stock": [], "source": "unavailable", "disclaimer": "Availability subject to change."}


@app.post("/stock")
async def stock(request: Request, query: StockQuery):
    rate_limit(request)
    """Return latest inventory snapshot or selected SKUs (read-only)."""
    try:
        if query.skus:
            rows = inventory_by_skus(query.skus)
        else:
            rows = latest_inventory_snapshot()
        return {"stock": rows, "source": "snapshot", "disclaimer": "Availability subject to change."}
    except Exception as e:
        logging.error(f"/stock service error: {e}")
        return {"stock": [], "source": "unavailable", "disclaimer": "Availability subject to change."}


@app.get("/inventory/expiring")
async def inventory_expiring(request: Request, thresholds: Optional[str] = None):
    """Return expiring inventory tiers from the latest snapshot batch.

    thresholds: comma-separated days (e.g., "90,60,30"). Default [90,60,30].
    Roles: ops, sales, or admin.
    """
    require_roles(request, ["ops", "sales", "admin"])
    try:
        parsed: list[int] | None = None
        if thresholds:
            parsed = [int(x.strip()) for x in thresholds.split(",") if x.strip()]
        res = get_expiring_inventory(thresholds=parsed)
        return res
    except Exception as e:
        logging.error(f"/inventory/expiring error: {e}")
        return {"items": [], "summary": {"count": 0}}


@app.get("/debug/sage-counts")
async def debug_sage_counts(request: Request):
    """Admin-only: return row counts and latest import timestamps for all snapshot tables."""
    require_roles(request, ["admin"])
    tables = [
        "sage_ar_snapshot", "sage_inventory_snapshot", "sage_gl_snapshot",
        "sage_ap_snapshot", "sage_staff_snapshot", "sage_vendors_snapshot", "sage_coa_snapshot",
    ]
    result = {}
    for table in tables:
        try:
            resp = db.table(table).select("id", count="exact").limit(1).execute()
            latest = db.table(table).select("imported_at").order("imported_at", desc=True).limit(1).execute()
            result[table] = {
                "count": resp.count,
                "latest_import": (latest.data[0].get("imported_at") if latest.data else None),
            }
        except Exception as e:
            result[table] = {"count": None, "error": str(e)}
    return result


@app.post("/cache/clear")
async def admin_clear_cache(request: Request):
    """Admin-only: flush all in-process TTL cache entries."""
    require_roles(request, ["admin"])
    from src.cache import clear_cache
    clear_cache()
    return {"cleared": True, "message": "In-process TTL cache flushed."}


@app.get("/analytics/ar_trends")
async def analytics_ar_trends(request: Request, periods: int = 3):
    require_roles(request, ["admin", "finance", "management", "ops"])
    if periods < 1:
        periods = 1
    if periods > 12:
        periods = 12
    summary = ar_trend_summary(periods=periods)
    periods_list = summary.get("periods", [])
    trend_info = {}
    if len(periods_list) >= 2:
        prev = float(periods_list[-2].get("balance") or 0)
        curr = float(periods_list[-1].get("balance") or 0)
        change_pct = compute_change_pct(curr, prev)
        trend = trend_label(change_pct, positive_is_good=False)
        trend_info = {"trend": trend, "change_pct": change_pct}
    return {"summary": summary, "trend": trend_info}


@app.get("/analytics/kpis")
async def analytics_kpis(request: Request):
    require_role(request, "admin")
    try:
        base = kpis()
        ar_trends = ar_trend_summary(periods=6).get("periods", [])
        trend_info = {}
        if len(ar_trends) >= 2:
            prev = float(ar_trends[-2].get("balance") or 0)
            curr = float(ar_trends[-1].get("balance") or 0)
            change_pct = compute_change_pct(curr, prev)
            trend = trend_label(change_pct, positive_is_good=False)
            trend_info = {"trend": trend, "change_pct": change_pct}
        base["ar"] = {**base.get("ar", {}), "trend": trend_info}
        return {"kpis": base}
    except Exception as e:
        logging.error(f"/analytics/kpis error: {e}")
        return {"kpis": {"ar": {}, "ap": {}, "cash": None}}


@app.get("/reports/ar_aging")
async def reports_ar_aging(request: Request, format: str | None = None):
    require_role(request, "admin")
    try:
        data = ar_aging_buckets()
        if format and format.lower() == "csv":
            csv = "bucket,amount\n" + "\n".join([
                f"0_30,{data.get('0_30', 0)}",
                f"31_60,{data.get('31_60', 0)}",
                f"61_90,{data.get('61_90', 0)}",
                f"91_plus,{data.get('91_plus', 0)}",
            ])
            return Response(content=csv, media_type="text/csv")
        return {"aging": data}
    except Exception as e:
        logging.error(f"/reports/ar_aging error: {e}")
        return {"aging": {"0_30": 0, "31_60": 0, "61_90": 0, "91_plus": 0}}


@app.get("/reports/ar_aging/customers")
async def reports_ar_aging_customers(request: Request, bucket: str):
    """Detailed AR aging by customer for a given bucket.

    Roles: admin only.
    """
    require_role(request, "admin")
    try:
        customers = ar_aging_customers(bucket=bucket)
        return {"customers": customers}
    except Exception as e:
        logging.error(f"/reports/ar_aging/customers error: {e}")
        return {"customers": []}


@app.get("/analytics/forecast/ar_balance")
async def analytics_forecast_ar_balance(request: Request, window: int = 3, horizon: int = 3):
    require_role(request, "admin")
    if window < 1:
        window = 1
    if horizon < 1:
        horizon = 1
    try:
        return forecast_ar_balance(window=window, horizon=horizon)
    except Exception as e:
        logging.error(f"/analytics/forecast/ar_balance error: {e}")
        return {"series": [], "rolling": [], "forecast": []}


# ---- Workflow Orchestration -------------------------------------------------

@app.post("/workflow/intent")
async def workflow_intent(request: Request, intent: IntentRequest):
    require_role(request, "admin")
    import uuid, datetime
    intent_id = str(uuid.uuid4())
    recommendation = {}
    try:
        # Very simple recommendation stub based on intent_type
        if intent.intent_type == "order_restock":
            sku = intent.payload.get("sku")
            qty = int(intent.payload.get("qty", 0))
            recommendation = {"action": "create_order", "sku": sku, "qty": qty}
        elif intent.intent_type == "send_reminder":
            customer_id = intent.payload.get("customer_id")
            recommendation = {"action": "email_reminder", "customer_id": customer_id}
        else:
            recommendation = {"action": "none", "note": "Unknown intent_type"}
    finally:
        audit_event("intent_created", {
            "intent_id": intent_id,
            "intent_type": intent.intent_type,
            "payload": intent.payload,
            "recommendation": recommendation,
            "created_at": datetime.datetime.utcnow().isoformat() + "Z",
        })
    # Persist intent
    save_intent(intent_id=intent_id, intent_type=intent.intent_type, payload=intent.payload, recommendation=recommendation)
    return {"intent_id": intent_id, "recommendation": recommendation}


@app.post("/workflow/approve")
async def workflow_approve(request: Request, approval: ApprovalRequest):
    require_role(request, "admin")
    import datetime
    audit_event(
        "intent_approval",
        {
            "intent_id": approval.intent_id,
            "approved": approval.approved,
            "approver_note": approval.approver_note,
            "approved_at": datetime.datetime.utcnow().isoformat() + "Z",
            "approval_reason": approval.approval_reason,
        },
        actor_id=request.state.user.get("sub"),
        action="workflow_approve_intent",
        outcome="success",
        reason_code="approved" if approval.approved else "rejected",
        subject_type="intent",
        subject_id=approval.intent_id,
        approval_reason=approval.approval_reason,
        attestation_text=approval.attestation_text or "I attest this workflow approval decision is authorized and reviewed.",
    )
    # Persist approval and update intent status; no side effects in MVP
    save_approval(intent_id=approval.intent_id, approved=approval.approved, approver_note=approval.approver_note)
    status = "approved" if approval.approved else "rejected"
    return {"intent_id": approval.intent_id, "status": status}


@app.get("/workflow/pending")
async def workflow_pending(request: Request, limit: int = 50):
    require_role(request, "admin")
    rows = list_pending_intents(limit=limit)
    return {"data": rows}


@app.post("/controls/projects")
async def controls_create_project(request: Request, payload: ProjectCreate):
    require_roles(request, ["admin", "ops", "management"])
    if payload.status not in PROJECT_STATUS_ALLOWED:
        raise HTTPException(status_code=400, detail="Invalid project status")
    created = create_project_record(
        name=payload.name,
        description=payload.description,
        owner_id=payload.assigned_staff_id or request.state.user.get("sub"),
        status=payload.status,
        activity_type=payload.activity_type,
        supplier_name=payload.supplier_name,
        assigned_staff_id=payload.assigned_staff_id,
        workflow_stage=payload.workflow_stage,
        po_reference=payload.po_reference,
        temperature_profile=payload.temperature_profile,
        nafdac_sampling_status=payload.nafdac_sampling_status,
        quality_check_status=payload.quality_check_status,
        quality_notes=payload.quality_notes,
    )
    if not created:
        raise HTTPException(status_code=500, detail="Failed to create project")
    audit_event(
        "controls_project_created",
        {"project_id": created.get("id"), "name": payload.name, "status": payload.status},
        actor_id=request.state.user.get("sub"),
        event_class="project_controls",
        action="create_project",
        outcome="success",
        subject_type="project",
        subject_id=created.get("id"),
    )
    return created


@app.get("/controls/projects")
async def controls_list_projects(request: Request, limit: int = 50, status: str | None = None):
    require_roles(request, ["admin", "ops", "management"])
    return {"data": list_projects(limit=max(1, min(limit, 200)), status=status)}


@app.get("/controls/readiness")
async def controls_readiness(request: Request):
    require_roles(request, ["admin", "ops", "management"])
    checks: dict[str, bool] = {
        "table_placeware_projects": False,
        "col_workflow_stage": False,
        "col_nafdac_sampling_status": False,
        "col_quality_check_status": False,
        "col_quality_notes": False,
        "col_quality_checked_by": False,
        "col_quality_checked_at": False,
    }
    try:
        import psycopg2

        dsn = get_psycopg_dsn()
        conn = psycopg2.connect(dsn)
        try:
            with conn.cursor() as cur:
                cur.execute("select to_regclass('public.placeware_projects')")
                checks["table_placeware_projects"] = cur.fetchone()[0] is not None
                if checks["table_placeware_projects"]:
                    cur.execute(
                        """
                        select column_name
                        from information_schema.columns
                        where table_schema = 'public' and table_name = 'placeware_projects'
                        """
                    )
                    cols = {str(row[0]) for row in (cur.fetchall() or [])}
                    checks["col_workflow_stage"] = "workflow_stage" in cols
                    checks["col_nafdac_sampling_status"] = "nafdac_sampling_status" in cols
                    checks["col_quality_check_status"] = "quality_check_status" in cols
                    checks["col_quality_notes"] = "quality_notes" in cols
                    checks["col_quality_checked_by"] = "quality_checked_by" in cols
                    checks["col_quality_checked_at"] = "quality_checked_at" in cols
        finally:
            conn.close()
    except Exception as exc:
        return {
            "ready": False,
            "checks": checks,
            "reason": f"readiness_check_failed: {exc}",
        }

    ready = all(checks.values())
    return {
        "ready": ready,
        "checks": checks,
        "reason": None if ready else "project workflow schema not fully applied",
    }


@app.post("/controls/projects/{project_id}/stage")
async def controls_update_project_stage(request: Request, project_id: str, payload: ProjectStageUpdateRequest):
    require_roles(request, ["admin", "ops", "management"])

    current = get_project(project_id)
    if not current:
        raise HTTPException(status_code=404, detail="Project not found")

    current_stage = str(current.get("workflow_stage") or "port_clearing").strip().lower()
    target_stage = payload.workflow_stage.strip().lower()
    if target_stage not in PROJECT_WORKFLOW_STAGES:
        raise HTTPException(status_code=400, detail=f"Invalid workflow stage: {target_stage}")

    actor_id = request.state.user.get("sub")
    if not _is_allowed_transition(current_stage, target_stage, PROJECT_STAGE_TRANSITIONS):
        _audit_transition_denied(
            actor_id=actor_id,
            subject_type="project",
            subject_id=project_id,
            current_status=current_stage,
            target_status=target_stage,
            policy_code="project_stage_transition_not_allowed",
            rejection_reason="Requested project stage transition violates workflow policy graph",
        )
        raise HTTPException(status_code=409, detail=f"Transition not allowed: {current_stage} -> {target_stage}")

    qc_status = str(payload.quality_check_status or current.get("quality_check_status") or "pending").strip().lower()
    if qc_status not in PROJECT_QC_STATUS_ALLOWED:
        raise HTTPException(status_code=400, detail=f"Invalid quality_check_status: {qc_status}")

    nafdac_status = str(payload.nafdac_sampling_status or current.get("nafdac_sampling_status") or "pending").strip().lower()

    if target_stage in PROJECT_QC_GATED_STAGES and qc_status not in PROJECT_QC_APPROVED_STATUSES:
        _audit_transition_denied(
            actor_id=actor_id,
            subject_type="project",
            subject_id=project_id,
            current_status=current_stage,
            target_status=target_stage,
            policy_code="qc_gate_not_satisfied",
            rejection_reason="Quality Control sign-off is required before entering this stage",
        )
        raise HTTPException(status_code=409, detail="Quality Control must approve before this stage transition")

    if target_stage == "released_for_issuing" and nafdac_status != "released":
        _audit_transition_denied(
            actor_id=actor_id,
            subject_type="project",
            subject_id=project_id,
            current_status=current_stage,
            target_status=target_stage,
            policy_code="nafdac_release_required",
            rejection_reason="NAFDAC release is required before issuing",
        )
        raise HTTPException(status_code=409, detail="NAFDAC status must be released before moving to issuing")

    quality_checked_by = actor_id if qc_status in PROJECT_QC_APPROVED_STATUSES else None
    quality_checked_at = dt.datetime.utcnow().replace(microsecond=0).isoformat() + "Z" if quality_checked_by else None

    updated = update_project_stage(
        project_id,
        workflow_stage=target_stage,
        nafdac_sampling_status=nafdac_status,
        quality_check_status=qc_status,
        quality_notes=payload.quality_notes,
        quality_checked_by=quality_checked_by,
        quality_checked_at=quality_checked_at,
    )
    if not updated:
        raise HTTPException(status_code=500, detail="Failed to update workflow stage")

    audit_event(
        "controls_project_stage_updated",
        {
            "project_id": project_id,
            "from": current_stage,
            "to": target_stage,
            "reason_code": payload.reason_code,
            "quality_check_status": qc_status,
            "nafdac_sampling_status": nafdac_status,
        },
        actor_id=actor_id,
        event_class="project_controls",
        action="update_project_stage",
        outcome="success",
        reason_code=payload.reason_code or target_stage,
        subject_type="project",
        subject_id=project_id,
    )
    return updated


@app.post("/controls/scope")
async def controls_create_scope_item(request: Request, payload: ScopeItemCreate):
    require_role(request, "admin")
    if payload.status not in SCOPE_STATUS_ALLOWED:
        raise HTTPException(status_code=400, detail="Invalid scope status")
    created = create_scope_item(
        project_id=payload.project_id,
        title=payload.title,
        description=payload.description,
        priority=payload.priority,
        status=payload.status,
        created_by=request.state.user.get("sub"),
    )
    if not created:
        raise HTTPException(status_code=500, detail="Failed to create scope item")
    audit_event(
        "controls_scope_item_created",
        {"project_id": payload.project_id, "scope_item_id": created.get("id"), "title": payload.title},
        actor_id=request.state.user.get("sub"),
        event_class="project_controls",
        action="create_scope_item",
        outcome="success",
        subject_type="scope_item",
        subject_id=created.get("id"),
    )
    return created


@app.get("/controls/scope")
async def controls_list_scope_items(request: Request, project_id: str, limit: int = 100):
    require_role(request, "admin")
    return {"data": list_scope_items(project_id=project_id, limit=max(1, min(limit, 500)))}


@app.post("/controls/scope/{scope_item_id}/status")
async def controls_update_scope_status(request: Request, scope_item_id: str, payload: StatusUpdateRequest):
    require_role(request, "admin")
    if payload.status not in SCOPE_STATUS_ALLOWED:
        raise HTTPException(status_code=400, detail="Invalid scope status")
    current = get_scope_item(scope_item_id)
    if not current:
        raise HTTPException(status_code=404, detail="Scope item not found")
    current_status = str(current.get("status") or "").strip().lower()
    actor_id = request.state.user.get("sub")
    if not _is_allowed_transition(current_status, payload.status, SCOPE_STATUS_TRANSITIONS):
        _audit_transition_denied(
            actor_id=actor_id,
            subject_type="scope_item",
            subject_id=scope_item_id,
            current_status=current_status,
            target_status=payload.status,
            policy_code="scope_transition_not_allowed",
            rejection_reason="Requested scope status transition violates policy graph",
        )
        raise HTTPException(status_code=409, detail=f"Transition not allowed: {current_status} -> {payload.status}")
    updated = update_scope_item_status(scope_item_id=scope_item_id, status=payload.status)
    if not updated:
        raise HTTPException(status_code=500, detail="Failed to update scope status")
    audit_event(
        "controls_scope_status_updated",
        {
            "scope_item_id": scope_item_id,
            "from": current_status,
            "to": payload.status,
            "reason_code": payload.reason_code,
        },
        actor_id=actor_id,
        event_class="project_controls",
        action="update_scope_status",
        outcome="success",
        reason_code=payload.reason_code or payload.status,
        subject_type="scope_item",
        subject_id=scope_item_id,
    )
    return updated


@app.post("/controls/cost")
async def controls_create_cost_item(request: Request, payload: CostItemCreate):
    require_role(request, "admin")
    if payload.amount < 0:
        raise HTTPException(status_code=400, detail="amount must be non-negative")
    if payload.status not in COST_STATUS_ALLOWED:
        raise HTTPException(status_code=400, detail="Invalid cost status")
    created = create_cost_item(
        project_id=payload.project_id,
        cost_type=payload.cost_type,
        amount=payload.amount,
        currency=payload.currency,
        status=payload.status,
        note=payload.note,
        created_by=request.state.user.get("sub"),
    )
    if not created:
        raise HTTPException(status_code=500, detail="Failed to create cost item")
    audit_event(
        "controls_cost_item_created",
        {"project_id": payload.project_id, "cost_item_id": created.get("id"), "amount": payload.amount, "currency": payload.currency},
        actor_id=request.state.user.get("sub"),
        event_class="project_controls",
        action="create_cost_item",
        outcome="success",
        subject_type="cost_item",
        subject_id=created.get("id"),
    )
    return created


@app.get("/controls/cost")
async def controls_list_cost_items(request: Request, project_id: str, limit: int = 100):
    require_role(request, "admin")
    return {"data": list_cost_items(project_id=project_id, limit=max(1, min(limit, 500)))}


@app.post("/controls/cost/{cost_item_id}/status")
async def controls_update_cost_status(request: Request, cost_item_id: str, payload: StatusUpdateRequest):
    require_role(request, "admin")
    if payload.status not in COST_STATUS_ALLOWED:
        raise HTTPException(status_code=400, detail="Invalid cost status")
    current = get_cost_item(cost_item_id)
    if not current:
        raise HTTPException(status_code=404, detail="Cost item not found")
    current_status = str(current.get("status") or "").strip().lower()
    actor_id = request.state.user.get("sub")
    if not _is_allowed_transition(current_status, payload.status, COST_STATUS_TRANSITIONS):
        _audit_transition_denied(
            actor_id=actor_id,
            subject_type="cost_item",
            subject_id=cost_item_id,
            current_status=current_status,
            target_status=payload.status,
            policy_code="cost_transition_not_allowed",
            rejection_reason="Requested cost status transition violates policy graph",
        )
        raise HTTPException(status_code=409, detail=f"Transition not allowed: {current_status} -> {payload.status}")
    updated = update_cost_item_status(cost_item_id=cost_item_id, status=payload.status)
    if not updated:
        raise HTTPException(status_code=500, detail="Failed to update cost status")
    audit_event(
        "controls_cost_status_updated",
        {
            "cost_item_id": cost_item_id,
            "from": current_status,
            "to": payload.status,
            "reason_code": payload.reason_code,
        },
        actor_id=actor_id,
        event_class="project_controls",
        action="update_cost_status",
        outcome="success",
        reason_code=payload.reason_code or payload.status,
        subject_type="cost_item",
        subject_id=cost_item_id,
    )
    return updated


@app.post("/controls/risk")
async def controls_create_risk_item(request: Request, payload: RiskItemCreate):
    require_role(request, "admin")
    if payload.probability < 1 or payload.probability > 5 or payload.impact < 1 or payload.impact > 5:
        raise HTTPException(status_code=400, detail="probability and impact must be between 1 and 5")
    if payload.status not in RISK_STATUS_ALLOWED:
        raise HTTPException(status_code=400, detail="Invalid risk status")
    risk_score = payload.probability * payload.impact
    if risk_score >= RISK_SCORE_MITIGATION_THRESHOLD and not (payload.mitigation_plan or "").strip():
        raise HTTPException(status_code=400, detail="mitigation_plan is required for elevated risk score")
    if risk_score >= RISK_SCORE_OWNER_THRESHOLD and not (payload.owner_id or "").strip():
        raise HTTPException(status_code=400, detail="owner_id is required for high risk score")
    if risk_score >= RISK_SCORE_MITIGATION_THRESHOLD and payload.status == "closed":
        raise HTTPException(status_code=400, detail="high risk score cannot start in closed status")
    created = create_risk_item(
        project_id=payload.project_id,
        title=payload.title,
        description=payload.description,
        probability=payload.probability,
        impact=payload.impact,
        mitigation_plan=payload.mitigation_plan,
        owner_id=payload.owner_id,
        status=payload.status,
        created_by=request.state.user.get("sub"),
    )
    if not created:
        raise HTTPException(status_code=500, detail="Failed to create risk item")
    audit_event(
        "controls_risk_item_created",
        {"project_id": payload.project_id, "risk_id": created.get("id"), "probability": payload.probability, "impact": payload.impact},
        actor_id=request.state.user.get("sub"),
        event_class="project_controls",
        action="create_risk_item",
        outcome="success",
        subject_type="risk_item",
        subject_id=created.get("id"),
    )
    return created


@app.get("/controls/risk")
async def controls_list_risk_items(request: Request, project_id: str, limit: int = 100):
    require_role(request, "admin")
    return {"data": list_risk_items(project_id=project_id, limit=max(1, min(limit, 500)))}


@app.post("/controls/risk/{risk_id}/status")
async def controls_update_risk_status(request: Request, risk_id: str, payload: StatusUpdateRequest):
    require_role(request, "admin")
    if payload.status not in RISK_STATUS_ALLOWED:
        raise HTTPException(status_code=400, detail="Invalid risk status")
    current = get_risk_item(risk_id)
    if not current:
        raise HTTPException(status_code=404, detail="Risk item not found")
    current_status = str(current.get("status") or "").strip().lower()
    actor_id = request.state.user.get("sub")
    if not _is_allowed_transition(current_status, payload.status, RISK_STATUS_TRANSITIONS):
        _audit_transition_denied(
            actor_id=actor_id,
            subject_type="risk_item",
            subject_id=risk_id,
            current_status=current_status,
            target_status=payload.status,
            policy_code="risk_transition_not_allowed",
            rejection_reason="Requested risk status transition violates policy graph",
        )
        raise HTTPException(status_code=409, detail=f"Transition not allowed: {current_status} -> {payload.status}")

    risk_score = int(current.get("probability") or 0) * int(current.get("impact") or 0)
    if payload.status == "closed" and risk_score >= RISK_SCORE_MITIGATION_THRESHOLD and not (current.get("mitigation_plan") or "").strip():
        _audit_transition_denied(
            actor_id=actor_id,
            subject_type="risk_item",
            subject_id=risk_id,
            current_status=current_status,
            target_status=payload.status,
            policy_code="risk_close_requires_mitigation",
            rejection_reason="High-risk items require mitigation_plan before closure",
        )
        raise HTTPException(status_code=400, detail="high-risk closure requires mitigation_plan")
    if payload.status == "closed" and risk_score >= RISK_SCORE_OWNER_THRESHOLD and not (current.get("owner_id") or "").strip():
        _audit_transition_denied(
            actor_id=actor_id,
            subject_type="risk_item",
            subject_id=risk_id,
            current_status=current_status,
            target_status=payload.status,
            policy_code="risk_close_requires_owner",
            rejection_reason="Highest-risk items require owner_id before closure",
        )
        raise HTTPException(status_code=400, detail="high-risk closure requires owner_id")

    updated = update_risk_item_status(risk_id=risk_id, status=payload.status)
    if not updated:
        raise HTTPException(status_code=500, detail="Failed to update risk status")
    audit_event(
        "controls_risk_status_updated",
        {
            "risk_id": risk_id,
            "from": current_status,
            "to": payload.status,
            "reason_code": payload.reason_code,
            "risk_score": risk_score,
        },
        actor_id=actor_id,
        event_class="project_controls",
        action="update_risk_status",
        outcome="success",
        reason_code=payload.reason_code or payload.status,
        subject_type="risk_item",
        subject_id=risk_id,
    )
    return updated


@app.post("/controls/change")
async def controls_create_change_request(request: Request, payload: ChangeRequestCreate):
    require_role(request, "admin")
    if payload.impact_cost is not None and payload.impact_cost < 0:
        raise HTTPException(status_code=400, detail="impact_cost must be non-negative")
    if payload.impact_schedule_days is not None and payload.impact_schedule_days < 0:
        raise HTTPException(status_code=400, detail="impact_schedule_days must be non-negative")
    created = create_change_request(
        project_id=payload.project_id,
        title=payload.title,
        description=payload.description,
        requested_by=request.state.user.get("sub"),
        reason_code=payload.reason_code,
        impact_scope=payload.impact_scope,
        impact_cost=payload.impact_cost,
        impact_schedule_days=payload.impact_schedule_days,
    )
    if not created:
        raise HTTPException(status_code=500, detail="Failed to create change request")
    audit_event(
        "controls_change_request_created",
        {"project_id": payload.project_id, "change_request_id": created.get("id"), "reason_code": payload.reason_code},
        actor_id=request.state.user.get("sub"),
        event_class="project_controls",
        action="create_change_request",
        outcome="success",
        subject_type="change_request",
        subject_id=created.get("id"),
    )
    return created


@app.get("/controls/change")
async def controls_list_change_requests(request: Request, project_id: str, limit: int = 100):
    require_role(request, "admin")
    return {"data": list_change_requests(project_id=project_id, limit=max(1, min(limit, 500)))}


@app.get("/controls/rollup")
async def controls_rollup(request: Request, project_id: str | None = None):
    require_role(request, "admin")
    data = get_controls_rollup(project_id=project_id)
    return {"data": data}


@app.get("/controls/audit/export")
async def controls_audit_export(
    request: Request,
    format: str = "json",
    start_at: str | None = None,
    end_at: str | None = None,
    event_class: str | None = "project_controls",
    subject_type: str | None = None,
    event_type: str | None = None,
    limit: int = 500,
):
    require_role(request, "admin")
    fmt = (format or "json").strip().lower()
    if fmt not in {"json", "csv"}:
        raise HTTPException(status_code=400, detail="format must be json or csv")
    safe_limit = max(1, min(limit, 5000))
    rows = list_audit_logs_filtered(
        limit=safe_limit,
        start_at=start_at,
        end_at=end_at,
        event_class=event_class,
        subject_type=subject_type,
        event_type=event_type,
    )

    actor_id = request.state.user.get("sub")
    exported_at = dt.datetime.utcnow().replace(microsecond=0).isoformat() + "Z"
    filter_payload = {
        "start_at": start_at,
        "end_at": end_at,
        "event_class": event_class,
        "subject_type": subject_type,
        "event_type": event_type,
        "limit": safe_limit,
        "format": fmt,
    }
    filter_hash = hashlib.sha256(json.dumps(filter_payload, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
    export_details = {
        "exported_by": actor_id,
        "exported_at": exported_at,
        "filter_hash": filter_hash,
        "filters": filter_payload,
        "row_count": len(rows),
    }
    export_attestation = "I attest this controls audit export is authorized and complete."
    export_signature_hash = _compute_signature_hash_ref(
        event_type="controls_audit_exported",
        actor_id=actor_id,
        subject_type="audit_export",
        subject_id=filter_hash,
        approval_reason="compliance_export",
        attestation_text=export_attestation,
        details=export_details,
    )
    audit_event(
        "controls_audit_exported",
        export_details,
        actor_id=actor_id,
        event_class="project_controls",
        action="export_controls_audit",
        outcome="success",
        reason_code="compliance_export",
        subject_type="audit_export",
        subject_id=filter_hash,
        approval_reason="compliance_export",
        attestation_text=export_attestation,
        signature_hash_ref=export_signature_hash,
    )

    if fmt == "json":
        return {
            "data": rows,
            "filters": {
                "start_at": start_at,
                "end_at": end_at,
                "event_class": event_class,
                "subject_type": subject_type,
                "event_type": event_type,
                "limit": safe_limit,
            },
        }

    output = StringIO()
    writer = csv.writer(output)
    writer.writerow([
        "created_at",
        "event_type",
        "event_class",
        "action",
        "outcome",
        "reason_code",
        "actor_id",
        "subject_type",
        "subject_id",
        "trace_id",
        "policy_code",
        "rejection_reason",
    ])
    for row in rows:
        details = row.get("details") or {}
        writer.writerow([
            row.get("created_at"),
            row.get("event_type"),
            row.get("event_class"),
            row.get("action"),
            row.get("outcome"),
            row.get("reason_code"),
            row.get("actor_id"),
            row.get("subject_type"),
            row.get("subject_id"),
            row.get("trace_id"),
            details.get("policy_code"),
            details.get("rejection_reason"),
        ])
    return Response(content=output.getvalue(), media_type="text/csv")


@app.post("/controls/change/{change_id}/decision")
async def controls_decide_change_request(request: Request, change_id: str, payload: ChangeDecisionRequest):
    require_role(request, "admin")
    if payload.status not in CHANGE_STATUS_ALLOWED:
        raise HTTPException(status_code=400, detail="Invalid status")

    current = get_change_request(change_id)
    if not current:
        raise HTTPException(status_code=404, detail="Change request not found")

    current_status = str(current.get("status") or "").strip().lower()
    if not _is_allowed_change_transition(current_status, payload.status):
        raise HTTPException(
            status_code=409,
            detail=f"Transition not allowed: {current_status} -> {payload.status}",
        )

    if _is_high_impact_change(current) and payload.status in {"approved", "implemented"}:
        if not payload.approval_reason or payload.approval_reason not in HIGH_IMPACT_APPROVAL_REASONS:
            raise HTTPException(
                status_code=400,
                detail="High-impact changes require a valid approval_reason code",
            )

    actor_id = request.state.user.get("sub")
    attestation_text = payload.attestation_text or "I attest this project change decision is authorized and reviewed."
    signature_hash_ref = _compute_signature_hash_ref(
        event_type="controls_change_request_decision",
        actor_id=actor_id,
        subject_type="change_request",
        subject_id=change_id,
        approval_reason=payload.approval_reason,
        attestation_text=attestation_text,
        details={"status": payload.status, "approval_note": payload.approval_note},
    )

    updated = decide_change_request(
        change_id=change_id,
        status=payload.status,
        approved_by=actor_id,
        approval_note=payload.approval_note,
        approval_reason=payload.approval_reason,
        attestation_text=attestation_text,
        signature_hash_ref=signature_hash_ref,
    )
    if not updated:
        raise HTTPException(status_code=500, detail="Failed to update change request")

    audit_event(
        "controls_change_request_decision",
        {
            "change_request_id": change_id,
            "status": payload.status,
            "approval_note": payload.approval_note,
        },
        actor_id=actor_id,
        event_class="project_controls",
        action="decide_change_request",
        outcome="success",
        reason_code=payload.status,
        subject_type="change_request",
        subject_id=change_id,
        approval_reason=payload.approval_reason,
        attestation_text=attestation_text,
        signature_hash_ref=signature_hash_ref,
    )
    return updated


@app.get("/audit/logs")
async def audit_logs_endpoint(request: Request, limit: int = 50):
    """Expose recent audit logs for workflow/intelligence views."""
    require_role(request, "admin")
    logs = get_audit_logs(limit=limit)
    return {"data": logs}


# ---- Dev Token Issuance (for local/testing only) ----------------------------

@app.post("/auth/dev_token")
async def auth_dev_token(request: Request, roles: list[str] = ["admin"]):
    if not DEV_TOKEN_ENABLED:
        raise HTTPException(status_code=403, detail="Dev token issuance disabled")
    # This issues a JWT for local testing of admin endpoints
    now = dt.datetime.now(dt.timezone.utc)
    exp = now + dt.timedelta(minutes=30)
    payload = {
        "sub": "dev-user",
        "roles": roles,
        "iat": int(now.timestamp()),
        "exp": int(exp.timestamp()),
    }
    # Optional audience
    try:
        from src.constants import JWT_AUDIENCE
        if JWT_AUDIENCE:
            payload["aud"] = JWT_AUDIENCE
    except Exception:
        pass
    token = jwt.encode(payload, JWT_SECRET, algorithm="HS256")
    return {"token": token, "roles": roles}


# ---- Auth (Password Flow + Refresh Rotation) -------------------------------

@app.post("/token", response_model=TokenResponse)
async def token(request: Request, form_data: OAuth2PasswordRequestForm = Depends()):
    username = normalize_email(form_data.username)
    rate_limit(request, key=f"auth:{username}")
    user = get_user_by_email(username)
    if not user:
        logging.warning("Auth login failed: reason=invalid_user email=%s", username)
        audit_event("auth_login_failed", {"email": username, "reason": "invalid_user"})
        raise HTTPException(status_code=401, detail="Invalid credentials")

    if not user.get("is_active"):
        logging.warning("Auth login failed: reason=inactive_user email=%s user_id=%s", username, user.get("id"))
        audit_event("auth_login_failed", {"email": username, "reason": "invalid_user"})
        raise HTTPException(status_code=401, detail="Invalid credentials")

    if not verify_password(form_data.password, user.get("hashed_password", "")):
        logging.warning("Auth login failed: reason=bad_password email=%s user_id=%s", username, user.get("id"))
        audit_event("auth_login_failed", {"email": username, "reason": "bad_password"})
        raise HTTPException(status_code=401, detail="Invalid credentials")

    roles = normalize_roles(user.get("roles") or [])
    access_token, access_exp = create_access_token(user_id=user["id"], roles=roles)
    refresh_raw, refresh_hash, refresh_exp = create_refresh_token()
    refresh_exp_iso = refresh_exp.replace(microsecond=0).isoformat()

    token_id = insert_refresh_token(
        user_id=user["id"],
        token_hash=refresh_hash,
        expires_at=refresh_exp_iso,
        user_agent=request.headers.get("User-Agent"),
        ip_address=request.client.host if request.client else None,
    )
    if not token_id:
        raise HTTPException(status_code=500, detail="Failed to create refresh token")

    audit_event("auth_login", {"user_id": user["id"], "email": user["email"]})
    expires_in = int((access_exp - dt.datetime.now(dt.timezone.utc)).total_seconds())
    return TokenResponse(
        access_token=access_token,
        refresh_token=refresh_raw,
        expires_in=max(expires_in, 0),
        roles=roles,
    )


@app.post("/refresh", response_model=TokenResponse)
async def refresh_token(request: Request, payload: RefreshRequest):
    source_ip = request.client.host if request.client else "unknown"
    rate_limit(request, key=f"auth:refresh:{source_ip}")
    if not payload.refresh_token:
        raise HTTPException(status_code=400, detail="Missing refresh token")

    token_hash = hash_refresh_token(payload.refresh_token)
    try:
        record = get_refresh_token_record(token_hash)
    except AuthStoreUnavailableError:
        raise HTTPException(status_code=503, detail="Authentication service temporarily unavailable")

    if not record:
        try:
            audit_event("auth_refresh_failed", {"reason": "not_found"})
        except Exception:
            pass
        raise HTTPException(status_code=401, detail="Invalid refresh token")

    if record.get("revoked_at"):
        try:
            audit_event("auth_refresh_failed", {"reason": "revoked"})
        except Exception:
            pass
        raise HTTPException(status_code=401, detail="Refresh token revoked")

    exp = parse_iso8601(record.get("expires_at"))
    now = dt.datetime.now(dt.timezone.utc)
    if exp and exp.tzinfo is None:
        exp = exp.replace(tzinfo=dt.timezone.utc)
    if exp and exp < now:
        revoke_refresh_token(record["id"])
        try:
            audit_event("auth_refresh_failed", {"reason": "expired"})
        except Exception:
            pass
        raise HTTPException(status_code=401, detail="Refresh token expired")

    user = get_user_by_id(record["user_id"])
    if not user or not user.get("is_active"):
        revoke_refresh_token(record["id"])
        try:
            audit_event("auth_refresh_failed", {"reason": "invalid_user"})
        except Exception:
            pass
        raise HTTPException(status_code=401, detail="Invalid user")

    roles = user.get("roles") or []
    access_token, access_exp = create_access_token(user_id=user["id"], roles=roles)
    refresh_raw, refresh_hash, refresh_exp = create_refresh_token()
    refresh_exp_iso = refresh_exp.replace(microsecond=0).isoformat()
    new_token_id = insert_refresh_token(
        user_id=user["id"],
        token_hash=refresh_hash,
        expires_at=refresh_exp_iso,
        user_agent=request.headers.get("User-Agent"),
        ip_address=request.client.host if request.client else None,
        replaced_by=None,
    )
    if not new_token_id:
        raise HTTPException(status_code=500, detail="Failed to rotate refresh token")

    revoke_refresh_token(record["id"], replaced_by=new_token_id)
    audit_event("auth_refresh", {"user_id": user["id"], "refresh_id": record["id"]})
    expires_in = int((access_exp - dt.datetime.now(dt.timezone.utc)).total_seconds())
    return TokenResponse(
        access_token=access_token,
        refresh_token=refresh_raw,
        expires_in=max(expires_in, 0),
        roles=roles,
    )


@app.post("/logout")
async def logout(request: Request, payload: LogoutRequest):
    source_ip = request.client.host if request.client else "unknown"
    rate_limit(request, key=f"auth:logout:{source_ip}")
    if payload.refresh_token:
        token_hash = hash_refresh_token(payload.refresh_token)
        try:
            record = get_refresh_token_record(token_hash)
        except AuthStoreUnavailableError:
            return {"status": "ok"}
        if record and not record.get("revoked_at"):
            revoke_refresh_token(record["id"])
            audit_event("auth_logout", {"user_id": record.get("user_id")})
    return {"status": "ok"}


@app.post("/submit_order")
async def submit_order(order: SubmitOrder):
    """Validate, persist, and accept an order."""
    source = str(order.source or "direct").strip().lower()
    normalized_source = source.replace("-", "_")

    lead_id = order.lead_id
    if lead_id is None and normalized_source in {"synbot", "chat", "widget", "walk_in", "in_person"}:
        lead_payload = Lead(
            name=order.customer_name,
            email=order.customer_email,
            phone=order.customer_phone or "N/A",
            message=order.notes or "Order initiated from assisted workflow",
            service="orders",
        )
        lead_id = store_lead(lead_payload.model_dump(exclude_none=True))

    payload = order.model_copy(update={"source": normalized_source, "lead_id": lead_id})
    accepted = _create_order_record(payload)
    audit_event(
        "order_submitted",
        {
            "order_id": accepted.get("order_id"),
            "tracking_id": accepted.get("tracking_id"),
            "lead_id": accepted.get("lead_id"),
            "source": accepted.get("source"),
            "item_count": len(accepted.get("items") or []),
            "customer_email": accepted.get("customer_email"),
        },
        event_class="workflow",
        action="submit_order",
        outcome="success",
        subject_type="order",
        subject_id=accepted.get("order_id"),
    )
    return accepted


@app.get("/track/{tracking_id}", response_model=TrackingResponse)
async def track_order(tracking_id: str):
    """Return persisted tracking information for an order."""
    row = get_tracking(tracking_id)
    if not row:
        raise HTTPException(status_code=404, detail="Tracking record not found")
    return {
        "id": row.get("id") or tracking_id,
        "status": row.get("status") or "received",
        "last_update": row.get("last_update"),
        "eta": row.get("eta"),
    }


# ---- User Management (Admin Only) -------------------------------------------

class UserCreate(BaseModel):
    email: str
    password: str
    roles: list[str] = ["viewer"]
    approval_reason: str | None = None
    attestation_text: str | None = None


class UserPasswordUpdate(BaseModel):
    password: str
    approval_reason: str | None = None
    attestation_text: str | None = None


class UserStatusUpdate(BaseModel):
    is_active: bool
    approval_reason: str | None = None
    attestation_text: str | None = None


@app.get("/users")
async def list_all_users(request: Request, limit: int = 50):
    """List users for admin management."""
    require_role(request, "admin")
    return {"users": list_users(limit=limit)}


@app.get("/users/directory")
async def get_user_directory(request: Request):
    """
    Return a lightweight user list for task/project assignment dropdowns.
    Accessible by admin, management, manager, hr, and finance roles.
    Returns minimal fields: id, email, display_name, roles.
    """
    payload = verify_jwt(request)
    allowed = {"admin", "management", "manager", "hr", "finance"}
    roles = set(payload.get("roles") or [])
    if not roles.intersection(allowed):
        raise HTTPException(status_code=403, detail="Insufficient privileges to view user directory")
    all_users = list_users(limit=500)
    directory = []
    for u in all_users:
        # Only expose non-sensitive fields
        directory.append({
            "id": u.get("id") or u.get("user_id"),
            "email": u.get("email", ""),
            "display_name": u.get("display_name") or u.get("full_name") or u.get("email", ""),
            "roles": u.get("roles") or [],
        })
    return directory


@app.post("/users")
async def create_new_user(request: Request, payload: UserCreate):
    """Create a new staff user."""
    require_role(request, "admin")
    email = normalize_email(payload.email)
    validate_password_strength(payload.password)
    roles = normalize_roles(payload.roles)

    existing = get_user_by_email(email)
    if existing:
        raise HTTPException(status_code=409, detail="User already exists")

    hashed = hash_password(payload.password)
    user_id = create_user(email, hashed, roles)
    if not user_id:
        raise HTTPException(status_code=500, detail="Failed to create user")

    audit_event(
        "user_created",
        {
            "creator": request.state.user.get("sub"),
            "target_email": email,
            "roles": roles,
            "approval_reason": payload.approval_reason,
        },
        actor_id=request.state.user.get("sub"),
        action="admin_create_user",
        outcome="success",
        reason_code="provision",
        subject_type="user",
        subject_id=user_id,
        approval_reason=payload.approval_reason,
        attestation_text=payload.attestation_text or "I attest this account provisioning action is authorized.",
    )
    return {"id": user_id, "email": email, "roles": roles}


@app.put("/users/{user_id}/password")
async def reset_user_password(request: Request, user_id: str, payload: UserPasswordUpdate):
    """Reset a user's password."""
    require_role(request, "admin")
    validate_password_strength(payload.password)
    hashed = hash_password(payload.password)
    ok = update_user_password(user_id, hashed)
    if not ok:
        raise HTTPException(status_code=500, detail="Failed to update password")
    
    audit_event(
        "user_password_reset",
        {
            "admin": request.state.user.get("sub"),
            "target_user_id": user_id,
            "approval_reason": payload.approval_reason,
        },
        actor_id=request.state.user.get("sub"),
        action="admin_reset_user_password",
        outcome="success",
        reason_code="credential_recovery",
        subject_type="user",
        subject_id=user_id,
        approval_reason=payload.approval_reason,
        attestation_text=payload.attestation_text or "I attest this credential reset is authorized and policy-compliant.",
    )
    return {"status": "ok"}


@app.patch("/users/{user_id}/status")
async def update_user_status(request: Request, user_id: str, payload: UserStatusUpdate):
    """Activate or deactivate a user."""
    require_role(request, "admin")
    # prevent self-lockout
    current_sub = request.state.user.get("sub")
    if current_sub == user_id and not payload.is_active:
        raise HTTPException(status_code=400, detail="Cannot deactivate your own account")

    ok = toggle_user_active(user_id, payload.is_active)
    if not ok:
        raise HTTPException(status_code=500, detail="Failed to update status")

    audit_event(
        "user_status_changed",
        {
            "admin": current_sub,
            "target_user_id": user_id,
            "active": payload.is_active,
            "approval_reason": payload.approval_reason,
        },
        actor_id=current_sub,
        action="admin_toggle_user_status",
        outcome="success",
        reason_code="activate" if payload.is_active else "deactivate",
        subject_type="user",
        subject_id=user_id,
        approval_reason=payload.approval_reason,
        attestation_text=payload.attestation_text or "I attest this account status change is authorized.",
    )
    return {"status": "ok"}


# ---- Sage Adapter Import ----------------------------------------------------

@app.post("/sage/import")
async def sage_import(
    request: Request,
    background_tasks: BackgroundTasks,
    customers: UploadFile | None = File(default=None),
    ar: UploadFile | None = File(default=None),
    ap: UploadFile | None = File(default=None),
    gl: UploadFile | None = File(default=None),
    inventory: UploadFile | None = File(default=None),
    staff: UploadFile | None = File(default=None),
    async_mode: bool = False,
    admin_ok: bool = Depends(require_admin_token),
):
    """Accept CSV files for Sage snapshots, validate headers, normalize, and return counts.

    This MVP endpoint validates and echoes counts only; persistence to Supabase
    snapshot tables and audit logging will be added next.
    """
    import uuid, datetime

    batch_id = str(uuid.uuid4())
    imported_at = datetime.datetime.utcnow().replace(microsecond=0).isoformat() + "Z"
    meta = ImportMeta(batch_id=batch_id, imported_at=imported_at)
    idempotency_key = _extract_idempotency_key(request)

    if idempotency_key:
        existing = find_import_job_by_idempotency("sage", idempotency_key)
        if existing:
            return _replay_or_busy_response(existing, imported_at)

    datasets: dict[str, dict] = {}
    for name, file in (
        ("customers", customers),
        ("ar", ar),
        ("ap", ap),
        ("gl", gl),
        ("inventory", inventory),
        ("staff", staff),
    ):
        if file:
            datasets[name] = {
                "filename": file.filename,
                "content_type": file.content_type,
                "content": await file.read(),
            }

    job_id = create_import_job(
        domain="sage",
        batch_id=batch_id,
        imported_at=imported_at,
        metadata={
            "source_system": "sage50",
            "idempotency_key": idempotency_key,
            "mode": "async" if async_mode else "sync",
        },
        idempotency_key=idempotency_key,
        status="queued" if async_mode else "running",
    )

    if async_mode:
        background_tasks.add_task(
            _process_sage_import_job,
            job_id=job_id,
            batch_id=batch_id,
            imported_at=imported_at,
            meta=meta,
            datasets=datasets,
            idempotency_key=idempotency_key,
            raise_on_error=False,
        )
        return JSONResponse(
            status_code=202,
            content={
                "status": "queued",
                "job_id": job_id,
                "batch_id": batch_id,
                "imported_at": imported_at,
            },
        )

    result = await _process_sage_import_job(
        job_id=job_id,
        batch_id=batch_id,
        imported_at=imported_at,
        meta=meta,
        datasets=datasets,
        idempotency_key=idempotency_key,
        raise_on_error=True,
    )
    if result is None:
        raise HTTPException(status_code=500, detail="Import failed")
    return result


@app.post("/import")
async def import_inventory(
    request: Request,
    background_tasks: BackgroundTasks,
    inventory: UploadFile | None = File(default=None),
    async_mode: bool = True,
    admin_ok: bool = Depends(require_admin_token),
):
    """Lightweight inventory import endpoint that triggers agents/workflows.

    - Accepts a single `inventory` CSV file
    - Requires admin token
    - Runs import and triggers agents; by default runs in background
    """
    if inventory is None:
        raise HTTPException(status_code=400, detail="inventory file is required")

    import tempfile, uuid
    from src.imports.sage_import import import_inventory_and_trigger
    from src.workflow.engine import WorkflowEngine
    from src.workflow.replenishment_workflow import register_replenishment_workflow

    # write uploaded file to a temp file for the import helper
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".csv")
    content = await inventory.read()
    tmp.write(content)
    tmp.flush()
    tmp.close()

    # prepare workflow engine (register default replenishment workflow)
    engine = WorkflowEngine()
    register_replenishment_workflow(engine)

    # harden: idempotency + audit + persistent job record
    idempotency_key = _extract_idempotency_key(request)
    if idempotency_key:
        existing = find_import_job_by_idempotency("sage", idempotency_key)
        if existing:
            try:
                # cleanup uploaded temp file when replaying
                import os
                os.remove(tmp.name)
            except Exception:
                pass
            return _replay_or_busy_response(existing, imported_default="")

    batch_id = str(uuid.uuid4())
    from datetime import datetime

    imported_at = datetime.utcnow().replace(microsecond=0).isoformat() + "Z"
    actor = getattr(request.state, "user", None) or {}
    actor_id = actor.get("sub") or actor.get("id")

    job_id = create_import_job(
        domain="sage",
        batch_id=batch_id,
        imported_at=imported_at,
        metadata={"filename": inventory.filename or "upload.csv", "user": actor_id},
        idempotency_key=idempotency_key,
        status="queued" if async_mode else "running",
    )

    audit_event(
        "sage_import_started",
        {"job_id": job_id, "batch_id": batch_id, "user": actor_id, "filename": inventory.filename},
        actor_id=actor_id,
        event_class="import",
        action="import_start",
        outcome="started",
    )

    def _bg_task(path: str, job_id: str, batch_id: str, actor_id: str | None):
        try:
            res = import_inventory_and_trigger(path, agent_names=["inventory_intelligence"], workflow_engine=engine)
            # attempt to load rows count for audit
            try:
                from src.imports.sage_import import load_inventory_csv

                rows = load_inventory_csv(path)
                counts = {"rows": len(rows)}
            except Exception:
                counts = {}
            update_import_job(job_id, status="succeeded", counts=counts, metadata={"result_summary": "ok"})
            audit_event(
                "sage_import_succeeded",
                {"job_id": job_id, "batch_id": batch_id, "counts": counts},
                actor_id=actor_id,
                event_class="import",
                action="import_complete",
                outcome="success",
            )
        except Exception as e:
            update_import_job(job_id, status="failed", error_message=str(e))
            audit_event(
                "sage_import_failed",
                {"job_id": job_id, "batch_id": batch_id, "error": str(e)},
                actor_id=actor_id,
                event_class="import",
                action="import_fail",
                outcome="failed",
            )
            try:
                logging.error(f"import job {job_id} failed: {e}")
            except Exception:
                pass
        finally:
            try:
                import os
                os.remove(path)
            except Exception:
                pass

    if async_mode:
        background_tasks.add_task(_bg_task, tmp.name, job_id, batch_id, actor_id)
        return JSONResponse(status_code=202, content={"status": "queued", "job_id": job_id, "batch_id": batch_id})

    # synchronous run
    try:
        try:
            res = import_inventory_and_trigger(tmp.name, agent_names=["inventory_intelligence"], workflow_engine=engine)
            try:
                from src.imports.sage_import import load_inventory_csv
                rows = load_inventory_csv(tmp.name)
                counts = {"rows": len(rows)}
            except Exception:
                counts = {}
            update_import_job(job_id, status="succeeded", counts=counts, metadata={"result_summary": "ok"})
            audit_event(
                "sage_import_succeeded",
                {"job_id": job_id, "batch_id": batch_id, "counts": counts},
                actor_id=actor_id,
                event_class="import",
                action="import_complete",
                outcome="success",
            )
            # Bust in-process TTL caches so the dashboard reflects fresh inventory immediately
            from src.cache import invalidate_cache_tags
            invalidate_cache_tags("inventory", "inventory_dashboard", "executive")
            return JSONResponse(status_code=200, content={"status": "ok", "job_id": job_id, "batch_id": batch_id, "result": res})
        except Exception as e:
            update_import_job(job_id, status="failed", error_message=str(e))
            audit_event(
                "sage_import_failed",
                {"job_id": job_id, "batch_id": batch_id, "error": str(e)},
                actor_id=actor_id,
                event_class="import",
                action="import_fail",
                outcome="failed",
            )
            raise
    finally:
        try:
            import os

            os.remove(tmp.name)
        except Exception:
            pass


@app.get("/sage/history")
async def sage_import_history(
    request: Request,
    limit: int = 50,
):
    """Retrieve history of Sage imports from import jobs with audit fallback."""
    require_roles(request, ["admin", "finance", "management", "ops"])
    limit = max(1, min(limit, 200))

    jobs = list_import_jobs(limit=limit, domain="sage")
    history = []

    for job in jobs:
        counts = job.get("counts") or {}
        if not isinstance(counts, dict):
            counts = {}
        count_parts = [f"{str(k).upper()}: {v}" for k, v in counts.items() if v and str(v) != "0"]
        count_str = ", ".join(count_parts) if count_parts else "No records"

        status = str(job.get("status") or "unknown").lower()
        history.append(
            {
                "id": job.get("id"),
                "date": job.get("created_at") or job.get("imported_at"),
                "user": (job.get("metadata") or {}).get("actor_id", "System") if isinstance(job.get("metadata"), dict) else "System",
                "action": f"Import {str(job.get('batch_id') or 'unknown')[:8]}...",
                "status": "success" if status in {"succeeded", "partial_success"} else "error",
                "details": count_str,
            }
        )

    if history:
        return {"data": history}

    logs = get_audit_logs(limit=limit)
    for log in logs:
        evt_type = log.get("event_type")
        if not evt_type or "sage_import" not in evt_type:
            continue
        details = log.get("details") or {}
        counts = details.get("counts", {}) if isinstance(details, dict) else {}
        count_parts = [f"{k.upper()}: {v}" for k, v in counts.items() if v and int(v) > 0]
        count_str = ", ".join(count_parts) if count_parts else "No records"
        history.append(
            {
                "id": log.get("id"),
                "date": log.get("created_at"),
                "user": details.get("user", "System") if isinstance(details, dict) else "System",
                "action": f"Import {str((details or {}).get('batch_id', 'unknown'))[:8]}...",
                "status": "success" if "validated" in evt_type or "success" in evt_type else "error",
                "details": count_str,
            }
        )

    return {"data": history}


@app.get("/imports/jobs")
async def import_jobs_history(
    request: Request,
    limit: int = 50,
    domain: str | None = None,
    status: str | None = None,
):
    """Admin view of import pipeline job runs across domains."""
    require_role(request, "admin")
    limit = max(1, min(limit, 200))
    return {"data": list_import_jobs(limit=limit, domain=domain, status=status)}


@app.get("/imports/jobs/{job_id}")
async def import_job_detail(request: Request, job_id: str):
    """Admin view of one import pipeline job record."""
    require_role(request, "admin")
    job = get_import_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Import job not found")
    metadata = job.get("metadata") or {}
    control_rollup = metadata.get("control_rollup")
    if not isinstance(control_rollup, dict):
        controls_policy = _resolve_controls_policy_config(str(job.get("domain") or ""))
        control_rollup = _compute_import_control_rollup(
            job.get("lineage") or {},
            rejected_rows=int((job.get("counts") or {}).get("rejected_rows") or 0),
            policy_config=controls_policy,
        )
    job["control_rollup"] = control_rollup
    return job


@app.post("/imports/policy/preview")
async def import_policy_preview(request: Request, payload: ImportPolicyPreviewRequest):
    """Admin what-if scoring endpoint for policy calibration before activation."""
    require_role(request, "admin")
    domain = (payload.domain or "").strip().lower()
    if domain not in {"sage", "hr", "ops", "crm"}:
        raise HTTPException(status_code=400, detail="domain must be one of sage|hr|ops|crm")

    baseline_policy = _resolve_controls_policy_config(domain)
    baseline_rollup = _compute_import_control_rollup(
        payload.lineage,
        rejected_rows=max(0, int(payload.rejected_rows)),
        policy_config=baseline_policy,
    )

    override = payload.policy_override or {}
    override_policy = {
        **baseline_policy,
        **override,
    }
    if isinstance(baseline_policy.get("severity_weights"), dict):
        override_policy["severity_weights"] = {
            **(baseline_policy.get("severity_weights") or {}),
            **((override.get("severity_weights") or {}) if isinstance(override.get("severity_weights"), dict) else {}),
        }

    preview_rollup = _compute_import_control_rollup(
        payload.lineage,
        rejected_rows=max(0, int(payload.rejected_rows)),
        policy_config=override_policy,
    )

    return {
        "domain": domain,
        "baseline": baseline_rollup,
        "preview": preview_rollup,
        "delta": {
            "control_score": round(float(preview_rollup.get("control_score", 0)) - float(baseline_rollup.get("control_score", 0)), 2),
            "warning_density": round(float(preview_rollup.get("warning_density", 0)) - float(baseline_rollup.get("warning_density", 0)), 4),
            "severity_index": round(float(preview_rollup.get("severity_index", 0)) - float(baseline_rollup.get("severity_index", 0)), 4),
        },
        "effective_policy": override_policy,
    }


@app.post("/imports/policy/activate")
async def import_policy_activate(request: Request, payload: ImportPolicyActivateRequest):
    """Admin endpoint to promote a controls policy version with signed attestation."""
    require_role(request, "admin")
    domain = (payload.domain or "").strip().lower()
    if domain not in {"sage", "hr", "ops", "crm"}:
        raise HTTPException(status_code=400, detail="domain must be one of sage|hr|ops|crm")

    controls_config = _validate_controls_config(payload.controls_config)
    actor_id = request.state.user.get("sub")
    attestation_text = payload.attestation_text or "I attest this policy activation is authorized, reviewed, and compliant."
    policy_version = payload.policy_version or dt.datetime.utcnow().strftime("%Y.%m.%d.%H%M%S")

    details = {
        "domain": domain,
        "policy_version": policy_version,
        "schema_version": payload.schema_version,
        "controls_config": controls_config,
        "notes": payload.notes,
    }
    signature_hash_ref = _compute_signature_hash_ref(
        event_type="import_policy_activated",
        actor_id=actor_id,
        subject_type="data_policy",
        subject_id=f"{domain}:{policy_version}",
        approval_reason=payload.approval_reason,
        attestation_text=attestation_text,
        details=details,
    )

    activated = activate_import_controls_policy(
        domain=domain,
        policy_version=policy_version,
        schema_version=payload.schema_version,
        controls_config=controls_config,
        approved_by=actor_id,
        approval_reason=payload.approval_reason,
        attestation_text=attestation_text,
        signature_hash_ref=signature_hash_ref,
        notes=payload.notes,
    )
    if not activated:
        raise HTTPException(status_code=500, detail="Failed to activate policy")

    audit_event(
        "import_policy_activated",
        details,
        actor_id=actor_id,
        event_class="data_ingestion",
        action="activate_controls_policy",
        outcome="success",
        reason_code=payload.approval_reason,
        subject_type="data_policy",
        subject_id=f"{domain}:{policy_version}",
        approval_reason=payload.approval_reason,
        attestation_text=attestation_text,
        signature_hash_ref=signature_hash_ref,
    )

    return {
        "status": "activated",
        "domain": domain,
        "policy_version": policy_version,
        "schema_version": payload.schema_version,
        "signature_hash_ref": signature_hash_ref,
        "policy": activated,
    }


@app.get("/imports/policy/history")
async def import_policy_history(request: Request, domain: str, limit: int = 20):
    """Admin endpoint to review policy version history for a domain."""
    require_role(request, "admin")
    normalized_domain = (domain or "").strip().lower()
    if normalized_domain not in {"sage", "hr", "ops", "crm"}:
        raise HTTPException(status_code=400, detail="domain must be one of sage|hr|ops|crm")
    safe_limit = max(1, min(limit, 200))
    return {"data": list_import_policy_versions(normalized_domain, limit=safe_limit)}


@app.post("/imports/policy/rollback")
async def import_policy_rollback(request: Request, payload: ImportPolicyRollbackRequest):
    """Admin endpoint to rollback active controls policy to a previous version with signed approval."""
    require_role(request, "admin")
    domain = (payload.domain or "").strip().lower()
    if domain not in {"sage", "hr", "ops", "crm"}:
        raise HTTPException(status_code=400, detail="domain must be one of sage|hr|ops|crm")

    target = get_import_policy_version(domain, payload.target_policy_version)
    if not target:
        raise HTTPException(status_code=404, detail="target policy version not found")

    current = get_import_policy(domain)
    actor_id = request.state.user.get("sub")
    rollback_policy_version = payload.rollback_policy_version or dt.datetime.utcnow().strftime("%Y.%m.%d.%H%M%S")
    attestation_text = payload.attestation_text or "I attest this policy rollback is authorized, reviewed, and compliant."

    details = {
        "domain": domain,
        "from_policy_version": current.get("policy_version") if isinstance(current, dict) else None,
        "to_policy_version": payload.target_policy_version,
        "rollback_policy_version": rollback_policy_version,
        "schema_version": target.get("schema_version"),
        "controls_config": target.get("controls_config") or {},
        "notes": payload.notes,
    }
    signature_hash_ref = _compute_signature_hash_ref(
        event_type="import_policy_rollback",
        actor_id=actor_id,
        subject_type="data_policy",
        subject_id=f"{domain}:{rollback_policy_version}",
        approval_reason=payload.approval_reason,
        attestation_text=attestation_text,
        details=details,
    )

    activated = activate_import_controls_policy(
        domain=domain,
        policy_version=rollback_policy_version,
        schema_version=str(target.get("schema_version") or "2026.1"),
        controls_config=target.get("controls_config") or {},
        approved_by=actor_id,
        approval_reason=payload.approval_reason,
        attestation_text=attestation_text,
        signature_hash_ref=signature_hash_ref,
        notes=payload.notes or f"Rollback to {payload.target_policy_version}",
    )
    if not activated:
        raise HTTPException(status_code=500, detail="Failed to rollback policy")

    audit_event(
        "import_policy_rollback",
        details,
        actor_id=actor_id,
        event_class="data_ingestion",
        action="rollback_controls_policy",
        outcome="success",
        reason_code=payload.approval_reason,
        subject_type="data_policy",
        subject_id=f"{domain}:{rollback_policy_version}",
        approval_reason=payload.approval_reason,
        attestation_text=attestation_text,
        signature_hash_ref=signature_hash_ref,
    )

    return {
        "status": "rolled_back",
        "domain": domain,
        "from_policy_version": current.get("policy_version") if isinstance(current, dict) else None,
        "to_policy_version": payload.target_policy_version,
        "rollback_policy_version": rollback_policy_version,
        "signature_hash_ref": signature_hash_ref,
        "policy": activated,
    }


@app.get("/ml/features/export")
async def ml_features_export(
    request: Request,
    domain: str = "sage",
    format: str = "json",
    row_limit: int = 50000,
):
    """Admin export of ML baseline feature snapshot from promoted import batches."""
    require_role(request, "admin")
    normalized_domain = (domain or "").strip().lower()
    if normalized_domain not in {"sage", "hr"}:
        raise HTTPException(status_code=400, detail="domain must be one of sage|hr")

    fmt = (format or "json").strip().lower()
    if fmt not in {"json", "csv"}:
        raise HTTPException(status_code=400, detail="format must be json or csv")

    promoted = get_promoted_kpi_batch(normalized_domain)
    batch_id = (promoted or {}).get("batch_id") if isinstance(promoted, dict) else None
    if not batch_id:
        batch_id = get_latest_successful_import_batch(normalized_domain)
    if not batch_id:
        raise HTTPException(status_code=404, detail="No promoted or successful batch found for domain")

    contract = _ml_feature_contract(normalized_domain)
    features = _compute_ml_feature_snapshot(normalized_domain, batch_id, row_limit=max(1, min(row_limit, 200000)))

    actor_id = request.state.user.get("sub")
    exported_at = dt.datetime.utcnow().replace(microsecond=0).isoformat() + "Z"
    details = {
        "domain": normalized_domain,
        "batch_id": batch_id,
        "contract_version": contract.get("contract_version"),
        "feature_count": len(features),
        "format": fmt,
        "row_limit": row_limit,
        "exported_at": exported_at,
    }
    attestation_text = "I attest this ML feature snapshot export is authorized and traceable."
    signature_hash_ref = _compute_signature_hash_ref(
        event_type="ml_feature_snapshot_exported",
        actor_id=actor_id,
        subject_type="ml_feature_snapshot",
        subject_id=f"{normalized_domain}:{batch_id}",
        approval_reason="ml_baseline_export",
        attestation_text=attestation_text,
        details=details,
    )
    audit_event(
        "ml_feature_snapshot_exported",
        details,
        actor_id=actor_id,
        event_class="analytics",
        action="export_ml_feature_snapshot",
        outcome="success",
        reason_code="ml_baseline_export",
        subject_type="ml_feature_snapshot",
        subject_id=f"{normalized_domain}:{batch_id}",
        approval_reason="ml_baseline_export",
        attestation_text=attestation_text,
        signature_hash_ref=signature_hash_ref,
    )

    payload = {
        "domain": normalized_domain,
        "batch_id": batch_id,
        "contract": contract,
        "features": features,
        "exported_at": exported_at,
        "signature_hash_ref": signature_hash_ref,
    }
    if fmt == "json":
        return payload

    output = StringIO()
    writer = csv.writer(output)
    writer.writerow(["domain", "batch_id", "contract_version", "feature_name", "value", "exported_at", "signature_hash_ref"])
    for feature_name, value in features.items():
        writer.writerow([
            normalized_domain,
            batch_id,
            contract.get("contract_version"),
            feature_name,
            value,
            exported_at,
            signature_hash_ref,
        ])
    return Response(content=output.getvalue(), media_type="text/csv")


@app.get("/ml/features/drift/summary")
async def ml_features_drift_summary(
    request: Request,
    domain: str = "sage",
    row_limit: int = 50000,
    search_limit: int = 100,
):
    """Admin summary of feature quality and drift deltas vs prior batch baseline."""
    require_role(request, "admin")
    normalized_domain = (domain or "").strip().lower()
    if normalized_domain not in {"sage", "hr"}:
        raise HTTPException(status_code=400, detail="domain must be one of sage|hr")

    promoted = get_promoted_kpi_batch(normalized_domain)
    current_batch_id = (promoted or {}).get("batch_id") if isinstance(promoted, dict) else None
    if not current_batch_id:
        current_batch_id = get_latest_successful_import_batch(normalized_domain)
    if not current_batch_id:
        raise HTTPException(status_code=404, detail="No promoted or successful batch found for domain")

    safe_row_limit = max(1, min(row_limit, 200000))
    contract = _ml_feature_contract(normalized_domain)
    current_features = _compute_ml_feature_snapshot(normalized_domain, current_batch_id, row_limit=safe_row_limit)
    current_quality = _compute_ml_feature_quality_summary(current_features)

    baseline_batch_id = _resolve_prior_ml_baseline_batch(
        normalized_domain,
        current_batch_id,
        search_limit=search_limit,
    )
    baseline_features: dict[str, Any] = {}
    baseline_quality: dict[str, Any] | None = None
    if baseline_batch_id:
        baseline_features = _compute_ml_feature_snapshot(
            normalized_domain,
            baseline_batch_id,
            row_limit=safe_row_limit,
        )
        baseline_quality = _compute_ml_feature_quality_summary(baseline_features)

    drift = _compute_ml_feature_distribution_deltas(current_features, baseline_features)
    drift_policy = _resolve_ml_drift_policy_config(normalized_domain)
    alerts = _compute_ml_drift_alerts(drift, current_quality, drift_policy)

    actor_id = request.state.user.get("sub")
    generated_at = dt.datetime.utcnow().replace(microsecond=0).isoformat() + "Z"
    details = {
        "domain": normalized_domain,
        "current_batch_id": current_batch_id,
        "baseline_batch_id": baseline_batch_id,
        "contract_version": contract.get("contract_version"),
        "comparison_available": drift.get("comparison_available"),
        "comparable_feature_count": drift.get("comparable_feature_count"),
        "mean_absolute_delta": drift.get("mean_absolute_delta"),
        "mean_absolute_pct_delta": drift.get("mean_absolute_pct_delta"),
        "highest_severity": alerts.get("highest_severity"),
        "severity_counts": alerts.get("severity_counts"),
        "row_limit": safe_row_limit,
        "generated_at": generated_at,
    }
    attestation_text = "I attest this ML drift baseline summary export is authorized and traceable."
    signature_hash_ref = _compute_signature_hash_ref(
        event_type="ml_feature_drift_summarized",
        actor_id=actor_id,
        subject_type="ml_feature_drift",
        subject_id=f"{normalized_domain}:{current_batch_id}",
        approval_reason="ml_drift_baseline_summary",
        attestation_text=attestation_text,
        details=details,
    )
    audit_event(
        "ml_feature_drift_summarized",
        details,
        actor_id=actor_id,
        event_class="analytics",
        action="summarize_ml_feature_drift",
        outcome="success",
        reason_code="ml_drift_baseline_summary",
        subject_type="ml_feature_drift",
        subject_id=f"{normalized_domain}:{current_batch_id}",
        approval_reason="ml_drift_baseline_summary",
        attestation_text=attestation_text,
        signature_hash_ref=signature_hash_ref,
    )

    return {
        "domain": normalized_domain,
        "contract": contract,
        "current": {
            "batch_id": current_batch_id,
            "features": current_features,
            "quality": current_quality,
        },
        "baseline": {
            "batch_id": baseline_batch_id,
            "features": baseline_features if baseline_batch_id else None,
            "quality": baseline_quality,
        },
        "drift": drift,
        "alerts": alerts,
        "generated_at": generated_at,
        "signature_hash_ref": signature_hash_ref,
    }


@app.get("/ml/features/drift/history")
async def ml_features_drift_history(
    request: Request,
    domain: str = "sage",
    limit: int | None = None,
):
    """Admin trend view for persisted ML drift summary audits."""
    require_role(request, "admin")
    normalized_domain = (domain or "").strip().lower()
    if normalized_domain not in {"sage", "hr"}:
        raise HTTPException(status_code=400, detail="domain must be one of sage|hr")

    policy = _resolve_ml_drift_policy_config(normalized_domain)
    default_limit = policy.get("history_limit_default") if isinstance(policy, dict) else 20
    safe_limit = max(1, min(int(limit or default_limit or 20), 200))

    rows = list_audit_logs_filtered(
        limit=safe_limit * 3,
        event_type="ml_feature_drift_summarized",
        subject_type="ml_feature_drift",
    )

    trend: list[dict[str, Any]] = []
    for row in rows or []:
        details = row.get("details") if isinstance(row, dict) else {}
        if not isinstance(details, dict):
            continue
        if (details.get("domain") or "").strip().lower() != normalized_domain:
            continue
        trend.append(
            {
                "generated_at": details.get("generated_at") or row.get("created_at"),
                "current_batch_id": details.get("current_batch_id"),
                "baseline_batch_id": details.get("baseline_batch_id"),
                "comparison_available": bool(details.get("comparison_available")),
                "comparable_feature_count": int(details.get("comparable_feature_count") or 0),
                "mean_absolute_delta": float(details.get("mean_absolute_delta") or 0.0),
                "mean_absolute_pct_delta": float(details.get("mean_absolute_pct_delta") or 0.0),
                "highest_severity": details.get("highest_severity") or "none",
                "severity_counts": details.get("severity_counts") or {},
                "signature_hash_ref": row.get("signature_hash_ref"),
            }
        )
        if len(trend) >= safe_limit:
            break

    comparable = [entry for entry in trend if entry.get("comparison_available")]
    severity_tally = {"warning": 0, "error": 0, "critical": 0}
    for entry in trend:
        counts = entry.get("severity_counts") if isinstance(entry.get("severity_counts"), dict) else {}
        for level in severity_tally.keys():
            severity_tally[level] += int(counts.get(level) or 0)

    return {
        "domain": normalized_domain,
        "count": len(trend),
        "trend": trend,
        "summary": {
            "comparison_count": len(comparable),
            "avg_mean_absolute_delta": round(
                sum(float(entry.get("mean_absolute_delta") or 0.0) for entry in comparable) / len(comparable),
                4,
            ) if comparable else 0.0,
            "avg_mean_absolute_pct_delta": round(
                sum(float(entry.get("mean_absolute_pct_delta") or 0.0) for entry in comparable) / len(comparable),
                6,
            ) if comparable else 0.0,
            "severity_counts": severity_tally,
        },
    }


@app.post("/ml/features/drift/acknowledge")
async def ml_features_drift_acknowledge(request: Request, payload: DriftAcknowledgeRequest):
    """Admin drift triage workflow with owner/status/remediation evidence."""
    require_role(request, "admin")
    domain = (payload.domain or "").strip().lower()
    if domain not in {"sage", "hr"}:
        raise HTTPException(status_code=400, detail="domain must be one of sage|hr")

    current_batch_id = (payload.current_batch_id or "").strip()
    if not current_batch_id:
        raise HTTPException(status_code=400, detail="current_batch_id is required")

    status = (payload.status or "").strip().lower()
    prior = _resolve_latest_drift_ack(domain, current_batch_id)
    previous_status = prior.get("status") if isinstance(prior, dict) else None
    _validate_drift_ack_transition(previous_status, status)

    due_at = (payload.due_at or "").strip() or None
    if due_at and parse_iso8601(due_at) is None:
        raise HTTPException(status_code=400, detail="due_at must be a valid ISO8601 datetime")

    owner_id = (payload.owner_id or "").strip() or None
    remediation_notes = (payload.remediation_notes or "").strip() or None
    remediation_actions = [
        str(action).strip()
        for action in (payload.remediation_actions or [])
        if str(action).strip()
    ]

    actor_id = request.state.user.get("sub")
    acknowledged_at = dt.datetime.utcnow().replace(microsecond=0).isoformat() + "Z"
    reason_code = (payload.reason_code or "").strip() or "ml_drift_triage"
    details = {
        "domain": domain,
        "current_batch_id": current_batch_id,
        "status": status,
        "previous_status": previous_status,
        "owner_id": owner_id,
        "due_at": due_at,
        "reason_code": reason_code,
        "remediation_notes": remediation_notes,
        "remediation_actions": remediation_actions,
        "acknowledged_at": acknowledged_at,
    }
    attestation_text = (
        (payload.attestation_text or "").strip()
        or "I attest this drift acknowledgement and remediation plan is authorized and traceable."
    )
    signature_hash_ref = _compute_signature_hash_ref(
        event_type="ml_feature_drift_acknowledged",
        actor_id=actor_id,
        subject_type="ml_feature_drift",
        subject_id=f"{domain}:{current_batch_id}",
        approval_reason=reason_code,
        attestation_text=attestation_text,
        details=details,
    )
    audit_event(
        "ml_feature_drift_acknowledged",
        details,
        actor_id=actor_id,
        event_class="analytics",
        action="acknowledge_ml_feature_drift",
        outcome="success",
        reason_code=reason_code,
        subject_type="ml_feature_drift",
        subject_id=f"{domain}:{current_batch_id}",
        approval_reason=reason_code,
        attestation_text=attestation_text,
        signature_hash_ref=signature_hash_ref,
    )

    return {
        "status": "acknowledged",
        "domain": domain,
        "current_batch_id": current_batch_id,
        "ack": {
            "status": status,
            "previous_status": previous_status,
            "owner_id": owner_id,
            "due_at": due_at,
            "reason_code": reason_code,
            "remediation_notes": remediation_notes,
            "remediation_actions": remediation_actions,
            "acknowledged_at": acknowledged_at,
        },
        "signature_hash_ref": signature_hash_ref,
    }


@app.get("/ml/features/drift/remediation/export")
async def ml_features_drift_remediation_export(
    request: Request,
    domain: str = "sage",
    format: str = "json",
    limit: int = 200,
):
    """Admin export for drift acknowledgement/remediation notes."""
    require_role(request, "admin")
    normalized_domain = (domain or "").strip().lower()
    if normalized_domain not in {"sage", "hr"}:
        raise HTTPException(status_code=400, detail="domain must be one of sage|hr")

    fmt = (format or "json").strip().lower()
    if fmt not in {"json", "csv"}:
        raise HTTPException(status_code=400, detail="format must be json or csv")

    safe_limit = max(1, min(limit, 1000))
    rows = list_audit_logs_filtered(
        limit=safe_limit * 5,
        event_type="ml_feature_drift_acknowledged",
        subject_type="ml_feature_drift",
    )

    data: list[dict[str, Any]] = []
    for row in rows or []:
        details = row.get("details") if isinstance(row, dict) else {}
        if not isinstance(details, dict):
            continue
        if (details.get("domain") or "").strip().lower() != normalized_domain:
            continue
        data.append(
            {
                "domain": normalized_domain,
                "current_batch_id": details.get("current_batch_id"),
                "status": details.get("status"),
                "previous_status": details.get("previous_status"),
                "owner_id": details.get("owner_id"),
                "due_at": details.get("due_at"),
                "reason_code": details.get("reason_code"),
                "remediation_notes": details.get("remediation_notes"),
                "remediation_actions": details.get("remediation_actions") or [],
                "acknowledged_at": details.get("acknowledged_at") or row.get("created_at"),
                "signature_hash_ref": row.get("signature_hash_ref"),
            }
        )
        if len(data) >= safe_limit:
            break

    actor_id = request.state.user.get("sub")
    exported_at = dt.datetime.utcnow().replace(microsecond=0).isoformat() + "Z"
    export_details = {
        "domain": normalized_domain,
        "count": len(data),
        "limit": safe_limit,
        "format": fmt,
        "exported_at": exported_at,
    }
    export_attestation = "I attest this drift remediation export is authorized and traceable."
    export_signature_hash_ref = _compute_signature_hash_ref(
        event_type="ml_feature_drift_remediation_exported",
        actor_id=actor_id,
        subject_type="ml_feature_drift_remediation_export",
        subject_id=f"{normalized_domain}:{exported_at}",
        approval_reason="ml_drift_remediation_export",
        attestation_text=export_attestation,
        details=export_details,
    )
    audit_event(
        "ml_feature_drift_remediation_exported",
        export_details,
        actor_id=actor_id,
        event_class="analytics",
        action="export_ml_feature_drift_remediation",
        outcome="success",
        reason_code="ml_drift_remediation_export",
        subject_type="ml_feature_drift_remediation_export",
        subject_id=f"{normalized_domain}:{exported_at}",
        approval_reason="ml_drift_remediation_export",
        attestation_text=export_attestation,
        signature_hash_ref=export_signature_hash_ref,
    )

    if fmt == "json":
        return {
            "domain": normalized_domain,
            "count": len(data),
            "exported_at": exported_at,
            "signature_hash_ref": export_signature_hash_ref,
            "data": data,
        }

    output = StringIO()
    writer = csv.writer(output)
    writer.writerow([
        "domain",
        "current_batch_id",
        "status",
        "previous_status",
        "owner_id",
        "due_at",
        "reason_code",
        "acknowledged_at",
        "remediation_notes",
        "remediation_actions",
        "signature_hash_ref",
    ])
    for row in data:
        writer.writerow([
            row.get("domain"),
            row.get("current_batch_id"),
            row.get("status"),
            row.get("previous_status"),
            row.get("owner_id"),
            row.get("due_at"),
            row.get("reason_code"),
            row.get("acknowledged_at"),
            row.get("remediation_notes"),
            "; ".join(str(action) for action in (row.get("remediation_actions") or [])),
            row.get("signature_hash_ref"),
        ])
    return Response(content=output.getvalue(), media_type="text/csv")


@app.get("/ml/features/drift/scorecard")
async def ml_features_drift_scorecard(
    request: Request,
    domain: str = "sage",
    limit: int = 50,
):
    """Admin KPI scorecard for drift SLA and remediation timeliness."""
    require_role(request, "admin")
    normalized_domain = (domain or "").strip().lower()
    if normalized_domain not in {"sage", "hr"}:
        raise HTTPException(status_code=400, detail="domain must be one of sage|hr")

    scorecard = _build_ml_drift_scorecard(normalized_domain, limit=max(1, min(limit, 200)))
    generated_at = dt.datetime.utcnow().replace(microsecond=0).isoformat() + "Z"

    actor_id = request.state.user.get("sub")
    details = {
        "domain": normalized_domain,
        "generated_at": generated_at,
        "count": scorecard.get("count"),
        "kpis": scorecard.get("kpis") or {},
        "limit": limit,
    }
    attestation_text = "I attest this drift scorecard review is authorized and traceable."
    signature_hash_ref = _compute_signature_hash_ref(
        event_type="ml_feature_drift_scorecard_viewed",
        actor_id=actor_id,
        subject_type="ml_feature_drift_scorecard",
        subject_id=f"{normalized_domain}:{generated_at}",
        approval_reason="ml_drift_scorecard_review",
        attestation_text=attestation_text,
        details=details,
    )
    audit_event(
        "ml_feature_drift_scorecard_viewed",
        details,
        actor_id=actor_id,
        event_class="analytics",
        action="view_ml_feature_drift_scorecard",
        outcome="success",
        reason_code="ml_drift_scorecard_review",
        subject_type="ml_feature_drift_scorecard",
        subject_id=f"{normalized_domain}:{generated_at}",
        approval_reason="ml_drift_scorecard_review",
        attestation_text=attestation_text,
        signature_hash_ref=signature_hash_ref,
    )

    return {
        **scorecard,
        "generated_at": generated_at,
        "signature_hash_ref": signature_hash_ref,
    }


@app.get("/ml/features/drift/escalations")
async def ml_features_drift_escalations(
    request: Request,
    domain: str = "sage",
    limit: int = 50,
):
    """Admin escalation queue for unresolved high-severity drift items."""
    require_role(request, "admin")
    normalized_domain = (domain or "").strip().lower()
    if normalized_domain not in {"sage", "hr"}:
        raise HTTPException(status_code=400, detail="domain must be one of sage|hr")

    artifacts = _build_ml_drift_escalation_artifacts(normalized_domain, limit=max(1, min(limit, 200)))
    generated_at = dt.datetime.utcnow().replace(microsecond=0).isoformat() + "Z"

    actor_id = request.state.user.get("sub")
    details = {
        "domain": normalized_domain,
        "generated_at": generated_at,
        "count": artifacts.get("count"),
        "owner_alert_count": len(artifacts.get("owner_alerts") or []),
        "limit": limit,
    }
    attestation_text = "I attest this drift escalation queue review is authorized and traceable."
    signature_hash_ref = _compute_signature_hash_ref(
        event_type="ml_feature_drift_escalations_viewed",
        actor_id=actor_id,
        subject_type="ml_feature_drift_escalation",
        subject_id=f"{normalized_domain}:{generated_at}",
        approval_reason="ml_drift_escalation_review",
        attestation_text=attestation_text,
        details=details,
    )
    audit_event(
        "ml_feature_drift_escalations_viewed",
        details,
        actor_id=actor_id,
        event_class="analytics",
        action="view_ml_feature_drift_escalations",
        outcome="success",
        reason_code="ml_drift_escalation_review",
        subject_type="ml_feature_drift_escalation",
        subject_id=f"{normalized_domain}:{generated_at}",
        approval_reason="ml_drift_escalation_review",
        attestation_text=attestation_text,
        signature_hash_ref=signature_hash_ref,
    )

    return {
        **artifacts,
        "generated_at": generated_at,
        "signature_hash_ref": signature_hash_ref,
    }


@app.post("/ml/features/drift/reminders/preview")
async def ml_features_drift_reminders_preview(request: Request, payload: DriftReminderPreviewRequest):
    """Admin preview hook for reminder scheduling on unresolved drift issues."""
    require_role(request, "admin")
    normalized_domain = (payload.domain or "").strip().lower()
    if normalized_domain not in {"sage", "hr"}:
        raise HTTPException(status_code=400, detail="domain must be one of sage|hr")

    preview = _build_ml_drift_reminder_preview(
        normalized_domain,
        limit=max(1, min(payload.limit, 200)),
        min_open_hours=payload.min_open_hours,
    )

    generated_at = dt.datetime.utcnow().replace(microsecond=0).isoformat() + "Z"
    actor_id = request.state.user.get("sub")
    details = {
        "domain": normalized_domain,
        "generated_at": generated_at,
        "count": preview.get("count"),
        "threshold_hours": preview.get("threshold_hours"),
        "limit": payload.limit,
    }
    attestation_text = "I attest this drift reminder preview is authorized and traceable."
    signature_hash_ref = _compute_signature_hash_ref(
        event_type="ml_feature_drift_reminders_previewed",
        actor_id=actor_id,
        subject_type="ml_feature_drift_reminder_preview",
        subject_id=f"{normalized_domain}:{generated_at}",
        approval_reason="ml_drift_reminder_preview",
        attestation_text=attestation_text,
        details=details,
    )
    audit_event(
        "ml_feature_drift_reminders_previewed",
        details,
        actor_id=actor_id,
        event_class="analytics",
        action="preview_ml_feature_drift_reminders",
        outcome="success",
        reason_code="ml_drift_reminder_preview",
        subject_type="ml_feature_drift_reminder_preview",
        subject_id=f"{normalized_domain}:{generated_at}",
        approval_reason="ml_drift_reminder_preview",
        attestation_text=attestation_text,
        signature_hash_ref=signature_hash_ref,
    )

    return {
        **preview,
        "generated_at": generated_at,
        "signature_hash_ref": signature_hash_ref,
    }


@app.post("/ml/models/demand-forecast/train")
async def ml_train_demand_forecast_model(request: Request, payload: DemandForecastTrainRequest):
    """Train and register a demand forecast model manifest (registry-lite)."""
    require_role(request, "admin")
    domain = (payload.domain or "").strip().lower()
    if domain != "ops":
        raise HTTPException(status_code=400, detail="domain must be ops for demand forecast MVP")

    min_points = max(4, min(int(payload.min_points or 6), 60))
    holdout_points = max(1, min(int(payload.holdout_points or 3), 12))
    series_payload = stock_turnover_series(periods=max(min_points + holdout_points + 6, 24))
    series = series_payload.get("series") if isinstance(series_payload, dict) else []
    values = [float((point or {}).get("turnover") or 0.0) for point in (series or [])]
    if len(values) < min_points:
        raise HTTPException(status_code=400, detail=f"Insufficient time-series points: need at least {min_points}")

    if len(values) <= holdout_points:
        holdout_points = max(1, len(values) // 3)
    split_index = max(2, len(values) - holdout_points)
    train_values = values[:split_index]
    holdout_values = values[split_index:]

    trend = _fit_linear_trend(train_values)
    holdout_predictions = _predict_linear_trend(
        float(trend.get("intercept") or 0.0),
        float(trend.get("slope") or 0.0),
        start_index=len(train_values),
        horizon=max(1, len(holdout_values)),
    )

    posture_domain = (payload.posture_domain or "sage").strip().lower()
    if posture_domain not in {"sage", "hr"}:
        raise HTTPException(status_code=400, detail="posture_domain must be one of sage|hr")

    manifest = _build_demand_forecast_manifest(
        domain=domain,
        model_key="demand_forecast_ops",
        training_values=train_values,
        holdout_values=holdout_values,
        holdout_predictions=holdout_predictions,
        trend_params=trend,
        posture_domain=posture_domain,
        max_mae_ratio=float(payload.max_mae_ratio or 0.35),
        approve_if_ready=bool(payload.approve_if_ready),
    )

    actor_id = request.state.user.get("sub")
    attestation_text = "I attest this model manifest registration is authorized and traceable."
    signature_hash_ref = _compute_signature_hash_ref(
        event_type="ml_model_manifest_registered",
        actor_id=actor_id,
        subject_type="ml_model_manifest",
        subject_id=f"{manifest.get('model_key')}:{manifest.get('model_version')}",
        approval_reason="ml_model_manifest_register",
        attestation_text=attestation_text,
        details=manifest,
    )
    audit_event(
        "ml_model_manifest_registered",
        manifest,
        actor_id=actor_id,
        event_class="analytics",
        action="register_ml_model_manifest",
        outcome="success",
        reason_code="ml_model_manifest_register",
        subject_type="ml_model_manifest",
        subject_id=f"{manifest.get('model_key')}:{manifest.get('model_version')}",
        approval_reason="ml_model_manifest_register",
        attestation_text=attestation_text,
        signature_hash_ref=signature_hash_ref,
    )

    return {
        "status": manifest.get("status"),
        "manifest": manifest,
        "holdout": {
            "actual": holdout_values,
            "predicted": holdout_predictions,
        },
        "signature_hash_ref": signature_hash_ref,
    }


@app.post("/ml/models/demand-forecast/predict")
async def ml_predict_demand_forecast(request: Request, payload: DemandForecastPredictRequest):
    """Run demand forecast inference from latest (or selected) registered model manifest."""
    require_role(request, "admin")
    domain = (payload.domain or "").strip().lower()
    if domain != "ops":
        raise HTTPException(status_code=400, detail="domain must be ops for demand forecast MVP")

    manifest = _resolve_latest_model_manifest(
        model_key="demand_forecast_ops",
        domain=domain,
        model_version=payload.model_version,
    )
    if not manifest:
        raise HTTPException(status_code=404, detail="No registered demand forecast model manifest found")

    model = manifest.get("model") if isinstance(manifest, dict) else {}
    params = model.get("params") if isinstance(model, dict) else {}
    intercept = float((params or {}).get("intercept") or 0.0)
    slope = float((params or {}).get("slope") or 0.0)

    current_series_payload = stock_turnover_series(periods=24)
    current_series = current_series_payload.get("series") if isinstance(current_series_payload, dict) else []
    start_index = len(current_series or [])
    horizon = max(1, min(int(payload.horizon or 3), 24))
    predictions = _predict_linear_trend(intercept, slope, start_index=start_index, horizon=horizon)

    actor_id = request.state.user.get("sub")
    generated_at = dt.datetime.utcnow().replace(microsecond=0).isoformat() + "Z"
    details = {
        "domain": domain,
        "model_key": manifest.get("model_key"),
        "model_version": manifest.get("model_version"),
        "horizon": horizon,
        "generated_at": generated_at,
    }
    attestation_text = "I attest this demand forecast inference is authorized and traceable."
    signature_hash_ref = _compute_signature_hash_ref(
        event_type="ml_model_inference_executed",
        actor_id=actor_id,
        subject_type="ml_model_manifest",
        subject_id=f"{manifest.get('model_key')}:{manifest.get('model_version')}",
        approval_reason="ml_model_inference",
        attestation_text=attestation_text,
        details=details,
    )
    audit_event(
        "ml_model_inference_executed",
        details,
        actor_id=actor_id,
        event_class="analytics",
        action="run_ml_model_inference",
        outcome="success",
        reason_code="ml_model_inference",
        subject_type="ml_model_manifest",
        subject_id=f"{manifest.get('model_key')}:{manifest.get('model_version')}",
        approval_reason="ml_model_inference",
        attestation_text=attestation_text,
        signature_hash_ref=signature_hash_ref,
    )

    return {
        "domain": domain,
        "model_key": manifest.get("model_key"),
        "model_version": manifest.get("model_version"),
        "status": manifest.get("status"),
        "horizon": horizon,
        "series_points": start_index,
        "predictions": predictions,
        "generated_at": generated_at,
        "signature_hash_ref": signature_hash_ref,
    }


@app.get("/ml/models/demand-forecast/manifests")
async def ml_list_demand_forecast_manifests(request: Request, domain: str = "ops", limit: int = 20):
    """List registered demand forecast model manifests (registry-lite)."""
    require_role(request, "admin")
    normalized_domain = (domain or "").strip().lower()
    if normalized_domain != "ops":
        raise HTTPException(status_code=400, detail="domain must be ops for demand forecast MVP")

    manifests = _list_model_manifests(
        model_key="demand_forecast_ops",
        domain=normalized_domain,
        limit=max(1, min(limit, 100)),
    )
    return {
        "domain": normalized_domain,
        "count": len(manifests),
        "data": manifests,
    }

# ---- HR Analytics ----------------------------------------------------------

@app.post("/hr/import")
async def hr_import(
    request: Request,
    background_tasks: BackgroundTasks,
    payroll: UploadFile | None = File(default=None),
    absences: UploadFile | None = File(default=None),
    async_mode: bool = False,
):
    require_roles(request, ["hr", "admin"])
    import uuid, datetime
    batch_id = str(uuid.uuid4())
    imported_at = datetime.datetime.utcnow().replace(microsecond=0).isoformat() + "Z"
    idempotency_key = _extract_idempotency_key(request)
    if idempotency_key:
        existing = find_import_job_by_idempotency("hr", idempotency_key)
        if existing:
            return _replay_or_busy_response(existing, imported_at)
    job_id = create_import_job(
        domain="hr",
        batch_id=batch_id,
        imported_at=imported_at,
        metadata={"source_system": "hr_upload", "idempotency_key": idempotency_key, "mode": "async" if async_mode else "sync"},
        idempotency_key=idempotency_key,
        status="queued" if async_mode else "running",
    )

    datasets: dict[str, dict] = {}
    for name, file in (("payroll", payroll), ("absences", absences)):
        if file:
            datasets[name] = {"filename": file.filename, "content_type": file.content_type, "content": await file.read()}

    if async_mode:
        background_tasks.add_task(
            _process_hr_import_job,
            job_id=job_id,
            batch_id=batch_id,
            imported_at=imported_at,
            datasets=datasets,
            idempotency_key=idempotency_key,
            raise_on_error=False,
        )
        return JSONResponse(status_code=202, content={"status": "queued", "job_id": job_id, "batch_id": batch_id, "imported_at": imported_at})

    result = await _process_hr_import_job(
        job_id=job_id,
        batch_id=batch_id,
        imported_at=imported_at,
        datasets=datasets,
        idempotency_key=idempotency_key,
        raise_on_error=True,
    )
    if result is None:
        raise HTTPException(status_code=500, detail="Import failed")
    return result


@app.get("/hr/analytics/summary")
async def hr_analytics_summary(request: Request, periods: int = 3):
    require_roles(request, ["hr", "admin", "management"])
    res = payroll_and_absence_summary(periods=periods)
    abs_trend = res.get("absenteeism_trend", [])
    trend_info = {}
    if len(abs_trend) >= 2:
        prev = float(abs_trend[-2].get("hours") or 0)
        curr = float(abs_trend[-1].get("hours") or 0)
        change_pct = compute_change_pct(curr, prev)
        trend = trend_label(change_pct, positive_is_good=False)
        trend_info = {"trend": trend, "change_pct": change_pct}
    res["absenteeism_trend_flag"] = trend_info
    audit_event("hr_analytics", {"periods": periods, "user": getattr(request.state, "user", None)})
    return res


# ---- Operations Analytics --------------------------------------------------

@app.post("/ops/import")
async def ops_import(
    request: Request,
    background_tasks: BackgroundTasks,
    orders: UploadFile | None = File(default=None),
    downtime: UploadFile | None = File(default=None),
    async_mode: bool = False,
):
    require_roles(request, ["ops", "admin"])
    import uuid, datetime
    batch_id = str(uuid.uuid4())
    imported_at = datetime.datetime.utcnow().replace(microsecond=0).isoformat() + "Z"
    idempotency_key = _extract_idempotency_key(request)
    if idempotency_key:
        existing = find_import_job_by_idempotency("ops", idempotency_key)
        if existing:
            return _replay_or_busy_response(existing, imported_at)
    job_id = create_import_job(
        domain="ops",
        batch_id=batch_id,
        imported_at=imported_at,
        metadata={"source_system": "ops_upload", "idempotency_key": idempotency_key, "mode": "async" if async_mode else "sync"},
        idempotency_key=idempotency_key,
        status="queued" if async_mode else "running",
    )

    datasets: dict[str, dict] = {}
    for name, file in (("orders", orders), ("downtime", downtime)):
        if file:
            datasets[name] = {"filename": file.filename, "content_type": file.content_type, "content": await file.read()}

    if async_mode:
        background_tasks.add_task(
            _process_ops_import_job,
            job_id=job_id,
            batch_id=batch_id,
            imported_at=imported_at,
            datasets=datasets,
            idempotency_key=idempotency_key,
            raise_on_error=False,
        )
        return JSONResponse(status_code=202, content={"status": "queued", "job_id": job_id, "batch_id": batch_id, "imported_at": imported_at})

    result = await _process_ops_import_job(
        job_id=job_id,
        batch_id=batch_id,
        imported_at=imported_at,
        datasets=datasets,
        idempotency_key=idempotency_key,
        raise_on_error=True,
    )
    if result is None:
        raise HTTPException(status_code=500, detail="Import failed")
    return result


@app.get("/ops/kpis")
async def ops_kpis_endpoint(request: Request):
    require_roles(request, ["ops", "admin", "management"])
    res = ops_kpis()
    series = stock_turnover_series(periods=6).get("series", [])
    trend_info = {}
    if len(series) >= 2:
        prev = float(series[-2].get("turnover") or 0)
        curr = float(series[-1].get("turnover") or 0)
        change_pct = compute_change_pct(curr, prev)
        trend = trend_label(change_pct, positive_is_good=True)
        trend_info = {"trend": trend, "change_pct": change_pct}
    res["stock_turnover_trend"] = trend_info
    audit_event("ops_kpis", {"user": getattr(request.state, "user", None)})
    return res


@app.get("/intelligence/executive_summary")
async def intelligence_executive_summary(request: Request):
    """Executive business health summary.

    Roles: admin only.
    """
    require_roles(request, ["admin", "management", "finance"])
    try:
        return executive_summary()
    except Exception as e:
        logging.error(f"/intelligence/executive_summary error: {e}")
        return {
            "status": "Degraded",
            "key_findings": ["Data pipeline error — check server logs for details."],
            "recommended_focus": ["Engineering"],
            "error": str(e),
        }


@app.get("/intelligence/risk_signals")
async def intelligence_risk_signals(request: Request):
    """Unified risk signals across Finance, CRM, Inventory, Ops, and HR.

    Roles: admin only.
    """
    require_roles(request, ["admin", "management", "finance", "ops"])
    try:
        signals = risk_signals()
        opportunities = opportunities_from_risks(signals.get("risks", []))
        return {**signals, "opportunities": opportunities}
    except Exception as e:
        logging.error(f"/intelligence/risk_signals error: {e}")
        return {"risks": [], "opportunities": []}


@app.get("/intelligence/recommendations")
async def intelligence_recommendations(request: Request):
    """Explainable, rule-based recommendations.

    Roles: admin only.
    """
    require_roles(request, ["admin", "management", "finance", "ops"])
    try:
        return recommendations()
    except Exception as e:
        logging.error(f"/intelligence/recommendations error: {e}")
        return {"recommendations": []}


@app.get("/intelligence/anomalies")
async def intelligence_anomalies(request: Request):
    """Optional lightweight anomaly detection (z-score based)."""
    require_roles(request, ["admin", "management", "finance", "ops"])
    try:
        return anomaly_signals()
    except Exception as e:
        logging.error(f"/intelligence/anomalies error: {e}")
        return {"anomalies": []}


@app.get("/ops/forecast/stock_turnover")
async def ops_forecast_stock_turnover(request: Request, window: int = 3, horizon: int = 3):
    require_roles(request, ["ops", "admin"])
    res = forecast_stock_turnover(window=window, horizon=horizon)
    audit_event("ops_forecast_stock_turnover", {"window": window, "horizon": horizon, "user": getattr(request.state, "user", None)})
    return res


# ---- CRM Risk Scoring ------------------------------------------------------

@app.post("/crm/import")
async def crm_import(
    request: Request,
    background_tasks: BackgroundTasks,
    pipeline: UploadFile | None = File(default=None),
    async_mode: bool = False,
):
    require_roles(request, ["sales", "admin"])
    import uuid, datetime
    batch_id = str(uuid.uuid4())
    imported_at = datetime.datetime.utcnow().replace(microsecond=0).isoformat() + "Z"
    idempotency_key = _extract_idempotency_key(request)
    if idempotency_key:
        existing = find_import_job_by_idempotency("crm", idempotency_key)
        if existing:
            return _replay_or_busy_response(existing, imported_at)
    job_id = create_import_job(
        domain="crm",
        batch_id=batch_id,
        imported_at=imported_at,
        metadata={"source_system": "crm_upload", "idempotency_key": idempotency_key, "mode": "async" if async_mode else "sync"},
        idempotency_key=idempotency_key,
        status="queued" if async_mode else "running",
    )

    datasets: dict[str, dict] = {}
    if pipeline:
        datasets["pipeline"] = {"filename": pipeline.filename, "content_type": pipeline.content_type, "content": await pipeline.read()}

    if async_mode:
        background_tasks.add_task(
            _process_crm_import_job,
            job_id=job_id,
            batch_id=batch_id,
            imported_at=imported_at,
            datasets=datasets,
            idempotency_key=idempotency_key,
            raise_on_error=False,
        )
        return JSONResponse(status_code=202, content={"status": "queued", "job_id": job_id, "batch_id": batch_id, "imported_at": imported_at})

    result = await _process_crm_import_job(
        job_id=job_id,
        batch_id=batch_id,
        imported_at=imported_at,
        datasets=datasets,
        idempotency_key=idempotency_key,
        raise_on_error=True,
    )
    if result is None:
        raise HTTPException(status_code=500, detail="Import failed")
    return result


@app.get("/crm/risk_scores")
async def crm_risk_scores_endpoint(request: Request):
    require_roles(request, ["sales", "admin"])
    res = crm_risk_scores()
    audit_event("crm_risk_scores", {"user": getattr(request.state, "user", None)})
    return res


@app.get("/admin/leads-to-orders")
async def leads_to_orders(request: Request, days: int = 30):
    require_role(request, "admin")
    from src.db_helpers import get_lead_order_conversion
    return {"data": get_lead_order_conversion(days=days)}

if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8000))  # Render uses PORT env
    uvicorn.run(app, host="0.0.0.0", port=port)


@app.get("/admin/leads")
async def admin_leads(request: Request, limit: int = 50, offset: int = 0):
    """Admin endpoint: return recent leads with pagination (admin only)."""
    require_role(request, "admin")
    from src.db import db, audit_event
    from src.constants import TABLE_LEADS
    try:
        start = int(offset)
        end = int(offset) + int(limit) - 1
        resp = db.table(TABLE_LEADS).select("*").order("created_at", desc=True).range(start, end).execute()
        leads = resp.data or []
        audit_event("admin_list_leads", {"count": len(leads)}, event_class="admin", actor_id=getattr(request.state, "user", None), subject_type="leads")
        return {"data": leads, "count": len(leads)}
    except Exception as e:
        import logging

        logging.exception("Failed to fetch admin leads: %s", e)
        raise HTTPException(status_code=500, detail="Failed to fetch leads")
