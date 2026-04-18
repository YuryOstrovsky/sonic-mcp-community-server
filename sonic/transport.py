"""Unified SONiC transport: RESTCONF + SSH.

Tier-2 tool handlers receive this object as `transport` and reach into
either sub-transport by name:

    transport.restconf.get_json(switch_ip, "/data/openconfig-interfaces:interfaces")
    transport.ssh.run(switch_ip, 'vtysh -c "show ip route json"')
"""

from __future__ import annotations

from typing import Optional

from sonic.inventory import SonicInventory
from sonic.transport_restconf import SonicRestconfTransport
from sonic.transport_ssh import SonicSshTransport


class SonicTransport:
    def __init__(self, inventory: Optional[SonicInventory] = None):
        self.inventory = inventory or SonicInventory()
        self.restconf = SonicRestconfTransport()
        self.ssh = SonicSshTransport()
        # Give sub-transports a handle to the inventory so they can
        # honour per-device credential overrides from inventory.json.
        self.restconf.inventory = self.inventory
        self.ssh.inventory = self.inventory

    def probe_host(self, switch_ip: str) -> dict:
        return {
            "switch_ip": switch_ip,
            "restconf": self.restconf.probe(switch_ip),
            "ssh": self.ssh.probe(switch_ip),
        }

    def close(self) -> None:
        self.ssh.close_all()
