# mcp_runtime/tool_capabilities.py

from typing import Dict, Optional, List


class ToolCapabilityError(Exception):
    pass


class ToolCapabilityResolver:
    """
    Phase 4.2:
    Resolve MCP tools by declared capabilities.
    """

    def __init__(self, registry):
        self.registry = registry

    @staticmethod
    def _scope_matches(required: List[str], supported: List[List[str]]) -> bool:
        """
        required: ['fabric']
        supported: [['fabric'], ['device']]
        """
        for scope_set in supported:
            if set(required) == set(scope_set):
                return True
        return False

    def find_tool(
        self,
        action: str,
        object_: str,
        scope_keys: Optional[list] = None,
    ) -> str:
        """
        Find a tool matching requested capability.
        """

        for name, tool in self.registry.tools.items():
            caps = tool.get("capabilities")
            if not caps:
                continue

            # ---- Action match ----
            if action not in caps.get("actions", []):
                continue

            # ---- Object match ----
            if object_ not in caps.get("objects", []):
                continue

            # ---- Scope match ----
            if scope_keys:
                tool_scopes = caps.get("scopes", [])
                if not self._scope_matches(scope_keys, tool_scopes):
                    continue

            return name

        raise ToolCapabilityError(
            f"No tool found for action={action}, object={object_}, scope={scope_keys}"
        )

    def explain_match(self, action, object_, scope_keys):
        """
        Phase 4.3:
        Explain how each tool was evaluated against required capabilities
        """

        explanation = []

        for name, tool in self.registry.tools.items():
            caps = tool.get("capabilities")
            if not caps:
                continue

            action_ok = action in caps.get("actions", [])
            object_ok = object_ in caps.get("objects", [])
            scope_ok = (
                True
                if not scope_keys
                else self._scope_matches(
                    scope_keys,
                    caps.get("scopes", []),
                )
            )

            matched = action_ok and object_ok and scope_ok

            explanation.append({
                "tool": name,
                "capabilities": caps,
                "matched": matched,
                "reason": (
                    "action/object/scope matched"
                    if matched else
                    "capability mismatch"
                ),
            })

        return explanation
