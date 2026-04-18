class SafetyEnvelopeError(Exception):
    pass


class SafetyEnvelope:
    """
    Phase 5.5:
    Enforces agent-level permissions against intent risk.
    """

    def __init__(self, agent):
        self.agent = agent

    def enforce(self, intent_meta: dict):
        risk = intent_meta.get("risk")

        # ------------------------------------
        # SAFE READ — always allowed
        # ------------------------------------
        if risk == "SAFE_READ":
            return "ALLOW"

        # ------------------------------------
        # SAFE MUTATION
        # ------------------------------------
        if risk == "SAFE_MUTATE":
            if not self.agent.allow_mutation:
                raise SafetyEnvelopeError(
                    f"Agent '{self.agent.name}' is not allowed to mutate state"
                )
            return "CONFIRM_REQUIRED"

        # ------------------------------------
        # RISKY MUTATION
        # ------------------------------------
        if risk == "RISKY_MUTATE":
            if not self.agent.allow_mutation:
                raise SafetyEnvelopeError(
                    f"Agent '{self.agent.name}' is not allowed to perform risky mutations"
                )
            return "CONFIRM_REQUIRED"

        raise SafetyEnvelopeError(f"Unknown risk level: {risk}")

