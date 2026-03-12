"""Simple agent router and registry helpers.

This module provides lightweight functions to register agents and dispatch
tasks to agents. In production this would be a robust queue or RPC system.
"""
from typing import Any, Dict, List, Optional
import logging
import src.db as db

logger = logging.getLogger(__name__)


# Trigger context mapping - maps event types to agents with context
TRIGGER_CONTEXT_MAP: Dict[str, Dict[str, Any]] = {
    # Inventory triggers
    "low_stock": {
        "agent": "inventory_agent",
        "action": "check_stock",
        "context_keys": ["sku", "current_qty", "threshold"],
        "priority": "high",
        "workflow": "replenishment.create",
    },
    "stock_expiring": {
        "agent": "inventory_agent",
        "action": "expiry_check",
        "context_keys": ["sku", "batch_id", "expiry_date", "days_until_expiry"],
        "priority": "high",
        "workflow": "expiry_promotion.create",
    },
    "stock_movement": {
        "agent": "inventory_agent",
        "action": "track_movement",
        "context_keys": ["sku", "qty", "movement_type", "source", "destination"],
        "priority": "medium",
    },
    
    # Financial triggers
    "ar_aging_critical": {
        "agent": "financial_agent",
        "action": "ar_review",
        "context_keys": ["customer_id", "amount", "days_overdue"],
        "priority": "critical",
        "workflow": "credit_risk.flag",
    },
    "payment_received": {
        "agent": "financial_agent",
        "action": "record_payment",
        "context_keys": ["customer_id", "amount", "invoice_id"],
        "priority": "medium",
    },
    "budget_variance": {
        "agent": "financial_agent",
        "action": "analyze_variance",
        "context_keys": ["department", "budget", "actual", "variance_pct"],
        "priority": "medium",
    },
    
    # Compliance triggers
    "compliance_violation": {
        "agent": "compliance_agent",
        "action": "investigate",
        "context_keys": ["violation_type", "severity", "entity_id", "details"],
        "priority": "critical",
        "workflow": "compliance.investigate",
    },
    "audit_required": {
        "agent": "compliance_agent",
        "action": "schedule_audit",
        "context_keys": ["audit_type", "scope", "deadline"],
        "priority": "high",
    },
    
    # Logistics triggers
    "shipment_delayed": {
        "agent": "logistics_agent",
        "action": "track_delay",
        "context_keys": ["shipment_id", "expected_date", "current_status"],
        "priority": "high",
    },
    "capacity_warning": {
        "agent": "logistics_agent",
        "action": "capacity_check",
        "context_keys": ["warehouse_id", "current_capacity", "threshold"],
        "priority": "medium",
    },
    
    # CRM triggers
    "customer_complaint": {
        "agent": "crm_agent",
        "action": "handle_complaint",
        "context_keys": ["customer_id", "complaint_type", "severity"],
        "priority": "high",
    },
    "lead_created": {
        "agent": "crm_agent",
        "action": "qualify_lead",
        "context_keys": ["lead_id", "source", "company_name"],
        "priority": "medium",
    },
    
    # Cold chain triggers
    "temperature_alert": {
        "agent": "cold_chain_agent",
        "action": "temperature_alert",
        "context_keys": ["location_id", "temperature", "threshold", "product_ids"],
        "priority": "critical",
    },
    
    # Risk triggers
    "risk_detected": {
        "agent": "enterprise_risk_agent",
        "action": "assess_risk",
        "context_keys": ["risk_type", "severity", "affected_areas"],
        "priority": "high",
    },
}


def get_trigger_context(event_type: str) -> Optional[Dict[str, Any]]:
    """Get the trigger context mapping for an event type."""
    return TRIGGER_CONTEXT_MAP.get(event_type)


def dispatch_event(event_type: str, payload: Dict[str, Any]) -> Optional[str]:
    """
    Dispatch an event to the appropriate agent based on trigger context.
    
    Args:
        event_type: The type of event (e.g., "low_stock", "ar_aging_critical")
        payload: Event payload with context data
    
    Returns:
        Task ID if dispatched successfully, None otherwise
    """
    context = get_trigger_context(event_type)
    
    if not context:
        logger.warning(f"No trigger context for event type: {event_type}")
        return None
    
    agent = context.get("agent")
    action = context.get("action")
    priority = context.get("priority", "medium")
    workflow = context.get("workflow")
    
    # Build task with context keys
    task_payload = {
        "action": action,
        "event_type": event_type,
        "priority": priority,
        **{k: payload.get(k) for k in context.get("context_keys", []) if k in payload},
    }
    
    if workflow:
        task_payload["workflow"] = workflow
    
    logger.info(f"Dispatching {event_type} to {agent}: {action} (priority={priority})")
    return send_task(agent, task_payload)


def register_agent(agent_name: str, event_types: list[str], rpc_endpoint: Optional[str] = None):
    try:
        now = None
        db.table('agent_registry').upsert({'agent_name': agent_name, 'description': '', 'event_types': event_types, 'rpc_endpoint': rpc_endpoint, 'enabled': True}).execute()
    except Exception:
        logger.exception('Failed registering agent %s', agent_name)


def list_agents():
    try:
        res = db.table('agent_registry').select('*').execute()
        return res.data or []
    except Exception:
        logger.exception('Failed listing agents')
        return []


def send_task(agent_name: str, task_payload: Dict[str, Any]) -> Optional[str]:
    """Dispatch a task to an agent by writing a row into `executive_action_log` or returning a task id.

    This is a placeholder implementation: real systems should use durable queues.
    """
    try:
        row = {'executive_id': None, 'intent': None, 'tasks': task_payload, 'actions': None, 'simulation': False}
        res = db.table('executive_action_log').insert(row).execute()
        if res and getattr(res, 'data', None):
            return res.data[0].get('id')
    except Exception:
        logger.exception('Failed sending task to agent %s', agent_name)
    return None
