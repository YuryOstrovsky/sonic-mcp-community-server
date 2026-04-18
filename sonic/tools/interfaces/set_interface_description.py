"""Tool: set_interface_description

Set or clear the description (alias) of a single interface.

SONiC master removed `config interface description` from the CLI, so we
write directly to CONFIG_DB via `sonic-db-cli HSET`. bgpcfgd / other
daemons that watch PORT|<iface> pick the change up automatically.

Risk: MUTATION, requires_confirmation=false — description is purely
cosmetic. No network, no control-plane impact.

Input sanitization is strict: alphanumerics + space + a small set of
safe punctuation, no quotes/backslashes/semicolons — those would break
remote shell quoting.
"""

from __future__ import annotations

import re
from typing import Any, Dict

from sonic.tools._common import require_switch_ip
from sonic.tools.interfaces._iface_state import read_interface_state

_IFACE_RE = re.compile(r"^Ethernet\d+$")
_DESC_ALLOWED = re.compile(r"^[A-Za-z0-9 _\-./:,#+=@()]*$")
_DESC_MAX = 256


def set_interface_description(
    *,
    inputs: Dict[str, Any],
    registry,
    transport,
    context: Dict[str, Any],
) -> Dict[str, Any]:
    switch_ip = require_switch_ip(inputs, context)
    interface = str(inputs.get("interface", "")).strip()
    description = str(inputs.get("description", ""))

    if not _IFACE_RE.match(interface):
        raise ValueError(
            f"'interface' must match 'EthernetN' (e.g. 'Ethernet0'). Got: {interface!r}"
        )
    if len(description) > _DESC_MAX:
        raise ValueError(f"'description' is longer than {_DESC_MAX} characters")
    if not _DESC_ALLOWED.match(description):
        raise ValueError(
            "'description' contains disallowed characters. Only letters, "
            "digits, spaces, and safe punctuation (_-./:,#+=@()) are allowed."
        )

    pre = read_interface_state(transport, switch_ip, interface)

    if description == "":
        # Clear via HDEL
        cmd = f'sudo sonic-db-cli CONFIG_DB HDEL "PORT|{interface}" description'
    else:
        cmd = (
            f'sudo sonic-db-cli CONFIG_DB HSET "PORT|{interface}" '
            f'description "{description}"'
        )
    res = transport.ssh.run(switch_ip, cmd)
    if res.exit_status != 0:
        raise RuntimeError(
            f"'{cmd}' exited with {res.exit_status}: {res.stderr[:300]}"
        )

    post = read_interface_state(transport, switch_ip, interface)
    changed = bool(
        pre and post and (pre.get("description") or "") != (post.get("description") or "")
    )

    return {
        "summary": {
            "switch_ip": switch_ip,
            "interface": interface,
            "requested_description": description,
            "cleared": description == "",
            "changed": changed,
            "source": "ssh sonic-db-cli CONFIG_DB HSET + restconf verify",
        },
        "pre_state": pre,
        "post_state": post,
        "stdout": res.stdout,
        "stderr": res.stderr,
    }
