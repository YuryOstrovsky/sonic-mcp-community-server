"""Tool: get_lldp_neighbors_all — parallel fan-out of get_lldp_neighbors.

On SONiC VS this yields per-switch results all showing RX=0 (the documented
VS limitation). On real hardware, this is the fabric-wide topology view.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from sonic.tools._fanout import fan_out
from sonic.tools.lldp.get_lldp_neighbors import get_lldp_neighbors


def get_lldp_neighbors_all(
    *,
    inputs: Dict[str, Any],
    registry,
    transport,
    context: Dict[str, Any],
) -> Dict[str, Any]:
    switch_ips: Optional[List[str]] = inputs.get("switch_ips")
    return fan_out(
        handler=get_lldp_neighbors,
        inventory=transport.inventory,
        transport=transport,
        registry=registry,
        inputs={k: v for k, v in inputs.items() if k != "switch_ips"},
        context=context,
        switch_ips=switch_ips,
    )
