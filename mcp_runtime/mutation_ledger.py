"""Persistent mutation ledger.

Every MUTATION / DESTRUCTIVE tool invocation is appended as a single JSON
line to `logs/mutations.jsonl`. Reads use the same file (tail-N for the
`get_mutation_history` tool; full scan for operator audits). Append is
atomic for short lines on POSIX — combined with a threading.Lock we're
safe against interleaved concurrent writes.

Schema per line:
    {
      "mutation_id":    "mut-<uuid8>",
      "timestamp":      "2026-04-17T21:05:33.882Z",
      "tool":           "set_interface_admin_status",
      "risk":           "MUTATION",
      "switch_ip":      "10.46.11.50",
      "inputs":         {...original inputs...},
      "status":         "ok" | "failed",
      "pre_state":      {...tool-specific},
      "post_state":     {...tool-specific},
      "error":          "<str or null>",
      "request_id":     "req-…",
      "correlation_id": "corr-…",
      "session_id":     "<uuid or null>",
      "agent":          "<str or null>"
    }

Keeping this intentionally simple: no indexing, no rotation — rely on
logrotate / journald downstream if size matters.
"""

from __future__ import annotations

import json
import os
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional
from uuid import uuid4


_LEDGER_PATH = Path(os.environ.get("MCP_MUTATION_LEDGER", "logs/mutations.jsonl"))


class MutationLedger:
    """Append-only persistent ledger. Expose `record()` for writes and
    `tail()` / `list_all()` for reads.
    """

    def __init__(self, path: Path = _LEDGER_PATH):
        self.path = path
        self._lock = threading.Lock()
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def record(
        self,
        *,
        tool: str,
        risk: str,
        switch_ip: Optional[str],
        inputs: Dict[str, Any],
        status: str,
        pre_state: Any = None,
        post_state: Any = None,
        error: Optional[str] = None,
        request_id: Optional[str] = None,
        correlation_id: Optional[str] = None,
        session_id: Optional[str] = None,
        agent: Optional[str] = None,
    ) -> Dict[str, Any]:
        entry = {
            "mutation_id": f"mut-{uuid4().hex[:8]}",
            "timestamp": datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z"),
            "tool": tool,
            "risk": risk,
            "switch_ip": switch_ip,
            "inputs": _redact_inputs(inputs),
            "status": status,
            "pre_state": pre_state,
            "post_state": post_state,
            "error": error,
            "request_id": request_id,
            "correlation_id": correlation_id,
            "session_id": session_id,
            "agent": agent,
        }
        line = json.dumps(entry, ensure_ascii=False) + "\n"
        with self._lock:
            with open(self.path, "a", encoding="utf-8") as f:
                f.write(line)
        return entry

    def tail(self, n: int = 50) -> List[Dict[str, Any]]:
        if not self.path.exists():
            return []
        with self._lock, open(self.path, "r", encoding="utf-8") as f:
            lines = f.readlines()
        out: List[Dict[str, Any]] = []
        for line in lines[-n:]:
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except Exception:
                out.append({"_unparseable_line": line[:200]})
        return out

    def list_all(self) -> List[Dict[str, Any]]:
        return self.tail(n=10**9)


# Redaction — some inputs might carry credentials or confirmation tokens.
_REDACT_KEYS = {"password", "token", "secret", "api_key", "key", "confirm_token"}


def _redact_inputs(inputs: Dict[str, Any]) -> Dict[str, Any]:
    if not isinstance(inputs, dict):
        return inputs
    return {k: ("***" if k.lower() in _REDACT_KEYS else v) for k, v in inputs.items()}


# Module-level singleton used by server.py and the get_mutation_history tool.
LEDGER = MutationLedger()
