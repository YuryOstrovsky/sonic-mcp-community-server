# Changelog

All notable changes to this project are documented here. The format is
based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this
project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.1.0] — First community release candidate

First public community release of the SONiC MCP Community Server: 55 tools
across reads, mutations, and fabric-level diagnostics over RESTCONF, SSH,
and `vtysh`.

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
