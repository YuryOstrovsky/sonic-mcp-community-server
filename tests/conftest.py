"""Pytest fixtures shared across the test suite.

Kept small on purpose — the modules under test (policy, ledger, catalog)
are pure Python with no external dependencies, so fixtures only provide
temp paths and repo-root sys.path wiring.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))


@pytest.fixture
def ledger_path(tmp_path: Path) -> Path:
    """Isolated ledger file per test — no cross-test pollution."""
    return tmp_path / "mutations.jsonl"
