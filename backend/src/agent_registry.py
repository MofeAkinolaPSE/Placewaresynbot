from dataclasses import dataclass
from typing import Dict, Type, Optional, List

from src.agents.base_agent import BaseAgent


_REGISTRY: Dict[str, Type[BaseAgent]] = {}


def register_agent(agent_cls: Type[BaseAgent]):
    """Register an agent class by its `name` attribute or class name.

    Usage:

    @register_agent
    class MyAgent(BaseAgent):
        name = "my_agent"

    """

    name = getattr(agent_cls, "name", agent_cls.__name__)
    _REGISTRY[name] = agent_cls
    return agent_cls


def get_agent(name: str, context: Optional[dict] = None) -> Optional[BaseAgent]:
    cls = _REGISTRY.get(name)
    if cls is None:
        return None
    return cls(context=context)


def list_agents() -> Dict[str, Type[BaseAgent]]:
    """Return the full registry of agent name -> agent class."""
    return dict(_REGISTRY)


@dataclass
class AgentEntry:
    name: str
    cls: Type[BaseAgent]


def registered_entries() -> List[AgentEntry]:
    return [AgentEntry(name=n, cls=c) for n, c in _REGISTRY.items()]
