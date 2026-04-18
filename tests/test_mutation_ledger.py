"""Tests for mcp_runtime.mutation_ledger — append-only JSONL persistence."""

from __future__ import annotations

import json
from pathlib import Path

from mcp_runtime.mutation_ledger import MutationLedger


class TestLedgerRecord:
    def test_record_writes_one_line(self, ledger_path: Path):
        ledger = MutationLedger(path=ledger_path)
        entry = ledger.record(
            tool="set_interface_admin_status",
            risk="MUTATION",
            switch_ip="10.0.0.1",
            inputs={"interface": "Ethernet0", "admin_status": "down"},
            status="ok",
            pre_state={"admin_status": "UP"},
            post_state={"admin_status": "DOWN"},
        )
        assert entry["mutation_id"].startswith("mut-")
        assert ledger_path.exists()
        lines = ledger_path.read_text().splitlines()
        assert len(lines) == 1
        parsed = json.loads(lines[0])
        assert parsed["tool"] == "set_interface_admin_status"
        assert parsed["status"] == "ok"

    def test_record_appends(self, ledger_path: Path):
        ledger = MutationLedger(path=ledger_path)
        for i in range(3):
            ledger.record(
                tool="config_save", risk="MUTATION",
                switch_ip=f"10.0.0.{i}", inputs={}, status="ok",
            )
        assert len(ledger_path.read_text().splitlines()) == 3

    def test_redacts_credentials_in_inputs(self, ledger_path: Path):
        ledger = MutationLedger(path=ledger_path)
        ledger.record(
            tool="some_tool", risk="MUTATION", switch_ip="10.0.0.1",
            inputs={"password": "s3cr3t", "username": "admin", "api_key": "sk-abc"},
            status="ok",
        )
        parsed = json.loads(ledger_path.read_text().splitlines()[0])
        assert parsed["inputs"]["password"] != "s3cr3t"
        assert parsed["inputs"]["api_key"] != "sk-abc"
        # Non-secret fields survive untouched.
        assert parsed["inputs"]["username"] == "admin"


class TestLedgerTail:
    def test_tail_empty_when_no_file(self, ledger_path: Path):
        ledger = MutationLedger(path=ledger_path)
        assert ledger.tail(n=10) == []

    def test_tail_returns_last_n(self, ledger_path: Path):
        ledger = MutationLedger(path=ledger_path)
        for i in range(5):
            ledger.record(
                tool="config_save", risk="MUTATION",
                switch_ip=f"10.0.0.{i}", inputs={}, status="ok",
            )
        tail = ledger.tail(n=3)
        assert len(tail) == 3
        # Last 3 entries, in write order.
        assert [e["switch_ip"] for e in tail] == ["10.0.0.2", "10.0.0.3", "10.0.0.4"]

    def test_tail_tolerates_malformed_lines(self, ledger_path: Path):
        ledger_path.parent.mkdir(parents=True, exist_ok=True)
        ledger_path.write_text(
            '{"mutation_id": "mut-aaaaaaaa", "tool": "x", "status": "ok"}\n'
            "not-a-json-line\n"
            '{"mutation_id": "mut-bbbbbbbb", "tool": "y", "status": "ok"}\n'
        )
        ledger = MutationLedger(path=ledger_path)
        tail = ledger.tail(n=10)
        # Two parseable + one diagnostic placeholder for the bad line.
        assert len(tail) == 3
        assert any("_unparseable_line" in e for e in tail)


class TestConcurrentWrites:
    def test_lock_serializes_writes(self, ledger_path: Path):
        # Basic smoke: concurrent record() calls from threads don't interleave
        # and all entries end up in the file.
        import threading
        ledger = MutationLedger(path=ledger_path)

        def worker(i: int):
            ledger.record(
                tool=f"worker_{i}", risk="MUTATION",
                switch_ip="10.0.0.1", inputs={"i": i}, status="ok",
            )

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(20)]
        for t in threads: t.start()
        for t in threads: t.join()

        lines = ledger_path.read_text().splitlines()
        assert len(lines) == 20
        # Every line should be valid JSON — no torn writes.
        for line in lines:
            json.loads(line)
