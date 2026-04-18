# mcp_runtime/mutation_registry.py

class MutationRegistry:
    """
    Phase 6.2:
    Registry of approved mutation tools and their rollback tools.
    """

    def __init__(self):
        # tool_name -> rollback_tool
        self._registry = {}

    def register(self, tool_name: str, *, rollback_tool: str):
        self._registry[tool_name] = rollback_tool

    def is_registered(self, tool_name: str) -> bool:
        return tool_name in self._registry

    def get_rollback(self, tool_name: str) -> str | None:
        return self._registry.get(tool_name)

