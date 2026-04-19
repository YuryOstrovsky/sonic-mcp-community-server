"""Tool: discover_fabric_from_seed

Given a seed switch already in inventory, walk its LLDP neighbors and
recursively (up to max_hops) propose any new management-reachable
switches. Returns a diff the client can present for approval — it
does NOT mutate inventory on its own.

Inputs:
  seed_switch_ip : required — an existing inventory member
  max_hops       : optional int 1..5, default 2
  probe          : optional bool, default true — RESTCONF/SSH probe each
                   candidate before proposing

Output:
  summary:
    seed, hops_walked, candidates_found, proposed_additions_count,
    known_count, unreachable_count
  proposed_additions: [{name, mgmt_ip, tags, discovered_via, restconf?, ssh?}]
  already_known:     [...]
  unreachable:       [...]

**Caveat:** LLDP RX on SONiC VS is often empty (documented upstream).
On the default 2-VM lab this tool will legitimately find nothing.
Real hardware with LLDP working fine is where this shines.
"""

from __future__ import annotations

import concurrent.futures
import ipaddress
from typing import Any, Dict, List, Set, Tuple

from sonic.tools._common import require_switch_ip
from sonic.tools.lldp.get_lldp_neighbors import get_lldp_neighbors


def _neighbor_mgmt_ips(payload: Dict[str, Any]) -> List[Tuple[str, Dict[str, Any]]]:
    """Pull (mgmt_ip, raw_neighbor) tuples from a get_lldp_neighbors payload.
    Skips anything without a usable mgmt-address.
    """
    out: List[Tuple[str, Dict[str, Any]]] = []
    for n in (payload or {}).get("neighbors") or []:
        mgmt = n.get("management_address")
        if not mgmt:
            continue
        mgmt = str(mgmt).strip()
        # management_address can be a comma-separated list in some LLDP stacks
        for candidate in [x.strip() for x in mgmt.split(",") if x.strip()]:
            try:
                ipaddress.IPv4Address(candidate)
            except Exception:
                continue
            out.append((candidate, n))
    return out


def discover_fabric_from_seed(
    *,
    inputs: Dict[str, Any],
    registry,
    transport,
    context: Dict[str, Any],
) -> Dict[str, Any]:
    seed = require_switch_ip(
        {"switch_ip": inputs.get("seed_switch_ip") or inputs.get("switch_ip")}, context,
    )
    try:
        max_hops = int(inputs.get("max_hops") or 2)
    except (TypeError, ValueError):
        raise ValueError("'max_hops' must be an integer 1..5")
    if not 1 <= max_hops <= 5:
        raise ValueError("'max_hops' must be in range 1..5")
    probe = bool(inputs.get("probe", True))

    known_ips: Set[str] = set(transport.inventory.all_ips())
    visited: Set[str] = {seed}
    frontier: List[str] = [seed]

    proposed: Dict[str, Dict[str, Any]] = {}
    already_known: List[Dict[str, Any]] = []
    unreachable: List[Dict[str, Any]] = []
    hops_walked = 0

    for _ in range(max_hops):
        next_frontier: List[str] = []
        for src in frontier:
            try:
                res = get_lldp_neighbors(
                    inputs={"switch_ip": src}, registry=registry,
                    transport=transport, context=context or {},
                )
            except Exception:
                continue
            for mgmt_ip, raw in _neighbor_mgmt_ips(res):
                if mgmt_ip in visited:
                    continue
                visited.add(mgmt_ip)
                entry = {
                    "mgmt_ip": mgmt_ip,
                    "name": (raw.get("system_name") or mgmt_ip).strip(),
                    "tags": ["discovered"],
                    "discovered_via": src,
                    "lldp_system_description": raw.get("system_description"),
                }
                if mgmt_ip in known_ips:
                    already_known.append(entry)
                else:
                    proposed[mgmt_ip] = entry
                    next_frontier.append(mgmt_ip)
        hops_walked += 1
        frontier = next_frontier
        if not frontier:
            break

    # Optional reachability probe of every proposal — keeps bad entries
    # (wrong subnet, firewalled, etc.) out of what the user approves.
    proposed_list = list(proposed.values())
    if probe and proposed_list:
        def _probe(ip: str) -> Dict[str, bool]:
            out = {"restconf": False, "ssh": False}
            try:
                out["restconf"] = bool(transport.restconf.probe(ip))
            except Exception:
                pass
            try:
                out["ssh"] = bool(transport.ssh.probe(ip))
            except Exception:
                pass
            return out

        with concurrent.futures.ThreadPoolExecutor(max_workers=min(8, len(proposed_list))) as ex:
            futs = {ex.submit(_probe, p["mgmt_ip"]): p for p in proposed_list}
            for fut in concurrent.futures.as_completed(futs):
                p = futs[fut]
                try:
                    p.update(fut.result(timeout=10))
                except Exception:
                    pass

        still_proposed: List[Dict[str, Any]] = []
        for p in proposed_list:
            if p.get("restconf") or p.get("ssh"):
                still_proposed.append(p)
            else:
                unreachable.append(p)
        proposed_list = still_proposed

    return {
        "summary": {
            "seed": seed,
            "hops_walked": hops_walked,
            "candidates_found": len(proposed) + len(already_known),
            "proposed_additions_count": len(proposed_list),
            "known_count": len(already_known),
            "unreachable_count": len(unreachable),
            "probe_enabled": probe,
            "source": "LLDP seed-walk",
        },
        "proposed_additions": proposed_list,
        "already_known": already_known,
        "unreachable": unreachable,
    }
