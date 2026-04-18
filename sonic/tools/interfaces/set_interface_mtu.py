"""Tool: set_interface_mtu

Change the MTU (Maximum Transmission Unit) of a single interface.
Source: SSH `sudo config interface mtu <EthernetN> <mtu>`.

Risk: MUTATION, requires_confirmation=true. Wrong MTU can silently
break paths that need jumbo frames (storage / RoCE / large TCP).
Allowed range is 68..9216 bytes.
"""

from __future__ import annotations

import re
import time
from typing import Any, Dict

from sonic.tools._common import require_switch_ip
from sonic.tools.interfaces._iface_state import read_interface_state

_IFACE_RE = re.compile(r"^Ethernet\d+$")
_MTU_MIN = 68
_MTU_MAX = 9216


def set_interface_mtu(
    *,
    inputs: Dict[str, Any],
    registry,
    transport,
    context: Dict[str, Any],
) -> Dict[str, Any]:
    switch_ip = require_switch_ip(inputs, context)
    interface = str(inputs.get("interface", "")).strip()

    if not interface or not _IFACE_RE.match(interface):
        raise ValueError(
            f"'interface' must match 'EthernetN' (e.g. 'Ethernet0'). Got: {interface!r}"
        )

    try:
        mtu = int(inputs.get("mtu"))
    except (TypeError, ValueError):
        raise ValueError(f"'mtu' must be an integer. Got: {inputs.get('mtu')!r}")
    if mtu < _MTU_MIN or mtu > _MTU_MAX:
        raise ValueError(
            f"'mtu' must be between {_MTU_MIN} and {_MTU_MAX}. Got: {mtu}"
        )

    pre = read_interface_state(transport, switch_ip, interface)

    cmd = f"sudo config interface mtu {interface} {mtu}"
    res = transport.ssh.run(switch_ip, cmd)
    if res.exit_status != 0:
        raise RuntimeError(
            f"'{cmd}' exited with {res.exit_status}: {res.stderr[:300]}"
        )

    time.sleep(1.0)  # let SWSS reprogram STATE_DB
    post = read_interface_state(transport, switch_ip, interface)

    changed = bool(pre and post and pre.get("mtu") != post.get("mtu"))

    return {
        "summary": {
            "switch_ip": switch_ip,
            "interface": interface,
            "requested_mtu": mtu,
            "changed": changed,
            "source": "ssh config interface mtu + restconf verify",
        },
        "pre_state": pre,
        "post_state": post,
        "stdout": res.stdout,
        "stderr": res.stderr,
    }
