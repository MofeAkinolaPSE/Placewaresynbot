"""
report_templates.py — Central report template registry for Placeware EOS.
=========================================================================
Defines the MANDATORY structure, sections, required scope fields and data
sources for every supported report type, including invoice generation.

Each template entry drives:
  • The ordered sections that the ReportGenerationAgent generates individually
  • The scope fields the user MUST supply before generation (shown in Wizard)
  • The DB tables queried per report (replaces the scattered _REPORT_REGISTRY)
  • The DOCX renderer (section titles, heading hierarchy, table layouts)

Usage:
    from src.report_templates import REPORT_TEMPLATE_REGISTRY, INVOICE_SECTION_ORDER
    template = REPORT_TEMPLATE_REGISTRY["executive"]
    sections = template["sections"]           # ordered list of section dicts
    scope_fields = template["scope_fields"]   # list of ScopeFieldDef dicts
"""
from __future__ import annotations

from typing import Any, Dict, List

# ── Section schema ─────────────────────────────────────────────────────────────
# Each section dict in template["sections"] has:
#   id           str  — machine key, unique within template
#   title        str  — displayed heading in DOCX / UI
#   prompt_hint  str  — guidance injected into LLM prompt for this section
#   required     bool — False → section generates if data available; True → always required
#   order        int  — rendering order (ascending)
#
# ── Scope field schema ─────────────────────────────────────────────────────────
# Each dict in template["scope_fields"] has:
#   key      str   — maps to ScopeParams keys
#   label    str   — user-facing label in Wizard Step 2
#   type     str   — "date" | "text" | "select" | "multiselect" | "number" | "line_items"
#   required bool  — wizard blocks generation if True and not filled
#   options  list  — only for "select" / "multiselect" types


def _section(
    id_: str,
    title: str,
    prompt_hint: str,
    required: bool = True,
    order: int = 0,
) -> Dict[str, Any]:
    return {
        "id": id_,
        "title": title,
        "prompt_hint": prompt_hint,
        "required": required,
        "order": order,
    }


def _scope_field(
    key: str,
    label: str,
    type_: str,
    required: bool = False,
    options: List[str] | None = None,
) -> Dict[str, Any]:
    d: Dict[str, Any] = {"key": key, "label": label, "type": type_, "required": required}
    if options is not None:
        d["options"] = options
    return d


# ── Template registry ──────────────────────────────────────────────────────────

REPORT_TEMPLATE_REGISTRY: Dict[str, Dict[str, Any]] = {

    # ── Deviation & CAPA ──────────────────────────────────────────────────────
    "deviation": {
        "client_facing_name": "Deviation & CAPA Report",
        "output_title": "Deviation & CAPA Report",
        "keywords": ["deviation", "capa", "non-conformance", "nonconformance", "corrective action"],
        "tables": [
            {"table": "placeware_deviation_reports", "select": "*", "order": "created_at", "limit": 50},
        ],
        "scope_fields": [
            _scope_field("date_from", "Report From", "date", required=True),
            _scope_field("date_to", "Report To", "date", required=True),
            _scope_field("department", "Department", "text"),
            _scope_field("severity_filter", "Severity Level", "select",
                         options=["All", "Critical", "Major", "Minor"]),
            _scope_field("custom_notes", "Additional Context / Evidence Notes", "text"),
        ],
        "sections": [
            _section("executive_summary", "Executive Summary",
                     "Provide a 2–3 sentence overview of deviation activity in the period. "
                     "State total deviations, open vs closed, and overall risk posture.", order=1),
            _section("deviation_log", "Deviation Log & Status",
                     "List all deviations in the data with: ID, description, severity (Critical/Major/Minor), "
                     "status (Open/Closed/Under Review), responsible person, and days open. "
                     "Present as a structured table narrative.", order=2),
            _section("root_cause_analysis", "Root Cause Analysis",
                     "Group deviations by root cause category (equipment, procedure, human error, etc.). "
                     "Include frequencies and patterns observed.", order=3),
            _section("capa_actions", "CAPA Actions & Timelines",
                     "For each open deviation, list the CAPA action assigned, responsible owner, "
                     "due date, and current status. Flag any overdue CAPAs with HIGH urgency.", order=4),
            _section("risk_analysis", "Risk Analysis",
                     "Assess the collective risk from open deviations. Identify top 3 risks by business impact. "
                     "Include likelihood and severity ratings.", order=5),
            _section("recommendations", "Recommendations",
                     "Provide minimum 4 specific, actionable recommendations with owner and target dates. "
                     "Prioritize by urgency (Critical first).", order=6),
            _section("data_coverage", "Data Coverage & Methodology",
                     "State tables queried, date range covered, total records reviewed, and RAG sources referenced.", order=7),
        ],
    },

    # ── Equipment Maintenance & Calibration ──────────────────────────────────
    "maintenance": {
        "client_facing_name": "Equipment Maintenance & Calibration Report",
        "output_title": "Equipment Maintenance & Calibration Report",
        "keywords": ["maintenance", "calibration", "equipment", "service schedule", "overdue maintenance"],
        "tables": [
            {"table": "placeware_equipment_registry", "select": "*", "order": "next_maintenance_date", "limit": 50},
        ],
        "scope_fields": [
            _scope_field("date_from", "Period From", "date", required=True),
            _scope_field("date_to", "Period To", "date", required=True),
            _scope_field("equipment_type", "Equipment Type", "text"),
            _scope_field("location", "Location / Unit", "text"),
            _scope_field("custom_notes", "Additional Context", "text"),
        ],
        "sections": [
            _section("executive_summary", "Executive Summary",
                     "State total equipment count, number due for maintenance, overdue count, "
                     "and calibration compliance %.", order=1),
            _section("equipment_status_table", "Equipment Status Overview",
                     "For each piece of equipment: ID, name, last service date, next service date, "
                     "calibration due, current status (Compliant/Due/Overdue). "
                     "Flag overdue items clearly.", order=2),
            _section("overdue_analysis", "Overdue & At-Risk Equipment",
                     "Analyse all overdue items. State days overdue, risk to operations, "
                     "and regulatory implications under NAFDAC/ISO standards.", order=3),
            _section("maintenance_history", "Maintenance History Summary",
                     "Summarise completed maintenance activities in the period. "
                     "Include technician, work performed, parts replaced.", order=4),
            _section("risk_analysis", "Risk Analysis",
                     "Identify top risks from deferred or overdue maintenance. "
                     "Severity ratings and business impact.", order=5),
            _section("recommendations", "Recommendations",
                     "Minimum 4 specific recommendations: scheduling gaps, vendor contracts, "
                     "calibration SOPs, compliance priority actions.", order=6),
            _section("data_coverage", "Data Coverage & Methodology",
                     "Tables queried, period, total records, RAG references.", order=7),
        ],
    },

    # ── Regulatory Compliance ─────────────────────────────────────────────────
    "compliance": {
        "client_facing_name": "Regulatory Compliance Report",
        "output_title": "Regulatory Compliance Report",
        "keywords": ["compliance", "sop", "nafdac", "qms", "regulatory", "standard operating"],
        "tables": [
            {"table": "placeware_compliance_activities", "select": "*", "order": "due_date", "limit": 50},
        ],
        "scope_fields": [
            _scope_field("date_from", "Period From", "date", required=True),
            _scope_field("date_to", "Period To", "date", required=True),
            _scope_field("standard", "Applicable Standard", "select",
                         options=["All", "NAFDAC", "ISO 9001", "ISO 22000", "GMP", "GDP"]),
            _scope_field("department", "Department", "text"),
            _scope_field("custom_notes", "Context / Notes", "text"),
        ],
        "sections": [
            _section("executive_summary", "Executive Summary",
                     "Overall compliance posture: score (%), overdue activities, "
                     "open deviations, SOP review status.", order=1),
            _section("compliance_activities", "Compliance Activity Status",
                     "List all compliance activities: name, standard, due date, status "
                     "(Completed/Pending/Overdue), owner, days remaining or overdue.", order=2),
            _section("sop_review_status", "SOP Review & Approval Status",
                     "List SOPs due for review, last reviewed date, owner, next review date. "
                     "Flag any expired SOPs.", order=3),
            _section("audit_readiness", "Audit Readiness Assessment",
                     "Assess readiness for upcoming audits. Score per clause/standard area. "
                     "Identify documentation gaps.", order=4),
            _section("risk_analysis", "Compliance Risk Analysis",
                     "Top compliance risks ranked by probability × impact. "
                     "Regulatory penalty exposure where applicable.", order=5),
            _section("recommendations", "Recommendations",
                     "Minimum 4 prioritised actions to close compliance gaps. "
                     "Include deadline, owner, and regulatory reference.", order=6),
            _section("data_coverage", "Data Coverage & Methodology", "", order=7),
        ],
    },

    # ── Audit Intelligence ────────────────────────────────────────────────────
    "audit": {
        "client_facing_name": "Audit Intelligence Report",
        "output_title": "Audit Intelligence Report",
        "keywords": ["audit schedule", "overdue audit", "upcoming audit", "audit calendar", "audit review"],
        "tables": [
            {"table": "audit_schedule", "select": "*", "limit": 50},
        ],
        "scope_fields": [
            _scope_field("date_from", "Schedule From", "date", required=True),
            _scope_field("date_to", "Schedule To", "date", required=True),
            _scope_field("audit_type", "Audit Type", "select",
                         options=["All", "Internal", "External", "Regulatory", "Supplier"]),
            _scope_field("custom_notes", "Context / Notes", "text"),
        ],
        "sections": [
            _section("executive_summary", "Executive Summary",
                     "Total audits scheduled, completed, overdue, upcoming in 30 days.", order=1),
            _section("audit_calendar", "Audit Calendar & Status",
                     "Structured view of all audits: audit ID, type, scope, scheduled date, "
                     "lead auditor, status (Scheduled/Completed/Overdue/Cancelled).", order=2),
            _section("overdue_audits", "Overdue Audits Analysis",
                     "Deep-dive on overdue audits: reason for delay, days overdue, "
                     "risk exposure, remediation plan.", order=3),
            _section("findings_summary", "Past Audit Findings Summary",
                     "Summarise open findings from recent audits. Classification, "
                     "responsible party, target close date.", order=4),
            _section("risk_analysis", "Audit Risk Analysis",
                     "Regulatory and operational risk from audit gaps.", order=5),
            _section("recommendations", "Recommendations",
                     "Actions to close scheduling gaps, resource constraints, "
                     "findings remediation.", order=6),
            _section("data_coverage", "Data Coverage & Methodology", "", order=7),
        ],
    },

    # ── Financial Performance ─────────────────────────────────────────────────
    "financial": {
        "client_facing_name": "Financial Performance Report",
        "output_title": "Financial Performance Report",
        "keywords": ["financial performance", "cashflow", "cash flow", "financial overview", "financial summary"],
        "tables": [
            {"table": "sage_gl_journal_entries", "select": "*", "order": "transaction_date", "limit": 100},
            {"table": "sage_sales_invoices", "select": "*", "order": "invoice_date", "limit": 100},
        ],
        "scope_fields": [
            _scope_field("date_from", "Period From", "date", required=True),
            _scope_field("date_to", "Period To", "date", required=True),
            _scope_field("entity_filter", "Entity / Business Unit", "text"),
            _scope_field("currency", "Currency", "select", options=["NGN", "USD", "GBP", "EUR"]),
            _scope_field("custom_notes", "Context / Notes", "text"),
        ],
        "sections": [
            _section("executive_summary", "Executive Summary",
                     "Total revenue, total expenses, net profit/loss for the period. "
                     "Key financial health indicators.", order=1),
            _section("revenue_analysis", "Revenue Analysis",
                     "Breakdown of revenue by customer, product line, or GL account. "
                     "MoM or YoY comparison if prior period data exists.", order=2),
            _section("expense_analysis", "Expense Analysis",
                     "Cost breakdown by category (COGS, operating, payroll, logistics, compliance). "
                     "Top 5 cost drivers. Cost as % of revenue.", order=3),
            _section("margin_analysis", "Gross & Net Margin Analysis",
                     "Gross margin %, net margin %. Identify margin compression drivers. "
                     "Compare to prior periods if available.", order=4),
            _section("cashflow_overview", "Cash Flow Overview",
                     "Opening balance, inflows, outflows, closing balance. "
                     "Operating vs investing vs financing activities.", order=5),
            _section("risk_analysis", "Financial Risk Analysis",
                     "Top 3 financial risks: liquidity, concentration, FX exposure, credit risk.", order=6),
            _section("recommendations", "Recommendations",
                     "Minimum 4 specific actions: cost reduction, revenue diversification, "
                     "working capital improvement.", order=7),
            _section("data_coverage", "Data Coverage & Methodology", "", order=8),
        ],
    },

    # ── Inventory Status ──────────────────────────────────────────────────────
    "inventory": {
        "client_facing_name": "Inventory Status Report",
        "output_title": "Inventory Status Report",
        "keywords": ["inventory", "stock", "expiry", "stock level", "low stock", "expiring"],
        "tables": [
            {"table": "placeware_inventory_snapshot", "select": "*", "limit": 100},
        ],
        "scope_fields": [
            _scope_field("date_from", "As At Date (From)", "date"),
            _scope_field("date_to", "As At Date (To)", "date", required=True),
            _scope_field("sku_filter", "SKU / Product Filter", "text"),
            _scope_field("warehouse", "Warehouse / Location", "text"),
            _scope_field("low_stock_threshold", "Low Stock Threshold (units)", "number"),
            _scope_field("custom_notes", "Notes", "text"),
        ],
        "sections": [
            _section("executive_summary", "Executive Summary",
                     "Total SKUs, total stock value, low-stock items count, "
                     "expiring within 30/60/90 days.", order=1),
            _section("stock_level_table", "Stock Level Overview",
                     "Per-SKU breakdown: SKU, product name, quantity on hand, "
                     "unit cost, total valuation, status (OK/Low/Critical/Expiring).", order=2),
            _section("low_stock_alert", "Low Stock & Reorder Alerts",
                     "Items below threshold or reorder point. Quantity gap, "
                     "recommended reorder quantity, lead time.", order=3),
            _section("expiry_analysis", "Expiry & Shelf Life Analysis",
                     "Items expiring within 30, 60, and 90 days. "
                     "Estimated value at risk. Disposal or markdown actions.", order=4),
            _section("valuation_summary", "Inventory Valuation Summary",
                     "Total inventory value by category. FIFO or weighted average cost note.", order=5),
            _section("risk_analysis", "Inventory Risk Analysis",
                     "Supply chain risks, dead stock, slow movers.", order=6),
            _section("recommendations", "Recommendations",
                     "Reorder actions, disposal plans, supplier escalation, "
                     "storage optimization.", order=7),
            _section("data_coverage", "Data Coverage & Methodology", "", order=8),
        ],
    },

    # ── Executive Business Health ─────────────────────────────────────────────
    "executive": {
        "client_facing_name": "Executive Business Health Report",
        "output_title": "Executive Business Health Report",
        "keywords": ["executive summary", "board report", "leadership brief", "business health", "kpi overview"],
        "tables": [
            {"table": "crm_sales_pipeline", "select": "*", "order": "created_at", "limit": 50},
            {"table": "placeware_inventory_snapshot", "select": "*", "limit": 50},
            {"table": "placeware_compliance_activities", "select": "*", "order": "due_date", "limit": 30},
            {"table": "sage_payroll_snapshot", "select": "*", "order": "pay_period", "limit": 20},
        ],
        "is_executive": True,
        "scope_fields": [
            _scope_field("date_from", "Period From", "date", required=True),
            _scope_field("date_to", "Period To", "date", required=True),
            _scope_field("audience", "Report Audience", "select",
                         options=["Board", "C-Suite", "Management", "Investors"]),
            _scope_field("custom_notes", "Strategic Context / Notes", "text"),
        ],
        "sections": [
            _section("executive_summary", "Executive Summary",
                     "3–4 sentence business health overview: revenue trajectory, "
                     "operational status, compliance posture, strategic headline.", order=1),
            _section("financial_kpis", "Financial KPIs",
                     "Key financial metrics: revenue, gross margin, cash position, "
                     "outstanding receivables, payroll cost. MoM change where available.", order=2),
            _section("sales_pipeline", "Sales & Commercial Performance",
                     "Pipeline value, conversion rate, top deals, CRM activity. "
                     "Revenue vs target.", order=3),
            _section("operations_overview", "Operations & Inventory",
                     "Stock value, low-stock alerts, logistics performance, "
                     "supplier status.", order=4),
            _section("compliance_snapshot", "Compliance & Quality Snapshot",
                     "Compliance score, open deviations, overdue activities, "
                     "audit readiness status.", order=5),
            _section("workforce_snapshot", "Workforce & HR Snapshot",
                     "Headcount, payroll run status, absence rate, "
                     "key HR actions.", order=6),
            _section("risk_dashboard", "Risk Dashboard",
                     "Top 5 business risks across all domains. "
                     "Severity matrix: Financial | Operational | Compliance | Reputational.", order=7),
            _section("strategic_recommendations", "Strategic Recommendations",
                     "Minimum 4 board-level recommendations with priority, "
                     "owner and 30/60/90-day timeline.", order=8),
            _section("data_coverage", "Data Coverage & Methodology", "", order=9),
        ],
    },

    # ── Sales & Pipeline ──────────────────────────────────────────────────────
    "sales": {
        "client_facing_name": "Sales & Pipeline Performance Report",
        "output_title": "Sales & Pipeline Performance Report",
        "keywords": [
            "sales report", "weekly sales", "pipeline report", "crm report", "lead report",
            "sales performance", "revenue report", "sales summary", "sales activity",
        ],
        "tables": [
            {"table": "crm_sales_pipeline", "select": "*", "order": "created_at", "limit": 100},
            {"table": "crm_lead_activity_log", "select": "*", "order": "created_at", "limit": 50},
        ],
        "scope_fields": [
            _scope_field("date_from", "Period From", "date", required=True),
            _scope_field("date_to", "Period To", "date", required=True),
            _scope_field("sales_rep", "Sales Representative", "text"),
            _scope_field("region", "Region / Territory", "text"),
            _scope_field("custom_notes", "Notes", "text"),
        ],
        "sections": [
            _section("executive_summary", "Executive Summary",
                     "Total pipeline value, deals closed, revenue achieved vs target, "
                     "conversion rate.", order=1),
            _section("pipeline_breakdown", "Pipeline Breakdown",
                     "Deals by stage: Prospecting → Qualified → Proposal → Negotiation → Won/Lost. "
                     "Value per stage, avg deal size, days in stage.", order=2),
            _section("closed_deals", "Closed & Won Deals",
                     "List of won deals: client, value, rep, close date, product. "
                     "Total closed revenue.", order=3),
            _section("lost_analysis", "Lost Deals Analysis",
                     "Deals lost: reasons, competitor, stage at loss. "
                     "Win/loss ratio.", order=4),
            _section("lead_activity", "Lead Activity & CRM Engagement",
                     "Calls made, emails sent, meetings held, follow-ups due. "
                     "Activity per rep.", order=5),
            _section("risk_analysis", "Sales Risk Analysis",
                     "Pipeline risks: stale deals, dependencies on few clients, "
                     "seasonality.", order=6),
            _section("recommendations", "Recommendations",
                     "Actions to improve conversion, pipeline health, "
                     "team performance.", order=7),
            _section("data_coverage", "Data Coverage & Methodology", "", order=8),
        ],
    },

    # ── Payroll & HR Summary ──────────────────────────────────────────────────
    "payroll": {
        "client_facing_name": "Payroll & HR Summary Report",
        "output_title": "Payroll & HR Summary Report",
        "keywords": [
            "payroll", "salary", "hr report", "compensation", "payroll report",
            "staff payroll", "payroll summary", "wages", "staff salary",
        ],
        "tables": [
            {"table": "sage_payroll_snapshot", "select": "*", "order": "pay_period", "limit": 50},
            {"table": "sage_hr_absences", "select": "*", "order": "absence_date", "limit": 50},
        ],
        "scope_fields": [
            _scope_field("date_from", "Pay Period From", "date", required=True),
            _scope_field("date_to", "Pay Period To", "date", required=True),
            _scope_field("department", "Department", "text"),
            _scope_field("custom_notes", "Notes", "text"),
        ],
        "sections": [
            _section("executive_summary", "Executive Summary",
                     "Total payroll cost, headcount paid, average salary, "
                     "total absence days, payroll vs budget.", order=1),
            _section("payroll_breakdown", "Payroll Breakdown",
                     "Per-department: headcount, gross pay, deductions, net pay. "
                     "Top 5 salary cost centres.", order=2),
            _section("individual_summary", "Individual Earnings Summary",
                     "Staff earnings table: name, department, basic, allowances, "
                     "deductions, net. Anonymised for board reports.", order=3),
            _section("absence_analysis", "Absence & Leave Analysis",
                     "Absence by type (sick, annual, maternity/paternity, unpaid). "
                     "Department with highest absence rate. Impact on productivity.", order=4),
            _section("payroll_variance", "Payroll Variance Analysis",
                     "MoM change in total payroll. Drivers of increase or decrease.", order=5),
            _section("risk_analysis", "HR Risk Analysis",
                     "Key workforce risks: turnover, absence trends, salary equity.", order=6),
            _section("recommendations", "Recommendations",
                     "Actions on payroll efficiency, absence management, "
                     "compliance with labour law.", order=7),
            _section("data_coverage", "Data Coverage & Methodology", "", order=8),
        ],
    },

    # ── Profit & Loss ─────────────────────────────────────────────────────────
    "pl": {
        "client_facing_name": "Profit & Loss Report",
        "output_title": "Profit & Loss Report",
        "keywords": [
            "p&l", "profit and loss", "income statement", "pl report", "profit loss",
            "net income", "profit & loss", "loss statement",
        ],
        "tables": [
            {"table": "sage_gl_journal_entries", "select": "*", "order": "transaction_date", "limit": 100},
            {"table": "sage_sales_invoices", "select": "*", "order": "invoice_date", "limit": 100},
        ],
        "scope_fields": [
            _scope_field("date_from", "Period From", "date", required=True),
            _scope_field("date_to", "Period To", "date", required=True),
            _scope_field("currency", "Currency", "select", options=["NGN", "USD", "GBP", "EUR"]),
            _scope_field("compare_period", "Comparison Period", "select",
                         options=["None", "Prior Month", "Prior Quarter", "Prior Year"]),
            _scope_field("custom_notes", "Notes", "text"),
        ],
        "sections": [
            _section("executive_summary", "Executive Summary",
                     "Net profit or loss for the period. Key driver. "
                     "Comparison to prior period if available.", order=1),
            _section("income_statement", "Income Statement",
                     "Revenue | COGS | Gross Profit | Operating Expenses | EBIT | "
                     "Interest | Tax | Net Profit. Use actual GL figures.", order=2),
            _section("revenue_detail", "Revenue Detail",
                     "Revenue breakdown by account, customer class, or product line. "
                     "MoM or YoY variance.", order=3),
            _section("cogs_analysis", "Cost of Goods Sold Analysis",
                     "COGS breakdown, gross margin %, product margin comparison.", order=4),
            _section("opex_detail", "Operating Expense Detail",
                     "All operating expenses by GL account and category. "
                     "Flagging unusually high items.", order=5),
            _section("risk_analysis", "Financial Risk Analysis",
                     "Margin compression risks, cost overruns, revenue concentration.", order=6),
            _section("recommendations", "Recommendations",
                     "Actionable P&L improvement recommendations.", order=7),
            _section("data_coverage", "Data Coverage & Methodology", "", order=8),
        ],
    },

    # ── Accounts Receivable Aging ─────────────────────────────────────────────
    "ar_aging": {
        "client_facing_name": "Accounts Receivable Aging Report",
        "output_title": "Accounts Receivable Aging Report",
        "keywords": [
            "ar aging", "accounts receivable", "outstanding invoices", "aging report",
            "overdue payments", "receivables", "ar report", "accounts receivable aging",
        ],
        "tables": [
            {"table": "sage_sales_invoices", "select": "*", "order": "invoice_date", "limit": 100},
            {"table": "sage_customers", "select": "*", "limit": 50},
        ],
        "scope_fields": [
            _scope_field("date_from", "As At Date (From)", "date"),
            _scope_field("date_to", "As At Date (To)", "date", required=True),
            _scope_field("customer_filter", "Customer / Account", "text"),
            _scope_field("currency", "Currency", "select", options=["NGN", "USD", "GBP", "EUR"]),
            _scope_field("custom_notes", "Notes", "text"),
        ],
        "sections": [
            _section("executive_summary", "Executive Summary",
                     "Total receivables outstanding, % overdue, largest debtor, "
                     "estimated bad debt exposure.", order=1),
            _section("aging_buckets", "Aging Buckets Analysis",
                     "Structured aging: Current | 1–30 Days | 31–60 Days | 61–90 Days | 90+ Days. "
                     "Value and % of total for each bucket.", order=2),
            _section("customer_breakdown", "Customer-Level Breakdown",
                     "Top 10 debtors: customer name, total outstanding, "
                     "oldest invoice date, last payment date.", order=3),
            _section("collection_status", "Collection Status & Activity",
                     "Collection actions taken: calls, emails, disputes raised. "
                     "Promised payment dates.", order=4),
            _section("bad_debt_risk", "Bad Debt Risk Assessment",
                     "Accounts likely uncollectable: criteria, value, "
                     "recommended provisioning.", order=5),
            _section("recommendations", "Recommendations",
                     "Credit control actions: dunning schedules, credit limit reviews, "
                     "legal action thresholds.", order=6),
            _section("data_coverage", "Data Coverage & Methodology", "", order=7),
        ],
    },

    # ── Frontdesk & Daily Operations ──────────────────────────────────────────
    "frontdesk": {
        "client_facing_name": "Frontdesk & Daily Operations Report",
        "output_title": "Frontdesk & Daily Operations Report",
        "keywords": [
            "frontdesk report", "daily report", "reception report", "walk-in summary",
            "daily operations", "frontdesk summary", "daily frontdesk", "front desk report",
        ],
        "tables": [
            {"table": "placeware_walk_ins", "select": "*", "order": "created_at", "limit": 100},
            {"table": "placeware_invoices", "select": "*", "order": "created_at", "limit": 50},
        ],
        "scope_fields": [
            _scope_field("date_from", "Day / Period From", "date", required=True),
            _scope_field("date_to", "Day / Period To", "date", required=True),
            _scope_field("staff_member", "Staff Member on Duty", "text"),
            _scope_field("custom_notes", "Notes / Incidents", "text"),
        ],
        "sections": [
            _section("executive_summary", "Daily Summary",
                     "Total walk-ins, total invoices raised, total revenue collected, "
                     "outstanding issues.", order=1),
            _section("walk_in_log", "Walk-In Log",
                     "Each visitor: time, purpose, product/service requested, "
                     "outcome (sold/inquiry/complaint/referred).", order=2),
            _section("sales_activity", "Sales & Invoice Activity",
                     "Invoices raised: customer, amount, product, payment status. "
                     "Total daily sales.", order=3),
            _section("incidents_issues", "Incidents & Issues",
                     "Any complaints, stockouts, escalations, or unusual events "
                     "during the period.", order=4),
            _section("recommendations", "Recommendations & Actions",
                     "Follow-up actions required for leads, complaints, "
                     "or unresolved inquiries.", order=5),
            _section("data_coverage", "Data Coverage", "", order=6),
        ],
    },

    # ── Invoice ───────────────────────────────────────────────────────────────
    "invoice": {
        "client_facing_name": "Client Invoice",
        "output_title": "TAX INVOICE",
        "keywords": [
            "invoice", "generate invoice", "client invoice", "billing",
            "proforma invoice", "proforma", "invoice generation",
        ],
        "tables": [
            {"table": "sage_sales_invoices", "select": "*", "order": "invoice_date", "limit": 10},
            {"table": "sage_customers", "select": "*", "limit": 50},
        ],
        "scope_fields": [
            _scope_field("client_name", "Client / Company Name", "text", required=True),
            _scope_field("client_address", "Client Address", "text", required=True),
            _scope_field("client_email", "Client Email", "text"),
            _scope_field("invoice_date", "Invoice Date", "date", required=True),
            _scope_field("due_date", "Payment Due Date", "date", required=True),
            _scope_field("line_items", "Line Items", "line_items", required=True),
            _scope_field("currency", "Currency", "select",
                         options=["NGN", "USD", "GBP", "EUR"], required=True),
            _scope_field("vat_rate", "VAT Rate (%)", "number"),
            _scope_field("payment_terms", "Payment Terms", "text"),
            _scope_field("bank_details", "Bank Account Details", "text"),
            _scope_field("custom_notes", "Additional Notes / Terms", "text"),
        ],
        # Invoice uses a different rendering path (InvoiceDocxBuilder)
        # but sections define the LLM-generated service description text
        "sections": [
            _section("service_description", "Service Description",
                     "Write a professional 2–3 sentence description of the services rendered, "
                     "suitable for an enterprise client invoice. "
                     "Base it on the line items provided.", required=False, order=1),
        ],
        "is_invoice": True,
    },
}

# ── Helper functions ────────────────────────────────────────────────────────────

def get_template(report_type: str) -> Dict[str, Any]:
    """Return the template for a report type, falling back to 'executive'."""
    return REPORT_TEMPLATE_REGISTRY.get(report_type, REPORT_TEMPLATE_REGISTRY["executive"])


def get_required_scope_fields(report_type: str) -> List[Dict[str, Any]]:
    """Return only the required scope fields for the given report type."""
    template = get_template(report_type)
    return [f for f in template.get("scope_fields", []) if f.get("required")]


def get_all_report_types() -> List[Dict[str, str]]:
    """Return a list of {type, client_facing_name} for all registered report types."""
    return [
        {"type": rtype, "name": cfg["client_facing_name"]}
        for rtype, cfg in REPORT_TEMPLATE_REGISTRY.items()
    ]


def detect_report_type(text: str) -> str:
    """
    Detect report type from natural language text using keyword matching.
    Returns report_type key. Defaults to 'executive' if no match found.
    """
    text_lower = text.lower()
    # Invoice check first (most specific)
    for rtype, cfg in REPORT_TEMPLATE_REGISTRY.items():
        if any(kw in text_lower for kw in cfg.get("keywords", [])):
            return rtype
    return "executive"


# ── Invoice section ordering (for DOCX renderer) ──────────────────────────────
INVOICE_SECTION_ORDER = [
    "client_details",
    "service_description",
    "line_items_table",
    "totals",
    "payment_terms",
    "bank_details",
    "terms_conditions",
]
