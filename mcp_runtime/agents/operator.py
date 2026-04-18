from mcp_runtime.agents.base import MCPAgent


class OperatorAgent(MCPAgent):
    """
    Phase 5.1:
    Operator agent — may mutate, but requires confirmation.
    """

    name = "operator"
    allow_mutation = True
    auto_mode_allowed = False

    def classify_intent(self, intent: str) -> dict:
        return {
            "type": "change",
            "risk": "SAFE_MUTATE",
        }


