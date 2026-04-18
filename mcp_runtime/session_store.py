# mcp_runtime/session_store.py

import time
import uuid
from mcp_runtime.session import MCPSession

_MAX_SESSIONS = 500       # hard cap on concurrent sessions
_SESSION_TTL  = 3600      # seconds of inactivity before eviction


class SessionStore:
    def __init__(self, max_sessions: int = _MAX_SESSIONS, ttl: int = _SESSION_TTL):
        self._sessions: dict = {}
        self._last_seen: dict = {}
        self._max_sessions = max_sessions
        self._ttl = ttl

    def get_or_create(self, session_id: str | None) -> MCPSession:
        # Fix #6: evict stale sessions on every access (cheap O(n) scan)
        self._evict_expired()

        if session_id and session_id in self._sessions:
            self._last_seen[session_id] = time.monotonic()
            return self._sessions[session_id]

        # If at capacity, drop the oldest idle session before adding
        if len(self._sessions) >= self._max_sessions:
            self._evict_oldest()

        new_id = session_id or str(uuid.uuid4())
        session = MCPSession(session_id=new_id)
        self._sessions[new_id] = session
        self._last_seen[new_id] = time.monotonic()
        return session

    def get(self, session_id: str) -> MCPSession | None:
        return self._sessions.get(session_id)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _evict_expired(self) -> None:
        now = time.monotonic()
        expired = [sid for sid, ts in self._last_seen.items() if now - ts > self._ttl]
        for sid in expired:
            self._sessions.pop(sid, None)
            self._last_seen.pop(sid, None)

    def _evict_oldest(self) -> None:
        if not self._last_seen:
            return
        oldest = min(self._last_seen, key=lambda k: self._last_seen[k])
        self._sessions.pop(oldest, None)
        self._last_seen.pop(oldest, None)
