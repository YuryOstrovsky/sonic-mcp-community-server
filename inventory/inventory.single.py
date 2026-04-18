"""Single-switch inventory — smallest working config.

Copy over sonic/inventory.py (keep the SonicInventory / SonicDevice
imports intact), edit the mgmt IP, restart the server.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional


@dataclass(frozen=True)
class SonicDevice:
    name: str
    mgmt_ip: str
    tags: tuple = ()


_DEFAULT_DEVICES: List[SonicDevice] = [
    SonicDevice(name="sonic1", mgmt_ip="10.0.0.10", tags=("lab",)),
]


class SonicInventory:
    def __init__(self, devices: Optional[List[SonicDevice]] = None):
        self.devices: List[SonicDevice] = (
            list(devices) if devices is not None else list(_DEFAULT_DEVICES)
        )

    def all_ips(self) -> List[str]:
        return [d.mgmt_ip for d in self.devices]

    def all_names(self) -> List[str]:
        return [d.name for d in self.devices]

    def resolve(self, ref: str) -> SonicDevice:
        for d in self.devices:
            if d.mgmt_ip == ref or d.name == ref:
                return d
        return SonicDevice(name=ref, mgmt_ip=ref, tags=("ad-hoc",))
