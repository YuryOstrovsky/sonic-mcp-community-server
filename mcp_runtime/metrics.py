# mcp_runtime/metrics.py

import re
from prometheus_client import Counter, Histogram

# ----------------------------------------
# Fix #22: label cardinality safety
# ----------------------------------------
# Tool names are validated against the registry (fix #3) so cardinality is
# bounded in practice.  safe_label() is a belt-and-suspenders guard that
# truncates and sanitizes any label value before it reaches Prometheus,
# preventing a logic bug elsewhere from ever creating an unbounded label space.
_LABEL_MAX = 64
_LABEL_RE = re.compile(r"[^a-zA-Z0-9_]")


def safe_label(value: str) -> str:
    """Sanitize a Prometheus label: replace bad chars with _, truncate."""
    return _LABEL_RE.sub("_", str(value))[:_LABEL_MAX]


# ----------------------------------------
# Global metrics registry
# ----------------------------------------

MCP_INVOKE_TOTAL = Counter(
    "mcp_invoke_total",
    "Total number of MCP tool invocations",
    ["tool"],
)

MCP_INVOKE_SUCCESS = Counter(
    "mcp_invoke_success_total",
    "Total successful MCP tool invocations",
    ["tool"],
)

MCP_INVOKE_FAILURE = Counter(
    "mcp_invoke_failure_total",
    "Total failed MCP tool invocations",
    ["tool"],
)

MCP_INVOKE_LATENCY = Histogram(
    "mcp_invoke_latency_seconds",
    "Latency of MCP tool invocations",
    ["tool"],
    buckets=(
        0.05,   # 50ms
        0.1,    # 100ms
        0.25,
        0.5,
        0.75,
        1.0,
        1.5,
        2.0,
        3.0,
        5.0,
        10.0,
        float("inf"),
    ),
)

MCP_INVOKE_STATUS = Counter(
    "mcp_invoke_status_total",
    "MCP tool invocations by HTTP status code",
    ["tool", "status"],
)


