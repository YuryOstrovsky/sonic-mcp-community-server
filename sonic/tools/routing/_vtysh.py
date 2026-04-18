"""Shared helper for running vtysh configure-mode commands.

FRR stores running config per-switch under /etc/sonic/frr/*.conf and reloads
it on restart. For a MUTATION tool we only care about the *running* config —
SONiC's separate `config save` persists frr.conf on disk.

Design:
  - Takes a list of config-mode commands (no leading "conf t"/"end").
  - Wraps them in vtysh -c "conf t" ... -c "end" form.
  - `sudo -n` so it runs under the paramiko-connected user without a TTY
    prompt (the lab user has NOPASSWD for vtysh via the SONiC defaults).
"""

from __future__ import annotations

import shlex
from dataclasses import dataclass
from typing import Any, List


@dataclass
class VtyshResult:
    exit_status: int
    stdout: str
    stderr: str
    command: str


def vtysh_configure(transport, switch_ip: str, cfg_lines: List[str]) -> VtyshResult:
    """Run a batch of `configure terminal` commands through vtysh via SSH.

    Each `cfg_lines[i]` should be a single config-mode directive like
    'ip route 10.0.0.0/24 10.1.1.2' or 'router bgp 65001'.
    """
    if not cfg_lines:
        raise ValueError("vtysh_configure: no commands given")

    parts = ["sudo", "-n", "vtysh", "-c", shlex.quote("configure terminal")]
    for line in cfg_lines:
        # Empty lines are tolerated (acts as a harmless vtysh no-op).
        parts.extend(["-c", shlex.quote(line)])
    parts.extend(["-c", shlex.quote("end")])
    cmd = " ".join(parts)

    res = transport.ssh.run(switch_ip, cmd)
    return VtyshResult(
        exit_status=res.exit_status,
        stdout=res.stdout,
        stderr=res.stderr,
        command=cmd,
    )


def vtysh_show_json(transport, switch_ip: str, show_cmd: str) -> Any:
    """Run `vtysh -c "<show_cmd>"` and parse JSON stdout.
    Used by pre/post verification hooks in routing mutations.
    """
    import json
    cmd = f'vtysh -c {shlex.quote(show_cmd)}'
    res = transport.ssh.run(switch_ip, cmd)
    if res.exit_status != 0:
        raise RuntimeError(
            f"vtysh exited {res.exit_status}: {res.stderr[:300]}"
        )
    text = (res.stdout or "").strip()
    if not text:
        return {}
    try:
        return json.loads(text)
    except json.JSONDecodeError as e:
        raise RuntimeError(
            f"vtysh '{show_cmd}' did not return JSON: {e}; first 200 chars: {text[:200]}"
        )
