"""Tool: get_routes

Retrieve the IPv4 routing table via FRR's native JSON output.
Source: SSH 'vtysh -c "show ip route [vrf X] json"'

FRR's JSON output is stable and native — no text parsing required.
"""

from __future__ import annotations

import json
from typing import Any, Dict, List

from sonic.tools._common import require_switch_ip


def get_routes(
    *,
    inputs: Dict[str, Any],
    registry,
    transport,
    context: Dict[str, Any],
) -> Dict[str, Any]:
    switch_ip = require_switch_ip(inputs, context)
    vrf = inputs.get("vrf")

    if vrf:
        cmd = f'vtysh -c "show ip route vrf {vrf} json"'
    else:
        cmd = 'vtysh -c "show ip route json"'

    res = transport.ssh.run(switch_ip, cmd)
    if res.exit_status != 0:
        raise RuntimeError(
            f"vtysh exited with {res.exit_status}: {res.stderr[:300]}"
        )

    text = res.stdout.strip()
    routes_by_prefix: Dict[str, Any] = {}
    if text:
        try:
            routes_by_prefix = json.loads(text)
        except json.JSONDecodeError as e:
            raise RuntimeError(
                f"could not parse vtysh JSON: {e}; first 200 chars: {text[:200]}"
            )

    flat: List[Dict[str, Any]] = []
    for prefix, entries in (routes_by_prefix or {}).items():
        if not isinstance(entries, list):
            continue
        for e in entries:
            if not isinstance(e, dict):
                continue
            flat.append(
                {
                    "prefix": prefix,
                    "protocol": e.get("protocol"),
                    "selected": bool(e.get("selected")),
                    "installed": bool(e.get("installed")),
                    "distance": e.get("distance"),
                    "metric": e.get("metric"),
                    "uptime": e.get("uptime"),
                    "vrf": e.get("vrfName"),
                    "nexthops": [
                        {
                            "ip": nh.get("ip"),
                            "interface": nh.get("interfaceName"),
                            "directly_connected": bool(nh.get("directlyConnected")),
                            "active": bool(nh.get("active")),
                            "fib": bool(nh.get("fib")),
                        }
                        for nh in (e.get("nexthops") or [])
                        if isinstance(nh, dict)
                    ],
                }
            )

    flat.sort(key=lambda r: (r["vrf"] or "", r["prefix"]))

    by_proto: Dict[str, int] = {}
    for r in flat:
        key = r["protocol"] or "unknown"
        by_proto[key] = by_proto.get(key, 0) + 1

    return {
        "summary": {
            "switch_ip": switch_ip,
            "vrf": vrf or "default",
            "prefix_count": len(routes_by_prefix),
            "entry_count": len(flat),
            "by_protocol": by_proto,
            "source": "ssh vtysh show ip route json",
        },
        "routes": flat,
    }
