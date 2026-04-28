"""
AgentMemory Service
===================
Universal active-learning memory layer for all domain agents.

Every agent can:
  • store()  — persist high-quality findings as embeddings in Supabase
  • recall() — semantic search over its own past memories to inject historical
               context into the next run's prompts
  • score_and_prune() — remove stale low-quality memories (30-day TTL)

This creates a compound-interest effect: each agent run that stores a good
finding makes the next run smarter, which produces better findings, and so on.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# Minimum confidence score before a finding is persisted
STORE_THRESHOLD = 0.65
# Memories not used in this many days are candidates for pruning
PRUNE_AFTER_DAYS = 30
# Max memories stored per agent (oldest are evicted when exceeded)
MAX_MEMORIES_PER_AGENT = 200


class AgentMemory:
    """
    Interface to placeware_agent_memory.

    Usage (from any agent):
        memory = AgentMemory(agent_name="inventory_agent")
        historical = memory.recall(query_embedding=embedding, k=3)
        # ... use historical in your prompt ...
        memory.store(findings=insight.findings, confidence=insight.confidence_score)
    """

    def __init__(self, agent_name: str) -> None:
        self.agent_name = agent_name

    # ── Store ──────────────────────────────────────────────────────────────────

    def store(
        self,
        findings: List[str],
        confidence: float = 0.0,
        memory_type: str = "finding",
    ) -> None:
        """
        Persist the top findings from an agent run as vector memories.
        Only fires when confidence >= STORE_THRESHOLD to keep the store clean.
        """
        if confidence < STORE_THRESHOLD:
            return
        if not findings:
            return

        try:
            from src.db import db
            from src.embed_proxy import get_embedding

            # Store up to 3 findings per run to avoid flooding the table
            for finding in findings[:3]:
                if not finding or not finding.strip():
                    continue
                embedding = get_embedding(finding)
                row: Dict[str, Any] = {
                    "agent_name":    self.agent_name,
                    "memory_type":   memory_type,
                    "content":       finding,
                    "quality_score": round(confidence, 4),
                    "used_count":    0,
                }
                if embedding:
                    row["embedding"] = embedding

                db.table("placeware_agent_memory").insert(row).execute()

            self._evict_if_over_limit()
        except Exception as exc:
            # Memory write must never crash the agent
            logger.warning(f"AgentMemory.store failed for {self.agent_name}: {exc}")

    # ── Recall ─────────────────────────────────────────────────────────────────

    def recall(
        self,
        query_embedding: Optional[List[float]] = None,
        query_text: Optional[str] = None,
        k: int = 3,
        threshold: float = 0.70,
    ) -> List[str]:
        """
        Return up to k semantically similar past memories as plain text strings.
        Increments used_count on matched rows so frequently-used memories rank higher.

        Provide either query_embedding (preferred) or query_text (will embed it).
        """
        try:
            from src.db import db

            if query_embedding is None and query_text:
                from src.embed_proxy import get_embedding
                query_embedding = get_embedding(query_text)

            if query_embedding is None:
                return self._recall_latest(k)

            result = db.rpc(
                "match_agent_memories",
                {
                    "p_agent_name":    self.agent_name,
                    "query_embedding": query_embedding,
                    "match_threshold": threshold,
                    "match_count":     k,
                },
            ).execute()

            rows: List[Dict] = result.data or []
            ids = [r["id"] for r in rows if "id" in r]
            if ids:
                # Increment usage counters asynchronously (best effort)
                try:
                    for mid in ids:
                        db.table("placeware_agent_memory").update(
                            {"used_count": db.raw("used_count + 1"), "last_used_at": datetime.utcnow().isoformat()}  # type: ignore[arg-type]
                        ).eq("id", mid).execute()
                except Exception:
                    pass

            return [r["content"] for r in rows if r.get("content")]

        except Exception as exc:
            logger.warning(f"AgentMemory.recall failed for {self.agent_name}: {exc}")
            return self._recall_latest(k)

    # ── Pruning ────────────────────────────────────────────────────────────────

    def score_and_prune(self) -> int:
        """
        Delete memories older than PRUNE_AFTER_DAYS that have never been used.
        Returns count of deleted rows.
        """
        cutoff = (datetime.utcnow() - timedelta(days=PRUNE_AFTER_DAYS)).isoformat()
        try:
            from src.db import db
            result = (
                db.table("placeware_agent_memory")
                .delete()
                .eq("agent_name", self.agent_name)
                .eq("used_count", 0)
                .lt("created_at", cutoff)
                .execute()
            )
            deleted = len(result.data) if hasattr(result, "data") and result.data else 0
            if deleted:
                logger.info(f"AgentMemory.prune: removed {deleted} stale memories for {self.agent_name}")
            return deleted
        except Exception as exc:
            logger.warning(f"AgentMemory.score_and_prune failed: {exc}")
            return 0

    # ── Helpers ────────────────────────────────────────────────────────────────

    def _recall_latest(self, k: int) -> List[str]:
        """Fallback: return k most recent memories by created_at."""
        try:
            from src.db import db
            result = (
                db.table("placeware_agent_memory")
                .select("content")
                .eq("agent_name", self.agent_name)
                .order("created_at", desc=True)
                .limit(k)
                .execute()
            )
            return [r["content"] for r in (result.data or []) if r.get("content")]
        except Exception:
            return []

    def _evict_if_over_limit(self) -> None:
        """Remove the oldest low-quality memories if we exceed MAX_MEMORIES_PER_AGENT."""
        try:
            from src.db import db
            count_res = (
                db.table("placeware_agent_memory")
                .select("id", count="exact")
                .eq("agent_name", self.agent_name)
                .execute()
            )
            count = getattr(count_res, "count", None) or 0
            if count > MAX_MEMORIES_PER_AGENT:
                # Delete excess oldest rows
                excess = count - MAX_MEMORIES_PER_AGENT
                old_rows = (
                    db.table("placeware_agent_memory")
                    .select("id")
                    .eq("agent_name", self.agent_name)
                    .order("created_at", desc=False)
                    .limit(excess)
                    .execute()
                )
                for row in (old_rows.data or []):
                    db.table("placeware_agent_memory").delete().eq("id", row["id"]).execute()
        except Exception:
            pass
