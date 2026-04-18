"""Tool: get_mac_table_all — parallel fan-out of get_mac_table."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from sonic.tools._fanout import fan_out
from sonic.tools.l2.get_mac_table import get_mac_table


def get_mac_table_all(
    *,
    inputs: Dict[str, Any],
    registry,
    transport,
    context: Dict[str, Any],
) -> Dict[str, Any]:
    switch_ips: Optional[List[str]] = inputs.get("switch_ips")
    return fan_out(
        handler=get_mac_table,
        inventory=transport.inventory,
        transport=transport,
        registry=registry,
        inputs={k: v for k, v in inputs.items() if k != "switch_ips"},
        context=context,
        switch_ips=switch_ips,
    )
