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
    """Prometheus scrape endpoint.

    Before emitting, we refresh cheap gauges (tools, inventory, ledger
    depth) in-line. Fabric-health gauges are refreshed at most once per
    METRIC_FABRIC_REFRESH_S seconds — they require fanout SSH so we don't
    want to hammer the switches on every scrape.
    """
    _refresh_cheap_gauges()
    _refresh_fabric_gauges_if_stale()
    return Response(
        content=generate_latest(),
        media_type=CONTENT_TYPE_LATEST,
    )


# ---------------- Gauge refresh helpers ----------------

_FABRIC_REFRESH_S = 30.0
_last_fabric_refresh = 0.0


def _refresh_cheap_gauges() -> None:
    from mcp_runtime.metrics import (
        MCP_INVENTORY_DEVICES, MCP_LEDGER_ENTRIES, MCP_LEDGER_FAILURES_24H,
        MCP_TOOLS_BY_RISK, MCP_TOOLS_TOTAL,
    )
    from mcp_runtime.mutation_ledger import LEDGER

    tools = mcp.list_tools()
    MCP_TOOLS_TOTAL.set(len(tools))
    by_risk: Dict[str, int] = {}
    for t in tools:
        r = (t.get("policy") or {}).get("risk") or "UNKNOWN"
        by_risk[r] = by_risk.get(r, 0) + 1
    for risk, n in by_risk.items():
        MCP_TOOLS_BY_RISK.labels(risk=risk).set(n)

    MCP_INVENTORY_DEVICES.set(len(mcp.inventory.all_ips()))

    entries = LEDGER.tail(n=2000)
    MCP_LEDGER_ENTRIES.set(len(entries))

    # Failed mutations in the last 24h.
    import datetime as _dt
    cutoff = _dt.datetime.now(_dt.timezone.utc) - _dt.timedelta(hours=24)
    failed = 0
    for e in entries:
        if e.get("status") != "failed":
            continue
        ts = e.get("timestamp") or ""
        try:
            t = _dt.datetime.fromisoformat(ts.replace("Z", "+00:00"))
        except Exception:
            continue
        if t >= cutoff:
            failed += 1
    MCP_LEDGER_FAILURES_24H.set(failed)


def _refresh_fabric_gauges_if_stale() -> None:
    """Populate fabric-health gauges. Rate-limited to one run every 30s
    so scraping doesn't fanout SSH on every Prometheus poll (which
    defaults to every 15s and would hammer the switches)."""
    global _last_fabric_refresh
    now = time.time()
    if now - _last_fabric_refresh < _FABRIC_REFRESH_S:
        return
    _last_fabric_refresh = now

    try:
        from mcp_runtime.metrics import (
            MCP_FABRIC_BGP_BROKEN, MCP_FABRIC_BGP_HEALTHY,
            MCP_FABRIC_BGP_ORPHAN, MCP_FABRIC_UNREACHABLE,
        )
        from sonic.tools.fabric.get_fabric_health import get_fabric_health
        result = get_fabric_health(
            inputs={"include_lldp": False},
            registry=mcp, transport=mcp.transport, context={},
        )
        s = result.get("summary") or {}
        MCP_FABRIC_BGP_HEALTHY.set(int(s.get("healthy") or 0))
        MCP_FABRIC_BGP_BROKEN.set(int(s.get("broken") or 0))
        MCP_FABRIC_BGP_ORPHAN.set(int(s.get("orphan") or 0))
        MCP_FABRIC_UNREACHABLE.set(int(s.get("unreachable") or 0))
    except Exception as e:
        # Don't kill a /metrics scrape because fabric-health had a blip.
        logger.warning("fabric gauge refresh failed: %s", e)

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


# -------------------------------------------------
# Fabric intent file — GET/PUT the JSON that
# validate_fabric_vs_intent consumes. Lets operators
# maintain intent from the web client without SSHing
# into the server / container.
# -------------------------------------------------

import json as _json
from pathlib import Path as _Path

_INTENT_ENV_VAR = "SONIC_FABRIC_INTENT_PATH"
_INTENT_DEFAULT_REL = _Path("config") / "fabric_intent.json"


def _intent_path() -> _Path:
    from sonic.inventory import _validated_config_path
    return _validated_config_path(os.environ.get(_INTENT_ENV_VAR), _INTENT_DEFAULT_REL)


@app.get("/fabric/intent")
def fabric_intent_get():
    """Return the current intent JSON content along with its path.

    When the file is missing, returns {exists: False, content: null} with
    200 so the client can render an empty editor rather than dealing with
    a 404. The path is always included so the UI can tell the user where
    on disk it lives.
    """
    path = _intent_path()
    if not path.exists():
        return {
            "exists": False,
            "path": str(path),
            "content": None,
            "source": "env" if os.environ.get(_INTENT_ENV_VAR) else "default",
        }
    try:
        text = path.read_text(encoding="utf-8")
        parsed = _json.loads(text)  # validate it's parseable
        return {
            "exists": True,
            "path": str(path),
            "content": parsed,
            "raw": text,
            "size_bytes": len(text.encode("utf-8")),
            "source": "env" if os.environ.get(_INTENT_ENV_VAR) else "default",
        }
    except _json.JSONDecodeError as e:
        # File exists but is malformed — surface raw text so the user can
        # fix it in the editor.
        return {
            "exists": True,
            "path": str(path),
            "content": None,
            "raw": path.read_text(encoding="utf-8", errors="replace"),
            "parse_error": f"invalid JSON: {e}",
            "source": "env" if os.environ.get(_INTENT_ENV_VAR) else "default",
        }


class _IntentPutBody(BaseModel):
    # Accept either parsed content (dict) or raw JSON text, to keep the
    # client simple. If both are present, `content` wins.
    content: Optional[Dict[str, Any]] = None
    raw: Optional[str] = None


@app.put("/fabric/intent")
def fabric_intent_put(body: _IntentPutBody):
    """Write a new intent file. Validates JSON before touching disk.

    Atomic write: data is written to a sibling `.tmp` file and rename()d
    over the target — readers never see a half-written file.
    """
    if body.content is None and (body.raw is None or not body.raw.strip()):
        raise HTTPException(400, "provide either `content` (object) or `raw` (JSON string)")

    if body.content is not None:
        parsed = body.content
    else:
        try:
            parsed = _json.loads(body.raw)
        except _json.JSONDecodeError as e:
            raise HTTPException(400, f"invalid JSON: {e}")

    if not isinstance(parsed, dict):
        raise HTTPException(400, "intent must be a JSON object at the top level")

    path = _intent_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(_json.dumps(parsed, indent=2) + "\n", encoding="utf-8")
        tmp.replace(path)
    except OSError as e:
        raise HTTPException(500, f"could not write intent file at {path}: {e}")

    return {
        "ok": True,
        "path": str(path),
        "size_bytes": path.stat().st_size,
    }


# -------------------------------------------------
# Fabric inventory — GET / PUT / POST / DELETE
# Live-reloaded from $SONIC_INVENTORY_PATH (default
# config/inventory.json). The client's Settings view
# uses these endpoints to manage switches without
# editing Python or restarting the container.
# -------------------------------------------------

import concurrent.futures as _concurrent_futures
from sonic.inventory import SonicDevice as _SonicDevice

# /inventory/probe does a transient inventory swap on the shared
# transport singletons. Serialising probes here keeps two concurrent
# callers from seeing each other's credentials mid-swap. The probe is
# short (~10s worst case) so a lock here is strictly simpler than
# per-transport rework.
_probe_lock = threading.Lock()


class _InventoryDeviceBody(BaseModel):
    name: str
    mgmt_ip: str
    tags: list = []
    username: Optional[str] = None
    password: Optional[str] = None


class _InventoryPutBody(BaseModel):
    switches: list[_InventoryDeviceBody]


def _device_view(d: _SonicDevice) -> Dict[str, Any]:
    """Shape a device for the wire. Never leak the password — the UI
    only needs to know that one is set."""
    return {
        "name": d.name,
        "mgmt_ip": d.mgmt_ip,
        "tags": list(d.tags or ()),
        "username": d.username,
        "has_password": bool(d.password),
    }


@app.get("/inventory")
def inventory_get():
    inv = mcp.inventory
    return {
        "path": inv.path(),
        "source": inv.source(),
        "switches": [_device_view(d) for d in inv.devices],
    }


@app.put("/inventory")
def inventory_put(body: _InventoryPutBody):
    """Replace the entire inventory with the given list."""
    devs = [
        _SonicDevice(
            name=s.name.strip() or s.mgmt_ip,
            mgmt_ip=s.mgmt_ip.strip(),
            tags=tuple(str(t) for t in (s.tags or [])),
            username=s.username or None,
            password=s.password or None,
        )
        for s in body.switches
    ]
    _validate_devices(devs)
    mcp.inventory.save(devs)
    return inventory_get()


@app.post("/inventory/switches")
def inventory_add(body: _InventoryDeviceBody):
    """Add or update a single switch. Replaces any existing entry with
    the same mgmt_ip."""
    existing = list(mcp.inventory.devices)
    new = _SonicDevice(
        name=body.name.strip() or body.mgmt_ip,
        mgmt_ip=body.mgmt_ip.strip(),
        tags=tuple(str(t) for t in (body.tags or [])),
        username=body.username or None,
        password=body.password or None,
    )
    _validate_devices([new])
    existing = [d for d in existing if d.mgmt_ip != new.mgmt_ip]
    existing.append(new)
    mcp.inventory.save(existing)
    return inventory_get()


@app.delete("/inventory/switches/{mgmt_ip}")
def inventory_delete(mgmt_ip: str):
    existing = list(mcp.inventory.devices)
    remaining = [d for d in existing if d.mgmt_ip != mgmt_ip]
    if len(remaining) == len(existing):
        raise HTTPException(404, f"switch {mgmt_ip} not in inventory")
    mcp.inventory.save(remaining)
    return inventory_get()


class _InventoryProbeBody(BaseModel):
    mgmt_ip: str
    username: Optional[str] = None
    password: Optional[str] = None


@app.post("/inventory/probe")
def inventory_probe(body: _InventoryProbeBody):
    """Test RESTCONF + SSH reachability with given creds — without
    persisting anything. Returns the same shape as /ready's per-device
    check so the UI can reuse its status rendering.

    If only `mgmt_ip` is sent, falls back to env-default credentials.
    """
    # Use a temporary inventory override so the transport picks up the
    # probed credentials without touching the live inventory.
    ip = body.mgmt_ip.strip()
    if not ip:
        raise HTTPException(400, "mgmt_ip is required")

    status: Dict[str, Any] = {"mgmt_ip": ip, "restconf": False, "ssh": False, "errors": []}
    # We build a transient SonicDevice in a fake inventory so the shared
    # credential resolver sees the override without us poking internals.
    from sonic.inventory import SonicInventory as _SI
    probe_inv = _SI(devices=[_SonicDevice(
        name=ip, mgmt_ip=ip,
        username=body.username or None,
        password=body.password or None,
    )])
    # Serialise the transient transport-inventory swap so concurrent
    # probes can't see each other's credentials.
    with _probe_lock:
        prev_rc, prev_ssh = mcp.transport.restconf.inventory, mcp.transport.ssh.inventory
        mcp.transport.restconf.inventory = probe_inv
        mcp.transport.ssh.inventory = probe_inv
        # Also invalidate any cached session/client for this IP so the
        # probe actually uses the supplied credentials.
        mcp.transport.restconf._sessions.pop(ip, None)
        try:
            mcp.transport.ssh._clients.pop(ip, None)
        except Exception:
            pass
        try:
            with _concurrent_futures.ThreadPoolExecutor(max_workers=2) as ex:
                rc_fut = ex.submit(mcp.transport.restconf.probe, ip)
                ssh_fut = ex.submit(mcp.transport.ssh.probe, ip)
                try:
                    status["restconf"] = bool(rc_fut.result(timeout=_READY_TIMEOUT))
                except Exception as e:
                    status["errors"].append(f"restconf: {e}")
                try:
                    status["ssh"] = bool(ssh_fut.result(timeout=_READY_TIMEOUT))
                except Exception as e:
                    status["errors"].append(f"ssh: {e}")
        finally:
            # Always restore — don't let a probe silently rewire live state.
            mcp.transport.restconf.inventory = prev_rc
            mcp.transport.ssh.inventory = prev_ssh
            mcp.transport.restconf._sessions.pop(ip, None)
            try:
                mcp.transport.ssh._clients.pop(ip, None)
            except Exception:
                pass
    return status


def _validate_devices(devices):
    """Common sanity checks for POST/PUT bodies."""
    seen = set()
    for d in devices:
        if not d.mgmt_ip:
            raise HTTPException(400, "each switch needs mgmt_ip")
        if d.mgmt_ip in seen:
            raise HTTPException(400, f"duplicate mgmt_ip: {d.mgmt_ip}")
        seen.add(d.mgmt_ip)
