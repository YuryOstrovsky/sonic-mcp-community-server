"""Tool invocation policy.

Three layers of gating:
  1. MCP_MUTATIONS_ENABLED — server-wide kill switch. Any tool with risk
     MUTATION or DESTRUCTIVE is rejected unless this env is on.
  2. requires_confirmation — per-tool flag. When true, the caller must
     send confirm=true in the /invoke request body.
  3. allowed_in_auto_mode — per-tool flag for autonomous agents.

Violations raise PolicyViolation, which the FastAPI layer maps to HTTP 403.
"""

from __future__ import annotations

import os
from typing import Any, Dict

_MUTATION_RISKS = {"MUTATION", "DESTRUCTIVE"}


class PolicyViolation(Exception):
    pass


def mutations_enabled() -> bool:
    return os.environ.get("MCP_MUTATIONS_ENABLED", "").strip().lower() in (
        "1", "true", "yes", "on",
    )


def enforce_policy(
    tool: Dict[str, Any],
    *,
    auto_mode: bool = False,
    confirm: bool = False,
) -> None:
    policy = tool.get("policy") or {}
    risk = policy.get("risk", "SAFE_READ")

    # ---- Layer 1: server-wide mutation kill switch ----
    if risk in _MUTATION_RISKS and not mutations_enabled():
        raise PolicyViolation(
            f"Tool '{tool.get('name')}' has risk tier {risk} but the server "
            f"has mutations disabled. Set MCP_MUTATIONS_ENABLED=1 in the "
            f"environment and restart the service to allow write operations."
        )

    # ---- Layer 2: auto-mode gating ----
    if auto_mode and not policy.get("allowed_in_auto_mode", False):
        raise PolicyViolation(
            f"Tool '{tool.get('name')}' is not allowed in auto mode."
        )

    # ---- Layer 3: per-tool confirmation ----
    if policy.get("requires_confirmation", False) and not confirm:
        raise PolicyViolation(
            f"Tool '{tool.get('name')}' requires explicit confirmation. "
            f"Re-invoke with confirm=true in the request body."
        )
