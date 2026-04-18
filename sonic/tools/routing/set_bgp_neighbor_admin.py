"""Tool: set_bgp_neighbor_admin

Administratively shut or no-shut a single BGP neighbor via FRR (vtysh).

FRR stores `neighbor X.Y.Z.W shutdown` under `router bgp <asn>`. To toggle
it we need to:
  1. Find the local ASN (from `show ip bgp summary json`).
  2. Enter `router bgp <asn>` in conf t.
  3. Issue `neighbor <ip> shutdown` or `no neighbor <ip> shutdown`.

Pre/post state verified from `show ip bgp neighbor <ip> json` which reports
adminShutDown=true|false.
"""

from __future__ import annotations

import ipaddress
from typing import Any, Dict, Optional

from sonic.tools._common import require_switch_ip
from sonic.tools.routing._vtysh import vtysh_configure, vtysh_show_json


def _local_asn(transport, switch_ip: str) -> Optional[int]:
    """Discover the local BGP ASN so we can `router bgp <asn>` correctly."""
    try:
        data = vtysh_show_json(transport, switch_ip, "show ip bgp summary json")
    except Exception:
        return None
    ipv4 = data.get("ipv4Unicast") or {}
    asn = ipv4.get("as") or ipv4.get("localAs")
    try:
        return int(asn) if asn is not None else None
    except (TypeError, ValueError):
        return None


def _neighbor_admin_state(
    transport, switch_ip: str, peer: str,
) -> Optional[Dict[str, Any]]:
    try:
        data = vtysh_show_json(
            transport, switch_ip, f"show ip bgp neighbor {peer} json"
        )
    except Exception:
        return None
    body = data.get(peer) if isinstance(data, dict) else None
    if not isinstance(body, dict):
        return None
    return {
        "shutdown": bool(body.get("adminShutDown") or body.get("adminShutdown")),
        "state": body.get("bgpState"),
        "remote_as": body.get("remoteAs"),
    }


def set_bgp_neighbor_admin(
    *,
    inputs: Dict[str, Any],
    registry,
    transport,
    context: Dict[str, Any],
) -> Dict[str, Any]:
    switch_ip = require_switch_ip(inputs, context)

    peer_raw = str(inputs.get("peer", "")).strip()
    try:
        ipaddress.IPv4Address(peer_raw)
    except Exception as e:
        raise ValueError(f"'peer' must be an IPv4 address: {e}")
    peer = peer_raw

    admin = str(inputs.get("admin_status", "")).strip().lower()
    if admin not in {"up", "down"}:
        raise ValueError("'admin_status' must be 'up' or 'down'")

    asn = _local_asn(transport, switch_ip)
    if asn is None:
        raise RuntimeError(
            "could not determine local BGP ASN — is BGP running on this switch?"
        )

    pre = _neighbor_admin_state(transport, switch_ip, peer)

    neighbor_cmd = (
        f"no neighbor {peer} shutdown" if admin == "up"
        else f"neighbor {peer} shutdown"
    )
    cfg = [f"router bgp {asn}", neighbor_cmd]
    res = vtysh_configure(transport, switch_ip, cfg)

    post = _neighbor_admin_state(transport, switch_ip, peer)

    expected_shut = (admin == "down")
    if post is not None and post.get("shutdown") is not expected_shut:
        raise RuntimeError(
            f"neighbor {peer} admin state did not flip to {admin!r}. "
            f"post={post} exit={res.exit_status} stderr={res.stderr[:300]}"
        )

    return {
        "summary": {
            "switch_ip": switch_ip,
            "asn": asn,
            "peer": peer,
            "requested_status": admin.upper(),
            "changed": bool(pre and post and pre.get("shutdown") != post.get("shutdown")),
            "source": "vtysh conf t + show ip bgp neighbor json verify",
        },
        "pre_state": pre,
        "post_state": post,
        "stdout": res.stdout,
        "stderr": res.stderr,
    }
