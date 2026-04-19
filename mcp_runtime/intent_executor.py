# mcp_runtime/intent_executor.py

from mcp_runtime.planner import MCPPlanner, PlannerError
from mcp_runtime.workflow import MCPWorkflowRunner
from mcp_runtime.agents.observer import ObserverAgent
from mcp_runtime.safety.envelope import SafetyEnvelope
from mcp_runtime.commit_registry import CommitRegistry


MUTATE_KEYWORDS = {"tag", "delete", "remove", "add", "set", "rename"}


class MCPIntentExecutor:
    """
    Phase 5.6:
    Intent → Agent → Safety → (Confirm?) → Plan → Execute
    """

    def __init__(self, mcp_server):
        self.mcp = mcp_server
        self.planner = MCPPlanner(mcp_server.registry)
        self.runner = MCPWorkflowRunner(mcp_server)
        self.commits = CommitRegistry()

    # ==================================================
    # Execute intent
    # ==================================================
    def execute(self, intent: str, session=None):

        intent_lc = intent.lower()

        # --------------------------------------------------
        # Phase 5.6.3 — Agent resolution
        # --------------------------------------------------
        if session and getattr(session, "agent", None):
            agent = session.agent
        else:
            agent = ObserverAgent()
            if session:
                session.agent = agent  # default agent injection

        intent_meta = agent.classify_intent(intent)

        # --------------------------------------------------
        # Safety pre-upgrade for mutation verbs
        # --------------------------------------------------
        if any(k in intent_lc for k in MUTATE_KEYWORDS):
            if intent_meta["risk"] == "SAFE_READ":
                intent_meta["risk"] = (
                    "RISKY_MUTATE" if "delete" in intent_lc else "SAFE_MUTATE"
                )

        # --------------------------------------------------
        # Safety envelope (DENY / CONFIRM / ALLOW)
        # --------------------------------------------------
        envelope = SafetyEnvelope(agent)
        decision = envelope.enforce(intent_meta)

        # --------------------------------------------------
        # 🔴 HARD STOP: confirmation required (NO PLANNING)
        # --------------------------------------------------
        if decision == "CONFIRM_REQUIRED":
            token = self.commits.create(
                intent=intent,
                agent=agent,                 # store agent OBJECT
                risk=intent_meta["risk"],
                plan=None,                   # plan comes later
            )

            return {
                "confirmation_required": True,
                "commit_token": token,
                "intent": intent,
                "risk": intent_meta["risk"],
                "agent": agent.name,
                "message": "Confirmation required to proceed",
            }

        # --------------------------------------------------
        # Planning (SAFE_READ only)
        # --------------------------------------------------
        try:
            plan = self.planner.plan(intent)
        except PlannerError:
            raise

        if plan.get("clarification_required"):
            return plan

        # --------------------------------------------------
        # Execution
        # --------------------------------------------------
        execution = self.runner.run(
            plan["workflow"]["steps"],
            session=session,
        )

        return {
            "intent": intent,
            "workflow": plan["workflow"],
            "execution": execution,
            "explain": plan.get("explain"),
        }

    # ==================================================
    # Confirm intent
    # ==================================================
    def confirm(self, commit_token: str, session=None):
        """
        Phase 5.6.5:
        Confirm a previously approved intent.
        NOTE: No re-planning occurs here.
        """

        record = self.commits.pop(commit_token)
        if not record:
            raise ValueError("Invalid or expired commit token")

        agent = record["agent"]
        risk = record["risk"]
        intent = record["intent"]

        # --------------------------------------------------
        # Safety re-check with original agent
        # --------------------------------------------------
        envelope = SafetyEnvelope(agent)
        envelope.enforce({"risk": risk})

        # --------------------------------------------------
        # No planner here — mutation execution comes later
        # --------------------------------------------------
        return {
            "confirmed": True,
            "intent": intent,
            "agent": agent.name,
            "message": "Intent confirmed and approved for execution",
        }

