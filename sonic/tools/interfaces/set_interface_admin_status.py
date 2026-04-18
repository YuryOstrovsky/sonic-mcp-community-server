"""Tool: set_interface_admin_status

Bring a single interface administratively up or down.
Source: SSH `sudo config interface startup|shutdown <Ethernet...>`

Behavior:
  - Reads pre-state (admin/oper/MTU/speed) via RESTCONF openconfig-interfaces
  - Runs the shutdown/startup command via SSH
  - Waits briefly for SWSS to reprogram, then reads post-state
  - Returns pre_state + post_state; the server wraps them in a ledger entry

Inputs:
  switch_ip     : required
  interface     : required, must match ^Ethernet\\d+$ (no injection)
  admin_status  : required, "up" or "down"

Safety: risk=MUTATION, requires_confirmation=true. To run, the client must
send confirm=true on the /invoke request AND the server must have
MCP_MUTATIONS_ENABLED=1 in its environment.
"""

from __future__ import annotations

import re
import time
from typing import Any, Dict, Optional

from sonic.tools._common import require_switch_ip

_IFACE_RE = re.compile(r"^Ethernet\d+$")


def _read_interface_state(transport, switch_ip: str, interface: str) -> Optional[Dict[str, Any]]:
    """Best-effort: pull {admin_status, oper_status, mtu, description, counters}
    for the target interface via RESTCONF. Returns None on failure so the
    mutation can still proceed."""
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


def set_interface_admin_status(
    *,
    inputs: Dict[str, Any],
    registry,
    transport,
    context: Dict[str, Any],
) -> Dict[str, Any]:
    switch_ip = require_switch_ip(inputs, context)

    interface = str(inputs.get("interface", "")).strip()
    admin_status = str(inputs.get("admin_status", "")).strip().lower()

    if not interface or not _IFACE_RE.match(interface):
        raise ValueError(
            "'interface' must match 'EthernetN' (e.g. 'Ethernet0'). Got: "
            f"{interface!r}"
        )
    if admin_status not in {"up", "down"}:
        raise ValueError("'admin_status' must be 'up' or 'down'")

    pre = _read_interface_state(transport, switch_ip, interface)

    action = "startup" if admin_status == "up" else "shutdown"
    cmd = f"sudo config interface {action} {interface}"

    res = transport.ssh.run(switch_ip, cmd)
    if res.exit_status != 0:
        raise RuntimeError(
            f"'{cmd}' exited with {res.exit_status}: {res.stderr[:300]}"
        )

    # Give SWSS a moment to program the ASIC state and propagate to STATE_DB.
    time.sleep(1.0)
    post = _read_interface_state(transport, switch_ip, interface)

    changed = bool(
        pre and post and pre.get("admin_status") != post.get("admin_status")
    )

    return {
        "summary": {
            "switch_ip": switch_ip,
            "interface": interface,
            "requested_status": admin_status.upper(),
            "action": action,
            "changed": changed,
            "source": "ssh config interface + restconf verify",
        },
        "pre_state": pre,
        "post_state": post,
        "stdout": res.stdout,
        "stderr": res.stderr,
    }
