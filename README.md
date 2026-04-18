# SONiC MCP Community Server

A lightweight **FastAPI** server that exposes a safe, read-only **Model Context Protocol (MCP)** tool API for **SONiC** switches.

It lets an AI agent (or any HTTP client) discover a machine-readable tool catalog via `GET /tools` and invoke tools via `POST /invoke`, with consistent response envelopes, structured logging, Prometheus metrics, and session support.

> **Status:** Phase 2 shipped. RESTCONF + SSH transports, **8 read-only tools** (`SAFE_READ` policy only):
> `get_interfaces`, `get_ip_interfaces`, `get_routes`, `get_ipv6_routes`, `get_bgp_summary`, `get_lldp_neighbors`, `get_system_info`, `run_show_command`.

See `PLAN.md` for the full phased roadmap.

---

## Architecture

**Two transports, one registry.** Each tool declares which transport it uses. The `SonicTransport` object handed to every handler exposes both:

- **`transport.restconf`** — HTTPS to the mgmt-framework on `:443`, basic auth, OpenConfig YANG. Stable, structured data.
- **`transport.ssh`** — paramiko SSH on `:22`, password auth. Used where RESTCONF doesn't implement a data model (e.g., the routing table — FRR's `vtysh -c "show ip route json"` returns native JSON).

Why both? On community SONiC master the RESTCONF surface is limited to a handful of OpenConfig modules (`openconfig-interfaces`, `openconfig-platform`, `openconfig-lldp`, …). System identity (`openconfig-system`) and routing aren't implemented, so SSH/CLI covers the gaps. See `PLAN.md` for the capability probe that motivated this.

---

## Tools (Phase 1 + Phase 2)

| Tool | Transport | Source |
|---|---|---|
| `get_interfaces` | RESTCONF | `GET /restconf/data/openconfig-interfaces:interfaces` |
| `get_ip_interfaces` | RESTCONF | Same path, filtered to subinterfaces with IPs |
| `get_routes` | SSH | `vtysh -c "show ip route [vrf X] json"` (FRR native JSON) |
| `get_ipv6_routes` | SSH | `vtysh -c "show ipv6 route [vrf X] json"` |
| `get_bgp_summary` | SSH | `vtysh -c "show ip bgp summary json"` + `show bgp ipv6 summary json` |
| `get_lldp_neighbors` | RESTCONF + SSH | `openconfig-lldp:lldp/interfaces` primary, `lldpcli -f json` for fallback + TX/RX stats + local advertisement. Reports explicit note when SONiC VS shows TX>0, RX=0. |
| `get_system_info` | SSH | `show version` (parsed) |
| `run_show_command` | SSH | Safe escape hatch — regex-validated `show …` commands only, 256-char cap, no shell metacharacters |

All tools require `switch_ip`. Full input schemas live in `generated/mcp_tools.json` and are exposed via `GET /tools`.

---

## Quick start

```bash
# 1) Clone, then from the repo root:
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt

# 2) Create .env
cp .env.example .env
# edit credentials / tunables for your lab

# 3) Run (dev / foreground)
python api/run.py
# listens on http://0.0.0.0:8000
```

### Run as a systemd service (recommended for real use)

```bash
sudo cp systemd/sonic-mcp.service /etc/systemd/system/sonic-mcp.service
sudo systemctl daemon-reload
sudo systemctl enable --now sonic-mcp
systemctl status sonic-mcp --no-pager
journalctl -u sonic-mcp -f
```

See `systemd/README.md` for full install / uninstall / operations steps.

---

## Use it

### List tools

```bash
curl -sS http://127.0.0.1:8000/tools | jq
```

### Invoke a tool

```bash
curl -sS -X POST http://127.0.0.1:8000/invoke \
  -H "Content-Type: application/json" \
  -d '{"tool":"get_system_info","inputs":{"switch_ip":"10.46.11.50"}}' | jq

curl -sS -X POST http://127.0.0.1:8000/invoke \
  -H "Content-Type: application/json" \
  -d '{"tool":"get_interfaces","inputs":{"switch_ip":"10.46.11.50","name":"Ethernet0"}}' | jq

curl -sS -X POST http://127.0.0.1:8000/invoke \
  -H "Content-Type: application/json" \
  -d '{"tool":"get_bgp_summary","inputs":{"switch_ip":"10.46.11.50"}}' | jq

curl -sS -X POST http://127.0.0.1:8000/invoke \
  -H "Content-Type: application/json" \
  -d '{"tool":"get_lldp_neighbors","inputs":{"switch_ip":"10.46.11.50"}}' | jq

curl -sS -X POST http://127.0.0.1:8000/invoke \
  -H "Content-Type: application/json" \
  -d '{"tool":"run_show_command","inputs":{"switch_ip":"10.46.11.50","command":"show platform summary"}}' | jq
```

### Health and readiness

```bash
curl -sS http://127.0.0.1:8000/health | jq
curl -sS http://127.0.0.1:8000/ready  | jq   # probes RESTCONF + SSH on every inventory device
curl -sS http://127.0.0.1:8000/metrics       # Prometheus text format
```

---

## Repository layout

```
api/                 FastAPI app (invoke / tools / health / ready / metrics / docs)
mcp_runtime/         Core runtime: registry, policy, session, metrics, logging, invoke envelope
sonic/               SONiC-specific code
  credentials.py     Env-driven credential resolver (per-host overrides)
  inventory.py       Static device list (VM1, VM2)
  transport_restconf.py  RESTCONF transport
  transport_ssh.py       SSH transport (paramiko)
  transport.py       Unified SonicTransport(restconf, ssh)
  tools/             Tier-2 handlers, one per tool
generated/           Tool catalog (mcp_tools.json)
systemd/             Systemd service unit + install README
sonic_initial_docs/  Lab specs and guides from the user
smoke-test/          End-to-end smoke tests against live devices
PLAN.md              Phased build plan and design decisions
```

---

## Adding a new tool

1. Create a handler under `sonic/tools/<category>/<tool_name>.py` with the signature:
   ```python
   def my_tool(*, inputs, registry, transport, context) -> dict:
       ...
   ```
2. Add an entry in `generated/mcp_tools.json` with the tool's input schema, `transport` field, and `policy` (keep `SAFE_READ` unless you're intentionally building a mutation).
3. Register the handler in `mcp_runtime/registry.py`.
4. Restart the server; hit `POST /invoke` to test.

---

## Security notes

- Only `SAFE_READ` tools today. Policy is enforced in `mcp_runtime/policy.py` before any transport call.
- Passwords live in `.env` (not committed). The request logger redacts sensitive-looking params before emitting.
- The server is intended for lab / trusted-network use. For internet-facing deployment, put it behind a reverse proxy, restrict CORS, and bump the rate limit / body-size caps as appropriate.

---

## Smoke tests

```bash
source .venv/bin/activate
python smoke-test/smoke_phase1.py   # end-to-end against VM1 + VM2
```

---

## Roadmap

See `PLAN.md`. Short version:

- **Phase 1 (done):** walking skeleton — transports, 4 starter tools, full invoke envelope.
- **Phase 2 (done):** LLDP, BGP summary, IPv6 routes, `run_show_command` escape hatch, systemd service.
- **Phase 3:** multi-device variants (query all inventory in parallel), gNMI transport (`pygnmi`) for streaming telemetry, topology, config mutations via RESTCONF PATCH.
- **Out of scope for now:** RoCE/RDMA (see `sonic_initial_docs/FUTURE_HARDWARE.md`).
