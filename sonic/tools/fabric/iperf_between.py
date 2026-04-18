"""Tool: iperf_between

End-to-end throughput test using iperf3. Orchestrates:
  1. Start a one-shot iperf3 server on the target switch (`iperf3 -s -D -1 -p N`)
  2. Wait briefly for the listener to bind
  3. Run the iperf3 client on the source switch against the target's IP
  4. Parse JSON output for Gbps + retransmits + CPU
  5. The -1 flag makes the server exit after one connection — no cleanup needed

If iperf3 isn't installed on either switch, returns a structured result
with an install hint rather than raising — the widget surfaces this.

Inputs:
  source_switch_ip : required
  target           : required (IP or hostname the source can reach)
  port             : optional, default 5201
  duration_s       : optional, default 5, range 1..60
  parallel         : optional, default 1 (streams), range 1..8
  reverse          : optional boolean — target sends, source receives
"""

from __future__ import annotations

import json
import shlex
import time
from typing import Any, Dict, List, Optional

from sonic.tools._common import require_switch_ip


def _has_iperf3(transport, switch_ip: str) -> bool:
    r = transport.ssh.run(switch_ip, "command -v iperf3 >/dev/null 2>&1 && echo yes || echo no")
    return (r.stdout or "").strip() == "yes"


def iperf_between(
    *,
    inputs: Dict[str, Any],
    registry,
    transport,
    context: Dict[str, Any],
) -> Dict[str, Any]:
    source = require_switch_ip(
        {"switch_ip": inputs.get("source_switch_ip") or inputs.get("switch_ip")}, context,
    )
    target = str(inputs.get("target", "")).strip()
    if not target:
        raise ValueError("'target' is required (IP or hostname reachable from source)")

    port = int(inputs.get("port", 5201))
    if not 1 <= port <= 65535:
        raise ValueError("'port' must be 1..65535")
    duration = int(inputs.get("duration_s", 5))
    if not 1 <= duration <= 60:
        raise ValueError("'duration_s' must be 1..60")
    parallel = int(inputs.get("parallel", 1))
    if not 1 <= parallel <= 8:
        raise ValueError("'parallel' must be 1..8")
    reverse = bool(inputs.get("reverse", False))

    # Up-front environment check — much friendlier than a cryptic SSH error.
    missing: List[str] = []
    if not _has_iperf3(transport, source):
        missing.append(source)
    # The target may be an external host (not in our inventory) — skip the
    # iperf3-presence check there and trust the client to error out.
    try:
        target_is_switch = target in transport.inventory.all_ips() or any(
            d.name == target for d in transport.inventory.devices
        )
    except Exception:
        target_is_switch = False
    if target_is_switch:
        if not _has_iperf3(transport, transport.inventory.resolve(target).mgmt_ip):
            missing.append(transport.inventory.resolve(target).mgmt_ip)

    if missing:
        return {
            "summary": {
                "from": source, "to": target, "status": "iperf3_not_installed",
                "missing_on": missing,
                "install_hint": "Run on each listed switch: `sudo apt update && sudo apt install -y iperf3`",
                "source": "iperf3 orchestration",
            },
            "result": None,
            "stdout": "",
            "stderr": "",
        }

    # Start one-shot server on the target (only when target is a managed switch).
    if target_is_switch:
        target_ip = transport.inventory.resolve(target).mgmt_ip
        # -s server, -D daemon, -1 exit after one connection, -p port, -i 0 quiet.
        srv_cmd = f"iperf3 -s -D -1 -p {port} -i 0"
        srv = transport.ssh.run(target_ip, srv_cmd)
        if srv.exit_status != 0:
            # Server may already be running on the port; try a different port once.
            return {
                "summary": {
                    "from": source, "to": target, "status": "server_start_failed",
                    "error": f"iperf3 server failed to start on {target_ip}:{port} "
                             f"(exit={srv.exit_status}): {srv.stderr[:200]}",
                    "source": "iperf3 orchestration",
                },
                "result": None, "stdout": "", "stderr": srv.stderr,
            }
        # Give the listener a moment to bind before the client connects.
        time.sleep(0.6)

    # Client run (JSON output).
    flags = ["-J", "-c", shlex.quote(target), "-p", str(port), "-t", str(duration)]
    if parallel > 1:
        flags += ["-P", str(parallel)]
    if reverse:
        flags.append("-R")
    client_cmd = "iperf3 " + " ".join(flags)
    cli = transport.ssh.run(source, client_cmd)

    # iperf3 returns non-zero on connect failure. Parse what we got either way.
    parsed: Optional[Dict[str, Any]] = None
    if cli.stdout.strip():
        try:
            parsed = json.loads(cli.stdout)
        except json.JSONDecodeError:
            pass

    summary: Dict[str, Any] = {
        "from": source, "to": target, "port": port,
        "duration_s": duration, "parallel": parallel, "reverse": reverse,
        "status": "ok" if cli.exit_status == 0 and parsed else "failed",
        "source": "iperf3 orchestration",
    }
    if parsed:
        end = parsed.get("end") or {}
        sum_sent = end.get("sum_sent") or {}
        sum_recv = end.get("sum_received") or {}
        streams_end = end.get("streams") or []
        summary.update({
            "bps_sent":     sum_sent.get("bits_per_second"),
            "bps_received": sum_recv.get("bits_per_second"),
            "retransmits":  sum_sent.get("retransmits"),
            "bytes_sent":   sum_sent.get("bytes"),
            "bytes_received": sum_recv.get("bytes"),
            "stream_count": len(streams_end),
            "cpu_source_pct": ((parsed.get("end") or {}).get("cpu_utilization_percent") or {}).get("host_total"),
            "cpu_target_pct": ((parsed.get("end") or {}).get("cpu_utilization_percent") or {}).get("remote_total"),
        })
    if cli.exit_status != 0 and not parsed:
        summary["error"] = (cli.stderr or cli.stdout or "")[:300]

    return {
        "summary": summary,
        "result": parsed,
        "stdout": cli.stdout,
        "stderr": cli.stderr,
        "exit_status": cli.exit_status,
    }


