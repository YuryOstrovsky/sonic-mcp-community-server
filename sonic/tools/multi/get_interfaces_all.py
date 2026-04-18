"""Tool: get_interfaces_all — parallel fan-out of get_interfaces."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from sonic.tools._fanout import fan_out
from sonic.tools.interfaces.get_interfaces import get_interfaces


def get_interfaces_all(
    *,
    inputs: Dict[str, Any],
    registry,
    transport,
    context: Dict[str, Any],
) -> Dict[str, Any]:
    switch_ips: Optional[List[str]] = inputs.get("switch_ips")
    return fan_out(
        handler=get_interfaces,
        inventory=transport.inventory,
        transport=transport,
        registry=registry,
        inputs={k: v for k, v in inputs.items() if k != "switch_ips"},
        context=context,
        switch_ips=switch_ips,
    )
