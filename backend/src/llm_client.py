"""LLM microservice client abstraction.

Replaces previous DeepSeek direct integration. Expects an external service
reachable via LLM_SERVICE_URL that accepts JSON:
{
  "context": str,
  "question": str,
  "instruction": optional str
}
and returns {"answer": str}.

If the service returns a non-200 or malformed payload, an empty string is
returned so the caller can trigger fallback logic.
"""

from __future__ import annotations
import os
import logging
import requests
from .constants import (
    LLM_SERVICE_URL,
    LLM_API_KEY,
    BOT_NAME,
    BOT_BRAND,
    LLM_SPACE_URL,
    LLM_SPACE_API_NAME,
    LLM_SPACE_API_KEY,
)

try:
    from gradio_client import Client as GradioClient  # lightweight optional dep
except Exception:  # pragma: no cover
    GradioClient = None  # type: ignore


class LLMClient:
    def __init__(self, base_url: str | None = None, api_key: str | None = None, space_url: str | None = None):
        self.base_url = base_url or LLM_SERVICE_URL
        self.api_key = api_key or LLM_API_KEY
        self.space_url = space_url or LLM_SPACE_URL
        if not self.base_url and not self.space_url:
            logging.warning("Neither LLM_SERVICE_URL nor LLM_SPACE_URL set; responses will fallback.")

    def _headers(self) -> dict:
        h = {"Content-Type": "application/json"}
        if self.api_key:
            h["Authorization"] = f"Bearer {self.api_key}"
        return h

    def generate_response(self, context: str, question: str, instruction: str | None = None) -> str:
        instruction = instruction or f"You are {BOT_NAME} for {BOT_BRAND}. Use the context succinctly."

        # Prefer HTTP microservice if defined
        if self.base_url:
            payload = {"context": context or "", "question": question, "instruction": instruction}
            try:
                resp = requests.post(
                    self.base_url.rstrip("/") + "/generate",
                    json=payload,
                    headers=self._headers(),
                    timeout=40,
                )
                if resp.status_code != 200:
                    logging.error(f"LLM service error {resp.status_code}: {resp.text[:200]}")
                else:
                    data = resp.json()
                    answer = data.get("answer") or data.get("output") or data.get("response") or ""
                    if isinstance(answer, str):
                        return answer.strip()
            except Exception as e:
                logging.error(f"LLM service exception: {e}")

        # Fall back to HF Space if configured
        if self.space_url and GradioClient:
            try:
                client = GradioClient(self.space_url)
                # Common pattern: pass combined prompt
                prompt = f"Instruction: {instruction}\n\nContext:\n{context}\n\nQuestion: {question}\nAnswer:"
                result = client.predict(prompt, api_name=LLM_SPACE_API_NAME or "/predict")
                # Try common result shapes
                if isinstance(result, str):
                    return result.strip()
                if isinstance(result, dict):
                    for key in ("answer", "output", "text"):
                        if key in result and isinstance(result[key], str):
                            return result[key].strip()
                if isinstance(result, list) and result and isinstance(result[0], str):
                    return result[0].strip()
            except Exception as e:
                logging.error(f"HF Space generation error: {e}")

        return ""
