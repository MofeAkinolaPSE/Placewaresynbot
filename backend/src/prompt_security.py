"""
Prompt injection defence utilities for ACE / Placeware LLM pipeline.

Covers:
- Direct injection: user input interpolated raw into prompts
- Context flooding: unbounded input length exhausting the context window
- Indirect injection: retrieved RAG chunks containing instruction hijacks
- History poisoning: stored chat messages replayed with embedded instructions

Usage:
    from src.prompt_security import sanitize_user_input, sanitize_rag_chunk, wrap_user_content
"""

from __future__ import annotations

import re
import logging

logger = logging.getLogger(__name__)

# Maximum characters allowed from a single user input before it enters any prompt.
# Chat messages are further capped at schema level (MessageCreate.content max_length=4000).
MAX_USER_INPUT_CHARS = 3000

# Maximum characters from a single RAG/history chunk inserted into a prompt.
MAX_RAG_CHUNK_CHARS = 1500

# Patterns that commonly appear in prompt injection attempts.
# Detects role-switch prefixes, meta-instruction markers, and jailbreak openers.
_INJECTION_PATTERNS = re.compile(
    r"(ignore\s+(previous|prior|all|above)\s+(instructions?|rules?|context|system|prompt))"
    r"|(system\s*:\s*)"
    r"|(assistant\s*:\s*)"
    r"|(<\|im_start\|>|<\|im_end\|>|<\|system\|>)"
    r"|(you\s+are\s+now\s+(a\s+)?(?:evil|unrestricted|jailbreak|dan))"
    r"|(do\s+anything\s+now)"
    r"|(reveal\s+(your\s+)?(system\s+)?prompt)"
    r"|(disregard\s+(all\s+)?(previous\s+)?instructions?)",
    re.IGNORECASE,
)


def sanitize_user_input(text: str, context: str = "user_input") -> str:
    """
    Sanitize user-supplied text before inserting into an LLM prompt.

    - Truncates to MAX_USER_INPUT_CHARS
    - Detects and logs common injection patterns (does not silently drop them;
      raises ValueError so callers can return a 400 to the user)
    """
    if not isinstance(text, str):
        text = str(text)

    # Truncate first to avoid regex running on unbounded input
    if len(text) > MAX_USER_INPUT_CHARS:
        logger.warning("prompt_security: input truncated from %d to %d chars [%s]", len(text), MAX_USER_INPUT_CHARS, context)
        text = text[:MAX_USER_INPUT_CHARS]

    match = _INJECTION_PATTERNS.search(text)
    if match:
        logger.warning("prompt_security: injection pattern detected in [%s]: %r", context, match.group(0))
        raise ValueError("Input contains patterns that are not permitted.")

    return text


def sanitize_rag_chunk(text: str) -> str:
    """
    Sanitize a retrieved RAG or chat-history chunk before inserting into an LLM prompt.
    Strips injection patterns and truncates — does NOT raise, since these come from
    internal storage rather than direct user input.
    """
    if not isinstance(text, str):
        text = str(text)
    if len(text) > MAX_RAG_CHUNK_CHARS:
        text = text[:MAX_RAG_CHUNK_CHARS]
    # Replace injection markers with a neutral placeholder
    text = _INJECTION_PATTERNS.sub("[filtered]", text)
    return text


def wrap_user_content(text: str) -> str:
    """
    Wrap user-supplied content in explicit XML-style delimiters so the model
    can distinguish between instructions (outside tags) and user data (inside tags).
    Apply this to all user text inserted into prompt templates.
    """
    return f"<user_input>{text}</user_input>"
