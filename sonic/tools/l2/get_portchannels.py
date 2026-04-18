"""Tool: get_portchannels

List configured link-aggregation groups (port-channels / LAGs) with their
protocol and member ports.
Source: SSH `show interfaces portchannel` (fixed-width with a leading Flags legend).
"""

from __future__ import annotations

from typing import Any, Dict, List

from sonic.tools._common import require_switch_ip
from sonic.tools._parse import parse_fixed_width_table


def _split_members(s: str) -> List[Dict[str, Any]]:
    """Parse a ports cell like 'Ethernet0(S) Ethernet4(D)' into [{port, flag}, …]."""
    out: List[Dict[str, Any]] = []
    for tok in s.split():
        tok = tok.strip()
        if not tok:
            continue
        if "(" in tok and tok.endswith(")"):
            name, flag = tok[:-1].split("(", 1)
            out.append({"port": name, "flag": flag})
        else:
            out.append({"port": tok, "flag": None})
    return out


def get_portchannels(
    *,
    inputs: Dict[str, Any],
    registry,
    transport,
    context: Dict[str, Any],
) -> Dict[str, Any]:
    switch_ip = require_switch_ip(inputs, context)

    res = transport.ssh.run(switch_ip, "show interfaces portchannel")
    if res.exit_status != 0:
        raise RuntimeError(
            f"show interfaces portchannel exited with {res.exit_status}: {res.stderr[:300]}"
        )

    rows = parse_fixed_width_table(res.stdout)

    entries: List[Dict[str, Any]] = []
    for r in rows:
        team = r.get("team_dev") or ""
        if not team:
            continue
        entries.append(
            {
                "no": r.get("no"),
                "team_dev": team,
                "protocol": r.get("protocol") or None,
                "members": _split_members(r.get("ports") or ""),
            }
        )

    return {
        "summary": {
            "switch_ip": switch_ip,
            "count": len(entries),
            "source": "ssh show interfaces portchannel",
        },
        "portchannels": entries,
    }
