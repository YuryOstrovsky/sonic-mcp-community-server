"""Tool: get_sflow_status

Retrieve sFlow sampling configuration and status.
Source: RESTCONF `openconfig-sampling-sflow:sampling/sflow`.

The openconfig-sampling-sflow module is among the 11 implemented on SONiC
community master. Returns `{config, state, collectors, interfaces}` per
the OpenConfig schema — missing subtrees are tolerated.
"""

from __future__ import annotations

from typing import Any, Dict, List

from sonic.tools._common import require_switch_ip


def get_sflow_status(
    *,
    inputs: Dict[str, Any],
    registry,
    transport,
    context: Dict[str, Any],
) -> Dict[str, Any]:
    switch_ip = require_switch_ip(inputs, context)

    r = transport.restconf.get_json(
        switch_ip, "/data/openconfig-sampling-sflow:sampling/sflow"
    )
    body = (r.get("payload") or {}).get("openconfig-sampling-sflow:sflow") or {}

    config = body.get("config") or {}
    state = body.get("state") or {}
    collectors_raw = (body.get("collectors") or {}).get("collector") or []
    interfaces_raw = (body.get("interfaces") or {}).get("interface") or []

    collectors: List[Dict[str, Any]] = []
    for c in collectors_raw:
        if not isinstance(c, dict):
            continue
        cstate = c.get("state") or c.get("config") or {}
        collectors.append({
            "address": cstate.get("address") or c.get("address"),
            "port": cstate.get("port"),
            "network_instance": cstate.get("network-instance"),
        })

    interfaces: List[Dict[str, Any]] = []
    for i in interfaces_raw:
        if not isinstance(i, dict):
            continue
        istate = i.get("state") or i.get("config") or {}
        interfaces.append({
            "name": istate.get("name") or i.get("name"),
            "enabled": istate.get("enabled"),
            "sampling_rate": istate.get("sampling-rate") or istate.get("ingress-sampling-rate"),
            "polling_interval": istate.get("polling-interval"),
        })

    enabled = state.get("enabled", config.get("enabled"))

    return {
        "summary": {
            "switch_ip": switch_ip,
            "enabled": bool(enabled),
            "sample_size": state.get("sample-size"),
            "polling_interval": state.get("polling-interval"),
            "agent_id_ipv4": state.get("agent-id-ipv4"),
            "agent_id_ipv6": state.get("agent-id-ipv6"),
            "collector_count": len(collectors),
            "interface_count": len(interfaces),
            "source": "restconf openconfig-sampling-sflow:sampling/sflow",
        },
        "config": config,
        "state": state,
        "collectors": collectors,
        "interfaces": interfaces,
    }
