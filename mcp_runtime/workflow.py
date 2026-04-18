from typing import List, Dict, Any
from uuid import uuid4
from copy import deepcopy

from mcp_runtime.workflow_schema import validate_workflow_schema
from mcp_runtime.safety.envelope import SafetyEnvelope, SafetyEnvelopeError
from mcp_runtime.trace import ExecutionTrace
from mcp_runtime.explain import ExecutionExplainer
from mcp_runtime.explain_contract import validate_explanation_contract  # ✅ NEW

def _get_by_path(data: Dict, path: str):
    cur = data
    for part in path.split("."):
        if not isinstance(cur, dict) or part not in cur:
            return None
        cur = cur[part]
    return cur


class MCPWorkflowRunner:
    """
    Phase 7.4
    - Linear mutation lineage
    - Rollback causality
    - Execution tracing
    - Frozen explanation contract (validated)
    """

    def __init__(self, mcp_server):
        self.mcp = mcp_server

    def run(
        self,
        steps: List[Dict[str, Any]],
        session=None,
    ) -> Dict[str, Any]:

        # --------------------------------------------------
        # Trace lifecycle (per run)
        # --------------------------------------------------
        trace = ExecutionTrace()

        # --------------------------------------------------
        # Schema validation
        # --------------------------------------------------
        validate_workflow_schema(
            {"version": "1.0", "steps": steps},
            mutation_registry=self.mcp.mutations,
        )

        workflow_id = f"wf-{uuid4().hex[:8]}"

        results: List[Dict] = []
        mutations: List[Dict] = []
        rollback_stack: List[Dict] = []
        rollback_results: List[Dict] = []

        current_context: Dict[str, Any] = {}
        safe_context = deepcopy(current_context)

        agent = getattr(session, "agent", None)
        session_id = getattr(session, "session_id", None)

        last_mutation_id = None

        # --------------------------------------------------
        # Execute steps
        # --------------------------------------------------
        for idx, step in enumerate(steps):
            tool = step["tool"]
            mode = step.get("mode", "read")
            inputs = step.get("inputs", {})
            step_context = step.get("context", {})
            rollback = step.get("rollback")
            condition = step.get("when")

            # ----------------------------
            # Conditional execution
            # ----------------------------
            if condition:
                value = _get_by_path(
                    {"context": current_context},
                    condition["path"],
                )
                if value != condition["equals"]:
                    skipped = {
                        "step": idx,
                        "tool": tool,
                        "skipped": True,
                        "reason": {
                            "path": condition["path"],
                            "expected": condition["equals"],
                            "actual": value,
                        },
                    }
                    results.append(skipped)
                    trace.add_step(skipped)
                    continue

            # ----------------------------
            # Mutation policy gate
            # ----------------------------
            if mode == "mutate":
                if not agent:
                    raise RuntimeError("Mutation requires an agent")

                if not agent.allow_mutation:
                    raise SafetyEnvelopeError(
                        f"Agent '{agent.name}' is not allowed to mutate"
                    )

                if self.mcp.auto_mode and not agent.auto_mode_allowed:
                    raise SafetyEnvelopeError(
                        f"Agent '{agent.name}' is not allowed in auto mode"
                    )

                SafetyEnvelope(agent).enforce({"risk": "SAFE_MUTATE"})

                if not rollback_stack:
                    safe_context = deepcopy(current_context)

                entry = self.mcp.mutation_ledger.record(
                    tool=tool,
                    agent=agent.name,
                    session_id=session_id,
                    status="attempted",
                    rollback_tool=rollback.get("tool") if rollback else None,
                    parent_mutation_id=last_mutation_id,
                )

                mutations.append(entry)
                trace.add_mutation(entry)

                if rollback:
                    rollback_stack.append({
                        "tool": rollback["tool"],
                        "inputs": rollback.get("inputs", {}),
                        "reverts_mutation_id": entry["mutation_id"],
                    })

            # ----------------------------
            # Tool execution
            # ----------------------------
            try:
                r = self.mcp.invoke(
                    tool_name=tool,
                    inputs=inputs,
                    context=step_context,
                    session=session,
                )

                current_context = r["context"]

                step_result = {
                    "step": idx,
                    "tool": tool,
                    "mode": mode,
                    "status": r["status"],
                }
                results.append(step_result)
                trace.add_step(step_result)

                if mode == "mutate":
                    entry["status"] = "executed"
                    last_mutation_id = entry["mutation_id"]

            except Exception as e:
                # ----------------------------
                # Rollback (LIFO, causal)
                # ----------------------------
                for rb in reversed(rollback_stack):
                    rb_tool = rb["tool"]
                    try:
                        self.mcp.invoke(
                            tool_name=rb_tool,
                            inputs=rb.get("inputs", {}),
                            context=safe_context,
                            session=session,
                        )

                        self.mcp.mutation_ledger.record(
                            tool=rb_tool,
                            agent=agent.name if agent else "system",
                            session_id=session_id,
                            status="rollback",
                            reverts_mutation_id=rb["reverts_mutation_id"],
                        )

                        rollback_result = {
                            "tool": rb_tool,
                            "status": "rollback",
                            "reverts_mutation_id": rb["reverts_mutation_id"],
                        }
                        rollback_results.append(rollback_result)
                        trace.add_rollback(rollback_result)

                    except Exception as re:
                        rollback_result = {
                            "tool": rb_tool,
                            "status": "rollback_failed",
                            "error": str(re),
                            "reverts_mutation_id": rb["reverts_mutation_id"],
                        }
                        rollback_results.append(rollback_result)
                        trace.add_rollback(rollback_result)

                trace.fail({
                    "step": idx,
                    "tool": tool,
                    "error": str(e),
                })
                trace.finish(safe_context)

                explainer = ExecutionExplainer(trace)
                explanation = explainer.explain_contract()
                validate_explanation_contract(explanation)  # ✅ ENFORCED

                return {
                    "workflow_id": workflow_id,
                    "steps": results,
                    "mutations": mutations,
                    "failed_step": idx,
                    "error": str(e),
                    "rollback_executed": True,
                    "rollback_results": rollback_results,
                    "final_context": safe_context,
                    "trace": trace,
                    "explanation": explanation,
                }

        # --------------------------------------------------
        # Successful completion
        # --------------------------------------------------
        trace.finish(current_context)

        explainer = ExecutionExplainer(trace)
        explanation = explainer.explain_contract()
        validate_explanation_contract(explanation)  # ✅ ENFORCED

        return {
            "workflow_id": workflow_id,
            "steps": results,
            "mutations": mutations,
            "final_context": current_context,
            "trace": trace,
            "explanation": explanation,
        }
