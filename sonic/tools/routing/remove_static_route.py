"""Tool: remove_static_route

Withdraw an IPv4 static route in the default VRF via FRR (vtysh).
Source: `vtysh -c 'conf t' -c 'no ip route <prefix> <nexthop>' -c 'end'`.
"""

from __future__ import annotations

import ipaddress
from typing import Any, Dict

from sonic.tools._common import require_switch_ip
from sonic.tools.routing._vtysh import vtysh_configure, vtysh_show_json


def _route_present(transport, switch_ip: str, prefix: str) -> bool:
    try:
        data = vtysh_show_json(transport, switch_ip, f"show ip route {prefix} json")
    except Exception:
        return False
    return bool(data)


def remove_static_route(
    *,
    inputs: Dict[str, Any],
    registry,
    transport,
    context: Dict[str, Any],
) -> Dict[str, Any]:
    switch_ip = require_switch_ip(inputs, context)

    try:
        prefix = str(ipaddress.IPv4Network(str(inputs.get("prefix", "")).strip(), strict=False))
    except Exception as e:
        raise ValueError(f"'prefix' must be IPv4 network (e.g. '10.0.0.0/24'): {e}")

    nexthop_raw = str(inputs.get("nexthop", "")).strip()
    if nexthop_raw:
        try:
            ipaddress.IPv4Address(nexthop_raw)
        except Exception as e:
            raise ValueError(f"'nexthop' must be an IPv4 address: {e}")

    pre_present = _route_present(transport, switch_ip, prefix)

    cfg = f"no ip route {prefix}"
    if nexthop_raw:
        cfg = f"{cfg} {nexthop_raw}"
    res = vtysh_configure(transport, switch_ip, [cfg])

    post_present = _route_present(transport, switch_ip, prefix)

    # FRR's `no ip route` silently succeeds even if the route wasn't there.
    # Trust the post-check: if the route is still present, something's wrong.
    if post_present:
        raise RuntimeError(
            f"route {prefix} still present after '{cfg}'. "
            f"exit={res.exit_status} stderr={res.stderr[:300]}"
        )

    return {
        "summary": {
            "switch_ip": switch_ip,
            "prefix": prefix,
            "nexthop": nexthop_raw or None,
            "pre_existed": pre_present,
            "changed": pre_present and not post_present,
            "note": (
                "route did not exist — no-op" if not pre_present
                else "route withdrawn"
            ),
            "source": "vtysh conf t + show ip route json verify",
        },
        "pre_state": {"present": pre_present},
        "post_state": {"present": post_present},
        "stdout": res.stdout,
        "stderr": res.stderr,
    }
