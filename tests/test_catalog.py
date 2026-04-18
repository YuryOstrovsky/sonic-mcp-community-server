"""Structural tests for generated/mcp_tools.json.

These guard the invariants the runtime depends on: every tool has a
valid schema, a legal risk tier, and that the in-tree Python handler
exists for every catalogued name (and vice-versa — no dangling files).
"""

from __future__ import annotations

import json
import pkgutil
from pathlib import Path

import pytest

import sonic.tools as _tools_pkg


_REPO_ROOT = Path(__file__).resolve().parent.parent
_CATALOG = json.loads((_REPO_ROOT / "generated/mcp_tools.json").read_text(encoding="utf-8"))

_VALID_RISKS = {"SAFE_READ", "MUTATION", "DESTRUCTIVE"}


@pytest.mark.parametrize("tool", _CATALOG, ids=lambda t: t.get("name", "?"))
class TestEveryTool:
    def test_has_name(self, tool: dict):
        assert tool.get("name"), "tool has no name"

    def test_has_description(self, tool: dict):
        assert tool.get("description"), f"{tool['name']} has no description"

    def test_has_category(self, tool: dict):
        assert tool.get("category"), f"{tool['name']} has no category"

    def test_has_transport(self, tool: dict):
        assert tool.get("transport"), f"{tool['name']} has no transport"

    def test_policy_risk_legal(self, tool: dict):
        risk = (tool.get("policy") or {}).get("risk")
        assert risk in _VALID_RISKS, f"{tool['name']} risk={risk!r} is not one of {_VALID_RISKS}"

    def test_input_schema_is_object(self, tool: dict):
        schema = tool.get("input_schema") or {}
        assert schema.get("type") == "object", f"{tool['name']} schema.type != object"
        assert isinstance(schema.get("properties") or {}, dict)

    def test_required_inputs_declared(self, tool: dict):
        """Required inputs must appear in the properties map."""
        schema = tool.get("input_schema") or {}
        props = schema.get("properties") or {}
        for req in schema.get("required") or []:
            assert req in props, f"{tool['name']}: required input {req!r} missing from properties"


def _discover_handler_names() -> set[str]:
    names: set[str] = set()
    for mod_info in pkgutil.walk_packages(_tools_pkg.__path__, prefix=f"{_tools_pkg.__name__}."):
        if mod_info.ispkg:
            continue
        stem = mod_info.name.rsplit(".", 1)[-1]
        if stem.startswith("_"):
            continue
        names.add(stem)
    return names


class TestCatalogHandlerParity:
    """Every catalog entry must have a handler file, and vice-versa."""

    def test_every_catalog_entry_has_handler(self):
        catalog_names = {t["name"] for t in _CATALOG if t.get("name")}
        handler_names = _discover_handler_names()
        missing = catalog_names - handler_names
        assert not missing, f"catalog entries without a handler file: {sorted(missing)}"

    def test_every_handler_has_catalog_entry(self):
        catalog_names = {t["name"] for t in _CATALOG if t.get("name")}
        handler_names = _discover_handler_names()
        orphans = handler_names - catalog_names
        assert not orphans, f"handler files without a catalog entry: {sorted(orphans)}"
