# mcp_runtime/commit_registry.py

import time
import uuid


class CommitRegistry:
    """
    Phase 5.4:
    - One-time commit tokens
    - TTL expiration
    - Replay protection
    - Audit trail
    """

    DEFAULT_TTL_SECONDS = 60

    def __init__(self):
        self._commits = {}
        self._audit_log = []

    # --------------------------------------------------
    # Commit creation
    # --------------------------------------------------
    def create(self, *, intent, plan, agent, risk, ttl=None):
        token = uuid.uuid4().hex
        now = time.time()

        record = {
            "token": token,
            "intent": intent,
            "plan": plan,
            "agent": agent,
            "risk": risk,
            "created_at": now,
            "expires_at": now + (ttl or self.DEFAULT_TTL_SECONDS),
            "used": False,
        }

        self._commits[token] = record

        self._audit_log.append({
            "event": "CREATED",
            "token": token,
            "agent": agent,
            "risk": risk,
            "timestamp": now,
        })

        return token

    # --------------------------------------------------
    # Commit consumption
    # --------------------------------------------------
    def pop(self, token):
        now = time.time()
        record = self._commits.get(token)

        if not record:
            self._audit_log.append({
                "event": "INVALID_TOKEN",
                "token": token,
                "timestamp": now,
            })
            return None

        if record["used"]:
            self._audit_log.append({
                "event": "REPLAY_ATTEMPT",
                "token": token,
                "timestamp": now,
            })
            return None

        if now > record["expires_at"]:
            self._audit_log.append({
                "event": "EXPIRED",
                "token": token,
                "timestamp": now,
            })
            del self._commits[token]
            return None

        record["used"] = True
        del self._commits[token]

        self._audit_log.append({
            "event": "CONFIRMED",
            "token": token,
            "agent": record["agent"],
            "risk": record["risk"],
            "timestamp": now,
        })

        return record

    # --------------------------------------------------
    # Audit access
    # --------------------------------------------------
    def audit_log(self):
        return list(self._audit_log)

