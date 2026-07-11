"""stdio entrypoint for the SONiC MCP server.

This is the standards-compliant MCP transport for local MCP clients such as
Claude Desktop, which launch the server as a subprocess and speak MCP over
stdin/stdout.

Run directly:
    python -m mcp_runtime.mcp_stdio

Claude Desktop (claude_desktop_config.json):
    {
      "mcpServers": {
        "sonic": {
          "command": "python",
          "args": ["-m", "mcp_runtime.mcp_stdio"],
          "cwd": "/absolute/path/to/sonic-mcp-community-server",
          "env": { "SONIC_DEFAULT_USERNAME": "admin", "SONIC_DEFAULT_PASSWORD": "..." }
        }
      }
    }

The same registry, policy, ledger, and kill switch apply as for the REST API.
"""

from __future__ import annotations

import anyio

from mcp.server.stdio import stdio_server

from mcp_runtime.logging import get_logger
from mcp_runtime.mcp_protocol import build_mcp_server
from mcp_runtime.server import create_server

logger = get_logger("mcp.stdio")


async def _serve() -> None:
    core = create_server()
    server = build_mcp_server(core)
    logger.info("MCP stdio server ready (%d tools)", len(core.list_tools()))
    async with stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream,
            write_stream,
            server.create_initialization_options(),
        )


def main() -> None:
    anyio.run(_serve)


if __name__ == "__main__":
    main()
