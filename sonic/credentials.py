"""Env-driven credential resolver for SONiC devices.

Resolution order for a given switch IP:
    1. SONIC_HOST_<ip-with-dots-as-underscores>_USERNAME / _PASSWORD
    2. SONIC_DEFAULT_USERNAME / SONIC_DEFAULT_PASSWORD
    3. Built-in lab defaults (admin / password)

Per-host overrides let operators rotate one switch's password without changing defaults.
"""

from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class SonicCredentials:
    username: str
    password: str

    @classmethod
    def for_host(cls, switch_ip: str) -> "SonicCredentials":
        key = "SONIC_HOST_" + switch_ip.replace(".", "_")
        user = (
            os.environ.get(f"{key}_USERNAME")
            or os.environ.get("SONIC_DEFAULT_USERNAME")
            or "admin"
        )
        pw = (
            os.environ.get(f"{key}_PASSWORD")
            or os.environ.get("SONIC_DEFAULT_PASSWORD")
            or "password"
        )
        return cls(username=user, password=pw)
