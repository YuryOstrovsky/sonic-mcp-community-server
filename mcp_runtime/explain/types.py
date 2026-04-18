from typing import List, Dict, Optional, TypedDict


class ExplanationSummary(TypedDict):
    steps_executed: int
    mutations: int
    rollbacks: int
    final_status: str


class ExplanationStep(TypedDict):
    step: int
    tool: str
    status: str
    mode: str


class ExecutionExplanation(TypedDict):
    status: str
    summary: ExplanationSummary
    steps: List[ExplanationStep]
    confidence: Optional[float]
    reasons: Optional[List[str]]

