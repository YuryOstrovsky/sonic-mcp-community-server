"""Tool: ping_between

ICMP reachability test from one SONiC switch to any IP target.

Source: SSH `ping -c <count> -W <timeout> [-I <source_if>] <target>`.

Inputs:
  source_switch_ip : required (the switch we SSH into and run ping from)
  target           : required (any IPv4 address or hostname)
  count            : optional, default 3, 1..10
  timeout_s        : optional, default 2, 1..10 (per-packet W timeout)
  source_interface : optional, e.g. 'Loopback0' or 'Ethernet0'

Output:
  summary: {from, to, transmitted, received, loss_pct, rtt_avg_ms, reachable}
  stdout:  raw ping output

Note: this is a SAFE_READ tool by design — it sends ICMP but doesn't
change any device state. Named `ping_between` because the practical use
case is "can VM1 reach VM2 over the fabric?".
"""

from __future__ import annotations

import ipaddress
import re
import shlex
from typing import Any, Dict, Optional

from sonic.tools._common import require_switch_ip


# ping summary line is robust across util-linux and busybox:
#   "3 packets transmitted, 3 received, 0% packet loss, time 2003ms"
_LOSS_RE = re.compile(
    r"(\d+)\s+packets? transmitted,\s+(\d+)\s+(?:packets?\s+)?received,"
    r"\s+([\d.]+)%\s+packet\s+loss"
)
# rtt min/avg/max/mdev = 0.100/0.250/0.400/0.100 ms
_RTT_RE = re.compile(
    r"(?:rtt|round-trip)\s+min/avg/max(?:/m?dev)?\s*=\s*"
    r"([\d.]+)/([\d.]+)/([\d.]+)(?:/([\d.]+))?\s*ms"
)
_HOSTNAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,252}$")
_IFACE_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_./-]{0,31}$")


def _valid_target(s: str) -> bool:
    try:
        ipaddress.ip_address(s)
        return True
    except ValueError:
        pass
    return bool(_HOSTNAME_RE.match(s))


def _parse(stdout: str) -> Dict[str, Any]:
    tx: Optional[int] = None
    rx: Optional[int] = None
    loss: Optional[float] = None
    rtt_min: Optional[float] = None
    rtt_avg: Optional[float] = None
    rtt_max: Optional[float] = None
    m = _LOSS_RE.search(stdout)
    if m:
        tx = int(m.group(1))
        rx = int(m.group(2))
        loss = float(m.group(3))
    m2 = _RTT_RE.search(stdout)
    if m2:
        rtt_min = float(m2.group(1))
        rtt_avg = float(m2.group(2))
        rtt_max = float(m2.group(3))
    return {
        "transmitted": tx,
        "received": rx,
        "loss_pct": loss,
        "rtt_min_ms": rtt_min,
        "rtt_avg_ms": rtt_avg,
        "rtt_max_ms": rtt_max,
    }


def ping_between(
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

    count_raw = inputs.get("count", 3)
    try:
        count = int(count_raw)
    except (TypeError, ValueError):
        raise ValueError("'count' must be an integer 1..10")
    if not 1 <= count <= 10:
        raise ValueError("'count' must be in range 1..10")

    timeout_raw = inputs.get("timeout_s", 2)
    try:
        timeout_s = int(timeout_raw)
    except (TypeError, ValueError):
        raise ValueError("'timeout_s' must be an integer 1..10")
    if not 1 <= timeout_s <= 10:
        raise ValueError("'timeout_s' must be in range 1..10")

    source_if = str(inputs.get("source_interface", "") or "").strip()
    if source_if and not _IFACE_RE.match(source_if):
        raise ValueError("'source_interface' must look like 'Ethernet0' or 'Loopback0'")

    parts = ["ping", "-c", str(count), "-W", str(timeout_s)]
    if source_if:
        parts += ["-I", source_if]
    parts.append(shlex.quote(target))
    cmd = " ".join(parts)

    res = transport.ssh.run(source, cmd)
    # ping exits non-zero on packet loss or name-resolution failure. Don't
    # raise — the parsed summary tells the user what happened.
    parsed = _parse(res.stdout or "")

    reachable = parsed.get("loss_pct") is not None and parsed["loss_pct"] < 100.0
    return {
        "summary": {
            "from": source,
            "to": target,
            "source_interface": source_if or None,
            "transmitted": parsed.get("transmitted"),
            "received": parsed.get("received"),
            "loss_pct": parsed.get("loss_pct"),
            "rtt_avg_ms": parsed.get("rtt_avg_ms"),
            "reachable": reachable,
            "source": "ssh ping",
        },
        "ping": parsed,
        "stdout": res.stdout,
        "stderr": res.stderr,
        "exit_status": res.exit_status,
    }
