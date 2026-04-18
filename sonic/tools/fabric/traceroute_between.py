"""Tool: traceroute_between

Multi-hop path discovery from one switch to any IP target.

Source: SSH `traceroute -n -w <tm> -q <q> -m <m> <target>`.

Each hop line parses to {hop, ips: [...], rtt_ms: [...]}. Non-responding
hops show up as {"hop": N, "ips": [], "rtt_ms": []}.

Why SAFE_READ: like ping, sends probes but makes no device-state change.
"""

from __future__ import annotations

import ipaddress
import re
import shlex
from typing import Any, Dict, List, Optional

from sonic.tools._common import require_switch_ip


# Sample output (util-linux traceroute -n):
#   1  10.0.0.1  0.300 ms  0.200 ms  0.250 ms
#   2  * * *
#   3  192.168.1.2  1.500 ms  1.400 ms  1.300 ms
_HOP_RE = re.compile(
    r"""
    ^\s*(\d+)\s+              # hop number
    (.+?)                      # rest (IPs + RTTs, or stars)
    \s*$
    """,
    re.X,
)
_IP_RE = re.compile(r"\b(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})\b")
_RTT_RE = re.compile(r"(\d+(?:\.\d+)?)\s*ms")

_HOSTNAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,252}$")


def _valid_target(s: str) -> bool:
    try:
        ipaddress.ip_address(s)
        return True
    except ValueError:
        pass
    return bool(_HOSTNAME_RE.match(s))


def _parse(stdout: str) -> List[Dict[str, Any]]:
    hops: List[Dict[str, Any]] = []
    for line in (stdout or "").splitlines():
        m = _HOP_RE.match(line)
        if not m:
            continue
        hop = int(m.group(1))
        rest = m.group(2)
        ips = _IP_RE.findall(rest)
        # De-duplicate while preserving order so we keep the "hop had ECMP
        # parity" info without the same IP three times.
        seen = set()
        uniq_ips: List[str] = []
        for ip in ips:
            if ip not in seen:
                seen.add(ip)
                uniq_ips.append(ip)
        rtts = [float(x) for x in _RTT_RE.findall(rest)]
        hops.append({
            "hop": hop,
            "ips": uniq_ips,
            "rtt_ms": rtts,
            "timeout": not uniq_ips,  # all stars
        })
    return hops


def traceroute_between(
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
    if not target or not _valid_target(target):
        raise ValueError("'target' must be an IPv4/IPv6 address or a DNS hostname")

    def _int_input(name: str, default: int, lo: int, hi: int) -> int:
        val = inputs.get(name, default)
        try:
            v = int(val)
        except (TypeError, ValueError):
            raise ValueError(f"'{name}' must be an integer {lo}..{hi}")
        if not lo <= v <= hi:
            raise ValueError(f"'{name}' must be in range {lo}..{hi}")
        return v

    max_hops = _int_input("max_hops", 8, 1, 30)
    queries = _int_input("queries", 1, 1, 3)
    wait_s = _int_input("wait_s", 2, 1, 5)

    cmd = (
        f"traceroute -n -m {max_hops} -q {queries} -w {wait_s} "
        f"{shlex.quote(target)}"
    )
    res = transport.ssh.run(source, cmd)
    # traceroute exits 0 even when the final hop isn't reached (it just keeps
    # printing stars) — don't raise on non-zero; rely on parsed output.
    hops = _parse(res.stdout or "")

    # Reached the target? The last non-timeout hop lists the target IP.
    last_ip: Optional[str] = None
    for h in reversed(hops):
        if h["ips"]:
            last_ip = h["ips"][0]
            break
    reached = bool(last_ip) and last_ip == target

    return {
        "summary": {
            "from": source,
            "to": target,
            "max_hops": max_hops,
            "hop_count": len(hops),
            "reached": reached,
            "last_hop_ip": last_ip,
            "source": "ssh traceroute -n",
        },
        "hops": hops,
        "stdout": res.stdout,
        "stderr": res.stderr,
        "exit_status": res.exit_status,
    }
