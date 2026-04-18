"""Tool: remove_vlan

Delete a VLAN from CONFIG_DB.
Source: SSH `sudo config vlan del <vid>`.

Risk: MUTATION, requires_confirmation=true — removing a VLAN with
active members or L3 config can break forwarding. SONiC's config
command refuses if the VLAN has attached L3 interfaces; we don't try
to override that.
"""

from __future__ import annotations

from typing import Any, Dict

from sonic.tools._common import require_switch_ip
from sonic.tools.l2._vlan_helpers import validate_vlan_id, vlan_exists


def remove_vlan(
    *,
    inputs: Dict[str, Any],
    registry,
    transport,
    context: Dict[str, Any],
) -> Dict[str, Any]:
    switch_ip = require_switch_ip(inputs, context)
    vid = validate_vlan_id(inputs.get("vlan_id"))

    pre_existed = vlan_exists(transport, switch_ip, vid)
    cmd = f"sudo config vlan del {vid}"
    res = transport.ssh.run(switch_ip, cmd)
    post_exists = vlan_exists(transport, switch_ip, vid)

    # If we tried to delete and it's still there, surface the error.
    if pre_existed and post_exists:
        raise RuntimeError(
            f"VLAN {vid} still present after 'config vlan del'. "
            f"SONiC may refuse deletion if the VLAN has L3 interfaces or "
            f"attached members. exit={res.exit_status} stderr={res.stderr[:300]}"
        )

    return {
        "summary": {
            "switch_ip": switch_ip,
            "vlan_id": vid,
            "pre_existed": pre_existed,
            "now_exists": post_exists,
            "changed": pre_existed and (not post_exists),
            "note": (
                "VLAN did not exist — no-op" if not pre_existed
                else "VLAN removed" if not post_exists
                else "VLAN still present (see stderr)"
            ),
            "source": "ssh sudo config vlan del + sonic-db-cli EXISTS verify",
        },
        "pre_state": {"vlan_exists": pre_existed},
        "post_state": {"vlan_exists": post_exists},
        "stdout": res.stdout,
        "stderr": res.stderr,
    }
