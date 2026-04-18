"""Tool: get_interfaces

Retrieve interface status for a SONiC switch via RESTCONF + OpenConfig.
Source: GET /restconf/data/openconfig-interfaces:interfaces
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from sonic.tools._common import require_switch_ip


def get_interfaces(
    *,
    inputs: Dict[str, Any],
    registry,
    transport,
    context: Dict[str, Any],
) -> Dict[str, Any]:
    switch_ip = require_switch_ip(inputs, context)
    name_filter: Optional[str] = inputs.get("name")

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
        if name_filter and name != name_filter:
            continue
        state = intf.get("state") or {}
        counters = state.get("counters") or {}
        eth_state = (
            (intf.get("openconfig-if-ethernet:ethernet") or {}).get("state") or {}
        )
        rows.append(
            {
                "name": name,
                "admin_status": state.get("admin-status"),
                "oper_status": state.get("oper-status"),
                "mtu": state.get("mtu"),
                "description": state.get("description") or None,
                "port_speed": eth_state.get("port-speed"),
                "in_pkts": counters.get("in-pkts"),
                "out_pkts": counters.get("out-pkts"),
                "in_errors": counters.get("in-errors"),
                "out_errors": counters.get("out-errors"),
                "in_discards": counters.get("in-discards"),
                "out_discards": counters.get("out-discards"),
            }
        )

    up = sum(1 for r in rows if r["oper_status"] == "UP")

    return {
        "summary": {
            "switch_ip": switch_ip,
            "count": len(rows),
            "oper_up": up,
            "filter": {"name": name_filter},
            "source": "restconf openconfig-interfaces:interfaces",
        },
        "interfaces": rows,
    }
