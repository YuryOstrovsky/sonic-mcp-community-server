"""Tool: get_platform_detail

Combined platform health: summary + fans + temperatures + PSUs.
Source: SSH `show platform {summary,fan,temperature,psustatus}`.

On SONiC VS, the hardware sensor commands return 'Fan Not detected' /
'Thermal Not detected' / 'PSU not detected' — the tool reports that
explicitly rather than returning empty silently.
"""

from __future__ import annotations

from typing import Any, Dict, List

from sonic.tools._common import require_switch_ip
from sonic.tools._parse import parse_box_table, parse_fixed_width_table, parse_kv_lines


_NOT_DETECTED_MARKERS = ("not detected",)


def _run(transport, switch_ip: str, cmd: str) -> str:
    res = transport.ssh.run(switch_ip, cmd)
    if res.exit_status != 0:
        return ""
    return res.stdout or ""


def _is_not_detected(text: str) -> bool:
    t = (text or "").lower()
    return any(m in t for m in _NOT_DETECTED_MARKERS)


def _try_tables(text: str) -> List[Dict[str, Any]]:
    """Try box-drawing first, then fixed-width fall-back."""
    rows = parse_box_table(text)
    if rows:
        return rows
    return parse_fixed_width_table(text)


def get_platform_detail(
    *,
    inputs: Dict[str, Any],
    registry,
    transport,
    context: Dict[str, Any],
) -> Dict[str, Any]:
    switch_ip = require_switch_ip(inputs, context)

    # --- summary (key/value lines) ---
    summary_text = _run(transport, switch_ip, "show platform summary")
    summary = parse_kv_lines(summary_text)

    # --- fans ---
    fan_text = _run(transport, switch_ip, "show platform fan")
    if _is_not_detected(fan_text):
        fans: List[Dict[str, Any]] = []
        fan_note = "not detected (virtual platform)"
    else:
        fans = _try_tables(fan_text)
        fan_note = None

    # --- temperatures ---
    temp_text = _run(transport, switch_ip, "show platform temperature")
    if _is_not_detected(temp_text):
        temps: List[Dict[str, Any]] = []
        temp_note = "not detected (virtual platform)"
    else:
        temps = _try_tables(temp_text)
        temp_note = None

    # --- PSUs ---
    psu_text = _run(transport, switch_ip, "show platform psustatus")
    if _is_not_detected(psu_text):
        psus: List[Dict[str, Any]] = []
        psu_note = "not detected (virtual platform)"
    else:
        psus = _try_tables(psu_text)
        psu_note = None

    is_virtual = bool(fan_note and temp_note and psu_note)

    return {
        "summary": {
            "switch_ip": switch_ip,
            "platform": summary.get("platform"),
            "hwsku": summary.get("hwsku"),
            "asic": summary.get("asic"),
            "asic_count": summary.get("asic_count"),
            "serial_number": summary.get("serial_number"),
            "model_number": summary.get("model_number"),
            "hardware_revision": summary.get("hardware_revision"),
            "virtual_platform": is_virtual,
            "source": "ssh show platform {summary,fan,temperature,psustatus}",
        },
        "fans":         {"count": len(fans),  "note": fan_note,  "items": fans},
        "temperatures": {"count": len(temps), "note": temp_note, "items": temps},
        "psus":         {"count": len(psus),  "note": psu_note,  "items": psus},
    }
