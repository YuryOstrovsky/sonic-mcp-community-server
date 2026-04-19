"""Integration test for plugin auto-discovery.

Boots the full MCPRegistry (which walks sonic.tools.*) and checks that
loading completes cleanly and every catalogued tool has a callable.
"""

from __future__ import annotations


from mcp_runtime.registry import MCPRegistry


class TestRegistryLoad:
    def test_load_without_errors(self, monkeypatch):
        # registry.load() reads generated/mcp_tools.json from cwd, so the
        # test must run with the repo root as cwd (conftest puts it on
        # sys.path; pytest run from repo root also sets cwd there).
        reg = MCPRegistry().load()
        assert len(reg.list_tools()) > 0

    def test_every_tool_has_callable_handler(self):
        reg = MCPRegistry().load()
        for tool in reg.list_tools():
            name = tool["name"]
            handler = reg.get_handler(name)
            assert callable(handler), f"{name} has no callable handler"

    def test_helpers_are_not_registered(self):
        """Private helper modules (basename starts with _) should NOT be
        exposed as tools."""
        reg = MCPRegistry().load()
        for name in reg.handlers.keys():
            assert not name.startswith("_"), f"private helper {name!r} leaked into the registry"
