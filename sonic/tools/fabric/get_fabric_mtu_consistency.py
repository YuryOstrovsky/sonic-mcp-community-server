"""Tool: get_fabric_mtu_consistency

Walk every pair of peered L3 interfaces (anchored on BGP adjacencies) and
compare MTU on both ends. An MTU mismatch silently blackholes large
packets — this is a classic debugging painpoint in real fabrics.

Strategy:
  1. get_fabric_topology → resolved BGP edges (source_ip → target_ip).
  2. For each edge, fetch interface state on BOTH sides (via
     get_interfaces) and map source_peer_ip → local interface on the
     target switch; extract mtu for both local interfaces.
  3. Report pairs as matched/mismatched, plus links where we couldn't
     determine MTU on one end.

Output:
  summary: {total_pairs, matched, mismatched, unknown}
  mismatched: [{ source, source_if, source_mtu, target, target_if, target_mtu }]
  matched:    [...same shape...]
  unknown:    [...same shape with null mtu fields...]
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from sonic.tools._fanout import fan_out
from sonic.tools.fabric.get_fabric_topology import get_fabric_topology
from sonic.tools.interfaces.get_interfaces import get_interfaces


def _mtu_map_from_payload(payload: Dict[str, Any]) -> Dict[str, int]:
    """Map 'Ethernet0' → mtu (int) from a get_interfaces payload."""
    out: Dict[str, int] = {}
    for row in (payload or {}).get("interfaces") or []:
        name = row.get("name")
        mtu = row.get("mtu")
        if name and mtu is not None:
            try:
                out[name] = int(mtu)
            except (TypeError, ValueError):
                pass
    return out


def get_fabric_mtu_consistency(
    *,
    inputs: Dict[str, Any],
    registry,
    transport,
    context: Dict[str, Any],
) -> Dict[str, Any]:
    # Reuse the topology builder to resolve BGP peer IPs to (switch, iface).
    topology = get_fabric_topology(
        inputs={
            "switch_ips": inputs.get("switch_ips"),
            "include_lldp": False,  # MTU check is BGP-peer-based; skip LLDP.
        },
        registry=registry, transport=transport, context=context,
    )
    bgp_edges = [e for e in (topology.get("edges") or []) if e.get("kind") == "bgp" and e.get("target")]

    # Fanout get_interfaces once per switch so each side's MTU table is handy.
    ifaces = fan_out(
        handler=get_interfaces,
        inventory=transport.inventory,
        transport=transport,
        registry=registry,
        inputs={},
        context=context or {},
        switch_ips=inputs.get("switch_ips") or None,
    )
    mtu_by_switch: Dict[str, Dict[str, int]] = {}
    for ip, entry in (ifaces.get("by_switch") or {}).items():
        if entry.get("status") == "ok":
            mtu_by_switch[ip] = _mtu_map_from_payload(entry.get("payload") or {})
        else:
            mtu_by_switch[ip] = {}

    # Build pairs; dedupe so A↔B doesn't appear as both A→B and B→A.
    seen = set()
    matched: List[Dict[str, Any]] = []
    mismatched: List[Dict[str, Any]] = []
    unknown: List[Dict[str, Any]] = []

    for e in bgp_edges:
        src = e["source"]
        tgt = e["target"]
        src_if = _find_local_if_for_peer(
            transport=transport, registry=registry, context=context,
            switch_ip=src, peer_ip=e.get("source_peer_ip"),
        )
        tgt_if = e.get("target_local_if")
        key = tuple(sorted([(src, src_if or ""), (tgt, tgt_if or "")]))
        if key in seen:
            continue
        seen.add(key)

        src_mtu: Optional[int] = mtu_by_switch.get(src, {}).get(src_if) if src_if else None
        tgt_mtu: Optional[int] = mtu_by_switch.get(tgt, {}).get(tgt_if) if tgt_if else None

        row = {
            "source":     src,
            "source_if":  src_if,
            "source_mtu": src_mtu,
            "target":     tgt,
            "target_if":  tgt_if,
            "target_mtu": tgt_mtu,
            "peer_ip":    e.get("source_peer_ip"),
        }
        if src_mtu is None or tgt_mtu is None:
            unknown.append(row)
        elif src_mtu != tgt_mtu:
            mismatched.append(row)
        else:
            matched.append(row)

    return {
        "summary": {
            "total_pairs": len(matched) + len(mismatched) + len(unknown),
            "matched":     len(matched),
            "mismatched":  len(mismatched),
            "unknown":     len(unknown),
            "source":      "get_fabric_topology + get_interfaces_all",
        },
        "matched":    matched,
        "mismatched": mismatched,
        "unknown":    unknown,
    }


def _find_local_if_for_peer(
    *, transport, registry, context, switch_ip: str, peer_ip: Optional[str],
) -> Optional[str]:
    """Best-effort reverse lookup: which local interface carries a subnet
    containing peer_ip? We reuse the IP-interface data the topology tool
    already collected but can't easily pass through, so re-fetch lazily."""
    if not peer_ip:
        return None
    import ipaddress
    try:
        peer = ipaddress.IPv4Address(peer_ip)
    except Exception:
        return None
    try:
        from sonic.tools.interfaces.get_ip_interfaces import get_ip_interfaces
        res = get_ip_interfaces(
            inputs={"switch_ip": switch_ip}, registry=registry,
            transport=transport, context=context or {},
        )
    except Exception:
        return None
    for row in res.get("ip_interfaces") or []:
        if row.get("family") != "ipv4":
            continue
        addr = row.get("address") or ""
        if "/" not in addr:
            continue
        try:
            net = ipaddress.IPv4Interface(addr).network
        except Exception:
            continue
        if peer in net:
            return row.get("interface")
    return None
