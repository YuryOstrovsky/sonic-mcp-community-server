r"""Tool: run_show_command

Safe escape hatch for arbitrary SONiC 'show …' commands.

Safety rules:
  - Command MUST start with 'show ' (case-insensitive after trim)
  - Allowed characters in the rest of the command: A-Z a-z 0-9 space - _ . / : | = + ,
  - No shell metacharacters: ; & $ ` > < \ ( ) { } [ ] \ ' " ? * ! # newline tab
  - Maximum length 256 chars
  - SSH remote shell is invoked with the command as a single argv element,
    but paramiko.exec_command passes the string to the remote shell as-is,
    so we also single-quote the command and block any embedded single-quotes.

This is intentionally a LAST-RESORT tool. Prefer dedicated tools where they exist.
"""

from __future__ import annotations

import re
from typing import Any, Dict

from sonic.tools._common import require_switch_ip


_MAX_LEN = 256
# allow unicode pipe/colon/equals for things like 'show interfaces status | grep Ethernet'
_ALLOWED = re.compile(r"^show\s+[A-Za-z0-9 _\-./:|=+,]+$")


def _validate(command: str) -> str:
    cmd = (command or "").strip()
    if len(cmd) == 0:
        raise ValueError("command is empty")
    if len(cmd) > _MAX_LEN:
        raise ValueError(f"command longer than {_MAX_LEN} chars")
    if "\n" in cmd or "\r" in cmd or "\t" in cmd:
        raise ValueError("command may not contain newlines or tabs")
    if "'" in cmd or '"' in cmd or "\\" in cmd:
        raise ValueError("command may not contain quotes or backslashes")
    if not cmd.lower().startswith("show "):
        raise ValueError("command must start with 'show '")
    if not _ALLOWED.match(cmd):
        raise ValueError(
            "command contains disallowed characters. "
            "Permitted: letters, digits, space, '-', '_', '.', '/', ':', '|', '=', '+', ','"
        )
    return cmd


def run_show_command(
    *,
    inputs: Dict[str, Any],
    registry,
    transport,
    context: Dict[str, Any],
) -> Dict[str, Any]:
    switch_ip = require_switch_ip(inputs, context)
    command = _validate(str(inputs.get("command", "")))
    timeout = int(inputs.get("timeout_seconds", 20))
    if timeout < 1 or timeout > 120:
        raise ValueError("timeout_seconds must be between 1 and 120")

    # Wrap in single quotes so SONiC shell parses the whole string as one command.
    # We blocked embedded single quotes in validation, so this is safe.
    remote_cmd = f"sh -c '{command}'"

    res = transport.ssh.run(switch_ip, remote_cmd, timeout=timeout)

    # Truncate stdout/stderr to avoid enormous payloads; use MCP_MAX_BODY_SIZE
    # at the HTTP layer as the hard cap.
    out = res.stdout
    err = res.stderr
    max_chars = 200_000
    truncated = False
    if len(out) > max_chars:
        out = out[:max_chars]
        truncated = True
    if len(err) > max_chars:
        err = err[:max_chars]
        truncated = True

    return {
        "summary": {
            "switch_ip": switch_ip,
            "command": command,
            "exit_status": res.exit_status,
            "duration_ms": res.duration_ms,
            "truncated": truncated,
            "stdout_bytes": len(res.stdout),
            "stderr_bytes": len(res.stderr),
            "source": "ssh (allowlisted show command)",
        },
        "stdout": out,
        "stderr": err,
    }
