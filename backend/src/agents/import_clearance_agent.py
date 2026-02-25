from __future__ import annotations
from typing import Any, Dict, List
import datetime as dt
from src.agents.base_agent import BaseAgent, Insight
from src.agent_registry import register_agent
from src.utils.batch_query import batch_query
from src.constants import PROCUREMENT_CLEARANCE_DELAY_DAYS, PROCUREMENT_DAILY_DELAY_COST


@register_agent
class ImportClearanceAgent(BaseAgent):
    name = "import_clearance"
    required_role = "procurement"

    def collect_data(self) -> Dict[str, Any]:
        executor = self.context.get("db_executor")
        specs = self.context.get("query_specs") or []
        parallel = bool(self.context.get("parallel_queries", False))
        if not executor:
            return {"results": [], "query_count": 0}
        # Default spec if none provided
        if not specs:
            specs = [{"type": "procurement_shipments_active"}]
        return batch_query(executor, specs, parallel=parallel)

    def analyze(self, data: Dict[str, Any]) -> Dict[str, Any]:
        results = data.get("results", [])
        stuck: List[Dict[str, Any]] = []
        supplier_scores: Dict[str, Dict[str, Any]] = {}
        total_estimated_cost = 0.0

        threshold_days = int(self.context.get("clearance_delay_days", PROCUREMENT_CLEARANCE_DELAY_DAYS))

        for spec, res in results:
            for row in res or []:
                try:
                    shipment_id = row.get("shipment_id") or row.get("id")
                    supplier = str(row.get("supplier") or "unknown")
                    status = str(row.get("status") or "").lower()
                    eta_str = row.get("arrival_date") or row.get("eta") or row.get("created_at")
                    created_at = None
                    if eta_str:
                        try:
                            created_at = dt.datetime.fromisoformat(str(eta_str))
                        except Exception:
                            created_at = None

                    # compute days in clearance if status indicates 'under clearance' or similar
                    days_in_clearance = 0
                    if status in ("under clearance", "at port", "clearance"):
                        # use created_at fallback to now
                        ref = created_at or dt.datetime.utcnow()
                        days_in_clearance = (dt.datetime.utcnow() - ref).days

                    if days_in_clearance >= threshold_days:
                        est_cost = float(self.context.get("daily_delay_cost", PROCUREMENT_DAILY_DELAY_COST)) * float(days_in_clearance)
                        total_estimated_cost += est_cost
                        stuck.append({
                            "shipment_id": shipment_id,
                            "supplier": supplier,
                            "days_in_clearance": days_in_clearance,
                            "status": status,
                            "estimated_delay_cost": est_cost,
                        })

                    # supplier score aggregation
                    s = supplier_scores.setdefault(supplier, {"count": 0, "avg_delay": 0.0, "rejections": 0})
                    s["count"] += 1
                    # try to record delay if present
                    if isinstance(days_in_clearance, int) and days_in_clearance:
                        s["avg_delay"] = ((s["avg_delay"] * (s["count"] - 1)) + days_in_clearance) / s["count"]
                    if row.get("rejected"):
                        s["rejections"] += 1
                except Exception:
                    continue

        metrics = {"stuck_shipments": len(stuck), "estimated_delay_cost": round(total_estimated_cost, 2)}
        return {"metrics": metrics, "stuck": stuck, "supplier_scores": supplier_scores}

    def generate_insights(self, analysis: Dict[str, Any]) -> Insight:
        insight = Insight()
        metrics = analysis.get("metrics") or {}
        stuck = analysis.get("stuck") or []
        supplier_scores = analysis.get("supplier_scores") or {}

        insight.metrics.update(metrics)

        if stuck:
            insight.findings.append(f"{len(stuck)} shipment(s) stuck in clearance beyond threshold.")
            insight.supporting_refs.extend(stuck[:10])
            insight.recommendations.append("Escalate stuck shipments to regulatory team and procurement leadership.")
            insight.recommendations.append("Review supplier performance and consider temporary supplier holds for repeat offenders.")
            # trigger workflow escalation if configured
            if self.context.get("auto_trigger_workflow") and self.context.get("workflow_engine"):
                engine = self.context.get("workflow_engine")
                for s in stuck[:10]:
                    try:
                        engine.enqueue("procurement.escalate_clearance", {"shipment_id": s.get("shipment_id"), "reason": "clearance_delay"})
                    except Exception:
                        pass

        if supplier_scores:
            # simple top offenders
            offenders = sorted([
                {"supplier": k, **v} for k, v in supplier_scores.items()
            ], key=lambda x: -float(x.get("avg_delay", 0)))[:5]
            insight.supporting_refs.extend(offenders)
            insight.findings.append(f"Top supplier delays: {', '.join([o['supplier'] for o in offenders])}")

        insight.confidence_score = 0.8 if metrics.get("stuck_shipments", 0) > 0 else 0.6
        return insight

    def write_cache(self, insight: Insight) -> None:
        cache = self.context.get("cache")
        ttl = int(self.context.get("cache_ttl_seconds", 300))
        if cache:
            cache.set(self.name, insight, ttl=ttl)

    def get_output_schema(self) -> Dict[str, Any]:
        return {"metrics": "dict", "stuck": "list", "supplier_scores": "dict"}
