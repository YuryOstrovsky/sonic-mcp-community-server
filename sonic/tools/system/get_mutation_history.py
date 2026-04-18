"""Tool: get_mutation_history

Return recent entries from the mutation ledger. Read-only, SAFE_READ.
Inputs:
  limit     : optional int, default 50 (1..500)
  switch_ip : optional — filter to entries against this switch
  tool      : optional — filter to entries for this tool name
  status    : optional — "ok" or "failed"
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from mcp_runtime.mutation_ledger import LEDGER


def get_mutation_history(
    *,
    inputs: Dict[str, Any],
    registry,
    transport,
    context: Dict[str, Any],
) -> Dict[str, Any]:
    limit = int(inputs.get("limit") or 50)
    limit = max(1, min(limit, 500))

    switch_ip: Optional[str] = inputs.get("switch_ip") or None
    tool_filter: Optional[str] = inputs.get("tool") or None
    status_filter: Optional[str] = inputs.get("status") or None

    entries = LEDGER.tail(n=limit * 4)  # oversample to allow filtering

    def keep(e: Dict[str, Any]) -> bool:
        if switch_ip and e.get("switch_ip") != switch_ip:
            return False
        if tool_filter and e.get("tool") != tool_filter:
            return False
        if status_filter and e.get("status") != status_filter:
            return False
        return True

    filtered: List[Dict[str, Any]] = [e for e in entries if keep(e)][-limit:]

    by_tool: Dict[str, int] = {}
    by_status: Dict[str, int] = {"ok": 0, "failed": 0}
    for e in filtered:
        t = e.get("tool") or "unknown"
        by_tool[t] = by_tool.get(t, 0) + 1
        s = e.get("status") or "unknown"
        by_status[s] = by_status.get(s, 0) + 1

    return {
        "summary": {
            "count": len(filtered),
            "limit": limit,
            "filter": {
                "switch_ip": switch_ip,
                "tool": tool_filter,
                "status": status_filter,
            },
            "by_tool": by_tool,
            "by_status": by_status,
            "source": "mutation ledger (logs/mutations.jsonl)",
        },
        "entries": filtered,
    }
