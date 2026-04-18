"""Tool: get_fabric_health

Runs get_fabric_topology, then classifies each edge + orphan peer:

  healthy_links  = BGP edges where both ends are in inventory AND the
                   session is established
  broken_links   = BGP edges where both ends are in inventory BUT the
                   session is NOT established
  orphan_peers   = BGP peers whose IP doesn't match any inventory switch
                   (configured but peering to something outside the
                   known fabric — or a mis-addressed interface)
  unreachable    = inventory switches that didn't answer any of the
                   three fanout reads (no system, no IP list, no BGP)

Output shape:
  {
    summary: { healthy, broken, orphan, unreachable, total_edges },
    healthy_links: [edge, ...],
    broken_links:  [edge, ...],
    orphan_peers:  [edge, ...],
    unreachable:   [mgmt_ip, ...],
    topology:      { ... full result of get_fabric_topology ... }
  }
"""

from __future__ import annotations

from typing import Any, Dict, List

from sonic.tools.fabric.get_fabric_topology import get_fabric_topology


def get_fabric_health(
    *,
    inputs: Dict[str, Any],
    registry,
    transport,
    context: Dict[str, Any],
) -> Dict[str, Any]:
    topology = get_fabric_topology(
        inputs=inputs, registry=registry, transport=transport, context=context,
    )

    nodes = topology.get("nodes") or []
    edges = topology.get("edges") or []
    orphans = topology.get("unmatched_peers") or []

    unreachable = [n["mgmt_ip"] for n in nodes if not n.get("reachable")]

    healthy: List[Dict[str, Any]] = []
    broken:  List[Dict[str, Any]] = []
    for e in edges:
        if e.get("kind") != "bgp":
            # LLDP edges are hardware-level presence, not health — include
            # them in the topology but don't classify here.
            continue
        if e.get("established"):
            healthy.append(e)
        else:
            broken.append(e)

    return {
        "summary": {
            "total_edges": len(edges),
            "bgp_edges": len(healthy) + len(broken),
            "healthy": len(healthy),
            "broken": len(broken),
            "orphan": len(orphans),
            "unreachable": len(unreachable),
        },
        "healthy_links": healthy,
        "broken_links": broken,
        "orphan_peers": orphans,
        "unreachable": unreachable,
        "topology": topology,
    }
