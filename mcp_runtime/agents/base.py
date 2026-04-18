from abc import ABC, abstractmethod


class MCPAgent(ABC):
    """
    Phase 5.0:
    Base class for all agents.
    """

    name: str = "base"
    allow_mutation: bool = False
    auto_mode_allowed: bool = False

    @abstractmethod
    def classify_intent(self, intent: str) -> dict:
        """
        Return intent classification metadata.
        Example:
        {
          "type": "read",
          "risk": "SAFE_READ"
        }
        """
        raise NotImplementedError



