from __future__ import annotations
from typing import Any, Dict, List, Optional
from src.agents.base_agent import BaseAgent, Insight
from src.agent_registry import register_agent
from src.utils.batch_query import batch_query


@register_agent
class ComplianceMonitoringAgent(BaseAgent):
    name = "compliance_monitoring"
    required_role = "compliance_officer"

    def collect_data(self) -> Dict[str, Any]:
        """Collect required compliance datasets using provided executor.

        Expected context keys:
          - `db_executor`: callable(spec) -> result
          - `query_specs`: iterable of specs (ideally two specs: batches, nafadc_samples)
          - `parallel_queries`: bool
        Returns batch_query result structure as a safe fallback.
        """
        executor = self.context.get("db_executor")
        specs = self.context.get("query_specs")
        parallel = bool(self.context.get("parallel_queries", False))

        if not executor or not specs:
            return {"results": [], "query_count": 0, "total_latency_ms": 0}

        return batch_query(executor, specs, parallel=parallel)

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
                    # canonical keys we look for
                    batch_id = row.get("batch_id") or row.get("id")
                    naf_status = (row.get("nafdac_status") or row.get("naf_status") or row.get("status"))
                    compliance_flag = row.get("compliance") or row.get("is_compliant")

                    # pending approval
                    if naf_status in (None, "pending", "awaiting"):
                        pending_approvals.append(row)

                    # explicit non-compliant markers or failed sample results
                    if naf_status in ("failed", "rejected") or compliance_flag in (False, "fail", "breach"):
                        non_compliant.append(row)
            except Exception:
                errors.append(f"failed to parse result for spec={spec}")

        metrics = {
            "pending_approvals_count": len(pending_approvals),
            "non_compliant_count": len(non_compliant),
            "query_count": data.get("query_count", 0),
        }

        return {
            "metrics": metrics,
            "pending_approvals": pending_approvals,
            "non_compliant": non_compliant,
            "errors": errors,
        }

    def generate_insights(self, analysis: Dict[str, Any]) -> Insight:
        metrics = analysis.get("metrics", {})
        pending = analysis.get("pending_approvals", [])
        non_compliant = analysis.get("non_compliant", [])
        errors = analysis.get("errors", [])

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

        # simple heuristic for confidence
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
