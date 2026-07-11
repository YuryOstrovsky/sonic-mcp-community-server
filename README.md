# SONiC MCP Community Server

A **Model Context Protocol (MCP)** server for **SONiC** switches. The same
55-tool catalog is exposed over **standard MCP** (stdio + Streamable HTTP)
*and* a custom REST API — so an off-the-shelf MCP client (Claude Desktop,
agents) and the companion web client both drive the same tools to inspect
and safely change a SONiC fabric.

- **Standard MCP transport** — point any MCP client at `/mcp` (Streamable
  HTTP) or `python -m mcp_runtime.mcp_stdio` (Claude Desktop) for
  plug-and-play tool discovery. See [Protocol compatibility](#protocol-compatibility).
- **55 tools** across reads, mutations, and fabric-level diagnostics
- **Three device transports** — RESTCONF, SSH, and `vtysh` (FRR) — each
  handler declares what it uses
- **Policy tiers** — `SAFE_READ` / `MUTATION` / `DESTRUCTIVE`, gated
  by a server-side kill switch, a per-tool confirmation flag, and an
  auto-mode allow-list
- **Mutation ledger** — every write is recorded as JSONL with pre/post
  state; `rollback_mutation` replays it in reverse
- **Plugin-style tool discovery** — drop a Python file under
  `sonic/tools/<category>/` and the registry picks it up on boot
- **File-backed inventory** with hot-reload, REST API, per-device
  credential overrides, and LLDP seed-walk discovery
- **Companion web client** with a fabric view, AI console, and live
  intent editor —
  [sonic-mcp-community-client](https://github.com/YuryOstrovsky/sonic-mcp-community-client)

### Links

- **GitHub (this repo):** https://github.com/YuryOstrovsky/sonic-mcp-community-server
- **GitHub (client):** https://github.com/YuryOstrovsky/sonic-mcp-community-client
- **Docker Hub (server):** [`extremecanada/sonic-mcp-community-server`](https://hub.docker.com/r/extremecanada/sonic-mcp-community-server)
- **Docker Hub (client):** [`extremecanada/sonic-mcp-community-client`](https://hub.docker.com/r/extremecanada/sonic-mcp-community-client)
- **GHCR (server):** `ghcr.io/yuryostrovsky/sonic-mcp-community-server`

> Each tagged release publishes **identical immutable tags** (`0.1.0`,
> `0.1`, `latest`, …) to both Docker Hub and GHCR, so whichever you pull,
> a given version is the same image tied to that GitHub release.

---

## Architecture

```
  MCP clients                     Web client / curl / Prometheus
  (Claude Desktop, agents)        (companion UI, HTTP callers)
        │  standard MCP                    │  custom REST
        │  stdio | Streamable HTTP         │
        ▼                                  ▼
┌───────────────────────────────────────────────────────────────┐
│ SONiC MCP server (FastAPI)                                     │
│   /mcp  (standard MCP)      /tools  /invoke  (REST)            │
│   /ready  /health  /metrics  /fabric/intent  /inventory       │
│   ── one shared 55-tool registry · policy · ledger · metrics ─│
└──────────────────────────────┬────────────────────────────────┘
                               │ three device transports
         ┌─────────────────────┼─────────────────────┐
         ▼                     ▼                     ▼
   RESTCONF /restconf/…   SSH (paramiko)      vtysh show … json
   (openconfig YANG)   show X / sonic-db-cli   (FRR native JSON)
         │                     │                     │
         └─────────────────────┼─────────────────────┘
                               ▼
                       ┌────────────────┐
                       │ SONiC switches │
                       │ (inventory/IPs)│
                       └────────────────┘
```

Both the MCP transport and the REST API drive **one shared registry**, so
policy (kill switch, confirmation), the mutation ledger, metrics, and auth
behave identically no matter how a tool is called.

Every tool handler receives a `SonicTransport` object with `.restconf`,
`.ssh`, and `.inventory`. Which one a tool uses is declared in the catalog
so the UI can render it (you'll see `transport: ssh` next to a result).

### Protocol compatibility

The server speaks the **standards-compliant Model Context Protocol** *and*
the custom REST API — the same 55-tool registry, exposed two ways:

| Surface | Endpoint / entrypoint | Who uses it |
|---|---|---|
| **MCP — Streamable HTTP** | `http(s)://<host>:8000/mcp` | Any remote MCP client / agent (claude.ai connectors, SDKs) |
| **MCP — stdio** | `python -m mcp_runtime.mcp_stdio` | Local MCP clients that launch a subprocess (Claude Desktop) |
| **Custom REST** | `GET /tools`, `POST /invoke` | The companion web client and plain HTTP callers |

Point an off-the-shelf MCP client (Claude Desktop, Codex, an agent SDK) at
the server and it gets **plug-and-play tool discovery** — all 55 tools with
their JSON-Schema inputs, risk annotations (`readOnlyHint` /
`destructiveHint`), and a `confirm` flag on mutating tools. Policy is
identical across surfaces: the `MCP_MUTATIONS_ENABLED` kill switch, the
mutation ledger, metrics, and `MCP_API_KEY` auth all apply to MCP calls too.

**Connect a remote MCP client (Streamable HTTP):**
point it at `http://<host>:8000/mcp`. When `MCP_API_KEY` is set, send
`Authorization: Bearer <key>`.

**Connect Claude Desktop (stdio)** — `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "sonic": {
      "command": "python",
      "args": ["-m", "mcp_runtime.mcp_stdio"],
      "cwd": "/absolute/path/to/sonic-mcp-community-server",
      "env": { "SONIC_DEFAULT_USERNAME": "admin", "SONIC_DEFAULT_PASSWORD": "YourPaSsWoRd" }
    }
  }
}
```

The `/tools` + `/invoke` REST API remains for the web client and simple
HTTP callers — nothing about it changed.

---

## Security and intended use

> ⚠️ **This server can change the configuration of network
> infrastructure.** Read this before you run it.

- **Designed for labs and trusted management networks.** It is **not**
  intended to be Internet-facing. **Do not publish port 8000 to the public
  Internet** — run it only on a trusted management network or behind an
  authenticated reverse proxy.
- **Authentication is optional but strongly recommended.** Set
  `MCP_API_KEY` to a long random secret (`openssl rand -hex 32`) to require
  `Authorization: Bearer <key>` on `/invoke` and every write endpoint. When
  it is unset, auth is **disabled** and the server logs a startup warning —
  any caller who can reach the port can change switch config. (`confirm:
  true` is not authentication; anyone can send it.)
- **Mutations are disabled by default** (`MCP_MUTATIONS_ENABLED=0`, in the
  image too). Enable writes explicitly when you need them.
- **Use least-privilege switch accounts.** Give the server only the access
  it needs on each device.
- **Protect `.env`, `config/inventory.json`, `logs/`, and `snapshots/`** —
  they hold credentials and change history. They are git-ignored; keep them
  that way and `chmod 600 .env`.
- **Test mutations in a lab before production.** Destructive tools can
  cause outages, and **rollback is best-effort, not a transaction
  guarantee** (see [Rollback limitations](#rollback-limitations)).

See [`SECURITY.md`](./SECURITY.md) for the full policy and how to report a
vulnerability privately.

---

## Quickstart

### Docker (fastest)

**Pull the published image** from Docker Hub:

```bash
docker pull extremecanada/sonic-mcp-community-server:latest
```

Or build from source:

```bash
git clone https://github.com/YuryOstrovsky/sonic-mcp-community-server
cd sonic-mcp-community-server
cp .env.example .env        # fill in SONIC_DEFAULT_USERNAME / PASSWORD
docker compose up -d --build
curl http://localhost:8000/tools | jq 'length'   # → 55
```

The shipped `docker-compose.yml` references
`extremecanada/sonic-mcp-community-server:latest` by default, so
`docker compose up -d` pulls from Docker Hub if no local image is built.

See [`README.docker.md`](./README.docker.md) for the full Docker walkthrough,
including bind-mounting `./config` (intent files) and `./snapshots` from
the host.

### systemd (bare-metal)

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env && $EDITOR .env
# Install and start the unit
sudo cp systemd/sonic-mcp.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now sonic-mcp.service
```

### Manual

```bash
source .venv/bin/activate
python api/run.py    # serves on :8000 by default
```

---

## Configuration

All settings are `.env` / environment variables. The most useful ones:

| Variable | Default | Purpose |
|---|---|---|
| `SONIC_DEFAULT_USERNAME` / `SONIC_DEFAULT_PASSWORD` | — | Credentials applied to all devices unless overridden per-host |
| `SONIC_HOST_<IP with dots as underscores>_USERNAME` / `_PASSWORD` | — | Per-host credential overrides via env |
| `SONIC_INVENTORY_PATH` | `config/inventory.json` | File-backed inventory (see Inventory below) |
| `MCP_API_KEY` | — (unset) | When set, `/invoke` + write endpoints require `Authorization: Bearer <key>`. Unset = auth disabled (logs a warning). |
| `MCP_MUTATIONS_ENABLED` | `0` | Server-wide kill switch — `0` refuses every MUTATION/DESTRUCTIVE tool (safe default); set `1` to allow writes |
| `SONIC_VERIFY_TLS` | `false` | RESTCONF TLS verify (lab VMs use self-signed) |
| `SONIC_RESTCONF_PORT` | `443` | mgmt-framework port |
| `SONIC_SSH_TIMEOUT_SECONDS` | `20` | paramiko SSH timeout |
| `MCP_LOG_LEVEL` | `INFO` | Standard Python log level |
| `CORS_ORIGINS` | "" | Comma-separated allowed origins, or `*` for any |
| `SONIC_FABRIC_INTENT_PATH` | `config/fabric_intent.json` | Override the intent file location (useful in Docker) |

---

## Inventory

Inventory is loaded from a JSON file at `$SONIC_INVENTORY_PATH` (default
`config/inventory.json`). The server watches the file's mtime and
hot-reloads on change — no restart needed.

```json
{
  "switches": [
    {
      "name": "vm1",
      "mgmt_ip": "10.46.11.50",
      "tags": ["lab", "vm", "sonic-vs"]
    },
    {
      "name": "spine1",
      "mgmt_ip": "10.0.0.1",
      "tags": ["spine"],
      "username": "admin",
      "password_env": "SONIC_SPINE1_PASSWORD"
    }
  ]
}
```

If the file is missing, malformed, or transiently empty, the server
keeps its last good list (or falls back to a built-in `vm1`/`vm2`
starter). A starter template ships at `config/inventory.example.json`.

**Per-device credentials** — a switch entry can carry credentials that
take precedence over env vars. Precedence chain (highest first):

1. Inventory JSON entry — `password` (inline) **or** `password_env` (name
   of an env var holding the secret; `password` wins if both are set)
2. `SONIC_HOST_<IP_with_underscores>_USERNAME` / `_PASSWORD`
3. `SONIC_DEFAULT_USERNAME` / `SONIC_DEFAULT_PASSWORD`

> 🔐 **Credential hygiene.** An inline `"password"` is convenient for a
> throwaway lab but writes a **plaintext secret into
> `config/inventory.json`**, which is not appropriate for production.
> Prefer `"password_env": "SONIC_SPINE1_PASSWORD"` (or the `SONIC_HOST_*`
> env vars) so the secret lives in the environment / a secret-mounted file
> instead. Keep `config/inventory.json` out of Git (it is git-ignored by
> default) and off screenshots, logs, and issue reports.

**REST API** (see below) lets the companion client or curl add / remove
/ probe switches without ever touching the JSON by hand. Anything not
in the inventory can still be invoked by raw IP — the `resolve()` helper
produces an ad-hoc device on the fly.

**Discovery** — the `discover_fabric_from_seed` tool walks LLDP
neighbors from a seed switch (up to `max_hops`, default 2) and proposes
new additions, each optionally probed on RESTCONF + SSH before the user
approves. The client's **Settings → Fabric Inventory** view wraps the
add / remove / probe / discover flows.

> **Caveat:** LLDP RX on SONiC VS is often empty (documented upstream),
> so seed-walk discovery legitimately finds nothing in the default
> 2-VM lab. Real hardware is where this shines.

---

## API surface

When `MCP_API_KEY` is set, endpoints marked 🔒 require an
`Authorization: Bearer <key>` header; the rest stay open.

| Endpoint | Auth | Purpose |
|---|---|---|
| `ANY /mcp` | 🔒 | **Standard MCP** (Streamable HTTP). Point any MCP client here — see [Protocol compatibility](#protocol-compatibility). |
| `GET /tools` | — | The full tool catalog — JSON array, 55 entries |
| `POST /invoke` | 🔒 | Run a tool. Body: `{tool, inputs, confirm?}`. The `get_mutation_history` tool exposes the mutation-ledger search here. |
| `GET /ready` | — | Probes every inventory device on RESTCONF + SSH. 503 if nothing reachable. |
| `GET /health` | — | Liveness — process is up |
| `GET /metrics` | — | Prometheus scrape — see below |
| `GET /fabric/intent` | — | Read the fabric intent JSON used by `validate_fabric_vs_intent` |
| `PUT /fabric/intent` | 🔒 | Write the fabric intent JSON |
| `GET /inventory` | — | Current inventory as JSON — `{path, source, switches}`. Passwords redacted (only `has_password: bool` is exposed). |
| `PUT /inventory` | 🔒 | Replace the full inventory. Body: `{switches: [...]}`. |
| `POST /inventory/switches` | 🔒 | Add-or-update a single switch by `mgmt_ip`. |
| `DELETE /inventory/switches/{mgmt_ip}` | 🔒 | Remove a switch. |
| `POST /inventory/probe` | 🔒 | Transient RESTCONF + SSH probe with supplied creds (does not persist). |

With `MCP_API_KEY` set, pass the key on protected calls:

```bash
export MCP_API_KEY=$(openssl rand -hex 32)   # then start the server with it set

curl -s http://localhost:8000/tools                 # open, no key needed
curl -s -X POST http://localhost:8000/invoke \
     -H "Authorization: Bearer $MCP_API_KEY" \
     -H "Content-Type: application/json" \
     -d '{"tool": "get_system_info", "inputs": {"switch": "10.46.11.50"}}'
```

Without the header, protected endpoints return `401`. Without `MCP_API_KEY`
set at all, auth is disabled (and the server logs a warning on startup).

---

## Tool catalog (55 tools)

Grouped by category. Every tool's full spec — input schema, policy,
transport — is served as JSON at `GET /tools`.

### Reads — system + platform

`get_system_info` · `get_platform_detail` · `get_system_info_all`

### Reads — interfaces + L3

`get_interfaces` · `get_ip_interfaces` · `get_interfaces_all`

### Reads — routing + BGP

`get_routes` · `get_ipv6_routes` · `get_bgp_summary` · `get_routes_all`
· `get_bgp_summary_all` · `get_routes_by_prefix`

### Reads — L2

`get_vlans` · `get_vlans_all` · `get_arp_table` · `get_arp_table_all`
· `get_mac_table` · `get_mac_table_all` · `get_portchannels`

### Reads — LLDP + sFlow

`get_lldp_neighbors` · `get_lldp_neighbors_all` · `get_sflow_status`

### Fabric reads + diagnostics

`get_fabric_topology` · `get_fabric_health` · `get_fabric_reachability_matrix`
· `get_fabric_mtu_consistency` · `get_fabric_bandwidth` · `get_fabric_config_diff`
· `validate_fabric_vs_intent` · `ping_between` · `traceroute_between`
· `iperf_between` · `detect_routing_loop` · `discover_fabric_from_seed`

### Mutations — interfaces

`set_interface_admin_status` · `set_interface_mtu` · `set_interface_description`
· `set_ip_interface` · `clear_interface_counters`

### Mutations — L2 + routing

`add_vlan` · `remove_vlan` · `set_portchannel_member`
· `add_static_route` · `remove_static_route` · `set_bgp_neighbor_admin`

### Mutations — fabric lifecycle

`drain_switch` · `undrain_switch` · `fabric_drain_rotate`
· `save_fabric_snapshot` · `restore_fabric_snapshot` *(DESTRUCTIVE)*

### System

`config_save` · `run_show_command` · `rollback_mutation`
· `get_mutation_history`

---

## Policy tiers

Every mutation is gated by three layers:

1. **`MCP_MUTATIONS_ENABLED` kill switch** — env-var, whole server. Off → every
   MUTATION/DESTRUCTIVE tool returns 403.
2. **`requires_confirmation` per-tool flag** — client must send `confirm: true`
   in the `/invoke` body. Used by the web client's confirmation modal.
3. **`allowed_in_auto_mode`** — for agentic callers, gates which tools are
   safe without a human in the loop.

A mutation that passes all three lands an entry in the ledger
(`logs/mutations.jsonl`) with timestamp, pre/post state, request/session
IDs, and the caller's inputs (credentials redacted).

`rollback_mutation` reads ledger entries by ID and invokes the inverse
tool with restored inputs. Works for admin-status / MTU / description /
IP assignment / VLAN / port-channel / static route / BGP neighbor /
drain/undrain. Refuses `config_save` and `clear_interface_counters`
(not reversible).

### Rollback limitations

> ⚠️ **Rollback is best-effort, not a transactional or guaranteed undo.**

Replaying a mutation in reverse re-applies the recorded pre-state; it does
**not** take a lock, snapshot the whole device, or verify the surrounding
config is unchanged. A rollback can fail or produce an unexpected result
when:

- the switch has become unreachable;
- external configuration changes happened after the original mutation;
- interface or routing state has since changed;
- a partial multi-switch change has already been applied elsewhere;
- the original pre-state capture was incomplete;
- the inverse operation is not idempotent.

Treat rollback as a convenience for a well-understood lab change, not as a
safety net for production. For point-in-time recovery of a whole device,
use `save_fabric_snapshot` / `restore_fabric_snapshot` and always test in a
lab first.

---

## Metrics

`GET /metrics` exposes Prometheus series:

| Metric | Labels | What |
|---|---|---|
| `mcp_invoke_total` | `tool` | Total invocations per tool |
| `mcp_invoke_success_total` / `_failure_total` | `tool` | Outcome split |
| `mcp_invoke_latency_seconds` | `tool` | Histogram (50ms → 10s buckets) |
| `mcp_invoke_status_total` | `tool`, `status` | Count by HTTP status |
| `mcp_tools_total` | — | Registered tool count (55) |
| `mcp_tools_by_risk` | `risk` | Count per risk tier |
| `mcp_inventory_devices_total` | — | Switches in inventory |
| `mcp_ledger_entries_total` | — | Mutation ledger depth |
| `mcp_ledger_failures_24h` | — | Failed mutations in the past 24h |
| `mcp_fabric_bgp_healthy` / `_broken` / `_orphan` | — | From the last `get_fabric_health` probe (cached 30s) |
| `mcp_fabric_unreachable_switches` | — | Switches that didn't answer the last probe |

Fabric-health gauges refresh lazily — at most once per 30s — so a
Prometheus scrape doesn't fanout SSH on every poll.

---

## Compatibility

SONiC varies substantially by release, vendor image, management-framework
availability, FRR version, and RESTCONF implementation. What works depends
on your image. This matrix reflects where the project has actually been
exercised versus where it is *expected* to work:

| Platform | SONiC | Read tools | Mutation tools | Transports | Status |
|---|---|---|---|---|---|
| **SONiC-VS** (KVM) | recent `master`/community VS builds | ✅ Yes | ⚠️ Partial | SSH, `vtysh` | **Tested** — the default 2-VM lab |
| SONiC-VS RESTCONF (mgmt-framework) | images with `mgmt-framework` enabled | ⚠️ Partial | ⚠️ Partial | RESTCONF | Expected — depends on the YANG/mgmt-framework build |
| Vendor / hardware SONiC | vendor images | ⚠️ Expected | ⚠️ Expected | SSH, `vtysh`, RESTCONF | **Not yet tested** — see [`sonic_initial_docs/FUTURE_HARDWARE.md`](./sonic_initial_docs/FUTURE_HARDWARE.md) |
| Enterprise SONiC (Dell/others) | vendor releases | ❓ Unknown | ❓ Unknown | — | Unsupported / untested |

**Legend:** ✅ tested & working · ⚠️ expected to work / partial · ❓ unknown.

**Known limitations**

- RESTCONF depends on `mgmt-framework` being present and the YANG models
  your image ships — some reads/writes fall back to SSH/`vtysh`.
- LLDP RX on SONiC-VS is often empty (documented upstream), so seed-walk
  discovery finds little in the default VM lab — this shines on real
  hardware.
- Mutation tools are marked ⚠️ Partial on VS because behaviour depends on
  the image's config backend; **always test in a lab first**.

If you run this against hardware or another SONiC flavor, a PR updating
this matrix (tested / expected / unsupported) is very welcome.

---

## Adding a tool

See [`CONTRIBUTING.md`](./CONTRIBUTING.md) for the full walkthrough. In short:

1. Write `sonic/tools/<category>/<tool_name>.py` exporting
   `def <tool_name>(*, inputs, registry, transport, context)`
2. Append the catalog entry to `generated/mcp_tools.json`
3. `pytest` — `tests/test_catalog.py` enforces handler↔catalog parity

The registry auto-discovers the file at boot — no third edit required. A new
tool automatically shows up on **all** surfaces at once: `/tools`, `/invoke`,
and standard MCP (`/mcp` + stdio). Its JSON Schema and policy come straight
from the catalog entry, so MCP clients get correct inputs and risk hints for
free.

---

## Development

```bash
pip install -r requirements-dev.txt
ruff check sonic/ mcp_runtime/ api/ tests/
pytest                         # unit tests, no switches required
python api/run.py              # local server
```

CI (GitHub Actions) runs pytest on Python 3.11 + 3.12, a `pip-audit`
dependency scan, and a Docker image build + Trivy scan + boot smoke on
every PR. Dependabot keeps dependencies, Actions, and the base image fresh.

---

## Community

- [`CONTRIBUTING.md`](./CONTRIBUTING.md) — how to add a tool and open a PR
- [`SECURITY.md`](./SECURITY.md) — security policy and private vulnerability reporting
- [`CODE_OF_CONDUCT.md`](./CODE_OF_CONDUCT.md) — Contributor Covenant
- [`CHANGELOG.md`](./CHANGELOG.md) — release history (Keep a Changelog)

---

## Few Screenshots of the MCP client working with this MCP server 

<img width="1712" height="865" alt="image" src="https://github.com/user-attachments/assets/418053fd-21d6-41ea-8e23-5b1f7df1fe9e" />

<img width="1723" height="878" alt="image" src="https://github.com/user-attachments/assets/92184616-1bb7-4fc2-8418-23074f6cd481" />

<img width="1724" height="875" alt="image" src="https://github.com/user-attachments/assets/9a0da236-8865-47b8-9e12-2f0fa7086eae" />

<img width="1723" height="878" alt="image" src="https://github.com/user-attachments/assets/7a4a7d73-6090-4d63-a0c5-67cf4b66f3fd" />





## License

Apache-2.0. See [`LICENSE`](./LICENSE).
