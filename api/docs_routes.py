# api/docs_routes.py
from pathlib import Path
from fastapi import APIRouter
from fastapi.responses import PlainTextResponse
from fastapi.responses import HTMLResponse
import html

router = APIRouter()

# This file is api/docs_routes.py -> repo root is parent of /api
REPO_ROOT = Path(__file__).resolve().parent.parent

TOOL_CATALOG = REPO_ROOT / "docs" / "TOOL_CATALOG.md"
MCP_OPENAPI = REPO_ROOT / "openapi" / "mcp-server" / "openapi_mcp_invoke.yaml"


@router.get("/docs/tools", response_class=PlainTextResponse)
def docs_tools():
    if not TOOL_CATALOG.exists():
        return PlainTextResponse(f"Missing file: {TOOL_CATALOG}", status_code=404)
    return PlainTextResponse(TOOL_CATALOG.read_text(encoding="utf-8"))


@router.get("/openapi/mcp-invoke.yaml", response_class=PlainTextResponse)
def openapi_mcp_invoke():
    # PlainTextResponse makes the browser display it instead of downloading
    if not MCP_OPENAPI.exists():
        return PlainTextResponse(f"Missing file: {MCP_OPENAPI}", status_code=404)
    return PlainTextResponse(MCP_OPENAPI.read_text(encoding="utf-8"))

@router.get("/swagger", response_class=HTMLResponse)
def swagger_ui():
    # Swagger UI loads the YAML directly from your server
    return HTMLResponse(
        """
<!doctype html>
<html>
  <head>
    <meta charset="utf-8"/>
    <title>MCP /invoke Swagger UI</title>
    <meta name="viewport" content="width=device-width, initial-scale=1"/>
    <link rel="stylesheet" href="https://unpkg.com/swagger-ui-dist@5/swagger-ui.css" />
    <style>
      body { margin: 0; }
    </style>
  </head>
  <body>
    <div id="swagger-ui"></div>

    <script src="https://unpkg.com/swagger-ui-dist@5/swagger-ui-bundle.js"></script>
    <script src="https://unpkg.com/swagger-ui-dist@5/swagger-ui-standalone-preset.js"></script>
    <script>
      window.onload = () => {
        SwaggerUIBundle({
          url: "/openapi/mcp-invoke.yaml",
          dom_id: "#swagger-ui",
          presets: [
            SwaggerUIBundle.presets.apis,
            SwaggerUIStandalonePreset
          ],
          layout: "StandaloneLayout",
          deepLinking: true
        });
      };
    </script>
  </body>
</html>
        """.strip()
    )

@router.get("/redoc", response_class=HTMLResponse)
def redoc():
    return HTMLResponse(
        """
<!doctype html>
<html>
  <head>
    <meta charset="utf-8"/>
    <title>MCP /invoke ReDoc</title>
    <meta name="viewport" content="width=device-width, initial-scale=1"/>
    <style> body { margin: 0; } </style>
  </head>
  <body>
    <redoc spec-url="/openapi/mcp-invoke.yaml"></redoc>
    <script src="https://unpkg.com/redoc@next/bundles/redoc.standalone.js"></script>
  </body>
</html>
        """.strip()
    )


@router.get("/docs/tools/html", response_class=HTMLResponse)
def docs_tools_html():
    if not TOOL_CATALOG.exists():
        return HTMLResponse(f"<h3>Missing file:</h3><pre>{TOOL_CATALOG}</pre>", status_code=404)

    md_text = TOOL_CATALOG.read_text(encoding="utf-8")

    try:
        import markdown  # pip install markdown
        body = markdown.markdown(
            md_text,
            extensions=["tables", "fenced_code", "toc"],
            output_format="html5",
        )
    except Exception:
        # Fallback: show as preformatted text if markdown package missing
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
    </div>
    {body}
  </body>
</html>
        """.strip()
    )

