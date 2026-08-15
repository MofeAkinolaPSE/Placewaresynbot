from __future__ import annotations
import logging
from datetime import date, timedelta
from typing import Any, Dict, List, Optional

from src.agents.base_agent import BaseAgent, Insight
from src.agent_registry import register_agent
from src.utils.batch_query import batch_query

logger = logging.getLogger(__name__)


@register_agent
class ComplianceMonitoringAgent(BaseAgent):
    name = "compliance_monitoring"
    required_role = "compliance_officer"

    # ══════════════════════════════════════════════════════════════════════════
    # Existing NAFDAC batch / sample path (unchanged)
    # ══════════════════════════════════════════════════════════════════════════

    def collect_data(self) -> Dict[str, Any]:
        """Collect required compliance datasets using provided executor.

        Expected context keys:
          - `db_executor`: callable(spec) -> result
          - `query_specs`: iterable of specs (ideally two specs: batches, nafadc_samples)
          - `parallel_queries`: bool
          - `db`: supabase client (for QMS activity scanning)
        Returns batch_query result structure as a safe fallback.
        """
        executor = self.context.get("db_executor")
        specs = self.context.get("query_specs")
        parallel = bool(self.context.get("parallel_queries", False))

        batch_results: Dict = {"results": [], "query_count": 0, "total_latency_ms": 0}
        if executor and specs:
            batch_results = batch_query(executor, specs, parallel=parallel)

        # Also scan QMS activity compliance if db client is available
        activity_data = self._scan_activity_compliance()

        return {**batch_results, "activity_data": activity_data}

    def analyze(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Analyze batch and sample results to detect pending approvals and breaches.

        Expects `results` to be list of (spec, result) tuples where each result
        is an iterable of dict rows.
        """
        results = data.get("results", [])
        pending_approvals: List[Dict[str, Any]] = []
        non_compliant: List[Dict[str, Any]] = []
        errors: List[str] = []

        for spec, res in results:
            if isinstance(res, dict) and res.get("error"):
                errors.append(f"spec={spec}: {res.get('error')}")
                continue
            try:
                for row in res or []:
                    if not isinstance(row, dict):
                        continue
                    naf_status = (row.get("nafdac_status") or row.get("naf_status") or row.get("status"))
                    compliance_flag = row.get("compliance") or row.get("is_compliant")

                    if naf_status in (None, "pending", "awaiting"):
                        pending_approvals.append(row)

                    if naf_status in ("failed", "rejected") or compliance_flag in (False, "fail", "breach"):
                        non_compliant.append(row)
            except Exception:
                errors.append(f"failed to parse result for spec={spec}")

        activity_data = data.get("activity_data", {})

        metrics = {
            "pending_approvals_count": len(pending_approvals),
            "non_compliant_count": len(non_compliant),
            "query_count": data.get("query_count", 0),
            "overdue_activities": activity_data.get("overdue_count", 0),
            "missed_activities":  activity_data.get("missed_count", 0),
        }

        return {
            "metrics": metrics,
            "pending_approvals": pending_approvals,
            "non_compliant": non_compliant,
            "errors": errors,
            "activity_data": activity_data,
        }

    def generate_insights(self, analysis: Dict[str, Any]) -> Insight:
        metrics = analysis.get("metrics", {})
        pending = analysis.get("pending_approvals", [])
        non_compliant = analysis.get("non_compliant", [])
        errors = analysis.get("errors", [])
        activity_data = analysis.get("activity_data", {})

        insight = Insight()
        insight.metrics.update(metrics)

        if pending:
            insight.findings.append(f"{len(pending)} batches pending NAFDAC approval")
            insight.recommendations.append("Hold dispatch and prevent invoicing for pending batches until approval.")
            insight.supporting_refs.extend(pending[:10])

        if non_compliant:
            insight.risks.append(f"{len(non_compliant)} non-compliant batches detected")
            insight.recommendations.append("Quarantine non-compliant batches and initiate QC investigation.")
            insight.supporting_refs.extend(non_compliant[:10])

        # QMS activity findings
        overdue_acts = activity_data.get("overdue_activities", [])
        missed_acts  = activity_data.get("missed_activities", [])

        if overdue_acts:
            insight.findings.append(
                f"{len(overdue_acts)} scheduled compliance activity/activities are overdue."
            )
            insight.recommendations.append(
                "Review overdue activities and update completion status or raise a deviation."
            )
        if missed_acts:
            insight.risks.append(
                f"{len(missed_acts)} compliance activity/activities were missed — "
                f"a deviation report may be required per SOP-DEV-001."
            )
            insight.supporting_refs.extend(missed_acts[:5])

        # Trigger batch-locking workflows for non-compliant and pending batches
        engine = self.context.get("workflow_engine")
        auto_trigger = bool(self.context.get("auto_trigger_workflow", True))
        if engine and auto_trigger:
            locked_count = 0
            for batch in non_compliant[:20]:
                batch_id = batch.get("batch_id") or batch.get("id")
                if batch_id:
                    try:
                        engine.enqueue("compliance.lock_batch", {
                            "batch_id": str(batch_id),
                            "reason": "non_compliant_nafdac",
                        })
                        locked_count += 1
                    except Exception:
                        pass
            for batch in pending[:20]:
                batch_id = batch.get("batch_id") or batch.get("id")
                if batch_id:
                    try:
                        engine.enqueue("compliance.lock_batch", {
                            "batch_id": str(batch_id),
                            "reason": "pending_nafdac_approval",
                        })
                        locked_count += 1
                    except Exception:
                        pass
            if locked_count:
                insight.execution_metadata["workflow_triggered"] = True
                insight.execution_metadata["batches_locked"] = locked_count

        if errors:
            insight.risks.append("partial_data: some compliance queries failed")
            insight.supporting_refs.append({"errors": errors})

        insight.confidence_score = 0.95 if not errors else 0.6
        insight.execution_metadata["query_count"] = metrics.get("query_count", 0)

        return insight

    def write_cache(self, insight: Insight) -> None:
        cache = self.context.get("cache")
        ttl = self.context.get("cache_ttl_seconds", 120)
        if cache is None:
            return
        cache.set(self.name, insight, ttl=ttl)

    def get_output_schema(self) -> Dict[str, Any]:
        return {
            "metrics": "dict",
            "pending_approvals": "list[dict]",
            "non_compliant": "list[dict]",
            "recommendations": "list[str]",
        }

    # ══════════════════════════════════════════════════════════════════════════
    # QMS Activity Compliance extension
    # ══════════════════════════════════════════════════════════════════════════

    def _scan_activity_compliance(self) -> Dict[str, Any]:
        """Scan compliance_activity_log for overdue and missed activities.

        Returns a summary dict with keys:
          overdue_count, missed_count, overdue_activities, missed_activities
        """
        db = self.context.get("db")
        if db is None:
            return {"overdue_count": 0, "missed_count": 0,
                    "overdue_activities": [], "missed_activities": []}
        try:
            today = date.today().isoformat()
            res = (
                db.table("compliance_activity_log")
                .select("*")
                .in_("status", ["scheduled", "overdue", "missed"])
                .lte("scheduled_date", today)
                .execute()
            )
            rows: List[Dict] = res.data or []
            overdue = [r for r in rows if (r.get("status") or "").lower() == "overdue"]
            missed  = [r for r in rows if (r.get("status") or "").lower() == "missed"]
            # Tag unresolved scheduled-past-due as implicitly overdue
            for r in rows:
                if (r.get("status") or "").lower() == "scheduled":
                    overdue.append(r)
            return {
                "overdue_count":      len(overdue),
                "missed_count":       len(missed),
                "overdue_activities": overdue[:10],
                "missed_activities":  missed[:10],
            }
        except Exception as exc:
            logger.exception("_scan_activity_compliance failed")
            return {"overdue_count": 0, "missed_count": 0,
                    "overdue_activities": [], "missed_activities": [],
                    "error": str(exc)}

    def check_sop_schedule_adherence(self) -> Dict[str, Any]:
        """Cross-reference SOP review dates against sop_registry to find overdue reviews.

        Returns dict: {overdue_reviews: list, review_due_soon: list}
        """
        db = self.context.get("db")
        if db is None:
            return {"overdue_reviews": [], "review_due_soon": []}
        try:
            today = date.today()
            res = db.table("sop_registry").select("*").eq("status", "active").execute()
            rows: List[Dict] = res.data or []

            overdue_reviews = []
            due_soon = []

            for r in rows:
                last_rev = r.get("last_reviewed_at")
                interval = int(r.get("review_interval_days") or 365)
                effective = r.get("effective_from")

                base_date_str = last_rev or effective
                if not base_date_str:
                    continue
                try:
                    base = date.fromisoformat(str(base_date_str)[:10])
                    next_review = base + timedelta(days=interval)
                    days_to_review = (next_review - today).days
                    if days_to_review < 0:
                        overdue_reviews.append({**r, "days_overdue": abs(days_to_review)})
                    elif days_to_review <= 30:
                        due_soon.append({**r, "days_until_review": days_to_review})
                except (ValueError, TypeError):
                    pass

            return {"overdue_reviews": overdue_reviews, "review_due_soon": due_soon}
        except Exception as exc:
            logger.exception("check_sop_schedule_adherence failed")
            return {"overdue_reviews": [], "review_due_soon": [], "error": str(exc)}

    def generate_compliance_status_report(self) -> Dict[str, Any]:
        """Return a consolidated compliance health summary dict for dashboard use.

        Combines: activity adherence, SOP review status, audit overdue count,
        deviation open count, maintenance overdue count.
        """
        db = self.context.get("db")
        if db is None:
            return {"error": "no_db"}

        report: Dict[str, Any] = {
            "generated_at": date.today().isoformat(),
            "activity_summary":    self._scan_activity_compliance(),
            "sop_review_summary":  self.check_sop_schedule_adherence(),
        }

        try:
            audit_res = (
                db.table("audit_schedule")
                .select("id", count="exact")
                .eq("status", "overdue")
                .execute()
            )
            report["audits_overdue"] = audit_res.count or 0
        except Exception:
            report["audits_overdue"] = None

        try:
            dev_res = (
                db.table("deviation_reports")
                .select("id", count="exact")
                .neq("status", "closed")
                .execute()
            )
            report["open_deviations"] = dev_res.count or 0
        except Exception:
            report["open_deviations"] = None

        try:
            maint_res = (
                db.table("maintenance_schedule")
                .select("id", count="exact")
                .eq("status", "overdue")
                .execute()
            )
            report["overdue_maintenance"] = maint_res.count or 0
        except Exception:
            report["overdue_maintenance"] = None

        # Overall score (simple heuristic 0–100)
        deductions = 0
        if report.get("activity_summary", {}).get("missed_count", 0):
            deductions += report["activity_summary"]["missed_count"] * 5
        if report.get("audits_overdue"):
            deductions += report["audits_overdue"] * 8
        if report.get("open_deviations"):
            deductions += report["open_deviations"] * 3
        if report.get("overdue_maintenance"):
            deductions += report["overdue_maintenance"] * 4

        report["overall_compliance_score"] = max(0, 100 - deductions)
        return report
