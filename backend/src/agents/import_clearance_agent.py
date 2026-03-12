from __future__ import annotations
from typing import Any, Dict, List, Optional
import datetime as dt
from src.agents.base_agent import BaseAgent, Insight
from src.agent_registry import register_agent
from src.utils.batch_query import batch_query
from src.constants import PROCUREMENT_CLEARANCE_DELAY_DAYS, PROCUREMENT_DAILY_DELAY_COST
from src.db import db


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

        # Build supplier_id → avg_delay_days lookup from scorecard rows
        scorecard_lookup: Dict[str, float] = {}
        for spec, res in results:
            if spec.get("type") == "supplier_scorecards":
                for row in res or []:
                    sid = str(row.get("supplier_id") or "")
                    avg_d = row.get("avg_delay_days")
                    if sid and avg_d is not None:
                        try:
                            scorecard_lookup[sid] = float(avg_d)
                        except (TypeError, ValueError):
                            pass

        for spec, res in results:
            for row in res or []:
                try:
                    shipment_id = row.get("shipment_id") or row.get("id")
                    supplier_id = row.get("supplier_id")
                    supplier = str(row.get("supplier") or supplier_id or "unknown")
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

                        # Predict additional days using supplier scorecard
                        predicted_additional_days: Optional[int] = None
                        if supplier_id and str(supplier_id) in scorecard_lookup:
                            avg_delay = scorecard_lookup[str(supplier_id)]
                            if days_in_clearance < avg_delay:
                                predicted_additional_days = int(avg_delay - days_in_clearance)
                            else:
                                predicted_additional_days = int(days_in_clearance * 0.2)

                        stuck_entry: Dict[str, Any] = {
                            "shipment_id": shipment_id,
                            "supplier": supplier,
                            "days_in_clearance": days_in_clearance,
                            "status": status,
                            "estimated_delay_cost": est_cost,
                        }
                        if predicted_additional_days is not None:
                            stuck_entry["predicted_additional_days"] = predicted_additional_days
                        stuck.append(stuck_entry)

                    # supplier score aggregation
                    s = supplier_scores.setdefault(supplier, {"supplier_id": supplier_id, "count": 0, "avg_delay": 0.0, "rejections": 0})
                    if not s.get("supplier_id") and supplier_id:
                        s["supplier_id"] = supplier_id
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

            # Persist scorecard snapshots (best effort)
            period = dt.datetime.utcnow().strftime("%Y-%m")
            actor = self.context.get("actor_id")
            for supplier_name, stats in list(supplier_scores.items())[:25]:
                try:
                    supplier_id = stats.get("supplier_id")
                    if not supplier_id and supplier_name and supplier_name != "unknown":
                        s_resp = db.table("suppliers").select("id").eq("name", supplier_name).limit(1).execute()
                        s_rows = s_resp.data if hasattr(s_resp, "data") else []
                        supplier_id = s_rows[0].get("id") if s_rows else None
                    if not supplier_id:
                        continue

                    count = max(int(stats.get("count", 0)), 1)
                    avg_delay = float(stats.get("avg_delay", 0.0))
                    rejections = int(stats.get("rejections", 0))
                    rejection_rate = (rejections / count) * 100
                    on_time_rate = max(0.0, min(100.0, 100.0 - (avg_delay * 10.0) - rejection_rate))
                    compliance_score = max(0.0, min(100.0, on_time_rate - (rejection_rate * 0.5)))

                    db.table("placeware_supplier_scorecards").insert(
                        {
                            "supplier_id": supplier_id,
                            "evaluation_period": period,
                            "avg_delay_days": round(avg_delay, 2),
                            "rejection_rate": round(rejection_rate, 2),
                            "compliance_score": round(compliance_score, 2),
                            "total_shipments": count,
                            "on_time_rate": round(on_time_rate, 2),
                            "notes": "auto-generated by import_clearance agent",
                            "evaluated_by": None,
                        }
                    ).execute()
                except Exception:
                    continue

        insight.confidence_score = 0.8 if metrics.get("stuck_shipments", 0) > 0 else 0.6
        return insight

    def write_cache(self, insight: Insight) -> None:
        cache = self.context.get("cache")
        ttl = int(self.context.get("cache_ttl_seconds", 300))
        if cache:
            cache.set(self.name, insight, ttl=ttl)

    def get_output_schema(self) -> Dict[str, Any]:
        return {"metrics": "dict", "stuck": "list", "supplier_scores": "dict"}
