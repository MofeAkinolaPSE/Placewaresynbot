from fastapi import APIRouter, Request, Depends
from pydantic import BaseModel
from typing import Any, Dict, List
from src.middleware import verify_jwt
from src.agents.router import route_question, merge_insights
from src.agent_registry import get_agent

router = APIRouter(prefix="/agents", tags=["agents"])


class AgentExecRequest(BaseModel):
    question: str
    mode: str | None = None


@router.post("/execute")
async def api_execute_agents(payload: AgentExecRequest, request: Request, user=Depends(lambda r: verify_jwt(r))):
    roles = set(getattr(request.state, "user", {}).get("roles") or [])
    mode = payload.mode or ("executive" if "admin" in roles or "management" in roles else "assistant")
    agent_names = route_question(payload.question, roles, mode)
    agent_insights: List[Dict[str, Any]] = []
    for name in agent_names:
        agent = get_agent(name, context={
            "db_executor": None,
            "query_specs": [],
            "cache": None,
            "workflow_engine": None,
        })
        if not agent:
            continue
        insight = agent.run()
        ins_dict = getattr(insight, "__dict__", insight)
        agent_insights.append(ins_dict)
    merged = merge_insights(agent_insights) if agent_insights else {}
    return {"agents_executed": agent_names, "merged": merged, "insights": agent_insights}
