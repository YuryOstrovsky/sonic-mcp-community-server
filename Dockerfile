FROM python:3.11-slim

LABEL maintainer="XCO MCP Community"
LABEL description="Read-only MCP server for ExtremeCloud Orchestrator (XCO) and RESTCONF"

# Prevent Python from writing .pyc files and enable unbuffered stdout/stderr
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# Install dependencies first (layer caching)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY api/            api/
COPY mcp_runtime/    mcp_runtime/
COPY restconf/       restconf/
COPY xco/            xco/
COPY docs/           docs/
COPY XCO_MCP_Server_User_Guide.docx        docs/
COPY XCO_MCP_Tier2_Operator_Notes.docx      docs/

# Tier-2 tool handler directories only (build utilities excluded via .dockerignore)
COPY tools/          tools/

# Generated runtime artifacts
COPY generated/mcp_tools.json        generated/mcp_tools.json
COPY generated/mcp_capabilities.json generated/mcp_capabilities.json
COPY generated/services.json         generated/services.json

# Generated OpenAPI spec for the server itself
COPY openapi/mcp-server/ openapi/mcp-server/

# Docker-specific README as the in-container documentation
COPY README.docker.md README.md

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')" || exit 1

ENTRYPOINT ["python", "-m", "api.run"]
