"""Tool: get_fabric_reachability_matrix

N×N ICMP matrix across the inventory. For each source switch, ping every
other switch in parallel. Returns a grid ready for a colour-coded widget.

Inputs:
  switch_ips : optional list of mgmt IPs (default = full inventory)
  count      : ping packets per probe (default 2, 1..5)
  timeout_s  : per-packet timeout (default 2, 1..10)

Output:
  summary: { targets:[...], probe_count, reachable_pct, broken_pairs: [...] }
  matrix:  { source_ip: { target_ip: {reachable, loss_pct, rtt_avg_ms, error?} } }
"""

from __future__ import annotations

import concurrent.futures
from typing import Any, Dict, List, Optional

from sonic.tools.fabric.ping_between import ping_between


def _probe_one(
    *,
    source: str,
    target: str,
    count: int,
    timeout_s: int,
    registry,
    transport,
    context: Dict[str, Any],
) -> Dict[str, Any]:
    try:
        res = ping_between(
            inputs={
                "source_switch_ip": source,
                "target": target,
                "count": count,
                "timeout_s": timeout_s,
            },
            registry=registry,
            transport=transport,
            context=context or {},
        )
        s = res.get("summary") or {}
        return {
            "reachable": bool(s.get("reachable")),
            "loss_pct": s.get("loss_pct"),
            "rtt_avg_ms": s.get("rtt_avg_ms"),
            "transmitted": s.get("transmitted"),
            "received": s.get("received"),
        }
    except Exception as e:
        return {"reachable": False, "error": str(e)}


def get_fabric_reachability_matrix(
    *,
    inputs: Dict[str, Any],
    registry,
    transport,
    context: Dict[str, Any],
) -> Dict[str, Any]:
    raw_ips: Optional[List[str]] = inputs.get("switch_ips")
    targets: List[str] = list(raw_ips) if raw_ips else list(transport.inventory.all_ips())
    if not targets:
        return {
            "summary": {"targets": [], "probe_count": 0, "reachable_pct": None, "broken_pairs": []},
            "matrix": {},
        }

    count_raw = inputs.get("count", 2)
    try:
        count = int(count_raw)
    except (TypeError, ValueError):
        raise ValueError("'count' must be an integer 1..5")
    if not 1 <= count <= 5:
        raise ValueError("'count' must be in range 1..5")

    timeout_raw = inputs.get("timeout_s", 2)
    try:
        timeout_s = int(timeout_raw)
    except (TypeError, ValueError):
        raise ValueError("'timeout_s' must be an integer 1..10")
    if not 1 <= timeout_s <= 10:
        raise ValueError("'timeout_s' must be in range 1..10")

    # Build (src, tgt) pairs — skip self-pings (always green, add no info).
    pairs = [(s, t) for s in targets for t in targets if s != t]

    matrix: Dict[str, Dict[str, Any]] = {ip: {} for ip in targets}
    broken: List[Dict[str, Any]] = []

    with concurrent.futures.ThreadPoolExecutor(max_workers=min(16, max(1, len(pairs)))) as ex:
        futures = {
            ex.submit(
                _probe_one,
                source=src, target=tgt,
                count=count, timeout_s=timeout_s,
                registry=registry, transport=transport, context=context,
            ): (src, tgt)
            for src, tgt in pairs
        }
        for fut in concurrent.futures.as_completed(futures):
            src, tgt = futures[fut]
            try:
                matrix[src][tgt] = fut.result()
            except Exception as e:
                matrix[src][tgt] = {"reachable": False, "error": str(e)}

    probe_count = len(pairs)
    reachable_count = sum(
        1 for src in targets for tgt in targets
        if src != tgt and matrix[src].get(tgt, {}).get("reachable")
    )
    for src in targets:
        for tgt in targets:
            if src == tgt:
                continue
            r = matrix[src].get(tgt, {})
            if not r.get("reachable"):
                broken.append({
                    "source": src, "target": tgt,
                    "loss_pct": r.get("loss_pct"),
                    "error": r.get("error"),
                })

    return {
        "summary": {
            "targets": targets,
            "probe_count": probe_count,
            "reachable_count": reachable_count,
            "reachable_pct": round(100.0 * reachable_count / probe_count, 1) if probe_count else None,
            "broken_pair_count": len(broken),
            "broken_pairs": broken,
            "source": "parallel ping_between fan-out",
        },
        "matrix": matrix,
    }
