"""UiPath Automation Cloud / Maestro runtime adapter.

This is the integration surface used by UiPath workflows, Maestro BPMN, or
Agent Builder tools. UiPath remains the orchestrator: it starts the workflow,
decides which activity/tool is about to run, then calls ProcessGuard before the
activity executes. ProcessGuard returns ALLOW/BLOCK plus corrective guidance.

Typical UiPath call sequence:

1. POST /uipath/session/start      -> create or reset a guard session
2. POST /uipath/reasoning/check    -> optional gray-zone intent check
3. POST /uipath/activity/check     -> mandatory pre-activity gate
4. If allow=true, UiPath executes the real activity/tool

The dashboard mounts this router automatically, so all UiPath decisions also
appear in the live SSE audit stream.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any
from uuid import uuid4

from processguard.audit import AuditLog
from processguard.bpmn_engine import BPMNProcess, load_bpmn
from processguard.guard import ProcessGuard
from processguard.llm_judge import LLMJudge
from processguard.models import Decision, GuardDecision, ReasoningStep, ToolCall

try:
    from fastapi import APIRouter, HTTPException
    from pydantic import BaseModel, Field

    _HAS_FASTAPI = True
except ImportError:
    _HAS_FASTAPI = False


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_BPMN_PATH = ROOT / "examples" / "refund_flow.bpmn"
DEFAULT_DB_PATH = ROOT / "audit.db"


def load_uipath_maestro_bpmn(path: Path | str | None = None) -> BPMNProcess:
    """Load a UiPath Maestro BPMN file, or the bundled refund demo BPMN."""
    return load_bpmn(path or DEFAULT_BPMN_PATH)


def _decision_payload(decision: GuardDecision, allow: bool) -> dict[str, Any]:
    violation = decision.violation
    return {
        "allow": allow,
        "decision": decision.decision.value,
        "violation": violation.type.value if violation else None,
        "violation_message": violation.message if violation else None,
        "corrective": decision.corrective_message,
        "allowed_next": decision.allowed_next_tasks,
        "current_node": decision.bpmn_current_node,
        "judge_used": decision.judge_used,
        "judge_provider": decision.judge_provider,
        "judge_verdict": decision.judge_verdict.value if decision.judge_verdict else None,
        "judge_rationale": decision.judge_rationale,
        "judge_confidence": decision.judge_confidence,
        "suggested_correction": decision.suggested_correction,
    }


class UiPathGuardSession:
    """Stateful ProcessGuard session per UiPath process/job instance."""

    _instances: dict[str, "UiPathGuardSession"] = {}

    def __init__(
        self,
        instance_id: str,
        bpmn: BPMNProcess,
        context: dict[str, Any] | None = None,
        agent_name: str = "UiPathAgent",
        trace_id: str | None = None,
        audit: AuditLog | None = None,
        judge: LLMJudge | None = None,
    ):
        self.instance_id = instance_id
        self.agent_name = agent_name
        self.trace_id = trace_id or instance_id
        self.bpmn = bpmn
        self.guard = ProcessGuard(bpmn, context=context, judge=judge or LLMJudge())
        self.audit = audit or AuditLog(DEFAULT_DB_PATH)

    @classmethod
    def start(
        cls,
        instance_id: str | None,
        bpmn: BPMNProcess,
        context: dict[str, Any] | None = None,
        agent_name: str = "UiPathAgent",
        reset: bool = True,
        audit: AuditLog | None = None,
        judge: LLMJudge | None = None,
    ) -> "UiPathGuardSession":
        sid = instance_id or f"uipath-{uuid4()}"
        if reset or sid not in cls._instances:
            cls._instances[sid] = cls(
                sid, bpmn, context=context, agent_name=agent_name,
                audit=audit, judge=judge,
            )
        else:
            cls._instances[sid].guard.update_context(**(context or {}))
        return cls._instances[sid]

    @classmethod
    def get_or_create(
        cls,
        instance_id: str,
        bpmn: BPMNProcess,
        context: dict[str, Any] | None = None,
        agent_name: str = "UiPathAgent",
        audit: AuditLog | None = None,
        judge: LLMJudge | None = None,
    ) -> "UiPathGuardSession":
        return cls.start(
            instance_id, bpmn, context=context, agent_name=agent_name,
            reset=False, audit=audit, judge=judge,
        )

    @classmethod
    def clear(cls, instance_id: str | None = None) -> int:
        if instance_id is None:
            count = len(cls._instances)
            cls._instances.clear()
            return count
        return 1 if cls._instances.pop(instance_id, None) is not None else 0

    def check_reasoning(self, step: ReasoningStep) -> dict[str, Any]:
        decision = self.guard.check_reasoning(step)
        if decision.decision is not Decision.ALLOW or decision.judge_used:
            self.audit.record(
                decision, call=None, trace_id=self.trace_id,
                agent_name=self.agent_name, bpmn_process=self.bpmn.process_id,
            )
        return _decision_payload(decision, allow=decision.decision is not Decision.BLOCK)

    def check_activity(
        self,
        activity_name: str,
        args: dict[str, Any],
        commit_on_allow: bool = True,
    ) -> dict[str, Any]:
        call = ToolCall(name=activity_name, args=args)
        decision = self.guard.check_tool_call(call)
        allow = decision.decision is Decision.ALLOW
        self.audit.record(
            decision, call=call, trace_id=self.trace_id,
            agent_name=self.agent_name, bpmn_process=self.bpmn.process_id,
        )
        payload = _decision_payload(decision, allow=allow)
        if allow and commit_on_allow:
            self.guard.commit(call)
            payload["committed"] = True
        else:
            payload["committed"] = False
        payload["session_current_node"] = self.guard._current_name()
        payload["next_allowed"] = [t.name for t in self.guard.allowed_next()]
        return payload

    def check_and_commit(self, activity_name: str, args: dict[str, Any]) -> dict[str, Any]:
        """Backward-compatible method used by the early Maestro demo tests."""
        return self.check_activity(activity_name, args, commit_on_allow=True)


if _HAS_FASTAPI:

    class SessionStartRequest(BaseModel):
        instance_id: str | None = Field(
            default=None,
            description="UiPath job/process instance id. Generated if omitted.",
        )
        bpmn_path: str | None = Field(
            default=None,
            description="Path to Maestro BPMN on the ProcessGuard host. Omit for demo BPMN.",
        )
        context: dict[str, Any] = Field(default_factory=dict)
        agent_name: str = "UiPathAgent"
        reset: bool = True

    class ReasoningCheckRequest(BaseModel):
        instance_id: str
        bpmn_path: str | None = None
        text: str
        intent: str | None = None
        target: str | None = None
        justification: str | None = None
        context: dict[str, Any] = Field(default_factory=dict)
        agent_name: str = "UiPathAgent"

    class ActivityCheckRequest(BaseModel):
        instance_id: str
        bpmn_path: str | None = None
        next_activity: str = Field(description="UiPath activity/tool name; must match BPMN task name.")
        args: dict[str, Any] = Field(default_factory=dict)
        context: dict[str, Any] = Field(default_factory=dict)
        agent_name: str = "UiPathAgent"
        commit_on_allow: bool = True

    class ResetRequest(BaseModel):
        instance_id: str | None = None

    router = APIRouter(prefix="/uipath", tags=["uipath-automation-cloud"])

    @router.get("/health")
    def uipath_health():
        return {
            "ok": True,
            "component": "ProcessGuard UiPath Automation Cloud adapter",
            "default_bpmn": str(DEFAULT_BPMN_PATH),
            "active_sessions": len(UiPathGuardSession._instances),
        }

    @router.post("/session/start")
    def uipath_session_start(req: SessionStartRequest):
        try:
            bpmn = load_uipath_maestro_bpmn(req.bpmn_path)
        except Exception as exc:
            raise HTTPException(400, f"bpmn load failed: {exc}") from exc
        session = UiPathGuardSession.start(
            req.instance_id, bpmn, context=req.context,
            agent_name=req.agent_name, reset=req.reset,
        )
        return {
            "instance_id": session.instance_id,
            "trace_id": session.trace_id,
            "process_id": bpmn.process_id,
            "current_node": session.guard._current_name(),
            "allowed_next": [t.name for t in session.guard.allowed_next()],
        }

    @router.post("/reasoning/check")
    def uipath_reasoning_check(req: ReasoningCheckRequest):
        try:
            bpmn = load_uipath_maestro_bpmn(req.bpmn_path)
        except Exception as exc:
            raise HTTPException(400, f"bpmn load failed: {exc}") from exc
        session = UiPathGuardSession.get_or_create(
            req.instance_id, bpmn, context=req.context, agent_name=req.agent_name,
        )
        session.guard.update_context(**req.context)
        step = ReasoningStep(
            text=req.text, intent=req.intent,
            target=req.target, justification=req.justification,
        )
        return session.check_reasoning(step)

    @router.post("/activity/check")
    def uipath_activity_check(req: ActivityCheckRequest):
        try:
            bpmn = load_uipath_maestro_bpmn(req.bpmn_path)
        except Exception as exc:
            raise HTTPException(400, f"bpmn load failed: {exc}") from exc
        session = UiPathGuardSession.get_or_create(
            req.instance_id, bpmn, context=req.context, agent_name=req.agent_name,
        )
        session.guard.update_context(**req.context)
        return session.check_activity(req.next_activity, req.args, req.commit_on_allow)

    @router.post("/check")
    def uipath_check(req: ActivityCheckRequest):
        """Backward-compatible alias for early demos."""
        return uipath_activity_check(req)

    @router.post("/reset")
    def uipath_reset(req: ResetRequest):
        cleared = UiPathGuardSession.clear(req.instance_id)
        return {"cleared": cleared, "instance_id": req.instance_id}
