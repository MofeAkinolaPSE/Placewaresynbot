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

                if intent_type == "send_email" or intent_type == "send_whatsapp":
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


async def _handle_send_whatsapp_action(
    intent: Dict[str, Any], text: str, simulation: bool
) -> Dict[str, Any]:
    """Send a WhatsApp message to an internal department via Termii."""
    import yaml
    from src.services.messaging import send_whatsapp

    params = intent.get("parameters", {})
    department = (params.get("department") or "operations").lower()

    cfg_path = os.path.join(os.path.dirname(__file__), "..", "..", "config.yaml")
    to_phone: Optional[str] = None
    try:
        with open(cfg_path, "r", encoding="utf-8") as f:
            cfg = yaml.safe_load(f) or {}
        phones = ((cfg.get("whatsapp") or {}).get("recipients")) or {}
        to_phone = phones.get(department)
    except Exception as exc:
        logger.error(f"Failed to load config for WhatsApp dispatch: {exc}")

    if not to_phone:
        return {
            "intent": intent,
            "report": {
                "summary": (
                    f"No WhatsApp number configured for '{department}'. "
                    "Add a whatsapp.recipients section to config.yaml."
                ),
                "status": "error",
            },
            "simulation": simulation,
        }

    if simulation:
        return {
            "intent": intent,
            "report": {
                "summary": f"[SIMULATION] Would send WhatsApp to {department} ({to_phone}).",
                "status": "simulated",
            },
            "simulation": True,
        }

    try:
        send_whatsapp(to_phone=to_phone, message=text)
        return {
            "intent": intent,
            "report": {
                "summary": f"WhatsApp message sent to the {department} department.",
                "status": "success",
            },
            "simulation": False,
        }
    except Exception as exc:
        logger.error(f"WhatsApp send failed: {exc}")
        return {
            "intent": intent,
            "report": {"summary": f"Failed to send WhatsApp to {department}: {exc}", "status": "error"},
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
    """Create a replenishment request for a SKU mentioned in the text."""
    import re as _re

    # Extract SKU and quantity from text using simple heuristics
    sku_match = _re.search(r"\b([A-Z]{2,}-?\d{3,})\b", text)
    qty_match = _re.search(r"\b(\d+)\s*(?:units?|packs?|pieces?|boxes?|items?)?\b", text)

    sku = sku_match.group(1) if sku_match else None
    qty = int(qty_match.group(1)) if qty_match else 50

    if simulation:
        return {
            "intent": intent,
            "report": {
                "summary": f"[SIMULATION] Would create replenishment request: SKU={sku or 'unknown'}, qty={qty}",
                "status": "simulated",
            },
            "simulation": True,
        }

    try:
        from src.services.replenishment import create_replenishment_request  # type: ignore[import]
        result = create_replenishment_request(sku=sku, quantity=qty, notes=text)
        return {
            "intent": intent,
            "report": {
                "summary": f"Replenishment request created for SKU {sku}, quantity {qty}.",
                "details": result,
                "status": "success",
            },
            "simulation": False,
        }
    except ImportError:
        # Fallback: insert directly via Supabase
        try:
            row = {
                "sku": sku,
                "requested_qty": qty,
                "notes": text,
                "status": "pending",
                "created_via": "eos_chat",
            }
            result_db = db.db.table("placeware_replenishment_requests").insert(row).execute()
            inserted = result_db.data[0] if hasattr(result_db, "data") and result_db.data else row
            return {
                "intent": intent,
                "report": {
                    "summary": f"Replenishment request submitted: SKU {sku or 'N/A'}, qty {qty}.",
                    "details": inserted,
                    "status": "success",
                },
                "simulation": False,
            }
        except Exception as exc:
            logger.error(f"Replenishment insert failed: {exc}")
            return {
                "intent": intent,
                "report": {"summary": f"Failed to create replenishment: {exc}", "status": "error"},
                "simulation": False,
            }


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

    if intent.get("intent_type") == "send_whatsapp":
        return await _handle_send_whatsapp_action(intent, text, simulation)

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
async def list_available_agents():
    """List available domain agents for EOS."""
    return {
        "agents": [
            {"id": k, "description": v} for k, v in AVAILABLE_AGENTS.items()
        ]
    }
