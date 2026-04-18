"""Shared helpers for VLAN mutation tools."""

from __future__ import annotations


def vlan_exists(transport, switch_ip: str, vid: int) -> bool:
    """Check whether CONFIG_DB has a VLAN|Vlan<vid> entry."""
    res = transport.ssh.run(
        switch_ip,
        f'sonic-db-cli CONFIG_DB EXISTS "VLAN|Vlan{vid}"',
    )
    return res.exit_status == 0 and res.stdout.strip() == "1"


def validate_vlan_id(raw) -> int:
    """Coerce + range-check the vlan_id input; raise ValueError on bad input."""
    try:
        vid = int(raw)
    except (TypeError, ValueError):
        raise ValueError(f"'vlan_id' must be an integer. Got: {raw!r}")
    if vid < 1 or vid > 4094:
        raise ValueError(f"'vlan_id' must be between 1 and 4094. Got: {vid}")
    return vid
