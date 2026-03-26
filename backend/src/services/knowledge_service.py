"""knowledge_service.py — Multi-stage RAG retrieval engine for SynBot.

Pipeline (in order):
  1. Memory check     — fast path: if a matching synbot_memory entry exists,
                        return it immediately without hitting the vector DB.
  2. Query rewrite    — DeepSeek expands the user's query with domain synonyms
                        to improve recall.
  3. Broad retrieval  — cosine-similarity search in knowledge_chunks (top_k=20).
  4. LLM re-rank      — DeepSeek scores and re-orders the retrieved chunks by
                        relevance to the *original* query.
  5. Context compress — keep only the top N chunks (default 5).
  6. Gap detection    — if best similarity < GAP_THRESHOLD, log to knowledge_gaps.

Usage:
    from src.services.knowledge_service import KnowledgeService
    svc = KnowledgeService()
    result = svc.search("fumigation deviation corrective action", department="quality")
    # result.chunks  — list of best chunks (content + metadata + similarity)
    # result.context — joined text ready for an LLM prompt
    # result.gap_logged — True if a knowledge gap was recorded
"""
from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field
from typing import Any

import psycopg2

from src.embed_proxy import get_embedding

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

BROAD_TOP_K     = int(os.getenv("KNOWLEDGE_BROAD_TOP_K",   "20"))
FINAL_TOP_K     = int(os.getenv("KNOWLEDGE_FINAL_TOP_K",   "5"))
GAP_THRESHOLD   = float(os.getenv("KNOWLEDGE_GAP_THRESHOLD", "0.55"))
MEMORY_ENABLED  = os.getenv("KNOWLEDGE_MEMORY_ENABLED", "1") not in ("0", "false")


# ---------------------------------------------------------------------------
# Return types
# ---------------------------------------------------------------------------

@dataclass
class ChunkResult:
    document_id: str
    chunk_index: int
    content: str
    metadata: dict[str, Any]
    similarity: float


@dataclass
class SearchResult:
    chunks: list[ChunkResult] = field(default_factory=list)
    context: str = ""
    gap_logged: bool = False
    memory_hit: bool = False
    query_used: str = ""


# ---------------------------------------------------------------------------
# Database helpers
# ---------------------------------------------------------------------------

def _get_db():
    dsn = os.getenv("DATABASE_URL")
    if not dsn:
        raise RuntimeError("DATABASE_URL is not set")
    return psycopg2.connect(dsn)


# ---------------------------------------------------------------------------
# Stage 1 — Memory check
# ---------------------------------------------------------------------------

def _check_memory(topic: str) -> str | None:
    """Return the summary of a matching synbot_memory entry, or None."""
    if not MEMORY_ENABLED:
        return None
    try:
        conn = _get_db()
        cur  = conn.cursor()
        cur.execute(
            """
            SELECT summary
            FROM synbot_memory
            WHERE lower(topic) LIKE lower(%s)
              AND confidence >= 0.7
            ORDER BY confidence DESC, hit_count DESC
            LIMIT 1
            """,
            (f"%{topic}%",),
        )
        row = cur.fetchone()
        if row:
            # Increment hit_count for analytics
            cur.execute(
                "UPDATE synbot_memory SET hit_count = hit_count + 1 WHERE lower(topic) LIKE lower(%s)",
                (f"%{topic}%",),
            )
            conn.commit()
        cur.close()
        conn.close()
        return row[0] if row else None
    except Exception as exc:
        logger.warning("Memory check failed: %s", exc)
        return None


# ---------------------------------------------------------------------------
# Stage 2 — Query rewrite
# ---------------------------------------------------------------------------

def _rewrite_query(raw_query: str, llm) -> str:
    """Expand the raw query with domain keywords for better retrieval recall."""
    if llm is None:
        return raw_query
    try:
        instruction = (
            "You are a query expansion assistant for a pharmaceutical company's QMS knowledge base. "
            "Your job is to rewrite the user's query to be more retrieval-friendly by adding relevant "
            "domain synonyms, related terms, and operational keywords. "
            "Return ONLY the rewritten query string — no explanations, no bullet points."
        )
        expanded = llm.generate_response(
            context="",
            question=raw_query,
            instruction=instruction,
        )
        expanded = expanded.strip().strip('"').strip("'")
        if expanded and len(expanded) < 500:
            logger.debug("Query rewritten: '%s' → '%s'", raw_query, expanded)
            return expanded
    except Exception as exc:
        logger.warning("Query rewrite failed, using original: %s", exc)
    return raw_query


# ---------------------------------------------------------------------------
# Stage 3 — Vector retrieval
# ---------------------------------------------------------------------------

def _vector_search(
    query_embedding: list[float],
    top_k: int = BROAD_TOP_K,
    department: str | None = None,
    document_type: str | None = None,
) -> list[ChunkResult]:
    """Call the match_knowledge_chunks SQL function."""
    try:
        conn = _get_db()
        cur  = conn.cursor()
        cur.execute(
            """
            SELECT id, document_id, chunk_index, content, metadata, similarity
            FROM match_knowledge_chunks(
                %s::vector,
                %s,   -- match_threshold
                %s,   -- match_count
                %s,   -- filter_department
                %s    -- filter_doc_type
            )
            """,
            (query_embedding, GAP_THRESHOLD, top_k, department, document_type),
        )
        rows = cur.fetchall()
        cur.close()
        conn.close()

        results: list[ChunkResult] = []
        for row in rows:
            meta = row[4]
            if isinstance(meta, str):
                try:
                    meta = json.loads(meta)
                except Exception:
                    meta = {}
            results.append(
                ChunkResult(
                    document_id=row[1],
                    chunk_index=row[2],
                    content=row[3],
                    metadata=meta or {},
                    similarity=float(row[5]),
                )
            )
        return results
    except Exception as exc:
        logger.error("Vector search failed: %s", exc)
        return []


# ---------------------------------------------------------------------------
# Stage 4 — LLM re-rank
# ---------------------------------------------------------------------------

def _rerank(
    original_query: str,
    chunks: list[ChunkResult],
    llm,
    final_top_k: int = FINAL_TOP_K,
) -> list[ChunkResult]:
    """Ask DeepSeek to score each chunk 0-10 for relevance to the query.

    Falls back to similarity-sorted ordering if the LLM call fails.
    """
    if llm is None or not chunks:
        return sorted(chunks, key=lambda c: c.similarity, reverse=True)[:final_top_k]

    # Build a compact prompt listing all chunks by index
    chunk_list = "\n".join(
        f"[{i}] {c.content[:300]}" for i, c in enumerate(chunks)
    )
    instruction = (
        "You are a relevance scoring assistant. "
        "Given a user query and a numbered list of text chunks, "
        "return a JSON array of objects [{\"index\": <i>, \"score\": <0-10>}] "
        "where score 10 = perfectly relevant, 0 = irrelevant. "
        "Return ONLY the JSON array, no explanation."
    )
    prompt = (
        f"Query: {original_query}\n\n"
        f"Chunks:\n{chunk_list}\n\n"
        "Score each chunk."
    )

    try:
        raw = llm.generate_response(context="", question=prompt, instruction=instruction)
        # Extract JSON array from the response
        start = raw.find("[")
        end   = raw.rfind("]") + 1
        if start >= 0 and end > start:
            scores = json.loads(raw[start:end])
            score_map: dict[int, float] = {
                int(s["index"]): float(s["score"])
                for s in scores
                if "index" in s and "score" in s
            }
            ranked = sorted(
                enumerate(chunks),
                key=lambda t: score_map.get(t[0], 0.0),
                reverse=True,
            )
            return [c for _, c in ranked[:final_top_k]]
    except Exception as exc:
        logger.warning("Re-rank failed, falling back to similarity order: %s", exc)

    # Fallback: sort by similarity
    return sorted(chunks, key=lambda c: c.similarity, reverse=True)[:final_top_k]


# ---------------------------------------------------------------------------
# Stage 6 — Knowledge gap logging
# ---------------------------------------------------------------------------

def _log_gap(
    query: str,
    best_similarity: float,
    agent: str | None,
    department: str | None,
    document_type: str | None,
) -> None:
    """Record a knowledge gap so admins can identify missing documents."""
    try:
        conn = _get_db()
        cur  = conn.cursor()
        cur.execute(
            """
            INSERT INTO knowledge_gaps
                (query, agent, department, document_type, best_similarity, status)
            VALUES (%s, %s, %s, %s, %s, 'pending')
            """,
            (query, agent, department, document_type, best_similarity),
        )
        conn.commit()
        cur.close()
        conn.close()
        logger.info(
            "Knowledge gap logged — query: '%s', best_sim: %.3f",
            query[:80],
            best_similarity,
        )
    except Exception as exc:
        logger.warning("Could not log knowledge gap: %s", exc)


# ---------------------------------------------------------------------------
# Public service
# ---------------------------------------------------------------------------

class KnowledgeService:
    """Multi-stage RAG retrieval service.

    Args:
        llm: A DeepSeek (or compatible) LLM instance.  If None, query rewrite
             and re-ranking are skipped (similarity order is used instead).
    """

    def __init__(self, llm=None):
        self._llm = llm

    def search(
        self,
        query: str,
        department: str | None = None,
        document_type: str | None = None,
        agent: str | None = None,
        top_k: int = FINAL_TOP_K,
    ) -> SearchResult:
        """Run the full multi-stage retrieval pipeline.

        Args:
            query:         Natural language query.
            department:    Optional filter (e.g. 'quality', 'operations').
            document_type: Optional filter (e.g. 'audit_report').
            agent:         Name of the calling agent (for gap logging).
            top_k:         Number of final chunks to return.

        Returns:
            SearchResult with .chunks, .context, .gap_logged, .memory_hit
        """
        result = SearchResult(query_used=query)

        # ── Stage 1: Memory check ──────────────────────────────────────────
        memory_summary = _check_memory(query)
        if memory_summary:
            logger.info("Memory hit for query: '%s'", query[:60])
            result.memory_hit = True
            result.context    = memory_summary
            return result

        # ── Stage 2: Query rewrite ─────────────────────────────────────────
        rewritten = _rewrite_query(query, self._llm)
        result.query_used = rewritten

        # ── Stage 3: Embed rewritten query ────────────────────────────────
        embedding = get_embedding(rewritten)
        if embedding is None:
            logger.error("Embedding failed for query; aborting retrieval.")
            return result

        # ── Stage 3: Broad vector retrieval ───────────────────────────────
        chunks = _vector_search(
            query_embedding=embedding,
            top_k=BROAD_TOP_K,
            department=department,
            document_type=document_type,
        )

        if not chunks:
            logger.info("No chunks retrieved for query: '%s'", query[:60])
            _log_gap(query, 0.0, agent, department, document_type)
            result.gap_logged = True
            return result

        best_sim = max(c.similarity for c in chunks)

        # ── Stage 4: LLM re-rank ──────────────────────────────────────────
        top_chunks = _rerank(query, chunks, self._llm, final_top_k=top_k)
        result.chunks = top_chunks

        # ── Stage 5: Assemble context ─────────────────────────────────────
        context_parts = [
            f"[Source: {c.metadata.get('document_type', 'document')} | "
            f"{c.metadata.get('department', '')}]\n{c.content}"
            for c in top_chunks
        ]
        result.context = "\n\n---\n\n".join(context_parts)

        # ── Stage 6: Gap detection ─────────────────────────────────────────
        if best_sim < GAP_THRESHOLD:
            _log_gap(query, best_sim, agent, department, document_type)
            result.gap_logged = True

        logger.info(
            "Knowledge search done — query: '%s', chunks: %d, best_sim: %.3f, gap: %s",
            query[:60],
            len(top_chunks),
            best_sim,
            result.gap_logged,
        )
        return result


# ---------------------------------------------------------------------------
# Memory write helper (called by agents after solving an investigation)
# ---------------------------------------------------------------------------

def store_memory(
    topic: str,
    summary: str,
    memory_type: str = "investigation",
    source_query: str | None = None,
    agent: str | None = None,
    department: str | None = None,
    confidence: float = 0.9,
) -> None:
    """Persist a solved investigation or pattern into synbot_memory."""
    try:
        conn = _get_db()
        cur  = conn.cursor()
        cur.execute(
            """
            INSERT INTO synbot_memory
                (memory_type, topic, summary, source_query, agent, department, confidence)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            """,
            (memory_type, topic, summary, source_query, agent, department, confidence),
        )
        conn.commit()
        cur.close()
        conn.close()
        logger.info("Stored memory: [%s] %s", memory_type, topic[:60])
    except Exception as exc:
        logger.warning("Could not store memory: %s", exc)
