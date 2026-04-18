"""Tool: add_static_route

Install an IPv4 static route in the default VRF via FRR (vtysh).
Source: `vtysh -c 'conf t' -c 'ip route <prefix> <nexthop>' -c 'end'`.

Pre/post state is read via `vtysh -c "show ip route <prefix> json"`.
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
    # FRR returns {} when the prefix isn't in the RIB, or a dict keyed by
    # prefix when it is.
    return bool(data)


def _parse_prefix(s: str) -> str:
    """Return canonical '<net>/<plen>' form. Raises ValueError if invalid."""
    net = ipaddress.IPv4Network(s, strict=False)
    return str(net)


def _parse_nexthop(s: str) -> str:
    ipaddress.IPv4Address(s)  # raises on invalid
    return s


def add_static_route(
    *,
    inputs: Dict[str, Any],
    registry,
    transport,
    context: Dict[str, Any],
) -> Dict[str, Any]:
    switch_ip = require_switch_ip(inputs, context)

    try:
        prefix = _parse_prefix(str(inputs.get("prefix", "")).strip())
    except Exception as e:
        raise ValueError(f"'prefix' must be IPv4 network (e.g. '10.0.0.0/24'): {e}")
    try:
        nexthop = _parse_nexthop(str(inputs.get("nexthop", "")).strip())
    except Exception as e:
        raise ValueError(f"'nexthop' must be an IPv4 address: {e}")

    distance_raw = inputs.get("distance")
    distance = None
    if distance_raw not in (None, ""):
        try:
            distance = int(distance_raw)
        except (TypeError, ValueError):
            raise ValueError("'distance' must be an integer 1..255")
        if not 1 <= distance <= 255:
            raise ValueError("'distance' must be 1..255")

    pre_present = _route_present(transport, switch_ip, prefix)

    cfg = f"ip route {prefix} {nexthop}"
    if distance is not None:
        cfg = f"{cfg} {distance}"
    res = vtysh_configure(transport, switch_ip, [cfg])

    post_present = _route_present(transport, switch_ip, prefix)

    if not post_present:
        raise RuntimeError(
            f"route {prefix} not present after '{cfg}'. "
            f"exit={res.exit_status} stderr={res.stderr[:300]}"
        )

    return {
        "summary": {
            "switch_ip": switch_ip,
            "prefix": prefix,
            "nexthop": nexthop,
            "distance": distance,
            "pre_existed": pre_present,
            "changed": (not pre_present) and post_present,
            "note": "route already existed — no-op" if pre_present else "route installed",
            "source": "vtysh conf t + show ip route json verify",
        },
        "pre_state": {"present": pre_present},
        "post_state": {"present": post_present},
        "stdout": res.stdout,
        "stderr": res.stderr,
    }
