"""Tool: get_lldp_neighbors

Retrieve LLDP neighbor information plus local advertisement and TX/RX counters.

Sources (combined for a richer answer):
  1. RESTCONF openconfig-lldp:lldp/interfaces — primary neighbor list
  2. SSH 'docker exec lldp lldpcli show neighbors -f json' — fallback (VS-friendly)
  3. SSH 'docker exec lldp lldpcli show statistics -f json' — TX/RX counters
  4. SSH 'docker exec lldp lldpcli show interface   -f json' — what WE advertise

Why the combination: community SONiC VS typically returns an empty
openconfig-lldp payload even when the daemon is running. lldpctl still
exposes TX/RX stats and local chassis info, which makes the empty-neighbor
case diagnosable (e.g., TX>0 but RX=0 means the VS isn't receiving frames —
a known SONiC VS limitation per sonic_initial_docs/LLDP_TOPOLOGY.md).
"""

from __future__ import annotations

import json
from typing import Any, Dict, List

from sonic.tools._common import require_switch_ip


def _openconfig_neighbors(transport, switch_ip: str) -> List[Dict[str, Any]]:
    try:
        r = transport.restconf.get_json(
            switch_ip, "/data/openconfig-lldp:lldp/interfaces"
        )
    except Exception:
        return []
    oc = (r.get("payload") or {}).get("openconfig-lldp:interfaces") or {}
    interfaces = oc.get("interface") or []
    out: List[Dict[str, Any]] = []
    for intf in interfaces:
        if not isinstance(intf, dict):
            continue
        local = intf.get("name")
        neighbors = (intf.get("neighbors") or {}).get("neighbor") or []
        for n in neighbors:
            if not isinstance(n, dict):
                continue
            st = n.get("state") or {}
            out.append(
                {
                    "local_interface": local,
                    "neighbor_id": n.get("id"),
                    "chassis_id": st.get("chassis-id"),
                    "chassis_id_type": st.get("chassis-id-type"),
                    "port_id": st.get("port-id"),
                    "port_description": st.get("port-description"),
                    "system_name": st.get("system-name"),
                    "system_description": st.get("system-description"),
                    "management_address": st.get("management-address"),
                    "ttl": st.get("ttl"),
                    "source": "restconf",
                }
            )
    return out


def _lldpcli_json(transport, switch_ip: str, cmd: str) -> Dict[str, Any]:
    """Run lldpcli inside the lldp docker and parse its JSON output."""
    full = f'docker exec lldp lldpcli -f json {cmd}'
    res = transport.ssh.run(switch_ip, full)
    if res.exit_status != 0:
        # Try with sudo
        res = transport.ssh.run(switch_ip, f"sudo {full}")
    if res.exit_status != 0 or not res.stdout.strip():
        return {}
    try:
        return json.loads(res.stdout)
    except json.JSONDecodeError:
        return {}


def _lldpcli_neighbors(transport, switch_ip: str) -> List[Dict[str, Any]]:
    data = _lldpcli_json(transport, switch_ip, "show neighbors")
    ifaces = (data.get("lldp") or {}).get("interface") or []
    out: List[Dict[str, Any]] = []
    # lldpcli JSON is awkwardly shaped: list of single-key dicts keyed by ifname
    for entry in ifaces if isinstance(ifaces, list) else [ifaces]:
        if not isinstance(entry, dict):
            continue
        for local_name, body in entry.items():
            if not isinstance(body, dict):
                continue
            chassis = body.get("chassis") or {}
            for sys_name, chassis_body in (
                chassis.items() if isinstance(chassis, dict) else []
            ):
                if not isinstance(chassis_body, dict):
                    continue
                port = body.get("port") or {}
                port_id = (port.get("id") or {}).get("value")
                out.append(
                    {
                        "local_interface": local_name,
                        "system_name": sys_name,
                        "chassis_id": (chassis_body.get("id") or {}).get("value"),
                        "chassis_id_type": (chassis_body.get("id") or {}).get(
                            "type"
                        ),
                        "port_id": port_id,
                        "port_description": port.get("descr"),
                        "management_address": chassis_body.get("mgmt-ip"),
                        "system_description": chassis_body.get("descr"),
                        "ttl": (body.get("ttl") or {}).get("ttl"),
                        "source": "lldpcli",
                    }
                )
    return out


def _lldpcli_stats(transport, switch_ip: str) -> List[Dict[str, Any]]:
    data = _lldpcli_json(transport, switch_ip, "show statistics")
    ifaces = (data.get("lldp") or {}).get("interface") or []
    out: List[Dict[str, Any]] = []

    def _pluck(d, key):
        v = d.get(key)
        if isinstance(v, dict):
            return v.get(key)
        return v

    for entry in ifaces if isinstance(ifaces, list) else [ifaces]:
        if not isinstance(entry, dict):
            continue
        for name, body in entry.items():
            if not isinstance(body, dict):
                continue
            out.append(
                {
                    "interface": name,
                    "tx": _pluck(body, "tx"),
                    "rx": _pluck(body, "rx"),
                    "rx_discarded": _pluck(body, "rx_discarded_cnt"),
                    "rx_unrecognized": _pluck(body, "rx_unrecognized_cnt"),
                    "ageout": _pluck(body, "ageout_cnt"),
                    "insert": _pluck(body, "insert_cnt"),
                    "delete": _pluck(body, "delete_cnt"),
                }
            )
    return out


def _lldpcli_local(transport, switch_ip: str) -> Dict[str, Any]:
    data = _lldpcli_json(transport, switch_ip, "show interface")
    ifaces = (data.get("lldp") or {}).get("interface") or []
    # Pull the first chassis advertisement we find — it's the same for every iface
    for entry in ifaces if isinstance(ifaces, list) else [ifaces]:
        if not isinstance(entry, dict):
            continue
        for _name, body in entry.items():
            if not isinstance(body, dict):
                continue
            chassis = body.get("chassis") or {}
            for sys_name, chassis_body in (
                chassis.items() if isinstance(chassis, dict) else []
            ):
                if not isinstance(chassis_body, dict):
                    continue
                return {
                    "system_name": sys_name,
                    "chassis_id": (chassis_body.get("id") or {}).get("value"),
                    "chassis_id_type": (chassis_body.get("id") or {}).get(
                        "type"
                    ),
                    "management_address": chassis_body.get("mgmt-ip"),
                    "system_description": chassis_body.get("descr"),
                    "capabilities": [
                        {"type": c.get("type"), "enabled": c.get("enabled")}
                        for c in (chassis_body.get("capability") or [])
                        if isinstance(c, dict)
                    ],
                }
    return {}


def get_lldp_neighbors(
    *,
    inputs: Dict[str, Any],
    registry,
    transport,
    context: Dict[str, Any],
) -> Dict[str, Any]:
    switch_ip = require_switch_ip(inputs, context)

    oc_neighbors = _openconfig_neighbors(transport, switch_ip)
    lldpcli_neighbors = _lldpcli_neighbors(transport, switch_ip) if not oc_neighbors else []
    stats = _lldpcli_stats(transport, switch_ip)
    local = _lldpcli_local(transport, switch_ip)

    neighbors = oc_neighbors or lldpcli_neighbors

    def _num(x):
        try:
            return int(x)
        except Exception:
            return 0

    total_tx = sum(_num(s.get("tx")) for s in stats)
    total_rx = sum(_num(s.get("rx")) for s in stats)

    notes: List[str] = []
    if not neighbors:
        if stats and total_tx > 0 and total_rx == 0:
            notes.append(
                "LLDP frames are being transmitted but none received (TX>0, RX=0). "
                "This is the documented limitation of SONiC VS — LLDP reception does "
                "not work on the virtual switch. Expect populated neighbors only on "
                "real hardware."
            )
        elif stats and total_tx == 0:
            notes.append(
                "LLDP daemon reports no TX activity. Confirm the lldp container is "
                "running on the switch."
            )
        else:
            notes.append("No LLDP neighbors discovered.")

    return {
        "summary": {
            "switch_ip": switch_ip,
            "neighbor_count": len(neighbors),
            "stats_totals": {"tx": total_tx, "rx": total_rx},
            "neighbor_source": (
                "restconf" if oc_neighbors else
                ("lldpcli" if lldpcli_neighbors else "none")
            ),
            "notes": notes,
        },
        "neighbors": neighbors,
        "local_advertisement": local,
        "per_interface_stats": stats,
    }
