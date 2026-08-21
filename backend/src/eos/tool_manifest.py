"""
EOS Tool Manifest — Single Source of Truth
===========================================
This file is the *only* place where intent keywords, handler names, agent
mappings, and tool-registry names are declared.  Both ``service.py`` and
``app.py`` import from here; nothing is duplicated.

No FastAPI, no DB imports — pure data structures so this module is safe to
import from anywhere without circular-dependency risk.
"""
from __future__ import annotations

from typing import Dict, List, Optional

# ---------------------------------------------------------------------------
# 1.  AVAILABLE AGENTS
#     Maps agent name → human-readable description shown in /eos/agents and
#     in the LLM parse prompt.
# ---------------------------------------------------------------------------
AVAILABLE_AGENTS: Dict[str, str] = {
    "financial_agent":            "Financial analysis, P&L, cashflow, AR/AP trends",
    "inventory_agent":            "Inventory levels, stock movements, expiry tracking",
    "compliance_agent":           "Regulatory compliance, NAFDAC audits, QMS activity scanning, SOP adherence, policy violations",
    "audit_intelligence":         "Audit schedule analysis, overdue audits, upcoming audits, compliance calendar, department audit risk",
    "deviation_capa":             "Deviation reports, CAPA actions, investigation workflow, QMS non-conformances",
    "maintenance_tracker":        "Equipment maintenance schedules, calibration status, cold-chain equipment uptime",
    "recall_manager":             "Product recalls, distribution trace, NAFDAC recall notifications, recall effectiveness",
    "cold_chain_agent":           "Temperature monitoring, cold storage, spoilage risk",
    "logistics_agent":            "Shipping, deliveries, supply chain capacity",
    "revenue_agent":              "Revenue forecasts, pricing, profitability",
    "enterprise_risk_agent":      "Risk assessment, mitigation strategies",
    "process_optimization_agent": "Workflow efficiency, automation opportunities",
    "import_agent":               "Import status, customs, procurement tracking",
    # --- New agents wired from app-wide agent registry ---
    "hr_agent":                   "Payroll, staff absences, workforce analytics",
    "crm_agent":                  "CRM analytics, lead scoring, customer risk, sales pipeline",
    "supplier_agent":             "Supplier performance, scorecard, delivery metrics",
    "digital_twin_agent":         "Digital twin system health, anomalies, dependency graph",
    "capability_agent":           "Capability gap detection, system improvement proposals",
    "lead_finder_agent":          "Discover pharma/healthcare prospects by location using Google Places intelligence",
}


# ---------------------------------------------------------------------------
# 2.  ACTION INTENTS
#     Intents that trigger a real action (email, calendar, task, etc.)
#     rather than running the analytics pipeline.
#
#     Each entry:
#       keywords  – lowercase substrings; if ANY appear in the question the
#                   intent is detected without calling the LLM parser.
#       handler   – name of the async function in service.py.
#       description – shown in the LLM parse prompt.
# ---------------------------------------------------------------------------
ACTION_INTENTS: Dict[str, Dict] = {
    "send_email": {
        "keywords": [
            "send email",
            "email the",
            "send an email",
            "notify the",
            "message the",
            "drop an email",
            "send a message to",
            "send a note to",
            "notify our",
            "email our",
            "contact the",
        ],
        "handler": "_handle_send_email_action",
        "description": "Send an email to an internal department or contact",
    },
    "send_whatsapp": {
        "keywords": [
            "send whatsapp",
            "whatsapp the",
            "send a whatsapp",
            "text the",
            "send a text to",
            "ping the",
            "whatsapp message",
        ],
        "handler": "_handle_send_whatsapp_action",
        "description": "Send a WhatsApp message to an internal department or staff member",
    },
    "schedule_meeting": {
        "keywords": [
            "schedule a meeting",
            "set up a meeting",
            "book a meeting",
            "arrange a meeting",
            "schedule a call",
            "create a meeting",
            "book a call",
            "setup a meeting",
            "schedule meeting",
            "update the calendar",
            "add to the calendar",
            "add to calendar",
        ],
        "handler": "_handle_schedule_meeting_action",
        "description": "Create a calendar event or schedule a meeting",
    },
    "create_task": {
        "keywords": [
            "create a task",
            "create task",
            "add a task",
            "add task",
            "new task",
            "remind me to",
            "set a reminder",
            "todo",
            "to-do",
            "make a note to",
        ],
        "handler": "_handle_task_creation",
        "description": "Create a task or reminder in the task management system",
    },
    "generate_report": {
        "keywords": [
            "generate report",
            "send me a report",
            "export report",
            "pdf report",
            "send report",
            "create a report",
            "pull a report",
            "download report",
            "generate the report",
            # More natural phrasings that don't match the exact-substring
            # patterns above -- e.g. "create the export so i access the
            # entire report" matched none of them and silently fell through
            # to the general chat path instead of actually generating
            # anything. Deliberately not adding a bare "export" or "the
            # report" -- too broad, would false-positive on unrelated
            # conversational mentions.
            "export the report",
            "export this report",
            "the full report",
            "give me the report",
            "access the report",
            "share the report",
            "get me the report",
            "word document",
            "word doc",
            "docx",
            # Domain-specific trigger phrases
            "sales report",
            "weekly sales",
            "pipeline report",
            "payroll report",
            "staff payroll",
            "p&l report",
            "profit and loss",
            "profit & loss",
            "ar aging",
            "accounts receivable report",
            "aging report",
            "frontdesk report",
            "daily operations report",
            "deviation report",
            "audit report",
            "compliance report",
            "inventory report",
            "maintenance report",
            "executive summary report",
            "board report",
        ],
        "handler": "_handle_generate_report_action",
        "description": "Generate and return a structured report (P&L, payroll, compliance, sales, inventory, AR aging, etc.)",
    },
    "trigger_replenishment": {
        "keywords": [
            "create replenishment",
            "submit replenishment",
            "reorder",
            "restock",
            "replenish stock",
            "place a restock",
            "order more stock",
            "low stock order",
            "trigger replenishment",
        ],
        "handler": "_handle_trigger_replenishment_action",
        "description": "Create a replenishment/restock request for a low-stock SKU",
    },
    "find_leads": {
        "keywords": [
            "find leads",
            "find pharmacies",
            "find hospitals",
            "find prospects",
            "discover leads",
            "search for leads",
            "locate pharmacies",
            "prospect search",
            "lead search",
            "find clinics",
            "find healthcare",
            "pharma leads",
            "new leads near",
            "leads in",
        ],
        "handler": "_handle_find_leads_action",
        "description": "Discover pharma/healthcare prospects near a location using location intelligence",
    },
    "send_bulk_message": {
        "keywords": [
            "send bulk sms",
            "send a bulk sms",
            "bulk sms",
            "send bulk message",
            "send a bulk message",
            "bulk message",
            "bulk text",
            "send bulk email",
            "send a bulk email",
            "bulk email",
            "broadcast message",
            "broadcast to customers",
            "broadcast to clients",
            "text all customers",
            "sms all customers",
            "email all customers",
            "message all customers",
            "text our customers",
            "sms our customers",
            "email our customers",
            "message our customers",
            "send a message to all",
            "send a text to all",
        ],
        # Unlike the other action intents, this one always requires an
        # explicit confirmation before anything is actually sent -- real
        # SMS/email cost and reach real customers, at a much larger blast
        # radius than any other action here. app.py special-cases this
        # intent (mirroring send_email's own two-phase draft flow) rather
        # than wiring it into the immediate-execute dispatch table; this
        # handler only resolves/previews, never sends.
        "handler": "_handle_send_bulk_message_action",
        "description": "Preview a bulk SMS or email broadcast to customers (always requires confirmation before sending)",
    },
}

# Convenience: flat keyword → intent_type lookup built from ACTION_INTENTS
# (used by _detect_action_intent in app.py so keywords live in exactly one place)
ACTION_KEYWORD_MAP: Dict[str, str] = {
    kw: intent
    for intent, cfg in ACTION_INTENTS.items()
    for kw in cfg["keywords"]
}

# Ordered detection: more-specific phrases first prevents short substrings from
# shadowing longer, more-specific ones at detection time.
ORDERED_ACTION_KEYWORDS: List[tuple[str, str]] = sorted(
    ACTION_KEYWORD_MAP.items(),
    key=lambda item: -len(item[0]),
)


# ---------------------------------------------------------------------------
# 3.  DATA INTENTS
#     Intents that run the analytics pipeline (parse → decompose → agents →
#     tool-registry → synthesize).
#
#     Each entry:
#       keywords   – fallback keyword detection phrases
#       agents     – agent names to dispatch (registry name used in get_agent())
#       tools      – tool_registry tool names to call for extra context
#       description – shown in the LLM parse prompt
# ---------------------------------------------------------------------------
DATA_INTENTS: Dict[str, Dict] = {
    "financial_review": {
        "keywords": ["revenue", "profit", "cashflow", "p&l", "ar ", "ap ", "financial", "accounts receivable", "accounts payable"],
        "agents": ["financial_agent", "revenue_agent"],
        "tools": ["getFinancialKpis", "getArTrendSummary"],
        "description": "Financial performance review: P&L, cashflow, AR/AP trends",
    },
    "inventory_audit": {
        "keywords": ["stock", "inventory", "expir", "quantity", "sku", "availability"],
        "agents": ["inventory_agent"],
        "tools": ["getLatestInventorySnapshot", "getExpiringInventory"],
        "description": "Inventory levels, stock status, expiry tracking",
    },
    "compliance_check": {
        "keywords": ["sop", "standard operating", "procedure", "compliance activity", "compliance", "audit", "regulation", "nafdac", "qms"],
        "agents": ["compliance_agent", "audit_intelligence"],
        "tools": [],
        "description": "Regulatory compliance, SOP adherence, NAFDAC/QMS status",
    },
    "audit_review": {
        "keywords": ["audit schedule", "audit calendar", "overdue audit", "upcoming audit", "audit risk"],
        "agents": ["audit_intelligence", "compliance_agent"],
        "tools": [],
        "description": "Audit schedule analysis: overdue, upcoming, department risk",
    },
    "deviation_review": {
        "keywords": ["deviation", "capa", "non-conformance", "nonconformance", "corrective action"],
        "agents": ["deviation_capa", "compliance_agent"],
        "tools": [],
        "description": "QMS deviations, CAPA workflow, non-conformance reports",
    },
    "maintenance_check": {
        "keywords": ["maintenance", "calibration", "equipment", "breakdown", "cold chain equipment"],
        "agents": ["maintenance_tracker"],
        "tools": [],
        "description": "Equipment maintenance schedules, calibration status, uptime",
    },
    "recall_management": {
        "keywords": ["recall", "product recall", "batch recall", "recall notification"],
        "agents": ["recall_manager", "compliance_agent"],
        "tools": [],
        "description": "Product recall management, distribution trace, NAFDAC notifications",
    },
    "risk_assessment": {
        "keywords": ["risk", "threat", "vulnerability", "risk register", "risk signals"],
        "agents": ["enterprise_risk_agent"],
        "tools": ["getRiskSignals"],
        "description": "Risk assessment, mitigation strategies, risk heatmap",
    },
    "forecast": {
        "keywords": ["forecast", "predict", "projection", "demand forecast", "stock forecast"],
        "agents": ["financial_agent", "inventory_agent"],
        "tools": ["getOpsKpis"],
        "description": "Demand and financial forecasting",
    },
    "capacity_analysis": {
        "keywords": ["delivery", "shipment", "logistics", "capacity", "cold storage capacity"],
        "agents": ["logistics_agent", "cold_chain_agent"],
        "tools": [],
        "description": "Logistics capacity, delivery ops, cold chain utilization",
    },
    "optimization": {
        "keywords": ["optimize", "efficiency", "bottleneck", "workflow", "process improvement"],
        "agents": ["process_optimization_agent"],
        "tools": [],
        "description": "Workflow efficiency, process bottleneck analysis",
    },
    "status_update": {
        "keywords": [],  # Default fallback — no keywords
        "agents": ["financial_agent"],
        "tools": ["getExecutiveSummary"],
        "description": "General status or business health update",
    },
    "hr_query": {
        "keywords": ["payroll", "salary", "absences", "staff performance", "workforce", "hr report", "overtime"],
        "agents": ["hr_agent"],
        "tools": [],
        "description": "HR analytics: payroll summary, staff absences, workforce metrics",
    },
    "crm_analytics": {
        "keywords": ["crm", "leads", "pipeline", "customer risk", "sales rep", "conversion rate", "crm stats"],
        "agents": ["crm_agent"],
        "tools": [],
        "description": "CRM analytics: lead scoring, pipeline health, customer risk",
    },
    "supplier_performance": {
        "keywords": ["supplier", "vendor performance", "supplier scorecard", "supplier metrics", "procurement performance"],
        "agents": ["supplier_agent"],
        "tools": [],
        "description": "Supplier scorecard, delivery performance, procurement metrics",
    },
    "digital_twin_status": {
        "keywords": ["digital twin", "system health", "twin anomalies", "dependency graph", "twin status"],
        "agents": ["digital_twin_agent"],
        "tools": [],
        "description": "Digital twin system health, open anomalies, inter-system dependencies",
    },
    "executive_overview": {
        "keywords": ["executive overview", "executive brief", "board report", "leadership summary", "business health", "kpi overview"],
        "agents": ["financial_agent", "inventory_agent", "enterprise_risk_agent"],
        "tools": ["getExecutiveSummary", "getRiskSignals", "getRecommendations"],
        "description": "Full executive overview across all business domains",
    },
    "reconciliation_check": {
        "keywords": [
            "reconciliation", "bank reconcile", "reconciled", "outstanding checks",
            "deposits in transit", "bank balance", "cleared", "uncleared",
            "outstanding items", "bank statement", "cash reconciliation",
        ],
        "agents": [],
        "tools": ["getReconciliationStatus"],
        "description": "Bank reconciliation freshness: stale snapshots, GL vs bank balance, outstanding items",
    },
    "db_schema_inquiry": {
        "keywords": [
            "schema", "what tables", "what data do we have", "what data exists",
            "full db scan", "database structure", "what columns", "what other data",
            "what information is stored", "what does the database contain",
            "list all tables", "data inventory", "what is in the database",
        ],
        "agents": [],
        "tools": ["getLiveSchemaSummary"],
        "description": "Live inventory of real database tables, columns, and row counts",
    },
}

# Merged list of all intent type strings for the LLM parse prompt
ALL_INTENT_TYPES: List[str] = list(ACTION_INTENTS.keys()) + list(DATA_INTENTS.keys())

# ---------------------------------------------------------------------------
# 4.  TASK_MAPPING
#     Maps intent_type → list of {agent, action} task descriptors fed to
#     TaskDecomposer.  Uses the DATA_INTENTS agent lists as source of truth.
# ---------------------------------------------------------------------------
def build_task_mapping() -> Dict[str, List[Dict[str, str]]]:
    """Build the TASK_MAPPING dict from DATA_INTENTS — no duplication."""
    mapping: Dict[str, List[Dict[str, str]]] = {}

    for intent_type, cfg in DATA_INTENTS.items():
        tasks = []
        for agent_name in cfg.get("agents", []):
            # derive a sensible default action name from the agent name
            action = {
                "financial_agent":            "get_summary",
                "revenue_agent":              "get_trends",
                "inventory_agent":            "get_stock_levels",
                "compliance_agent":           "get_activity_compliance",
                "audit_intelligence":         "get_audit_status",
                "deviation_capa":             "get_open_deviations",
                "maintenance_tracker":        "get_overdue",
                "recall_manager":             "get_active_recalls",
                "cold_chain_agent":           "storage_status",
                "logistics_agent":            "capacity",
                "enterprise_risk_agent":      "assess_risks",
                "process_optimization_agent": "analyze_workflows",
                "hr_agent":                   "get_summary",
                "crm_agent":                  "get_summary",
                "supplier_agent":             "get_metrics",
                "digital_twin_agent":         "get_state",
                "capability_agent":           "get_proposals",
            }.get(agent_name, "analyze")
            tasks.append({"agent": agent_name, "action": action})
        mapping[intent_type] = tasks

    # Action intents produce no agent tasks (handled directly)
    for intent_type in ACTION_INTENTS:
        mapping[intent_type] = []

    return mapping


TASK_MAPPING: Dict[str, List[Dict[str, str]]] = build_task_mapping()

# ---------------------------------------------------------------------------
# 5.  DEPARTMENT CONTACT MAP
#     Used by send_email / send_whatsapp handlers to resolve dept → address.
#     Loaded from config.yaml at runtime; this dict provides the key synonyms.
# ---------------------------------------------------------------------------
DEPARTMENT_SYNONYMS: Dict[str, List[str]] = {
    "marketing":   ["marketing"],
    "operations":  ["operations", "ops", "operation"],
    "orders":      ["orders", "procurement", "purchasing"],
    "sales":       ["sales"],
    "finance":     ["finance", "accounting", "accounts"],
    "hr":          ["hr", "human resources", "people"],
    "management":  ["management", "executive", "ceo", "coo", "cfo"],
}
