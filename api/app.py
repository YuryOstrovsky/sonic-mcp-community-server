# api/app.py

import concurrent.futures
import os
import threading
import time
from collections import deque
from datetime import datetime, timezone

from fastapi import FastAPI, HTTPException, Header, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from prometheus_client import generate_latest, CONTENT_TYPE_LATEST
from pydantic import BaseModel
from starlette.middleware.base import BaseHTTPMiddleware
from typing import Optional, Dict, Any

from mcp_runtime.server import MCPServer
from mcp_runtime.session_store import SessionStore
from mcp_runtime.errors import ToolNotFound
from mcp_runtime.policy import PolicyViolation
from mcp_runtime.logging import get_logger
from api.docs_routes import router as docs_router

logger = get_logger("mcp.api")

# -------------------------------------------------
# App & MCP initialization
# -------------------------------------------------

app = FastAPI(title="SONiC MCP Community Server")

# Fix #24: CORS — restrictive by default; set CORS_ORIGINS env var to allow
# specific origins (comma-separated), or "*" for any origin.
_cors_origins_raw = os.environ.get("CORS_ORIGINS", "")
_cors_origins = [o.strip() for o in _cors_origins_raw.split(",") if o.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type", "X-MCP-Session"],
)

# -------------------------------------------------
# Fix #21: Request / response logging middleware
# -------------------------------------------------

class RequestLoggingMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        start = time.perf_counter()
        response = await call_next(request)
        duration_ms = int((time.perf_counter() - start) * 1000)
        logger.info(
            "http method=%s path=%s status=%s duration_ms=%d",
            request.method,
            request.url.path,
            response.status_code,
            duration_ms,
        )
        return response

app.add_middleware(RequestLoggingMiddleware)

# -------------------------------------------------
# Fix #16: Request body size limit
# -------------------------------------------------
_MAX_BODY_BYTES = int(os.environ.get("MCP_MAX_BODY_SIZE", str(1 * 1024 * 1024)))  # default 1 MB


class BodySizeLimitMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        content_length = request.headers.get("content-length")
        if content_length and int(content_length) > _MAX_BODY_BYTES:
            return Response(
                content=f"Request body too large (max {_MAX_BODY_BYTES} bytes)",
                status_code=413,
            )
        return await call_next(request)

app.add_middleware(BodySizeLimitMiddleware)

app.include_router(docs_router)
mcp = MCPServer(auto_mode=False)
session_store = SessionStore()

# -------------------------------------------------
# Fix #13: In-memory rate limiter (sliding window per IP)
# -------------------------------------------------
_RATE_LIMIT_RPM = int(os.environ.get("MCP_RATE_LIMIT_RPM", "60"))  # requests/minute/IP
_rate_store: dict[str, deque] = {}
_rate_lock = threading.Lock()


def _is_rate_limited(ip: str) -> bool:
    now = time.monotonic()
    window = 60.0
    with _rate_lock:
        if ip not in _rate_store:
            _rate_store[ip] = deque()
        q = _rate_store[ip]
        # evict timestamps outside the sliding window
        while q and now - q[0] > window:
            q.popleft()
        if len(q) >= _RATE_LIMIT_RPM:
            return True
        q.append(now)
        return False


# -------------------------------------------------
# Models
# -------------------------------------------------

class InvokeRequest(BaseModel):
    tool: str
    inputs: Dict[str, Any] = {}
    context: Optional[Dict[str, Any]] = None
    # For tools with policy.requires_confirmation=true, the caller MUST send
    # confirm=true. Without it the server returns 403 PolicyViolation.
    confirm: bool = False


# -------------------------------------------------
# Endpoints
# -------------------------------------------------

@app.post("/invoke")
def invoke_tool(
    request: Request,
    req: InvokeRequest,
    x_mcp_session: Optional[str] = Header(default=None),
):
    """
    Invoke an MCP tool with optional session support.

    - Session is carried via X-MCP-Session header
    - If missing, a new session is created
    """
    # Fix #13: rate limit per client IP
    client_ip = request.client.host if request.client else "unknown"
    if _is_rate_limited(client_ip):
        raise HTTPException(
            status_code=429,
            detail=f"Rate limit exceeded ({_RATE_LIMIT_RPM} requests/minute)",
        )

    # Fix #3: validate tool name against registry before invoking
    if req.tool not in mcp.registry.tools:
        raise HTTPException(status_code=404, detail=f"Tool '{req.tool}' not found")

    try:
        session = session_store.get_or_create(x_mcp_session)

        result = mcp.invoke(
            tool_name=req.tool,
            inputs=req.inputs,
            context=req.context,
            session=session,
            confirm=req.confirm,
        )

        return {
            "session_id": session.session_id,
            "result": result,
        }

    # Fix #4: map specific exceptions to correct HTTP codes
    except ToolNotFound as e:
        raise HTTPException(status_code=404, detail=str(e))
    except PolicyViolation as e:
        raise HTTPException(status_code=403, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/tools")
def list_tools():
    return mcp.list_tools()


@app.get("/health")
def health():
    return {
        "status": "ok",
        "service": "sonic-mcp",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "version": "1.0",
    }

@app.get("/metrics")
def metrics():
    return Response(
        content=generate_latest(),
        media_type=CONTENT_TYPE_LATEST,
    )

# Fix #9: per-check timeout so /ready cannot hang indefinitely
_READY_TIMEOUT = 10  # seconds

@app.get("/ready")
def readiness_check(response: Response):
    """Readiness probe:
    - registry loaded
    - each inventory device reachable on at least one transport (RESTCONF or SSH)
    """
    checks: Dict[str, Any] = {"registry": False, "devices": {}}
    errors = []

    try:
        tools = mcp.list_tools()
        if tools:
            checks["registry"] = True
        else:
            errors.append("registry_empty")
    except Exception as e:
        errors.append(f"registry_error: {e}")

    for ip in mcp.inventory.all_ips():
        device_status: Dict[str, Any] = {"restconf": False, "ssh": False}
        try:
            with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
                rc_fut = executor.submit(mcp.transport.restconf.probe, ip)
                ssh_fut = executor.submit(mcp.transport.ssh.probe, ip)
                device_status["restconf"] = bool(
                    rc_fut.result(timeout=_READY_TIMEOUT)
                )
                device_status["ssh"] = bool(
                    ssh_fut.result(timeout=_READY_TIMEOUT)
                )
        except concurrent.futures.TimeoutError:
            errors.append(f"device_{ip}_timeout_after_{_READY_TIMEOUT}s")
        except Exception as e:
            errors.append(f"device_{ip}_error: {e}")
        checks["devices"][ip] = device_status

    any_device_ok = any(
        d.get("restconf") or d.get("ssh")
        for d in checks["devices"].values()
    )

    if checks["registry"] and any_device_ok:
        return {"status": "ready", "checks": checks}

    response.status_code = 503
    return {"status": "not_ready", "checks": checks, "errors": errors}
