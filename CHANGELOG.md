# Changelog

All notable changes to this project are documented here. The format is
based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this
project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.2.0] — Standards-compliant MCP transport

### Added

- **Standard Model Context Protocol support** — the same 55-tool registry is
  now exposed over the official MCP protocol, so any MCP client (Claude
  Desktop, claude.ai connectors, agent SDKs) gets plug-and-play tool
  discovery:
  - **Streamable HTTP** mounted at `/mcp` on the existing server (gated by the
    same `MCP_API_KEY` Bearer auth).
  - **stdio** entrypoint `python -m mcp_runtime.mcp_stdio` for local clients
    like Claude Desktop.
  - Tools carry JSON-Schema inputs, risk annotations (`readOnlyHint` /
    `destructiveHint`), and a `confirm` flag on mutating tools. Policy parity:
    the `MCP_MUTATIONS_ENABLED` kill switch, mutation ledger, and metrics all
    apply to MCP calls.
- New `mcp_runtime/mcp_protocol.py` (adapter) and `mcp_runtime/mcp_stdio.py`
  (entrypoint); in-memory protocol tests.

### Unchanged

- The custom `/tools` + `/invoke` REST API is untouched — the companion web
  client and plain HTTP callers work exactly as before.

## [0.1.0] — First community release candidate

First public community release of the SONiC MCP Community Server: 55 tools
across reads, mutations, and fabric-level diagnostics over RESTCONF, SSH,
and `vtysh`.

### Security

- Pinned dependencies updated to clear 13 known CVEs flagged by `pip-audit`
  before the first release: `cryptography` 46.0.4 → 49.0.0, `starlette`
  0.50.0 → 1.3.1 (compatible with FastAPI 0.139.0, which allows
  `starlette>=0.46`), and `paramiko` 4.0.0 → 5.0.0 (CVE-2026-44405 in the
  SSH transport). Verified `pip-audit --strict` reports no known
  vulnerabilities and the full suite + image boot pass on the new pins.
- Corrected an unresolvable `pydantic-core` pin (2.47.0 → 2.46.4) that a
  grouped Dependabot bump introduced, which had broken `pip install`, the
  Docker build, and CI.

### Added

- **API authentication** — optional `MCP_API_KEY` Bearer token gating
  `/invoke` and all write endpoints (inventory PUT/POST/DELETE,
  `PUT /fabric/intent`, `/inventory/probe`). Public endpoints (`/health`,
  `/ready`, `/tools`, `/metrics`, `/docs*`) stay open. A startup warning is
  logged when the key is unset.
- **`password_env` inventory field** — reference a secret by environment
  variable name instead of storing plaintext in `config/inventory.json`.
- Single authoritative version module (`mcp_runtime/version.py`), surfaced
  by `/health` and the OpenAPI spec.
- `SECURITY.md`, `CODE_OF_CONDUCT.md`, and this `CHANGELOG.md`.
- Dependency and container security scanning in CI (pip-audit, Trivy),
  SBOM generation on release, and Dependabot updates.
- Release workflow now re-runs the full quality gate (ruff, pytest,
  pip-audit) before publishing, and pushes identical immutable tags to both
  GHCR and Docker Hub so a release and the pulled image always match.
- `Authorization` added to the CORS allow-list so a browser client on
  another origin can authenticate (its preflight no longer fails).
- Prominent **Security and intended use** section in the README, plus a
  SONiC compatibility matrix and clarified MCP-protocol scope.

### Changed

- **Docker default is now read-only** — `MCP_MUTATIONS_ENABLED=0` in the
  image (was `1`). Enable writes explicitly. This aligns the Dockerfile
  with `.env.example`, `docker-compose.yml`, and the README.
- Unexpected server errors now return only a request ID; full details are
  logged server-side instead of being sent to the client.

### Security

- See `SECURITY.md`. The server is intended for labs and trusted
  management networks and must not be exposed directly to the Internet.

[Unreleased]: https://github.com/YuryOstrovsky/sonic-mcp-community-server/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/YuryOstrovsky/sonic-mcp-community-server/releases/tag/v0.1.0
