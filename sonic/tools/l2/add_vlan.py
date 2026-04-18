"""Tool: add_vlan

Create a VLAN (1-4094) in CONFIG_DB.
Source: SSH `sudo config vlan add <vid>`. SONiC's vlanmgrd watches
CONFIG_DB for the new VLAN|Vlan<vid> entry and provisions it.

Risk: MUTATION, requires_confirmation=true — creating a VLAN isn't
destructive, but it does change the L2 configuration and is worth a
deliberate click in production.
"""

from __future__ import annotations

from typing import Any, Dict

from sonic.tools._common import require_switch_ip
from sonic.tools.l2._vlan_helpers import validate_vlan_id, vlan_exists


def add_vlan(
    *,
    inputs: Dict[str, Any],
    registry,
    transport,
    context: Dict[str, Any],
) -> Dict[str, Any]:
    switch_ip = require_switch_ip(inputs, context)
    vid = validate_vlan_id(inputs.get("vlan_id"))

    pre_existed = vlan_exists(transport, switch_ip, vid)
    cmd = f"sudo config vlan add {vid}"
    res = transport.ssh.run(switch_ip, cmd)
    # Don't raise on non-zero — some SONiC builds exit != 0 when VLAN exists
    # but still leave state consistent. We verify via post-check.
    post_exists = vlan_exists(transport, switch_ip, vid)

    if not post_exists:
        raise RuntimeError(
            f"VLAN {vid} was not present after 'config vlan add'. "
            f"exit={res.exit_status} stderr={res.stderr[:300]}"
        )

    return {
        "summary": {
            "switch_ip": switch_ip,
            "vlan_id": vid,
            "pre_existed": pre_existed,
            "now_exists": post_exists,
            "changed": (not pre_existed) and post_exists,
            "note": "VLAN already existed — no-op" if pre_existed else "VLAN created",
            "source": "ssh sudo config vlan add + sonic-db-cli EXISTS verify",
        },
        "pre_state": {"vlan_exists": pre_existed},
        "post_state": {"vlan_exists": post_exists},
        "stdout": res.stdout,
        "stderr": res.stderr,
    }
