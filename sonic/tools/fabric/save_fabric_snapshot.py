"""Tool: save_fabric_snapshot

Snapshot the full /etc/sonic/config_db.json from every switch in the
inventory (or a supplied subset) into the server's local
snapshots/<name>/<switch_ip>.json directory. A companion metadata file
(snapshot.json) records the snapshot timestamp and per-switch sizes.

Output is plain JSON — easy to diff, easy to ship, easy to hand-edit.

Inputs:
  name        : optional snapshot label (default = ISO timestamp)
  switch_ips  : optional scope; default = full inventory
  note        : optional free-text note saved in the metadata

SAFE_READ — reads only. `restore_fabric_snapshot` is the destructive twin.
"""

from __future__ import annotations

import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from sonic.tools._common import require_switch_ip  # noqa: F401  (side effect: validates imports)


_SNAPSHOT_ROOT_ENV = "SONIC_SNAPSHOT_ROOT"
_DEFAULT_ROOT = Path("snapshots")

# Reject anything that could escape the snapshot directory.
_SAFE_NAME_RE = re.compile(r"^[A-Za-z0-9_.\-]+$")


def _snapshot_root() -> Path:
    env = os.environ.get(_SNAPSHOT_ROOT_ENV)
    return Path(env) if env else _DEFAULT_ROOT


def _ts_label() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _validate_name(name: str) -> str:
    if not _SAFE_NAME_RE.match(name):
        raise ValueError(
            "'name' may only contain letters, digits, '_', '.', '-' "
            "(no slashes, no traversal)"
        )
    return name


def _pull_config_db(transport, switch_ip: str) -> str:
    """Return the raw JSON text of /etc/sonic/config_db.json from the switch."""
    res = transport.ssh.run(
        switch_ip,
        "sudo cat /etc/sonic/config_db.json",
    )
    if res.exit_status != 0:
        raise RuntimeError(
            f"failed to read config_db.json on {switch_ip}: "
            f"exit={res.exit_status} stderr={res.stderr[:200]}"
        )
    text = (res.stdout or "").strip()
    if not text:
        raise RuntimeError(f"config_db.json on {switch_ip} was empty")
    # Validate — better to fail here than when someone tries to restore.
    try:
        json.loads(text)
    except json.JSONDecodeError as e:
        raise RuntimeError(f"config_db.json on {switch_ip} is not valid JSON: {e}")
    return text


def save_fabric_snapshot(
    *,
    inputs: Dict[str, Any],
    registry,
    transport,
    context: Dict[str, Any],
) -> Dict[str, Any]:
    raw_name = str(inputs.get("name") or "").strip() or _ts_label()
    name = _validate_name(raw_name)
    note = str(inputs.get("note") or "").strip() or None
    scope: Optional[List[str]] = inputs.get("switch_ips") or None
    targets = list(scope) if scope else list(transport.inventory.all_ips())
    if not targets:
        raise RuntimeError("no switches in inventory to snapshot")

    root = _snapshot_root() / name
    root.mkdir(parents=True, exist_ok=True)

    per_switch: Dict[str, Any] = {}
    ok_count = 0
    for ip in targets:
        try:
            text = _pull_config_db(transport, ip)
            out_path = root / f"{ip}.json"
            out_path.write_text(text, encoding="utf-8")
            per_switch[ip] = {
                "status": "ok",
                "path": str(out_path),
                "size_bytes": out_path.stat().st_size,
            }
            ok_count += 1
        except Exception as e:
            per_switch[ip] = {"status": "error", "error": str(e)}

    # Metadata — useful for listing + auditing.
    metadata = {
        "name": name,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "switches": targets,
        "ok_count": ok_count,
        "error_count": len(targets) - ok_count,
        "note": note,
    }
    (root / "snapshot.json").write_text(
        json.dumps(metadata, indent=2) + "\n", encoding="utf-8",
    )

    return {
        "summary": {
            "name": name,
            "path": str(root),
            "switch_count": len(targets),
            "ok_count": ok_count,
            "error_count": len(targets) - ok_count,
            "note": note,
            "source": "ssh cat /etc/sonic/config_db.json",
        },
        "by_switch": per_switch,
    }
