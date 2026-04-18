# SONiC MCP Community Server — Client Contract

A single-page spec of what a demo/production MCP client needs to speak to this server. Designed so another Claude session (or another engineer) can pick up the client work cold.

This doc captures the **HTTP/JSON protocol** and the **current tool surface**. The protocol is stable across Phase 2/3/future tool additions — only the catalog grows.

---

## 1. Server summary

- **Protocol:** HTTP, JSON bodies
- **Default address:** `http://<host>:8000` (configurable via `SONIC_MCP_PORT`)
- **Auth on the server itself:** none (it's a trusted-network service today)
- **Lab host:** `http://10.46.11.8:8000` (the VMs themselves are `10.46.11.50/51`)

---

## 2. Endpoints

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/invoke` | Invoke a tool (the one that matters) |
| `GET` | `/tools` | Tool catalog — machine-readable JSON array |
| `GET` | `/health` | Liveness — always fast, never touches devices |
| `GET` | `/ready` | Readiness — probes every inventory device on both transports |
| `GET` | `/metrics` | Prometheus text format |
| `GET` | `/docs` | FastAPI Swagger UI |
| `GET` | `/openapi.json` | FastAPI OpenAPI schema |

### Operational limits

- **Rate limit:** 60 requests/minute/IP (sliding window). `429` if exceeded. Configurable server-side via `MCP_RATE_LIMIT_RPM`.
- **Body size cap:** 1 MB per request. `413` if exceeded.
- **CORS:** off by default. Set `CORS_ORIGINS` env on the server for cross-origin clients.

---

## 3. `/invoke` request envelope

```http
POST /invoke HTTP/1.1
Content-Type: application/json
X-MCP-Session: <uuid>           # optional; server creates one if absent
```

```json
{
  "tool": "<tool_name>",
  "inputs": { "...": "..." },
  "context": { "switch_ip": "10.46.11.50" }   // optional; merged with session context
}
```

### Fields

| Field | Required | Notes |
|---|---|---|
| `tool` | ✅ | Must match one of the names returned by `GET /tools` |
| `inputs` | ✅ (may be `{}`) | Must satisfy the tool's `input_schema` |
| `context` | ⭕ | Free-form key/value. Server merges session context + this body context + any `switch_ip` in `inputs`. Session persists context across calls. |

### Session header

- Send `X-MCP-Session: <uuid>` to reuse a session across calls — the server will remember context (like the last `switch_ip`).
- Omit on the first call — the server generates a session ID and returns it in the response body.
- The client should **save and reuse** the returned session ID for the remainder of the user's interaction.

---

## 4. `/invoke` response envelope

**HTTP 200** on success (even when the underlying tool returned a semantic "no data" result — the protocol-level `status=200` means "the server invoked the tool"; the tool's own payload contains semantic status).

```json
{
  "session_id": "dbe6da2a-890b-429d-bc94-404c37704e01",
  "result": {
    "tool": "get_system_info",
    "status": 200,
    "payload": {
      "summary": { "...": "..." },
      "<domain>": { "...": "..." }
    },
    "context": {
      "switch_ip": "10.46.11.50"
    },
    "meta": {
      "request_id": "req-c949f77f",
      "correlation_id": "corr-2a39bc66",
      "risk": "SAFE_READ",
      "transport": "ssh",
      "duration_ms": 800
    },
    "explain": {
      "policy": { "risk": "SAFE_READ", "mode": "manual" },
      "transport": "ssh"
    }
  }
}
```

### Field semantics

- `session_id` — the client should store this and send it on subsequent calls.
- `result.tool` — echoes the invoked tool name.
- `result.status` — integer; always `200` on successful invocation. HTTP-level non-2xx means the server itself (not the tool) rejected or failed.
- `result.payload` — tool-specific. **Always an object with a `summary` key plus one or more domain keys.** See per-tool payload shapes below.
- `result.context` — the resolved context after merging session + body + inputs. Clients can surface this (e.g., "querying switch 10.46.11.50").
- `result.meta` — observability: request ID, correlation ID, tool's risk tier, transport used, latency.
- `result.explain` — policy decision and transport. Useful for UI "why did this happen" affordances.

---

## 5. HTTP error mapping

The server maps exceptions to HTTP codes **at the `/invoke` layer**. These are reliable — build the client's error handler off of them.

| HTTP status | Meaning | Client UX |
|---|---|---|
| `400` | Client input malformed at FastAPI layer (bad JSON, missing body, etc.) | Inline validation error |
| `403` | `PolicyViolation` — tool requires confirmation or not allowed in current mode | Surface policy message, offer to re-run with confirmation |
| `404` | Unknown tool name | Suggest nearest tool name from `/tools` |
| `413` | Body too large | "Request too large, try a narrower filter" |
| `422` | `ValueError` raised by handler (e.g. missing `switch_ip`, bad `command` in `run_show_command`) | Show the error message — it's user-facing |
| `429` | Rate limited | Back off; show a soft message |
| `500` | Handler raised an unexpected exception (upstream timeout, RESTCONF 5xx bubbled up, SSH connect failure) | Generic error + correlation ID for troubleshooting |
| `503` | Returned by `/ready` when not ready | Degrade gracefully; some tools may still work |

### Error body shape

```json
{ "detail": "human-readable message" }
```

FastAPI standard. Client should always display `detail`.

---

## 6. `GET /tools` — tool catalog

Returns a JSON array of tool specs. Each entry:

```json
{
  "name": "get_interfaces",
  "description": "...",
  "category": "interfaces",
  "transport": "restconf",
  "input_schema": {
    "type": "object",
    "properties": { "switch_ip": {"type":"string"}, "name": {"type":"string"} },
    "required": ["switch_ip"]
  },
  "policy": {
    "risk": "SAFE_READ",
    "allowed_in_auto_mode": true,
    "requires_confirmation": false
  },
  "tags": ["read","interfaces","openconfig","tier2"]
}
```

Clients should **fetch this at startup** (and maybe periodically) to render the tool picker UI. Don't hardcode tool lists in the client.

### Policy flags the client cares about

- `risk` — `SAFE_READ` is the only risk tier in Phase 1/2. Phase 3+ will add `MUTATION`, `DESTRUCTIVE`. Render a warning badge for anything ≠ `SAFE_READ`.
- `requires_confirmation` — if true, show a "confirm before running" modal.
- `allowed_in_auto_mode` — controls whether an autonomous agent can run the tool without a human in the loop.

---

## 7. Current tool surface (Phase 2)

8 tools, all `SAFE_READ`, all require `switch_ip`.

### Interfaces

| Tool | Inputs | Payload summary |
|---|---|---|
| `get_interfaces` | `switch_ip`, optional `name` | `summary{count, oper_up}` + `interfaces[]` with admin/oper/mtu/speed/counters |
| `get_ip_interfaces` | `switch_ip` | `summary{count, ipv4_count, ipv6_count}` + `ip_interfaces[]` with `{interface, subif, family, address, admin_status, oper_status}` |

### Routing

| Tool | Inputs | Payload summary |
|---|---|---|
| `get_routes` | `switch_ip`, optional `vrf` | `summary{prefix_count, entry_count, by_protocol}` + `routes[]` with `{prefix, protocol, selected, installed, distance, metric, uptime, vrf, nexthops[]}` |
| `get_ipv6_routes` | `switch_ip`, optional `vrf` | Same shape as `get_routes`, IPv6 prefixes |
| `get_bgp_summary` | `switch_ip`, optional `vrf`, `include_ipv6` | `summary{totals{ipv4_peers, ipv4_established, ipv6_peers, ipv6_established}}` + `ipv4{router_id, as, peer_count, established_count, peers[]}` + `ipv6{…same…}` |

### LLDP

| Tool | Inputs | Payload summary |
|---|---|---|
| `get_lldp_neighbors` | `switch_ip` | `summary{neighbor_count, stats_totals{tx,rx}, neighbor_source, notes[]}` + `neighbors[]` + `local_advertisement{}` + `per_interface_stats[]`. **UX note:** if `stats_totals.rx == 0`, show the first `notes[]` entry prominently — it explains the VS limitation. |

### System

| Tool | Inputs | Payload summary |
|---|---|---|
| `get_system_info` | `switch_ip` | `summary{switch_ip, source}` + `system{sonic_software_version, platform, hwsku, asic, kernel, build_date, uptime, …}` |
| `run_show_command` | `switch_ip`, `command`, optional `timeout_seconds` | `summary{command, exit_status, duration_ms, truncated, stdout_bytes, stderr_bytes}` + `stdout` + `stderr`. **UX note:** `command` is strictly validated (must start with `show `, no shell metacharacters, no quotes, ≤256 chars) — 422 on violation. Render `stdout` as monospaced text. |

### Transport hint

The `meta.transport` field in the response tells the client which backend answered:
- `"restconf"` — structured, stable
- `"ssh"` — CLI-backed; may be subject to SONiC version quirks
- `"restconf+ssh"` — combined (currently only `get_lldp_neighbors`)

UI can show this as a small technical badge.

---

## 8. Health, readiness, metrics

### `GET /health`
```json
{ "status": "ok", "service": "sonic-mcp", "timestamp": "...", "version": "1.0" }
```
Always 200 when the process is alive. **Don't** use this as a "switch is reachable" signal.

### `GET /ready`
```json
{
  "status": "ready",
  "checks": {
    "registry": true,
    "devices": {
      "10.46.11.50": { "restconf": true, "ssh": true },
      "10.46.11.51": { "restconf": true, "ssh": true }
    }
  }
}
```
Returns 200 when registry is loaded AND at least one device responds on at least one transport. 503 otherwise with `errors[]`.

**Use this** for a client-side "lab status" widget. A device with `restconf=false, ssh=true` means RESTCONF tools against that device will fail but SSH tools will work.

### `GET /metrics`
Prometheus text format. Key metrics:
- `mcp_invoke_total{tool="..."}`
- `mcp_invoke_success_total{tool="..."}`
- `mcp_invoke_failure_total{tool="..."}`
- `mcp_invoke_latency_seconds{tool="..."}` (histogram)
- `mcp_invoke_status_total{tool="...", status="200|404|exception|..."}`

---

## 9. Session + context — worked example

```
# Call 1: no session yet
POST /invoke
Content-Type: application/json

{"tool": "get_system_info", "inputs": {"switch_ip": "10.46.11.50"}}

→ 200, {"session_id": "abc-123", "result": {...}}
    # server stored context = {switch_ip: "10.46.11.50"} in session abc-123

# Call 2: reuse session; context implicit
POST /invoke
X-MCP-Session: abc-123
Content-Type: application/json

{"tool": "get_interfaces", "inputs": {"switch_ip": "10.46.11.50"}}

→ 200, ...
    # input switch_ip still required by schema, but if it matches session context, no surprise.
    # If client wanted to address a different switch on this session, they pass the new IP; session context updates.
```

Recommended client behavior:
- Store the session ID in local state (browser session storage, in-memory, etc.)
- Always send it on subsequent calls
- Let the user "switch target" by explicitly passing a new `switch_ip` — client updates its own state to reflect the new target

---

## 10. What the client SHOULD and SHOULDN'T do

### Should

- Discover tools at startup via `GET /tools` — don't hardcode.
- Render each tool's input form from its `input_schema` (JSON Schema).
- Respect `policy.requires_confirmation` with a modal.
- Show `meta.transport` and `meta.duration_ms` subtly — helpful for ops.
- Display `result.explain` on demand ("why did this happen?") — don't show by default.
- Surface `result.payload.summary` prominently — it's designed as the "headline" for every tool.
- Handle 429 with exponential back-off + user feedback.

### Shouldn't

- Don't assume payload shapes beyond the `summary` invariant — specific fields may evolve. For stable fields, the catalog spec is the source of truth.
- Don't bypass the envelope (e.g., fetching the switch directly over SSH/RESTCONF from the browser) — defeats the point of the MCP server.
- Don't cache tool results by default — operators need fresh data. Caching belongs in dedicated "overview" views, not the invoke path.
- Don't hardcode tool names, inputs, or categories — the catalog is the contract.

---

## 11. Enterprise features NOT present in community grade

The XCO MCP demo client was built against an enterprise server. For this community server:

- **No auth** on `/invoke` — don't render login UI, API-key UI, OAuth flows
- **No multi-tenancy** — no tenant picker, no "switch tenant" dropdown
- **No RBAC** — no role/permission badges (all users see all tools)
- **No license gates** — no "feature unavailable in this tier" modals
- **No planner/workflow surface** — the runtime has scaffolding but no tools use it yet
- **No mutation ledger UI** — all tools are read-only in Phase 1/2, so there's nothing to display
- **No fabric/tenant/device context resolution** — context is just `switch_ip`

Keep the UI shell, tool catalog pane, invoke flow, response rendering, session handling. Strip the above.

---

## 12. Versioning & evolution

- The **protocol** (envelope, session, error shapes, endpoint URLs) is stable for Phase 1–3.
- The **tool surface** grows additively. New tools appear in `/tools`. Existing tool names and their documented fields will not be removed without a deprecation pass.
- New policy tiers will appear in `policy.risk` in Phase 3 (`MUTATION`, `DESTRUCTIVE`). Clients should treat unknown risk tiers as "surface prominently as not-safe".
- If/when we break the envelope, the server will expose `/v2/invoke` rather than breaking `/invoke`.

---

## 13. Quick sanity test for the client

Point the client at a running server and confirm it can:

1. `GET /health` → 200
2. `GET /tools` → array of ≥8 entries
3. `POST /invoke {tool: "get_system_info", inputs: {switch_ip: "10.46.11.50"}}` → 200 with `result.payload.system.sonic_software_version` populated
4. `POST /invoke {tool: "get_routes", inputs: {switch_ip: "10.46.11.50"}}` → 200 with `result.payload.routes` as a non-empty array
5. `POST /invoke {tool: "run_show_command", inputs: {switch_ip: "10.46.11.50", command: "rm -rf /"}}` → 422 with a clear `detail`

The server ships a reference smoke test at `smoke-test/smoke_phase1.py` that exercises all 8 tools against both lab VMs; treat it as the canonical example of how to call `/invoke`.
