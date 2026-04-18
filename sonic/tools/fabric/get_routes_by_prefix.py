"""Tool: get_routes_by_prefix

Search the whole fabric RIB for a given IP prefix. Answers:
  "Who advertises 10.0.0.0/24? Which switches have it installed via BGP?"

Strategy: fanout get_routes across the inventory, filter each switch's
route list to those whose destination is exactly `prefix` OR a parent
(covers) OR a child (covered by) depending on `match_mode`.

Inputs:
  prefix     : required, IPv4 CIDR (e.g. 10.0.0.0/24)
  match_mode : optional, one of {"exact","covers","covered_by","any"}. Default "any".
  switch_ips : optional, limit scope to these switches

Output:
  summary: { prefix, match_mode, switch_count, installed_on, absent_on }
  by_switch: { ip: {status, matches: [route_row, ...]} }
"""

from __future__ import annotations

import ipaddress
from typing import Any, Dict, List, Optional

from sonic.tools._fanout import fan_out
from sonic.tools.routing.get_routes import get_routes


def _route_prefix(row: Dict[str, Any]) -> Optional[ipaddress.IPv4Network]:
    # get_routes emits rows like {destination: "10.0.0.0/24", ...}.
    # Different FRR builds may use `prefix` instead — accept both.
    raw = row.get("destination") or row.get("prefix")
    if not raw:
        return None
    try:
        return ipaddress.IPv4Network(raw, strict=False)
    except Exception:
        return None


def _matches(row_net: ipaddress.IPv4Network, target: ipaddress.IPv4Network, mode: str) -> bool:
    if mode == "exact":
        return row_net == target
    if mode == "covers":       # row covers (is a supernet of) target
        return row_net.supernet_of(target) and row_net != target
    if mode == "covered_by":   # row is inside target
        return target.supernet_of(row_net) and row_net != target
    # "any" = exact OR covers OR covered_by
    return (
        row_net == target
        or row_net.supernet_of(target)
        or target.supernet_of(row_net)
    )


def get_routes_by_prefix(
    *,
    inputs: Dict[str, Any],
    registry,
    transport,
    context: Dict[str, Any],
) -> Dict[str, Any]:
    prefix_raw = str(inputs.get("prefix", "")).strip()
    if not prefix_raw:
        raise ValueError("'prefix' is required (e.g. '10.0.0.0/24')")
    try:
        target = ipaddress.IPv4Network(prefix_raw, strict=False)
    except Exception as e:
        raise ValueError(f"'prefix' must be a valid IPv4 network: {e}")

    mode = str(inputs.get("match_mode", "any")).strip().lower()
    if mode not in {"exact", "covers", "covered_by", "any"}:
        raise ValueError("'match_mode' must be one of exact|covers|covered_by|any")

    switch_ips = inputs.get("switch_ips") or None

    fo = fan_out(
        handler=get_routes,
        inventory=transport.inventory,
        transport=transport, registry=registry,
        inputs={}, context=context or {}, switch_ips=switch_ips,
    )

    by_switch: Dict[str, Any] = {}
    installed_on: List[str] = []
    absent_on: List[str] = []

    for ip, entry in (fo.get("by_switch") or {}).items():
        if entry.get("status") != "ok":
            by_switch[ip] = {"status": "error", "error": entry.get("error"), "matches": []}
            continue
        payload = entry.get("payload") or {}
        rows = payload.get("routes") or []
        matches: List[Dict[str, Any]] = []
        for row in rows:
            net = _route_prefix(row)
            if net is None:
                continue
            if _matches(net, target, mode):
                matches.append(row)
        by_switch[ip] = {"status": "ok", "match_count": len(matches), "matches": matches}
        if matches:
            installed_on.append(ip)
        else:
            absent_on.append(ip)

    return {
        "summary": {
            "prefix": str(target),
            "match_mode": mode,
            "switch_count": len(by_switch),
            "installed_on_count": len(installed_on),
            "installed_on": installed_on,
            "absent_on": absent_on,
            "source": "get_routes fanout + prefix filter",
        },
        "by_switch": by_switch,
    }
