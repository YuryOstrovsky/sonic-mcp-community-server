"""Tool registry for the SONiC MCP server.

Every tool is a Python handler. Catalog metadata lives in
generated/mcp_tools.json so clients can discover inputs/policy/tags.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Callable, Dict, List

from sonic.tools.interfaces.clear_interface_counters import clear_interface_counters
from sonic.tools.interfaces.get_interfaces import get_interfaces
from sonic.tools.interfaces.get_ip_interfaces import get_ip_interfaces
from sonic.tools.interfaces.set_interface_admin_status import set_interface_admin_status
from sonic.tools.interfaces.set_interface_description import set_interface_description
from sonic.tools.interfaces.set_interface_mtu import set_interface_mtu
from sonic.tools.l2.add_vlan import add_vlan
from sonic.tools.l2.get_arp_table import get_arp_table
from sonic.tools.l2.get_portchannels import get_portchannels
from sonic.tools.l2.get_vlans import get_vlans
from sonic.tools.l2.remove_vlan import remove_vlan
from sonic.tools.lldp.get_lldp_neighbors import get_lldp_neighbors
from sonic.tools.multi.get_bgp_summary_all import get_bgp_summary_all
from sonic.tools.multi.get_interfaces_all import get_interfaces_all
from sonic.tools.multi.get_lldp_neighbors_all import get_lldp_neighbors_all
from sonic.tools.multi.get_routes_all import get_routes_all
from sonic.tools.multi.get_system_info_all import get_system_info_all
from sonic.tools.multi.get_vlans_all import get_vlans_all
from sonic.tools.routing.get_bgp_summary import get_bgp_summary
from sonic.tools.routing.get_ipv6_routes import get_ipv6_routes
from sonic.tools.routing.get_routes import get_routes
from sonic.tools.sampling.get_sflow_status import get_sflow_status
from sonic.tools.system.config_save import config_save
from sonic.tools.system.get_mutation_history import get_mutation_history
from sonic.tools.system.get_platform_detail import get_platform_detail
from sonic.tools.system.get_system_info import get_system_info
from sonic.tools.system.run_show_command import run_show_command


TOOLS_FILE = Path("generated/mcp_tools.json")


class MCPRegistry:
    def __init__(self):
        self.tools: Dict[str, dict] = {}
        self.handlers: Dict[str, Callable] = {}

    def load(self) -> "MCPRegistry":
        data = json.loads(TOOLS_FILE.read_text(encoding="utf-8"))
        for tool in data:
            name = tool.get("name")
            if not name:
                continue
            if tool.get("policy", {}).get("disabled") is True:
                continue
            self.tools[name] = tool

        self.handlers.update(
            {
                "get_interfaces": get_interfaces,
                "get_ip_interfaces": get_ip_interfaces,
                "get_routes": get_routes,
                "get_ipv6_routes": get_ipv6_routes,
                "get_bgp_summary": get_bgp_summary,
                "get_lldp_neighbors": get_lldp_neighbors,
                "get_vlans": get_vlans,
                "get_arp_table": get_arp_table,
                "get_portchannels": get_portchannels,
                "get_platform_detail": get_platform_detail,
                "get_sflow_status": get_sflow_status,
                "get_system_info": get_system_info,
                "get_system_info_all": get_system_info_all,
                "get_interfaces_all": get_interfaces_all,
                "get_bgp_summary_all": get_bgp_summary_all,
                "get_routes_all": get_routes_all,
                "get_lldp_neighbors_all": get_lldp_neighbors_all,
                "get_vlans_all": get_vlans_all,
                "set_interface_admin_status": set_interface_admin_status,
                "set_interface_mtu": set_interface_mtu,
                "set_interface_description": set_interface_description,
                "clear_interface_counters": clear_interface_counters,
                "add_vlan": add_vlan,
                "remove_vlan": remove_vlan,
                "config_save": config_save,
                "get_mutation_history": get_mutation_history,
                "run_show_command": run_show_command,
            }
        )

        missing_spec = [n for n in self.handlers if n not in self.tools]
        missing_handler = [n for n in self.tools if n not in self.handlers]
        if missing_spec:
            raise RuntimeError(
                f"handlers registered without catalog entries: {missing_spec}"
            )
        if missing_handler:
            raise RuntimeError(
                f"catalog entries without handlers: {missing_handler}"
            )
        return self

    def list_tools(self) -> List[dict]:
        return list(self.tools.values())

    def get(self, name: str):
        return self.tools.get(name)

    def get_handler(self, name: str):
        return self.handlers.get(name)
