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


# Available agent domains for task routing
AVAILABLE_AGENTS = {
    "financial_agent": "Financial analysis, P&L, cashflow, AR/AP trends",
    "inventory_agent": "Inventory levels, stock movements, expiry tracking",
    "compliance_agent": "Regulatory compliance, audit logs, policy violations",
    "cold_chain_agent": "Temperature monitoring, cold storage, spoilage risk",
    "logistics_agent": "Shipping, deliveries, supply chain capacity",
    "revenue_agent": "Revenue forecasts, pricing, profitability",
    "enterprise_risk_agent": "Risk assessment, mitigation strategies",
    "process_optimization_agent": "Workflow efficiency, automation opportunities",
    "import_agent": "Import status, customs, procurement tracking",
}


class IntentRequest(BaseModel):
    text: str
    simulation_mode: bool = False


class IntentParser:
    """
    Parses free-form executive text into structured intent using LLM.
    """

    PARSE_PROMPT = """You are an executive intent parser for {brand}, a pharmaceutical distribution company.

Given the executive's statement, extract a structured intent with these fields:
- intent_type: One of [capacity_analysis, financial_review, compliance_check, inventory_audit, risk_assessment, forecast, optimization, status_update, action_request]
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
            prompt = self.PARSE_PROMPT.format(
                brand=BOT_BRAND, domains=domains_list, text=text
            )
            
            response = llm.generate_response(
                context="",
                question=prompt,
                instruction="You are a JSON extraction engine. Output ONLY valid JSON with no additional text."
            )
            
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
        """Fallback parsing using keyword detection."""
        text_lower = text.lower()
        
        # Check for task creation intent first
        if any(w in text_lower for w in ["create task", "add task", "new task", "remind me", "schedule", "todo", "to-do", "meeting"]):
            intent_type = "create_task"
            domains = []
            # Try to extract task details
            priority = "medium"
            if any(w in text_lower for w in ["urgent", "critical", "asap", "immediately"]):
                priority = "critical"
            elif any(w in text_lower for w in ["high priority", "important"]):
                priority = "high"
            elif any(w in text_lower for w in ["low priority", "whenever", "eventually"]):
                priority = "low"
            return {
                "intent_type": intent_type,
                "scope": "specific_item",
                "urgency": priority,
                "domains": domains,
                "parameters": {"task_text": text, "priority": priority},
                "original_text": text,
            }
        
        # Detect intent type from keywords
        if any(w in text_lower for w in ["revenue", "profit", "cashflow", "p&l", "ar", "ap", "financial"]):
            intent_type = "financial_review"
            domains = ["financial_agent", "revenue_agent"]
        elif any(w in text_lower for w in ["stock", "inventory", "expir", "quantity"]):
            intent_type = "inventory_audit"
            domains = ["inventory_agent"]
        elif any(w in text_lower for w in ["compliance", "audit", "regulation", "nafdac"]):
            intent_type = "compliance_check"
            domains = ["compliance_agent"]
        elif any(w in text_lower for w in ["risk", "threat", "vulnerability"]):
            intent_type = "risk_assessment"
            domains = ["enterprise_risk_agent"]
        elif any(w in text_lower for w in ["forecast", "predict", "project"]):
            intent_type = "forecast"
            domains = ["financial_agent", "inventory_agent"]
        elif any(w in text_lower for w in ["delivery", "shipment", "logistics", "capacity"]):
            intent_type = "capacity_analysis"
            domains = ["logistics_agent"]
        else:
            intent_type = "status_update"
            domains = ["financial_agent"]

        return {
            "intent_type": intent_type,
            "scope": "global",
            "urgency": "medium",
            "domains": domains,
            "parameters": {},
            "original_text": text,
        }


class TaskDecomposer:
    """
    Decomposes structured intent into concrete agent tasks.
    """

    TASK_MAPPING = {
        "financial_review": [
            {"agent": "financial_agent", "action": "get_summary"},
            {"agent": "revenue_agent", "action": "get_trends"},
        ],
        "inventory_audit": [
            {"agent": "inventory_agent", "action": "get_stock_levels"},
            {"agent": "inventory_agent", "action": "get_expiry_alerts"},
        ],
        "compliance_check": [
            {"agent": "compliance_agent", "action": "get_violations"},
            {"agent": "compliance_agent", "action": "get_audit_status"},
        ],
        "risk_assessment": [
            {"agent": "enterprise_risk_agent", "action": "assess_risks"},
        ],
        "forecast": [
            {"agent": "financial_agent", "action": "forecast"},
            {"agent": "inventory_agent", "action": "demand_forecast"},
        ],
        "capacity_analysis": [
            {"agent": "logistics_agent", "action": "capacity"},
            {"agent": "cold_chain_agent", "action": "storage_status"},
        ],
        "optimization": [
            {"agent": "process_optimization_agent", "action": "analyze_workflows"},
        ],
        "status_update": [
            {"agent": "financial_agent", "action": "get_summary"},
        ],
        "action_request": [
            {"agent": "process_optimization_agent", "action": "recommend"},
        ],
        "create_task": [],  # No agent tasks - handled directly
    }

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
    
    # Handle task creation intent specially
    if intent.get("intent_type") == "create_task":
        return await _handle_task_creation(intent, text, simulation)
    
    # 2. Decompose into tasks
    decomposer = TaskDecomposer()
    tasks = decomposer.decompose(intent)
    logger.info(f"Decomposed into {len(tasks)} tasks")
    
    # 3. Dispatch tasks (or simulate)
    outputs = []
    for t in tasks:
        agent = t.get("agent")
        task = t.get("task")
        
        if simulation:
            outputs.append({
                "agent": agent,
                "result": f"[SIMULATION] Would execute {task.get('action')} on {agent}",
                "status": "simulated",
            })
        else:
            try:
                tid = agent_router.send_task(agent, task)
                outputs.append({"agent": agent, "task_id": tid, "status": "dispatched"})
            except Exception as e:
                outputs.append({"agent": agent, "error": str(e), "status": "failed"})
    
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
