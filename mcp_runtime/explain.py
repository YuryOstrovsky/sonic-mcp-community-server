# mcp_runtime/explain.py

from typing import Dict, Any, List
from mcp_runtime.explain_contract import EXPLANATION_CONTRACT_VERSION


class ExecutionExplainer:
    """
    Phase 7.1.1
    Converts ExecutionTrace into a human-readable explanation.
    """

    def __init__(self, trace):
        self.trace = trace

    def explain(self) -> Dict[str, Any]:
        explanation: Dict[str, Any] = {
            "status": self._derive_status(),
            "summary": self._build_summary(),
            "steps": self._explain_steps(),
            "mutations": self._explain_mutations(),
            "rollbacks": self._explain_rollbacks(),
        }

        if getattr(self.trace, "error", None):
            explanation["error"] = self.trace.error

        return explanation

    # --------------------------------------------------
    # Status derivation
    # --------------------------------------------------
    def _derive_status(self) -> str:
        if getattr(self.trace, "error", None):
            return "failed"
        return "success"

    # --------------------------------------------------
    # Summary
    # --------------------------------------------------
    def _build_summary(self) -> Dict[str, Any]:
        return {
            "steps_executed": len(self.trace.steps),
            "mutations_attempted": len(self.trace.mutations),
            "rollbacks_executed": len(self.trace.rollbacks),
        }

    # --------------------------------------------------
    # Step explanation
    # --------------------------------------------------
    def _explain_steps(self) -> List[Dict[str, Any]]:
        explained = []
        for step in self.trace.steps:
            explained.append({
                "step": step.get("step"),
                "tool": step.get("tool"),
                "mode": step.get("mode", "read"),
                "status": step.get("status"),
                "skipped": step.get("skipped", False),
                "reason": step.get("reason"),
            })
        return explained

    # --------------------------------------------------
    # Mutation explanation
    # --------------------------------------------------
    def _explain_mutations(self) -> List[Dict[str, Any]]:
        explained = []
        for m in self.trace.mutations:
            explained.append({
                "mutation_id": m.get("mutation_id"),
                "tool": m.get("tool"),
                "status": m.get("status"),
                "agent": m.get("agent"),
                "parent_mutation_id": m.get("parent_mutation_id"),
                "rollback_tool": m.get("rollback_tool"),
            })
        return explained

    # --------------------------------------------------
    # Rollback explanation
    # --------------------------------------------------
    def _explain_rollbacks(self) -> List[Dict[str, Any]]:
        explained = []
        for rb in self.trace.rollbacks:
            explained.append({
                "tool": rb.get("tool"),
                "status": rb.get("status"),
                "reverts_mutation_id": rb.get("reverts_mutation_id"),
                "error": rb.get("error"),
            })
        return explained

        # --------------------------------------------------
    # Human-readable explanation
    # --------------------------------------------------
    def explain_text(self) -> str:
        lines = []

        status = self._derive_status()
        lines.append(f"Workflow finished with status: {status}.")

        # Steps
        if self.trace.steps:
            lines.append(f"{len(self.trace.steps)} step(s) were executed:")
            for step in self.trace.steps:
                if step.get("skipped"):
                    lines.append(
                        f"• Step {step['step']}: {step['tool']} was skipped."
                    )
                else:
                    lines.append(
                        f"• Step {step['step']}: executed tool '{step['tool']}' "
                        f"with status '{step.get('status')}'."
                    )
        else:
            lines.append("No steps were executed.")

        # Mutations
        if self.trace.mutations:
            lines.append(f"{len(self.trace.mutations)} mutation(s) were attempted:")
            for m in self.trace.mutations:
                lines.append(
                    f"• Mutation '{m['tool']}' by agent '{m['agent']}' "
                    f"ended with status '{m['status']}'."
                )
        else:
            lines.append("No mutations occurred.")

        # Rollbacks
        if self.trace.rollbacks:
            lines.append(f"{len(self.trace.rollbacks)} rollback(s) were executed:")
            for rb in self.trace.rollbacks:
                lines.append(
                    f"• Rollback tool '{rb['tool']}' reverted mutation "
                    f"{rb.get('reverts_mutation_id')}."
                )
        else:
            lines.append("No rollbacks were required.")

        # Error
        if getattr(self.trace, "error", None):
            lines.append(f"Error encountered: {self.trace.error}")

        return "\n".join(lines)
    
    # --------------------------------------------------
    # Explanation with confidence & outcome
    # --------------------------------------------------
    # --------------------------------------------------
    # Step 7.1.3 — Confidence & outcome classification
    # --------------------------------------------------
    def explain_with_confidence(self) -> dict:
        reasons = []
        confidence = 1.0

        # Base status from trace
        # --------------------------------------------------
        # Derive execution status from trace
        # --------------------------------------------------
        if self.trace.error:
            status = "failed"
        elif self.trace.rollbacks:
            status = "failed_with_recovery"
        else:
            status = "success"


        # Step-level signals
        for step in self.trace.steps:
            step_status = step.get("status")
            if step_status and str(step_status).startswith(("4", "5")):
                reasons.append(
                    f"Step {step['step']} returned non-success status {step_status}"
                )
                confidence -= 0.2

        # Rollback signals
        if self.trace.rollbacks:
            reasons.append("One or more rollbacks were executed")
            confidence -= 0.3

        # Error signal
        if getattr(self.trace, "error", None):
            reasons.append("Execution terminated due to an error")
            confidence -= 0.4

        # Clamp confidence
        confidence = max(0.0, min(1.0, confidence))

        # Outcome classification
        if status == "success" and confidence == 1.0:
            outcome = "success"
        elif status == "success":
            outcome = "partial_success"
        elif self.trace.rollbacks:
            outcome = "failed_with_recovery"
        else:
            outcome = "failed"

        return {
            "outcome": outcome,
            "confidence": round(confidence, 2),
            "reasons": reasons,
        }
    
    def explain_contract(self) -> dict:
        base = self.explain()
        confidence = self.explain_with_confidence()

        return {
            "version": EXPLANATION_CONTRACT_VERSION,  # ✅ REQUIRED
            "status": base["status"],
            "summary": {
                "steps_executed": base["summary"]["steps_executed"],
                "mutations": base["summary"].get("mutations", 0),   # ✅ REQUIRED
                "rollbacks": base["summary"].get("rollbacks", 0),   # ✅ REQUIRED
                "final_status": base["summary"].get("final_status", "unknown"),  # Default value if missing

            },
            "steps": base["steps"],
            "confidence": confidence["confidence"],
            "reasons": confidence["reasons"],
        }






