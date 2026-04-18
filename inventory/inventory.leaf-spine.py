"""Leaf-spine inventory — 2 spines, 4 leaves.

Adjust the mgmt IPs to match your lab. The `tags` tuple lets you later
filter fanout tools by role (e.g. drain only the spines for
maintenance, probe only the leaves for MAC-learning tests).

Topology this represents:

             spine1          spine2
            /      \        /      \
      leaf1        leaf2  leaf3     leaf4
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
    # Spines
    SonicDevice(name="spine1", mgmt_ip="10.0.1.1",  tags=("spine", "core", "pod-a")),
    SonicDevice(name="spine2", mgmt_ip="10.0.1.2",  tags=("spine", "core", "pod-a")),
    # Leaves
    SonicDevice(name="leaf1",  mgmt_ip="10.0.2.11", tags=("leaf", "tor", "rack-1")),
    SonicDevice(name="leaf2",  mgmt_ip="10.0.2.12", tags=("leaf", "tor", "rack-2")),
    SonicDevice(name="leaf3",  mgmt_ip="10.0.2.13", tags=("leaf", "tor", "rack-3")),
    SonicDevice(name="leaf4",  mgmt_ip="10.0.2.14", tags=("leaf", "tor", "rack-4")),
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

    def by_tag(self, tag: str) -> List[SonicDevice]:
        """Helper — not used by the runtime, but handy for custom scripts
        that want to run a tool only against a role (e.g. all spines)."""
        return [d for d in self.devices if tag in d.tags]

    def resolve(self, ref: str) -> SonicDevice:
        for d in self.devices:
            if d.mgmt_ip == ref or d.name == ref:
                return d
        return SonicDevice(name=ref, mgmt_ip=ref, tags=("ad-hoc",))
