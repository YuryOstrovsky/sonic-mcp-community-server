"""Tool: detect_routing_loop

Traceroute from every switch to every other switch's management IP (or
a user-supplied target) and flag paths whose hop list contains the same
IP twice — that's a loop or flap. Also flags paths that don't reach the
target within `max_hops`.

Inputs:
  targets     : optional list of IPv4 destinations; default = every other
                inventory mgmt IP
  switch_ips  : optional scope; default = full inventory
  max_hops    : default 6 (keep low — these are direct-attach fabrics)
  wait_s      : default 2 — per-hop wait timeout for traceroute
"""

from __future__ import annotations

import concurrent.futures
from typing import Any, Dict, List, Optional

from sonic.tools.fabric.traceroute_between import traceroute_between


def _dup_hop(hops: List[Dict[str, Any]]) -> Optional[str]:
    """Return an IP that appears on >=2 different hops, or None."""
    seen_at: Dict[str, int] = {}
    for h in hops:
        for ip in h.get("ips") or []:
            if ip in seen_at and seen_at[ip] != h.get("hop"):
                return ip
            seen_at.setdefault(ip, h.get("hop"))
    return None


def detect_routing_loop(
    *,
    inputs: Dict[str, Any],
    registry,
    transport,
    context: Dict[str, Any],
) -> Dict[str, Any]:
    scope_sources: Optional[List[str]] = inputs.get("switch_ips") or None
    sources = list(scope_sources) if scope_sources else list(transport.inventory.all_ips())

    raw_targets: Optional[List[str]] = inputs.get("targets") or None
    if raw_targets:
        targets = list(raw_targets)
    else:
        # default: every other switch's mgmt IP
        targets = list(transport.inventory.all_ips())

    max_hops = int(inputs.get("max_hops") or 6)
    wait_s = int(inputs.get("wait_s") or 2)
    if not 1 <= max_hops <= 30:
        raise ValueError("'max_hops' must be 1..30")
    if not 1 <= wait_s <= 5:
        raise ValueError("'wait_s' must be 1..5")

    pairs = [(src, tgt) for src in sources for tgt in targets if src != tgt]

    def _probe(src: str, tgt: str) -> Dict[str, Any]:
        try:
            res = traceroute_between(
                inputs={
                    "source_switch_ip": src, "target": tgt,
                    "max_hops": max_hops, "queries": 1, "wait_s": wait_s,
                },
                registry=registry, transport=transport, context=context or {},
            )
        except Exception as e:
            return {"source": src, "target": tgt, "status": "error", "error": str(e)}
        hops = res.get("hops") or []
        summary = res.get("summary") or {}
        dup = _dup_hop(hops)
        return {
            "source": src, "target": tgt,
            "status": "ok",
            "reached": bool(summary.get("reached")),
            "hop_count": summary.get("hop_count"),
            "looping_ip": dup,
            "has_loop": dup is not None,
            "hops": hops,
        }

    probes: List[Dict[str, Any]] = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=min(8, max(1, len(pairs)))) as ex:
        futures = [ex.submit(_probe, s, t) for s, t in pairs]
        for f in concurrent.futures.as_completed(futures):
            probes.append(f.result())

    loops = [p for p in probes if p.get("has_loop")]
    unreached = [p for p in probes if p.get("status") == "ok" and not p.get("reached")]
    errors = [p for p in probes if p.get("status") == "error"]

    return {
        "summary": {
            "pairs_probed": len(probes),
            "loops_found": len(loops),
            "unreached": len(unreached),
            "errors": len(errors),
            "max_hops": max_hops,
            "source": "traceroute fanout + hop-duplication scan",
        },
        "loops": loops,
        "unreached": unreached,
        "errors": errors,
        "all_probes": probes,
    }
