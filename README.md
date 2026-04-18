# SONiC MCP Community Server

A **Model Context Protocol (MCP)** server for **SONiC** switches. Exposes
a tool catalog and invocation API that any AI agent — or plain HTTP
client — can use to inspect and safely change a SONiC fabric.

- **53 tools** across reads, mutations, and fabric-level diagnostics
- **Three transports** — RESTCONF, SSH, and `vtysh` (FRR) — each handler
  declares what it uses
- **Policy tiers** — `SAFE_READ` / `MUTATION` / `DESTRUCTIVE`, gated
  by a server-side kill switch, a per-tool confirmation flag, and an
  auto-mode allow-list
- **Mutation ledger** — every write is recorded as JSONL with pre/post
  state; `rollback_mutation` replays it in reverse
- **Plugin-style tool discovery** — drop a Python file under
  `sonic/tools/<category>/` and the registry picks it up on boot
- **Companion web client** with a fabric view, AI console, and live
  intent editor —
  [sonic-mcp-community-client](https://github.com/YuryOstrovsky/sonic-mcp-community-client)

### Links

- **GitHub (this repo):** https://github.com/YuryOstrovsky/sonic-mcp-community-server
- **GitHub (client):** https://github.com/YuryOstrovsky/sonic-mcp-community-client
- **Docker Hub (server):** [`extremecanada/sonic-mcp-community-server`](https://hub.docker.com/r/extremecanada/sonic-mcp-community-server)
- **Docker Hub (client):** [`extremecanada/sonic-mcp-community-client`](https://hub.docker.com/r/extremecanada/sonic-mcp-community-client)

---

## Architecture

```
┌──────────────────────┐   HTTP   ┌─────────────────────────────┐
│ AI agent / web UI /  │  ──────> │ SONiC MCP server (FastAPI)  │
│ curl / Prometheus    │  <────── │  /tools  /invoke            │
└──────────────────────┘          │  /ready  /health  /metrics  │
                                  │  /fabric/intent             │
                                  └──────────────┬──────────────┘
                                                 │ three transports
                 ┌───────────────────────────────┼───────────────────────────────┐
                 │                               │                               │
                 ▼                               ▼                               ▼
        RESTCONF /restconf/…           SSH (paramiko)                 vtysh show … json
        (openconfig YANG)         show X / sonic-db-cli / config     (FRR native JSON)
                 │                               │                               │
                 └───────────────────────────────┼───────────────────────────────┘
                                                 │
                                                 ▼
                                        ┌────────────────┐
                                        │ SONiC switches │
                                        │ (inventory/IPs)│
                                        └────────────────┘
```

Every tool handler receives a `SonicTransport` object with `.restconf`,
`.ssh`, and `.inventory`. Which one a tool uses is declared in the catalog
so the UI can render it (you'll see `transport: ssh` next to a result).

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
curl http://localhost:8000/tools | jq 'length'   # → 53
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
| `SONIC_HOST_<IP with dots as underscores>_USERNAME` / `_PASSWORD` | — | Per-host credential overrides |
| `MCP_MUTATIONS_ENABLED` | `1` | Server-wide kill switch — set `0` to refuse every MUTATION/DESTRUCTIVE tool |
| `SONIC_VERIFY_TLS` | `false` | RESTCONF TLS verify (lab VMs use self-signed) |
| `SONIC_RESTCONF_PORT` | `443` | mgmt-framework port |
| `SONIC_SSH_TIMEOUT_SECONDS` | `20` | paramiko SSH timeout |
| `MCP_LOG_LEVEL` | `INFO` | Standard Python log level |
| `CORS_ORIGINS` | "" | Comma-separated allowed origins, or `*` for any |
| `SONIC_FABRIC_INTENT_PATH` | `config/fabric_intent.json` | Override the intent file location (useful in Docker) |

---

## Inventory

Static Python inventory at `sonic/inventory.py`. Default:

```python
SonicDevice(name="vm1", mgmt_ip="10.46.11.50", tags=("lab", "vm", "sonic-vs")),
SonicDevice(name="vm2", mgmt_ip="10.46.11.51", tags=("lab", "vm", "sonic-vs")),
```

Edit this list to point at your own lab. Anything not in the list can
still be invoked by raw IP — the `resolve()` helper produces an ad-hoc
device on the fly.

---

## API surface

| Endpoint | Purpose |
|---|---|
| `GET /tools` | The full tool catalog — JSON array, 53 entries |
| `POST /invoke` | Run a tool. Body: `{tool, inputs, confirm?}` |
| `GET /ready` | Probes every inventory device on RESTCONF + SSH. 503 if nothing reachable. |
| `GET /health` | Liveness — process is up |
| `GET /metrics` | Prometheus scrape — see below |
| `GET /fabric/intent` / `PUT /fabric/intent` | Read/write the fabric intent JSON used by `validate_fabric_vs_intent` |
| `POST /audit/mutations` | Mutation ledger search (also exposed as the `get_mutation_history` tool) |

---

## Tool catalog (53 tools)

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
· `iperf_between` · `detect_routing_loop`

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

---

## Metrics

`GET /metrics` exposes Prometheus series:

| Metric | Labels | What |
|---|---|---|
| `mcp_invoke_total` | `tool` | Total invocations per tool |
| `mcp_invoke_success_total` / `_failure_total` | `tool` | Outcome split |
| `mcp_invoke_latency_seconds` | `tool` | Histogram (50ms → 10s buckets) |
| `mcp_invoke_status_total` | `tool`, `status` | Count by HTTP status |
| `mcp_tools_total` | — | Registered tool count (53) |
| `mcp_tools_by_risk` | `risk` | Count per risk tier |
| `mcp_inventory_devices_total` | — | Switches in inventory |
| `mcp_ledger_entries_total` | — | Mutation ledger depth |
| `mcp_ledger_failures_24h` | — | Failed mutations in the past 24h |
| `mcp_fabric_bgp_healthy` / `_broken` / `_orphan` | — | From the last `get_fabric_health` probe (cached 30s) |
| `mcp_fabric_unreachable_switches` | — | Switches that didn't answer the last probe |

Fabric-health gauges refresh lazily — at most once per 30s — so a
Prometheus scrape doesn't fanout SSH on every poll.

---

## Adding a tool

See [`CONTRIBUTING.md`](./CONTRIBUTING.md) for the full walkthrough. In short:

1. Write `sonic/tools/<category>/<tool_name>.py` exporting
   `def <tool_name>(*, inputs, registry, transport, context)`
2. Append the catalog entry to `generated/mcp_tools.json`
3. `pytest` — `tests/test_catalog.py` enforces handler↔catalog parity

The registry auto-discovers the file at boot — no third edit required.

---

## Development

```bash
pip install -r requirements-dev.txt
ruff check sonic/ mcp_runtime/ api/ tests/
pytest                         # unit tests, no switches required
python api/run.py              # local server
```

CI (GitHub Actions) runs pytest on Python 3.11 + 3.12 plus a Docker
image build & boot smoke on every PR.

---

## License

Apache-2.0. See [`LICENSE`](./LICENSE) when present.
