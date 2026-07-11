"""Tests for the standards-compliant MCP protocol adapter.

Uses the MCP SDK's in-memory client/server session so we exercise the real
list_tools / call_tool wire path without a subprocess or a socket.
"""

from __future__ import annotations

import json

import pytest

from mcp.shared.memory import create_connected_server_and_client_session

from mcp_runtime.mcp_protocol import _to_mcp_tool, build_mcp_server


class _FakeCore:
    """Minimal stand-in for MCPServer — records invoke() calls."""

    def __init__(self, tools):
        self._tools = tools
        self.calls = []

    def list_tools(self):
        return self._tools

    def invoke(self, *, tool_name, inputs, confirm=False):
        self.calls.append({"tool": tool_name, "inputs": dict(inputs), "confirm": confirm})
        return {"tool": tool_name, "status": 200, "payload": {"ok": True, "echo": inputs}}


SAFE = {"name": "get_x", "description": "read x", "policy": {"risk": "SAFE_READ"},
        "input_schema": {"type": "object", "properties": {"switch_ip": {"type": "string"}}, "required": ["switch_ip"]}}
MUT = {"name": "set_x", "description": "change x", "policy": {"risk": "MUTATION", "requires_confirmation": True},
       "input_schema": {"type": "object", "properties": {"switch_ip": {"type": "string"}}, "required": ["switch_ip"]}}
DESTRUCTIVE = {"name": "wipe_x", "description": "wipe x", "policy": {"risk": "DESTRUCTIVE", "requires_confirmation": True},
               "input_schema": {"type": "object", "properties": {}}}


class TestToolMapping:
    def test_safe_read_is_readonly_no_confirm(self):
        t = _to_mcp_tool(SAFE)
        assert t.annotations.readOnlyHint is True
        assert "confirm" not in (t.inputSchema.get("properties") or {})
        assert not t.description.startswith("[")

    def test_mutation_gets_confirm_and_prefix(self):
        t = _to_mcp_tool(MUT)
        assert "confirm" in t.inputSchema["properties"]
        assert t.inputSchema["properties"]["confirm"]["type"] == "boolean"
        assert t.description.startswith("[MUTATION]")
        assert t.annotations.readOnlyHint is False

    def test_destructive_annotation(self):
        t = _to_mcp_tool(DESTRUCTIVE)
        assert t.annotations.destructiveHint is True
        assert t.description.startswith("[DESTRUCTIVE]")


@pytest.mark.anyio
async def test_list_and_call_over_mcp():
    core = _FakeCore([SAFE, MUT])
    server = build_mcp_server(core)
    async with create_connected_server_and_client_session(server) as session:
        await session.initialize()

        tools = await session.list_tools()
        names = {t.name for t in tools.tools}
        assert names == {"get_x", "set_x"}

        # A read call routes to invoke() with confirm=False.
        res = await session.call_tool("get_x", {"switch_ip": "10.0.0.1"})
        assert res.isError is False
        assert core.calls[-1] == {"tool": "get_x", "inputs": {"switch_ip": "10.0.0.1"}, "confirm": False}
        body = json.loads(res.content[0].text)
        assert body["payload"]["ok"] is True

        # A mutation call passes confirm through and strips it from inputs.
        await session.call_tool("set_x", {"switch_ip": "10.0.0.2", "confirm": True})
        assert core.calls[-1] == {"tool": "set_x", "inputs": {"switch_ip": "10.0.0.2"}, "confirm": True}


@pytest.fixture
def anyio_backend():
    return "asyncio"
