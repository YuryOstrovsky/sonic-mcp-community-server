"""Shared helper: read a single interface's state via RESTCONF.

Used by every interface-mutation tool (set_interface_admin_status,
set_interface_mtu, set_interface_description) to snapshot pre/post state
for the mutation ledger.
"""

from __future__ import annotations

from typing import Any, Dict, Optional


def read_interface_state(transport, switch_ip: str, interface: str) -> Optional[Dict[str, Any]]:
    """Best-effort: return the interface's state dict (admin/oper/mtu/
    description + counters) or None if RESTCONF couldn't answer. Handlers
    tolerate None so a mutation can still proceed even if the pre-snapshot
    fails."""
    try:
        r = transport.restconf.get_json(
            switch_ip,
            f"/data/openconfig-interfaces:interfaces/interface={interface}/state",
        )
    except Exception:
        return None
    body = (r.get("payload") or {}).get("openconfig-interfaces:state") or {}
    return {
        "admin_status": body.get("admin-status"),
        "oper_status": body.get("oper-status"),
        "mtu": body.get("mtu"),
        "description": body.get("description"),
        "counters": body.get("counters") or None,
    }
