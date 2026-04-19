"""Tool: rollback_mutation

Given a mutation_id from the ledger, invoke the reverse operation to
undo it. Works for tools whose effect is expressible as a parameter
inversion:

  set_interface_admin_status   up ↔ down
  set_interface_mtu            → restore pre_state.mtu
  set_interface_description    → restore pre_state.description
  set_ip_interface             add ↔ remove (same iface + address)
  add_vlan ↔ remove_vlan       (same vlan_id)
  add_static_route ↔ remove_static_route (same prefix + nexthop)
  set_bgp_neighbor_admin       up ↔ down
  set_portchannel_member       add ↔ remove
  drain_switch ↔ undrain_switch

Non-reversible by design (this tool refuses them):
  clear_interface_counters     (counters can't be un-cleared)
  config_save                  (disk state change — not un-doable in place)
  get_mutation_history / reads

If the original mutation's `status` is "failed", rollback refuses — there
is nothing to undo.

Risk: MUTATION + requires_confirmation. The rollback itself is recorded
in the ledger so it can in turn be rolled back (within reason).
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from mcp_runtime.mutation_ledger import LEDGER


# ---------- Reversal planner ----------
# Each entry maps an original tool name to a function that returns
# (reverse_tool_name, reverse_inputs) for the given ledger entry, or
# raises ValueError if non-reversible.

def _rev_admin_status(e: Dict[str, Any]):
    inputs = e.get("inputs") or {}
    pre = (e.get("pre_state") or {}).get("admin_status")
    # Fall back to inverting the requested status if pre_state is missing.
    if pre and pre.upper() in {"UP", "DOWN"}:
        restore = "up" if pre.upper() == "UP" else "down"
    else:
        cur = str(inputs.get("admin_status", "")).lower()
        restore = "down" if cur == "up" else "up" if cur == "down" else None
        if restore is None:
            raise ValueError("can't determine previous admin_status")
    return "set_interface_admin_status", {
        "switch_ip": inputs.get("switch_ip"),
        "interface": inputs.get("interface"),
        "admin_status": restore,
    }


def _rev_mtu(e: Dict[str, Any]):
    inputs = e.get("inputs") or {}
    pre = (e.get("pre_state") or {}).get("mtu")
    if pre is None:
        raise ValueError("pre_state.mtu missing — can't restore original MTU")
    return "set_interface_mtu", {
        "switch_ip": inputs.get("switch_ip"),
        "interface": inputs.get("interface"),
        "mtu": int(pre),
    }


def _rev_description(e: Dict[str, Any]):
    inputs = e.get("inputs") or {}
    pre = (e.get("pre_state") or {}).get("description")
    # Description can legitimately be an empty string pre-change.
    if pre is None:
        pre = ""
    return "set_interface_description", {
        "switch_ip": inputs.get("switch_ip"),
        "interface": inputs.get("interface"),
        "description": pre,
    }


def _rev_ip_interface(e: Dict[str, Any]):
    inputs = e.get("inputs") or {}
    action = str(inputs.get("action", "")).lower()
    reverse = {"add": "remove", "remove": "add"}.get(action)
    if not reverse:
        raise ValueError("set_ip_interface entry missing action=add|remove")
    return "set_ip_interface", {
        "switch_ip": inputs.get("switch_ip"),
        "interface": inputs.get("interface"),
        "address": inputs.get("address"),
        "action": reverse,
    }


def _rev_add_vlan(e: Dict[str, Any]):
    inputs = e.get("inputs") or {}
    return "remove_vlan", {
        "switch_ip": inputs.get("switch_ip"),
        "vlan_id": inputs.get("vlan_id"),
    }


def _rev_remove_vlan(e: Dict[str, Any]):
    inputs = e.get("inputs") or {}
    return "add_vlan", {
        "switch_ip": inputs.get("switch_ip"),
        "vlan_id": inputs.get("vlan_id"),
    }


def _rev_add_route(e: Dict[str, Any]):
    inputs = e.get("inputs") or {}
    return "remove_static_route", {
        "switch_ip": inputs.get("switch_ip"),
        "prefix": inputs.get("prefix"),
        "nexthop": inputs.get("nexthop"),
    }


def _rev_remove_route(e: Dict[str, Any]):
    inputs = e.get("inputs") or {}
    nh = inputs.get("nexthop")
    if not nh:
        # Without the original nexthop we can't accurately re-add the route.
        raise ValueError(
            "remove_static_route entry is missing `nexthop` — rollback requires "
            "a specific next-hop (the original command removed all routes to the prefix)"
        )
    return "add_static_route", {
        "switch_ip": inputs.get("switch_ip"),
        "prefix": inputs.get("prefix"),
        "nexthop": nh,
    }


def _rev_bgp_admin(e: Dict[str, Any]):
    inputs = e.get("inputs") or {}
    pre = (e.get("pre_state") or {}).get("shutdown")
    if pre is not None:
        restore = "down" if pre else "up"
    else:
        cur = str(inputs.get("admin_status", "")).lower()
        restore = "down" if cur == "up" else "up" if cur == "down" else None
        if restore is None:
            raise ValueError("can't determine previous BGP admin_status")
    return "set_bgp_neighbor_admin", {
        "switch_ip": inputs.get("switch_ip"),
        "peer": inputs.get("peer"),
        "admin_status": restore,
    }


def _rev_portchannel_member(e: Dict[str, Any]):
    inputs = e.get("inputs") or {}
    action = str(inputs.get("action", "")).lower()
    reverse = {"add": "remove", "remove": "add"}.get(action)
    if not reverse:
        raise ValueError("set_portchannel_member entry missing action=add|remove")
    return "set_portchannel_member", {
        "switch_ip": inputs.get("switch_ip"),
        "portchannel": inputs.get("portchannel"),
        "interface": inputs.get("interface"),
        "action": reverse,
    }


def _rev_drain(e: Dict[str, Any]):
    return "undrain_switch", {"switch_ip": (e.get("inputs") or {}).get("switch_ip")}


def _rev_undrain(e: Dict[str, Any]):
    return "drain_switch", {"switch_ip": (e.get("inputs") or {}).get("switch_ip")}


_REVERSIBLE: Dict[str, Any] = {
    "set_interface_admin_status": _rev_admin_status,
    "set_interface_mtu":          _rev_mtu,
    "set_interface_description":  _rev_description,
    "set_ip_interface":           _rev_ip_interface,
    "add_vlan":                   _rev_add_vlan,
    "remove_vlan":                _rev_remove_vlan,
    "add_static_route":           _rev_add_route,
    "remove_static_route":        _rev_remove_route,
    "set_bgp_neighbor_admin":     _rev_bgp_admin,
    "set_portchannel_member":     _rev_portchannel_member,
    "drain_switch":               _rev_drain,
    "undrain_switch":             _rev_undrain,
}

_NOT_REVERSIBLE_REASONS: Dict[str, str] = {
    "clear_interface_counters": "counters can't be un-cleared — the pre-clear values aren't retrievable",
    "config_save":              "config_save writes disk state; rolling it back would require a separate snapshot/restore flow",
    "set_portchannel_member":   "",  # actually reversible, here just to show shape
}


def _find_entry(mutation_id: str) -> Optional[Dict[str, Any]]:
    for e in LEDGER.tail(n=5000):
        if e.get("mutation_id") == mutation_id:
            return e
    return None


def rollback_mutation(
    *,
    inputs: Dict[str, Any],
    registry,
    transport,
    context: Dict[str, Any],
) -> Dict[str, Any]:
    mid = str(inputs.get("mutation_id", "")).strip()
    if not mid:
        raise ValueError("'mutation_id' is required (find one in get_mutation_history or the Activity view)")

    entry = _find_entry(mid)
    if entry is None:
        raise ValueError(f"mutation_id {mid!r} not found in ledger")

    if entry.get("status") != "ok":
        raise ValueError(
            f"can't rollback a failed mutation (status={entry.get('status')}): "
            f"there is nothing to undo"
        )

    tool = entry.get("tool") or ""
    if tool not in _REVERSIBLE:
        reason = _NOT_REVERSIBLE_REASONS.get(tool) or (
            f"no known reversal for tool {tool!r}"
        )
        raise ValueError(f"{tool!r} is not reversible: {reason}")

    reverse_tool, reverse_inputs = _REVERSIBLE[tool](entry)
    # Invoke the reverse tool via the registry — get the right handler
    # and call it directly with the same transport/context.
    handler = registry.get_handler(reverse_tool)
    if handler is None:
        raise RuntimeError(f"reverse tool {reverse_tool!r} not registered — cannot roll back")

    result = handler(
        inputs=reverse_inputs,
        registry=registry,
        transport=transport,
        context=context or {},
    )

    return {
        "summary": {
            "original_mutation_id": mid,
            "original_tool": tool,
            "reverse_tool": reverse_tool,
            "reverse_inputs": reverse_inputs,
            "source": "mutation ledger replay (reverse planner)",
        },
        "original_entry": {
            "timestamp": entry.get("timestamp"),
            "tool": tool,
            "inputs": entry.get("inputs"),
            "pre_state": entry.get("pre_state"),
            "post_state": entry.get("post_state"),
        },
        "reverse_result": result,
    }
