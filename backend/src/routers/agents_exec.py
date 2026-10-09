"""
Agents API Router
Provides endpoints to list, execute, and manage department-scoped intelligence agents.
Implements Agent_stack.md specification.
"""
from fastapi import APIRouter, Request, Depends, HTTPException
from pydantic import BaseModel
from typing import Any, Dict, List, Optional
import logging
from src.middleware import verify_jwt, require_role, rate_limit, client_ip
from src.agents.router import route_question, merge_insights
from src.agent_registry import get_agent, list_agents
from src.db import db
from src.workflow.registrations import setup_workflows
from src.routers.cache_ui import get_shared_cache
import datetime as dt

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/agents", tags=["agents"])

# Initialize workflow engine with all standard workflows registered
workflow_engine = setup_workflows()
shared_cache = get_shared_cache()


AGENT_DEFAULT_SPECS: Dict[str, List[Dict[str, Any]]] = {
    "inventory_intelligence": [
        {"type": "inventory_low_stock", "threshold": 10},
        {"type": "inventory_expiring", "days": 60},
    ],
    "import_clearance": [
        {"type": "procurement_shipments_active"},
        {"type": "supplier_scorecards"},
    ],
    "cold_chain_integrity": [
        {"type": "cold_chain_sensor_events_recent"},
        {"type": "inventory_batches_with_temp"},
        {"type": "temperature_violations_recent"},
    ],
    "compliance_monitoring": [
        {"type": "compliance_pending"},
    ],
    "financial_analyst": [
        {"type": "ar_aging"},
        {"type": "gl_profitability"},
    ],
    "logistics_optimization": [
        {"type": "deliveries_recent"},
        {"type": "routes_performance"},
    ],
    "cold_room_capacity": [
        {"type": "cold_room_status_all"},
    ],
    "revenue_strategy": [
        {"type": "revenue_by_product"},
        {"type": "revenue_by_customer"},
        {"type": "ar_aging"},
        {"type": "customer_list"},
    ],
    "crm_intelligence": [
        {"type": "customer_list"},
    ],
    "enterprise_risk": [
        {"type": "procurement_shipments_active"},
        {"type": "inventory_expiring", "days": 60},
        {"type": "credit_risk_actions"},
        {"type": "batch_status_locks"},
        {"type": "deliveries_sla_breaches", "limit": 200},
    ],
    "process_optimization": [
        {"type": "shipment_lifecycle", "limit": 200},
        {"type": "custody_events", "limit": 300},
        {"type": "ar_paid", "limit": 200},
    ],
    "expiry_monitoring": [
        {"type": "inventory_expiring", "days": 60},
    ],
    # Reliability stack agents
    "maintenance_tracking": [
        {"type": "maintenance_incidents_open"},
        {"type": "maintenance_tasks_overdue"},
    ],
    "digital_twin_monitor": [
        {"type": "twin_current_state_map"},
        {"type": "twin_open_anomalies"},
    ],
    "capability_discovery": [
        {"type": "capability_proposals_active"},
        {"type": "capability_signals_recent"},
    ],
}


# Sage aged-debtor exports carry no due_date; standard trade terms are applied
# to the invoice date so AR aging buckets can still be computed.
DEFAULT_AR_TERMS_DAYS = 30


def _ar_days_overdue(row: Dict[str, Any], today: dt.date) -> int:
    """Days past due for an AR row. Uses due_date when present, otherwise
    invoice_date + DEFAULT_AR_TERMS_DAYS. Returns 0 when neither parses."""
    raw = row.get("due_date")
    terms = 0
    if not raw:
        raw = row.get("invoice_date") or row.get("date")
        terms = DEFAULT_AR_TERMS_DAYS
    if not raw:
        return 0
    try:
        base = dt.date.fromisoformat(str(raw)[:10])
    except Exception:
        return 0
    return max((today - base).days - terms, 0)


def create_db_executor():
    """Create a database executor function for agent queries."""
    def executor(spec: Dict[str, Any]) -> Any:
        """Execute a query specification against the database."""
        query_type = spec.get("type", "")
        try:
            if query_type == "inventory_low_stock":
                threshold = spec.get("threshold", 10)
                # Only items that are actually stocked — items never held (qty 0
                # across all history) are catalog noise, not low-stock signals.
                result = db.table("placeware_inventory_snapshot").select("*").gt(
                    "current_qty", 0
                ).lt("current_qty", threshold).execute()
                rows = result.data if hasattr(result, 'data') else []
                # Normalize to the field names InventoryIntelligenceAgent reads.
                return [
                    {
                        **r,
                        "product_id": r.get("sku"),
                        "stock": r.get("current_qty"),
                        "threshold": r.get("safety_stock") or threshold,
                    }
                    for r in rows
                ]
            
            elif query_type == "inventory_expiring":
                days = spec.get("days", 60)
                # Merge placeware operational inventory + sage_items_snapshot (pharmaceutical)
                rows = []
                try:
                    result = db.table("placeware_inventory_snapshot").select("*").execute()
                    rows += result.data if hasattr(result, "data") else []
                except Exception:
                    pass
                try:
                    from src.fin.readmodel import live as _live
                    if _live():
                        # ACE Books stock by item, with the next batch and its expiry
                        inv = db.table("v_inventory").select("sku,name,current_stock,expiry_date,batch_number").execute().data or []
                        for r in inv:
                            if r.get("expiry_date") and float(r.get("current_stock") or 0) > 0:
                                rows.append({"sku": r["sku"], "product_id": r["sku"], "name": r.get("name"),
                                             "batch_id": r.get("batch_number"), "expiry_date": r["expiry_date"],
                                             "best_before": r["expiry_date"], "qty_on_hand": float(r.get("current_stock") or 0),
                                             "source": "ACE Books"})
                        raise StopIteration
                    # NOTE: this local DB wrapper has no .not_ — filter for non-null
                    # expiry_date in Python after fetch (same workaround already used
                    # by services/inventory.py's get_expiring_inventory). A prior
                    # `.not_.is_(...)` call here raised AttributeError on every call,
                    # silently swallowed by the except below, so this branch never
                    # actually ran.
                    sage_res = (
                        db.table("sage_items_snapshot")
                        .select("item_id,item_name,expiry_date,batch_number")
                        .order("expiry_date")
                        .limit(2000)
                        .execute()
                    )
                    sage_rows = [
                        r for r in (sage_res.data if hasattr(sage_res, "data") else [])
                        if r.get("expiry_date")
                    ][:500]
                    item_ids = [r.get("item_id") for r in sage_rows if r.get("item_id")]
                    # Look up real on-hand quantity per SKU instead of hardcoding 0 —
                    # sage_items_snapshot is the catalog (no qty column); actual stock
                    # levels live in sage_inventory_snapshot, keyed by the same sku/item_id.
                    # Scoped to the latest import batch only: this table accumulates one
                    # batch_id per CSV re-upload (repeated re-imports of the same file are
                    # common here), so summing across all batch_ids would multiply every
                    # quantity by however many times the file was re-imported.
                    qty_by_sku: Dict[str, float] = {}
                    if item_ids:
                        try:
                            latest_batch_resp = (
                                db.table("sage_inventory_snapshot")
                                .select("batch_id")
                                .order("imported_at", desc=True)
                                .limit(1)
                                .execute()
                            )
                            latest_batch_rows = latest_batch_resp.data if hasattr(latest_batch_resp, "data") else []
                            latest_batch_id = latest_batch_rows[0].get("batch_id") if latest_batch_rows else None
                            qty_q = db.table("sage_inventory_snapshot").select("sku,quantity").in_("sku", item_ids)
                            if latest_batch_id:
                                qty_q = qty_q.eq("batch_id", latest_batch_id)
                            qty_res = qty_q.execute()
                            for qr in (qty_res.data if hasattr(qty_res, "data") else []):
                                q_sku = qr.get("sku")
                                if q_sku:
                                    qty_by_sku[q_sku] = qty_by_sku.get(q_sku, 0) + float(qr.get("quantity") or 0)
                        except Exception:
                            pass
                    for r in sage_rows:
                        item_id = r.get("item_id")
                        rows.append({
                            "sku": item_id,
                            "product_id": item_id,
                            "name": r.get("item_name"),
                            "batch_id": r.get("batch_number"),
                            "expiry_date": r.get("expiry_date"),
                            "best_before": r.get("expiry_date"),
                            "qty_on_hand": qty_by_sku.get(item_id, 0),
                        })
                except (Exception, StopIteration):
                    pass
                return rows
            
            elif query_type == "procurement_shipments_active":
                result = db.table("placeware_shipments").select("*").in_("status", ["in_transit", "at_port", "under_clearance"]).execute()
                return result.data if hasattr(result, 'data') else []
            
            elif query_type == "cold_chain_sensor_events_recent":
                result = db.table("temperature_logs").select(
                    "id, location, equipment_id, reading_celsius, min_threshold, max_threshold, logged_by, logged_at, is_deviation"
                ).order("logged_at", desc=True).limit(100).execute()
                rows = result.data if hasattr(result, 'data') else []
                return [
                    {
                        "sensor_id": r.get("equipment_id") or r.get("location"),
                        "timestamp": r.get("logged_at"),
                        "temperature_c": r.get("reading_celsius"),
                        "batch_id": r.get("location"),
                        "is_deviation": r.get("is_deviation"),
                    }
                    for r in rows
                ]

            elif query_type == "inventory_batches_with_temp":
                # No FK links temperature_logs to inventory today; returning zone status is the most honest available signal.
                result = db.table("placeware_storage_zones").select("*").execute()
                return result.data if hasattr(result, 'data') else []
            
            elif query_type == "ar_aging":
                # Only real invoices (amount > 0) — Sage aged-debtor summary rows carry 0.
                result = db.table("placeware_ar_ledger").select("*").gt(
                    "amount", 0
                ).limit(spec.get("limit", 50000)).execute()
                rows = result.data if hasattr(result, 'data') else []
                now = dt.date.today()
                normalized = []
                for row in rows:
                    days_overdue = _ar_days_overdue(row, now)
                    normalized.append({
                        **row,
                        "days_overdue": days_overdue,
                        "amount": row.get("amount") or row.get("balance") or 0,
                        "customer_id": row.get("customer_id"),
                        "customer_code": row.get("customer_code") or row.get("customer_id"),
                    })
                return normalized
            
            elif query_type == "compliance_pending":
                # placeware_inventory_snapshot.nafdac_status is a hardcoded 'approved'
                # placeholder (migrations 043/068) — it can never reflect a real pending
                # or rejected batch. nafdac_batch_registry is the real, live-tracked
                # NAFDAC status table (see qc.py's register/approve/reject endpoints).
                result = (
                    db.table("nafdac_batch_registry")
                    .select(
                        "id, batch_number, product_name, nafdac_reg_number, supplier, "
                        "status, valid_from, valid_to, dispatch_blocked, "
                        "approved_by, approved_at, rejection_reason, created_at"
                    )
                    .neq("status", "approved")
                    .execute()
                )
                return result.data if hasattr(result, 'data') else []
            
            elif query_type == "deliveries_recent":
                result = db.table("supplier_deliveries").select("*").order("created_at", desc=True).limit(50).execute()
                return result.data if hasattr(result, 'data') else []

            elif query_type == "routes_performance":
                result = db.table("supplier_deliveries").select("*").order("created_at", desc=True).limit(200).execute()
                return result.data if hasattr(result, 'data') else []
            
            elif query_type == "capacity_current":
                result = db.table("placeware_storage_zones").select("*").execute()
                return result.data if hasattr(result, 'data') else []
            
            elif query_type == "cold_room_status_all":
                result = db.table("placeware_storage_zones").select(
                    "id, zone_name, zone_type, max_capacity, current_load, "
                    "current_temperature, avg_daily_inflow, status"
                ).eq("status", "active").execute()
                # Map to expected column names for agent
                rows = result.data if hasattr(result, 'data') else []
                return [
                    {
                        "room_id": r.get("id"),
                        "capacity": r.get("max_capacity"),
                        "used_capacity": r.get("current_load"),
                        "temperature_c": r.get("current_temperature"),
                        "avg_daily_inflow": r.get("avg_daily_inflow"),
                    }
                    for r in rows
                ]
            
            elif query_type == "temperature_violations_recent":
                result = db.table("temperature_logs").select(
                    "id, location, equipment_id, reading_celsius, min_threshold, max_threshold, logged_by, logged_at, is_deviation"
                ).eq("is_deviation", True).order("logged_at", desc=True).limit(50).execute()
                return result.data if hasattr(result, 'data') else []

            # --- Revenue / Risk / Process agent queries ---

            elif query_type == "revenue_by_product":
                result = db.table("placeware_ar_ledger").select(
                    "customer_id, customer_name, amount, balance, due_date, invoice_date"
                ).gt("amount", 0).limit(spec.get("limit", 50000)).execute()
                rows = result.data if hasattr(result, 'data') else []
                now = dt.date.today()
                normalized = []
                for row in rows:
                    normalized.append(
                        {
                            "product_id": "unattributed",
                            "sku": "unattributed",
                            "customer_id": row.get("customer_id"),
                            "customer": row.get("customer_name"),
                            "amount": row.get("amount") or row.get("balance") or 0,
                            "days_overdue": _ar_days_overdue(row, now),
                        }
                    )
                return normalized

            elif query_type == "revenue_by_customer":
                result = db.table("placeware_ar_ledger").select(
                    "customer_id, customer_name, amount, balance, due_date, invoice_date"
                ).gt("amount", 0).limit(spec.get("limit", 50000)).execute()
                rows = result.data if hasattr(result, 'data') else []
                now = dt.date.today()
                normalized = []
                for row in rows:
                    normalized.append(
                        {
                            "customer_id": row.get("customer_id"),
                            "customer": row.get("customer_name"),
                            "amount": row.get("amount") or row.get("balance") or 0,
                            "days_overdue": _ar_days_overdue(row, now),
                        }
                    )
                return normalized

            elif query_type == "shipment_lifecycle":
                result = db.table("placeware_shipments").select("*").order(
                    "created_at", desc=True
                ).limit(spec.get("limit", 100)).execute()
                return result.data if hasattr(result, 'data') else []

            elif query_type == "custody_events":
                result = db.table("chain_of_custody_events").select("*").order(
                    "event_time", desc=True
                ).limit(spec.get("limit", 200)).execute()
                return result.data if hasattr(result, 'data') else []

            elif query_type == "ar_paid":
                result = db.table("placeware_ar_ledger").select("*").eq(
                    "status", "paid"
                ).order("invoice_date", desc=True).limit(
                    spec.get("limit", 200)
                ).execute()
                return result.data if hasattr(result, 'data') else []

            elif query_type == "deliveries_sla_breaches":
                result = db.table("supplier_deliveries").select("*").order(
                    "created_at", desc=True
                ).limit(spec.get("limit", 200)).execute()
                rows = result.data if hasattr(result, 'data') else []
                breached = []
                for row in rows:
                    delay = row.get("delay_minutes")
                    sla = row.get("sla_minutes")
                    try:
                        if delay is not None and sla is not None and float(delay) > float(sla):
                            breached.append(row)
                    except Exception:
                        continue
                return breached

            elif query_type == "credit_risk_actions":
                result = db.table("credit_risk_actions").select("*").order(
                    "executed_at", desc=True
                ).limit(50).execute()
                return result.data if hasattr(result, 'data') else []

            elif query_type == "supplier_scorecards":
                result = db.table("placeware_supplier_scorecards").select("*").execute()
                return result.data if hasattr(result, 'data') else []

            elif query_type == "batch_status_locks":
                result = db.table("batch_status_locks").select("*").execute()
                return result.data if hasattr(result, 'data') else []

            elif query_type == "gl_profitability" and __import__("src.fin.readmodel", fromlist=["live"]).live():
                # Real product grain from ACE Books sales lines (Sage history + ACE invoices, last 12 months)
                from src.services import books_analytics
                return books_analytics.product_profitability(months=12)

            elif query_type == "gl_profitability":
                # Aggregate GL snapshot into product-level revenue/cost rows expected by FinancialAnalystAgent.
                # Classification uses account_type from sage_coa_snapshot (Nigerian Sage 50
                # CoA does not follow US GAAP 4000-6999 numbering).
                from src.services.sage_adapter.service import _latest_batch_for_table
                from src.constants import REVENUE_ACCOUNT_TYPES, COST_ACCOUNT_TYPES

                coa_res = db.table("sage_coa_snapshot").select("account_code,account_type").limit(2000).execute()
                acct_type_map = {
                    str(r.get("account_code") or "").strip(): (r.get("account_type") or "")
                    for r in (coa_res.data or [])
                    if r.get("account_code")
                }

                batch_id = _latest_batch_for_table("sage_gl_snapshot", db)
                gl_q = db.table("sage_gl_snapshot").select("account_code,account_name,debit,credit")
                if batch_id:
                    gl_q = gl_q.eq("batch_id", batch_id)
                gl_rows = gl_q.limit(50000).execute().data or []
                rows_out = []
                for row in gl_rows:
                    code_raw = str(row.get("account_code") or "").strip()
                    acct_type = acct_type_map.get(code_raw, "")
                    debit = float(row.get("debit") or 0)
                    credit = float(row.get("credit") or 0)
                    # NOTE: these rows are GL account-level aggregates, not per-SKU
                    # product data — sage_gl_snapshot has no product/SKU grain at
                    # all. "product_id" is kept (holding the GL account_code) so
                    # FinancialAnalystAgent's existing product_stats aggregation
                    # still picks these rows up; "entity_kind" lets consumers
                    # phrase findings as GL accounts rather than real products.
                    if acct_type in REVENUE_ACCOUNT_TYPES:
                        net = credit - debit
                        if net != 0:
                            rows_out.append({
                                "product_id": code_raw,
                                "account_code": code_raw,
                                "product_name": row.get("account_name"),
                                "entity_kind": "gl_account",
                                "revenue": round(net, 2),
                                "cost": 0.0,
                                "units": 0,
                            })
                    elif acct_type in COST_ACCOUNT_TYPES:
                        net = debit - credit
                        if net != 0:
                            rows_out.append({
                                "product_id": code_raw,
                                "account_code": code_raw,
                                "product_name": row.get("account_name"),
                                "entity_kind": "gl_account",
                                "revenue": 0.0,
                                "cost": round(net, 2),
                                "units": 0,
                            })
                return rows_out

            # ── Reliability stack query handlers ──────────────────────────────
            elif query_type == "maintenance_incidents_open":
                result = db.table("placeware_incident_log").select("*").eq(
                    "status", "open"
                ).order("detected_at", desc=True).limit(100).execute()
                return result.data if hasattr(result, "data") else []

            elif query_type == "maintenance_tasks_overdue":
                import datetime as _dt
                now_iso = _dt.datetime.utcnow().isoformat() + "Z"
                result = db.table("placeware_maintenance_tasks").select("*").in_(
                    "status", ["scheduled", "in_progress", "open"]
                ).lt("due_at", now_iso).limit(100).execute()
                return result.data if hasattr(result, "data") else []

            elif query_type == "twin_current_state_map":
                result = db.table("placeware_twin_nodes").select(
                    "node_key,component,label,actual_state,health_status,last_sync_at"
                ).execute()
                return result.data if hasattr(result, "data") else []

            elif query_type == "twin_open_anomalies":
                result = db.table("placeware_twin_anomaly_events").select("*").is_(
                    "resolved_at", "null"
                ).order("detected_at", desc=True).limit(50).execute()
                return result.data if hasattr(result, "data") else []

            elif query_type == "capability_proposals_active":
                result = db.table("placeware_capability_proposals").select("*").in_(
                    "status", ["proposed", "approved"]
                ).order("confidence_score", desc=True).limit(50).execute()
                return result.data if hasattr(result, "data") else []

            elif query_type == "capability_signals_recent":
                result = db.table("placeware_capability_signals").select("*").order(
                    "last_seen_at", desc=True
                ).limit(100).execute()
                return result.data if hasattr(result, "data") else []

            elif query_type == "customer_list" and __import__("src.fin.readmodel", fromlist=["live"]).live():
                # CRM customers with their ACE Books balance
                from src.fin.db import q as _q, tx as _tx
                with _tx() as _c:
                    return _q(_c, """SELECT c.customer_code AS customer_id, c.name, COALESCE(c.client_type,'active') AS status,
                                            COALESCE(c.risk_score,0) AS risk_score, COALESCE(a.bal,0) AS outstanding_balance
                                     FROM customers c LEFT JOIN (SELECT customer_pk, SUM(balance) bal FROM v_ar_open GROUP BY 1) a
                                          ON a.customer_pk=c.id ORDER BY c.name LIMIT %s""", (spec.get("limit", 2000),))

            elif query_type == "customer_list":
                # Primary source: Sage master data (1.5K+ real customers).
                # Falls back to the internal CRM customers table when the snapshot is empty.
                result = db.table("sage_customers_snapshot").select(
                    "customer_id, name, status, phone"
                ).order("name").limit(spec.get("limit", 2000)).execute()
                rows = result.data if hasattr(result, "data") else []
                if rows:
                    seen = set()
                    out = []
                    for r in rows:
                        cid = r.get("customer_id") or ""
                        if not cid or cid in seen:
                            continue
                        seen.add(cid)
                        out.append({
                            "customer_id": cid,
                            "name": r.get("name") or cid,
                            "status": r.get("status") or "active",
                            "risk_score": 0,
                            "phone": r.get("phone") or "",
                        })
                    return out
                result = db.table("customers").select(
                    "id, name, customer_code, status, risk_score, contact_details"
                ).order("name").limit(spec.get("limit", 300)).execute()
                rows = result.data if hasattr(result, "data") else []
                return [
                    {
                        "customer_id": r.get("customer_code") or str(r.get("id", "")),
                        "name": r.get("name") or r.get("customer_code") or "",
                        "status": r.get("status") or "active",
                        "risk_score": r.get("risk_score") or 0,
                        "phone": (r.get("contact_details") or {}).get("phone", ""),
                    }
                    for r in rows
                ]

            else:
                logger.warning(f"Unknown query type: {query_type}")
                return []
        except Exception as e:
            logger.error(f"DB executor error for {query_type}: {e}")
            return {"error": str(e)}
    
    return executor


class AgentExecRequest(BaseModel):
    question: str
    mode: Optional[str] = None


class SingleAgentRequest(BaseModel):
    agent_name: str
    context: Optional[Dict[str, Any]] = None


@router.get("/list")
def api_list_agents(user=Depends(verify_jwt)):
    """List all available agents with their metadata."""
    agents = list_agents()
    return {
        "agents": [
            {
                "name": name,
                "required_role": getattr(agent_cls, "required_role", None),
            }
            for name, agent_cls in agents.items()
        ],
        "count": len(agents),
    }


@router.post("/execute")
def api_execute_agents(payload: AgentExecRequest, request: Request, user=Depends(verify_jwt)):
    """Execute agents based on question routing - runs multiple agents and merges insights."""
    rate_limit(request, key=f"agents:execute:{client_ip(request)}", limit=30)
    user_ctx = getattr(request.state, "user", {}) or {}
    roles = set(user_ctx.get("roles") or [])
    actor_id = user_ctx.get("sub")
    actor_role = next(iter(roles), None)
    mode = payload.mode or ("executive" if "admin" in roles or "management" in roles else "assistant")
    agent_names = route_question(payload.question, roles, mode)
    
    db_executor = create_db_executor()
    agent_insights: List[Dict[str, Any]] = []
    errors: List[Dict[str, str]] = []
    
    for name in agent_names:
        try:
            agent = get_agent(name, context={
                "db_executor": db_executor,
                "query_specs": _get_default_specs_for_agent(name),
                "cache": shared_cache,
                "workflow_engine": workflow_engine,
                "auto_trigger_workflow": True,
                "actor_id": actor_id,
                "actor_role": actor_role,
            })
            if not agent:
                errors.append({"agent": name, "error": "Agent not found"})
                continue
            insight = agent.run()
            ins_dict = getattr(insight, "__dict__", insight) if hasattr(insight, "__dict__") else dict(insight)
            ins_dict["_agent_name"] = name
            agent_insights.append(ins_dict)
        except Exception as e:
            logger.exception(f"Agent {name} failed: {e}")
            errors.append({"agent": name, "error": str(e)})
    
    merged = merge_insights(agent_insights) if agent_insights else {}
    return {
        "agents_executed": agent_names,
        "merged": merged,
        "insights": agent_insights,
        "errors": errors if errors else None,
    }


@router.post("/run/{agent_name}")
def api_run_single_agent(agent_name: str, request: Request, user=Depends(verify_jwt)):
    """Run a specific agent by name."""
    rate_limit(request, key=f"agents:run:{request.client.host if request.client else 'unknown'}", limit=20)
    user_ctx = getattr(request.state, "user", {}) or {}
    roles = set(user_ctx.get("roles") or [])
    actor_id = user_ctx.get("sub")
    actor_role = next(iter(roles), None)
    
    db_executor = create_db_executor()
    
    agent = get_agent(agent_name, context={
        "db_executor": db_executor,
        "query_specs": _get_default_specs_for_agent(agent_name),
        "cache": shared_cache,
        "workflow_engine": workflow_engine,
        "auto_trigger_workflow": True,
        "actor_id": actor_id,
        "actor_role": actor_role,
    })
    
    if not agent:
        raise HTTPException(status_code=404, detail=f"Agent '{agent_name}' not found")
    
    # Check role permissions
    required_role = getattr(agent, "required_role", None)
    if required_role and required_role not in roles and "admin" not in roles:
        raise HTTPException(status_code=403, detail=f"Insufficient permissions for agent '{agent_name}'")
    
    try:
        insight = agent.run()
        ins_dict = getattr(insight, "__dict__", insight) if hasattr(insight, "__dict__") else dict(insight)
        return {
            "agent": agent_name,
            "insight": ins_dict,
            "success": True,
        }
    except Exception as e:
        logger.exception(f"Agent {agent_name} execution failed")
        raise HTTPException(status_code=500, detail="Internal server error")


def _get_default_specs_for_agent(agent_name: str) -> List[Dict[str, Any]]:
    """Return default query specifications for a given agent."""
    return list(AGENT_DEFAULT_SPECS.get(agent_name, []))

