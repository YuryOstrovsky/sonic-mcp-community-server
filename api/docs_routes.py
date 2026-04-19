# api/docs_routes.py
"""
Documentation routes that never 404.

Everything is generated on demand from `generated/mcp_tools.json` and
FastAPI's own OpenAPI spec, so the routes work out of the box — there
is no separate `docs/TOOL_CATALOG.md` to keep in sync.

  /docs/tools         → plaintext markdown catalog
  /docs/tools/html    → the same, rendered as HTML
  /openapi/mcp-invoke.yaml → FastAPI's openapi.json (valid YAML, JSON is a subset)
  /swagger            → Swagger UI pointed at the same spec

FastAPI already ships /docs and /redoc against /openapi.json — we
don't re-register those here to avoid double-handlers.
"""
from __future__ import annotations

import html
import json
from pathlib import Path
from typing import Any, Dict, List

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, PlainTextResponse

router = APIRouter()

# repo root is one dir up from /api
REPO_ROOT = Path(__file__).resolve().parent.parent
CATALOG_JSON = REPO_ROOT / "generated" / "mcp_tools.json"


def _load_catalog() -> List[Dict[str, Any]]:
    if not CATALOG_JSON.exists():
        return []
    try:
        return json.loads(CATALOG_JSON.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return []


def _render_catalog_markdown(tools: List[Dict[str, Any]]) -> str:
    if not tools:
        return "# SONiC MCP tool catalog\n\n_No tools registered._\n"

    # Group by category, keep alphabetical within each.
    buckets: Dict[str, List[Dict[str, Any]]] = {}
    for t in tools:
        buckets.setdefault(t.get("category", "misc"), []).append(t)
    for k in buckets:
        buckets[k].sort(key=lambda t: t.get("name", ""))

    lines: List[str] = []
    lines.append("# SONiC MCP tool catalog")
    lines.append("")
    lines.append(f"**{len(tools)} tools** across {len(buckets)} categories.")
    lines.append("")
    lines.append("Every row is served live at `GET /tools`. This page is")
    lines.append("generated from the same JSON — no separate doc to maintain.")
    lines.append("")

    for cat in sorted(buckets):
        lines.append(f"## {cat}")
        lines.append("")
        lines.append("| Tool | Transport | Risk | Auto-mode | Confirm? | Description |")
        lines.append("|---|---|---|---|---|---|")
        for t in buckets[cat]:
            pol = t.get("policy") or {}
            desc = (t.get("description") or "").replace("|", "\\|").replace("\n", " ")
            lines.append(
                f"| `{t.get('name','')}` "
                f"| {t.get('transport','—')} "
                f"| {pol.get('risk','?')} "
                f"| {'✓' if pol.get('allowed_in_auto_mode') else '✗'} "
                f"| {'✓' if pol.get('requires_confirmation') else '✗'} "
                f"| {desc} |"
            )
        lines.append("")

    return "\n".join(lines) + "\n"


@router.get("/docs/tools", response_class=PlainTextResponse)
def docs_tools() -> PlainTextResponse:
    return PlainTextResponse(_render_catalog_markdown(_load_catalog()))


@router.get("/docs/tools/html", response_class=HTMLResponse)
def docs_tools_html() -> HTMLResponse:
    md_text = _render_catalog_markdown(_load_catalog())
    try:
        import markdown
        body = markdown.markdown(
            md_text,
            extensions=["tables", "fenced_code", "toc"],
            output_format="html5",
        )
    except Exception:
        body = f"<pre>{html.escape(md_text)}</pre>"

    return HTMLResponse(
        f"""
<!doctype html>
<html>
  <head>
    <meta charset="utf-8"/>
    <title>MCP Tool Catalog</title>
    <meta name="viewport" content="width=device-width, initial-scale=1"/>
    <style>
      body {{ font-family: system-ui, -apple-system, Segoe UI, Roboto, Arial, sans-serif; margin: 24px; }}
      h1,h2,h3 {{ margin-top: 1.2em; }}
      pre {{ background: #f6f8fa; padding: 12px; border-radius: 8px; overflow-x: auto; }}
      code {{ background: #f6f8fa; padding: 2px 4px; border-radius: 6px; }}
      table {{ border-collapse: collapse; width: 100%; margin: 12px 0; }}
      th, td {{ border: 1px solid #e5e7eb; padding: 8px; vertical-align: top; }}
      th {{ background: #f9fafb; text-align: left; }}
      blockquote {{ border-left: 4px solid #e5e7eb; padding-left: 12px; color: #374151; }}
      a {{ color: #2563eb; text-decoration: none; }}
      a:hover {{ text-decoration: underline; }}
      .topbar {{ display:flex; gap:12px; align-items:center; margin-bottom: 16px; }}
      .pill {{ display:inline-block; padding: 2px 10px; border-radius: 999px; background: #eef2ff; color: #3730a3; font-size: 12px; }}
    </style>
  </head>
  <body>
    <div class="topbar">
      <span class="pill">SONiC MCP Community Server</span>
      <a href="/docs/tools">raw markdown</a>
      <a href="/docs">api docs</a>
      <a href="/swagger">swagger</a>
    </div>
    {body}
  </body>
</html>
        """.strip()
    )


@router.get("/openapi/mcp-invoke.yaml", response_class=PlainTextResponse)
def openapi_mcp_invoke(request: Request) -> PlainTextResponse:
    """FastAPI's own OpenAPI spec. JSON is valid YAML, so the route name
    is preserved for anyone with a link to it. The content is kept in
    sync with the server automatically."""
    spec = request.app.openapi()
    return PlainTextResponse(json.dumps(spec, indent=2))


@router.get("/swagger", response_class=HTMLResponse)
def swagger_ui() -> HTMLResponse:
    return HTMLResponse(
        """
<!doctype html>
<html>
  <head>
    <meta charset="utf-8"/>
    <title>SONiC MCP — Swagger UI</title>
    <meta name="viewport" content="width=device-width, initial-scale=1"/>
    <link rel="stylesheet" href="https://unpkg.com/swagger-ui-dist@5/swagger-ui.css" />
    <style> body { margin: 0; } </style>
  </head>
  <body>
    <div id="swagger-ui"></div>
    <script src="https://unpkg.com/swagger-ui-dist@5/swagger-ui-bundle.js"></script>
    <script src="https://unpkg.com/swagger-ui-dist@5/swagger-ui-standalone-preset.js"></script>
    <script>
      window.onload = () => {
        SwaggerUIBundle({
          url: "/openapi.json",
          dom_id: "#swagger-ui",
          presets: [SwaggerUIBundle.presets.apis, SwaggerUIStandalonePreset],
          layout: "StandaloneLayout",
          deepLinking: true
        });
      };
    </script>
  </body>
</html>
        """.strip()
    )
