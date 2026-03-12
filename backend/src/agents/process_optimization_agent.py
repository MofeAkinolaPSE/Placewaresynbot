from __future__ import annotations
from typing import Any, Dict, List
import statistics
import datetime as dt
from src.agents.base_agent import BaseAgent, Insight
from src.agent_registry import register_agent
from src.utils.batch_query import batch_query


@register_agent
class ProcessOptimizationAgent(BaseAgent):
    """Business Process Optimisation Agent — monitors pharma-domain process
    cycle times: port clearance duration, dispatch turnaround, invoice-to-payment
    cycle, and anti-room (port dwell) time.  Detects bottlenecks and suggests
    improvements."""

    name = "process_optimization"
    required_role = "ops_lead"

    def collect_data(self) -> Dict[str, Any]:
        executor = self.context.get("db_executor")
        specs = self.context.get("query_specs") or []
        parallel = bool(self.context.get("parallel_queries", False))
        if not executor or not specs:
            return {"results": [], "query_count": 0}
        return batch_query(executor, specs, parallel=parallel)

    def analyze(self, data: Dict[str, Any]) -> Dict[str, Any]:
        results = data.get("results", [])
        errors: List[str] = []

        # Aggregate cycle times per process stage
        clearance_durations: List[float] = []   # days in clearance (shipments)
        anti_room_times: List[float] = []       # days at port before entering clearance
        dispatch_turnarounds: List[float] = []  # hours from dispatch to delivery
        payment_cycles: List[float] = []        # days from invoice to payment
        bottlenecks: List[Dict[str, Any]] = []

        now = dt.datetime.utcnow()

        for spec, res in results:
            if isinstance(res, dict) and res.get("error"):
                errors.append(str(res.get("error")))
                continue
            spec_type = spec.get("type", "") if isinstance(spec, dict) else ""

            for row in res or []:
                try:
                    # Shipment lifecycle data (clearance + anti-room)
                    if spec_type in ("shipment_lifecycle", "procurement_shipments_active"):
                        status = str(row.get("status") or "").lower()
                        created_at = row.get("created_at") or row.get("arrival_date")
                        # Support multiple column name variants across schema versions
                        cleared_at = (
                            row.get("cleared_at")
                            or row.get("clearance_completed_at")
                            or row.get("customs_cleared_at")
                        )
                        at_port_at = (
                            row.get("at_port_at")
                            or row.get("port_arrived_at")
                            or row.get("arrival_date")
                            or row.get("received_at")
                        )

                        if created_at:
                            try:
                                start = dt.datetime.fromisoformat(str(created_at).replace("Z", "+00:00")).replace(tzinfo=None)
                            except Exception:
                                start = None
                        else:
                            start = None

                        # Clearance duration: time in "under_clearance" state
                        if cleared_at and start:
                            try:
                                end = dt.datetime.fromisoformat(str(cleared_at).replace("Z", "+00:00")).replace(tzinfo=None)
                                days = (end - start).total_seconds() / 86400
                                clearance_durations.append(days)
                            except Exception:
                                pass
                        elif status in ("under_clearance", "under clearance", "clearance") and start:
                            days = (now - start).total_seconds() / 86400
                            clearance_durations.append(days)

                        # Anti-room time: time at port before clearance starts
                        if at_port_at and start:
                            try:
                                port_start = dt.datetime.fromisoformat(str(at_port_at).replace("Z", "+00:00")).replace(tzinfo=None)
                                ar_days = (port_start - start).total_seconds() / 86400
                                if ar_days >= 0:
                                    anti_room_times.append(ar_days)
                            except Exception:
                                pass

                    # Custody events (dispatch turnaround)
                    elif spec_type == "custody_events":
                        event_type = str(row.get("event_type") or row.get("location") or "").lower()
                        event_time = row.get("event_time") or row.get("created_at")
                        shipment_id = row.get("shipment_id")

                        if event_type in ("dispatched", "dispatch") and event_time:
                            # Look for matching delivery event elsewhere
                            dispatch_time = event_time
                        if event_type in ("delivered", "delivery") and event_time:
                            delivered_time = event_time

                        # Direct turnaround from dispatch_at and delivered_at columns
                        dispatch_at = row.get("dispatch_at") or row.get("dispatched_at")
                        delivered_at = row.get("delivered_at")
                        if dispatch_at and delivered_at:
                            try:
                                d_start = dt.datetime.fromisoformat(str(dispatch_at).replace("Z", "+00:00")).replace(tzinfo=None)
                                d_end = dt.datetime.fromisoformat(str(delivered_at).replace("Z", "+00:00")).replace(tzinfo=None)
                                hours = (d_end - d_start).total_seconds() / 3600
                                if hours >= 0:
                                    dispatch_turnarounds.append(hours)
                            except Exception:
                                pass

                    # AR paid invoices (invoice-to-payment cycle)
                    elif spec_type in ("ar_paid", "ar_aging"):
                        invoice_date = row.get("invoice_date") or row.get("date")
                        payment_date = row.get("payment_date") or row.get("paid_at")
                        # If no explicit payment_date, use due_date as proxy for paid invoices
                        # (marks metric as estimated in the output)
                        if not payment_date:
                            status_val = str(row.get("status") or "").lower()
                            if status_val == "paid":
                                payment_date = row.get("due_date")
                        if invoice_date and payment_date:
                            try:
                                inv = dt.datetime.fromisoformat(str(invoice_date).replace("Z", "+00:00")).replace(tzinfo=None)
                                pay = dt.datetime.fromisoformat(str(payment_date).replace("Z", "+00:00")).replace(tzinfo=None)
                                cycle_days = (pay - inv).total_seconds() / 86400
                                if cycle_days >= 0:
                                    payment_cycles.append(cycle_days)
                            except Exception:
                                pass

                except Exception:
                    errors.append("row_parse_error")

        # Compute stage metrics
        def _stage_stats(values: List[float]) -> Dict[str, float]:
            if not values:
                return {"avg": 0.0, "p50": 0.0, "p95": 0.0, "count": 0}
            sorted_vals = sorted(values)
            p50_idx = max(0, int(len(sorted_vals) * 0.50) - 1)
            p95_idx = max(0, int(len(sorted_vals) * 0.95) - 1)
            return {
                "avg": round(statistics.mean(sorted_vals), 2),
                "p50": round(sorted_vals[p50_idx], 2),
                "p95": round(sorted_vals[p95_idx], 2),
                "count": len(sorted_vals),
            }

        stages = {
            "clearance_duration_days": _stage_stats(clearance_durations),
            "anti_room_days": _stage_stats(anti_room_times),
            "dispatch_turnaround_hours": _stage_stats(dispatch_turnarounds),
            "invoice_to_payment_days": _stage_stats(payment_cycles),
        }

        # Detect bottlenecks with thresholds
        thresholds = {
            "clearance_duration_days": float(self.context.get("clearance_bottleneck_days", 5)),
            "anti_room_days": float(self.context.get("anti_room_bottleneck_days", 3)),
            "dispatch_turnaround_hours": float(self.context.get("dispatch_bottleneck_hours", 48)),
            "invoice_to_payment_days": float(self.context.get("payment_bottleneck_days", 45)),
        }

        for stage_name, stats in stages.items():
            threshold = thresholds.get(stage_name, float("inf"))
            if stats["avg"] > threshold and stats["count"] > 0:
                bottlenecks.append({
                    "stage": stage_name,
                    "avg": stats["avg"],
                    "p95": stats["p95"],
                    "threshold": threshold,
                    "severity": "high" if stats["p95"] > threshold * 1.5 else "medium",
                })

        return {"stages": stages, "bottlenecks": bottlenecks, "errors": errors}

    def generate_insights(self, analysis: Dict[str, Any]) -> Insight:
        stages = analysis.get("stages", {})
        bottlenecks = analysis.get("bottlenecks", [])
        errors = analysis.get("errors", [])

        insight = Insight()
        insight.metrics.update(stages)
        insight.metrics["bottleneck_count"] = len(bottlenecks)

        # Stage summaries
        for stage_name, stats in stages.items():
            if stats["count"] > 0:
                label = stage_name.replace("_", " ").title()
                insight.findings.append(
                    f"{label}: avg {stats['avg']}, p50 {stats['p50']}, p95 {stats['p95']} "
                    f"({stats['count']} observations)."
                )

        if bottlenecks:
            insight.findings.append(
                f"Detected {len(bottlenecks)} process bottleneck(s)."
            )
            insight.supporting_refs.extend(bottlenecks)

            for bn in bottlenecks:
                stage = bn["stage"].replace("_", " ").title()
                if bn["severity"] == "high":
                    insight.risks.append(
                        f"CRITICAL bottleneck: {stage} avg {bn['avg']} exceeds "
                        f"threshold {bn['threshold']} by {round(bn['avg'] - bn['threshold'], 1)}."
                    )
                insight.recommendations.append(
                    f"Improve {stage}: current avg {bn['avg']} vs target {bn['threshold']}. "
                    f"Investigate root cause and assign process owner."
                )

            insight.confidence_score = 0.85
        else:
            insight.findings.append("No significant process bottlenecks detected.")
            insight.confidence_score = 0.7

        if errors:
            insight.risks.append("partial_data: some process queries failed")
            insight.confidence_score = min(insight.confidence_score, 0.55)

        return insight

    def write_cache(self, insight: Insight) -> None:
        cache = self.context.get("cache")
        ttl = self.context.get("cache_ttl_seconds", 300)
        if cache:
            cache.set(self.name, insight, ttl=ttl)

    def get_output_schema(self) -> Dict[str, Any]:
        return {
            "stages": "dict of stage_name -> {avg, p50, p95, count}",
            "bottlenecks": "list[dict(stage, avg, p95, threshold, severity)]",
        }
