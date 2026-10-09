"""
Executive Orchestration Service (EOS) - LLM-powered executive intent handling.

This module provides intelligent parsing of executive directives into
structured intents, decomposes them into domain agent tasks, and
synthesizes outputs into executive-friendly reports.
"""

import os
import json
import logging
import re
from typing import Any, Dict, List, Optional
from fastapi import APIRouter, Depends, Request, HTTPException
from pydantic import BaseModel

from ..deepseek import DeepSeek
from ..constants import BOT_NAME, BOT_BRAND
import src.agent_router as agent_router
import src.db as db
from .tool_manifest import (
    AVAILABLE_AGENTS,
    ACTION_INTENTS,
    DATA_INTENTS,
    ALL_INTENT_TYPES,
    TASK_MAPPING,
    DEPARTMENT_SYNONYMS,
    ORDERED_ACTION_KEYWORDS,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/eos", tags=["eos"])

# LLM client for EOS - initialized lazily
_llm_client: Optional[DeepSeek] = None


def get_llm_client() -> DeepSeek:
    """Lazy initialization of DeepSeek client for EOS."""
    global _llm_client
    if _llm_client is None:
        api_key = os.getenv("DEEPSEEK_API_KEY")
        if not api_key:
            raise RuntimeError("DEEPSEEK_API_KEY not configured for EOS")
        _llm_client = DeepSeek(api_key)
    return _llm_client


# AVAILABLE_AGENTS imported from tool_manifest — single source of truth


class IntentRequest(BaseModel):
    text: str
    simulation_mode: bool = False


class IntentParser:
    """
    Parses free-form executive text into structured intent using LLM.
    """

    # Intent list is built from tool_manifest at parse time so it stays in sync automatically.
    PARSE_PROMPT = """You are an executive intent parser for {brand}, a pharmaceutical distribution company.

Given the executive's statement, extract a structured intent with these fields:
- intent_type: One of [{intent_types}]
- scope: One of [global, regional, department, specific_item]
- urgency: One of [low, medium, high, critical]
- domains: List of relevant domains from [{domains}]
- parameters: Any specific parameters mentioned (dates, products, thresholds, etc.)
- original_text: The original executive statement

Respond ONLY with valid JSON, no markdown or explanation.

Executive statement: {text}"""

    def parse(self, text: str) -> Dict[str, Any]:
        """Parse executive text into structured intent using LLM."""
        try:
            llm = get_llm_client()
            domains_list = ", ".join(AVAILABLE_AGENTS.keys())
            intent_types_list = ", ".join(ALL_INTENT_TYPES)
            prompt = self.PARSE_PROMPT.format(
                brand=BOT_BRAND,
                domains=domains_list,
                intent_types=intent_types_list,
                text=text,
            )
            
            response = llm.generate_response(
                context="",
                question=prompt,
                instruction="You are a JSON extraction engine. Output ONLY valid JSON with no additional text."
            )
            # Inject intent_types dynamically from the manifest so the prompt stays current.
            
            # Extract JSON from response
            json_match = re.search(r'\{[\s\S]*\}', response)
            if json_match:
                intent = json.loads(json_match.group())
                intent["original_text"] = text
                return intent
            else:
                logger.warning(f"No JSON found in LLM response: {response[:200]}")
                return self._fallback_parse(text)
                
        except json.JSONDecodeError as e:
            logger.error(f"JSON parse error in intent: {e}")
            return self._fallback_parse(text)
        except Exception as e:
            logger.error(f"IntentParser error: {e}")
            return self._fallback_parse(text)

    def _fallback_parse(self, text: str) -> Dict[str, Any]:
        """Keyword-based fallback when LLM parsing fails.

        Detection order (most-specific phrase first prevents false positives):
        1. Action intents — checked via ORDERED_ACTION_KEYWORDS from the manifest.
        2. Data intents   — checked via DATA_INTENTS[*].keywords from the manifest.
        """
        text_lower = text.lower()

        # ── 1. Action intent detection (longest keyword wins) ─────────────────
        for keyword, intent_type in ORDERED_ACTION_KEYWORDS:
            if keyword in text_lower:
                params: Dict[str, Any] = {"text": text}

                if intent_type == "send_email" or intent_type == "send_sms":
                    detected_dept = "operations"
                    for dept, synonyms in DEPARTMENT_SYNONYMS.items():
                        if any(s in text_lower for s in synonyms):
                            detected_dept = dept
                            break
                    params["department"] = detected_dept

                if intent_type == "create_task":
                    priority = "medium"
                    if any(w in text_lower for w in ["urgent", "critical", "asap", "immediately"]):
                        priority = "critical"
                    elif any(w in text_lower for w in ["high priority", "important"]):
                        priority = "high"
                    elif any(w in text_lower for w in ["low priority", "whenever", "eventually"]):
                        priority = "low"
                    params["task_text"] = text
                    params["priority"] = priority

                if intent_type == "generate_report":
                    # Detect specific report type from text
                    report_type = None
                    _report_type_map = [
                        ("sales", ["sales report", "weekly sales", "pipeline report", "crm report", "sales performance", "revenue report", "sales summary"]),
                        ("payroll", ["payroll report", "staff payroll", "payroll summary", "salary report", "wages"]),
                        ("pl", ["p&l report", "profit and loss", "profit & loss", "income statement", "pl report"]),
                        ("ar_aging", ["ar aging", "accounts receivable report", "aging report", "receivables report"]),
                        ("frontdesk", ["frontdesk report", "daily operations report", "front desk report", "daily frontdesk"]),
                        ("deviation", ["deviation report", "capa report", "non-conformance report"]),
                        ("audit", ["audit report", "audit review"]),
                        ("compliance", ["compliance report", "regulatory report"]),
                        ("inventory", ["inventory report", "stock report"]),
                        ("maintenance", ["maintenance report", "equipment report", "calibration report"]),
                        ("executive", ["executive summary report", "board report", "leadership brief"]),
                        ("financial", ["financial report", "financial performance report"]),
                    ]
                    for rtype, phrases in _report_type_map:
                        if any(phrase in text_lower for phrase in phrases):
                            report_type = rtype
                            break
                    if report_type:
                        params["report_type"] = report_type

                return {
                    "intent_type": intent_type,
                    "scope": "specific_item" if intent_type in ("create_task", "schedule_meeting") else "department",
                    "urgency": params.get("priority", "medium"),
                    "domains": [],
                    "parameters": params,
                    "original_text": text,
                }

        # ── 2. Data intent detection (first keyword match wins) ────────────────
        for intent_type, cfg in DATA_INTENTS.items():
            if not cfg.get("keywords"):
                continue
            if any(kw in text_lower for kw in cfg["keywords"]):
                return {
                    "intent_type": intent_type,
                    "scope": "global",
                    "urgency": "medium",
                    "domains": list(cfg.get("agents", [])),
                    "parameters": {},
                    "original_text": text,
                }

        # ── 3. Default ─────────────────────────────────────────────────────────
        return {
            "intent_type": "status_update",
            "scope": "global",
            "urgency": "medium",
            "domains": ["financial_agent"],
            "parameters": {},
            "original_text": text,
        }


class TaskDecomposer:
    """
    Decomposes structured intent into concrete agent tasks.
    """

    # TASK_MAPPING is imported from tool_manifest — no duplicate keys, single source of truth.
    TASK_MAPPING = TASK_MAPPING

    def decompose(self, intent: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Transform intent into list of agent tasks."""
        intent_type = intent.get("intent_type", "status_update")
        domains = intent.get("domains", [])
        params = intent.get("parameters", {})
        
        tasks = []
        
        # Get base tasks from mapping
        base_tasks = self.TASK_MAPPING.get(intent_type, self.TASK_MAPPING["status_update"])
        
        for task_template in base_tasks:
            agent = task_template["agent"]
            # If intent specifies domains, filter to only those
            if domains and agent not in domains:
                continue
            tasks.append({
                "agent": agent,
                "task": {
                    "action": task_template["action"],
                    **params,
                },
            })
        
        # If no tasks matched, use specified domains
        if not tasks and domains:
            for domain in domains[:3]:  # Limit to 3 agents
                if domain in AVAILABLE_AGENTS:
                    tasks.append({
                        "agent": domain,
                        "task": {"action": "analyze", **params},
                    })
        
        return tasks if tasks else [{"agent": "financial_agent", "task": {"action": "get_summary"}}]


class Synthesizer:
    """
    Aggregates agent outputs into executive-friendly report using LLM.
    """

    SYNTHESIS_PROMPT = """You are an executive report synthesizer for {brand}.

Given these agent analysis outputs, create a concise executive summary:

Agent Outputs:
{outputs}

Original Request: {original_text}

Create a brief executive summary (3-5 sentences) followed by key action items if any.
Format as:

EXECUTIVE SUMMARY:
[Your summary here]

KEY INSIGHTS:
- [Insight 1]
- [Insight 2]

RECOMMENDED ACTIONS:
- [Action 1 if needed]
"""

    def synthesize(
        self, agent_outputs: List[Dict[str, Any]], original_text: str = ""
    ) -> Dict[str, Any]:
        """Aggregate agent outputs into executive report."""
        try:
            llm = get_llm_client()
            outputs_str = json.dumps(agent_outputs, indent=2, default=str)
            
            prompt = self.SYNTHESIS_PROMPT.format(
                brand=BOT_BRAND, outputs=outputs_str, original_text=original_text
            )
            
            response = llm.generate_response(
                context="",
                question=prompt,
                instruction=f"You are {BOT_NAME}, an executive assistant. Provide a structured executive summary."
            )
            
            return {
                "summary": response,
                "details": agent_outputs,
                "status": "synthesized",
            }
        except Exception as e:
            logger.error(f"Synthesis error: {e}")
            return {
                "summary": "Analysis complete. See details for agent outputs.",
                "details": agent_outputs,
                "status": "fallback",
            }


async def _handle_task_creation(intent: Dict[str, Any], text: str, simulation: bool) -> Dict[str, Any]:
    """
    Handle task creation intent from executive chat.
    Creates a task in the task management system.
    """
    from src.routers.calendar_tasks import create_task_from_chat
    
    params = intent.get("parameters", {})
    priority = params.get("priority", "medium")
    task_text = params.get("task_text", text)
    
    # Extract title (use LLM to clean up the task title)
    try:
        llm = get_llm_client()
        title_prompt = f"""Extract a clean task title from this request: "{task_text}"
        
Respond with ONLY the task title (max 100 chars), no explanation."""
        title = llm.generate_response(
            context="",
            question=title_prompt,
            instruction="Extract brief task title only."
        ).strip().strip('"').strip("'")
        
        # Limit title length
        if len(title) > 100:
            title = title[:97] + "..."
    except Exception:
        # Fallback: use first 100 chars of text
        title = task_text[:100] if len(task_text) <= 100 else task_text[:97] + "..."
    
    if simulation:
        return {
            "intent": intent,
            "tasks": [],
            "outputs": [{"action": "create_task", "title": title, "priority": priority, "status": "simulated"}],
            "report": {
                "summary": f"[SIMULATION] Would create task: \"{title}\" with {priority} priority.",
                "details": [],
                "status": "simulated",
            },
            "simulation": True,
        }
    
    # Create the task
    result = create_task_from_chat(
        title=title,
        description=f"Created via Synbot chat: {text}",
        priority=priority,
    )
    
    if result.get("success"):
        task = result.get("task", {})
        return {
            "intent": intent,
            "tasks": [{"type": "create_task", "title": title}],
            "outputs": [{"action": "create_task", "task": task, "status": "created"}],
            "report": {
                "summary": f"✅ Task created successfully!\n\nTask: \"{title}\"\nPriority: {priority}\n\nYou can view and manage this task in the Calendar & Tasks page.",
                "details": [task],
                "status": "success",
            },
            "simulation": False,
        }
    else:
        return {
            "intent": intent,
            "tasks": [],
            "outputs": [{"action": "create_task", "error": result.get("error"), "status": "failed"}],
            "report": {
                "summary": f"Failed to create task: {result.get('error', 'Unknown error')}",
                "details": [],
                "status": "error",
            },
            "simulation": False,
        }


async def _handle_send_email_action(
    intent: Dict[str, Any], text: str, simulation: bool
) -> Dict[str, Any]:
    """Delegate email composition and delivery to EmailAgent."""
    from src.agent_registry import get_agent

    params = intent.get("parameters", {})
    department = (params.get("department") or "operations").lower()

    agent = get_agent("email_agent", context={
        "intent_text": text,
        "department":  department,
        "actor_id":    "eos_chat",
        "simulation":  simulation,
        "enable_memory": True,
    })
    if agent:
        try:
            insight = agent.run()
            summary = "\n".join(insight.findings) if insight.findings else "Email action completed."
            status = "simulated" if simulation else ("success" if insight.confidence_score >= 0.5 else "error")
            return {
                "intent": intent,
                "report": {"summary": summary, "status": status, "metrics": insight.metrics},
                "simulation": simulation,
            }
        except Exception as exc:
            logger.error(f"EmailAgent failed: {exc}")
            # Fall through to inline fallback below
            return {
                "intent": intent,
                "report": {"summary": f"Email agent encountered an error: {exc}", "status": "error"},
                "simulation": simulation,
            }

    # ── Inline fallback (no agent registered) ────────────────────────────────
    import yaml
    from src.services.messaging import send_email

    cfg_path = os.path.join(os.path.dirname(__file__), "..", "..", "config.yaml")
    to_email: Optional[str] = None
    try:
        with open(cfg_path, "r", encoding="utf-8") as f:
            cfg = yaml.safe_load(f) or {}
        to_email = ((cfg.get("email") or {}).get("recipients") or {}).get(department)
    except Exception as exc:
        logger.error(f"Config load failed in email fallback: {exc}")

    if not to_email:
        return {
            "intent": intent,
            "report": {
                "summary": (
                    f"No email address configured for department '{department}'. "
                    "Check email.recipients in config.yaml."
                ),
                "status": "error",
            },
            "simulation": simulation,
        }

    subject = f"Message via {BOT_BRAND} Executive Assistant"
    body_text = f"This message was sent via {BOT_NAME}:\n\n{text}\n\n---\nSent by {BOT_BRAND} AI Assistant"

    if simulation:
        return {
            "intent": intent,
            "report": {
                "summary": f"[SIMULATION] Would send email to {department} ({to_email}).\nSubject: {subject}",
                "status": "simulated",
            },
            "simulation": True,
        }

    try:
        send_email(to_email=to_email, subject=subject, body=body_text)
        return {
            "intent": intent,
            "report": {"summary": f"Email sent to {department} ({to_email}).", "status": "success"},
            "simulation": False,
        }
    except Exception as exc:
        logger.error(f"Email fallback send failed: {exc}")
        return {
            "intent": intent,
            "report": {"summary": f"Failed to send email: {exc}", "status": "error"},
            "simulation": False,
        }


async def _handle_schedule_meeting_action(
    intent: Dict[str, Any], text: str, simulation: bool
) -> Dict[str, Any]:
    """Delegate calendar parsing, conflict-check, and event creation to CalendarAgent."""
    from src.agent_registry import get_agent

    agent = get_agent("calendar_agent", context={
        "intent_text": text,
        "action":      "create",
        "actor_id":    "eos_chat",
        "simulation":  simulation,
        "enable_memory": True,
    })
    if agent:
        try:
            insight = agent.run()
            summary = "\n".join(insight.findings) if insight.findings else "Calendar action completed."
            status = "simulated" if simulation else ("success" if insight.confidence_score >= 0.5 else "error")
            return {
                "intent": intent,
                "report": {"summary": summary, "status": status, "metrics": insight.metrics},
                "simulation": simulation,
            }
        except Exception as exc:
            logger.error(f"CalendarAgent failed: {exc}")
            return {
                "intent": intent,
                "report": {"summary": f"Calendar agent encountered an error: {exc}", "status": "error"},
                "simulation": simulation,
            }

    # ── Inline fallback ───────────────────────────────────────────────────────
    import datetime as _dt
    from src.db import db as _db

    now = _dt.datetime.utcnow()
    time_match = re.search(
        r"\bat\s+(noon|midnight|\d{1,2}(?::\d{2})?(?:\s*[ap]m)?)",
        text, re.IGNORECASE
    )
    if time_match:
        ts = time_match.group(1).strip().lower()
        if ts == "noon":
            start = now.replace(hour=12, minute=0, second=0, microsecond=0)
        elif ts == "midnight":
            start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        else:
            hm = re.match(r"(\d{1,2})(?::(\d{2}))?(?:\s*([ap]m))?", ts, re.IGNORECASE)
            if hm:
                hour = int(hm.group(1))
                minutes = int(hm.group(2) or 0)
                ampm = (hm.group(3) or "").lower()
                if ampm == "pm" and hour < 12:
                    hour += 12
                elif ampm == "am" and hour == 12:
                    hour = 0
                start = now.replace(hour=min(hour, 23), minute=min(minutes, 59), second=0, microsecond=0)
            else:
                start = now + _dt.timedelta(hours=1)
    else:
        start = now + _dt.timedelta(hours=1)

    end = start + _dt.timedelta(hours=1)
    title_match = re.search(
        r"(?:schedule|book|arrange|set up|create|add)\s+a?\s*(?:meeting|call|event)\s+"
        r"(?:about|for|with|re|regarding|to discuss)?\s*(.+?)"
        r"(?:\s+at\s+\d|\s+on\s+|\s*$)",
        text, re.IGNORECASE
    )
    title = (title_match.group(1).strip().capitalize() if title_match else "") or f"Meeting – {now.strftime('%b %d, %Y')}"
    if len(title) > 100:
        title = title[:97] + "..."

    if simulation:
        return {
            "intent": intent,
            "report": {
                "summary": f"[SIMULATION] Would schedule: {title}\nStart: {start.isoformat()}Z",
                "status": "simulated",
            },
            "simulation": True,
        }

    try:
        import json as _json
        result = _db.table("placeware_calendar_events").insert({
            "title": title,
            "description": f"Scheduled via {BOT_NAME}: {text}",
            "event_type": "meeting",
            "start_time": start.isoformat() + "Z",
            "end_time": end.isoformat() + "Z",
            "all_day": False,
            "location": None,
            "attendees": _json.dumps([]),
            "metadata": _json.dumps({"created_via": "eos_chat"}),
        }).execute()
        return {
            "intent": intent,
            "report": {
                "summary": f"Meeting scheduled!\nTitle: {title}\nStart: {start.strftime('%Y-%m-%d %H:%M UTC')}",
                "status": "success",
            },
            "simulation": False,
        }
    except Exception as exc:
        logger.error(f"Schedule meeting fallback failed: {exc}")
        return {
            "intent": intent,
            "report": {"summary": f"Failed to schedule meeting: {exc}", "status": "error"},
            "simulation": False,
        }


async def _handle_find_leads_action(
    intent: Dict[str, Any], text: str, simulation: bool
) -> Dict[str, Any]:
    """Delegate location-based prospect discovery to LeadFinderAgent."""
    from src.agent_registry import get_agent
    import re as _re

    params   = intent.get("parameters", {})
    location = params.get("location") or params.get("region") or ""

    # ── Inline NLP fallback: extract "in <city>" or "near <city>" ───────────
    if not location:
        m = _re.search(r"\b(?:in|near|around|close to)\s+([A-Za-z][A-Za-z ,]+?)(?:\s+(?:for|to|with|and|$)|\.|,|$)", text, _re.IGNORECASE)
        location = m.group(1).strip() if m else "Lagos, Nigeria"

    business_type = params.get("business_type") or params.get("type") or ""
    if not business_type:
        for kw in ("pharmacy", "hospital", "clinic", "healthcare", "distributor", "lab"):
            if kw in text.lower():
                business_type = kw
                break
        business_type = business_type or "pharmacy"

    radius_m = int(params.get("radius_m") or 5000)
    limit    = int(params.get("limit") or 20)

    agent = get_agent("lead_finder_agent", context={
        "intent_text":   text,
        "location":      location,
        "business_type": business_type,
        "radius_m":      radius_m,
        "limit":         limit,
        "industry":      "pharma",
        "simulation":    simulation,
        "actor_id":      "eos_chat",
        "enable_memory": True,
    })

    if agent:
        try:
            insight = agent.run()
            summary = "\n".join(insight.findings) if insight.findings else "Lead discovery completed."
            status  = "simulated" if simulation else ("success" if insight.confidence_score >= 0.5 else "error")
            return {
                "intent":     intent,
                "report":     {"summary": summary, "status": status, "metrics": insight.metrics},
                "simulation": simulation,
            }
        except Exception as exc:
            logger.error(f"LeadFinderAgent failed: {exc}")
            return {
                "intent": intent,
                "report": {"summary": f"Lead finder encountered an error: {exc}", "status": "error"},
                "simulation": simulation,
            }

    return {
        "intent": intent,
        "report": {
            "summary": (
                f"Lead Finder is available via the CRM → Lead Finder page. "
                f"Search for '{business_type}' near '{location}'."
            ),
            "status": "fallback",
        },
        "simulation": simulation,
    }


async def _handle_send_bulk_message_action(
    intent: Dict[str, Any], text: str, simulation: bool
) -> Dict[str, Any]:
    """
    Resolve a bulk-message chat request into a preview -- channel, message
    text, and a real recipient count -- WITHOUT sending anything.

    Deliberately does not fit the {"report": {"summary","status"}} shape the
    other handlers here use, and is deliberately never wired into app.py's
    immediate-execute _ACTION_DISPATCH table: a bulk send reaches every
    matching customer and costs real Termii/SMTP quota, a much larger blast
    radius than any other action in this file, so app.py always requires an
    explicit user confirmation on the next turn before actually dispatching
    (mirroring send_email's existing two-phase draft flow, just
    non-negotiable here rather than a preview-compose nicety).
    """
    import re as _re

    tl = text.lower()

    # Channel: scan the raw text rather than trusting which manifest keyword
    # fired (app.py only tells us the intent_type, not which phrase matched).
    if "email" in tl:
        channel = "email"
    elif any(kw in tl for kw in ("sms", "text message", "text all", "text our", "bulk text")):
        channel = "sms"
    else:
        channel = None

    # Message text: prefer explicitly quoted text (straight or curly quotes
    # -- built via chr() instead of a raw literal so this source file stays
    # pure-ASCII regardless of encoding; matches the same mojibake class
    # fixed elsewhere in this codebase, e.g. reports.py), else text after a
    # natural lead-in phrase. No content is invented if neither pattern
    # matches -- see the needs_input branch below.
    _LEFT_DQ, _RIGHT_DQ = chr(0x201C), chr(0x201D)
    message_text = None
    m = _re.search(r'["' + _LEFT_DQ + r']([^"' + _RIGHT_DQ + r']{3,4096})["' + _RIGHT_DQ + r']', text)
    if m:
        message_text = m.group(1).strip()
    else:
        m = _re.search(r"\b(?:saying|that says|telling them|message[: ]+)\s*(.+)$", text, _re.IGNORECASE)
        if m:
            message_text = m.group(1).strip().strip("\"'" + _LEFT_DQ + _RIGHT_DQ)

    if not channel or not message_text:
        missing = []
        if not channel:
            missing.append("whether this is SMS or email")
        if not message_text:
            missing.append("the exact message to send, in quotes")
        return {
            "intent": intent,
            "status": "needs_input",
            "message": (
                "I need a bit more before I can safely queue a bulk send - "
                + " and ".join(missing) + ". For example: "
                "send a bulk SMS to customers saying \"We have new stock in, place your order today.\""
            ),
            "simulation": simulation,
        }

    from src.services.messaging import resolve_bulk_recipients
    recipients = resolve_bulk_recipients(None)
    if channel == "sms":
        count = sum(1 for r in recipients if (r.get("phone") or "").strip())
    else:
        count = sum(1 for r in recipients if "@" in (r.get("email") or ""))

    return {
        "intent": intent,
        "status": "ready",
        "channel": channel,
        "message_text": message_text,
        "subject": "Message from Placeware" if channel == "email" else None,
        "recipient_filter": None,
        "recipient_count": count,
        "simulation": simulation,
    }


def _extract_sms_body(text: str) -> Optional[str]:
    """Pull the intended message body out of a chat request. Prefers text in
    quotes, else text after a natural lead-in ("saying", "tell them", ...).
    Returns None rather than inventing content."""
    import re as _re

    # Curly quotes built via chr() so this file stays pure-ASCII (same
    # mojibake class already fixed elsewhere in this codebase).
    _LEFT_DQ, _RIGHT_DQ = chr(0x201C), chr(0x201D)
    m = _re.search(r'["' + _LEFT_DQ + r']([^"' + _RIGHT_DQ + r']{3,900})["' + _RIGHT_DQ + r']', text)
    if m:
        return m.group(1).strip()
    m = _re.search(
        r"\b(?:saying|that says|tell(?:ing)? (?:them|him|her|the client|the customer)|message[: ]+)"
        r"\s*(?:that\s+)?(.+)$",
        text,
        _re.IGNORECASE,
    )
    if m:
        return m.group(1).strip().strip("\"'" + _LEFT_DQ + _RIGHT_DQ).rstrip(".")
    return None


def _sms_needs_input(intent: Dict[str, Any], simulation: bool, message: str) -> Dict[str, Any]:
    return {
        "intent": intent,
        "report": {"summary": message, "status": "needs_input"},
        "simulation": simulation,
    }


# "text Royan that ...", "send an sms to Royan Hospital saying ..." -- grab the
# name between the preposition and whatever introduces the message body.
_RECIPIENT_NAME_RE = re.compile(
    # "...to Royan saying" / "...for Royan Hospital:" and the verb-first form
    # people also use: "text Royan Hospital saying ...".
    r"\b(?:to|for|text|sms|email|message)\s+(?!this\b|that\b|the\s+number\b)"
    r"([A-Za-z][\w'&.\-]*(?:\s+[A-Za-z][\w'&.\-]*){0,3}?)"
    r"(?=\s+(?:saying|that|telling|to\s+say|about|re\b|:)|\s*[,:\"]|$)",
    re.IGNORECASE,
)

# Words that are never a client name, so we don't go looking up "a text".
_NON_NAME_TOKENS = {
    "a", "an", "the", "text", "sms", "message", "him", "her", "them", "it",
    "client", "customer", "number", "this", "that", "please", "quick",
    # The verb-first alternative above can match before the preposition
    # ("send a TEXT to Royan"), leaving it on the front of the candidate.
    "to", "for", "send", "email",
}


def _extract_recipient_name(text: str) -> Optional[str]:
    m = _RECIPIENT_NAME_RE.search(text or "")
    if not m:
        return None
    candidate = " ".join(
        w for w in m.group(1).split()
        if w.lower() not in _NON_NAME_TOKENS
    ).strip(" ,:\"'")
    if candidate.replace(" ", "").isdigit():
        return None  # a bare number is a phone number, not a client name
    return candidate if len(candidate) >= 2 else None


async def _handle_send_sms_action(
    intent: Dict[str, Any], text: str, simulation: bool
) -> Dict[str, Any]:
    """
    Send an SMS via Termii, either to an explicit phone number given in the
    chat request or to a department number from config.yaml's sms.recipients.

    Unlike the departmental-only handler this replaces, the number is read
    out of the user's own message -- "send a text to +234... saying ..." is
    the normal way people phrase this, and previously the number was silently
    ignored.
    """
    import re as _re
    from src.services.messaging import (
        send_sms, _normalize_ng_phone, find_client_contacts, sms_blackout_active,
    )

    params = intent.get("parameters", {})
    recipient_label = None

    # 1. Explicit number in the message wins.
    raw_phone = None
    m = _re.search(r"\+?[0-9][0-9\-\s]{7,14}[0-9]", text or "")
    if m:
        raw_phone = _re.sub(r"\s+", "", m.group(0))
    to_phone = _normalize_ng_phone(raw_phone) if raw_phone else None

    # 2. No number given -- resolve a client by name against the CRM, so
    #    "text Royan that their vaccines are on the way" works the way people
    #    actually phrase it.
    if not to_phone:
        hint = _extract_recipient_name(text)
        if hint:
            matches = find_client_contacts(hint)
            with_phone = [c for c in matches if c.get("phone")]
            if len(with_phone) == 1:
                to_phone = with_phone[0]["phone"]
                recipient_label = with_phone[0]["name"]
            elif len(with_phone) > 1:
                names = ", ".join(c["name"] for c in with_phone[:5])
                return _sms_needs_input(
                    intent, simulation,
                    f"More than one client matches '{hint}': {names}. "
                    "Which one should I text?",
                )
            elif matches:
                # Prefer a match that at least has *something* stored, so we
                # report the useful failure ("that number isn't textable")
                # rather than "no number" for a different same-name record.
                best = next((c for c in matches if c.get("phone_raw")), matches[0])
                if best.get("phone_raw"):
                    detail = (
                        f"the number on file ({best['phone_raw']}) isn't a valid "
                        "Nigerian mobile number, so it can't receive SMS"
                    )
                else:
                    detail = "there's no phone number on their record"
                return _sms_needs_input(
                    intent, simulation,
                    f"I can't text {best['name']} — {detail}. "
                    "Give me a mobile number to use, or update their record.",
                )

    # 3. Otherwise fall back to a department number from config.yaml.
    department = (params.get("department") or "").lower()
    if not to_phone and department:
        import yaml
        cfg_path = os.path.join(os.path.dirname(__file__), "..", "..", "config.yaml")
        try:
            with open(cfg_path, "r", encoding="utf-8") as f:
                cfg = yaml.safe_load(f) or {}
            phones = ((cfg.get("sms") or {}).get("recipients")) or {}
            to_phone = _normalize_ng_phone(phones.get(department))
        except Exception as exc:
            logger.error(f"Failed to load config for SMS dispatch: {exc}")

    if not to_phone:
        return _sms_needs_input(
            intent, simulation,
            "I need a phone number or a client name to text. For example: "
            "send a text to 08012345678 saying \"Your vaccines are ready\", "
            "or: text Royan Hospital saying \"Your vaccines are on the way\".",
        )

    who = f"{recipient_label} ({to_phone})" if recipient_label else to_phone

    body = _extract_sms_body(text)
    if not body:
        return _sms_needs_input(
            intent, simulation,
            f"I have the number for {who} but not the message. Put the text in "
            "quotes, for example: \"Your vaccines are ready for collection.\"",
        )

    if simulation:
        return {
            "intent": intent,
            "report": {
                "summary": f"[SIMULATION] Would send SMS to {who}: {body}",
                "status": "simulated",
            },
            "simulation": True,
        }

    # Refuse rather than report a success that never lands. Termii answers
    # "Successfully Sent" for overnight generic-route traffic and bills for
    # it, but the carrier rejects it -- which is exactly how a message was
    # reported as sent and never arrived.
    if sms_blackout_active():
        return _sms_needs_input(
            intent, simulation,
            f"I haven't sent this. Nigerian carriers reject our SMS route "
            f"between 8PM and 8AM, so a text to {who} would be charged but "
            "never delivered. Send it after 8AM, or use email instead.",
        )

    try:
        # "generic" is the only route provisioned on this Termii workspace --
        # "dnd" returns 422 "Route not configured ... route=DND" until Termii
        # support enables it. DND-registered numbers won't receive generic
        # traffic at any hour.
        result = send_sms(to_phone, body, channel="generic")
        if str(result.get("code", "ok")).lower() not in ("ok", "success"):
            return {
                "intent": intent,
                "report": {
                    "summary": f"Termii rejected the SMS to {who}: {result.get('message') or result}",
                    "status": "error",
                },
                "simulation": False,
            }
        return {
            "intent": intent,
            "report": {
                "summary": f"SMS sent to {who}: \"{body}\"",
                "status": "success",
            },
            "simulation": False,
        }
    except Exception as exc:
        logger.error(f"SMS send failed: {exc}")
        return {
            "intent": intent,
            "report": {"summary": f"Failed to send SMS to {who}: {exc}", "status": "error"},
            "simulation": False,
        }


async def _handle_generate_report_action(
    intent: Dict[str, Any], text: str, simulation: bool
) -> Dict[str, Any]:
    """Delegate structured report generation to ReportGenerationAgent."""
    from src.agent_registry import get_agent

    params = intent.get("parameters", {})
    report_type = params.get("report_type")  # Optional override

    agent = get_agent("report_generation_agent", context={
        "intent_text": text,
        "report_type": report_type,
        "actor_id":    "eos_chat",
        "simulation":  simulation,
        "enable_memory": True,
    })
    if agent:
        try:
            insight = agent.run()
            metrics = insight.metrics or {}
            full_report: str = metrics.get("full_report", "") or ""
            report_memory_id = metrics.get("report_memory_id")
            if report_memory_id:
                # A .docx download will be attached to the chat response (see
                # /chat's generate_report action-dispatch call site) -- keep
                # the chat bubble to a short summary instead of dumping the
                # whole multi-section narrative as raw text.
                summary = metrics.get("summary") or full_report[:400] or "Report generated."
            else:
                # Not persisted (low quality score, or a simulation run) --
                # nothing to download, so fall back to showing the full text
                # inline, same as before this change.
                summary = full_report if full_report else (
                    "\n".join(insight.findings) if insight.findings else "Report generation completed."
                )
            status = "simulated" if simulation else "success"
            return {
                "intent": intent,
                "report": {"summary": summary, "status": status, "metrics": metrics},
                "simulation": simulation,
            }
        except Exception as exc:
            logger.error(f"ReportGenerationAgent failed: {exc}")
            return {
                "intent": intent,
                "report": {"summary": f"Report agent encountered an error: {exc}", "status": "error"},
                "simulation": simulation,
            }

    # ── Inline fallback (legacy path) ────────────────────────────────────────
    if simulation:
        return {
            "intent": intent,
            "report": {"summary": "[SIMULATION] Would generate a report based on: " + text, "status": "simulated"},
            "simulation": True,
        }

    report_data: Dict[str, Any] = {}
    text_lower = text.lower()
    detected_type = "general"

    try:
        if any(w in text_lower for w in ["p&l", "profit", "loss", "income statement", "pl report"]):
            detected_type = "P&L"
            from src.services.finance import get_pl_summary  # type: ignore[import]
            report_data = get_pl_summary()
        elif any(w in text_lower for w in ["payroll", "salary", "wages"]):
            detected_type = "Payroll"
            from src.services.hr import get_payroll_summary  # type: ignore[import]
            report_data = get_payroll_summary()
        elif any(w in text_lower for w in ["compliance", "audit", "qms", "nafdac"]):
            detected_type = "Compliance"
            from src.services.compliance import get_compliance_summary  # type: ignore[import]
            report_data = get_compliance_summary()
        elif any(w in text_lower for w in ["inventory", "stock"]):
            detected_type = "Inventory"
            from src.services.tool_registry import ToolRegistry
            report_data = ToolRegistry.execute("getLatestInventorySnapshot", {}, ["executive"], "executive")
        else:
            from src.services.tool_registry import ToolRegistry
            report_data = ToolRegistry.execute("getExecutiveSummary", {}, ["executive"], "executive")
    except Exception as exc:
        logger.warning(f"Report fallback data pull partial error: {exc}")

    synth = Synthesizer()
    report = synth.synthesize(
        [{"source": "report", "type": detected_type, "data": report_data}],
        original_text=text,
    )
    return {"intent": intent, "report": report, "simulation": False}


async def _handle_trigger_replenishment_action(
    intent: Dict[str, Any], text: str, simulation: bool
) -> Dict[str, Any]:
    """Reorder requests from chat are READ-ONLY: show what the live reorder plan says needs
    ordering and where to raise it. Stock orders are raised, approved and marked ordered in
    Operations -> Stock Orders & Purchases, where the person confirms quantity and supplier
    (read-before-write; ACe guide/06_ACE_Synbot_Standards_Applied.md). The old path wrote a guessed quantity to a table
    that no longer exists."""
    try:
        from src.services.ace_tools import stock_orders_status, _resolve
        s = stock_orders_status(text)
        need = s.get("needs_ordering") or []
        where = "Raise the order in Operations -> Stock Orders & Purchases -> Reorder plan, then approve it and mark it ordered with the supplier."
        named = need[0] if need and _resolve(text, [str(need[0]["product"])])[0] else None
        if named:
            status = str(named.get("status") or "").replace("_", " ")
            summary = (f"{named['product']} is {status} ({named.get('on_hand') or 0:g} on hand); the reorder plan suggests "
                       f"{named.get('suggested_qty') or '?'} units" + (f" from {named['supplier']}" if named.get("supplier") else "")
                       + f". I don't place orders from chat. {where}")
        elif need:
            top = "; ".join(f"{r['product']} ({str(r['status']).replace('_', ' ')}, suggest {r.get('suggested_qty') or '?'})"
                            for r in need[:5])
            summary = (f"{s.get('products_to_order_total') or len(need)} products need ordering: {s.get('of_which_out_of_stock') or 0} "
                       f"out of stock and {s.get('of_which_running_low') or 0} running low. Top of the list: {top}. {where}")
        else:
            summary = "Nothing needs reordering right now according to the reorder plan (Operations -> Stock Orders & Purchases)."
        return {"intent": intent, "report": {"summary": summary, "status": "success"}, "simulation": simulation}
    except Exception as exc:
        logger.error(f"reorder lookup failed: {exc}")
        return {"intent": intent, "report": {"summary": "I can't reach the reorder plan right now. "
                "Operations -> Stock Orders & Purchases -> Reorder plan shows it.", "status": "error"}, "simulation": simulation}


@router.post("/intent")
async def handle_intent(request: Request, body: IntentRequest):
    """
    Process an executive intent: parse, decompose, dispatch, synthesize.
    """
    text = body.text
    simulation = body.simulation_mode
    
    if not text.strip():
        raise HTTPException(400, "Empty intent text")
    
    # 1. Parse intent
    parser = IntentParser()
    intent = parser.parse(text)
    logger.info(f"Parsed intent: {intent.get('intent_type')} scope={intent.get('scope')}")
    
    # Handle action intents before analytics pipeline
    if intent.get("intent_type") == "send_email":
        return await _handle_send_email_action(intent, text, simulation)

    if intent.get("intent_type") == "send_sms":
        return await _handle_send_sms_action(intent, text, simulation)

    if intent.get("intent_type") == "schedule_meeting":
        return await _handle_schedule_meeting_action(intent, text, simulation)

    if intent.get("intent_type") == "create_task":
        return await _handle_task_creation(intent, text, simulation)

    if intent.get("intent_type") == "generate_report":
        return await _handle_generate_report_action(intent, text, simulation)

    if intent.get("intent_type") == "trigger_replenishment":
        return await _handle_trigger_replenishment_action(intent, text, simulation)
    
    # 2. Decompose into tasks
    decomposer = TaskDecomposer()
    tasks = decomposer.decompose(intent)
    logger.info(f"Decomposed into {len(tasks)} tasks")
    
    # 3. Dispatch tasks (or simulate) — real agent execution via agent_registry
    outputs = []
    for t in tasks:
        agent_name = t.get("agent")
        task = t.get("task")

        if simulation:
            outputs.append({
                "agent": agent_name,
                "result": f"[SIMULATION] Would execute {task.get('action')} on {agent_name}",
                "status": "simulated",
            })
        else:
            try:
                from src.agent_registry import get_agent as _get_agent
                from src.routers.agents_exec import (
                    create_db_executor,
                    _get_default_specs_for_agent,
                    workflow_engine as _wf_engine,
                    shared_cache as _cache,
                )
                actor = request.client.host if request.client else "eos"
                agent_obj = _get_agent(
                    agent_name,
                    context={
                        "db_executor":         create_db_executor(),
                        "query_specs":         _get_default_specs_for_agent(agent_name),
                        "cache":               _cache,
                        "workflow_engine":     _wf_engine,
                        "auto_trigger_workflow": False,
                        "actor_id":            actor,
                        "actor_role":          None,
                    },
                )
                if agent_obj:
                    insight = agent_obj.run()
                    outputs.append({
                        "agent":  agent_name,
                        "result": getattr(insight, "__dict__", insight),
                        "status": "executed",
                    })
                else:
                    # Agent not in registry — fall back to stub dispatch
                    tid = agent_router.send_task(agent_name, task)
                    outputs.append({"agent": agent_name, "task_id": tid, "status": "dispatched"})
            except Exception as e:
                logger.error(f"Agent execution failed for {agent_name}: {e}")
                outputs.append({"agent": agent_name, "error": str(e), "status": "failed"})

    # 3b. Augment with tool-registry data for this intent type
    intent_type = intent.get("intent_type", "status_update")
    tool_names = (DATA_INTENTS.get(intent_type) or {}).get("tools", [])
    if tool_names and not simulation:
        try:
            from src.services.tool_registry import ToolRegistry
            for tool_name in tool_names:
                try:
                    result = ToolRegistry.execute(
                        tool_name,
                        args={},
                        roles=["executive"],
                        mode="executive",
                    )
                    outputs.append({
                        "source": "tool_registry",
                        "tool":   tool_name,
                        "result": result,
                        "status": "ok",
                    })
                except Exception as te:
                    logger.warning(f"Tool registry call failed [{tool_name}]: {te}")
                    outputs.append({"source": "tool_registry", "tool": tool_name, "error": str(te), "status": "failed"})
        except ImportError:
            logger.warning("tool_registry module not importable; skipping")
    
    # 4. Synthesize report
    synth = Synthesizer()
    report = synth.synthesize(outputs, original_text=text)
    
    # 5. Log executive action
    try:
        db.db.table("executive_action_log").insert({
            "executive_id": request.client.host if request.client else "unknown",
            "intent": intent,
            "tasks": tasks,
            "actions": outputs,
            "simulation": simulation,
        }).execute()
    except Exception as e:
        logger.exception(f"Failed logging executive action: {e}")
    
    return {
        "intent": intent,
        "tasks": tasks,
        "outputs": outputs,
        "report": report,
        "simulation": simulation,
    }


@router.get("/agents")
def list_available_agents():
    """List available domain agents for EOS."""
    return {
        "agents": [
            {"id": k, "description": v} for k, v in AVAILABLE_AGENTS.items()
        ]
    }
