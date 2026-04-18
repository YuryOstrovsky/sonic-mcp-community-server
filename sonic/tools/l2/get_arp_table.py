"""Tool: get_arp_table

Retrieve the ARP/neighbor table.
Source: SSH `show arp` (fixed-width text).
"""

from __future__ import annotations

from typing import Any, Dict, List

from sonic.tools._common import require_switch_ip
from sonic.tools._parse import parse_fixed_width_table


def get_arp_table(
    *,
    inputs: Dict[str, Any],
    registry,
    transport,
    context: Dict[str, Any],
) -> Dict[str, Any]:
    switch_ip = require_switch_ip(inputs, context)

    res = transport.ssh.run(switch_ip, "show arp")
    if res.exit_status != 0:
        raise RuntimeError(
            f"show arp exited with {res.exit_status}: {res.stderr[:300]}"
        )

    rows = parse_fixed_width_table(res.stdout)

    entries: List[Dict[str, Any]] = []
    for r in rows:
        ip = r.get("address") or r.get("ip") or ""
        if not ip:
            continue
        entries.append(
            {
                "ip": ip,
                "mac": r.get("macaddress") or r.get("mac") or None,
                "interface": r.get("iface") or r.get("interface") or None,
                "vlan": r.get("vlan") if r.get("vlan") and r.get("vlan") != "-" else None,
            }
        )

    return {
        "summary": {
            "switch_ip": switch_ip,
            "count": len(entries),
            "source": "ssh show arp",
        },
        "entries": entries,
    }
