"""Phase 1 + Phase 2 end-to-end smoke test.

Assumes the MCP server is running (either via systemd 'sonic-mcp' or
'python api/run.py') on http://127.0.0.1:8000.

Hits /health, /ready, /tools, then exercises every registered tool
against both VMs in the default inventory.

Exit code:
    0 — all required checks passed
    1 — one or more checks failed (details printed)

Run with:
    python smoke-test/smoke_phase1.py
    python smoke-test/smoke_phase1.py --base http://127.0.0.1:8000
    python smoke-test/smoke_phase1.py --vm 10.46.11.50
"""

from __future__ import annotations

import argparse
import sys
import time
from typing import Any, Callable, Dict, List, Tuple

import requests


DEFAULT_BASE = "http://127.0.0.1:8000"
DEFAULT_VMS = ["10.46.11.50", "10.46.11.51"]


class Result:
    def __init__(self, name: str, ok: bool, detail: str = ""):
        self.name = name
        self.ok = ok
        self.detail = detail

    def __repr__(self) -> str:
        mark = "PASS" if self.ok else "FAIL"
        return f"[{mark}] {self.name} {self.detail}"


def _invoke(base: str, tool: str, inputs: Dict[str, Any]) -> Tuple[int, Dict[str, Any]]:
    r = requests.post(
        f"{base}/invoke",
        json={"tool": tool, "inputs": inputs},
        timeout=30,
    )
    try:
        body = r.json()
    except ValueError:
        body = {"_raw": r.text}
    return r.status_code, body


def _payload(body: Dict[str, Any]) -> Dict[str, Any]:
    return (body.get("result") or {}).get("payload") or {}


def _check(name: str, fn: Callable[[], Tuple[bool, str]]) -> Result:
    try:
        ok, detail = fn()
        return Result(name, ok, detail)
    except Exception as e:
        return Result(name, False, f"exception: {e!r}")


def run(base: str, vms: List[str]) -> List[Result]:
    results: List[Result] = []

    # ---------- server-side checks ----------

    def health() -> Tuple[bool, str]:
        r = requests.get(f"{base}/health", timeout=5)
        j = r.json()
        ok = r.status_code == 200 and j.get("status") == "ok"
        return ok, f"status={j.get('status')} service={j.get('service')}"

    results.append(_check("GET /health", health))

    def tools() -> Tuple[bool, str]:
        r = requests.get(f"{base}/tools", timeout=5)
        j = r.json()
        names = sorted(t["name"] for t in j)
        expected = {
            "get_interfaces",
            "get_ip_interfaces",
            "get_routes",
            "get_ipv6_routes",
            "get_bgp_summary",
            "get_lldp_neighbors",
            "get_system_info",
            "run_show_command",
        }
        ok = expected.issubset(set(names))
        return ok, f"have={len(names)} expected>={len(expected)}"

    results.append(_check("GET /tools", tools))

    def ready() -> Tuple[bool, str]:
        r = requests.get(f"{base}/ready", timeout=15)
        j = r.json()
        devices = (j.get("checks") or {}).get("devices", {})
        return r.status_code in (200, 503), (
            f"status={j.get('status')} devices={list(devices.keys())}"
        )

    results.append(_check("GET /ready", ready))

    # ---------- per-device tool checks ----------

    for ip in vms:

        def _sysinfo(ip=ip) -> Tuple[bool, str]:
            status, body = _invoke(base, "get_system_info", {"switch_ip": ip})
            if status != 200:
                return False, f"http={status} body={str(body)[:200]}"
            sys_ = _payload(body).get("system") or {}
            ok = bool(sys_.get("sonic_software_version")) and bool(sys_.get("platform"))
            return ok, f"version={sys_.get('sonic_software_version')} hwsku={sys_.get('hwsku')}"

        results.append(_check(f"get_system_info({ip})", _sysinfo))

        def _interfaces(ip=ip) -> Tuple[bool, str]:
            status, body = _invoke(base, "get_interfaces", {"switch_ip": ip})
            if status != 200:
                return False, f"http={status} body={str(body)[:200]}"
            summary = _payload(body).get("summary") or {}
            count = summary.get("count") or 0
            return bool(count), f"count={count}"

        results.append(_check(f"get_interfaces({ip})", _interfaces))

        def _ip_interfaces(ip=ip) -> Tuple[bool, str]:
            status, body = _invoke(base, "get_ip_interfaces", {"switch_ip": ip})
            if status != 200:
                return False, f"http={status} body={str(body)[:200]}"
            summary = _payload(body).get("summary") or {}
            count = summary.get("count") or 0
            return bool(count), f"count={count} v4={summary.get('ipv4_count')}"

        results.append(_check(f"get_ip_interfaces({ip})", _ip_interfaces))

        def _routes(ip=ip) -> Tuple[bool, str]:
            status, body = _invoke(base, "get_routes", {"switch_ip": ip})
            if status != 200:
                return False, f"http={status} body={str(body)[:200]}"
            summary = _payload(body).get("summary") or {}
            entries = summary.get("entry_count") or 0
            return bool(entries), f"entries={entries}"

        results.append(_check(f"get_routes({ip})", _routes))

        def _ipv6_routes(ip=ip) -> Tuple[bool, str]:
            status, body = _invoke(base, "get_ipv6_routes", {"switch_ip": ip})
            if status != 200:
                return False, f"http={status} body={str(body)[:200]}"
            summary = _payload(body).get("summary") or {}
            entries = summary.get("entry_count") or 0
            # A SONiC switch with L3 interfaces always has at least fe80::/64 routes
            return bool(entries), f"entries={entries}"

        results.append(_check(f"get_ipv6_routes({ip})", _ipv6_routes))

        def _bgp(ip=ip) -> Tuple[bool, str]:
            status, body = _invoke(base, "get_bgp_summary", {"switch_ip": ip})
            if status != 200:
                return False, f"http={status} body={str(body)[:200]}"
            summary = _payload(body).get("summary") or {}
            totals = summary.get("totals") or {}
            peers = totals.get("ipv4_peers") or 0
            # Tool always returns a payload shape; we pass when router_id is present OR peers > 0
            ipv4 = _payload(body).get("ipv4") or {}
            rid = ipv4.get("router_id")
            return bool(rid) or bool(peers), f"router_id={rid} v4_peers={peers}"

        results.append(_check(f"get_bgp_summary({ip})", _bgp))

        def _lldp(ip=ip) -> Tuple[bool, str]:
            status, body = _invoke(base, "get_lldp_neighbors", {"switch_ip": ip})
            if status != 200:
                return False, f"http={status} body={str(body)[:200]}"
            summary = _payload(body).get("summary") or {}
            totals = summary.get("stats_totals") or {}
            # Tool always returns a payload. We pass if stats_totals is present.
            return "tx" in totals, (
                f"neighbors={summary.get('neighbor_count')} "
                f"tx={totals.get('tx')} rx={totals.get('rx')}"
            )

        results.append(_check(f"get_lldp_neighbors({ip})", _lldp))

        def _run_show(ip=ip) -> Tuple[bool, str]:
            status, body = _invoke(
                base,
                "run_show_command",
                {"switch_ip": ip, "command": "show platform summary"},
            )
            if status != 200:
                return False, f"http={status} body={str(body)[:200]}"
            summary = _payload(body).get("summary") or {}
            ok = (
                summary.get("exit_status") == 0
                and summary.get("stdout_bytes", 0) > 0
            )
            return ok, (
                f"exit={summary.get('exit_status')} bytes={summary.get('stdout_bytes')}"
            )

        results.append(_check(f"run_show_command({ip})", _run_show))

    # ---------- negative test: run_show_command rejects unsafe input ----------

    def _reject_bad_cmd() -> Tuple[bool, str]:
        status, body = _invoke(
            base,
            "run_show_command",
            {"switch_ip": vms[0], "command": "rm -rf /"},
        )
        # Server should return 500 (handler raised ValueError) or 422 — either is fine
        return status in (400, 422, 500), f"http={status}"

    results.append(_check("run_show_command rejects 'rm -rf /'", _reject_bad_cmd))

    return results


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default=DEFAULT_BASE)
    ap.add_argument(
        "--vm",
        action="append",
        dest="vms",
        default=None,
        help="Switch IP to test; may be repeated. Defaults to VM1+VM2.",
    )
    args = ap.parse_args()

    vms = args.vms if args.vms else DEFAULT_VMS

    print("== SONiC MCP smoke test ==")
    print(f"   base: {args.base}")
    print(f"   vms:  {vms}")
    print()

    start = time.time()
    results = run(args.base, vms)
    duration = time.time() - start

    print()
    for r in results:
        print(r)
    print()

    passed = sum(1 for r in results if r.ok)
    total = len(results)
    print(f"== {passed}/{total} checks passed in {duration:.2f}s ==")

    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(main())
