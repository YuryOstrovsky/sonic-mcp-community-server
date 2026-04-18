"""Tool: get_ip_interfaces

List L3 (IPv4/IPv6) interface assignments for a SONiC switch.
Source: GET /restconf/data/openconfig-interfaces:interfaces
(filtered to subinterfaces carrying IP addresses).
"""

from __future__ import annotations

from typing import Any, Dict, List

from sonic.tools._common import require_switch_ip


def _addresses(addr_container: Dict[str, Any]) -> List[Dict[str, Any]]:
    return ((addr_container or {}).get("addresses") or {}).get("address") or []


def _pick_ip_plen(addr: Dict[str, Any]):
    src = addr.get("state") or addr.get("config") or {}
    return src.get("ip"), src.get("prefix-length")


def get_ip_interfaces(
    *,
    inputs: Dict[str, Any],
    registry,
    transport,
    context: Dict[str, Any],
) -> Dict[str, Any]:
    switch_ip = require_switch_ip(inputs, context)

    r = transport.restconf.get_json(
        switch_ip, "/data/openconfig-interfaces:interfaces"
    )
    oc = (r.get("payload") or {}).get("openconfig-interfaces:interfaces") or {}
    interfaces = oc.get("interface") or []

    rows: List[Dict[str, Any]] = []
    for intf in interfaces:
        if not isinstance(intf, dict):
            continue
        name = intf.get("name")
        admin = (intf.get("state") or {}).get("admin-status")
        oper = (intf.get("state") or {}).get("oper-status")
        subs = (intf.get("subinterfaces") or {}).get("subinterface") or []
        for sub in subs:
            if not isinstance(sub, dict):
                continue
            idx = sub.get("index", 0)

            for addr in _addresses(sub.get("openconfig-if-ip:ipv4") or {}):
                ip, plen = _pick_ip_plen(addr)
                if ip:
                    rows.append(
                        {
                            "interface": name,
                            "subif": idx,
                            "family": "ipv4",
                            "address": f"{ip}/{plen}" if plen is not None else ip,
                            "admin_status": admin,
                            "oper_status": oper,
                        }
                    )
            for addr in _addresses(sub.get("openconfig-if-ip:ipv6") or {}):
                ip, plen = _pick_ip_plen(addr)
                if ip:
                    rows.append(
                        {
                            "interface": name,
                            "subif": idx,
                            "family": "ipv6",
                            "address": f"{ip}/{plen}" if plen is not None else ip,
                            "admin_status": admin,
                            "oper_status": oper,
                        }
                    )

    return {
        "summary": {
            "switch_ip": switch_ip,
            "count": len(rows),
            "ipv4_count": sum(1 for r in rows if r["family"] == "ipv4"),
            "ipv6_count": sum(1 for r in rows if r["family"] == "ipv6"),
            "source": "restconf openconfig-interfaces:interfaces (subinterfaces)",
        },
        "ip_interfaces": rows,
    }
