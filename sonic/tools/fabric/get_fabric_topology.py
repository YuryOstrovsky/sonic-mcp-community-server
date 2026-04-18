"""Tool: get_fabric_topology

Discover the inter-switch fabric by cross-correlating what every switch in
the inventory says about itself. Fans out three reads per switch in
parallel and builds a graph:

    nodes  = [{id, mgmt_ip, display_name, asn, router_id, version}, ...]
    edges  = [
      {
        source: <mgmt_ip>,         # the switch we learned the adjacency from
        target: <mgmt_ip>,         # resolved opposite end, or null if orphan
        kind: "bgp" | "lldp",
        source_local_if: "Ethernet0",  # LLDP only
        source_peer_ip:  "10.1.1.2",   # BGP only
        source_local_asn: 65001,
        target_remote_asn: 65002,
        established: bool | null,
      },
      ...
    ]

BGP edges are built from `show ip bgp summary` (via the existing
get_bgp_summary handler). Peer IP is matched against every other switch's
configured IP addresses (get_ip_interfaces) to resolve the `target` mgmt IP.
LLDP edges come from get_lldp_neighbors when available (SONiC VS often has
RX=0 so the LLDP side may be empty — we still emit what we have).

Unresolved BGP peers (peer IP not found on any inventory switch) appear
under `unmatched_peers` so the client can show them.
"""

from __future__ import annotations

import ipaddress
from typing import Any, Dict, List, Optional, Tuple

from sonic.tools._fanout import fan_out
from sonic.tools.interfaces.get_ip_interfaces import get_ip_interfaces
from sonic.tools.lldp.get_lldp_neighbors import get_lldp_neighbors
from sonic.tools.routing.get_bgp_summary import get_bgp_summary
from sonic.tools.system.get_system_info import get_system_info


def _fanout(handler, *, inventory, transport, registry, context, switch_ips):
    return fan_out(
        handler=handler,
        inventory=inventory,
        transport=transport,
        registry=registry,
        inputs={},
        context=context or {},
        switch_ips=switch_ips,
    )


def _ip_owner_map(ip_interfaces_by_switch: Dict[str, Any]) -> Dict[str, Tuple[str, str]]:
    """Build {configured_ipv4_address: (owner_mgmt_ip, owner_interface_name)}."""
    owners: Dict[str, Tuple[str, str]] = {}
    for mgmt_ip, entry in ip_interfaces_by_switch.items():
        if entry.get("status") != "ok":
            continue
        payload = entry.get("payload") or {}
        for row in payload.get("ip_interfaces") or []:
            if row.get("family") != "ipv4":
                continue
            addr = row.get("address") or ""
            host_ip = addr.split("/", 1)[0] if "/" in addr else addr
            try:
                ipaddress.IPv4Address(host_ip)
            except Exception:
                continue
            owners[host_ip] = (mgmt_ip, row.get("interface") or "")
    return owners


def _nodes_from_system(
    system_by_switch: Dict[str, Any],
    bgp_by_switch: Dict[str, Any],
    inventory,
) -> List[Dict[str, Any]]:
    nodes: List[Dict[str, Any]] = []
    for mgmt_ip, entry in sorted(system_by_switch.items()):
        reachable = entry.get("status") == "ok"
        sys = ((entry.get("payload") or {}).get("system") or {}) if reachable else {}
        bgp_entry = bgp_by_switch.get(mgmt_ip) or {}
        bgp_payload = (bgp_entry.get("payload") or {}) if bgp_entry.get("status") == "ok" else {}
        bgp_ipv4 = bgp_payload.get("ipv4") or {}
        nodes.append({
            "id": mgmt_ip,
            "mgmt_ip": mgmt_ip,
            "display_name": inventory.resolve(mgmt_ip).name,
            "reachable": reachable,
            "version": sys.get("sonic_software_version"),
            "platform": sys.get("platform"),
            "hwsku": sys.get("hwsku"),
            "asn": bgp_ipv4.get("local_as") or bgp_ipv4.get("as"),
            "router_id": bgp_ipv4.get("router_id"),
        })
    return nodes


def _bgp_edges(
    bgp_by_switch: Dict[str, Any],
    ip_owners: Dict[str, Tuple[str, str]],
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    edges: List[Dict[str, Any]] = []
    orphans: List[Dict[str, Any]] = []
    for src_mgmt, entry in bgp_by_switch.items():
        if entry.get("status") != "ok":
            continue
        payload = entry.get("payload") or {}
        ipv4 = payload.get("ipv4") or {}
        local_asn = ipv4.get("local_as") or ipv4.get("as")
        for peer in ipv4.get("peers") or []:
            peer_ip = peer.get("peer")
            if not peer_ip:
                continue
            target = ip_owners.get(peer_ip)
            edge = {
                "source": src_mgmt,
                "target": target[0] if target else None,
                "target_local_if": target[1] if target else None,
                "kind": "bgp",
                "source_peer_ip": peer_ip,
                "source_local_asn": local_asn,
                "target_remote_asn": peer.get("remote_as"),
                "established": bool(peer.get("established")),
                "state": peer.get("state"),
            }
            if target:
                edges.append(edge)
            else:
                orphans.append(edge)
    return edges, orphans


def _lldp_edges(
    lldp_by_switch: Dict[str, Any],
    mgmt_ip_by_system_name: Dict[str, str],
) -> List[Dict[str, Any]]:
    edges: List[Dict[str, Any]] = []
    for src_mgmt, entry in lldp_by_switch.items():
        if entry.get("status") != "ok":
            continue
        payload = entry.get("payload") or {}
        for n in payload.get("neighbors") or []:
            sysname = n.get("system_name") or ""
            target = mgmt_ip_by_system_name.get(sysname)
            edges.append({
                "source": src_mgmt,
                "target": target,
                "kind": "lldp",
                "source_local_if": n.get("local_interface"),
                "neighbor_system_name": sysname,
                "neighbor_chassis_id": n.get("chassis_id"),
                "neighbor_port_id": n.get("port_id"),
            })
    return edges


def get_fabric_topology(
    *,
    inputs: Dict[str, Any],
    registry,
    transport,
    context: Dict[str, Any],
) -> Dict[str, Any]:
    """Assemble the inter-switch topology.

    Inputs (all optional):
      switch_ips   : list of mgmt IPs to include (default = full inventory)
      include_lldp : bool, default true
    """
    switch_ips = inputs.get("switch_ips") or None
    include_lldp = bool(inputs.get("include_lldp", True))

    # Three read fanouts in parallel per-switch. (fanout itself parallelises
    # the handlers across switches; we still do 3 sequential fanouts since
    # the underlying transport is the bottleneck.)
    system = _fanout(
        get_system_info,
        inventory=transport.inventory, transport=transport, registry=registry,
        context=context, switch_ips=switch_ips,
    )
    ip_ifaces = _fanout(
        get_ip_interfaces,
        inventory=transport.inventory, transport=transport, registry=registry,
        context=context, switch_ips=switch_ips,
    )
    bgp = _fanout(
        get_bgp_summary,
        inventory=transport.inventory, transport=transport, registry=registry,
        context=context, switch_ips=switch_ips,
    )
    lldp = _fanout(
        get_lldp_neighbors,
        inventory=transport.inventory, transport=transport, registry=registry,
        context=context, switch_ips=switch_ips,
    ) if include_lldp else {"by_switch": {}, "summary": {}}

    nodes = _nodes_from_system(
        system.get("by_switch") or {},
        bgp.get("by_switch") or {},
        transport.inventory,
    )

    ip_owners = _ip_owner_map(ip_ifaces.get("by_switch") or {})
    bgp_edges, orphan_peers = _bgp_edges(bgp.get("by_switch") or {}, ip_owners)

    # Build {sonic_hostname -> mgmt_ip} for LLDP resolution. SONiC's LLDP
    # neighbor.system-name is the target's hostname. The inventory already
    # carries a name per device; match on that.
    mgmt_by_name: Dict[str, str] = {
        d.name: d.mgmt_ip for d in transport.inventory.devices
    }
    lldp_edges = _lldp_edges(lldp.get("by_switch") or {}, mgmt_by_name) if include_lldp else []

    edges = bgp_edges + lldp_edges

    return {
        "summary": {
            "node_count": len(nodes),
            "edge_count": len(edges),
            "bgp_edge_count": len(bgp_edges),
            "lldp_edge_count": len(lldp_edges),
            "orphan_peer_count": len(orphan_peers),
            "source": "get_system_info + get_ip_interfaces + get_bgp_summary + get_lldp_neighbors (fanout)",
        },
        "nodes": nodes,
        "edges": edges,
        "unmatched_peers": orphan_peers,
    }
