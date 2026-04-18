"""Tests for mcp_runtime.policy — the three-layer gate that decides
whether a given tool invocation is allowed to proceed.
"""

from __future__ import annotations

import pytest

from mcp_runtime.policy import PolicyViolation, enforce_policy


SAFE_TOOL = {
    "name": "get_interfaces",
    "policy": {"risk": "SAFE_READ", "allowed_in_auto_mode": True, "requires_confirmation": False},
}

MUTATION_TOOL = {
    "name": "set_interface_admin_status",
    "policy": {"risk": "MUTATION", "allowed_in_auto_mode": False, "requires_confirmation": True},
}

DESTRUCTIVE_TOOL = {
    "name": "restore_fabric_snapshot",
    "policy": {"risk": "DESTRUCTIVE", "allowed_in_auto_mode": False, "requires_confirmation": True},
}


def _enable_mutations(monkeypatch):
    monkeypatch.setenv("MCP_MUTATIONS_ENABLED", "1")


def _disable_mutations(monkeypatch):
    monkeypatch.setenv("MCP_MUTATIONS_ENABLED", "0")


class TestKillSwitch:
    def test_safe_read_always_allowed(self, monkeypatch):
        _disable_mutations(monkeypatch)
        enforce_policy(SAFE_TOOL)  # must not raise

    def test_mutation_rejected_when_disabled(self, monkeypatch):
        _disable_mutations(monkeypatch)
        with pytest.raises(PolicyViolation, match="mutations disabled"):
            enforce_policy(MUTATION_TOOL, confirm=True)

    def test_mutation_allowed_when_enabled_and_confirmed(self, monkeypatch):
        _enable_mutations(monkeypatch)
        enforce_policy(MUTATION_TOOL, confirm=True)

    def test_destructive_requires_enabled_and_confirm(self, monkeypatch):
        _enable_mutations(monkeypatch)
        # Without confirm → should raise
        with pytest.raises(PolicyViolation):
            enforce_policy(DESTRUCTIVE_TOOL, confirm=False)
        # With confirm → allowed
        enforce_policy(DESTRUCTIVE_TOOL, confirm=True)


class TestConfirmation:
    def test_mutation_rejected_without_confirm(self, monkeypatch):
        _enable_mutations(monkeypatch)
        with pytest.raises(PolicyViolation, match="confirm"):
            enforce_policy(MUTATION_TOOL, confirm=False)

    def test_mutation_accepted_with_confirm(self, monkeypatch):
        _enable_mutations(monkeypatch)
        enforce_policy(MUTATION_TOOL, confirm=True)

    def test_safe_read_ignores_confirm(self, monkeypatch):
        _disable_mutations(monkeypatch)
        enforce_policy(SAFE_TOOL, confirm=False)  # fine
        enforce_policy(SAFE_TOOL, confirm=True)   # also fine


class TestAutoMode:
    def test_auto_mode_allowed_tool(self, monkeypatch):
        _disable_mutations(monkeypatch)
        enforce_policy(SAFE_TOOL, auto_mode=True)

    def test_auto_mode_blocked_tool(self, monkeypatch):
        _enable_mutations(monkeypatch)
        with pytest.raises(PolicyViolation, match="auto"):
            enforce_policy(MUTATION_TOOL, auto_mode=True, confirm=True)
