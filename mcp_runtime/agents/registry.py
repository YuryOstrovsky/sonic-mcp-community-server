# mcp_runtime/agents/registry.py

from mcp_runtime.agents.observer import ObserverAgent
from mcp_runtime.agents.operator import OperatorAgent
from mcp_runtime.agents.admin import AdminAgent


AGENT_MAP = {
    "observer": ObserverAgent,
    "operator": OperatorAgent,
    "admin": AdminAgent,
}


def get_agent(agent_name: str):
    cls = AGENT_MAP.get(agent_name)
    if not cls:
        raise ValueError(f"Unknown agent: {agent_name}")
    return cls()

