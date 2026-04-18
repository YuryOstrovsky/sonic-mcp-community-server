"""Tool: drain_switch

Administratively shut every configured BGP neighbour on the target switch.
The reverse operation is `undrain_switch`. Both are MUTATION + require
confirmation — draining removes the switch from the forwarding plane.

Implementation:
  - Read the current BGP peers via `show ip bgp summary json`
  - Enter `router bgp <asn>` in vtysh and issue `neighbor <ip> shutdown`
    for every peer in one batch
  - Verify post-state via `show ip bgp summary json` — peers should all
    report adminShutDown=true
"""

from __future__ import annotations

from typing import Any, Dict, List

from sonic.tools._common import require_switch_ip
from sonic.tools.routing._vtysh import vtysh_configure, vtysh_show_json


def _summary(transport, switch_ip: str) -> Dict[str, Any]:
    try:
        return vtysh_show_json(transport, switch_ip, "show ip bgp summary json")
    except Exception:
        return {}


def _peer_ips(summary: Dict[str, Any]) -> List[str]:
    peers = ((summary or {}).get("ipv4Unicast") or {}).get("peers") or {}
    return [ip for ip in peers.keys() if isinstance(ip, str)]


def _peer_state(summary: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    """Populate remote_as + state from the summary dict; `shutdown` is left
    None here — the caller should fill it in via `_fill_shutdown_flags()`
    which queries `show ip bgp neighbor <ip> json` (where adminShutDown
    actually lives)."""
    peers = ((summary or {}).get("ipv4Unicast") or {}).get("peers") or {}
    out: Dict[str, Dict[str, Any]] = {}
    for ip, body in peers.items():
        if not isinstance(body, dict):
            continue
        out[ip] = {
            "remote_as": body.get("remoteAs"),
            "state": body.get("state"),
            "shutdown": None,
        }
    return out


def _fill_shutdown_flags(transport, switch_ip: str, state: Dict[str, Dict[str, Any]]) -> None:
    """Query `show ip bgp neighbor <ip> json` per peer; fill state[ip]['shutdown']."""
    for ip in list(state.keys()):
        try:
            data = vtysh_show_json(transport, switch_ip, f"show ip bgp neighbor {ip} json")
        except Exception:
            continue
        body = data.get(ip) if isinstance(data, dict) else None
        if isinstance(body, dict):
            state[ip]["shutdown"] = bool(body.get("adminShutDown") or body.get("adminShutdown"))


def drain_switch(
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
                "switch_ip": switch_ip,
                "asn": asn,
                "peer_count": 0,
                "changed": False,
                "note": "no BGP peers configured — nothing to drain",
                "source": "vtysh conf t + show ip bgp summary json verify",
            },
            "pre_state":  {"peers": {}},
            "post_state": {"peers": {}},
            "stdout": "", "stderr": "",
        }

    pre_state = _peer_state(pre_summary)
    _fill_shutdown_flags(transport, switch_ip, pre_state)

    cfg = [f"router bgp {asn}"]
    cfg.extend([f"neighbor {ip} shutdown" for ip in peers])
    res = vtysh_configure(transport, switch_ip, cfg)

    post_summary = _summary(transport, switch_ip)
    post_state = _peer_state(post_summary)
    _fill_shutdown_flags(transport, switch_ip, post_state)

    not_shut = [ip for ip in peers if not post_state.get(ip, {}).get("shutdown")]
    if not_shut:
        raise RuntimeError(
            f"drain_switch: peers {not_shut} did not report adminShutdown after command. "
            f"exit={res.exit_status} stderr={res.stderr[:300]}"
        )

    changed_count = sum(
        1 for ip in peers
        if (pre_state.get(ip, {}).get("shutdown") is False)
        and (post_state.get(ip, {}).get("shutdown") is True)
    )

    return {
        "summary": {
            "switch_ip": switch_ip,
            "asn": asn,
            "peer_count": len(peers),
            "changed_count": changed_count,
            "changed": changed_count > 0,
            "note": f"{len(peers)} peer(s) shut via router bgp {asn}",
            "source": "vtysh conf t + show ip bgp summary json verify",
        },
        "pre_state":  {"peers": pre_state},
        "post_state": {"peers": post_state},
        "stdout": res.stdout,
        "stderr": res.stderr,
    }
