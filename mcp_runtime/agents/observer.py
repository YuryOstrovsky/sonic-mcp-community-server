from mcp_runtime.agents.base import MCPAgent


class ObserverAgent(MCPAgent):
    """
    Read-only agent.
    """

    name = "observer"
    allow_mutation = False
    auto_mode_allowed = True

    def classify_intent(self, intent: str) -> dict:
        return {
            "type": "read",
            "risk": "SAFE_READ",
        }

