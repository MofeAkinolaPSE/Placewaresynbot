"""
Standard Workflow Registrations
Implements the structured workflow automations from Agent_stack.md
"""
from __future__ import annotations
import logging
from typing import Any, Dict

from src.workflow.engine import WorkflowEngine, WorkflowContext
from src.workflow.batch_locking import lock_batch, auto_release_batch
from src.workflow.expiry_prevention import create_promotion
from src.workflow.credit_risk import apply_credit_action
from src.workflow.replenishment_actions import mark_replenishment_received
from src.db import db, audit_event

logger = logging.getLogger(__name__)


def register_standard_workflows(engine: WorkflowEngine) -> None:
    """Register all standard workflows with the workflow engine."""
    
    # ==========================================
    # COMPLIANCE WORKFLOWS
    # ==========================================
    
    def compliance_lock_batch(ctx: WorkflowContext) -> Dict[str, Any]:
        """Lock a batch due to compliance issues (temp violation, NAFDAC pending, etc.)"""
        batch_id = ctx.payload.get("batch_id")
        reason = ctx.payload.get("reason", "compliance_issue")
        
        if not batch_id:
            return {"error": "batch_id required"}
        
        try:
            result = lock_batch(batch_id, reason)
            logger.info(f"Batch {batch_id} locked due to {reason}")
            
            audit_event(
                "batch_locked",
                {"batch_id": batch_id, "reason": reason},
                actor_id=None,
                event_class="compliance",
                action="lock_batch",
                outcome="success",
                subject_type="batch",
                subject_id=batch_id,
            )
            
            return {"success": True, "batch_id": batch_id, "locked": True}
        except Exception as e:
            logger.error(f"Failed to lock batch {batch_id}: {e}")
            return {"error": str(e)}
    
    engine.register("compliance.lock_batch", [compliance_lock_batch])

    def compliance_auto_release(ctx: WorkflowContext) -> Dict[str, Any]:
        """Auto-release a compliance-locked batch when approval is received."""
        batch_id = ctx.payload.get("batch_id")
        actor = ctx.payload.get("actor")
        if not batch_id:
            return {"error": "batch_id required"}
        try:
            result = auto_release_batch(str(batch_id), actor=str(actor) if actor else None)
            if not result.get("ok"):
                return result
            logger.info(f"Auto-released batch {batch_id} after approval")
            return {"success": True, "batch_id": batch_id, "released": True}
        except Exception as e:
            logger.error(f"Failed to auto-release batch {batch_id}: {e}")
            return {"error": str(e)}

    engine.register("compliance.auto_release", [compliance_auto_release])
    
    # ==========================================
    # PROCUREMENT WORKFLOWS
    # ==========================================
    
    def procurement_escalate_clearance(ctx: WorkflowContext) -> Dict[str, Any]:
        """Escalate a stuck shipment to regulatory team."""
        shipment_id = ctx.payload.get("shipment_id")
        reason = ctx.payload.get("reason", "clearance_delay")
        
        if not shipment_id:
            return {"error": "shipment_id required"}
        
        try:
            # Create escalation alert
            db.table("placeware_clearance_alerts").insert({
                "shipment_id": shipment_id,
                "alert_type": "escalation",
                "notes": f"Auto-escalated: {reason}",
            }).execute()
            
            # Create task for regulatory team
            db.table("placeware_tasks").insert({
                "title": f"Clearance Escalation: Shipment {shipment_id[:8]}",
                "description": f"Shipment stuck in clearance. Reason: {reason}",
                "status": "pending",
                "priority": "high",
                "source": "workflow",
                "assigned_to": "role:regulatory",
            }).execute()
            
            logger.info(f"Escalated shipment {shipment_id} for reason: {reason}")
            return {"success": True, "shipment_id": shipment_id, "escalated": True}
        except Exception as e:
            logger.error(f"Failed to escalate shipment {shipment_id}: {e}")
            return {"error": str(e)}
    
    engine.register("procurement.escalate_clearance", [procurement_escalate_clearance])
    
    # ==========================================
    # INVENTORY WORKFLOWS  
    # ==========================================
    
    def inventory_create_replenishment(ctx: WorkflowContext) -> Dict[str, Any]:
        """Create a replenishment request for low stock items."""
        sku = ctx.payload.get("sku")
        current_qty = ctx.payload.get("current_qty", 0)
        reorder_qty = ctx.payload.get("reorder_qty", 100)
        
        if not sku:
            return {"error": "sku required"}
        
        try:
            db.table("replenishment_requests").insert({
                "sku": sku,
                "requested_qty": reorder_qty,
                "status": "recommended",
                "created_by": "workflow",
                "notes": f"Auto-generated from low stock workflow. current_qty={current_qty}",
            }).execute()
            
            logger.info(f"Created replenishment request for SKU {sku}")
            return {"success": True, "sku": sku, "requested_qty": reorder_qty}
        except Exception as e:
            logger.error(f"Failed to create replenishment for {sku}: {e}")
            return {"error": str(e)}
    
    engine.register("inventory.create_replenishment", [inventory_create_replenishment])

    def inventory_stock_received(ctx: WorkflowContext) -> Dict[str, Any]:
        """Complete replenishment lifecycle: ordered -> received and clear low-stock alert context."""
        request_id = ctx.payload.get("request_id")
        received_qty = ctx.payload.get("received_qty")
        actor = ctx.payload.get("actor") or "workflow"

        if not request_id:
            return {"error": "request_id required"}

        try:
            result = mark_replenishment_received(
                request_id=str(request_id),
                received_qty=float(received_qty) if received_qty is not None else None,
                actor=str(actor),
            )
            if not result.get("ok"):
                return result
            logger.info(f"Marked replenishment request {request_id} as received")
            return {"success": True, **result}
        except Exception as e:
            logger.error(f"Failed to mark replenishment request received {request_id}: {e}")
            return {"error": str(e)}

    engine.register("inventory.stock_received", [inventory_stock_received])
    
    def inventory_expiry_promotion(ctx: WorkflowContext) -> Dict[str, Any]:
        """Create a promotion for near-expiry items."""
        sku = ctx.payload.get("sku")
        batch_id = ctx.payload.get("batch_id")
        expiry_date = ctx.payload.get("expiry_date")
        days_to_expiry = ctx.payload.get("days_to_expiry", 60)
        discount_pct = ctx.payload.get("discount_pct", 15.0)
        
        if not sku:
            return {"error": "sku required"}
        
        try:
            result = create_promotion(
                sku=sku,
                batch_id=batch_id,
                qty=ctx.payload.get("qty", 0),
                discount_pct=discount_pct,
                created_by="workflow",
            )
            
            # Notify sales team
            db.table("placeware_tasks").insert({
                "title": f"Expiry Promotion: {sku}",
                "description": f"Item expires in {days_to_expiry} days. Promotion created with {discount_pct}% discount.",
                "status": "pending",
                "priority": "medium",
                "source": "workflow",
                "assigned_to": "role:sales",
            }).execute()
            
            logger.info(f"Created expiry promotion for SKU {sku}")
            return {"success": True, "sku": sku, "discount_pct": discount_pct}
        except Exception as e:
            logger.error(f"Failed to create promotion for {sku}: {e}")
            return {"error": str(e)}
    
    engine.register("inventory.expiry_promotion", [inventory_expiry_promotion])
    
    # ==========================================
    # COLD CHAIN WORKFLOWS
    # ==========================================
    
    def cold_chain_quarantine_batch(ctx: WorkflowContext) -> Dict[str, Any]:
        """Quarantine a batch due to temperature violation."""
        batch_id = ctx.payload.get("batch_id")
        sensor_id = ctx.payload.get("sensor_id")
        temperature_c = ctx.payload.get("temperature_c")
        
        if not batch_id:
            return {"error": "batch_id required"}
        
        try:
            # Lock the batch
            lock_batch(batch_id, "temperature_violation")
            
            # Create capacity alert
            db.table("placeware_capacity_alerts").insert({
                "zone_id": ctx.payload.get("zone_id"),
                "alert_type": "temperature_violation",
                "temperature_c": temperature_c,
                "notes": f"Sensor {sensor_id} reported {temperature_c}°C",
            }).execute()
            
            # Create QC task
            db.table("placeware_tasks").insert({
                "title": f"QC Review: Batch {batch_id[:8]} Temp Violation",
                "description": f"Temperature violation detected: {temperature_c}°C. Review batch integrity.",
                "status": "pending",
                "priority": "urgent",
                "source": "workflow",
                "assigned_to": "role:qc",
            }).execute()
            
            logger.info(f"Quarantined batch {batch_id} due to temp violation")
            return {"success": True, "batch_id": batch_id, "quarantined": True}
        except Exception as e:
            logger.error(f"Failed to quarantine batch {batch_id}: {e}")
            return {"error": str(e)}
    
    engine.register("cold_chain.quarantine_batch", [cold_chain_quarantine_batch])
    
    # ==========================================
    # FINANCE WORKFLOWS
    # ==========================================
    
    def finance_flag_credit_risk(ctx: WorkflowContext) -> Dict[str, Any]:
        """Flag a customer as credit risk due to overdue AR."""
        customer_id = ctx.payload.get("customer_id")
        days_overdue = ctx.payload.get("days_overdue", 0)
        amount_overdue = ctx.payload.get("amount_overdue", 0)
        
        if not customer_id:
            return {"error": "customer_id required"}
        
        try:
            # Apply credit action
            action = "reduce_limit" if days_overdue > 60 else "flag"
            apply_credit_action(customer_id, action)
            
            # Create executive notification
            db.table("placeware_tasks").insert({
                "title": f"Credit Risk: Customer {customer_id[:8]}",
                "description": f"Customer overdue {days_overdue} days. Outstanding: {amount_overdue}.",
                "status": "pending",
                "priority": "high" if days_overdue > 90 else "medium",
                "source": "workflow",
                "assigned_to": "role:finance",
            }).execute()
            
            audit_event(
                "customer_credit_flagged",
                {"customer_id": customer_id, "days_overdue": days_overdue, "action": action},
                actor_id=None,
                event_class="finance",
                action="flag_credit",
                outcome="success",
                subject_type="customer",
                subject_id=customer_id,
            )
            
            logger.info(f"Flagged customer {customer_id} as credit risk")
            return {"success": True, "customer_id": customer_id, "action": action}
        except Exception as e:
            logger.error(f"Failed to flag customer {customer_id}: {e}")
            return {"error": str(e)}
    
    engine.register("finance.flag_credit_risk", [finance_flag_credit_risk])
    
    # ==========================================
    # LOGISTICS WORKFLOWS
    # ==========================================
    
    def logistics_delivery_breach(ctx: WorkflowContext) -> Dict[str, Any]:
        """Handle delivery SLA breach."""
        delivery_id = ctx.payload.get("delivery_id")
        customer_id = ctx.payload.get("customer_id")
        delay_hours = ctx.payload.get("delay_hours", 0)
        
        if not delivery_id:
            return {"error": "delivery_id required"}
        
        try:
            # Log SLA breach
            db.table("placeware_tasks").insert({
                "title": f"SLA Breach: Delivery {delivery_id[:8]}",
                "description": f"Delivery delayed by {delay_hours} hours. Customer {customer_id} affected.",
                "status": "pending",
                "priority": "high",
                "source": "workflow",
                "assigned_to": "role:logistics",
            }).execute()
            
            logger.info(f"Logged SLA breach for delivery {delivery_id}")
            return {"success": True, "delivery_id": delivery_id, "breach_logged": True}
        except Exception as e:
            logger.error(f"Failed to log SLA breach for {delivery_id}: {e}")
            return {"error": str(e)}
    
    engine.register("logistics.delivery_breach", [logistics_delivery_breach])
    
    logger.info("Registered 7 standard workflows")


# Auto-register on import if engine is available
def setup_workflows() -> WorkflowEngine:
    """Create and configure a workflow engine with all standard workflows."""
    engine = WorkflowEngine()
    register_standard_workflows(engine)
    return engine
