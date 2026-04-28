"""
CalendarAgent — Smart scheduling and calendar management for EOS.
=================================================================
Responsibilities:
  • Parse meeting details (title, time, duration, attendees) from free-form text
  • Detect time conflicts in placeware_calendar_events before inserting
  • Suggest the next available slot when a conflict exists
  • Create, update, or list events via Supabase
  • Log every parse attempt to placeware_calendar_agent_log for few-shot learning
  • Recall past successful parse examples to improve title/time extraction

Context keys consumed:
    intent_text   str  — raw user message
    action        str  — 'create' | 'list' | 'cancel' (default: 'create')
    actor_id      str  — for audit log
    simulation    bool — if True, skip Supabase write
"""
from __future__ import annotations

import logging
import re
import os
from datetime import datetime, timedelta, timezone, date
from typing import Any, Dict, List, Optional, Tuple

from src.agent_registry import register_agent
from src.agents.base_agent import BaseAgent, Insight

logger = logging.getLogger(__name__)

# Business-hours window for auto-rescheduling (UTC)
_BUSINESS_START_HOUR = 8   # 08:00 UTC
_BUSINESS_END_HOUR   = 17  # 17:00 UTC

# Default durations by meeting type keyword
_DURATION_MAP = {
    "review":    120,
    "board":     120,
    "strategy":  120,
    "audit":     90,
    "briefing":  60,
    "meeting":   60,
    "standup":   30,
    "sync":      30,
    "call":      30,
    "catchup":   30,
    "catch-up":  30,
}


@register_agent
class CalendarAgent(BaseAgent):
    """
    EOS-callable agent for intelligent calendar management.
    Learns from previous scheduling interactions to improve parsing accuracy.
    """

    name = "calendar_agent"
    required_role = None

    # ── Lifecycle ──────────────────────────────────────────────────────────────

    def collect_data(self) -> Dict[str, Any]:
        """Parse intent text and load past examples for few-shot context."""
        intent_text = self.context.get("intent_text", "")
        few_shot    = self._get_few_shot_examples()
        memories    = self._get_memories()
        return {
            "intent_text": intent_text,
            "few_shot":    few_shot,
            "memories":    memories,
        }

    def analyze(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Use LLM + regex to extract event details; check for conflicts."""
        intent_text = data.get("intent_text", "")
        few_shot    = data.get("few_shot", [])
        memories    = data.get("memories", [])

        parsed = self._parse_event(intent_text, few_shot, memories)
        action = self.context.get("action", "create")

        if action == "list":
            events = self._list_upcoming()
            return {"action": "list", "events": events}

        if action == "cancel":
            return {"action": "cancel", "parsed": parsed, "intent_text": intent_text}

        # Default: create
        conflict, suggestion = self._check_conflict(parsed["start"], parsed["end"])
        if conflict:
            # Auto-reschedule to suggested slot
            duration_min = parsed.get("duration_min", 60)
            parsed["start"] = suggestion
            parsed["end"]   = suggestion + timedelta(minutes=duration_min)
            parsed["conflict_resolved"] = True
        else:
            parsed["conflict_resolved"] = False

        return {
            "action":  "create",
            "parsed":  parsed,
            "conflict_was_detected": conflict,
        }

    def generate_insights(self, analysis: Dict[str, Any]) -> Insight:
        """Execute the calendar action and return a human-readable Insight."""
        action     = analysis.get("action", "create")
        simulation = bool(self.context.get("simulation", False))
        actor_id   = self.context.get("actor_id", "eos")

        if action == "list":
            events = analysis.get("events", [])
            lines = [
                f"• {e.get('title')} — {e.get('start_time', '')[:16]}"
                for e in events[:10]
            ]
            return Insight(
                findings=lines or ["No upcoming events found."],
                confidence_score=1.0,
            )

        parsed = analysis.get("parsed", {})
        title  = parsed.get("title", "Meeting")
        start  = parsed.get("start")
        end    = parsed.get("end")
        attendees = parsed.get("attendees", [])

        if not start:
            return Insight(
                findings=["Could not determine a meeting time from the request."],
                risks=["No event created."],
                recommendations=["Try: 'Schedule a meeting tomorrow at 3pm'"],
                confidence_score=0.2,
            )

        start_str = start.strftime("%Y-%m-%dT%H:%M:%SZ")
        end_str   = end.strftime("%Y-%m-%dT%H:%M:%SZ")

        if simulation:
            msg = (
                f"[SIMULATION] Would schedule: {title}\n"
                f"Start: {start_str}   End: {end_str}"
            )
            if parsed.get("conflict_resolved"):
                msg += "\n(Original slot had a conflict — rescheduled automatically.)"
            return Insight(
                findings=[msg],
                confidence_score=1.0,
                metrics={"simulated": True, "title": title},
            )

        # ── Write to Supabase ────────────────────────────────────────────────
        event_id: Optional[str] = None
        try:
            import json as _json
            from src.db import db
            row = {
                "title":       title,
                "description": f"Scheduled via CalendarAgent: {self.context.get('intent_text', '')}",
                "event_type":  parsed.get("event_type", "meeting"),
                "start_time":  start_str,
                "end_time":    end_str,
                "all_day":     False,
                "location":    parsed.get("location"),
                "attendees":   _json.dumps(attendees),
                "metadata":    _json.dumps({"created_via": "calendar_agent", "actor_id": actor_id}),
            }
            res = db.table("placeware_calendar_events").insert(row).execute()
            if hasattr(res, "data") and res.data:
                event_id = res.data[0].get("id")
        except Exception as exc:
            logger.error(f"CalendarAgent: event insert failed: {exc}")
            return Insight(
                findings=[f"Failed to create calendar event: {exc}"],
                risks=["Event not saved."],
                confidence_score=0.1,
            )

        # ── Log for future few-shot learning ────────────────────────────────
        self._log_parse(
            intent_text=self.context.get("intent_text", ""),
            parsed_title=title,
            parsed_time=start_str,
            duration_min=parsed.get("duration_min", 60),
            success=True,
            event_id=str(event_id) if event_id else None,
            actor_id=actor_id,
        )

        # ── Store memory ─────────────────────────────────────────────────────
        from src.services.agent_memory import AgentMemory
        AgentMemory(self.name).store(
            findings=[f"Scheduled '{title}' at {start_str} (duration {parsed.get('duration_min', 60)} min)"],
            confidence=0.85,
        )

        conflict_note = ""
        if analysis.get("conflict_was_detected"):
            conflict_note = "\n(Original time had a conflict — automatically rescheduled to next available slot.)"

        return Insight(
            findings=[
                f"Meeting scheduled!",
                f"Title: {title}",
                f"Start: {start.strftime('%Y-%m-%d %H:%M UTC')}",
                f"End:   {end.strftime('%Y-%m-%d %H:%M UTC')}",
                *(([conflict_note]) if conflict_note else []),
            ],
            recommendations=["View and edit this event in the Calendar page."],
            confidence_score=1.0,
            metrics={"event_id": str(event_id), "title": title, "start": start_str},
        )

    def write_cache(self, insight: Insight) -> None:
        pass  # Logged directly inside generate_insights

    def get_output_schema(self) -> Dict[str, Any]:
        return {
            "findings": "list[str]",
            "metrics": {"event_id": "str", "title": "str", "start": "str"},
        }

    # ── Parsing ────────────────────────────────────────────────────────────────

    def _parse_event(
        self,
        text: str,
        few_shot: List[Dict],
        memories: List[str],
    ) -> Dict[str, Any]:
        """LLM-first parse with regex fallback."""

        few_shot_block = ""
        if few_shot:
            examples = "\n".join(
                f"  Input: \"{e.get('intent_text','')}\" → Title: \"{e.get('parsed_title','')}\" | Time: \"{e.get('parsed_time','')[:16]}\""
                for e in few_shot[:5]
            )
            few_shot_block = f"\nPast examples (use to calibrate extraction):\n{examples}"

        memory_block = ""
        if memories:
            memory_block = "\nRecalled context:\n" + "\n".join(f"  - {m}" for m in memories[:3])

        prompt = f"""Extract calendar event details from this scheduling request.

Request: "{text}"
Current UTC time: {datetime.utcnow().strftime('%Y-%m-%d %H:%M')}
{few_shot_block}
{memory_block}

Respond ONLY with valid JSON matching this schema:
{{
  "title": "string — concise meeting title",
  "start_iso": "YYYY-MM-DDTHH:MM:SSZ — ISO-8601 UTC datetime",
  "duration_minutes": integer,
  "event_type": "meeting|call|review|audit|briefing|other",
  "location": "string or null",
  "attendees": ["email_or_name"],
  "confidence": 0.0-1.0
}}

Rules:
- If no date is given, assume today.
- If no time is given, use 09:00 UTC.
- Infer duration from event type keywords if not stated.
- Extract attendees only if explicitly named or their title is mentioned.
"""

        import json as _json
        try:
            from src.deepseek import DeepSeek
            llm = DeepSeek(os.getenv("DEEPSEEK_API_KEY", ""))
            raw = llm.generate_response(
                context="",
                question=prompt,
                instruction="You are a calendar parsing engine. Output ONLY valid JSON.",
            )
            match = re.search(r"\{[\s\S]*\}", raw)
            if match:
                data = _json.loads(match.group())
                start = self._parse_iso(data.get("start_iso"))
                duration_min = int(data.get("duration_minutes") or 60)
                end = (start + timedelta(minutes=duration_min)) if start else None
                return {
                    "title":       (data.get("title") or "Meeting").strip(),
                    "start":       start or self._default_start(),
                    "end":         end or (self._default_start() + timedelta(hours=1)),
                    "duration_min": duration_min,
                    "event_type":  data.get("event_type", "meeting"),
                    "location":    data.get("location"),
                    "attendees":   data.get("attendees", []),
                    "confidence":  float(data.get("confidence", 0.8)),
                }
        except Exception as exc:
            logger.warning(f"CalendarAgent: LLM parse failed, falling back to regex: {exc}")

        return self._regex_parse(text)

    def _regex_parse(self, text: str) -> Dict[str, Any]:
        """Pure-regex fallback parser."""
        now = datetime.utcnow().replace(second=0, microsecond=0)

        # ── Time extraction ──────────────────────────────────────────────────
        time_match = re.search(
            r"\bat\s+(noon|midnight|\d{1,2}(?::\d{2})?(?:\s*[ap]m)?)",
            text, re.IGNORECASE,
        )
        start = self._default_start()
        if time_match:
            ts = time_match.group(1).strip().lower()
            if ts == "noon":
                start = now.replace(hour=12, minute=0)
            elif ts == "midnight":
                start = now.replace(hour=0, minute=0) + timedelta(days=1)
            else:
                hm = re.match(r"(\d{1,2})(?::(\d{2}))?(?:\s*([ap]m))?", ts, re.IGNORECASE)
                if hm:
                    h, m, ampm = int(hm.group(1)), int(hm.group(2) or 0), (hm.group(3) or "").lower()
                    if ampm == "pm" and h < 12:
                        h += 12
                    elif ampm == "am" and h == 12:
                        h = 0
                    start = now.replace(hour=min(h, 23), minute=min(m, 59))

        # ── Date modifiers ───────────────────────────────────────────────────
        tl = text.lower()
        if "tomorrow" in tl:
            start += timedelta(days=1)
        elif "next week" in tl:
            start += timedelta(weeks=1)
        elif "monday" in tl:
            start = self._next_weekday(start, 0)
        elif "friday" in tl:
            start = self._next_weekday(start, 4)

        # ── Title extraction ─────────────────────────────────────────────────
        title_match = re.search(
            r"(?:schedule|book|arrange|set up|create|add)\s+a?\s*(?:meeting|call|event|review|briefing)\s+"
            r"(?:about|for|with|re|regarding|to discuss)?\s*(.+?)"
            r"(?:\s+at\s+\d|\s+on\s+|\s+tomorrow|\s+next\s+|\s*$)",
            text, re.IGNORECASE,
        )
        title = ""
        if title_match:
            title = title_match.group(1).strip().capitalize()
        if not title or len(title) < 3:
            title = f"Meeting — {now.strftime('%b %d, %Y')}"

        # ── Duration ────────────────────────────────────────────────────────
        duration_min = 60
        for kw, dur in _DURATION_MAP.items():
            if kw in tl:
                duration_min = dur
                break

        end = start + timedelta(minutes=duration_min)
        return {
            "title":       title,
            "start":       start,
            "end":         end,
            "duration_min": duration_min,
            "event_type":  "meeting",
            "location":    None,
            "attendees":   [],
            "confidence":  0.6,
        }

    # ── Conflict detection ─────────────────────────────────────────────────────

    def _check_conflict(
        self,
        start: datetime,
        end: datetime,
    ) -> Tuple[bool, Optional[datetime]]:
        """
        Check for overlapping events in placeware_calendar_events.
        Returns (conflict_found, suggested_start).
        """
        try:
            from src.db import db
            start_str = start.strftime("%Y-%m-%dT%H:%M:%SZ")
            end_str   = end.strftime("%Y-%m-%dT%H:%M:%SZ")

            res = (
                db.table("placeware_calendar_events")
                .select("id, start_time, end_time")
                .lt("start_time", end_str)
                .gt("end_time", start_str)
                .execute()
            )
            conflicts = res.data or []
            if not conflicts:
                return False, None

            # Find next free slot after the last conflicting event ends
            latest_end_str = max(c["end_time"] for c in conflicts)
            latest_end = self._parse_iso(latest_end_str) or (end + timedelta(hours=1))

            # Round up to next 30-min mark and ensure within business hours
            suggestion = self._next_business_slot(latest_end, timedelta(minutes=int((end - start).total_seconds() / 60)))
            return True, suggestion

        except Exception as exc:
            logger.warning(f"CalendarAgent: conflict check failed: {exc}")
            return False, None

    def _next_business_slot(self, after: datetime, duration: timedelta) -> datetime:
        """Return the next :00 or :30 slot after `after` within business hours."""
        slot = after.replace(second=0, microsecond=0)
        # Round up to next 30-min boundary
        minutes = slot.minute
        if minutes < 30:
            slot = slot.replace(minute=30)
        else:
            slot = (slot + timedelta(hours=1)).replace(minute=0)

        # Clamp to business hours
        if slot.hour < _BUSINESS_START_HOUR:
            slot = slot.replace(hour=_BUSINESS_START_HOUR, minute=0)
        elif slot.hour >= _BUSINESS_END_HOUR:
            slot = (slot + timedelta(days=1)).replace(hour=_BUSINESS_START_HOUR, minute=0)

        # Skip weekends
        while slot.weekday() >= 5:
            slot += timedelta(days=1)

        return slot

    # ── Listing ────────────────────────────────────────────────────────────────

    def _list_upcoming(self, limit: int = 10) -> List[Dict]:
        try:
            from src.db import db
            now_str = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
            res = (
                db.table("placeware_calendar_events")
                .select("id, title, start_time, end_time, event_type")
                .gte("start_time", now_str)
                .order("start_time", desc=False)
                .limit(limit)
                .execute()
            )
            return res.data or []
        except Exception as exc:
            logger.warning(f"CalendarAgent: list_upcoming failed: {exc}")
            return []

    # ── Learning helpers ───────────────────────────────────────────────────────

    def _get_few_shot_examples(self) -> List[Dict]:
        try:
            from src.db import db
            res = (
                db.table("placeware_calendar_agent_log")
                .select("intent_text, parsed_title, parsed_time")
                .eq("success", True)
                .order("created_at", desc=True)
                .limit(20)
                .execute()
            )
            return res.data or []
        except Exception:
            return []

    def _get_memories(self) -> List[str]:
        try:
            from src.services.agent_memory import AgentMemory
            intent_text = self.context.get("intent_text", "")
            return AgentMemory(self.name).recall(query_text=intent_text, k=3)
        except Exception:
            return []

    def _log_parse(
        self,
        intent_text: str,
        parsed_title: str,
        parsed_time: str,
        duration_min: int,
        success: bool,
        event_id: Optional[str],
        actor_id: str,
    ) -> None:
        try:
            from src.db import db
            db.table("placeware_calendar_agent_log").insert({
                "intent_text":        intent_text,
                "parsed_title":       parsed_title,
                "parsed_time":        parsed_time,
                "parsed_duration_min": duration_min,
                "success":            success,
                "event_id":           event_id,
                "actor_id":           actor_id,
            }).execute()
        except Exception as exc:
            logger.warning(f"CalendarAgent: log_parse failed: {exc}")

    # ── Utils ──────────────────────────────────────────────────────────────────

    @staticmethod
    def _parse_iso(s: Optional[str]) -> Optional[datetime]:
        if not s:
            return None
        try:
            return datetime.fromisoformat(str(s).replace("Z", "+00:00")).replace(tzinfo=None)
        except (ValueError, TypeError):
            return None

    @staticmethod
    def _default_start() -> datetime:
        """Default: next business hour (09:00 UTC today or tomorrow if after 17:00)."""
        now = datetime.utcnow().replace(second=0, microsecond=0)
        if now.hour >= _BUSINESS_END_HOUR:
            now = (now + timedelta(days=1)).replace(hour=_BUSINESS_START_HOUR + 1, minute=0)
        elif now.hour < _BUSINESS_START_HOUR:
            now = now.replace(hour=_BUSINESS_START_HOUR + 1, minute=0)
        return now

    @staticmethod
    def _next_weekday(dt: datetime, weekday: int) -> datetime:
        days_ahead = weekday - dt.weekday()
        if days_ahead <= 0:
            days_ahead += 7
        return dt + timedelta(days=days_ahead)
