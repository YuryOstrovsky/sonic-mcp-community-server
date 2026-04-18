"""Parallel fan-out primitive for multi-device tool variants.

Takes a single-switch handler + a list of switch IPs, runs the handler
against each IP in a thread pool, and returns a merged envelope:
    {
        "summary": {
            "target_count": N,
            "ok_count": K,
            "error_count": N-K,
            "targets": [ip1, ip2, ...],
            "elapsed_ms": int,
        },
        "by_switch": {
            ip1: {"status": "ok", "payload": {...}, "duration_ms": ...},
            ip2: {"status": "error", "error": "connection refused", ...},
            ...
        }
    }

Handlers continue to take a single `switch_ip` in `inputs` — fan-out is
purely a transport-level concern. A per-host failure does NOT abort the
other queries.
"""

from __future__ import annotations

import concurrent.futures
import time
from typing import Any, Callable, Dict, List, Optional


def fan_out(
    *,
    handler: Callable[..., Dict[str, Any]],
    inventory,
    transport,
    registry,
    inputs: Dict[str, Any],
    context: Dict[str, Any],
    switch_ips: Optional[List[str]] = None,
    max_workers: int = 8,
    per_host_timeout_s: int = 60,
) -> Dict[str, Any]:
    targets: List[str] = list(switch_ips) if switch_ips else inventory.all_ips()
    if not targets:
        return {
            "summary": {
                "target_count": 0,
                "ok_count": 0,
                "error_count": 0,
                "targets": [],
                "elapsed_ms": 0,
            },
            "by_switch": {},
        }

    def _invoke_one(ip: str) -> Dict[str, Any]:
        call_inputs = dict(inputs)
        call_inputs["switch_ip"] = ip
        call_ctx = dict(context) if context else {}
        call_ctx["switch_ip"] = ip
        started = time.time()
        try:
            payload = handler(
                inputs=call_inputs,
                registry=registry,
                transport=transport,
                context=call_ctx,
            )
            return {
                "status": "ok",
                "payload": payload,
                "duration_ms": int((time.time() - started) * 1000),
            }
        except Exception as e:
            return {
                "status": "error",
                "error": str(e),
                "error_type": type(e).__name__,
                "duration_ms": int((time.time() - started) * 1000),
            }

    started_overall = time.time()
    results: Dict[str, Dict[str, Any]] = {}
    with concurrent.futures.ThreadPoolExecutor(
        max_workers=min(max_workers, len(targets))
    ) as ex:
        futures = {ex.submit(_invoke_one, ip): ip for ip in targets}
        for fut in concurrent.futures.as_completed(futures, timeout=per_host_timeout_s * 2):
            ip = futures[fut]
            try:
                results[ip] = fut.result(timeout=per_host_timeout_s)
            except Exception as e:
                results[ip] = {
                    "status": "error",
                    "error": f"future failed: {e}",
                    "error_type": type(e).__name__,
                    "duration_ms": None,
                }

    ok = sum(1 for r in results.values() if r.get("status") == "ok")
    return {
        "summary": {
            "target_count": len(targets),
            "ok_count": ok,
            "error_count": len(targets) - ok,
            "targets": targets,
            "elapsed_ms": int((time.time() - started_overall) * 1000),
        },
        "by_switch": results,
    }
