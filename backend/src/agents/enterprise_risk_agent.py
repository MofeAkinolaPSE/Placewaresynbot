from __future__ import annotations
from typing import Any, Dict, List
import statistics
from src.agents.base_agent import BaseAgent, Insight
from src.agent_registry import register_agent
from src.utils.batch_query import batch_query


@register_agent
class EnterpriseRiskAgent(BaseAgent):
    """Cross-domain Enterprise Risk Agent.

    Pulls data from multiple domains (procurement, inventory, finance,
    logistics, compliance) and correlates risks into a unified heatmap
    with scenario simulations.
    """

    name = "enterprise_risk"
    required_role = "risk_officer"

    # Risk domain weights for composite scoring
    _DOMAIN_WEIGHTS = {
        "procurement": 0.20,
        "inventory": 0.20,
        "finance": 0.25,
        "logistics": 0.15,
        "compliance": 0.20,
    }

    def collect_data(self) -> Dict[str, Any]:
        """Collect cross-domain data: direct DB queries + other agents' cached insights."""
        executor = self.context.get("db_executor")
        specs = self.context.get("query_specs") or []
        parallel = bool(self.context.get("parallel_queries", False))

        # Primary: query DB for risk-related tables
        db_data: Dict[str, Any] = {"results": [], "query_count": 0}
        if executor and specs:
            db_data = batch_query(executor, specs, parallel=parallel)

        # Secondary: read cached insights from other agents
        cache = self.context.get("cache")
        agent_caches: Dict[str, Any] = {}
        if cache:
            for agent_key in (
                "import_clearance", "inventory_intelligence",
                "financial_analyst", "logistics_optimization",
                "compliance_monitoring", "cold_chain_integrity",
            ):
                cached = cache.get(agent_key)
                if cached:
                    agent_caches[agent_key] = cached

        db_data["agent_caches"] = agent_caches
        return db_data

    def analyze(self, data: Dict[str, Any]) -> Dict[str, Any]:
        results = data.get("results", [])
        agent_caches = data.get("agent_caches", {})
        errors: List[str] = []

        # ------------------------------------------------------------------
        # Domain risk scores (0-100 scale)
        # ------------------------------------------------------------------
        domain_scores: Dict[str, Dict[str, Any]] = {}

        # 1. Procurement risk: clearance delays, stuck shipments
        proc_score = 0.0
        proc_details: Dict[str, Any] = {"stuck_shipments": 0, "estimated_cost": 0}
        if "import_clearance" in agent_caches:
            ic = agent_caches["import_clearance"]
            metrics = getattr(ic, "metrics", {}) if hasattr(ic, "metrics") else ic.get("metrics", {})
            stuck = metrics.get("stuck_shipments", 0)
            cost = metrics.get("estimated_delay_cost", 0)
            proc_details = {"stuck_shipments": stuck, "estimated_cost": cost}
            proc_score = min(100, stuck * 15 + (cost / 100000) * 10)
        domain_scores["procurement"] = {"score": round(proc_score, 1), "details": proc_details}

        # 2. Inventory risk: low stock + expiry
        inv_score = 0.0
        inv_details: Dict[str, Any] = {"low_stock_count": 0, "near_expiry_count": 0}
        if "inventory_intelligence" in agent_caches:
            ii = agent_caches["inventory_intelligence"]
            metrics = getattr(ii, "metrics", {}) if hasattr(ii, "metrics") else ii.get("metrics", {})
            low = metrics.get("low_stock_count", 0)
            inv_details["low_stock_count"] = low
            inv_score += min(50, low * 5)
        inv_details_near_expiry = 0
        for spec, res in results:
            spec_type = spec.get("type", "") if isinstance(spec, dict) else ""
            if spec_type == "inventory_expiring":
                try:
                    inv_details_near_expiry = len(res) if isinstance(res, list) else 0
                except Exception:
                    pass
        inv_details["near_expiry_count"] = inv_details_near_expiry
        inv_score += min(50, inv_details_near_expiry * 3)
        domain_scores["inventory"] = {"score": round(min(100, inv_score), 1), "details": inv_details}

        # 3. Finance risk: AR aging 90+, margin compression
        fin_score = 0.0
        fin_details: Dict[str, Any] = {"ar_90plus": 0, "overall_margin_pct": 0}
        if "financial_analyst" in agent_caches:
            fa = agent_caches["financial_analyst"]
            metrics = getattr(fa, "metrics", {}) if hasattr(fa, "metrics") else fa.get("metrics", {})
            ar_buckets = metrics.get("ar_buckets", {})
            ar_90 = ar_buckets.get("90+", 0)
            margin = metrics.get("overall_margin_pct", 100)
            fin_details = {"ar_90plus": ar_90, "overall_margin_pct": margin}
            fin_score = min(50, (ar_90 / 1_000_000) * 20) + max(0, (20 - margin) * 2.5)
        # Also pull from DB query results
        for spec, res in results:
            if isinstance(res, dict) and res.get("error"):
                errors.append(str(res.get("error")))
                continue
            spec_type = spec.get("type", "") if isinstance(spec, dict) else ""
            if spec_type in ("credit_risk_actions", "ar_aging"):
                try:
                    for row in res or []:
                        action = str(row.get("action", ""))
                        if action in ("limit_reduce", "flagged", "hold"):
                            fin_score += 5
                except Exception:
                    pass
        domain_scores["finance"] = {"score": round(min(100, fin_score), 1), "details": fin_details}

        # 4. Logistics risk: SLA breaches
        log_score = 0.0
        log_details: Dict[str, Any] = {"sla_breach_count": 0, "avg_delay": 0}
        if "logistics_optimization" in agent_caches:
            lo = agent_caches["logistics_optimization"]
            metrics = getattr(lo, "metrics", {}) if hasattr(lo, "metrics") else lo.get("metrics", {})
            breaches = metrics.get("sla_breach_count", 0)
            avg_delay = metrics.get("avg_delay_minutes", 0)
            log_details = {"sla_breach_count": breaches, "avg_delay": avg_delay}
            log_score = min(100, breaches * 10 + avg_delay * 0.5)
        domain_scores["logistics"] = {"score": round(min(100, log_score), 1), "details": log_details}

        # 5. Compliance risk: pending + non-compliant batches, temp violations
        comp_score = 0.0
        comp_details: Dict[str, Any] = {"pending_count": 0, "non_compliant_count": 0, "temp_violations": 0}
        if "compliance_monitoring" in agent_caches:
            cm = agent_caches["compliance_monitoring"]
            metrics = getattr(cm, "metrics", {}) if hasattr(cm, "metrics") else cm.get("metrics", {})
            pending = metrics.get("pending_approvals_count", 0)
            non_comp = metrics.get("non_compliant_count", 0)
            comp_details["pending_count"] = pending
            comp_details["non_compliant_count"] = non_comp
            comp_score += pending * 5 + non_comp * 20
        if "cold_chain_integrity" in agent_caches:
            cc = agent_caches["cold_chain_integrity"]
            metrics = getattr(cc, "metrics", {}) if hasattr(cc, "metrics") else cc.get("metrics", {})
            violations = metrics.get("violations", 0)
            comp_details["temp_violations"] = violations
            comp_score += violations * 8
        domain_scores["compliance"] = {"score": round(min(100, comp_score), 1), "details": comp_details}

        # ------------------------------------------------------------------
        # Composite enterprise risk score (weighted)
        # ------------------------------------------------------------------
        composite = sum(
            domain_scores.get(d, {}).get("score", 0) * w
            for d, w in self._DOMAIN_WEIGHTS.items()
        )

        # ------------------------------------------------------------------
        # Risk heatmap data
        # ------------------------------------------------------------------
        heatmap: List[Dict[str, Any]] = []
        for domain, info in domain_scores.items():
            score = info["score"]
            severity = 1 if score < 20 else 2 if score < 40 else 3 if score < 60 else 4 if score < 80 else 5
            likelihood = min(5, max(1, int(score / 20) + 1))
            heatmap.append({
                "domain": domain,
                "severity": severity,
                "likelihood": likelihood,
                "score": score,
                "details": info["details"],
            })

        metrics = {
            "composite_risk_score": round(composite, 1),
            "domain_count": len(domain_scores),
            "high_risk_domains": sum(1 for d in domain_scores.values() if d["score"] >= 60),
            "agent_caches_used": len(agent_caches),
        }

        return {
            "metrics": metrics,
            "domain_scores": domain_scores,
            "heatmap": heatmap,
            "errors": errors,
        }

    def generate_insights(self, analysis: Dict[str, Any]) -> Insight:
        metrics = analysis.get("metrics", {})
        domain_scores = analysis.get("domain_scores", {})
        heatmap = analysis.get("heatmap", [])
        errors = analysis.get("errors", [])

        insight = Insight()
        insight.metrics.update(metrics)
        insight.metrics["heatmap"] = heatmap

        composite = metrics.get("composite_risk_score", 0)

        # Top risks
        sorted_domains = sorted(domain_scores.items(), key=lambda x: -x[1]["score"])
        if sorted_domains:
            top_domain, top_info = sorted_domains[0]
            insight.findings.append(
                f"Highest risk domain: {top_domain} (score {top_info['score']}/100)"
            )
            insight.supporting_refs.extend(heatmap)

        # Enterprise risk level
        if composite >= 60:
            insight.risks.append(
                f"Enterprise risk ELEVATED: composite score {composite}/100. "
                "Immediate cross-functional review recommended."
            )
            insight.recommendations.append(
                "Initiate executive risk committee meeting. Assign domain owners for mitigation."
            )
        elif composite >= 35:
            insight.risks.append(
                f"Enterprise risk MODERATE: composite score {composite}/100."
            )
            insight.recommendations.append(
                "Monitor top risk domains closely. Schedule review within 7 days."
            )
        else:
            insight.findings.append(
                f"Enterprise risk LOW: composite score {composite}/100."
            )

        # Scenario simulation
        proc_score = domain_scores.get("procurement", {}).get("score", 0)
        fin_details = domain_scores.get("finance", {}).get("details", {})
        ar_90 = fin_details.get("ar_90plus", 0)

        if proc_score > 0 and ar_90 > 0:
            # "If delays increase 20%, what happens?"
            simulated_proc = min(100, proc_score * 1.2)
            simulated_composite = composite + (simulated_proc - proc_score) * self._DOMAIN_WEIGHTS["procurement"]
            cash_impact_pct = round((simulated_composite - composite) / max(1, composite) * 100, 1)
            insight.findings.append(
                f"Scenario: If port delays increase 20%, composite risk rises to "
                f"{round(simulated_composite, 1)} (impact: +{cash_impact_pct}%)."
            )
            insight.metrics["scenario_delay_20pct"] = {
                "simulated_composite": round(simulated_composite, 1),
                "delta": round(simulated_composite - composite, 1),
            }

        # Domain-specific recommendations
        for domain, info in sorted_domains:
            if info["score"] >= 40:
                insight.recommendations.append(
                    f"Mitigate {domain} risk (score {info['score']}): "
                    f"review {', '.join(f'{k}={v}' for k, v in info['details'].items())}."
                )

        if errors:
            insight.risks.append("partial_data: some risk queries failed")

        insight.confidence_score = 0.85 if metrics.get("agent_caches_used", 0) >= 3 else 0.6
        return insight

    def write_cache(self, insight: Insight) -> None:
        cache = self.context.get("cache")
        ttl = self.context.get("cache_ttl_seconds", 300)
        if cache:
            cache.set(self.name, insight, ttl=ttl)

    def get_output_schema(self) -> Dict[str, Any]:
        return {
            "metrics": "dict (composite_risk_score, high_risk_domains, scenario_*)",
            "heatmap": "list[dict(domain, severity, likelihood, score, details)]",
            "domain_scores": "dict per domain with score + details",
        }
