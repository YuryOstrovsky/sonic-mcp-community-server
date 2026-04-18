"""SONiC MCP server core.

Responsibilities:
- Load tool registry (catalog + handlers)
- Dispatch /invoke calls to handlers
- Enforce policy (SAFE_READ only today)
- Emit Prometheus metrics, structured logs, request/correlation IDs
- Maintain simple session-backed context (switch_ip)
"""

from __future__ import annotations

import time
from typing import Optional

from dotenv import load_dotenv

from mcp_runtime.errors import ToolNotFound
from mcp_runtime.logging import get_logger, setup_logging
from mcp_runtime.metrics import (
    MCP_INVOKE_FAILURE,
    MCP_INVOKE_LATENCY,
    MCP_INVOKE_STATUS,
    MCP_INVOKE_SUCCESS,
    MCP_INVOKE_TOTAL,
    safe_label,
)
from mcp_runtime.mutation_ledger import LEDGER as MUTATION_LEDGER
from mcp_runtime.policy import enforce_policy
from mcp_runtime.registry import MCPRegistry
from mcp_runtime.session import MCPSession
from mcp_runtime.tracing import new_correlation_id, new_request_id

from sonic.inventory import SonicInventory
from sonic.transport import SonicTransport

_MUTATION_RISKS = {"MUTATION", "DESTRUCTIVE"}


setup_logging()
logger = get_logger("mcp.server")
invoke_logger = get_logger("mcp.invoke")
load_dotenv()


class MCPServer:
    def __init__(self, auto_mode: bool = False):
        self.registry = MCPRegistry().load()
        self.auto_mode = auto_mode
        self.inventory = SonicInventory()
        self.transport = SonicTransport(inventory=self.inventory)
        logger.info(
            "MCPServer initialized auto_mode=%s tools=%d devices=%d",
            self.auto_mode,
            len(self.registry.list_tools()),
            len(self.inventory.devices),
        )

    def list_tools(self):
        return self.registry.list_tools()

    def invoke(
        self,
        tool_name: str,
        inputs: dict,
        context: Optional[dict] = None,
        session: Optional[MCPSession] = None,
        confirm: bool = False,
    ) -> dict:
        request_id = new_request_id()
        correlation_id = (
            session.correlation_id
            if session and hasattr(session, "correlation_id")
            else new_correlation_id()
        )

        invoke_logger.info(
            "invoke start tool=%s request_id=%s correlation_id=%s confirm=%s",
            tool_name,
            request_id,
            correlation_id,
            confirm,
        )

        start_ts = time.time()
        MCP_INVOKE_TOTAL.labels(tool=safe_label(tool_name)).inc()

        try:
            tool = self.registry.get(tool_name)
            if not tool:
                raise ToolNotFound(tool_name)

            enforce_policy(tool, auto_mode=self.auto_mode, confirm=confirm)

            merged_ctx: dict = {}
            if session:
                merged_ctx.update(session.get_context() or {})
            if context:
                merged_ctx.update(context)
            if "switch_ip" in inputs and "switch_ip" not in merged_ctx:
                merged_ctx["switch_ip"] = inputs["switch_ip"]

            handler = self.registry.get_handler(tool_name)
            if handler is None:
                raise ToolNotFound(f"no handler registered for {tool_name}")

            risk = (tool.get("policy") or {}).get("risk", "SAFE_READ")

            try:
                payload = handler(
                    inputs=inputs,
                    registry=self.registry,
                    transport=self.transport,
                    context=merged_ctx,
                )
            except Exception as handler_err:
                # If a MUTATION handler raised, record the failure in the ledger
                # before re-raising, so audit trails show the attempt.
                if risk in _MUTATION_RISKS:
                    MUTATION_LEDGER.record(
                        tool=tool_name,
                        risk=risk,
                        switch_ip=inputs.get("switch_ip"),
                        inputs=inputs,
                        status="failed",
                        error=str(handler_err),
                        request_id=request_id,
                        correlation_id=correlation_id,
                        session_id=session.session_id if session else None,
                    )
                raise

            # Successful MUTATION — record pre/post if the handler returned them.
            if risk in _MUTATION_RISKS:
                pre_state = None
                post_state = None
                if isinstance(payload, dict):
                    pre_state = payload.get("pre_state")
                    post_state = payload.get("post_state")
                entry = MUTATION_LEDGER.record(
                    tool=tool_name,
                    risk=risk,
                    switch_ip=inputs.get("switch_ip"),
                    inputs=inputs,
                    status="ok",
                    pre_state=pre_state,
                    post_state=post_state,
                    request_id=request_id,
                    correlation_id=correlation_id,
                    session_id=session.session_id if session else None,
                )
                # Surface the mutation_id in the payload so the client can
                # reference it (e.g., for a "View in Activity" link).
                if isinstance(payload, dict):
                    payload.setdefault("mutation_id", entry["mutation_id"])

            duration = time.time() - start_ts
            MCP_INVOKE_SUCCESS.labels(tool=safe_label(tool_name)).inc()
            MCP_INVOKE_LATENCY.labels(tool=safe_label(tool_name)).observe(duration)
            MCP_INVOKE_STATUS.labels(
                tool=safe_label(tool_name), status="200"
            ).inc()

            if session:
                session.update_context(merged_ctx)

            invoke_logger.info(
                "invoke success tool=%s duration_ms=%d correlation_id=%s",
                tool_name,
                int(duration * 1000),
                correlation_id,
            )

            return {
                "tool": tool_name,
                "status": 200,
                "payload": payload,
                "context": merged_ctx,
                "meta": {
                    "request_id": request_id,
                    "correlation_id": correlation_id,
                    "risk": tool["policy"]["risk"],
                    "transport": tool.get("transport"),
                    "duration_ms": int(duration * 1000),
                },
                "explain": {
                    "policy": {
                        "risk": tool["policy"]["risk"],
                        "mode": "auto" if self.auto_mode else "manual",
                    },
                    "transport": tool.get("transport"),
                },
            }

        except Exception as e:
            MCP_INVOKE_FAILURE.labels(tool=safe_label(tool_name)).inc()
            MCP_INVOKE_STATUS.labels(
                tool=safe_label(tool_name), status="exception"
            ).inc()
            invoke_logger.exception(
                "invoke failed tool=%s request_id=%s correlation_id=%s error=%s",
                tool_name,
                request_id,
                correlation_id,
                str(e),
            )
            raise


def create_server() -> MCPServer:
    return MCPServer(auto_mode=False)


if __name__ == "__main__":
    mcp = create_server()
    logger.info("MCP Server started")
    for t in mcp.list_tools():
        logger.info("registered tool=%s", t["name"])
