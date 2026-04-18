"""Tool: set_portchannel_member

Add or remove an Ethernet interface as a member of a PortChannel (LAG).

Source: SSH `sudo config portchannel member add|del <PortChannel> <Ethernet>`.
The command returns non-zero in some edge cases (member already present/
absent) — we rely on the post-state check via CONFIG_DB.

Pre/post state is read from CONFIG_DB's PORTCHANNEL_MEMBER|<po>|<eth> keys.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List

from sonic.tools._common import require_switch_ip


_PO_RE = re.compile(r"^PortChannel\d+$")
_ETH_RE = re.compile(r"^Ethernet\d+$")


def _members(transport, switch_ip: str, portchannel: str) -> List[str]:
    """Return the list of Ethernet members currently configured on the LAG.
    Uses `sonic-db-cli` on CONFIG_DB to enumerate PORTCHANNEL_MEMBER|<po>|*.
    """
    cmd = f'sudo sonic-db-cli CONFIG_DB KEYS "PORTCHANNEL_MEMBER|{portchannel}|*"'
    res = transport.ssh.run(switch_ip, cmd)
    if res.exit_status != 0:
        return []
    out = []
    for line in (res.stdout or "").splitlines():
        parts = line.strip().split("|", 2)
        if len(parts) == 3 and parts[0] == "PORTCHANNEL_MEMBER" and parts[1] == portchannel:
            out.append(parts[2])
    return sorted(out)


def set_portchannel_member(
    *,
    inputs: Dict[str, Any],
    registry,
    transport,
    context: Dict[str, Any],
) -> Dict[str, Any]:
    switch_ip = require_switch_ip(inputs, context)

    portchannel = str(inputs.get("portchannel", "")).strip()
    interface = str(inputs.get("interface", "")).strip()
    action = str(inputs.get("action", "")).strip().lower()

    if not _PO_RE.match(portchannel):
        raise ValueError("'portchannel' must match 'PortChannelN' (e.g. 'PortChannel1')")
    if not _ETH_RE.match(interface):
        raise ValueError("'interface' must match 'EthernetN' (e.g. 'Ethernet0')")
    if action not in {"add", "remove"}:
        raise ValueError("'action' must be 'add' or 'remove'")

    pre_members = _members(transport, switch_ip, portchannel)
    pre_has_it = interface in pre_members

    verb = "add" if action == "add" else "del"
    cmd = f"sudo config portchannel member {verb} {portchannel} {interface}"
    res = transport.ssh.run(switch_ip, cmd)

    post_members = _members(transport, switch_ip, portchannel)
    post_has_it = interface in post_members

    if action == "add" and not post_has_it:
        raise RuntimeError(
            f"{interface} not a member of {portchannel} after '{cmd}'. "
            f"exit={res.exit_status} stderr={res.stderr[:300]}"
        )
    if action == "remove" and post_has_it:
        raise RuntimeError(
            f"{interface} still a member of {portchannel} after '{cmd}'. "
            f"exit={res.exit_status} stderr={res.stderr[:300]}"
        )

    return {
        "summary": {
            "switch_ip": switch_ip,
            "portchannel": portchannel,
            "interface": interface,
            "action": action,
            "changed": pre_has_it != post_has_it,
            "note": (
                "no-op (member was already in the requested state)" if pre_has_it == post_has_it
                else f"member {'added' if action == 'add' else 'removed'}"
            ),
            "source": "ssh sudo config portchannel + sonic-db-cli CONFIG_DB verify",
        },
        "pre_state": {"members": pre_members},
        "post_state": {"members": post_members},
        "stdout": res.stdout,
        "stderr": res.stderr,
    }
