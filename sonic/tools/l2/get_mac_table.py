"""Tool: get_mac_table

Retrieve the forwarding (MAC) table.
Source: SSH `show mac` — fixed-width plain text.
"""

from __future__ import annotations

from typing import Any, Dict, List

from sonic.tools._common import require_switch_ip
from sonic.tools._parse import parse_fixed_width_table


def get_mac_table(
    *,
    inputs: Dict[str, Any],
    registry,
    transport,
    context: Dict[str, Any],
) -> Dict[str, Any]:
    switch_ip = require_switch_ip(inputs, context)

    res = transport.ssh.run(switch_ip, "show mac")
    if res.exit_status != 0:
        raise RuntimeError(
            f"show mac exited with {res.exit_status}: {res.stderr[:300]}"
        )

    rows = parse_fixed_width_table(res.stdout)

    entries: List[Dict[str, Any]] = []
    for r in rows:
        mac = r.get("macaddress") or r.get("mac") or ""
        if not mac:
            continue
        entries.append(
            {
                "vlan": r.get("vlan") if r.get("vlan") and r.get("vlan") != "-" else None,
                "mac": mac,
                "port": r.get("port") or r.get("interface") or None,
                "type": r.get("type") or None,
            }
        )

    return {
        "summary": {
            "switch_ip": switch_ip,
            "count": len(entries),
            "source": "ssh show mac",
        },
        "entries": entries,
    }
