# mcp_runtime/planner.py

from typing import Dict, List, Optional
from mcp_runtime.workflow_schema import validate_workflow_schema
from mcp_runtime.intent_normalizer import (
    IntentNormalizer,
    IntentNormalizationError,
)
from mcp_runtime.tool_capabilities import (
    ToolCapabilityResolver,
)


class PlannerError(Exception):
    pass


class MCPPlanner:
    """
    Phase 4.x:
    Deterministic intent → workflow planner
    """

    def __init__(self, registry):
        self.registry = registry
        self.normalizer = IntentNormalizer()
        self.cap_resolver = ToolCapabilityResolver(registry)

    # ---------------------------------------------------------
    # Phase 4.8 — context-aware planning
    # ---------------------------------------------------------
    def plan(
        self,
        intent: str,
        prior_context: Optional[Dict] = None,
    ) -> Dict:

        if not intent or not intent.strip():
            raise PlannerError("Empty intent")

        prior_context = prior_context or {}

        clauses = [
            c.strip()
            for c in intent.lower().split(" then ")
            if c.strip()
        ]

        steps: List[Dict] = []
        explain_steps = []
        questions = []

        for clause in clauses:
            try:
                normalized = self.normalizer.normalize(clause)
            except IntentNormalizationError:
                # Ambiguous intent → clarification
                if clause.startswith("show switches"):
                    questions.append({
                        "clause": clause,
                        "missing": ["fabric"],
                    })
                    continue

                if clause.startswith("show device"):
                    questions.append({
                        "clause": clause,
                        "missing": ["device"],
                    })
                    continue

                raise PlannerError(f"Unrecognized intent: '{clause}'")

            action = normalized["action"]
            obj = normalized["object"]
            scope = dict(normalized["scope"])  # copy

            # ---- Inject prior context if missing ----
            if "fabric" not in scope and "fabric" in prior_context:
                scope["fabric"] = prior_context["fabric"]["name"].lower()

            # =====================================================
            # Rule: show switches in fabric <fabric>
            # =====================================================
            if action == "show" and obj == "switches":
                if "fabric" not in scope:
                    questions.append({
                        "clause": clause,
                        "missing": ["fabric"],
                    })
                    continue

                tool = self.cap_resolver.find_tool(
                    action="show",
                    object_="switches",
                    scope_keys=["fabric"],
                )

                steps.append({
                    "tool": tool,
                    "context": {"fabric": scope["fabric"]},
                })

                explain_steps.append({
                    "clause": clause,
                    "tool": tool,
                    "context_used": {"fabric": scope["fabric"]},
                })
                continue

            # =====================================================
            # Rule: show device <device>
            # =====================================================
            if action == "show" and obj == "device":
                if "device" not in scope:
                    questions.append({
                        "clause": clause,
                        "missing": ["device"],
                    })
                    continue

                tool = self.cap_resolver.find_tool(
                    action="show",
                    object_="switches",
                    scope_keys=["device"],
                )

                steps.append({
                    "tool": tool,
                    "context": {"device": scope["device"]},
                })

                explain_steps.append({
                    "clause": clause,
                    "tool": tool,
                    "context_used": {"device": scope["device"]},
                })
                continue

            raise PlannerError(f"Unable to plan clause: '{clause}'")

        if questions:
            return {
                "clarification_required": True,
                "questions": questions,
                "partial_workflow": {
                    "version": "1.0",
                    "steps": steps,
                },
            }

        workflow = {
            "version": "1.0",
            "steps": steps,
        }

        validate_workflow_schema(workflow)

        return {
            "workflow": workflow,
            "explain": {
                "intent": intent,
                "steps": explain_steps,
                "prior_context_used": bool(prior_context),
            },
        }

    # ---------------------------------------------------------
    # Phase 4.7 — clarification resolution (unchanged)
    # ---------------------------------------------------------
    def resolve_clarification(
        self,
        previous_plan: Dict,
        answers: Dict,
    ) -> Dict:

        if not previous_plan.get("clarification_required"):
            raise PlannerError("No clarification required")

        steps = previous_plan.get("partial_workflow", {}).get("steps", [])

        for q in previous_plan["questions"]:
            clause = q["clause"]
            missing = q["missing"]

            for key in missing:
                if key not in answers:
                    raise PlannerError(f"Missing clarification answer for '{key}'")

                value = answers[key].lower()

                if clause.startswith("show switches"):
                    tool = self.cap_resolver.find_tool(
                        action="show",
                        object_="switches",
                        scope_keys=["fabric"],
                    )
                    steps.append({
                        "tool": tool,
                        "context": {"fabric": value},
                    })

                elif clause.startswith("show device"):
                    tool = self.cap_resolver.find_tool(
                        action="show",
                        object_="switches",
                        scope_keys=["device"],
                    )
                    steps.append({
                        "tool": tool,
                        "context": {"device": value},
                    })

        workflow = {
            "version": "1.0",
            "steps": steps,
        }

        validate_workflow_schema(workflow)

        return {
            "workflow": workflow,
            "clarification_resolved": True,
        }
