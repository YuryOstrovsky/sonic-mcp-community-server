"""Tool registry for the SONiC MCP server.

Tools live under sonic/tools/<category>/<tool_name>.py. Each file must
define a function whose name matches the file's stem (e.g. get_interfaces
lives in get_interfaces.py and exports def get_interfaces(...)).

Discovery is automatic — dropping a new .py file into any sonic/tools/
subdirectory is enough to register a tool. Files whose basename starts
with '_' (_common.py, _fanout.py, …) are treated as private helpers and
skipped. Tools whose name isn't also listed in generated/mcp_tools.json
are skipped with a warning (missing catalog entry).

Catalog metadata lives in generated/mcp_tools.json — input schema, risk,
transport tags, etc. Keep that file in sync when adding a tool.
"""

from __future__ import annotations

import importlib
import json
import pkgutil
from pathlib import Path
from typing import Callable, Dict, List

import sonic.tools as _tools_pkg
from mcp_runtime.logging import get_logger


logger = get_logger("mcp.registry")
TOOLS_FILE = Path("generated/mcp_tools.json")


def _discover_handlers() -> Dict[str, Callable]:
    """Walk sonic.tools.* packages, import every non-underscore module,
    and pick out the function that matches the module's stem.
    """
    handlers: Dict[str, Callable] = {}
    for mod_info in pkgutil.walk_packages(_tools_pkg.__path__, prefix=f"{_tools_pkg.__name__}."):
        if mod_info.ispkg:
            continue
        # Skip helper modules whose basename starts with '_'.
        stem = mod_info.name.rsplit(".", 1)[-1]
        if stem.startswith("_"):
            continue
        try:
            module = importlib.import_module(mod_info.name)
        except Exception as e:
            # A broken plugin shouldn't crash the whole server at boot —
            # log loudly and keep going.
            logger.error("plugin import failed: %s (%s)", mod_info.name, e)
            continue
        fn = getattr(module, stem, None)
        if fn is None or not callable(fn):
            logger.warning(
                "plugin %s has no callable named %r — skipping",
                mod_info.name, stem,
            )
            continue
        if stem in handlers:
            # Same tool name from two different categories = programming error.
            logger.error(
                "duplicate tool name %r from %s (already bound to %s)",
                stem, mod_info.name, handlers[stem].__module__,
            )
            continue
        handlers[stem] = fn
    return handlers


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

        # Plugin-style auto-discovery: every non-underscore module under
        # sonic.tools.* that exports a function matching its stem becomes
        # a handler. Registry is populated in one sweep at boot.
        self.handlers.update(_discover_handlers())

        missing_spec = [n for n in self.handlers if n not in self.tools]
        missing_handler = [n for n in self.tools if n not in self.handlers]
        if missing_spec:
            raise RuntimeError(
                f"handlers discovered without catalog entries: {missing_spec}"
            )
        if missing_handler:
            raise RuntimeError(
                f"catalog entries without handlers: {missing_handler}"
            )
        logger.info("registry loaded: %d tools (discovered from sonic.tools.*)", len(self.handlers))
        return self

    def list_tools(self) -> List[dict]:
        return list(self.tools.values())

    def get(self, name: str):
        return self.tools.get(name)

    def get_handler(self, name: str):
        return self.handlers.get(name)
