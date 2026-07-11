"""Standards-compliant Model Context Protocol (MCP) adapter.

Exposes the SAME tool registry over the official MCP protocol — via stdio
(see mcp_runtime.mcp_stdio) and Streamable HTTP (mounted at /mcp by the
FastAPI app) — in addition to the custom /tools + /invoke REST API that the
companion web client uses. No tool code is duplicated: MCP `call_tool`
routes straight into `MCPServer.invoke()`, so policy, the mutation ledger,
metrics, and the kill switch all behave identically across both surfaces.

Policy mapping:
  - Every catalog tool becomes an MCP tool with its JSON-Schema inputs.
  - `requires_confirmation` tools gain an explicit `confirm` boolean in
    their MCP schema (an MCP client / human sets it to run a mutation).
  - `MCP_MUTATIONS_ENABLED` still gates every MUTATION/DESTRUCTIVE tool.
  - Risk is surfaced as MCP tool annotations (readOnlyHint / destructiveHint)
    and prefixed in the description so agents see it.
"""

from __future__ import annotations

import copy
import json
from typing import Any

import anyio
from mcp import types
from mcp.server.lowlevel import Server

from mcp_runtime.errors import ToolNotFound
from mcp_runtime.logging import get_logger
from mcp_runtime.policy import PolicyViolation
from mcp_runtime.server import MCPServer
from mcp_runtime.version import __version__

logger = get_logger("mcp.protocol")

MCP_SERVER_NAME = "sonic-mcp-community-server"
MCP_INSTRUCTIONS = (
    "Tools to inspect and safely change a SONiC switch fabric. Read tools are "
    "SAFE_READ; MUTATION/DESTRUCTIVE tools require `confirm: true` and are "
    "rejected entirely unless the server has MCP_MUTATIONS_ENABLED=1."
)


def _to_mcp_tool(spec: dict) -> types.Tool:
    """Convert a catalog entry into an MCP Tool definition."""
    schema = copy.deepcopy(spec.get("input_schema") or {"type": "object", "properties": {}})
    schema.setdefault("type", "object")
    schema.setdefault("properties", {})

    policy = spec.get("policy") or {}
    risk = policy.get("risk") or "SAFE_READ"

    if policy.get("requires_confirmation"):
        # Explicit approval flag for mutating/destructive tools.
        schema["properties"]["confirm"] = {
            "type": "boolean",
            "description": "Must be true to run this mutating/destructive tool.",
        }

    description = spec.get("description") or ""
    if risk != "SAFE_READ":
        description = f"[{risk}] {description}"

    return types.Tool(
        name=spec["name"],
        description=description,
        inputSchema=schema,
        annotations=types.ToolAnnotations(
            title=spec.get("name"),
            readOnlyHint=(risk == "SAFE_READ"),
            destructiveHint=(risk == "DESTRUCTIVE"),
            idempotentHint=(risk == "SAFE_READ"),
        ),
    )


def build_mcp_server(core: MCPServer) -> Server:
    """Build a low-level MCP `Server` backed by the shared registry/core.

    The returned server is transport-agnostic — stdio and Streamable HTTP
    both drive it.
    """
    server: Server = Server(
        MCP_SERVER_NAME, version=__version__, instructions=MCP_INSTRUCTIONS
    )

    @server.list_tools()
    async def _list_tools() -> list[types.Tool]:
        return [_to_mcp_tool(t) for t in core.list_tools()]

    @server.call_tool()
    async def _call_tool(name: str, arguments: dict[str, Any] | None):
        args = dict(arguments or {})
        confirm = bool(args.pop("confirm", False))

        def _run() -> dict:
            return core.invoke(tool_name=name, inputs=args, confirm=confirm)

        try:
            # invoke() does blocking SSH/RESTCONF I/O — run off the event loop.
            result = await anyio.to_thread.run_sync(_run)
        except ToolNotFound as e:
            raise ValueError(f"unknown tool: {name}") from e
        except PolicyViolation as e:
            # Kill switch / confirmation gate — surface as a tool error the
            # agent can read and act on.
            raise ValueError(f"policy: {e}") from e
        except ValueError:
            raise
        except Exception as e:  # unexpected — log server-side, sanitize outward
            logger.exception("mcp call_tool failed tool=%s: %s", name, e)
            raise ValueError(f"tool '{name}' failed: internal error") from e

        text = json.dumps(result, indent=2, default=str)
        payload = result.get("payload") if isinstance(result, dict) else None
        structured = payload if isinstance(payload, dict) else {"payload": payload}
        return [types.TextContent(type="text", text=text)], structured

    return server
