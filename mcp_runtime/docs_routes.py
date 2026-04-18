from __future__ import annotations

from pathlib import Path
from fastapi import APIRouter
from fastapi.responses import FileResponse, PlainTextResponse

router = APIRouter()

# repo root assumption: this file is in mcp_runtime/, so root is parent
REPO_ROOT = Path(__file__).resolve().parent.parent

TOOL_CATALOG = REPO_ROOT / "docs" / "TOOL_CATALOG.md"
MCP_OPENAPI = REPO_ROOT / "openapi" / "mcp-server" / "openapi_mcp_invoke.yaml"


@router.get("/docs/tools", response_class=PlainTextResponse)
def get_tool_catalog():
    if not TOOL_CATALOG.exists():
        return PlainTextResponse(f"Missing file: {TOOL_CATALOG}", status_code=404)
    return PlainTextResponse(TOOL_CATALOG.read_text(encoding="utf-8"))


@router.get("/openapi/mcp-invoke.yaml")
def get_mcp_openapi():
    if not MCP_OPENAPI.exists():
        return PlainTextResponse(f"Missing file: {MCP_OPENAPI}", status_code=404)
    return FileResponse(
        MCP_OPENAPI,
        media_type="application/yaml",
        filename="openapi_mcp_invoke.yaml",
    )

