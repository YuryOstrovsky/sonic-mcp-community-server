# mcp_runtime/trace.py

from typing import List, Dict, Any
from uuid import uuid4
from datetime import datetime


class ExecutionTrace:
    def __init__(self):
        self.trace_id = f"trace-{uuid4().hex[:8]}"
        self.started_at = datetime.utcnow().isoformat() + "Z"
        self.finished_at = None

        self.steps: List[Dict[str, Any]] = []
        self.mutations: List[Dict[str, Any]] = []
        self.rollbacks: List[Dict[str, Any]] = []

        self.final_context: Dict[str, Any] = {}
        self.error: Dict[str, Any] | None = None

    def add_step(self, step: Dict[str, Any]):
        self.steps.append(step)

    def add_mutation(self, mutation: Dict[str, Any]):
        self.mutations.append(mutation)

    def add_rollback(self, rollback: Dict[str, Any]):
        self.rollbacks.append(rollback)

    def fail(self, error: Dict[str, Any]):
        self.error = error

    def finish(self, final_context: Dict[str, Any]):
        self.final_context = final_context
        self.finished_at = datetime.utcnow().isoformat() + "Z"

