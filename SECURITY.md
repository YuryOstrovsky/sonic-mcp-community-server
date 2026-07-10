# Security Policy

The SONiC MCP Community Server can **read and change the configuration of
network infrastructure**. Please treat it accordingly. This document
describes what the project does to stay safe, how to run it safely, and
how to report a vulnerability.

## Supported versions

This is an early community project. Security fixes are applied to the
latest release only.

| Version | Supported |
|---------|-----------|
| 0.1.x   | ✅ |
| < 0.1   | ❌ |

## Reporting a vulnerability

**Please do not open a public GitHub issue for security problems.**

Report privately using GitHub's **[Report a vulnerability](https://github.com/YuryOstrovsky/sonic-mcp-community-server/security/advisories/new)**
("Security" tab → "Advisories" → "Report a vulnerability"). If that is
unavailable to you, contact the maintainer directly and mark the message
as security-sensitive.

Please include:

- a description of the issue and its impact;
- steps to reproduce or a proof of concept;
- affected version / commit;
- any suggested remediation.

**What not to disclose in public issues, screenshots, or diagnostic
bundles:** switch credentials, management IPs of production gear, API
keys, mutation-ledger contents, or `.env` / `inventory.json` files.
Redact these before sharing.

### Response expectations

This is a volunteer-maintained project, not a commercial product with an
SLA. As a rough guide:

- acknowledgement of a report: within ~7 days;
- initial assessment: within ~14 days;
- fix or mitigation for confirmed high-severity issues: as fast as
  reasonably possible, coordinated with the reporter before public
  disclosure.

## Intended use and threat model

- **This server is intended for labs and trusted management networks.**
  It is **not** designed to be Internet-facing.
- **Do not publish port 8000 to the public Internet.** Run it only on a
  trusted management network, or behind an authenticated reverse proxy
  (mTLS / OAuth2 / SSO). Publishing the port through Docker without a
  firewall in front of it exposes switch-management capabilities.
- Use **least-privilege switch accounts** — give the MCP server only the
  access it needs on each device.
- **Test mutations in a lab before production.** Destructive tools
  (`drain_switch`, `restore_fabric_snapshot`, interface/BGP admin, static
  route changes) can cause network outages.

## Security controls in this project

- **API authentication** — set `MCP_API_KEY` to require an
  `Authorization: Bearer <key>` on `/invoke` and all write endpoints. When
  unset, auth is disabled and the server logs a startup warning. Public
  endpoints: `/health`, `/ready`, `/tools`, `/metrics`, `/docs*`.
- **Mutation kill switch** — `MCP_MUTATIONS_ENABLED` defaults to `0`
  (read-only). Every MUTATION/DESTRUCTIVE tool returns 403 until it is
  explicitly set to `1`.
- **Per-tool confirmation** — tools flagged `requires_confirmation` reject
  requests that don't send `confirm: true`.
- **Mutation ledger** — every write is recorded to `logs/mutations.jsonl`
  with pre/post state; credentials are redacted from the record.
- **Sanitized errors** — unexpected server errors return only a request ID;
  the full detail is logged server-side, never returned to the caller.
- **Rate limiting**, **request body size limits**, and **restrictive CORS**
  (empty allow-list by default) are on by default.
- **Container hardening** — non-root user, multi-stage slim image,
  `no-new-privileges`, read-only-friendly layout, healthcheck.

## Credential and log handling

- Prefer **environment variables** or **`password_env`** (an inventory
  field naming an env var) over inline `password` values in
  `config/inventory.json`.
- Ensure `.env`, real `config/inventory.json`, `logs/`, and `snapshots/`
  are **excluded from Git** (they are, via `.gitignore`).
- Restrict file permissions on secret-bearing files (`chmod 600 .env`).
- Keep credentials out of screenshots, logs, issue reports, and diagnostic
  bundles.

## Known security boundaries

- Rollback is **best-effort, not transactional** — see the README.
- `SONIC_VERIFY_TLS` defaults to `false` for self-signed lab VMs; enable it
  where you have a valid RESTCONF certificate chain.
- The server does not currently implement per-user identity or RBAC — the
  API key is a single shared secret. Layer a reverse proxy for per-user
  auth if you need it.
