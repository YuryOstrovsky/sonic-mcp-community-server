from mcp_runtime.agents.base import MCPAgent


class AdminAgent(MCPAgent):
    """
    Phase 5.5:
    Admin agent — may perform any action, but still gated by confirmation.
    """

    name = "admin"
    allow_mutation = True
    auto_mode_allowed = True

    def classify_intent(self, intent: str) -> dict:
        return {
            "type": "change",
            "risk": "RISKY_MUTATE",
        }

