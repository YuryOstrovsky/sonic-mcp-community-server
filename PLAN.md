# SONiC MCP Community Server — Build Plan

A living document. Update as decisions change, phases ship, or probes reveal new facts.

---

## 1. Goal

Build a **community-grade Model Context Protocol (MCP) server for SONiC** by reusing the already-built MCP runtime scaffolding (FastAPI, registry, policy, session, metrics, logging, Tier-1/Tier-2 pattern) from the prior XCO/RESTCONF project, and stripping out everything XCO/SLX-specific.

The MCP server should let an AI agent (or any HTTP client) invoke well-defined tools against SONiC switches and get structured responses back.

---

## 2. Lab environment

Everything runs on this Ubuntu host.

| Device | Mgmt IP | Notes |
|---|---|---|
| Host | `10.46.11.8` | Runs VMs + MCP server |
| SONiC VM1 | `10.46.11.50` | KVM, SONiC VS |
| SONiC VM2 | `10.46.11.51` | KVM, SONiC VS |

- **Inter-switch link:** VM1 `Ethernet0` (`192.168.1.1`) ↔ VM2 `Ethernet0` (`192.168.1.2`)
- **Credentials:** `admin / password` (basic auth / password SSH)
- **SONiC build:** `SONiC.master.1090303-014aafe09`, OS v13, Debian 13.4, built 2026-04-16 (installed from <https://sonic.software/>)
- **Platform:** `x86_64-kvm_x86_64-r0`, `Force10-S6000` SKU, `ASIC: vs`

---

## 3. Capability probe — what the lab actually exposes

Probed 2026-04-17 against VM1.

| Interface | Status | Notes |
|---|---|---|
| **RESTCONF on :443** | ✅ Working | IETF RESTCONF, `/.well-known/host-meta` → `/restconf`, basic auth, JSON. mgmt-framework container. |
| **OpenConfig YANG models** | ✅ Working | `GET /restconf/data/openconfig-interfaces:interfaces/interface=Ethernet0/state` returned structured counters + admin/oper state. |
| **gNMI on :8080** | ✅ TCP open | gRPC HTTP/2 — not yet exercised. Container running. |
| **SSH on :22** | ✅ Working | Password auth, `admin/password`. |
| **Redis (6379/6400)** | ⚠️ Localhost-only | Requires SSH tunnel; APPL_DB/CONFIG_DB/STATE_DB/COUNTERS_DB accessible that way. |
| **`show ... --json`** | ❌ Not supported | No `--json` flag on this master build. CLI text output only. |
| **OpenConfig `system:system/state`** | ⚠️ 500 | Not every OpenConfig subtree is implemented — expect to map around gaps. |
| **Native `sonic-system:…`** | ⚠️ 404 | Native SONiC YANG namespaces exist but differ per subtree — probe each before committing. |

**Running containers on both VMs:** `snmp`, `pmon`, `mgmt-framework`, `lldp`, `gnmi`, `eventd`, `radv`, `gbsyncd`, `bgp`, `syncd`, `teamd`, `sysmgr`, `swss`, `database`.

---

## 4. Architecture decisions

### Primary transport: RESTCONF + OpenConfig
CLI is unstable on master (no `--json`). mgmt-framework RESTCONF on :443 with OpenConfig YANG gives **structured, version-stable** data out of the box. Existing `restconf/client.py` (used for SLX9150) is ~80% reusable.

### Secondary transport: SSH/CLI (paramiko, sync)
Fallback for things RESTCONF doesn't expose (diagnostic `show` commands, `supportsave`, image operations). Each tool declares which transport it uses.

### Future transport: gNMI (pygnmi)
Phase 3. For streaming telemetry and subscriptions (counters, events).

### Runtime scaffolding — reuse as-is
- FastAPI app: `api/app.py` (CORS, rate limit, body-size, request logging, session header)
- Runtime: `mcp_runtime/server.py` invoke flow, `registry.py` pattern, `policy.py`, `session*.py`, `logging.py`, `metrics.py`, `errors.py`, `trace.py`, `tracing.py`, `mutation_*` scaffolding, `explain*`, `workflow*`, `planner.py`
- Tier-2 handler contract: `handler(inputs, registry, transport, context)` — stays identical

### Context model — simplify
Drop XCO's fabric/tenant/device resolution (`context_resolver/validator/injection`). SONiC context is just `switch_ip` (and later a named device inventory). Session still holds it across calls.

### Quarantine, don't delete
Move all XCO/SLX-specific code into `_legacy/` first. Build SONiC alongside. Delete `_legacy/` once parity is reached. (No git repo here = no safety net otherwise.)

---

## 5. What goes where

### Keep (reuse)
- `api/app.py` (minor edits: `/ready` probe target, service name)
- `api/run.py`, `api/docs_routes.py`
- `mcp_runtime/{server,registry,policy,session,session_store,logging,metrics,errors,trace,tracing,explain*,workflow*,planner,mutation_*,tool_capabilities,intent_*,commit_registry,docs_routes}.py`
- `Dockerfile`, `.dockerignore`, `.gitignore`, `requirements.txt` (add `paramiko` in Phase 2)

### Quarantine to `_legacy/`
- `xco/`
- `restconf/` (but copy `client.py` as a starting reference for the new SONiC RESTCONF transport)
- `tools/{fabric,faultmanager,inventory,monitor,notification,system,tenant,auth}/`
- `tools/{parse_openapi,classify_endpoints,resolve_endpoints,validate_endpoints,probe_read_endpoints,generate_mcp_tools,apply_gateway_rules,validate_context_samples}.py`
- `generated/*` (XCO endpoint/tool JSON)
- `openapi/`
- `smoke-test/`
- `docs/TOOL_CATALOG.md`, `docs/examples.md`
- `XCO_MCP_Server_User_Guide.docx`, `XCO_MCP_Tier2_Operator_Notes.docx`
- `README.docker.md` (replace), `README.md` (replace)
- `mcp_runtime/tier1_tools.py` (XCO-specific allowlist)
- `mcp_runtime/auth.py` (XCO token lifecycle)
- `mcp_runtime/transport.py` (XCO HTTPS transport)
- `mcp_runtime/{context_resolver,context_validator,context_injection,context_merge,context,context_resolver}.py`

### Build new
- `sonic/transport_restconf.py` — RESTCONF client (basic auth, HTTPS, JSON, retries)
- `sonic/transport_ssh.py` — paramiko-based SSH transport (Phase 2)
- `sonic/credentials.py` — env-driven per-host credential resolver
- `sonic/inventory.py` — static device list (VM1/VM2 + future hosts)
- `sonic/tools/interfaces/` — `get_interfaces`, `get_ip_interfaces`
- `sonic/tools/routing/` — `get_routes`
- `sonic/tools/system/` — `get_system_info`
- `generated/mcp_tools.json` — fresh SONiC tool catalog
- `mcp_runtime/registry.py` — rewire to SONiC handlers
- `mcp_runtime/server.py` — swap `XCOTransport` for `SonicTransport`
- `.env.example` — SONiC vars (`SONIC_DEFAULT_USERNAME`, `SONIC_DEFAULT_PASSWORD`, `SONIC_VERIFY_TLS`, `SONIC_TIMEOUT_SECONDS`)

---

## 6. Phased delivery

### Phase 1 — walking skeleton (shipped 2026-04-17)
- [x] Quarantine XCO/SLX code into `_legacy/`
- [x] Strip `mcp_runtime` of XCO-specific context/auth/transport
- [x] Build `sonic/transport_restconf.py` against VM1
- [x] Build `sonic/transport_ssh.py` (paramiko, per-host client pool) — **moved up from Phase 2** because community SONiC master doesn't implement routing or stable system-info YANG, so SSH is needed for `get_routes` and `get_system_info` from day one
- [x] Fresh `generated/mcp_tools.json` with 4 starter tools
- [x] Implement `get_interfaces`, `get_ip_interfaces` via RESTCONF/OpenConfig
- [x] Implement `get_routes` via SSH `vtysh -c "show ip route json"` (FRR native JSON)
- [x] Implement `get_system_info` via SSH `show version` (parsed)
- [x] `/ready` probes RESTCONF + SSH on every inventory device
- [x] `/invoke` returns structured JSON end-to-end from both VMs
- [x] `.env.example`, new `README.md`, paramiko added to `requirements.txt`
- [x] Smoke test: `smoke-test/smoke_phase1.py` — 11/11 checks pass in ~5.5s
- [ ] Delete `_legacy/` once user confirms no need to reference it

**Exit criteria met:** `POST /invoke {"tool":"get_system_info","inputs":{"switch_ip":"10.46.11.50"}}` and the other three tools return structured payloads from both VM1 and VM2.

### Phase 2 — broader tool set (shipped 2026-04-17)
- [x] `sonic/transport_ssh.py` (paramiko) — done in Phase 1
- [x] Per-tool transport declaration in catalog — done in Phase 1
- [x] `get_lldp_neighbors` — combines RESTCONF openconfig-lldp (primary) with `lldpcli -f json` over SSH (fallback + diagnostics). Reports explicit note when TX>0 and RX=0 (the documented SONiC VS limitation).
- [x] `get_ipv6_routes` — via `vtysh show ipv6 route json`
- [x] `get_bgp_summary` — IPv4 + IPv6 peer summary via `vtysh show (ip|bgp ipv6) bgp summary json`
- [x] `run_show_command` — safe, allowlisted escape hatch (regex-validated, 256-char cap, blocks shell metacharacters and quotes, returns raw stdout/stderr/exit)
- [x] Systemd unit shipped at `systemd/sonic-mcp.service` with install instructions at `systemd/README.md`
- [x] Smoke: 20/20 against VM1+VM2 in ~9.3s (covers all 8 tools plus a negative test that `run_show_command` rejects `rm -rf /`)
- [ ] `get_platform_summary` (parse `show platform summary`) — deferred; `run_show_command "show platform summary"` covers the raw case for now
- [ ] Multi-device variants of existing tools (query all inventory devices in parallel, aggregate) — moved to Phase 3

### Phase 3 — Automation & observability depth
- [ ] Multi-device variants of existing tools (query all inventory devices in parallel, aggregate)
- [ ] gNMI transport via `pygnmi` (streaming + polled `Get`)
- [ ] Topology tool (optional Containerlab LLDP lab integration — see `sonic_initial_docs/LLDP_TOPOLOGY.md`)
- [ ] Config changes (start with safe, idempotent mutations via RESTCONF PATCH)
- [ ] Workflow/planner wiring (scaffolding already present in runtime)

### Out of scope (for now)
- RoCE/RDMA tooling — revisit when real Mellanox hardware lands (see `sonic_initial_docs/FUTURE_HARDWARE.md`)
- Write/mutation tools — kept behind policy flag until Phase 3
- Redis DB direct access — deferred; consider in Phase 3 if specific reads are faster that way

---

## 7. Conventions

- **Tool naming:** `<category>_<verb>_<object>` — e.g. `interfaces_get_status`, `routing_get_routes`, `system_get_info`. Category aligns with handler dir (`sonic/tools/<category>/`).
- **Inputs:** every tool takes `switch_ip` (required). Optional filters per tool.
- **Outputs:** `{tool, status, payload, context, meta, explain}` envelope from the existing runtime — unchanged.
- **Errors:** HTTP status codes at `/invoke` layer preserved (404 tool-not-found, 403 policy-violation, 422 validation, 500 upstream).
- **Policy default:** `SAFE_READ` until we explicitly add mutations.
- **Logging:** structured, redacting `password`/`token`/`secret`/`key` — keep the existing redaction helper.

---

## 8. Open questions / parking lot

- Is there a convention we want for referring to devices by name (e.g. `vm1`/`vm2`) instead of IPs? Implies a small inventory file.
- gNMI auth mode in this build (cert? user/password via metadata?) — resolve when Phase 3 starts.
- How aggressive should we be about caching RESTCONF responses? Probably not at all until we see real traffic patterns.
- Docker image target: ship the MCP server as a container alongside the VMs? Deferred until Phase 1 is working bare-metal.

---

## 9. Change log

- **2026-04-17:** Plan created. Capability probe ran — RESTCONF + OpenConfig confirmed on both VMs. Decision: RESTCONF-first, SSH Phase 2, gNMI Phase 3. Quarantine via `_legacy/`.
- **2026-04-17:** Deeper probe of YANG modules revealed only 11 are implemented in community master; `openconfig-system` and routing models return 500/404. Decision amended: **SSH moved into Phase 1** (needed for `get_routes` and `get_system_info`). `get_routes` uses FRR's native `vtysh show ip route json` — structured output with no text parsing.
- **2026-04-17:** Phase 1 walking skeleton shipped. `sonic/` module (credentials, inventory, transport_restconf, transport_ssh, transport wrapper, 4 tool handlers), rewritten `mcp_runtime/registry.py` + `mcp_runtime/server.py`, edited `api/app.py` (`/ready` + title + service name), `.env.example`, new `README.md`, `smoke-test/smoke_phase1.py`. Smoke: 11/11 against VM1+VM2 in ~5.5s.
- **2026-04-17:** `_legacy/` deleted (4.8 MB) after Phase 1 exit criteria met.
- **2026-04-17:** Phase 2 shipped. Added `get_lldp_neighbors`, `get_bgp_summary`, `get_ipv6_routes`, `run_show_command` (4 new tools → 8 total). LLDP probed on VS — confirmed docs: TX OK, RX=0, neighbors empty. Tool surfaces this transparently. Added systemd unit (`systemd/sonic-mcp.service` + README). Smoke: 20/20 in ~9.3s.
- **2026-04-17:** systemd service installed via sudo (`/etc/systemd/system/sonic-mcp.service`, `enable --now`). Service runs as user01, connects to both VMs on /ready. Cleaned `Documentation=` line in unit file.
- **2026-04-17:** `CLIENT_CONTRACT.md` written at repo root — single-page spec of the `/invoke` protocol, session model, error mapping, 8-tool surface, and explicit list of enterprise features the XCO client needs stripped. Intended as the handoff doc for the demo client team / parallel Claude session.
- **2026-04-17:** Client work started in `/home/user01/sonic-mcp-community-client/` (separate dir, same session). XCO client quarantined to `_legacy/`, design tokens (`figmaStyles.ts`, `index.css`) preserved verbatim. Client Phase A shipped: FastAPI proxy (~300 lines, no auth), regex NL router covering all 8 SONiC tools, fresh minimal React App showing `/api/health` + tool catalog. Installed nodejs+npm on the host; `npm run build` produces `frontend/dist/`, served by the backend at single port `5174`. Smoke: `/api/health`, `/api/tools`, `/api/invoke`, `/api/nl` (with and without auto-invoke) all green. UI accessible from user's Mac at `http://<host>:5174/`.
- **2026-04-17:** Client Phase B shipped. Real frontend shell — split into focused files (`App.tsx`, `Sidebar.tsx`, `SwitchPicker.tsx`, `Dashboard.tsx`, `ConsoleView.tsx`, `ToolsView.tsx`, `shared.tsx`, `lib/state.ts`). Three views behind the left sidebar, top-bar switch picker (VM1/VM2 with per-transport status pills), dashboard with device reachability + MCP status cards, AI console with chat history + example-prompt strip + auto-invoke, tools browser with auto-generated input forms from each tool's JSON Schema. Results rendered as JSON (Phase C replaces with widgets). `tsc` + `vite build` clean, 39 modules, 217 KB bundle.
- **2026-04-17:** Client Phase C shipped — widgets for every tool. `widgets/common.tsx` (Table with sticky header + filter, KvGrid, SummaryStrip, Section, UpDownPill, fmtNum) + 7 tool-specific widgets (`InterfacesWidget`, `IpInterfacesWidget`, `RoutesWidget` covers both IPv4 and IPv6, `BgpSummaryWidget`, `LldpWidget`, `SystemInfoWidget`, `ShowCommandWidget`). `ToolResultPanel` wraps every result with status/transport/duration pills + widget↔raw JSON toggle. Console chat turns and Tools result panel both use it. LldpWidget surfaces the "TX>0, RX=0" SONiC VS limitation as a warning banner. 48 modules, 239 KB bundle.
- **2026-04-17:** Server Phase 3a shipped — 6 new tools (**14 total**): `get_vlans`, `get_arp_table`, `get_portchannels` (new `l2/` category), `get_platform_detail` (adds fans/temps/PSUs with "not detected on virtual platform" handling), `get_sflow_status` (RESTCONF openconfig-sampling-sflow), `get_system_info_all` (multi-device fanout). Parallel fan-out primitive at `sonic/tools/_fanout.py` (thread pool, per-host error isolation). CLI table parser helper at `sonic/tools/_parse.py` (box-drawing + fixed-width). Client catalog auto-updates; widgets for the new tools come in Phase 3b.
- **2026-04-17:** Lab fabric rebuilt to a minimal working state. Root cause of user's "my config disappeared" was missing `sudo config save` on SONiC. Root cause of broken inter-switch link was **identical MAC on both VMs** (cloned image) — `DEVICE_METADATA.mac` on VM2 changed to `22:0e:60:52:d4:3c`. 32 phantom ARISTA BGP peers stripped; one real iBGP session VM1↔VM2 established (Loopback0 on VM2 changed to 10.1.0.2 to avoid router-id collision); Vlan100 created on both VMs with Ethernet124 member. Persistence verified by rebooting VM2 — all state survived (new memory: `lab_fabric_state.md`).
- **2026-04-17:** Client Phase 3b shipped — widgets for all 6 new tools (VlansWidget, ArpTableWidget, PortchannelsWidget, PlatformDetailWidget, SflowStatusWidget) + MultiDeviceWidget (generic `_all` handler with per-switch collapsible cards, recursive inner-widget rendering) + HelpWidget (context-aware, uses real device names, live tool catalog as collapsible per-category dropdowns with Run buttons, clickable tips with "try it" buttons). Backend `/api/help` endpoint aggregates live `/ready` + `/tools` + contextual examples. NL router picks up "help" intents (incl. "help on VM1") and 6 new tool patterns (vlans, arp, portchannels, platform_detail, sflow). Client `HelpWidget` dispatches `sonic-mcp:submit-prompt` events for one-click tool invocation.
- **2026-04-17:** Server Phase 3c shipped — 5 more `_all` multi-device variants: `get_interfaces_all`, `get_bgp_summary_all`, `get_routes_all`, `get_lldp_neighbors_all`, `get_vlans_all`. Server now at **19 tools** (13 single + 6 `_all`). Client NL router `_TOOLS_WITH_ALL_VARIANT` allowlist expanded accordingly; bare `\broutes?\b` pattern added so "routes on all switches" triggers fan-out. Smoke: every `_all` variant returns 2/2 ok in 250–1200ms range.
- **2026-04-17:** Client Phase D shipped — LLM fallback in the NL router. New `backend/llm.py` provides OpenAI (default `gpt-4o-mini`) and Ollama (default `qwen2.5:3b-instruct`) backends, both via httpx (no SDK deps). On regex miss, `/api/nl` passes the live tool catalog + device list + switch aliases to the LLM, which returns strict JSON `{tool, inputs, reason}`. LLM picks are validated against the catalog before being treated as a routed intent. New endpoints: `/api/llm-status`, `POST /api/openai-key` (runtime, in-memory only). New frontend `LlmStatus.tsx` top-bar pill showing current backend preference with an inline popover to paste/clear an OpenAI key. ConsoleView tags LLM-sourced suggestions with a "🤖 via LLM" pill alongside the standard confidence pill.
- **2026-04-17:** Client backend systemd unit shipped (`sonic-mcp-client.service`) — mirrors server pattern. Installed at `/etc/systemd/system/`, enabled-and-started, both services now visible in `systemctl list-units`. HelpWidget `TOOL_TO_QUERY` map extended with Run-button entries for all 6 `_all` variants.
- **2026-04-17:** Client Settings view shipped — dedicated ⚙ sidebar entry. Persisted runtime config at `backend/settings.json` (mode 0600, `.gitignore`-excluded). `POST /api/openai-key` and new `PATCH /api/settings` + `GET /api/settings` endpoints. Precedence: `settings.json` > `.env` > default, with source badges in the UI. OpenAI key persists across `systemctl restart` (verified). Added explicit "Active LLM provider" radio selector (`openai` | `ollama` | `auto`) — backend honors the pinned choice and refuses silent fallback. Top-bar pill now shows effective provider + 📌 when pinned. Ollama model input switched to a curated dropdown (qwen2.5 3B/7B, llama3.2 3B, llama3.1 8B, phi3.5, mistral, gemma2) + "Custom…" escape hatch; install instructions auto-update with the selected model.
- **2026-04-17:** Server Phase 4a shipped — mutation tools + policy tiers + persistent ledger. New risk tiers: MUTATION, DESTRUCTIVE. `mcp_runtime/policy.py` gates on three layers (MCP_MUTATIONS_ENABLED env, per-tool requires_confirmation, auto_mode). InvokeRequest gains `confirm: bool = False`. Persistent JSONL ledger at `logs/mutations.jsonl` (thread-safe append, secret-redacting). New tools: `set_interface_admin_status` (MUTATION, requires_confirmation=true — shuts/starts a single interface via `sudo config interface`), `config_save` (MUTATION, no confirmation — `sudo config save -y`), `get_mutation_history` (SAFE_READ — last N ledger entries, filterable). Server at **22 tools**. Smoke: kill switch + confirmation + ledger all proven end-to-end against VM1.
- **2026-04-17:** Client Phase 4 shipped — full mutation UX. New `ConfirmationModal.tsx` (yellow for MUTATION, red for DESTRUCTIVE, Esc/backdrop-to-cancel) pops in both ToolsView and ConsoleView whenever a tool has `requires_confirmation: true`. On confirm, re-invokes with `confirm: true`. Defensive 403 fallback: if the server rejects with "requires explicit confirmation" despite the up-front check (e.g., tools catalog not yet loaded), the client synthesizes a ToolSpec and pops the modal retroactively. `MutationResultWidget` renders pre/post state diff with strike-through on "before" and green bold on changed "after"; surfaces `mutation_id` as a badge. `ActivityView` + `ActivityWidget` — dedicated ⟳ sidebar entry with timeline of every mutation, expandable per-entry for raw inputs/pre/post/error. `CopyButton` fixed for HTTP (non-secure-context) via `execCommand` fallback. Client backend `InvokeReq` model gained `confirm: bool` so the proxy forwards it to the MCP server. NL patterns for `set_interface_admin_status` (shutdown/startup/enable/disable/bring-up/down/no-shut/set/configure verbs + Ethernet literal), `config_save`, and `get_mutation_history`.
- **2026-04-18:** Server Phase 4b shipped — 5 more mutation tools → **27 tools total**, **7 mutations**. New: `set_interface_mtu` (MUTATION+confirm, 68..9216 range), `set_interface_description` (MUTATION, cosmetic so no confirm; writes CONFIG_DB via `sonic-db-cli HSET` since SONiC master dropped the CLI subcommand; strict input sanitisation), `clear_interface_counters` (MUTATION, no confirm, `sonic-clear counters` — all interfaces on this build), `add_vlan` and `remove_vlan` (MUTATION+confirm, `sudo config vlan add/del`, pre/post verified via `sonic-db-cli EXISTS`). Shared helpers `sonic/tools/interfaces/_iface_state.py` and `sonic/tools/l2/_vlan_helpers.py`. Client: 5 new NL patterns with value extraction (interface + mtu / vlan_id); all route `[regex]` with no LLM needed. NL ordering fixed so `add vlan 250` doesn't get caught by `get_vlans`'s bare `\bvlans?\b` fallback. HelpWidget `TOOL_TO_QUERY` extended with Run buttons for all 5 (except `set_interface_description` which needs arbitrary text). All 5 mutations verified end-to-end against VM1 with real pre/post state captures in the ledger.
