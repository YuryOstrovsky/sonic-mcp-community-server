"""Tool: get_fabric_config_diff

Compare a whitelist of meaningful CONFIG_DB tables between two switches.
SONiC CONFIG_DB has 100+ tables, most of which carry runtime noise (mgmt
IPs, hostnames, timers). This tool restricts the diff to tables operators
actually care about for fabric consistency:

  VLAN, VLAN_MEMBER, VLAN_INTERFACE
  PORTCHANNEL, PORTCHANNEL_MEMBER, PORTCHANNEL_INTERFACE
  INTERFACE, LOOPBACK_INTERFACE
  BGP_NEIGHBOR
  DEVICE_METADATA (useful for hwsku / type / mac diffs)

Output:
  summary: {left, right, tables_checked, tables_differ, total_keys_differ}
  tables:  [{ name, left_only: [...], right_only: [...], differing: [{key, left, right}] }]

Inputs:
  left_switch_ip  : required
  right_switch_ip : required
  tables          : optional list — restrict to these tables only
"""

from __future__ import annotations

import json
import shlex
from typing import Any, Dict, List, Optional, Tuple


_DEFAULT_TABLES = [
    "DEVICE_METADATA",
    "VLAN", "VLAN_MEMBER", "VLAN_INTERFACE",
    "PORTCHANNEL", "PORTCHANNEL_MEMBER", "PORTCHANNEL_INTERFACE",
    "INTERFACE", "LOOPBACK_INTERFACE",
    "BGP_NEIGHBOR",
    "MGMT_INTERFACE",
]


def _dump_table(transport, switch_ip: str, table: str) -> Dict[str, Dict[str, Any]]:
    """Pull one CONFIG_DB table via sonic-db-cli; return {key: {field: value}}."""
    # KEYS returns full-qualified keys like "VLAN|Vlan100"
    keys_cmd = f'sudo sonic-db-cli CONFIG_DB KEYS {shlex.quote(f"{table}|*")}'
    res = transport.ssh.run(switch_ip, keys_cmd)
    if res.exit_status != 0:
        return {}
    out: Dict[str, Dict[str, Any]] = {}
    for raw_line in (res.stdout or "").splitlines():
        line = raw_line.strip()
        if not line or not line.startswith(f"{table}|"):
            continue
        # HGETALL returns an alternating flat list of field/value pairs
        hget_cmd = f'sudo sonic-db-cli CONFIG_DB HGETALL {shlex.quote(line)}'
        hres = transport.ssh.run(switch_ip, hget_cmd)
        if hres.exit_status != 0:
            continue
        # sonic-db-cli's default output is a Python-style dict literal; try
        # JSON first (newer builds), fall back to ast.literal_eval.
        parsed: Dict[str, Any] = {}
        txt = (hres.stdout or "").strip()
        if txt:
            try:
                parsed = json.loads(txt)
            except Exception:
                try:
                    import ast
                    parsed = ast.literal_eval(txt)
                    if not isinstance(parsed, dict):
                        parsed = {}
                except Exception:
                    parsed = {}
        # Strip the "TABLE|" prefix so diffs read cleanly.
        short_key = line.split("|", 1)[1] if "|" in line else line
        out[short_key] = parsed
    return out


def _diff_one(
    left: Dict[str, Dict[str, Any]],
    right: Dict[str, Dict[str, Any]],
) -> Tuple[List[str], List[str], List[Dict[str, Any]]]:
    left_only = sorted(set(left.keys()) - set(right.keys()))
    right_only = sorted(set(right.keys()) - set(left.keys()))
    differing: List[Dict[str, Any]] = []
    for k in sorted(set(left.keys()) & set(right.keys())):
        l = left[k]
        r = right[k]
        # Collapse field-level diffs
        all_fields = sorted(set(l.keys()) | set(r.keys()))
        field_diffs = [
            {"field": f, "left": l.get(f), "right": r.get(f)}
            for f in all_fields
            if l.get(f) != r.get(f)
        ]
        if field_diffs:
            differing.append({"key": k, "fields": field_diffs})
    return left_only, right_only, differing


def get_fabric_config_diff(
    *,
    inputs: Dict[str, Any],
    registry,
    transport,
    context: Dict[str, Any],
) -> Dict[str, Any]:
    left = str(inputs.get("left_switch_ip", "")).strip()
    right = str(inputs.get("right_switch_ip", "")).strip()
    if not left or not right:
        raise ValueError("both 'left_switch_ip' and 'right_switch_ip' are required")
    if left == right:
        raise ValueError("'left_switch_ip' and 'right_switch_ip' must differ")

    tables_raw: Optional[List[str]] = inputs.get("tables")
    tables = tables_raw if tables_raw else list(_DEFAULT_TABLES)

    per_table: List[Dict[str, Any]] = []
    total_diffs = 0
    tables_differ = 0

    for t in tables:
        l = _dump_table(transport, left, t)
        r = _dump_table(transport, right, t)
        l_only, r_only, diffs = _diff_one(l, r)
        entry = {
            "name": t,
            "left_only": l_only,
            "right_only": r_only,
            "differing": diffs,
            "left_count": len(l),
            "right_count": len(r),
        }
        per_table.append(entry)
        t_diffs = len(l_only) + len(r_only) + len(diffs)
        total_diffs += t_diffs
        if t_diffs:
            tables_differ += 1

    return {
        "summary": {
            "left": left,
            "right": right,
            "tables_checked": len(tables),
            "tables_differ": tables_differ,
            "total_keys_differ": total_diffs,
            "source": "sonic-db-cli CONFIG_DB (scoped table whitelist)",
        },
        "tables": per_table,
    }
