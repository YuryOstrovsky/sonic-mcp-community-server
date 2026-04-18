"""Tool: get_vlans

List configured VLANs with IP assignment, member ports, and port-tagging mode.
Source: SSH `show vlan brief`.
"""

from __future__ import annotations

from typing import Any, Dict, List

from sonic.tools._common import require_switch_ip
from sonic.tools._parse import parse_box_table


def get_vlans(
    *,
    inputs: Dict[str, Any],
    registry,
    transport,
    context: Dict[str, Any],
) -> Dict[str, Any]:
    switch_ip = require_switch_ip(inputs, context)

    res = transport.ssh.run(switch_ip, "show vlan brief")
    if res.exit_status != 0:
        raise RuntimeError(
            f"show vlan brief exited with {res.exit_status}: {res.stderr[:300]}"
        )

    rows = parse_box_table(res.stdout)

    vlans: List[Dict[str, Any]] = []
    for r in rows:
        vid = r.get("vlan_id") or ""
        if not vid or not vid.strip():
            continue
        ports_raw = r.get("ports") or ""
        ports = [p.strip() for p in ports_raw.replace(",", " ").split() if p.strip()]
        vlans.append(
            {
                "vlan_id": vid,
                "ip_address": r.get("ip_address") or None,
                "ports": ports,
                "port_tagging": r.get("port_tagging") or None,
                "proxy_arp": r.get("proxy_arp") or None,
                "dhcp_helper_address": r.get("dhcp_helper_address") or None,
            }
        )

    return {
        "summary": {
            "switch_ip": switch_ip,
            "count": len(vlans),
            "source": "ssh show vlan brief",
        },
        "vlans": vlans,
    }
