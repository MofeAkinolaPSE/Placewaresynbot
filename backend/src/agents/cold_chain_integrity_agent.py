from __future__ import annotations
from typing import Any, Dict, List
import datetime as dt
from src.agents.base_agent import BaseAgent, Insight
from src.agent_registry import register_agent
from src.utils.batch_query import batch_query


@register_agent
class ColdChainIntegrityAgent(BaseAgent):
    name = "cold_chain_integrity"
    required_role = "qc"

    def collect_data(self) -> Dict[str, Any]:
        executor = self.context.get("db_executor")
        specs = self.context.get("query_specs") or []
        parallel = bool(self.context.get("parallel_queries", False))
        if not executor:
            return {"results": [], "query_count": 0}
        if not specs:
            specs = [{"type": "cold_chain_sensor_events_recent"}, {"type": "inventory_batches_with_temp"}]
        return batch_query(executor, specs, parallel=parallel)

    def analyze(self, data: Dict[str, Any]) -> Dict[str, Any]:
        results = data.get("results", [])
        out_of_range: List[Dict[str, Any]] = []
        affected_batches: List[Dict[str, Any]] = []
        temp_stats = {"events_processed": 0, "violations": 0}

        # configured allowed range
        low = float(self.context.get("temp_allowed_low", 2.0))
        high = float(self.context.get("temp_allowed_high", 8.0))

        for spec, res in results:
            for row in res or []:
                try:
                    temp = row.get("temperature_c")
                    sensor_id = row.get("sensor_id") or row.get("device")
                    ts = row.get("timestamp") or row.get("event_time")
                    batch_id = row.get("batch_id")
                    if temp is None:
                        continue
                    temp_stats["events_processed"] += 1
                    t = float(temp)
                    if t < low or t > high:
                        temp_stats["violations"] += 1
                        out_of_range.append({"sensor_id": sensor_id, "timestamp": ts, "temperature_c": t, "batch_id": batch_id})
                        if batch_id:
                            affected_batches.append({"batch_id": batch_id, "sensor_id": sensor_id, "temperature_c": t, "timestamp": ts})
                except Exception:
                    continue

        return {"temp_stats": temp_stats, "violations": out_of_range, "affected_batches": affected_batches}

    def generate_insights(self, analysis: Dict[str, Any]) -> Insight:
        insight = Insight()
        stats = analysis.get("temp_stats") or {}
        violations = analysis.get("violations") or []
        affected = analysis.get("affected_batches") or []

        insight.metrics.update(stats)

        if violations:
            insight.findings.append(f"{len(violations)} temperature violation(s) detected in the cold chain.")
            insight.supporting_refs.extend(violations[:20])
            insight.recommendations.append("Quarantine affected batches and inspect temperature logs for transport legs.")
            insight.recommendations.append("Validate sensor calibrations and delivery vehicle compliance records.")
            # attempt automated lock on affected batches if workflow configured
            if self.context.get("auto_trigger_workflow") and self.context.get("workflow_engine"):
                engine = self.context.get("workflow_engine")
                for b in affected[:20]:
                    try:
                        engine.enqueue("compliance.lock_batch", {"batch_id": b.get("batch_id"), "reason": "temp_violation"})
                    except Exception:
                        pass

        insight.confidence_score = 0.9 if stats.get("events_processed", 0) > 0 else 0.5
        return insight

    def write_cache(self, insight: Insight) -> None:
        cache = self.context.get("cache")
        ttl = int(self.context.get("cache_ttl_seconds", 300))
        if cache:
            cache.set(self.name, insight, ttl=ttl)

    def get_output_schema(self) -> Dict[str, Any]:
        return {"temp_stats": "dict", "violations": "list", "affected_batches": "list"}
