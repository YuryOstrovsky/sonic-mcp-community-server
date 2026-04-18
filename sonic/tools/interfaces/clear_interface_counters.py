"""Tool: clear_interface_counters

Reset interface traffic counters (in/out pkts, errors, discards).
Source: SSH `sonic-clear counters`.

Risk: MUTATION, requires_confirmation=false — zero impact on forwarding
or config. Just resets the RX/TX accumulators. Commonly used during
troubleshooting ("I want to see fresh counters").

Note: this version of SONiC's sonic-clear takes no per-interface arg —
it clears counters for ALL interfaces. The tool documents that.
"""

from __future__ import annotations

from typing import Any, Dict

from sonic.tools._common import require_switch_ip


def clear_interface_counters(
    *,
    inputs: Dict[str, Any],
    registry,
    transport,
    context: Dict[str, Any],
) -> Dict[str, Any]:
    switch_ip = require_switch_ip(inputs, context)

    cmd = "sonic-clear counters"
    res = transport.ssh.run(switch_ip, cmd)
    if res.exit_status != 0:
        raise RuntimeError(
            f"'{cmd}' exited with {res.exit_status}: {res.stderr[:300]}"
        )

    return {
        "summary": {
            "switch_ip": switch_ip,
            "scope": "all interfaces",
            "note": "sonic-clear counters on this build takes no per-interface argument — it resets counters for every Ethernet interface at once.",
            "source": "ssh sonic-clear counters",
        },
        "pre_state": None,   # counter snapshot would be noisy and volatile
        "post_state": {"counters_cleared": True},
        "stdout": res.stdout,
        "stderr": res.stderr,
    }
