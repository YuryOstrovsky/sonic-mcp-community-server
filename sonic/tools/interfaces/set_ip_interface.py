"""Tool: set_ip_interface

Add or remove an IPv4 address on a SONiC switch interface.

Source: SSH `sudo config interface ip add|remove <intf> <addr>/<plen>`.
SONiC's intfmgrd watches CONFIG_DB and provisions the address.

Pre/post state is read via RESTCONF openconfig-if-ip (subinterface 0).

Inputs:
  switch_ip : required
  interface : required, ^[A-Za-z0-9_./-]+$  (Ethernet0, PortChannel10, Loopback0, Vlan100, …)
  address   : required, IPv4 with prefix length, e.g. "10.1.1.1/24"
  action    : required, "add" or "remove"

Safety: MUTATION + requires_confirmation. L3 misconfigurations cause
traffic blackholes, so this always pops the confirmation modal.
"""

from __future__ import annotations

import ipaddress
import re
import time
from typing import Any, Dict, List, Optional

from sonic.tools._common import require_switch_ip


# SONiC interface name forms we accept. The `sonic-db-cli` / `config` tooling
# honours any valid interface; we restrict character class to avoid injection.
_IFACE_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_./-]{0,31}$")


def _parse_addr_with_prefix(s: str) -> ipaddress.IPv4Interface:
    """Raises ValueError if `s` isn't a valid IPv4 address with a prefix length."""
    # Allow users to pass host-style 10.1.1.1/24 without strict=True balking.
    return ipaddress.IPv4Interface(s)


def _read_ip_state(transport, switch_ip: str, interface: str) -> Optional[List[str]]:
    """Return the list of IPv4 addresses currently assigned on subinterface 0,
    formatted as "<ip>/<plen>". Returns None when RESTCONF can't answer."""
    try:
        r = transport.restconf.get_json(
            switch_ip,
            f"/data/openconfig-interfaces:interfaces/interface={interface}/subinterfaces/subinterface=0/openconfig-if-ip:ipv4/addresses",
        )
    except Exception:
        return None
    addrs_container = (r.get("payload") or {}).get("openconfig-if-ip:addresses") or {}
    out: List[str] = []
    for addr in addrs_container.get("address") or []:
        src = addr.get("state") or addr.get("config") or {}
        ip = src.get("ip")
        plen = src.get("prefix-length")
        if ip:
            out.append(f"{ip}/{plen}" if plen is not None else ip)
    return out


def set_ip_interface(
    *,
    inputs: Dict[str, Any],
    registry,
    transport,
    context: Dict[str, Any],
) -> Dict[str, Any]:
    switch_ip = require_switch_ip(inputs, context)

    interface = str(inputs.get("interface", "")).strip()
    address = str(inputs.get("address", "")).strip()
    action = str(inputs.get("action", "")).strip().lower()

    if not _IFACE_RE.match(interface):
        raise ValueError(
            "'interface' must be a valid SONiC interface name "
            "(e.g. Ethernet0, PortChannel10, Vlan100, Loopback0)"
        )
    if action not in {"add", "remove"}:
        raise ValueError("'action' must be 'add' or 'remove'")
    try:
        parsed = _parse_addr_with_prefix(address)
    except Exception as e:
        raise ValueError(
            f"'address' must be IPv4 with prefix (e.g. '10.1.1.1/24'): {e}"
        )
    normalized = f"{parsed.ip}/{parsed.network.prefixlen}"

    pre = _read_ip_state(transport, switch_ip, interface)
    pre_has_it = pre is not None and normalized in pre

    cmd = f"sudo config interface ip {action} {interface} {normalized}"
    res = transport.ssh.run(switch_ip, cmd)

    # Some SONiC versions exit non-zero on idempotent ops (already-present add
    # or already-absent remove). Tolerate that; trust the post-check.
    time.sleep(0.8)
    post = _read_ip_state(transport, switch_ip, interface)
    post_has_it = post is not None and normalized in post

    if action == "add" and not post_has_it:
        raise RuntimeError(
            f"'{cmd}' did not add the address. "
            f"exit={res.exit_status} stderr={res.stderr[:300]}"
        )
    if action == "remove" and post_has_it:
        raise RuntimeError(
            f"'{cmd}' did not remove the address. "
            f"exit={res.exit_status} stderr={res.stderr[:300]}"
        )

    changed = pre_has_it != post_has_it
    return {
        "summary": {
            "switch_ip": switch_ip,
            "interface": interface,
            "address": normalized,
            "action": action,
            "changed": changed,
            "note": (
                "no-op (address was already in the requested state)" if not changed
                else f"address {'added' if action == 'add' else 'removed'}"
            ),
            "source": "ssh sudo config interface ip + restconf openconfig-if-ip verify",
        },
        "pre_state": {"ipv4_addresses": pre},
        "post_state": {"ipv4_addresses": post},
        "stdout": res.stdout,
        "stderr": res.stderr,
    }
