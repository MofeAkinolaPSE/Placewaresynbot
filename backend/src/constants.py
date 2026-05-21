"""Centralized constants for Warebot.

This module provides a single source of truth for branding, table names,
embedding parameters, disclaimers, environment variable keys, and service
endpoint configuration. Import these instead of scattering literals.
"""

import os

# Branding & Bot Identity
BOT_BRAND = "Placeware"
BOT_NAME = "Warebot"

# Embedding / Retrieval Params
EMBEDDING_DIM = 384
DEFAULT_TOP_K = 3
MATCH_THRESHOLD = 0.78

# Disclaimers (append to every user-visible LLM answer)
NAFDAC_DISCLAIMER = (
    "This response is for general pharmaceutical information only and does not substitute for professional medical advice. "
    "Always consult a qualified healthcare professional. Stock levels may change; availability is not guaranteed."
)

# Supabase Tables
TABLE_LEADS = "placeware_leads"
TABLE_USERS = "placeware_users"
TABLE_REFRESH_TOKENS = "placeware_refresh_tokens"
TABLE_ORDERS = "placeware_orders"
TABLE_STOCK_CACHE = "placeware_stock_cache" # Note: Adapter service currently uses 'sage_inventory_snapshot' directly
TABLE_INVENTORY_EVENTS = "placeware_inventory_events"
TABLE_STAFF = "placeware_staff"
TABLE_TIMESHEETS = "placeware_timesheets"
TABLE_ALERTS = "placeware_alerts"
TABLE_BRIEFINGS = "placeware_executive_briefings"
TABLE_TRACKING = "placeware_tracking"
TABLE_AUDIT_LOGS = "placeware_audit_logs"
TABLE_IMPORT_JOBS = "placeware_import_jobs"
TABLE_IMPORT_REJECTIONS = "placeware_import_rejections"
TABLE_KPI_PROMOTIONS = "placeware_kpi_promotions"
TABLE_DATA_POLICIES = "placeware_data_policies"
TABLE_TIMESHEETS = "placeware_timesheets"
TABLE_TRACKING = "placeware_tracking"
TABLE_AUDIT_LOGS = "placeware_audit_logs"
TABLE_QNA = "qna"  # existing vector table
TABLE_CHAT_HISTORY = "placeware_chat_history"
TABLE_CHATS = "placeware_chats"
TABLE_PROJECTS = "placeware_projects"
TABLE_SCOPE_ITEMS = "placeware_scope_items"
TABLE_COST_ITEMS = "placeware_cost_items"
TABLE_RISK_REGISTER = "placeware_risk_register"
TABLE_CHANGE_REQUESTS = "placeware_change_requests"
TABLE_PROCUREMENT_SHIPMENTS = "placeware_procurement_shipments"
TABLE_PROCUREMENT_SHIPMENT_EVENTS = "placeware_procurement_shipment_events"
TABLE_WEBHOOK_IDEMPOTENCY = "placeware_webhook_idempotency"
TABLE_SAGE_SYNC_LOG = "placeware_sage_sync_log"
TABLE_SAGE_SYNC_TIMESTAMPS = "placeware_sage_sync_timestamps"


# Stage 3 project-controls governance
PROJECT_STATUS_ALLOWED = {"active", "on_hold", "completed", "cancelled"}
PROJECT_WORKFLOW_STAGES = {
    "port_clearing",
    "anti_room_received",
    "cold_room_stacked",
    "nafdac_sampling",
    "released_for_issuing",
    "packaging_for_delivery",
    "delivered_to_end_users",
}
PROJECT_QC_STATUS_ALLOWED = {"pending", "in_review", "passed", "failed", "waived"}
PROJECT_QC_APPROVED_STATUSES = {"passed", "waived"}
PROJECT_QC_GATED_STAGES = {"cold_room_stacked", "released_for_issuing"}

PROJECT_STAGE_TRANSITIONS = {
    "port_clearing": {"anti_room_received"},
    "anti_room_received": {"cold_room_stacked", "port_clearing"},
    "cold_room_stacked": {"nafdac_sampling", "anti_room_received"},
    "nafdac_sampling": {"released_for_issuing", "cold_room_stacked"},
    "released_for_issuing": {"packaging_for_delivery", "nafdac_sampling"},
    "packaging_for_delivery": {"delivered_to_end_users", "released_for_issuing"},
    "delivered_to_end_users": set(),
}
SCOPE_STATUS_ALLOWED = {"planned", "in_progress", "done", "deferred", "cancelled"}
COST_STATUS_ALLOWED = {"planned", "approved", "committed", "actual", "cancelled"}
RISK_STATUS_ALLOWED = {"open", "monitoring", "mitigating", "accepted", "closed"}
CHANGE_STATUS_ALLOWED = {"proposed", "under_review", "approved", "rejected", "implemented"}

# --- Order status workflow ---
ORDER_STATUS_ALLOWED = {"received", "packed", "dispatched", "delivered", "cancelled"}
ORDER_STATUS_TRANSITIONS = {
    "received": {"packed", "cancelled"},
    "packed": {"dispatched", "cancelled"},
    "dispatched": {"delivered", "cancelled"},
    "delivered": set(),
    "cancelled": set(),
}

CHANGE_STATUS_TRANSITIONS = {
    "proposed": {"under_review", "rejected"},
    "under_review": {"approved", "rejected"},
    "approved": {"implemented"},
    "rejected": {"under_review"},
    "implemented": set(),
}

SCOPE_STATUS_TRANSITIONS = {
    "planned": {"in_progress", "deferred", "cancelled"},
    "in_progress": {"done", "deferred", "cancelled"},
    "deferred": {"planned", "in_progress", "cancelled"},
    "done": set(),
    "cancelled": set(),
}

COST_STATUS_TRANSITIONS = {
    "planned": {"approved", "cancelled"},
    "approved": {"committed", "cancelled"},
    "committed": {"actual", "cancelled"},
    "actual": set(),
    "cancelled": set(),
}

RISK_STATUS_TRANSITIONS = {
    "open": {"monitoring", "mitigating", "accepted", "closed"},
    "monitoring": {"mitigating", "accepted", "closed"},
    "mitigating": {"monitoring", "accepted", "closed"},
    "accepted": {"monitoring", "closed"},
    "closed": {"monitoring"},
}

HIGH_IMPACT_SCOPE_LEVELS = {"major", "critical"}
HIGH_IMPACT_COST_THRESHOLD = 1_000_000.0
HIGH_IMPACT_SCHEDULE_DAYS_THRESHOLD = 14
HIGH_IMPACT_APPROVAL_REASONS = {
    "regulatory",
    "budget_override",
    "timeline_exception",
    "scope_expansion",
    "risk_acceptance",
    "executive_override",
}

RISK_SCORE_MITIGATION_THRESHOLD = 15
RISK_SCORE_OWNER_THRESHOLD = 20

# Environment Variable Keys
ENV_SUPABASE_URL = "SUPABASE_URL"
ENV_SUPABASE_KEY = "SUPABASE_KEY"
ENV_EMAIL_FROM = "EMAIL_FROM"
ENV_EMAIL_PASS = "EMAIL_PASS"
ENV_LLM_PROVIDER = "LLM_PROVIDER"  # which brain implementation to use: "deepseek" or "service"
ENV_LLM_SERVICE_URL = "LLM_SERVICE_URL"  # microservice endpoint for LLM completions
ENV_LLM_API_KEY = "LLM_API_KEY"  # optional auth for microservice
ENV_LLM_SPACE_URL = "LLM_SPACE_URL"  # optional: HF Space for generation (alternative to microservice)
ENV_LLM_SPACE_API_NAME = "LLM_SPACE_API_NAME"  # e.g. /predict or /predict_js
ENV_LLM_SPACE_API_KEY = "LLM_SPACE_API_KEY"  # optional bearer for private Space

# DeepSeek-specific env (current default brain)
ENV_DEEPSEEK_API_KEY = "DEEPSEEK_API_KEY"
ENV_DEEPSEEK_MODEL = "DEEPSEEK_MODEL"

ENV_SAGE_MOCK = "SAGE_MOCK"  # if set truthy -> use mock adapter
ENV_JWT_SECRET = "JWT_SECRET"  # for signing/verifying admin/user tokens
ENV_RATE_LIMIT = "RATE_LIMIT"  # requests per minute per key/ip (default 60)
ENV_DEV_TOKEN_ENABLED = "DEV_TOKEN_ENABLED"  # allow issuing dev tokens via API
ENV_CORS_ALLOW_ORIGINS = "CORS_ALLOW_ORIGINS"  # comma-separated list of origins
ENV_AT_REST_KEY = "AT_REST_KEY"  # base64-encoded 32-byte key for AES-256-GCM at-rest encryption
ENV_JWT_AUDIENCE = "JWT_AUDIENCE"  # optional audience claim to validate
ENV_AUTH0_DOMAIN = "AUTH0_DOMAIN"  # Auth0 tenant domain (e.g., your-tenant.eu.auth0.com)
ENV_AUTH0_AUDIENCE = "AUTH0_AUDIENCE"  # Auth0 API audience identifier
ENV_WIDGET_SITE_KEYS = "WIDGET_SITE_KEYS"  # comma-separated public site keys allowed for anonymous widget chat
ENV_ACCESS_TOKEN_MINUTES = "ACCESS_TOKEN_MINUTES"
ENV_REFRESH_TOKEN_DAYS = "REFRESH_TOKEN_DAYS"
ENV_WEBSOCKET_ENABLED = "WEBSOCKET_ENABLED"
ENV_PROCUREMENT_CLEARANCE_DELAY_DAYS = "PROCUREMENT_CLEARANCE_DELAY_DAYS"
ENV_PROCUREMENT_DAILY_DELAY_COST = "PROCUREMENT_DAILY_DELAY_COST"

# Optional future integrations
ENV_SAGE_API_KEY = "SAGE_API_KEY"

# ---------------------------------------------------------------------------
# QMS / Compliance Table Names
# ---------------------------------------------------------------------------
TABLE_SOP_REGISTRY          = "sop_registry"
TABLE_AUDIT_SCHEDULE        = "audit_schedule"
TABLE_COMPLIANCE_ACTIVITY   = "compliance_activity_log"
TABLE_EQUIPMENT_REGISTRY    = "equipment_registry"
TABLE_MAINTENANCE_SCHEDULE  = "maintenance_schedule"
TABLE_DEVIATION_REPORTS     = "deviation_reports"
TABLE_RECALL_CASES          = "recall_cases"
TABLE_DOCUMENT_ARCHIVE      = "document_archive"

# Reliability / Maintenance Agent tables
TABLE_MAINTENANCE_ASSETS         = "placeware_maintenance_assets"
TABLE_MAINTENANCE_TASKS          = "placeware_maintenance_tasks"
TABLE_INCIDENT_LOG               = "placeware_incident_log"
TABLE_REMEDIATION_ACTIONS        = "placeware_remediation_actions"
TABLE_FAILURE_PATTERN_LIBRARY    = "placeware_failure_pattern_library"

# Digital Twin tables (migration 075)
TABLE_TWIN_NODES                 = "placeware_twin_nodes"
TABLE_TWIN_STATE_HISTORY         = "placeware_twin_state_history"
TABLE_TWIN_ANOMALY_EVENTS        = "placeware_twin_anomaly_events"
TABLE_TWIN_DEPENDENCY_EDGES      = "placeware_twin_dependency_edges"

# Capability Discovery tables (migration 076)
TABLE_CAPABILITY_SIGNALS         = "placeware_capability_signals"
TABLE_CAPABILITY_PROPOSALS       = "placeware_capability_proposals"
TABLE_CAPABILITY_STATUS_HISTORY  = "placeware_capability_status_history"

# Reliability rollout mode: when True, all auto-fix playbooks are skipped and
# the agent only observes/records without mutating state.
RELIABILITY_OBSERVE_ONLY: bool = os.getenv("RELIABILITY_OBSERVE_ONLY", "false").lower() == "true"

# ── Knowledge Engine tables (migration 073) ──────────────────────────────────
TABLE_INGESTED_DOCUMENTS    = "ingested_documents"
TABLE_KNOWLEDGE_CHUNKS      = "knowledge_chunks"
TABLE_KNOWLEDGE_GAPS        = "knowledge_gaps"
TABLE_SYNBOT_MEMORY         = "synbot_memory"

# Deviation report ID prefix sequence helper (format: DEV-YYYY-NNN)
DEVIATION_ID_PREFIX = "DEV"
RECALL_ID_PREFIX    = "RECALL"

# Document storage backend (local | supabase | s3)
DOCUMENT_STORAGE_BACKEND  = os.getenv("DOCUMENT_STORAGE_BACKEND", "local")
DOCUMENT_STORAGE_BUCKET   = os.getenv("DOCUMENT_STORAGE_BUCKET", "compliance-documents")
DOCUMENT_LOCAL_PATH       = os.path.join(os.path.dirname(__file__), "..", "static", "documents")

# QMS / Compliance role permission sets
COMPLIANCE_ALL_ROLES  = {"admin", "quality_assurance", "qa", "management", "operations", "ops", "staff"}
COMPLIANCE_QA_ROLES   = {"admin", "quality_assurance", "qa"}
COMPLIANCE_MGMT_ROLES = {"admin", "management"}
COMPLIANCE_OPS_ROLES  = {"admin", "quality_assurance", "qa", "operations", "ops", "management"}

# Deviation & Recall status workflows
DEVIATION_STATUS_ALLOWED      = {"open", "under_investigation", "closed", "escalated"}
RECALL_STATUS_ALLOWED         = {"initiated", "in_progress", "completed", "closed"}
AUDIT_STATUS_ALLOWED          = {"scheduled", "in_progress", "completed", "overdue", "skipped"}
ACTIVITY_STATUS_ALLOWED       = {"scheduled", "completed", "missed", "overdue", "deferred"}
MAINTENANCE_STATUS_ALLOWED    = {"scheduled", "completed", "overdue", "cancelled"}

# SOP categories
SOP_CATEGORY_LABELS = {
    "storage":       "Storage & Handling",
    "qc":            "Quality Control & Regulatory",
    "distribution":  "Distribution",
    "warehouse":     "Warehouse Operations",
    "equipment":     "Equipment & Calibration",
    "deviation":     "Deviation & CAPA",
    "recall":        "Recall Management",
    "hr":            "HR & Training",
}

# Webhook shared secret (HMAC) for provider callbacks
ENV_WEBHOOK_SECRET = "WEBHOOK_SECRET"

# --- Financial Data Pipeline Config ---
# GL account code that holds the cash/bank balance (used by kpis() to derive cash position).
# Change this to match the account code in the customer's Sage chart of accounts.
CASH_GL_ACCOUNT_CODE: str = os.getenv("CASH_GL_ACCOUNT_CODE", "1000")

# Revenue accounts: any GL account_code cast to int in this range is treated as revenue (credit side).
REVENUE_GL_ACCOUNT_MIN: int = 4000
REVENUE_GL_ACCOUNT_MAX: int = 4999

# Cost/expense accounts: debit-side rows in this range feed total_cost.
COST_GL_ACCOUNT_MIN: int = 5000
COST_GL_ACCOUNT_MAX: int = 6999

# How many hours before a missing/unchanged Sage import triggers stale_pipeline_alert on /health.
PIPELINE_STALE_HOURS: int = int(os.getenv("PIPELINE_STALE_HOURS", "48"))

# --- Executive Summary Thresholds ---
# AR overdue count above this threshold triggers a key_finding. Set to 0 so any overdue invoice fires.
EXEC_SUMMARY_AR_OVERDUE_THRESHOLD: int = int(os.getenv("EXEC_SUMMARY_AR_OVERDUE_THRESHOLD", "0"))

# Defaults / Derived
LLM_PROVIDER = os.getenv(ENV_LLM_PROVIDER, "deepseek").lower()
LLM_SERVICE_URL = os.getenv(ENV_LLM_SERVICE_URL, "")
LLM_API_KEY = os.getenv(ENV_LLM_API_KEY, "")
LLM_SPACE_URL = os.getenv(ENV_LLM_SPACE_URL, "")
LLM_SPACE_API_NAME = os.getenv(ENV_LLM_SPACE_API_NAME, "/predict")
LLM_SPACE_API_KEY = os.getenv(ENV_LLM_SPACE_API_KEY, "")
DEEPSEEK_API_KEY = os.getenv(ENV_DEEPSEEK_API_KEY, "")
SAGE_MOCK = os.getenv(ENV_SAGE_MOCK, "false") not in ("0", "false", "False")
JWT_SECRET = os.getenv(ENV_JWT_SECRET, "change-me-for-prod-replace-with-32plus-chars")

# Webhook secret used to verify provider callbacks (HMAC-SHA256)
WEBHOOK_SECRET = os.getenv(ENV_WEBHOOK_SECRET, "")
RATE_LIMIT = int(os.getenv(ENV_RATE_LIMIT, "60"))
DEV_TOKEN_ENABLED = os.getenv(ENV_DEV_TOKEN_ENABLED, "1") not in ("0", "false", "False")
CORS_ALLOW_ORIGINS = [o.strip() for o in os.getenv(ENV_CORS_ALLOW_ORIGINS, "*").split(",") if o.strip()] or ["*"]
AT_REST_KEY = os.getenv(ENV_AT_REST_KEY, "")
JWT_AUDIENCE = os.getenv(ENV_JWT_AUDIENCE, "")
AUTH0_DOMAIN = os.getenv(ENV_AUTH0_DOMAIN, "")
AUTH0_AUDIENCE = os.getenv(ENV_AUTH0_AUDIENCE, "")
WIDGET_SITE_KEYS = [k.strip() for k in os.getenv(ENV_WIDGET_SITE_KEYS, "").split(",") if k.strip()]
AUTH0_ISSUER = f"https://{AUTH0_DOMAIN}/" if AUTH0_DOMAIN else ""
ACCESS_TOKEN_MINUTES = int(os.getenv(ENV_ACCESS_TOKEN_MINUTES, "45"))
REFRESH_TOKEN_DAYS = int(os.getenv(ENV_REFRESH_TOKEN_DAYS, "7"))
WEBSOCKET_ENABLED = os.getenv(ENV_WEBSOCKET_ENABLED, "1") not in ("0", "false", "False")
PROCUREMENT_CLEARANCE_DELAY_DAYS = int(os.getenv(ENV_PROCUREMENT_CLEARANCE_DELAY_DAYS, "5"))
PROCUREMENT_DAILY_DELAY_COST = float(os.getenv(ENV_PROCUREMENT_DAILY_DELAY_COST, "250000"))

def append_disclaimer(text: str) -> str:
    """Ensure the NAFDAC disclaimer is appended exactly once."""
    if not text:
        return NAFDAC_DISCLAIMER
    norm = text.strip()
    if NAFDAC_DISCLAIMER.lower() in norm.lower():
        return norm
    return f"{norm}\n\n{NAFDAC_DISCLAIMER}"
