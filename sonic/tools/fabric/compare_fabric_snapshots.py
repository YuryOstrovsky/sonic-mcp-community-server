"""Tool: compare_fabric_snapshots

Diff two saved snapshots (produced by save_fabric_snapshot) without
touching the live fabric. Works per-switch: for each switch present in
BOTH snapshots, compute a structural diff of its config_db.json; report
keys only-in-left / only-in-right / keys present on both with differing
field values.

Inputs:
  left_name  : required — snapshot label
  right_name : required — snapshot label
  switch_ips : optional subset; default = the intersection of both snapshots

Output shape mirrors get_fabric_config_diff so the existing
FabricConfigDiffWidget renders it unchanged.

SAFE_READ — local filesystem reads only.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


_SNAPSHOT_ROOT_ENV = "SONIC_SNAPSHOT_ROOT"
_DEFAULT_ROOT = Path("snapshots")

# Table whitelist intentionally mirrors get_fabric_config_diff so users
# see consistent results whether they diff live↔live or saved↔saved.
_DEFAULT_TABLES = [
    "DEVICE_METADATA",
    "VLAN", "VLAN_MEMBER", "VLAN_INTERFACE",
    "PORTCHANNEL", "PORTCHANNEL_MEMBER", "PORTCHANNEL_INTERFACE",
    "INTERFACE", "LOOPBACK_INTERFACE",
    "BGP_NEIGHBOR",
    "MGMT_INTERFACE",
]


def _snapshot_root() -> Path:
    env = os.environ.get(_SNAPSHOT_ROOT_ENV)
    return Path(env) if env else _DEFAULT_ROOT


def _load_switch_config(snapshot_dir: Path, ip: str) -> Dict[str, Any]:
    p = snapshot_dir / f"{ip}.json"
    if not p.exists():
        raise RuntimeError(f"snapshot {snapshot_dir.name} has no file for {ip}")
    return json.loads(p.read_text(encoding="utf-8"))


def _extract_table(config: Dict[str, Any], table: str) -> Dict[str, Dict[str, Any]]:
    """SONiC config_db.json is {table: {key: {field: value}}}. Flatten the
    requested table to {key: {field: value}} for easy diffing."""
    body = config.get(table) or {}
    if not isinstance(body, dict):
        return {}
    out: Dict[str, Dict[str, Any]] = {}
    for k, v in body.items():
        if isinstance(v, dict):
            out[k] = v
    return out


def _diff_one(
    left: Dict[str, Dict[str, Any]],
    right: Dict[str, Dict[str, Any]],
) -> Tuple[List[str], List[str], List[Dict[str, Any]]]:
    left_only = sorted(set(left.keys()) - set(right.keys()))
    right_only = sorted(set(right.keys()) - set(left.keys()))
    differing: List[Dict[str, Any]] = []
    for k in sorted(set(left.keys()) & set(right.keys())):
        lv, rv = left[k], right[k]
        all_fields = sorted(set(lv.keys()) | set(rv.keys()))
        field_diffs = [
            {"field": f, "left": lv.get(f), "right": rv.get(f)}
            for f in all_fields if lv.get(f) != rv.get(f)
        ]
        if field_diffs:
            differing.append({"key": k, "fields": field_diffs})
    return left_only, right_only, differing


def compare_fabric_snapshots(
    *,
    inputs: Dict[str, Any],
    registry,
    transport,
    context: Dict[str, Any],
) -> Dict[str, Any]:
    left_name = str(inputs.get("left_name") or "").strip()
    right_name = str(inputs.get("right_name") or "").strip()
    if not left_name or not right_name:
        raise ValueError("both 'left_name' and 'right_name' are required")
    if left_name == right_name:
        raise ValueError("left and right snapshot names must differ")

    root = _snapshot_root()
    left_dir = root / left_name
    right_dir = root / right_name
    if not (left_dir / "snapshot.json").exists():
        raise ValueError(f"snapshot {left_name!r} not found at {left_dir}")
    if not (right_dir / "snapshot.json").exists():
        raise ValueError(f"snapshot {right_name!r} not found at {right_dir}")

    left_meta = json.loads((left_dir / "snapshot.json").read_text(encoding="utf-8"))
    right_meta = json.loads((right_dir / "snapshot.json").read_text(encoding="utf-8"))

    left_switches = set(left_meta.get("switches") or [])
    right_switches = set(right_meta.get("switches") or [])
    scope: Optional[List[str]] = inputs.get("switch_ips")
    if scope:
        targets = [ip for ip in scope if ip in left_switches and ip in right_switches]
    else:
        targets = sorted(left_switches & right_switches)

    tables = inputs.get("tables") or list(_DEFAULT_TABLES)

    per_switch: List[Dict[str, Any]] = []
    total_diffs = 0
    switches_differ = 0

    for ip in targets:
        try:
            left_cfg = _load_switch_config(left_dir, ip)
            right_cfg = _load_switch_config(right_dir, ip)
        except Exception as e:
            per_switch.append({"switch_ip": ip, "error": str(e), "tables": []})
            continue

        per_table = []
        switch_total = 0
        for t in tables:
            lv = _extract_table(left_cfg, t)
            rv = _extract_table(right_cfg, t)
            l_only, r_only, diffs = _diff_one(lv, rv)
            n = len(l_only) + len(r_only) + len(diffs)
            switch_total += n
            per_table.append({
                "name": t,
                "left_only": l_only,
                "right_only": r_only,
                "differing": diffs,
                "left_count": len(lv),
                "right_count": len(rv),
            })
        if switch_total:
            switches_differ += 1
        total_diffs += switch_total
        per_switch.append({
            "switch_ip": ip,
            "tables": per_table,
            "total_diffs": switch_total,
        })

    return {
        "summary": {
            "left": left_name,
            "right": right_name,
            "left_timestamp":  left_meta.get("timestamp"),
            "right_timestamp": right_meta.get("timestamp"),
            "switches_compared": len(targets),
            "switches_differ": switches_differ,
            "total_keys_differ": total_diffs,
            "tables_checked": len(tables),
            "source": "snapshot file diff (local fs, scoped whitelist)",
        },
        "per_switch": per_switch,
    }
