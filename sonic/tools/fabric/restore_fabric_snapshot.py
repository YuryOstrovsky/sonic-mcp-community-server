"""Tool: restore_fabric_snapshot

Apply a previously-saved snapshot back to each listed switch. For each
switch, upload the stored config_db.json to /etc/sonic/config_db.json
and run `sudo config reload -y`.

**This is DESTRUCTIVE.** `config reload` tears down the data plane
briefly while swss reprograms from the new config. It can lock the
operator out if the new config breaks management access. Always verify
the snapshot is healthy before restoring.

Inputs:
  name        : required — label of the snapshot to apply
  switch_ips  : optional — restrict to a subset of switches in the snapshot
  skip_reload : optional — upload the JSON but don't run `config reload`.
                Useful for staging (manual reload later).

SAFE_READ it is not: risk=DESTRUCTIVE, requires_confirmation=true.
"""

from __future__ import annotations

import base64
import json
import os
import shlex
import time
from pathlib import Path
from typing import Any, Dict, List, Optional


_SNAPSHOT_ROOT_ENV = "SONIC_SNAPSHOT_ROOT"
_DEFAULT_ROOT = Path("snapshots")


def _snapshot_root() -> Path:
    env = os.environ.get(_SNAPSHOT_ROOT_ENV)
    return Path(env) if env else _DEFAULT_ROOT


def _push_config(transport, switch_ip: str, text: str) -> None:
    """Write `text` to /etc/sonic/config_db.json on the switch.

    We base64-encode to avoid shell-quoting issues with large JSON
    payloads (nested quotes, special characters). `sudo tee` writes
    as root; `>/dev/null` silences the echo.
    """
    encoded = base64.b64encode(text.encode("utf-8")).decode("ascii")
    cmd = (
        f"echo {shlex.quote(encoded)} | base64 -d | "
        f"sudo tee /etc/sonic/config_db.json >/dev/null"
    )
    res = transport.ssh.run(switch_ip, cmd)
    if res.exit_status != 0:
        raise RuntimeError(
            f"failed to write config_db.json on {switch_ip}: "
            f"exit={res.exit_status} stderr={res.stderr[:200]}"
        )


def _reload(transport, switch_ip: str) -> Dict[str, Any]:
    # config reload prints a lot; -y confirms.
    res = transport.ssh.run(switch_ip, "sudo config reload -y")
    return {
        "exit_status": res.exit_status,
        "stdout_tail": (res.stdout or "")[-400:],
        "stderr_tail": (res.stderr or "")[-400:],
    }


def restore_fabric_snapshot(
    *,
    inputs: Dict[str, Any],
    registry,
    transport,
    context: Dict[str, Any],
) -> Dict[str, Any]:
    name = str(inputs.get("name") or "").strip()
    if not name:
        raise ValueError("'name' is required (the snapshot label)")
    skip_reload = bool(inputs.get("skip_reload", False))
    scope: Optional[List[str]] = inputs.get("switch_ips") or None

    root = _snapshot_root() / name
    meta_path = root / "snapshot.json"
    if not root.is_dir() or not meta_path.exists():
        raise ValueError(f"snapshot {name!r} not found at {root}")

    try:
        metadata = json.loads(meta_path.read_text(encoding="utf-8"))
    except Exception as e:
        raise RuntimeError(f"could not read snapshot metadata: {e}")

    stored_switches: List[str] = metadata.get("switches") or []
    if not stored_switches:
        raise RuntimeError("snapshot has no switches listed in metadata")

    if scope:
        targets = [ip for ip in scope if ip in stored_switches]
        missing = [ip for ip in scope if ip not in stored_switches]
        if missing:
            raise ValueError(
                f"requested switch_ips {missing} are not in this snapshot. "
                f"Snapshot contains: {stored_switches}"
            )
    else:
        targets = list(stored_switches)

    per_switch: Dict[str, Any] = {}
    ok_count = 0

    for ip in targets:
        switch_path = root / f"{ip}.json"
        if not switch_path.exists():
            per_switch[ip] = {"status": "error", "error": f"missing switch file {switch_path}"}
            continue
        try:
            text = switch_path.read_text(encoding="utf-8")
            # Re-validate: catch on-disk corruption before touching the switch.
            json.loads(text)
        except Exception as e:
            per_switch[ip] = {"status": "error", "error": f"corrupt snapshot file: {e}"}
            continue

        try:
            _push_config(transport, ip, text)
        except Exception as e:
            per_switch[ip] = {"status": "error", "error": f"push failed: {e}"}
            continue

        entry: Dict[str, Any] = {"status": "uploaded", "path_on_switch": "/etc/sonic/config_db.json"}
        if not skip_reload:
            # `config reload` disconnects SSH briefly; allow the command to
            # time out rather than failing the whole tool.
            try:
                started = time.time()
                entry["reload"] = _reload(transport, ip)
                entry["reload"]["elapsed_s"] = round(time.time() - started, 2)
                if entry["reload"]["exit_status"] == 0:
                    entry["status"] = "reloaded"
                else:
                    entry["status"] = "reload_error"
            except Exception as e:
                # Expected for long-running reloads; the switch will finish
                # reloading server-side regardless. Surface this honestly.
                entry["status"] = "reload_disconnected"
                entry["reload_error"] = str(e)
        ok_count += 1 if entry["status"] in {"reloaded", "uploaded", "reload_disconnected"} else 0
        per_switch[ip] = entry

    return {
        "summary": {
            "name": name,
            "path": str(root),
            "metadata_timestamp": metadata.get("timestamp"),
            "switch_count": len(targets),
            "ok_count": ok_count,
            "error_count": len(targets) - ok_count,
            "skip_reload": skip_reload,
            "source": "ssh upload + config reload" if not skip_reload else "ssh upload only",
        },
        "by_switch": per_switch,
    }
