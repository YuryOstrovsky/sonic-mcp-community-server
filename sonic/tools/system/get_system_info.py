"""Tool: get_system_info

Retrieve SONiC build, kernel, platform, HwSKU, ASIC, serial, and uptime info.
Source: SSH 'show version'. Output is plain text — parsed via key/value lines.

Why SSH here: community SONiC master does not expose system identity
through openconfig-system (returns HTTP 500); 'show version' is the
stable source across builds.
"""

from __future__ import annotations

import re
from typing import Any, Dict, Optional

from sonic.tools._common import require_switch_ip


_FIELDS = [
    ("SONiC Software Version", "sonic_software_version"),
    ("SONiC OS Version", "sonic_os_version"),
    ("Distribution", "distribution"),
    ("Kernel", "kernel"),
    ("Build commit", "build_commit"),
    ("Build date", "build_date"),
    ("Built by", "built_by"),
    ("Platform", "platform"),
    ("HwSKU", "hwsku"),
    ("ASIC", "asic"),
    ("ASIC Count", "asic_count"),
    ("Serial Number", "serial_number"),
    ("Model Number", "model_number"),
    ("Hardware Revision", "hardware_revision"),
    ("Uptime", "uptime"),
    ("Date", "date"),
]


def _parse_show_version(text: str) -> Dict[str, Optional[str]]:
    out: Dict[str, Optional[str]] = {k: None for _label, k in _FIELDS}
    for line in text.splitlines():
        for label, key in _FIELDS:
            m = re.match(rf"^\s*{re.escape(label)}\s*:\s*(.*)$", line)
            if m:
                val = m.group(1).strip()
                if val and val.upper() != "N/A":
                    out[key] = val
                break
    return out


def get_system_info(
    *,
    inputs: Dict[str, Any],
    registry,
    transport,
    context: Dict[str, Any],
) -> Dict[str, Any]:
    switch_ip = require_switch_ip(inputs, context)

    res = transport.ssh.run(switch_ip, "show version")
    if res.exit_status != 0:
        raise RuntimeError(
            f"show version exited with {res.exit_status}: {res.stderr[:300]}"
        )

    parsed = _parse_show_version(res.stdout)

    return {
        "summary": {
            "switch_ip": switch_ip,
            "source": "ssh show version",
        },
        "system": parsed,
    }
