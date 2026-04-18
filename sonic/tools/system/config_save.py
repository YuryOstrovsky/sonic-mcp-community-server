"""Tool: config_save

Persist the running CONFIG_DB to /etc/sonic/config_db.json so the config
survives reboot. Equivalent to operators running `sudo config save -y`.

This is classified MUTATION because it changes disk state, but it's
safe (no network impact) and reversible (just don't save again before
reboot). requires_confirmation=false, allowed_in_auto_mode=true — the
common case is "I just made 5 interface changes, now persist them all".
"""

from __future__ import annotations

from typing import Any, Dict

from sonic.tools._common import require_switch_ip


def config_save(
    *,
    inputs: Dict[str, Any],
    registry,
    transport,
    context: Dict[str, Any],
) -> Dict[str, Any]:
    switch_ip = require_switch_ip(inputs, context)

    res = transport.ssh.run(switch_ip, "sudo config save -y")
    saved = res.exit_status == 0

    return {
        "summary": {
            "switch_ip": switch_ip,
            "saved": saved,
            "duration_ms": res.duration_ms,
            "source": "ssh sudo config save -y",
        },
        "pre_state": {"saved_to_disk": "unknown (pre-save)"},
        "post_state": {"saved_to_disk": saved, "exit_status": res.exit_status},
        "stdout": res.stdout[-800:],
        "stderr": res.stderr[-400:],
    }
