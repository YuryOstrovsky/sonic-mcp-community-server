"""Tool: get_system_info_all

Parallel multi-device variant of get_system_info. Invokes the single-device
handler against every IP in `switch_ips` (or every device in the inventory
if omitted) and returns a merged envelope.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from sonic.tools._fanout import fan_out
from sonic.tools.system.get_system_info import get_system_info


def get_system_info_all(
    *,
    inputs: Dict[str, Any],
    registry,
    transport,
    context: Dict[str, Any],
) -> Dict[str, Any]:
    switch_ips: Optional[List[str]] = inputs.get("switch_ips")
    return fan_out(
        handler=get_system_info,
        inventory=transport.inventory,
        transport=transport,
        registry=registry,
        inputs={k: v for k, v in inputs.items() if k != "switch_ips"},
        context=context,
        switch_ips=switch_ips,
    )
