"""Centralized constants for PlacewareBot.

This module provides a single source of truth for branding, table names,
embedding parameters, disclaimers, environment variable keys, and service
endpoint configuration. Import these instead of scattering literals.
"""

import os

# Branding & Bot Identity
BOT_BRAND = "Placeware"
BOT_NAME = "PlacewareBot"

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


# Stage 3 project-controls governance
PROJECT_STATUS_ALLOWED = {"active", "on_hold", "completed", "cancelled"}
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
ENV_HF_API_URL = "HF_API_URL"
ENV_HF_API_KEY = "HF_API_KEY"

# Webhook shared secret (HMAC) for provider callbacks
ENV_WEBHOOK_SECRET = "WEBHOOK_SECRET"

# Defaults / Derived
LLM_PROVIDER = os.getenv(ENV_LLM_PROVIDER, "deepseek").lower()
LLM_SERVICE_URL = os.getenv(ENV_LLM_SERVICE_URL, "")
LLM_API_KEY = os.getenv(ENV_LLM_API_KEY, "")
LLM_SPACE_URL = os.getenv(ENV_LLM_SPACE_URL, "")
LLM_SPACE_API_NAME = os.getenv(ENV_LLM_SPACE_API_NAME, "/predict")
LLM_SPACE_API_KEY = os.getenv(ENV_LLM_SPACE_API_KEY, "")
DEEPSEEK_API_KEY = os.getenv(ENV_DEEPSEEK_API_KEY, "")
SAGE_MOCK = os.getenv(ENV_SAGE_MOCK, "1") not in ("0", "false", "False")
JWT_SECRET = os.getenv(ENV_JWT_SECRET, "change-me-for-prod")

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
