"""Tool: get_bgp_summary

Retrieve BGP IPv4/IPv6 peer summary from FRR via native JSON output.
Source: SSH 'vtysh -c "show ip bgp summary json"' (plus IPv6).
"""

from __future__ import annotations

import json
from typing import Any, Dict, List

from sonic.tools._common import require_switch_ip


_ESTABLISHED_STATES = {"Established", "established"}


def _fetch(transport, switch_ip: str, cmd: str) -> Dict[str, Any]:
    res = transport.ssh.run(switch_ip, cmd)
    if res.exit_status != 0:
        raise RuntimeError(
            f"vtysh exited with {res.exit_status}: {res.stderr[:300]}"
        )
    text = res.stdout.strip()
    if not text:
        return {}
    try:
        return json.loads(text)
    except json.JSONDecodeError as e:
        raise RuntimeError(
            f"could not parse vtysh JSON for '{cmd}': {e}; first 200 chars: {text[:200]}"
        )


def _peers_from_afi(afi_body: Dict[str, Any]) -> List[Dict[str, Any]]:
    peers_raw = (afi_body or {}).get("peers") or {}
    out: List[Dict[str, Any]] = []
    if isinstance(peers_raw, dict):
        for peer_ip, peer in peers_raw.items():
            if not isinstance(peer, dict):
                continue
            out.append(
                {
                    "peer": peer_ip,
                    "remote_as": peer.get("remoteAs"),
                    "local_as": peer.get("localAs"),
                    "state": peer.get("state"),
                    "peer_state": peer.get("peerState"),
                    "established": peer.get("state") in _ESTABLISHED_STATES,
                    "uptime": peer.get("peerUptime"),
                    "msg_rcvd": peer.get("msgRcvd"),
                    "msg_sent": peer.get("msgSent"),
                    "prefix_rcvd": peer.get("pfxRcd"),
                    "prefix_sent": peer.get("pfxSnt"),
                    "connections_established": peer.get("connectionsEstablished"),
                    "connections_dropped": peer.get("connectionsDropped"),
                    "description": peer.get("desc"),
                }
            )
    return out


def _summarize_afi(afi_body: Dict[str, Any]) -> Dict[str, Any]:
    peers = _peers_from_afi(afi_body)
    established = sum(1 for p in peers if p["established"])
    return {
        "router_id": afi_body.get("routerId"),
        "as": afi_body.get("as"),
        "vrf": afi_body.get("vrfName"),
        "table_version": afi_body.get("tableVersion"),
        "peer_count": afi_body.get("peerCount") or len(peers),
        "established_count": established,
        "peers": peers,
    }


def get_bgp_summary(
    *,
    inputs: Dict[str, Any],
    registry,
    transport,
    context: Dict[str, Any],
) -> Dict[str, Any]:
    switch_ip = require_switch_ip(inputs, context)
    include_ipv6 = bool(inputs.get("include_ipv6", True))
    vrf = inputs.get("vrf")

    v4_cmd = (
        f'vtysh -c "show ip bgp vrf {vrf} summary json"'
        if vrf
        else 'vtysh -c "show ip bgp summary json"'
    )
    v6_cmd = (
        f'vtysh -c "show bgp vrf {vrf} ipv6 summary json"'
        if vrf
        else 'vtysh -c "show bgp ipv6 summary json"'
    )

    v4 = _fetch(transport, switch_ip, v4_cmd)
    v4_summary = _summarize_afi(v4.get("ipv4Unicast") or {})

    v6_summary: Dict[str, Any] = {}
    if include_ipv6:
        try:
            v6 = _fetch(transport, switch_ip, v6_cmd)
            # FRR may return ipv6Unicast inside top level OR inside 'ipv6Unicast' key
            v6_summary = _summarize_afi(
                v6.get("ipv6Unicast") or v6 or {}
            )
        except Exception:
            v6_summary = {}

    totals = {
        "ipv4_peers": v4_summary.get("peer_count") or 0,
        "ipv4_established": v4_summary.get("established_count") or 0,
        "ipv6_peers": v6_summary.get("peer_count") or 0,
        "ipv6_established": v6_summary.get("established_count") or 0,
    }

    return {
        "summary": {
            "switch_ip": switch_ip,
            "vrf": vrf or "default",
            "totals": totals,
            "source": "ssh vtysh show (ip|bgp ipv6) bgp summary json",
        },
        "ipv4": v4_summary,
        "ipv6": v6_summary,
    }
