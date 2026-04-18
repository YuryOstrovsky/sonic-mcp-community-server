"""Shared helpers for SONiC tool handlers."""

from __future__ import annotations

from typing import Any, Dict, Optional


def require_switch_ip(inputs: Dict[str, Any], context: Optional[Dict[str, Any]] = None) -> str:
    """Pull switch_ip from inputs, falling back to resolved context."""
    ip = inputs.get("switch_ip") or (context or {}).get("switch_ip")
    if not ip or not isinstance(ip, str) or not ip.strip():
        raise ValueError("missing required input: switch_ip")
    return ip.strip()
