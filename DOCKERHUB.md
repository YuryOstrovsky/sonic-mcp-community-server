# SONiC MCP Community Server

A **Model Context Protocol (MCP)** server for **SONiC** switches. Exposes
53 tools — reads, mutations, and fabric-level diagnostics — that any AI
agent or plain HTTP client can use to inspect and safely change a SONiC
fabric.

Pair with [`extremecanada/sonic-mcp-community-client`](https://hub.docker.com/r/extremecanada/sonic-mcp-community-client) for the web UI.

---

## 🚀 Quick start

```bash
docker pull extremecanada/sonic-mcp-community-server:latest

docker run -d --name sonic-mcp \
  -p 8000:8000 \
  -e SONIC_DEFAULT_USERNAME=admin \
  -e SONIC_DEFAULT_PASSWORD=YourSwitchPassword \
  -e MCP_MUTATIONS_ENABLED=1 \
  -v $(pwd)/config:/app/config:ro \
  -v $(pwd)/logs:/app/logs \
  -v $(pwd)/snapshots:/app/snapshots \
  extremecanada/sonic-mcp-community-server:latest

curl http://localhost:8000/tools | jq 'length'   # → 53
```

That's it. Point it at any SONiC switch reachable from the container
over RESTCONF (`:443`) and SSH (`:22`).

---

## 🧱 docker-compose

```yaml
services:
  mcp:
    image: extremecanada/sonic-mcp-community-server:latest
    container_name: sonic-mcp
    restart: unless-stopped
    ports: ["8000:8000"]
    env_file: .env
    volumes:
      - ./config:/app/config:ro       # intent files (validate_fabric_vs_intent)
      - ./logs:/app/logs              # mutation ledger (JSONL)
      - ./snapshots:/app/snapshots    # saved config_db.json dumps
    environment:
      - SONIC_FABRIC_INTENT_PATH=/app/config/fabric_intent.json
```

Create `.env` alongside:

```env
SONIC_DEFAULT_USERNAME=admin
SONIC_DEFAULT_PASSWORD=YourSwitchPassword
MCP_MUTATIONS_ENABLED=1
SONIC_VERIFY_TLS=false
```

Then: `docker compose up -d`.

---

## 🔑 Environment variables

| Variable | Default | Purpose |
|---|---|---|
| `SONIC_DEFAULT_USERNAME` / `_PASSWORD` | — | Credentials for all switches (override per-host with `SONIC_HOST_<IP_with_underscores>_USERNAME` / `_PASSWORD`) |
| `MCP_MUTATIONS_ENABLED` | `1` | Server-wide kill switch. `0` makes every MUTATION/DESTRUCTIVE tool return 403 |
| `SONIC_VERIFY_TLS` | `false` | RESTCONF TLS verify (lab switches use self-signed) |
| `SONIC_RESTCONF_PORT` | `443` | mgmt-framework HTTPS port |
| `SONIC_SSH_TIMEOUT_SECONDS` | `20` | paramiko SSH timeout |
| `MCP_LOG_LEVEL` | `INFO` | Python log level |
| `CORS_ORIGINS` | `""` | Comma-separated allowed origins, or `*` |
| `SONIC_FABRIC_INTENT_PATH` | `config/fabric_intent.json` | Override path for `validate_fabric_vs_intent` |

---

## 📂 Volumes

| Mount | Purpose | Mode |
|---|---|---|
| `/app/config` | Intent JSON(s) for `validate_fabric_vs_intent` | `ro` recommended |
| `/app/logs` | `mutations.jsonl` — the mutation audit trail | `rw` required |
| `/app/snapshots` | `save_fabric_snapshot` / `restore_fabric_snapshot` output | `rw` required |

**Nothing lab-specific is baked into the image** — every credential,
intent, and snapshot lives on the host.

---

## 🔌 Endpoints

| Path | Purpose |
|---|---|
| `GET /tools` | Full tool catalog (JSON array, 53 entries) |
| `POST /invoke` | Run a tool. Body: `{tool, inputs, confirm?}` |
| `GET /ready` | Probes every device on RESTCONF + SSH; 503 if nothing reachable |
| `GET /health` | Liveness |
| `GET /metrics` | Prometheus scrape (tool invocation + fabric health gauges) |
| `GET /fabric/intent` / `PUT /fabric/intent` | Manage intent JSON |

---

## 🛡️ Safety tiers

Every mutation is triple-gated:

1. **`MCP_MUTATIONS_ENABLED=0`** → 403 on every write tool
2. **Per-tool `requires_confirmation`** → client must send `confirm=true`
3. **Auto-mode allow-list** → gates agentic callers

Every successful mutation lands in `/app/logs/mutations.jsonl` with
pre/post state. `rollback_mutation` replays any reversible entry.

---

## 🧰 Companion client

The web UI with fabric graph, AI console, mutation-confirm modal,
command palette, intent editor, and row actions is a separate image:

```bash
docker pull extremecanada/sonic-mcp-community-client:latest
```

See [`extremecanada/sonic-mcp-community-client`](https://hub.docker.com/r/extremecanada/sonic-mcp-community-client)
for its own quickstart.

---

## 🔗 Links

- **Source:** https://github.com/YuryOstrovsky/sonic-mcp-community-server
- **Client repo:** https://github.com/YuryOstrovsky/sonic-mcp-community-client
- **Client image:** [`extremecanada/sonic-mcp-community-client`](https://hub.docker.com/r/extremecanada/sonic-mcp-community-client)
- **License:** Apache-2.0

---

## ⚠️ Notes

- This build has **no auth** on the REST API. Put it on a trusted
  network (VPN, Tailscale, Cloudflare Access, reverse-proxy with auth).
- The container runs as non-root user `mcp` (uid 1000) with
  `no-new-privileges`. Host-side bind-mounts inherit that uid.
- Tags: `:latest`, `:<major>`, `:<major>.<minor>`, `:<full-semver>`.
  Pin to an exact version in production.
