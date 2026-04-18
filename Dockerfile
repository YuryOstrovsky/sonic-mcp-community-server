# SONiC MCP Community Server — slim Python image.
#
# Design principles:
#   - The image is immutable and fabric-agnostic. Nothing lab-specific is baked in.
#   - All state (mutation ledger, intent file, credentials) is bind-mounted
#     from the host so the image can be pulled once and used against any fabric.
#   - Non-root user ("mcp") owns /app so bind-mounted volumes don't fight permissions.
#   - Two-stage build keeps the runtime image small (no pip cache, no build deps).

# ---------------------------------------------------------------
# Stage 1 — builder: install deps into a self-contained prefix
# ---------------------------------------------------------------
FROM python:3.11-slim AS builder

ENV PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PYTHONDONTWRITEBYTECODE=1

# Build-time tools needed by paramiko's cryptography wheel on some arches.
# On python:3.11-slim amd64 the prebuilt wheel is used and gcc isn't
# strictly required, but including it makes the image portable across arches.
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /build
COPY requirements.txt .
RUN pip install --prefix=/install --no-cache-dir -r requirements.txt


# ---------------------------------------------------------------
# Stage 2 — runtime: copy deps + app code, drop build tooling
# ---------------------------------------------------------------
FROM python:3.11-slim

LABEL org.opencontainers.image.title="SONiC MCP Community Server" \
      org.opencontainers.image.description="FastAPI-based Model Context Protocol server for SONiC switches" \
      org.opencontainers.image.source="https://github.com/YuryOstrovsky/sonic-mcp-community-server" \
      org.opencontainers.image.licenses="Apache-2.0"

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

# Non-root user; uid 1000 lines up with typical host user so bind-mount
# ownership on ./config and ./logs behaves naturally.
RUN groupadd --system --gid 1000 mcp \
 && useradd  --system --uid 1000 --gid 1000 --home-dir /app --shell /bin/bash mcp \
 && mkdir -p /app /app/config /app/logs \
 && chown -R mcp:mcp /app

# Pull installed deps from the builder stage.
COPY --from=builder /install /usr/local

WORKDIR /app

# ---------------------------------------------------------------
# Copy application code — everything outside this list is ignored
# via .dockerignore (venvs, smoke tests, docs, .env, logs/, config/…)
# ---------------------------------------------------------------
COPY --chown=mcp:mcp api/                  api/
COPY --chown=mcp:mcp mcp_runtime/          mcp_runtime/
COPY --chown=mcp:mcp sonic/                sonic/
COPY --chown=mcp:mcp generated/mcp_tools.json generated/mcp_tools.json
COPY --chown=mcp:mcp README.md             README.md
# (.env.example stays in the repo so users can `cp` it — no need to
# ship it inside the image.)

USER mcp

EXPOSE 8000

# ---------------------------------------------------------------
# Runtime defaults — overridable via `docker run -e …` or compose `environment:`
# ---------------------------------------------------------------
# Mutations ARE allowed by default; ops that want a read-only mirror flip
# this to 0 in their .env / compose file.
ENV MCP_MUTATIONS_ENABLED=1 \
    SONIC_MCP_PORT=8000 \
    SONIC_VERIFY_TLS=false

# Health probe — hits /health which doesn't require MCP session state.
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health', timeout=3)" || exit 1

# Bind-mount these at runtime. Listed for documentation only — an empty
# volume definition doesn't force users to provide one, but surfaces intent.
VOLUME ["/app/config", "/app/logs"]

ENTRYPOINT ["python", "-m", "api.run"]
