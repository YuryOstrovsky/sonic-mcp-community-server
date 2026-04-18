"""Credential resolver for SONiC devices.

Resolution order for a given switch IP (first non-empty wins):

  1. Per-device override in inventory.json  (SonicDevice.username / .password)
  2. SONIC_HOST_<ip-with-dots-as-underscores>_USERNAME / _PASSWORD
  3. SONIC_DEFAULT_USERNAME / SONIC_DEFAULT_PASSWORD
  4. Built-in lab defaults (admin / password)

The inventory-level override lets operators stamp out per-switch
credentials in a single JSON file managed from the web client,
without having to set N env vars.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class SonicCredentials:
    username: str
    password: str

    @classmethod
    def for_host(
        cls,
        switch_ip: str,
        *,
        inventory_username: Optional[str] = None,
        inventory_password: Optional[str] = None,
    ) -> "SonicCredentials":
        key = "SONIC_HOST_" + switch_ip.replace(".", "_")
        user = (
            inventory_username
            or os.environ.get(f"{key}_USERNAME")
            or os.environ.get("SONIC_DEFAULT_USERNAME")
            or "admin"
        )
        pw = (
            inventory_password
            or os.environ.get(f"{key}_PASSWORD")
            or os.environ.get("SONIC_DEFAULT_PASSWORD")
            or "password"
        )
        return cls(username=user, password=pw)
