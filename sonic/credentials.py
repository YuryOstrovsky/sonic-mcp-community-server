"""Credential resolver for SONiC devices.

Resolution order for a given switch IP (first non-empty wins):

  1. Per-device override in inventory.json  (SonicDevice.username / .password)
  2. `password_env` on the inventory entry — the *name* of an env var to
     read the secret from, so the plaintext never has to live in the JSON
  3. SONIC_HOST_<ip-with-dots-as-underscores>_USERNAME / _PASSWORD
  4. SONIC_DEFAULT_USERNAME / SONIC_DEFAULT_PASSWORD
  5. Built-in SONiC factory defaults (admin / YourPaSsWoRd)

Prefer `password_env` (or env vars) over an inline `password` — see the
Security section of the README. An inline password is convenient for a
throwaway lab but means a plaintext secret sits in config/inventory.json.
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
        inventory_password_env: Optional[str] = None,
    ) -> "SonicCredentials":
        key = "SONIC_HOST_" + switch_ip.replace(".", "_")
        user = (
            inventory_username
            or os.environ.get(f"{key}_USERNAME")
            or os.environ.get("SONIC_DEFAULT_USERNAME")
            or "admin"
        )
        # `password_env` names an environment variable that holds the
        # secret — preferred over an inline plaintext `password`.
        env_pw = os.environ.get(inventory_password_env) if inventory_password_env else None
        pw = (
            inventory_password
            or env_pw
            or os.environ.get(f"{key}_PASSWORD")
            or os.environ.get("SONIC_DEFAULT_PASSWORD")
            or "YourPaSsWoRd"
        )
        return cls(username=user, password=pw)
