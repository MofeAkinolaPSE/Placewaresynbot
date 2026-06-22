import logging
from .constants import (
    MATCH_THRESHOLD,
)
from .db import db
from .prompt_security import sanitize_rag_chunk


class QnARetriever:
    def __init__(self, match_threshold: float | None = None):
        self.match_threshold = match_threshold if match_threshold is not None else MATCH_THRESHOLD

    def retrieve(self, embedding, k: int = 1):
        try:
            payload = {
                "query_embedding": embedding,
                "match_threshold": self.match_threshold,
                "match_count": k,
            }
            logging.info(f"Calling match_documents threshold={self.match_threshold} k={k}")
            results = db.rpc("match_documents", payload).execute()
            rows = results.data or []
            logging.info(f"Knowledge base (local DB) returned {len(rows)} rows")
            return [
                (sanitize_rag_chunk(row.get("question") or ""), sanitize_rag_chunk(row.get("answer") or ""))
                for row in rows
            ]
        except Exception as e:
            logging.error(f"QnARetriever error: {e}")
            return []  # Fallback path if retrieval fails