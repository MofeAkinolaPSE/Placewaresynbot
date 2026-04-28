"""
LeadFinderAgent — Location-intelligence prospect discovery for EOS.
===================================================================
Responsibilities:
  • Accept a location + business_type from natural-language context
  • Call places_service.search_places() (Google Places API or mock)
  • Deduplicate new results against existing crm_prospects by place_id
  • Write net-new prospects to crm_prospects with Places enrichment
  • Return an Insight describing what was found / added

Context keys consumed:
    intent_text    str  — raw user utterance (for memory recall)
    location       str  — e.g. "Lekki, Lagos" (required)
    business_type  str  — e.g. "pharmacy" (default: "pharmacy")
    radius_m       int  — search radius in metres (default: 5000)
    limit          int  — max results to fetch (default: 20)
    industry       str  — industry tag for crm_prospects (default: "pharma")
    simulation     bool — if True, skip DB writes (dry run)
    actor_id       str  — for audit trail
"""
from __future__ import annotations

import logging
import time
from typing import Any, Dict, List, Optional

from src.agent_registry import register_agent
from src.agents.base_agent import BaseAgent, Insight

logger = logging.getLogger(__name__)


@register_agent
class LeadFinderAgent(BaseAgent):
    """EOS-callable agent: discover pharma/healthcare leads by location."""

    name          = "lead_finder_agent"
    required_role = "crm"

    # ── BaseAgent lifecycle ─────────────────────────────────────────────────

    def collect_data(self) -> Dict[str, Any]:
        """Pull location params from context; load existing place_ids for dedup."""
        location      = (self.context.get("location") or "Lagos, Nigeria").strip()
        business_type = (self.context.get("business_type") or "pharmacy").strip()
        radius_m      = int(self.context.get("radius_m") or 5000)
        limit         = int(self.context.get("limit") or 20)
        industry      = (self.context.get("industry") or "pharma").strip()

        # Fetch existing place_ids to enable deduplication without a JOIN
        existing_place_ids: set[str] = set()
        try:
            import src.db as _db
            res = _db.table("crm_prospects").select("place_id").execute()
            for row in (res.data or []):
                pid = row.get("place_id")
                if pid:
                    existing_place_ids.add(pid)
        except Exception:
            logger.exception("LeadFinderAgent: could not load existing place_ids")

        return {
            "location":           location,
            "business_type":      business_type,
            "radius_m":           radius_m,
            "limit":              limit,
            "industry":           industry,
            "existing_place_ids": existing_place_ids,
        }

    def analyze(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Call Places API / mock; filter out duplicates."""
        from src.services.places_service import search_places

        location      = data["location"]
        business_type = data["business_type"]
        radius_m      = data["radius_m"]
        limit         = data["limit"]
        existing      = data["existing_place_ids"]

        raw_results: List[dict] = []
        try:
            raw_results = search_places(
                location=location,
                business_type=business_type,
                radius_m=radius_m,
                limit=limit,
            )
        except Exception:
            logger.exception("LeadFinderAgent: places search failed")

        new_prospects = []
        skipped = 0
        for place in raw_results:
            pid = place.get("place_id")
            if pid and pid in existing:
                skipped += 1
                continue
            new_prospects.append(place)

        return {
            "location":      location,
            "business_type": business_type,
            "industry":      data["industry"],
            "new_prospects": new_prospects,
            "skipped":       skipped,
            "total_found":   len(raw_results),
        }

    def generate_insights(self, analysis: Dict[str, Any]) -> Insight:
        """Persist net-new prospects and build a human-readable Insight."""
        simulation     = bool(self.context.get("simulation", False))
        actor_id       = self.context.get("actor_id", "eos_chat")
        new_prospects  = analysis["new_prospects"]
        skipped        = analysis["skipped"]
        total_found    = analysis["total_found"]
        location       = analysis["location"]
        business_type  = analysis["business_type"]
        industry       = analysis["industry"]

        inserted: List[dict] = []
        insert_errors = 0

        if not simulation:
            try:
                import src.db as _db
                for place in new_prospects:
                    row = {
                        "company_name":      place.get("company_name") or place.get("name", "Unknown"),
                        "industry":          industry,
                        "region":            location,
                        "formatted_address": place.get("formatted_address"),
                        "phone_number":      place.get("phone_number"),
                        "website":           place.get("website"),
                        "rating":            place.get("rating"),
                        "user_ratings_total": place.get("user_ratings_total"),
                        "places_score":      place.get("places_score"),
                        "place_id":          place.get("place_id"),
                        "lat":               place.get("lat"),
                        "lng":               place.get("lng"),
                        "source":            place.get("source", "places_api"),
                        "search_query":      f"{business_type} in {location}",
                        "status":            "new",
                    }
                    try:
                        res = _db.table("crm_prospects").insert(row).execute()
                        if hasattr(res, "data") and res.data:
                            inserted.append(res.data[0])
                    except Exception:
                        logger.exception(
                            "LeadFinderAgent: insert failed for %s", row.get("company_name")
                        )
                        insert_errors += 1
            except Exception:
                logger.exception("LeadFinderAgent: DB write phase failed")
        else:
            # Simulation: treat all new prospects as "would insert"
            inserted = new_prospects

        # ── Build human-readable Insight ─────────────────────────────────────
        added_count = len(inserted)
        findings: List[str] = []

        if simulation:
            findings.append(
                f"[SIMULATION] Would add {added_count} new leads in '{location}' "
                f"({business_type}) — {skipped} duplicates would be skipped."
            )
        else:
            findings.append(
                f"Found {total_found} '{business_type}' businesses near {location}. "
                f"Added {added_count} new prospects to CRM "
                f"({skipped} duplicates skipped, {insert_errors} errors)."
            )

        # Top-5 preview lines
        for p in new_prospects[:5]:
            name  = p.get("company_name") or p.get("name", "–")
            score = p.get("places_score", 0)
            addr  = p.get("formatted_address", "")
            findings.append(f"• {name} — score {score}  {addr}")

        if len(new_prospects) > 5:
            findings.append(f"  … and {len(new_prospects) - 5} more")

        recommendations: List[str] = []
        if added_count > 0 and not simulation:
            recommendations.append(
                "Go to CRM → Lead Finder → Discover to score and assign the new prospects."
            )
        if insert_errors > 0:
            recommendations.append(
                f"{insert_errors} row(s) failed to insert — check DB logs for details."
            )

        confidence = 0.95 if added_count > 0 else 0.6

        # ── Persist agent memory ─────────────────────────────────────────────
        try:
            from src.services.agent_memory import AgentMemory
            AgentMemory(self.name).store(
                findings=[findings[0]],
                confidence=confidence,
            )
        except Exception:
            pass

        return Insight(
            findings=findings,
            recommendations=recommendations,
            confidence_score=confidence,
            metrics={
                "location":      location,
                "business_type": business_type,
                "total_found":   total_found,
                "added":         added_count,
                "skipped":       skipped,
                "simulation":    simulation,
            },
        )

    def write_cache(self, insight: Insight) -> None:
        """Update prospect_search_cache with result count."""
        try:
            from src.services.places_service import cache_key as _ck
            import src.db as _db

            loc  = self.context.get("location", "")
            biz  = self.context.get("business_type", "pharmacy")
            rad  = int(self.context.get("radius_m") or 5000)
            key  = _ck(loc, biz, rad)

            added = insight.metrics.get("added", 0)
            _db.table("prospect_search_cache").upsert({
                "query_key":       key,
                "search_location": loc,
                "business_type":   biz,
                "radius_m":        rad,
                "result_count":    added,
            }).execute()
        except Exception:
            logger.exception("LeadFinderAgent: cache write failed (non-fatal)")

    def get_output_schema(self) -> Dict[str, Any]:
        return {
            "findings":        "list[str]",
            "recommendations": "list[str]",
            "metrics": {
                "location":      "str",
                "business_type": "str",
                "total_found":   "int",
                "added":         "int",
                "skipped":       "int",
                "simulation":    "bool",
            },
        }
