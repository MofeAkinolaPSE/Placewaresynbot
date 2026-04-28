"""
EmailAgent — Intelligent email composition and delivery for EOS.
================================================================
Responsibilities:
  • Compose contextually-aware email content via LLM (subject + body)
  • Enforce per-department daily send quotas (default 50/day, config-driven)
  • Route to correct recipient(s) from config.yaml
  • Log every send attempt to placeware_email_send_log
  • Learn from past emails: feeds last 5 sent-to-dept subjects into compose
    prompt so tone and content improves over time
  • Graceful retry: 1 automatic retry on transient SMTP failure

Context keys consumed:
    intent_text   str  — raw user message (used for LLM composition)
    department    str  — target department key from config.yaml recipients
    actor_id      str  — user / session identifier for audit log
    simulation    bool — if True, skip actual send; return preview only
"""
from __future__ import annotations

import logging
import os
import time
from datetime import date
from typing import Any, Dict, List, Optional

from src.agent_registry import register_agent
from src.agents.base_agent import BaseAgent, Insight

logger = logging.getLogger(__name__)

# Daily send limit when config.yaml doesn't specify one
_DEFAULT_DAILY_LIMIT = 50

# Subjects from past emails fed as few-shot examples to the compose prompt
_HISTORY_FETCH_COUNT = 5


@register_agent
class EmailAgent(BaseAgent):
    """
    EOS-callable agent for composing and sending departmental emails.
    Integrates rate-limiting, delivery logging, and progressive learning.
    """

    name = "email_agent"
    required_role = None  # EOS dispatches as executive — no role gate

    # ── Lifecycle ──────────────────────────────────────────────────────────────

    def collect_data(self) -> Dict[str, Any]:
        """Load config, recipient, quota state, and past-send history."""
        department = (self.context.get("department") or "operations").lower()
        simulation = bool(self.context.get("simulation", False))

        cfg = self._load_config()
        recipients: Dict[str, str] = ((cfg.get("email") or {}).get("recipients")) or {}
        daily_limit: int = int(((cfg.get("email") or {}).get("daily_limit")) or _DEFAULT_DAILY_LIMIT)
        to_email: Optional[str] = recipients.get(department)

        quota = self._get_quota(department) if not simulation else {"sent_count": 0, "daily_limit": daily_limit}
        history = self._get_send_history(department, limit=_HISTORY_FETCH_COUNT)
        memories = self._get_memories()

        return {
            "department":   department,
            "to_email":     to_email,
            "daily_limit":  daily_limit,
            "quota":        quota,
            "history":      history,
            "memories":     memories,
            "cfg":          cfg,
        }

    def analyze(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Check quota and compose email content using the LLM."""
        quota      = data.get("quota", {})
        sent_count = int(quota.get("sent_count", 0))
        daily_limit = int(data.get("daily_limit", _DEFAULT_DAILY_LIMIT))
        to_email    = data.get("to_email")
        department  = data.get("department", "operations")
        intent_text = self.context.get("intent_text", "")
        simulation  = bool(self.context.get("simulation", False))

        # ── Quota gate ──────────────────────────────────────────────────────
        if sent_count >= daily_limit:
            return {
                "blocked":   True,
                "reason":    f"Daily email quota reached ({sent_count}/{daily_limit}) for '{department}'. "
                             "Try again tomorrow or contact IT to raise the limit.",
                "to_email":  to_email,
                "department": department,
            }

        # ── Recipient gate ───────────────────────────────────────────────────
        if not to_email:
            return {
                "blocked":   True,
                "reason":    f"No email address configured for department '{department}'. "
                             "Check email.recipients in config.yaml.",
                "department": department,
            }

        # ── LLM Compose ─────────────────────────────────────────────────────
        subject, body = self._compose(
            intent_text=intent_text,
            department=department,
            history=data.get("history", []),
            memories=data.get("memories", []),
            simulation=simulation,
        )

        return {
            "blocked":    False,
            "to_email":   to_email,
            "department": department,
            "subject":    subject,
            "body":       body,
            "sent_count": sent_count,
            "daily_limit": daily_limit,
            "simulation": simulation,
        }

    def generate_insights(self, analysis: Dict[str, Any]) -> Insight:
        """Send the email (if not blocked/simulated) and return an Insight."""
        if analysis.get("blocked"):
            return Insight(
                findings=[analysis.get("reason", "Email blocked.")],
                risks=["Email not sent."],
                confidence_score=1.0,
            )

        simulation  = analysis.get("simulation", False)
        to_email    = analysis["to_email"]
        subject     = analysis["subject"]
        body        = analysis["body"]
        department  = analysis["department"]
        actor_id    = self.context.get("actor_id", "eos")

        if simulation:
            return Insight(
                findings=[
                    f"[PREVIEW] Draft email for {department} ({to_email}).",
                    f"Subject: {subject}",
                    f"Body:\n{body}",
                ],
                recommendations=["Reply 'send it' to confirm, or describe what to change."],
                confidence_score=1.0,
                metrics={
                    "simulated":  True,
                    "to_email":   to_email,
                    "subject":    subject,
                    "body":       body,
                    "department": department,
                },
            )

        # ── Real send with 1 retry ───────────────────────────────────────────
        status = "sent"
        error_detail: Optional[str] = None
        for attempt in range(2):
            try:
                from src.services.messaging import send_email
                send_email(to_email=to_email, subject=subject, body=body)
                break
            except Exception as exc:
                error_detail = str(exc)
                logger.warning(f"EmailAgent send attempt {attempt + 1} failed: {exc}")
                if attempt == 0:
                    time.sleep(2)
                else:
                    status = "failed"

        # ── Log to Supabase ─────────────────────────────────────────────────
        self._log_send(
            department=department,
            to_email=to_email,
            subject=subject,
            body_preview=body[:500],
            status=status,
            error_detail=error_detail,
            actor_id=actor_id,
        )

        # ── Increment quota ─────────────────────────────────────────────────
        if status == "sent":
            self._increment_quota(department)

        # ── Store learning memory ────────────────────────────────────────────
        if status == "sent":
            from src.services.agent_memory import AgentMemory
            AgentMemory(self.name).store(
                findings=[f"Email to {department}: subject={subject!r}"],
                confidence=0.9,
                memory_type="finding",
            )

        if status == "failed":
            return Insight(
                findings=[f"Failed to send email to {department} ({to_email})."],
                risks=[f"SMTP error: {error_detail}"],
                recommendations=[
                    "Check EMAIL_FROM / EMAIL_PASS in .env.",
                    "Ensure Gmail 2FA is enabled and an App Password is set.",
                ],
                confidence_score=0.3,
            )

        return Insight(
            findings=[
                f"Email sent successfully to the {department} department ({to_email}).",
                f"Subject: {subject}",
            ],
            recommendations=[],
            confidence_score=1.0,
            metrics={"status": "sent", "to_email": to_email, "department": department},
        )

    def write_cache(self, insight: Insight) -> None:
        pass  # Delivery is already logged; no additional cache needed.

    def get_output_schema(self) -> Dict[str, Any]:
        return {
            "findings": "list[str]",
            "risks":    "list[str]",
            "metrics":  {"status": "str", "to_email": "str", "department": "str"},
        }

    # ── Private helpers ────────────────────────────────────────────────────────

    def _load_config(self) -> Dict[str, Any]:
        cfg_path = os.path.join(os.path.dirname(__file__), "..", "..", "config.yaml")
        try:
            import yaml
            with open(cfg_path, "r", encoding="utf-8") as f:
                return yaml.safe_load(f) or {}
        except Exception as exc:
            logger.error(f"EmailAgent: config load failed: {exc}")
            return {}

    def _get_quota(self, department: str) -> Dict[str, Any]:
        """Read or create today's quota row for this department."""
        try:
            from src.db import db
            today = date.today().isoformat()
            res = (
                db.table("placeware_email_quota")
                .select("*")
                .eq("department", department)
                .eq("quota_date", today)
                .execute()
            )
            rows = res.data or []
            if rows:
                return rows[0]
            # Auto-create today's row
            row = {"department": department, "quota_date": today, "sent_count": 0}
            db.table("placeware_email_quota").insert(row).execute()
            return row
        except Exception as exc:
            logger.warning(f"EmailAgent: quota fetch failed: {exc}")
            return {"sent_count": 0, "daily_limit": _DEFAULT_DAILY_LIMIT}

    def _increment_quota(self, department: str) -> None:
        try:
            from src.db import db
            today = date.today().isoformat()
            existing = (
                db.table("placeware_email_quota")
                .select("id, sent_count")
                .eq("department", department)
                .eq("quota_date", today)
                .execute()
            )
            rows = existing.data or []
            if rows:
                new_count = int(rows[0].get("sent_count", 0)) + 1
                db.table("placeware_email_quota").update({"sent_count": new_count}).eq("id", rows[0]["id"]).execute()
        except Exception as exc:
            logger.warning(f"EmailAgent: quota increment failed: {exc}")

    def _get_send_history(self, department: str, limit: int = 5) -> List[Dict[str, Any]]:
        """Fetch recent successful sends to this department for few-shot context."""
        try:
            from src.db import db
            res = (
                db.table("placeware_email_send_log")
                .select("subject, body_preview, created_at")
                .eq("department", department)
                .eq("status", "sent")
                .order("created_at", desc=True)
                .limit(limit)
                .execute()
            )
            return res.data or []
        except Exception:
            return []

    def _get_memories(self) -> List[str]:
        """Recall relevant agent memories to improve compose prompt."""
        try:
            from src.services.agent_memory import AgentMemory
            intent_text = self.context.get("intent_text", "")
            return AgentMemory(self.name).recall(query_text=intent_text, k=3)
        except Exception:
            return []

    def _log_send(
        self,
        department: str,
        to_email: str,
        subject: str,
        body_preview: str,
        status: str,
        error_detail: Optional[str],
        actor_id: str,
    ) -> None:
        try:
            from src.db import db
            db.table("placeware_email_send_log").insert({
                "department":   department,
                "to_email":     to_email,
                "subject":      subject,
                "body_preview": body_preview,
                "status":       status,
                "error_detail": error_detail,
                "actor_id":     actor_id,
            }).execute()
        except Exception as exc:
            logger.warning(f"EmailAgent: log_send failed: {exc}")

    def _compose(
        self,
        intent_text: str,
        department: str,
        history: List[Dict[str, Any]],
        memories: List[str],
        simulation: bool,
    ) -> tuple[str, str]:
        """Use DeepSeek to generate a professional subject line and email body."""
        from src.constants import BOT_NAME, BOT_BRAND

        # ── Precomposed passthrough — skip LLM if draft already exists ────────
        precomposed_subject = self.context.get("precomposed_subject")
        precomposed_body    = self.context.get("precomposed_body")
        if precomposed_subject and precomposed_body:
            return precomposed_subject, precomposed_body

        history_block = ""
        if history:
            lines = [f"  - Subject: {h.get('subject', '')}" for h in history[:3]]
            history_block = "\nRecent emails to this department (tone reference only):\n" + "\n".join(lines)

        memory_block = ""
        if memories:
            memory_block = "\nContext:\n" + "\n".join(f"  - {m}" for m in memories[:2])

        prompt = f"""You are {BOT_NAME}, the AI executive assistant for {BOT_BRAND}.
Write a concise, professional internal email based ONLY on what was explicitly requested.

User's request: "{intent_text}"
Target department: {department}
{history_block}
{memory_block}

Strict rules:
- Keep it SHORT: greeting line + 1-2 sentences of body + closing. 3 paragraphs maximum.
- Base content STRICTLY on what the user said. Do NOT invent meeting locations, urgency,
  attendance rules, penalties, operational instructions, or any detail not mentioned.
- If the request is simple (e.g. "tell them there's a meeting at 12"), the email should
  be equally simple and direct — do not embellish.
- Professional but natural tone. No corporate jargon or dramatic language.
- End with: "Best regards,\\n{BOT_BRAND} Executive Team"

Output format (exactly):
SUBJECT: <concise subject line>
BODY:
<email body>
"""

        subject = f"Internal Update from {BOT_BRAND} Executive Team"
        body = intent_text  # Fallback

        try:
            from src.deepseek import DeepSeek
            llm = DeepSeek(os.getenv("DEEPSEEK_API_KEY", ""))
            response = llm.generate_response(
                context="",
                question=prompt,
                instruction="You are a professional business email writer. Output ONLY the email in the specified format.",
            )

            lines = response.strip().split("\n")
            subject_line = next((l for l in lines if l.upper().startswith("SUBJECT:")), None)
            if subject_line:
                subject = subject_line.split(":", 1)[1].strip()

            body_start = next((i for i, l in enumerate(lines) if l.upper().startswith("BODY:")), None)
            if body_start is not None:
                body = "\n".join(lines[body_start + 1:]).strip()
            else:
                body = response.strip()

        except Exception as exc:
            logger.error(f"EmailAgent: LLM compose failed: {exc}")
            # Fallback: plain passthrough body
            body = (
                f"This message was sent via {BOT_NAME}:\n\n{intent_text}\n\n"
                f"Best regards,\n{BOT_BRAND} Executive Team"
            )

        return subject, body
