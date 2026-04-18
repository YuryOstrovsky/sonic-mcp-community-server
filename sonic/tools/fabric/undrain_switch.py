"""Tool: undrain_switch

Administratively bring up every configured BGP neighbour on the target
switch — the reverse of drain_switch. MUTATION + requires confirmation.
"""

from __future__ import annotations

from typing import Any, Dict

from sonic.tools._common import require_switch_ip
from sonic.tools.fabric.drain_switch import _fill_shutdown_flags, _peer_ips, _peer_state, _summary
from sonic.tools.routing._vtysh import vtysh_configure


def undrain_switch(
    *,
    inputs: Dict[str, Any],
    registry,
    transport,
    context: Dict[str, Any],
) -> Dict[str, Any]:
    switch_ip = require_switch_ip(inputs, context)

    pre_summary = _summary(transport, switch_ip)
    asn = (pre_summary.get("ipv4Unicast") or {}).get("as") or (pre_summary.get("ipv4Unicast") or {}).get("localAs")
    if asn is None:
        raise RuntimeError("could not determine local BGP ASN — is BGP running?")
    try:
        asn = int(asn)
    except (TypeError, ValueError):
        raise RuntimeError(f"local BGP ASN is not an integer: {asn!r}")

    peers = _peer_ips(pre_summary)
    if not peers:
        return {
            "summary": {
                "switch_ip": switch_ip, "asn": asn, "peer_count": 0,
                "changed": False,
                "note": "no BGP peers configured — nothing to undrain",
                "source": "vtysh conf t + show ip bgp summary json verify",
            },
            "pre_state":  {"peers": {}},
            "post_state": {"peers": {}},
            "stdout": "", "stderr": "",
        }

    pre_state = _peer_state(pre_summary)
    _fill_shutdown_flags(transport, switch_ip, pre_state)

    cfg = [f"router bgp {asn}"]
    cfg.extend([f"no neighbor {ip} shutdown" for ip in peers])
    res = vtysh_configure(transport, switch_ip, cfg)

    post_summary = _summary(transport, switch_ip)
    post_state = _peer_state(post_summary)
    _fill_shutdown_flags(transport, switch_ip, post_state)

    still_shut = [ip for ip in peers if post_state.get(ip, {}).get("shutdown")]
    if still_shut:
        raise RuntimeError(
            f"undrain_switch: peers {still_shut} still adminShutdown after command. "
            f"exit={res.exit_status} stderr={res.stderr[:300]}"
        )

    changed_count = sum(
        1 for ip in peers
        if (pre_state.get(ip, {}).get("shutdown") is True)
        and (post_state.get(ip, {}).get("shutdown") is False)
    )

    return {
        "summary": {
            "switch_ip": switch_ip,
            "asn": asn,
            "peer_count": len(peers),
            "changed_count": changed_count,
            "changed": changed_count > 0,
            "note": f"{len(peers)} peer(s) un-shut via router bgp {asn}",
            "source": "vtysh conf t + show ip bgp summary json verify",
        },
        "pre_state":  {"peers": pre_state},
        "post_state": {"peers": post_state},
        "stdout": res.stdout,
        "stderr": res.stderr,
    }
