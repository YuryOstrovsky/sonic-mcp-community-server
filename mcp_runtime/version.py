# mcp_runtime/version.py
"""Single authoritative version for the SONiC MCP Community Server.

Everything that reports a version — the /health endpoint, package
metadata, image labels, release notes — should read `__version__` from
here so there is exactly one place to bump.

We start at 0.1.0 for the first community release: the project is
substantial, but authentication, SONiC-compatibility coverage, and
operational behaviour will keep evolving, so the public API is not yet
frozen at 1.0.
"""

__version__ = "0.1.0"
