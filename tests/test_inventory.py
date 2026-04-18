"""Tests for sonic.inventory — file-backed loading, hot-reload, save()."""

from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from sonic.inventory import SonicDevice, SonicInventory


def _write(path: Path, switches: list) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"switches": switches}, indent=2), encoding="utf-8")


@pytest.fixture
def inv_path(tmp_path: Path, monkeypatch) -> Path:
    p = tmp_path / "config" / "inventory.json"
    monkeypatch.setenv("SONIC_INVENTORY_PATH", str(p))
    return p


class TestInitialLoad:
    def test_fallback_to_hardcoded_when_file_missing(self, inv_path):
        inv = SonicInventory()
        assert inv.source() == "hardcoded"
        assert len(inv.devices) >= 1

    def test_loads_from_file_when_present(self, inv_path):
        _write(inv_path, [
            {"name": "spine1", "mgmt_ip": "10.0.0.1", "tags": ["spine"]},
        ])
        inv = SonicInventory()
        assert inv.source() == "file"
        assert inv.all_ips() == ["10.0.0.1"]
        assert inv.resolve("spine1").tags == ("spine",)


class TestHotReload:
    def test_reloads_when_file_changes(self, inv_path):
        _write(inv_path, [{"name": "a", "mgmt_ip": "1.1.1.1"}])
        inv = SonicInventory()
        assert inv.all_ips() == ["1.1.1.1"]

        # Sleep so mtime definitely advances on low-res filesystems.
        time.sleep(0.02)
        _write(inv_path, [
            {"name": "a", "mgmt_ip": "1.1.1.1"},
            {"name": "b", "mgmt_ip": "2.2.2.2"},
        ])
        assert sorted(inv.all_ips()) == ["1.1.1.1", "2.2.2.2"]

    def test_malformed_json_keeps_previous(self, inv_path):
        _write(inv_path, [{"name": "a", "mgmt_ip": "1.1.1.1"}])
        inv = SonicInventory()
        assert inv.all_ips() == ["1.1.1.1"]

        time.sleep(0.02)
        inv_path.write_text("{ not json", encoding="utf-8")
        # Bad file shouldn't wipe the cached list.
        assert inv.all_ips() == ["1.1.1.1"]

    def test_zero_devices_keeps_previous(self, inv_path):
        _write(inv_path, [{"name": "a", "mgmt_ip": "1.1.1.1"}])
        inv = SonicInventory()
        assert inv.all_ips() == ["1.1.1.1"]

        time.sleep(0.02)
        _write(inv_path, [])
        # Empty file is treated as "transient edit mid-save" — keep last.
        assert inv.all_ips() == ["1.1.1.1"]


class TestSave:
    def test_save_round_trips(self, inv_path):
        inv = SonicInventory()
        inv.save([
            SonicDevice(name="x", mgmt_ip="3.3.3.3", tags=("tor",)),
            SonicDevice(name="y", mgmt_ip="4.4.4.4"),
        ])
        # File exists and parses cleanly.
        body = json.loads(inv_path.read_text())
        assert [s["mgmt_ip"] for s in body["switches"]] == ["3.3.3.3", "4.4.4.4"]
        # The in-memory inventory reloads on next access.
        assert sorted(inv.all_ips()) == ["3.3.3.3", "4.4.4.4"]

    def test_save_omits_empty_optionals(self, inv_path):
        inv = SonicInventory()
        inv.save([SonicDevice(name="z", mgmt_ip="5.5.5.5")])
        row = json.loads(inv_path.read_text())["switches"][0]
        assert "tags" not in row           # empty tuple → omitted
        assert "username" not in row        # None → omitted
        assert "password" not in row

    def test_save_preserves_overrides(self, inv_path):
        inv = SonicInventory()
        inv.save([SonicDevice(
            name="creds-switch", mgmt_ip="6.6.6.6",
            username="admin2", password="hunter2",
        )])
        row = json.loads(inv_path.read_text())["switches"][0]
        assert row["username"] == "admin2"
        assert row["password"] == "hunter2"


class TestResolve:
    def test_unknown_ip_returns_ad_hoc(self, inv_path):
        inv = SonicInventory()
        d = inv.resolve("192.0.2.42")
        assert d.mgmt_ip == "192.0.2.42"
        assert "ad-hoc" in d.tags
