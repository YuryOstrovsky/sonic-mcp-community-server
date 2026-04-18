# SONiC MCP Community Server — Docker quickstart

A fabric-agnostic container image. The image ships the tool catalogue and
FastAPI app; **all lab-specific state stays on the host** via bind-mounts
and a `.env` file.

## 1. Prerequisites

- Docker 24+ with the `compose` plugin (or `docker-compose` 2.x).
- Network reachability from the container to your SONiC management IPs.
  (No special `network_mode` — the default bridge is fine if the host
  can reach the switches.)
- A `.env` file in the same directory as `docker-compose.yml` (see below).

## 2. Configure

```bash
cp .env.example .env
# Edit .env and set at minimum:
#   SONIC_DEFAULT_USERNAME=admin
#   SONIC_DEFAULT_PASSWORD=your-lab-password
#   MCP_MUTATIONS_ENABLED=1   (set to 0 for a read-only mirror)
```

Optional — create a fabric intent file so `validate_fabric_vs_intent`
has something to compare against:

```bash
mkdir -p config
cat > config/fabric_intent.json <<'JSON'
{
  "switches": {
    "10.46.11.50": {
      "asn": 65100,
      "expected_bgp_peers": [
        {"peer_ip": "192.168.1.2", "remote_asn": 65100}
      ],
      "expected_interfaces": [
        {"name": "Ethernet0", "address": "192.168.1.1/30", "mtu": 9100}
      ]
    }
  }
}
JSON
```

## 3. Build + run

```bash
docker compose up -d --build
docker compose logs -f      # watch boot
```

Smoke:

```bash
curl -s http://localhost:8000/health
curl -s http://localhost:8000/tools | jq 'length'
curl -s -X POST http://localhost:8000/invoke \
  -H 'Content-Type: application/json' \
  -d '{"tool":"get_fabric_health","inputs":{}}' | jq .
```

## 4. What lives where

| Host path           | Container path      | Purpose                                  | Mode |
|---------------------|---------------------|------------------------------------------|------|
| `./.env`            | (loaded as env)     | Credentials, kill switches, tunables     | –    |
| `./config/`         | `/app/config`       | Intent file(s) — `fabric_intent.json`    | ro   |
| `./logs/`           | `/app/logs`         | Mutation ledger (`mutations.jsonl`)      | rw   |

**Everything else is immutable in the image.** To upgrade, pull/rebuild;
state survives because it's on the host.

## 5. Overriding the intent path

Three ways, in precedence order (highest first):

1. Per-call input: `"intent_path": "/app/config/other.json"` in the
   `validate_fabric_vs_intent` invocation.
2. Env var `SONIC_FABRIC_INTENT_PATH` (already set to
   `/app/config/fabric_intent.json` by `docker-compose.yml`).
3. Hardcoded default: `config/fabric_intent.json` relative to cwd.

If you want the intent file to live outside `./config`, mount it anywhere
you like and point the env var at that path:

```yaml
environment:
  - SONIC_FABRIC_INTENT_PATH=/shared/fleet/prod-fabric.json
volumes:
  - /nfs/fleet:/shared/fleet:ro
```

## 6. Common operations

| Action                 | Command                              |
|------------------------|--------------------------------------|
| Start                  | `docker compose up -d`               |
| Logs                   | `docker compose logs -f`             |
| Health                 | `docker inspect sonic-mcp --format='{{.State.Health.Status}}'` |
| Tail mutation ledger   | `tail -f logs/mutations.jsonl`       |
| Rebuild after code change | `docker compose up -d --build`    |
| Stop                   | `docker compose down`                |
| Purge (keep state)     | `docker compose down && docker image prune -f` |

## 7. Security notes

- The container runs as non-root (uid 1000). Bind-mounts on `config/` and
  `logs/` inherit that ownership — on most hosts the first user already
  has uid 1000 so no `chown` is needed.
- `no-new-privileges: true` is on by default.
- **This build has no auth on the REST API.** It's designed for private
  lab networks. Put a reverse proxy (nginx + basic auth, Cloudflare
  Access, Tailscale, etc.) in front if you expose it beyond a trusted net.
- `MCP_MUTATIONS_ENABLED=0` turns the server into a read-only mirror —
  every mutation tool returns 403. Recommended default for any deployment
  not owned by you.
