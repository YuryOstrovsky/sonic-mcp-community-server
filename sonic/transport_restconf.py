"""HTTPS/RESTCONF transport for SONiC mgmt-framework.

Per-host requests.Session for connection pooling and keepalive.
Basic auth from SonicCredentials. Paths given to request() are relative
to /restconf (e.g. '/data/openconfig-interfaces:interfaces').
"""

from __future__ import annotations

import os
import threading
import time
from typing import Any, Dict, Optional

import requests
import urllib3

from mcp_runtime.logging import get_logger
from sonic.credentials import SonicCredentials

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

_ALLOWED = {"GET", "POST", "PUT", "PATCH", "DELETE", "HEAD"}


class RestconfError(Exception):
    pass


class SonicRestconfTransport:
    def __init__(
        self,
        port: Optional[int] = None,
        verify_tls: Optional[bool] = None,
        timeout: Optional[int] = None,
    ):
        self.port = port or int(os.environ.get("SONIC_RESTCONF_PORT", "443"))
        self.verify_tls = (
            verify_tls
            if verify_tls is not None
            else os.environ.get("SONIC_VERIFY_TLS", "false").lower()
            in ("1", "true", "yes", "on")
        )
        self.timeout = timeout or int(
            os.environ.get("SONIC_RESTCONF_TIMEOUT_SECONDS", "20")
        )
        self._sessions: Dict[str, requests.Session] = {}
        self._lock = threading.Lock()
        self.logger = get_logger("sonic.restconf")

    def _session_for(self, switch_ip: str) -> requests.Session:
        with self._lock:
            s = self._sessions.get(switch_ip)
            if s is not None:
                return s
            creds = SonicCredentials.for_host(switch_ip)
            s = requests.Session()
            s.auth = (creds.username, creds.password)
            s.verify = self.verify_tls
            s.headers.update(
                {
                    "Accept": "application/yang-data+json",
                    "Content-Type": "application/yang-data+json",
                }
            )
            self._sessions[switch_ip] = s
            return s

    def _url(self, switch_ip: str, path: str) -> str:
        if not path.startswith("/"):
            path = "/" + path
        if not (path.startswith("/restconf") or path.startswith("/.well-known")):
            path = "/restconf" + path
        return f"https://{switch_ip}:{self.port}{path}"

    def request(
        self,
        switch_ip: str,
        method: str,
        path: str,
        params: Optional[Dict[str, Any]] = None,
        json_body: Optional[Dict[str, Any]] = None,
        correlation_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        method = method.upper()
        if method not in _ALLOWED:
            raise RestconfError(f"method not allowed: {method}")

        url = self._url(switch_ip, path)
        headers = {"X-Correlation-ID": correlation_id} if correlation_id else {}

        start = time.time()
        try:
            r = self._session_for(switch_ip).request(
                method=method,
                url=url,
                params=params,
                json=json_body,
                headers=headers,
                timeout=self.timeout,
            )
        except Exception as e:
            self.logger.exception(
                "restconf request failed switch=%s url=%s error=%s",
                switch_ip,
                url,
                e,
            )
            raise

        duration_ms = int((time.time() - start) * 1000)
        ct = r.headers.get("Content-Type", "")
        payload: Any = None
        if r.content:
            if "json" in ct.lower():
                try:
                    payload = r.json()
                except ValueError:
                    payload = {
                        "_raw": r.text[:2000],
                        "_warning": "not valid JSON",
                    }
            else:
                payload = {"_raw": r.text[:2000], "_content_type": ct}

        self.logger.info(
            "restconf %s status=%s duration_ms=%d switch=%s url=%s corr=%s",
            method,
            r.status_code,
            duration_ms,
            switch_ip,
            url,
            correlation_id,
        )
        return {
            "status": r.status_code,
            "payload": payload,
            "url": url,
            "duration_ms": duration_ms,
        }

    def get_json(
        self,
        switch_ip: str,
        path: str,
        params: Optional[Dict[str, Any]] = None,
        correlation_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """GET path (relative to /restconf); raise on non-2xx."""
        r = self.request(
            switch_ip, "GET", path, params=params, correlation_id=correlation_id
        )
        if r["status"] >= 400:
            snippet = ""
            if isinstance(r["payload"], dict):
                snippet = str(r["payload"])[:300]
            raise RestconfError(
                f"RESTCONF GET {path} -> {r['status']}: {snippet}"
            )
        return r

    def probe(self, switch_ip: str) -> bool:
        """Used by /ready. Any HTTP response from the RESTCONF host-meta endpoint
        means the mgmt-framework HTTPS server is alive."""
        try:
            r = self.request(switch_ip, "GET", "/.well-known/host-meta")
            return 200 <= r["status"] < 500
        except Exception:
            return False
