"""The access roles people can be given on User Access - one list, used by login
(ALLOWED_ROLES), the User Access page (what to offer and what each opens) and HR
(the department a new person starts in).

A person can hold more than one role (e.g. frontdesk + sales). The pages each role
opens are enforced by the sidebar / route gates in the frontend and by each API's
own role check in the backend; this file describes them for the people assigning.
"""
from __future__ import annotations

from typing import Any, Dict, List

ROLE_CATALOG: List[Dict[str, Any]] = [
    {"key": "frontdesk", "label": "Frontdesk", "department": "Frontdesk",
     "about": "Registers walk-ins and customer requests, checks stock availability and follows each request through QC, finance and dispatch."},
    {"key": "sales", "label": "Sales", "department": "Sales",
     "about": "CRM: customers, pipeline, leads and prospecting, reminders, weekly report; Frontdesk; stock availability."},
    {"key": "finance", "label": "Finance", "department": "Finance",
     "about": "ACE Books (invoices, receipts, bills, banking, statements, close), credit control, credit limits, Executive Overview."},
    {"key": "ops", "label": "Operations", "department": "Operations",
     "about": "Operations overview, project controls, stock orders, suppliers, logistics; stock and compliance scheduling."},
    {"key": "procurement", "label": "Procurement", "department": "Procurement",
     "about": "Stock orders and purchases (reorder plan, raise / approve / order), suppliers, stock levels."},
    {"key": "quality_assurance", "label": "Quality (QA / QC)", "department": "Quality",
     "about": "Batch release, recalls, expiry, deviations and CAPA, audits, maintenance, compliance & QMS."},
    {"key": "hr", "label": "HR", "department": "HR",
     "about": "HR overview (who is in, hours), staff directory, timesheet approval, escalation rules."},
    {"key": "management", "label": "Management (CEO / CFO)", "department": "Management",
     "about": "Executive Overview, ACE Books, HR (view), operations, quality and CRM - everything except system administration."},
    {"key": "admin", "label": "Admin", "department": "Admin",
     "about": "Everything, including User Access, workflow and settings."},
    {"key": "viewer", "label": "Viewer", "department": "Operations",
     "about": "Own workspace (tasks, clock, messages) and the general dashboard only."},
]

# accepted at login for accounts created before the catalogue (not offered for new accounts)
LEGACY_ALIASES = {"qa"}

ALLOWED_ROLES = {r["key"] for r in ROLE_CATALOG} | LEGACY_ALIASES
