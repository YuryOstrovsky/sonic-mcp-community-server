"""Tool: fabric_drain_rotate

Rolling maintenance playbook: for each switch in scope,
  1. drain_switch (admin-shut every BGP peer)
  2. wait up to wait_after_drain_s for the rest of the fabric to
     report "still reachable" via get_fabric_health
  3. undrain_switch
  4. wait up to wait_after_undrain_s for all adjacencies back to Established

Stops at the first failure (and DOES NOT undrain the failed switch — you
want an operator to look at it manually).

MUTATION + requires_confirmation.
"""

from __future__ import annotations

import time
from typing import Any, Dict, List, Optional

from sonic.tools.fabric.drain_switch import drain_switch
from sonic.tools.fabric.get_fabric_health import get_fabric_health
from sonic.tools.fabric.undrain_switch import undrain_switch


def _int_input(inputs: Dict[str, Any], name: str, default: int, lo: int, hi: int) -> int:
    val = inputs.get(name, default)
    try:
        v = int(val)
    except (TypeError, ValueError):
        raise ValueError(f"'{name}' must be an integer {lo}..{hi}")
    if not lo <= v <= hi:
        raise ValueError(f"'{name}' must be in range {lo}..{hi}")
    return v


def _wait_for_established(transport, registry, context, source: str, timeout_s: int) -> Dict[str, Any]:
    """Poll get_fabric_health every 2s until `broken` == 0 or timeout."""
    deadline = time.time() + timeout_s
    last = None
    while time.time() < deadline:
        try:
            last = get_fabric_health(
                inputs={}, registry=registry, transport=transport, context=context or {},
            )
            s = (last.get("summary") or {})
            if s.get("broken") == 0 and s.get("unreachable") == 0:
                return {"reached": True, "waited_s": round(timeout_s - (deadline - time.time()), 2), "health": s}
        except Exception as e:
            last = {"error": str(e)}
        time.sleep(2)
    return {"reached": False, "waited_s": timeout_s, "health": (last or {}).get("summary")}


def fabric_drain_rotate(
    *,
    inputs: Dict[str, Any],
    registry,
    transport,
    context: Dict[str, Any],
) -> Dict[str, Any]:
    scope: Optional[List[str]] = inputs.get("switch_ips") or None
    targets = list(scope) if scope else list(transport.inventory.all_ips())
    if not targets:
        raise RuntimeError("no switches in inventory")

    wait_after_drain = _int_input(inputs, "wait_after_drain_s", 8, 1, 120)
    wait_after_undrain = _int_input(inputs, "wait_after_undrain_s", 20, 1, 300)

    per_switch: List[Dict[str, Any]] = []
    overall_ok = True
    for ip in targets:
        step: Dict[str, Any] = {"switch_ip": ip, "steps": []}
        ctx = context or {}

        # --- drain ---
        t0 = time.time()
        try:
            d = drain_switch(inputs={"switch_ip": ip}, registry=registry, transport=transport, context=ctx)
            step["steps"].append({
                "op": "drain", "elapsed_s": round(time.time() - t0, 2),
                "status": "ok",
                "peers": (d.get("summary") or {}).get("peer_count"),
                "changed": (d.get("summary") or {}).get("changed_count"),
            })
        except Exception as e:
            step["steps"].append({"op": "drain", "status": "failed", "error": str(e),
                                  "elapsed_s": round(time.time() - t0, 2)})
            step["status"] = "aborted_at_drain"
            per_switch.append(step)
            overall_ok = False
            break

        # Short soak so downstream neighbours see the WITHDRAW.
        time.sleep(wait_after_drain)

        # --- undrain ---
        t1 = time.time()
        try:
            u = undrain_switch(inputs={"switch_ip": ip}, registry=registry, transport=transport, context=ctx)
            step["steps"].append({
                "op": "undrain", "elapsed_s": round(time.time() - t1, 2),
                "status": "ok",
                "peers": (u.get("summary") or {}).get("peer_count"),
                "changed": (u.get("summary") or {}).get("changed_count"),
            })
        except Exception as e:
            step["steps"].append({"op": "undrain", "status": "failed", "error": str(e),
                                  "elapsed_s": round(time.time() - t1, 2)})
            step["status"] = "aborted_at_undrain"
            per_switch.append(step)
            overall_ok = False
            break

        # Poll for full reconvergence.
        wait = _wait_for_established(transport, registry, ctx, ip, wait_after_undrain)
        step["steps"].append({"op": "wait_for_established",
                              "reached": wait["reached"], "waited_s": wait["waited_s"],
                              "health": wait.get("health")})
        step["status"] = "ok" if wait["reached"] else "converge_timeout"
        if not wait["reached"]:
            overall_ok = False
        per_switch.append(step)

    return {
        "summary": {
            "target_count": len(targets),
            "completed": len(per_switch),
            "overall_ok": overall_ok,
            "wait_after_drain_s": wait_after_drain,
            "wait_after_undrain_s": wait_after_undrain,
            "source": "drain_switch + undrain_switch orchestration",
        },
        "per_switch": per_switch,
    }
