"""
Automated Workflow Scheduler
Implements scheduled triggers for workflow automation loops.
Runs periodic checks and triggers appropriate workflows.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from src.db import db
from src.workflow.batch_locking import lock_batch, is_batch_locked
from src.workflow.expiry_prevention import create_promotion
from src.workflow.credit_risk import apply_credit_action, is_customer_flagged

logger = logging.getLogger(__name__)

# Configuration for automation thresholds
AUTOMATION_CONFIG = {
    "low_stock_threshold": 10,  # Trigger replenishment below this qty
    "expiry_warning_days": 30,  # Create promotion if expiring within X days
    "auto_promotion_discount": 15.0,  # Default discount % for expiry promotions
    "ar_aging_critical_days": 90,  # Flag customer if AR > X days
    "ar_aging_warning_days": 60,  # Warn if AR > X days
    "scheduler_interval_minutes": 5,  # How often to run checks
}


class WorkflowAutomation:
    """
    Automated workflow triggers that detect conditions and initiate actions.
    """

    def __init__(self):
        self._running = False
        self._task: Optional[asyncio.Task] = None

    async def start(self):
        """Start the automation scheduler."""
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._run_loop())
        logger.info("Workflow automation scheduler started")

    async def stop(self):
        """Stop the automation scheduler."""
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("Workflow automation scheduler stopped")

    async def _run_loop(self):
        """Main scheduler loop."""
        interval = AUTOMATION_CONFIG["scheduler_interval_minutes"] * 60
        while self._running:
            try:
                await self._run_all_checks()
            except Exception as e:
                logger.exception(f"Automation check failed: {e}")
            await asyncio.sleep(interval)

    async def _run_all_checks(self):
        """Run all automation checks."""
        logger.debug("Running workflow automation checks...")
        
        # 1. Check for low stock and trigger replenishment
        await self._check_low_stock()
        
        # 2. Check for near-expiry items and create promotions
        await self._check_expiry_prevention()
        
        # 3. Check for AR aging and flag credit risks
        await self._check_credit_risk()
        
        logger.debug("Workflow automation checks completed")

    async def _check_low_stock(self):
        """
        Check for low stock items and trigger replenishment.
        Creates replenishment orders for items below threshold.
        """
        try:
            threshold = AUTOMATION_CONFIG["low_stock_threshold"]
            
            # Query inventory for low stock items
            result = db.table("placeware_inventory_snapshot").select(
                "sku, current_qty, safety_stock"
            ).lt("current_qty", threshold).execute()
            
            items = result.data if hasattr(result, 'data') else []
            
            for item in items:
                sku = item.get("sku")
                current = item.get("current_qty", 0)
                safety = item.get("safety_stock", threshold * 2)
                
                # Check if already has pending replenishment
                pending = db.table("replenishment_requests").select("id").eq(
                    "sku", sku
                ).eq("status", "recommended").execute()
                
                if pending.data:
                    continue  # Already has pending request
                
                # Calculate reorder quantity
                reorder_qty = max(safety - current, threshold * 2)
                
                # Create replenishment request
                db.table("replenishment_requests").insert({
                    "sku": sku,
                    "requested_qty": reorder_qty,
                    "status": "recommended",
                    "created_by": "auto_low_stock",
                    "notes": f"Auto-generated: stock {current} below threshold {threshold}",
                }).execute()
                
                logger.info(f"Auto-replenishment created: {sku} qty={reorder_qty}")
                
        except Exception as e:
            logger.error(f"Low stock check failed: {e}")

    async def _check_expiry_prevention(self):
        """
        Check for near-expiry items and create discount promotions.
        Locks batches that are expired.
        """
        try:
            warning_days = AUTOMATION_CONFIG["expiry_warning_days"]
            discount = AUTOMATION_CONFIG["auto_promotion_discount"]
            cutoff = (datetime.utcnow() + timedelta(days=warning_days)).isoformat()
            
            # Query inventory for near-expiry items
            result = db.table("placeware_inventory_snapshot").select(
                "sku, batch_id, current_qty, expiry_date"
            ).lt("expiry_date", cutoff).gt("current_qty", 0).execute()
            
            items = result.data if hasattr(result, 'data') else []
            
            for item in items:
                sku = item.get("sku")
                batch_id = item.get("batch_id")
                qty = item.get("current_qty", 0)
                expiry = item.get("expiry_date")
                
                if not expiry:
                    continue
                
                # Parse expiry date
                try:
                    exp_date = datetime.fromisoformat(expiry.replace("Z", "+00:00"))
                except:
                    continue
                
                # If expired, lock the batch
                if exp_date < datetime.utcnow().replace(tzinfo=exp_date.tzinfo):
                    if batch_id and not is_batch_locked(batch_id):
                        lock_batch(batch_id, "Auto-locked: Expired", "system")
                        logger.warning(f"Batch {batch_id} auto-locked due to expiry")
                    continue
                
                # Check if promotion already exists
                existing = db.table("promotions").select("id").eq(
                    "sku", sku
                ).eq("batch_id", batch_id).execute()
                
                if existing.data:
                    continue  # Already has promotion
                
                # Create promotion for near-expiry item
                create_promotion(
                    sku=sku,
                    batch_id=batch_id,
                    qty=qty,
                    discount_pct=discount,
                    created_by="system_auto_expiry"
                )
                
                logger.info(f"Auto-promotion created: {sku} batch={batch_id} discount={discount}%")
                
        except Exception as e:
            logger.error(f"Expiry prevention check failed: {e}")

    async def _check_credit_risk(self):
        """
        Check AR aging and flag credit risk customers.
        Automatically adjusts credit limits for risky customers.
        """
        try:
            critical_days = AUTOMATION_CONFIG["ar_aging_critical_days"]
            warning_days = AUTOMATION_CONFIG["ar_aging_warning_days"]
            
            # Query AR ledger (view joins customer name)
            result = db.table("placeware_ar_ledger").select(
                "customer_id, customer_name, amount, invoice_date"
            ).execute()
            
            rows = result.data if hasattr(result, 'data') else []
            
            # Group by customer
            customer_ar: Dict[str, Dict[str, Any]] = {}
            for row in rows:
                cid = row.get("customer_id")
                if not cid:
                    continue
                if cid not in customer_ar:
                    customer_ar[cid] = {
                        "name": row.get("customer_name"),
                        "total_ar": 0,
                        "oldest_invoice": None,
                        "overdue_days": 0,
                    }
                
                amount = float(row.get("amount", 0))
                customer_ar[cid]["total_ar"] += amount
                
                inv_date = row.get("invoice_date")
                if inv_date:
                    try:
                        inv_dt = datetime.fromisoformat(inv_date.replace("Z", "+00:00"))
                        days_old = (datetime.utcnow().replace(tzinfo=inv_dt.tzinfo) - inv_dt).days
                        if days_old > customer_ar[cid]["overdue_days"]:
                            customer_ar[cid]["overdue_days"] = days_old
                            customer_ar[cid]["oldest_invoice"] = inv_date
                    except:
                        pass
            
            # Check each customer
            for cid, data in customer_ar.items():
                days = data["overdue_days"]
                
                if days >= critical_days:
                    # Critical - flag customer
                    if not is_customer_flagged(cid):
                        apply_credit_action(cid, "flagged", {
                            "reason": f"AR overdue {days} days",
                            "ar_amount": data["total_ar"],
                            "oldest_invoice": data["oldest_invoice"],
                            "trigger": "auto_ar_critical",
                        })
                        logger.warning(f"Customer {cid} flagged: AR overdue {days} days")
                        
                elif days >= warning_days:
                    # Warning - reduce credit limit
                    apply_credit_action(cid, "limit_reduce", {
                        "reason": f"AR overdue {days} days (warning)",
                        "ar_amount": data["total_ar"],
                        "trigger": "auto_ar_warning",
                    })
                    logger.info(f"Customer {cid} credit reduced: AR overdue {days} days")
                    
        except Exception as e:
            logger.error(f"Credit risk check failed: {e}")


# Singleton instance
_automation: Optional[WorkflowAutomation] = None


def get_workflow_automation() -> WorkflowAutomation:
    """Get or create the workflow automation singleton."""
    global _automation
    if _automation is None:
        _automation = WorkflowAutomation()
    return _automation


async def start_workflow_automation():
    """Start the workflow automation scheduler."""
    automation = get_workflow_automation()
    await automation.start()


async def stop_workflow_automation():
    """Stop the workflow automation scheduler."""
    automation = get_workflow_automation()
    await automation.stop()


# Manual trigger for testing
async def run_automation_checks_once():
    """Run all automation checks once (for testing/manual trigger)."""
    automation = get_workflow_automation()
    await automation._run_all_checks()
