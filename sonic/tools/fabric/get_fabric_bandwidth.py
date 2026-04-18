"""Tool: get_fabric_bandwidth

Two-poll interface counter delta across the whole inventory. Reveals which
links are carrying traffic right now and at what rate.

Implementation:
  1. Fanout get_interfaces across every switch — snapshot 1 (t=0)
  2. Sleep `interval_s` seconds (default 5, range 2..30)
  3. Fanout get_interfaces again — snapshot 2 (t=interval_s)
  4. For each (switch, interface) compute bits/second in and out.
  5. If the interface exposes a port speed (bits/s), compute % utilization.

Inputs:
  switch_ips  : optional scope; default = full inventory
  interval_s  : optional, default 5
  min_bps     : optional, drop interfaces whose (tx+rx) bps is below this
                threshold; default 0 (include everything). Useful to see
                only active links in a large fabric.

Output:
  summary: {switch_count, interface_count, top_in: [...], top_out: [...]}
  interfaces: [{switch_ip, interface, speed_bps, rx_bps, tx_bps, rx_pct, tx_pct}, ...]
"""

from __future__ import annotations

import time
from typing import Any, Dict, List, Optional

from sonic.tools._fanout import fan_out
from sonic.tools.interfaces.get_interfaces import get_interfaces


# Which counter fields we need from openconfig-interfaces:interfaces:state:counters.
_COUNTER_FIELDS = (
    "in_octets", "out_octets", "in-octets", "out-octets",
)


def _extract_counters(
    iface_payload: Dict[str, Any],
) -> Dict[str, Dict[str, Any]]:
    """{interface_name: {in_bytes, out_bytes, speed_bps}}."""
    out: Dict[str, Dict[str, Any]] = {}
    for row in (iface_payload or {}).get("interfaces") or []:
        name = row.get("name")
        if not name:
            continue
        counters = row.get("counters") or {}
        in_b  = _first_present(counters, ("in_octets", "in-octets"))
        out_b = _first_present(counters, ("out_octets", "out-octets"))
        speed = row.get("speed_bps") or row.get("speed")
        try:
            in_b = int(in_b) if in_b is not None else None
        except (TypeError, ValueError):
            in_b = None
        try:
            out_b = int(out_b) if out_b is not None else None
        except (TypeError, ValueError):
            out_b = None
        speed_bps = _parse_speed(speed)
        out[name] = {"in_bytes": in_b, "out_bytes": out_b, "speed_bps": speed_bps}
    return out


def _first_present(d: Dict[str, Any], keys):
    for k in keys:
        if k in d and d[k] is not None:
            return d[k]
    return None


def _parse_speed(v: Any) -> Optional[int]:
    """Accept '100G', '100000000000', '40G', int bps, etc."""
    if v is None:
        return None
    if isinstance(v, int):
        return v
    s = str(v).strip().upper()
    if not s:
        return None
    mult = 1
    for suffix, m in (("G", 10**9), ("M", 10**6), ("K", 10**3)):
        if s.endswith(suffix):
            mult = m
            s = s[:-1]
            break
    try:
        return int(float(s) * mult)
    except ValueError:
        return None


def get_fabric_bandwidth(
    *,
    inputs: Dict[str, Any],
    registry,
    transport,
    context: Dict[str, Any],
) -> Dict[str, Any]:
    switch_ips = inputs.get("switch_ips") or None

    interval_raw = inputs.get("interval_s", 5)
    try:
        interval = int(interval_raw)
    except (TypeError, ValueError):
        raise ValueError("'interval_s' must be an integer 2..30")
    if not 2 <= interval <= 30:
        raise ValueError("'interval_s' must be in range 2..30")

    min_bps = int(inputs.get("min_bps") or 0)

    def _snapshot():
        return fan_out(
            handler=get_interfaces,
            inventory=transport.inventory,
            transport=transport, registry=registry,
            inputs={}, context=context or {}, switch_ips=switch_ips,
        )

    t0 = time.time()
    snap1 = _snapshot()
    time.sleep(interval)
    snap2 = _snapshot()
    elapsed = time.time() - t0

    rows: List[Dict[str, Any]] = []
    for ip, entry1 in (snap1.get("by_switch") or {}).items():
        entry2 = (snap2.get("by_switch") or {}).get(ip) or {}
        if entry1.get("status") != "ok" or entry2.get("status") != "ok":
            continue
        c1 = _extract_counters(entry1.get("payload") or {})
        c2 = _extract_counters(entry2.get("payload") or {})
        for name, a in c1.items():
            b = c2.get(name)
            if not b:
                continue
            if a.get("in_bytes") is None or b.get("in_bytes") is None:
                continue
            if a.get("out_bytes") is None or b.get("out_bytes") is None:
                continue
            d_in  = max(0, b["in_bytes"]  - a["in_bytes"])
            d_out = max(0, b["out_bytes"] - a["out_bytes"])
            rx_bps = int((d_in  * 8) / max(1, interval))
            tx_bps = int((d_out * 8) / max(1, interval))
            if (rx_bps + tx_bps) < min_bps:
                continue
            speed_bps = b.get("speed_bps") or a.get("speed_bps")
            rx_pct = round(100.0 * rx_bps / speed_bps, 2) if speed_bps else None
            tx_pct = round(100.0 * tx_bps / speed_bps, 2) if speed_bps else None
            rows.append({
                "switch_ip": ip,
                "interface": name,
                "rx_bps": rx_bps,
                "tx_bps": tx_bps,
                "speed_bps": speed_bps,
                "rx_pct": rx_pct,
                "tx_pct": tx_pct,
            })

    rows.sort(key=lambda r: (r["rx_bps"] + r["tx_bps"]), reverse=True)
    top_in  = sorted(rows, key=lambda r: r["rx_bps"], reverse=True)[:5]
    top_out = sorted(rows, key=lambda r: r["tx_bps"], reverse=True)[:5]

    switches_ok = sum(
        1 for ip in (snap1.get("by_switch") or {})
        if (snap1.get("by_switch") or {}).get(ip, {}).get("status") == "ok"
        and (snap2.get("by_switch") or {}).get(ip, {}).get("status") == "ok"
    )

    return {
        "summary": {
            "switch_count":    switches_ok,
            "interface_count": len(rows),
            "interval_s":      interval,
            "elapsed_s":       round(elapsed, 2),
            "top_in":          top_in,
            "top_out":         top_out,
            "source":          "two-poll interfaces counter delta",
        },
        "interfaces": rows,
    }
