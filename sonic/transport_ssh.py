"""SSH transport for SONiC using paramiko.

Per-host client pool — one paramiko client per switch, reused across
exec_command() calls. If a client's transport dies, it's dropped and
reconnected on the next call.
"""

from __future__ import annotations

import os
import threading
import time
from dataclasses import dataclass
from typing import Dict, Optional

import paramiko

from mcp_runtime.logging import get_logger
from sonic.credentials import SonicCredentials


class SshError(Exception):
    pass


@dataclass
class SshResult:
    stdout: str
    stderr: str
    exit_status: int
    duration_ms: int


class SonicSshTransport:
    def __init__(self, port: int = 22, timeout: Optional[int] = None):
        self.port = port
        self.timeout = timeout or int(
            os.environ.get("SONIC_SSH_TIMEOUT_SECONDS", "20")
        )
        self._clients: Dict[str, paramiko.SSHClient] = {}
        self._lock = threading.Lock()
        self.logger = get_logger("sonic.ssh")

    def _is_alive(self, client: paramiko.SSHClient) -> bool:
        t = client.get_transport()
        return bool(t and t.is_active())

    def _client_for(self, switch_ip: str) -> paramiko.SSHClient:
        with self._lock:
            c = self._clients.get(switch_ip)
            if c is not None and self._is_alive(c):
                return c

            if c is not None:
                try:
                    c.close()
                except Exception:
                    pass

            creds = SonicCredentials.for_host(switch_ip)
            c = paramiko.SSHClient()
            c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            c.connect(
                hostname=switch_ip,
                port=self.port,
                username=creds.username,
                password=creds.password,
                timeout=self.timeout,
                look_for_keys=False,
                allow_agent=False,
            )
            self._clients[switch_ip] = c
            return c

    def run(
        self,
        switch_ip: str,
        command: str,
        timeout: Optional[int] = None,
    ) -> SshResult:
        t = timeout or self.timeout
        self.logger.info("ssh exec switch=%s cmd=%s", switch_ip, command)
        start = time.time()
        try:
            client = self._client_for(switch_ip)
            _stdin, stdout, stderr = client.exec_command(command, timeout=t)
            out = stdout.read().decode("utf-8", errors="replace")
            err = stderr.read().decode("utf-8", errors="replace")
            status = stdout.channel.recv_exit_status()
        except Exception as e:
            with self._lock:
                old = self._clients.pop(switch_ip, None)
                if old is not None:
                    try:
                        old.close()
                    except Exception:
                        pass
            self.logger.exception(
                "ssh exec failed switch=%s cmd=%s error=%s",
                switch_ip,
                command,
                e,
            )
            raise SshError(f"SSH exec failed on {switch_ip}: {e}") from e

        duration_ms = int((time.time() - start) * 1000)
        self.logger.info(
            "ssh done switch=%s status=%d duration_ms=%d",
            switch_ip,
            status,
            duration_ms,
        )
        return SshResult(
            stdout=out, stderr=err, exit_status=status, duration_ms=duration_ms
        )

    def probe(self, switch_ip: str) -> bool:
        try:
            r = self.run(switch_ip, "echo ok", timeout=5)
            return r.exit_status == 0 and "ok" in r.stdout
        except Exception:
            return False

    def close_all(self) -> None:
        with self._lock:
            for c in list(self._clients.values()):
                try:
                    c.close()
                except Exception:
                    pass
            self._clients.clear()
