from supabase import create_client, Client
import os
from dotenv import load_dotenv
import logging
from .constants import (
    ENV_SUPABASE_URL,
    ENV_SUPABASE_KEY,
    MATCH_THRESHOLD,
)

load_dotenv()

SUPABASE_URL = os.getenv(ENV_SUPABASE_URL)
SUPABASE_KEY = os.getenv(ENV_SUPABASE_KEY)
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)


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
            logging.info(
                f"Calling match_documents threshold={self.match_threshold} k={k}"
            )
            results = supabase.rpc("match_documents", payload).execute()
            rows = results.data or []
            logging.info(f"Supabase returned {len(rows)} rows")
            return [(row.get("question"), row.get("answer")) for row in rows]
        except Exception as e:
            logging.error(f"QnARetriever error: {e}")
            return []  # Fallback path if retrieval fails