# Contributing to SONiC MCP Community Server

Thanks for considering a contribution! The project is small and
intentionally mechanical — a new tool is usually one Python file plus
one catalog entry. This guide walks through the common cases.

## Quickstart

```bash
git clone https://github.com/YuryOstrovsky/sonic-mcp-community-server
cd sonic-mcp-community-server
python -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
cp .env.example .env          # fill in lab credentials
pytest                        # unit tests (no switches required)
```

For an end-to-end run you need at least one SONiC switch reachable over
RESTCONF + SSH. `smoke-test/smoke_phase1.py` exercises the read path; the
`docker compose up` path documented in `README.docker.md` spins up the
full server.

## Adding a new tool

Every tool is a single Python file in `sonic/tools/<category>/` plus
one entry in `generated/mcp_tools.json`. The registry auto-discovers any
non-underscore module under `sonic/tools/`, so there's no third file
to edit.

### 1. Write the handler

`sonic/tools/<category>/<tool_name>.py`:

```python
"""Tool: <tool_name> — one-line summary."""

from __future__ import annotations
from typing import Any, Dict

from sonic.tools._common import require_switch_ip


def my_new_tool(
    *,
    inputs: Dict[str, Any],
    registry,
    transport,
    context: Dict[str, Any],
) -> Dict[str, Any]:
    switch_ip = require_switch_ip(inputs, context)
    # … do the work …
    return {
        "summary": {"switch_ip": switch_ip, "source": "where the data came from"},
        "entries": [...],
    }
```

The function **name must match the file stem** (`my_new_tool.py` →
`def my_new_tool`). Files whose basename starts with `_` are treated
as private helpers and skipped by the discovery walker.

### 2. Register it in the catalog

Append to `generated/mcp_tools.json`:

```jsonc
{
  "name": "my_new_tool",
  "description": "What it does, in one paragraph — shown in the UI.",
  "category": "interfaces",          // used for grouping
  "transport": "ssh",                 // restconf / ssh / mixed / local
  "input_schema": {
    "type": "object",
    "properties": {
      "switch_ip": {"type": "string", "description": "SONiC mgmt IP."}
    },
    "required": ["switch_ip"]
  },
  "policy": {
    "risk": "SAFE_READ",              // SAFE_READ / MUTATION / DESTRUCTIVE
    "allowed_in_auto_mode": true,
    "requires_confirmation": false
  },
  "tags": ["read", "interfaces"]
}
```

For mutations, set `requires_confirmation: true` so the client pops the
Confirm modal. The ledger captures pre/post state automatically if your
handler returns `pre_state` + `post_state` keys.

### 3. Client-side wiring (optional but recommended)

- Add a NL-router regex in `../sonic-mcp-community-client/backend/nl_router.py`
- Add a TOOL_TO_QUERY entry in the HelpWidget so users see a "Run" button
- If the payload shape needs a custom widget, add one under
  `frontend/src/widgets/` and register it in `widgets/index.tsx`

### 4. Tests

`tests/test_catalog.py` enforces handler↔catalog parity — your new
tool will fail CI if either half is missing. If the logic is non-trivial
(parsing, diffs, rollback planning), add focused unit tests under `tests/`.

## Code style

- `ruff check sonic/ mcp_runtime/ api/ tests/` must be clean.
- Python 3.11+. Type-annotate public function signatures.
- Keep handlers pure-Python — reach network/disk only through the
  `transport` object passed in. Makes tests easy.
- Don't silently swallow errors — raise with context, let the server
  envelope surface the message.

## Risk tiers

| Tier | Rule of thumb |
|------|---------------|
| `SAFE_READ` | No device-state change. ICMP probes count as SAFE_READ. |
| `MUTATION` | Changes device state in a recoverable way. Requires `requires_confirmation: true` for anything with traffic impact. |
| `DESTRUCTIVE` | Hard to reverse (`config reload`, disk wipes, etc.). Always `requires_confirmation: true`. |

The server-wide kill switch `MCP_MUTATIONS_ENABLED=0` turns every
MUTATION/DESTRUCTIVE tool into a 403.

## Reporting bugs

Use the Bug Report template. Include:
1. What you ran / asked for
2. What happened vs what you expected
3. Server logs (`docker compose logs mcp` or `journalctl -u sonic-mcp`)
4. SONiC version + build

## PRs

- Keep them focused — one new tool or one bug fix per PR.
- CI runs pytest on Python 3.11 + 3.12 plus a Docker build smoke test.
- We'll ask for changes, not reject lightly — this is a community repo.
