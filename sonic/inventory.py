"""SONiC device inventory.

Resolution priority (first non-empty source wins):

  1. JSON file at  $SONIC_INVENTORY_PATH  (default: config/inventory.json)
  2. Hardcoded fallback — keeps the default two-VM lab working out of the box

The JSON file is re-read on every access whose underlying file mtime
has changed — so adding or removing a switch takes effect without a
server restart. On parse error we log and fall back to whatever was
previously loaded; a broken JSON never kills live traffic.

Schema:

  {
    "switches": [
      {
        "name": "vm1",
        "mgmt_ip": "10.46.11.50",
        "tags": ["leaf", "rack-1"],
        "username": "admin",            // optional, overrides env defaults
        "password": "secret"             // optional, same
      }
    ]
  }

Ad-hoc fallback: `resolve(ref)` returns a synthetic `SonicDevice` for
unknown IPs so callers can still invoke tools against devices that
haven't been registered yet.
"""

from __future__ import annotations

import json
import os
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from mcp_runtime.logging import get_logger

logger = get_logger("mcp.inventory")


_ENV_INVENTORY_PATH = "SONIC_INVENTORY_PATH"
_DEFAULT_INVENTORY_PATH = Path("config") / "inventory.json"


@dataclass(frozen=True)
class SonicDevice:
    name: str
    mgmt_ip: str
    tags: tuple = ()
    # Optional per-device credential override. None means "use env default".
    # Stored alongside the device so the JSON-file source can carry secrets;
    # env-based creds still work unchanged when these are None.
    username: Optional[str] = None
    password: Optional[str] = None


# Hardcoded fallback — used only when the JSON file is missing.
_HARDCODED_FALLBACK: List[SonicDevice] = [
    SonicDevice(name="vm1", mgmt_ip="10.46.11.50", tags=("lab", "vm", "sonic-vs")),
    SonicDevice(name="vm2", mgmt_ip="10.46.11.51", tags=("lab", "vm", "sonic-vs")),
]


def _inventory_path() -> Path:
    env = os.environ.get(_ENV_INVENTORY_PATH)
    return Path(env) if env else _DEFAULT_INVENTORY_PATH


def _parse_devices(raw: Dict) -> List[SonicDevice]:
    """Convert the parsed JSON into SonicDevice objects. Silently skips rows
    missing `mgmt_ip` (the only strictly required field)."""
    out: List[SonicDevice] = []
    for row in raw.get("switches") or []:
        if not isinstance(row, dict):
            continue
        mgmt_ip = str(row.get("mgmt_ip") or "").strip()
        if not mgmt_ip:
            continue
        name = str(row.get("name") or mgmt_ip).strip()
        tags_raw = row.get("tags") or []
        tags = tuple(str(t) for t in tags_raw if isinstance(t, (str, int)))
        username = row.get("username")
        password = row.get("password")
        out.append(SonicDevice(
            name=name, mgmt_ip=mgmt_ip, tags=tags,
            username=str(username) if username else None,
            password=str(password) if password else None,
        ))
    return out


class SonicInventory:
    """Thread-safe inventory with hot-reload from a JSON file.

    The file is re-read lazily: whenever a read method is called and
    the file's mtime has changed since the last read, we reload. That
    keeps the hot path cheap (no watcher thread) and still picks up
    edits without a restart.
    """

    def __init__(self, devices: Optional[List[SonicDevice]] = None):
        self._lock = threading.Lock()
        self._devices: List[SonicDevice]
        self._last_mtime: Optional[float] = None
        self._last_source: str = "unknown"

        if devices is not None:
            # Explicit override — used by tests and the ad-hoc init path.
            self._devices = list(devices)
            self._last_source = "explicit"
        else:
            self._devices = list(_HARDCODED_FALLBACK)
            self._last_source = "hardcoded"
            # Eager first load so `/ready` at boot reflects the JSON file.
            self._reload_if_changed()

    # ---------- reload machinery ----------

    def _reload_if_changed(self) -> None:
        path = _inventory_path()
        try:
            mtime = path.stat().st_mtime
        except FileNotFoundError:
            # File might have been deleted after an earlier successful load.
            # Keep whatever we had rather than suddenly losing inventory.
            if self._last_source == "file":
                logger.warning("inventory file %s disappeared — keeping last-known list", path)
            return
        except OSError as e:
            logger.warning("inventory stat(%s) failed: %s", path, e)
            return

        if self._last_mtime is not None and mtime == self._last_mtime:
            return   # unchanged

        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as e:
            logger.error("inventory file %s is invalid JSON: %s — keeping previous list", path, e)
            return
        except OSError as e:
            logger.warning("inventory read(%s) failed: %s", path, e)
            return

        parsed = _parse_devices(raw if isinstance(raw, dict) else {})
        if not parsed:
            logger.warning("inventory file %s parsed to zero devices — keeping previous list", path)
            return

        self._devices = parsed
        self._last_mtime = mtime
        self._last_source = "file"
        logger.info("inventory reloaded from %s — %d device(s)", path, len(parsed))

    # ---------- public read API ----------

    @property
    def devices(self) -> List[SonicDevice]:
        with self._lock:
            self._reload_if_changed()
            return list(self._devices)

    def all_ips(self) -> List[str]:
        return [d.mgmt_ip for d in self.devices]

    def all_names(self) -> List[str]:
        return [d.name for d in self.devices]

    def resolve(self, ref: str) -> SonicDevice:
        for d in self.devices:
            if d.mgmt_ip == ref or d.name == ref:
                return d
        return SonicDevice(name=ref, mgmt_ip=ref, tags=("ad-hoc",))

    def source(self) -> str:
        """'file' / 'hardcoded' / 'explicit' — for /ready and the UI."""
        with self._lock:
            self._reload_if_changed()
            return self._last_source

    def path(self) -> str:
        return str(_inventory_path())

    # ---------- public write API ----------
    #
    # Writes always go to the JSON file. If the file doesn't exist yet,
    # the first successful write creates it (plus parent directories).
    # Concurrent writers are serialised by the same lock that guards
    # reads, so we never tear a half-written list into a reader.

    def save(self, devices: List[SonicDevice]) -> None:
        """Persist the given list of devices and hot-reload."""
        path = _inventory_path()
        body = {
            "switches": [_device_to_json(d) for d in devices],
        }
        text = json.dumps(body, indent=2) + "\n"
        with self._lock:
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.with_suffix(path.suffix + ".tmp")
            tmp.write_text(text, encoding="utf-8")
            tmp.replace(path)
            # Trigger reload on next read; don't mutate _devices here to
            # avoid divergence if the just-written JSON happens to parse
            # differently on disk (unlikely but principled).
            self._last_mtime = None


def _device_to_json(d: SonicDevice) -> Dict:
    """Mirror _parse_devices — only include keys that carry a value."""
    row: Dict = {"name": d.name, "mgmt_ip": d.mgmt_ip}
    if d.tags:
        row["tags"] = list(d.tags)
    if d.username:
        row["username"] = d.username
    if d.password:
        row["password"] = d.password
    return row
