# mcp_runtime/workflow_schema.py

from typing import Dict


class WorkflowSchemaError(ValueError):
    pass


def validate_workflow_schema(workflow: Dict, mutation_registry=None):
    """
    Phase 6.2:
    Validate workflow structure and enforce mutation safety rules.
    """

    if not isinstance(workflow, dict):
        raise WorkflowSchemaError("Workflow must be a dict")

    if workflow.get("version") != "1.0":
        raise WorkflowSchemaError("Unsupported or missing workflow version")

    steps = workflow.get("steps")
    if not isinstance(steps, list) or not steps:
        raise WorkflowSchemaError("Workflow must contain a non-empty 'steps' list")

    for idx, step in enumerate(steps):
        if not isinstance(step, dict):
            raise WorkflowSchemaError(f"Step {idx} must be a dict")

        if "tool" not in step:
            raise WorkflowSchemaError(f"Step {idx} missing 'tool'")

        mode = step.get("mode", "read")
        if mode not in ("read", "mutate"):
            raise WorkflowSchemaError(
                f"Step {idx} has invalid mode '{mode}'"
            )

        if "inputs" in step and not isinstance(step["inputs"], dict):
            raise WorkflowSchemaError(f"Step {idx} 'inputs' must be a dict")

        if "context" in step and not isinstance(step["context"], dict):
            raise WorkflowSchemaError(f"Step {idx} 'context' must be a dict")

        # --------------------------------------------------
        # Conditional execution validation
        # --------------------------------------------------
        if "when" in step:
            when = step["when"]
            if not isinstance(when, dict):
                raise WorkflowSchemaError(f"Step {idx} 'when' must be a dict")
            if "path" not in when or "equals" not in when:
                raise WorkflowSchemaError(
                    f"Step {idx} 'when' requires 'path' and 'equals'"
                )

        # --------------------------------------------------
        # Mutation-specific validation (Phase 6.2)
        # --------------------------------------------------
        if mode == "mutate":
            if mutation_registry is None:
                raise WorkflowSchemaError(
                    f"Step {idx} mutation not allowed without mutation registry"
                )

            tool = step["tool"]

            if not mutation_registry.is_registered(tool):
                raise WorkflowSchemaError(
                    f"Step {idx} uses unregistered mutation tool '{tool}'"
                )

            rollback = step.get("rollback")
            if not isinstance(rollback, dict):
                raise WorkflowSchemaError(
                    f"Step {idx} mutate step requires 'rollback'"
                )

            if "tool" not in rollback:
                raise WorkflowSchemaError(
                    f"Step {idx} rollback missing 'tool'"
                )

            expected_rb = mutation_registry.get_rollback(tool)
            actual_rb = rollback.get("tool")

            if expected_rb != actual_rb:
                raise WorkflowSchemaError(
                    f"Step {idx} rollback tool mismatch for '{tool}': "
                    f"expected '{expected_rb}', got '{actual_rb}'"
                )
