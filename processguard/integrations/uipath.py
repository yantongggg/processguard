"""UiPath Test Cloud / Maestro adapter.

UiPath Maestro orchestrates agentic workflows using BPMN; Test Cloud verifies
them at runtime. ProcessGuard plugs in at two points:

1. **Pre-execution**: ingest a UiPath Maestro `.bpmn` file directly — same
   parser, no transform required (UiPath uses standard BPMN 2.0).
2. **Runtime hook**: expose `/uipath/check` HTTP endpoint that Maestro can call
   before each activity dispatch. Maestro sends {trace_id, current_node,
   next_activity, context}; we reply {allow: bool, corrective: str}.

For the hackathon submission we ship the file-ingest path (proven) and a
FastAPI stub for the runtime hook.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from processguard.bpmn_engine import BPMNProcess, load_bpmn
from processguard.guard import ProcessGuard
from processguard.models import Decision, ToolCall

try:
    from fastapi import APIRouter, HTTPException
    from pydantic import BaseModel

    _HAS_FASTAPI = True
except ImportError:
    _HAS_FASTAPI = False


def load_uipath_maestro_bpmn(path: Path | str) -> BPMNProcess:
    """UiPath Maestro `.bpmn` files are standard BPMN 2.0 — pass through."""
    return load_bpmn(path)


class UiPathGuardSession:
    """Stateful session per UiPath process instance."""

    _instances: dict[str, "UiPathGuardSession"] = {}

    def __init__(self, bpmn: BPMNProcess, context: dict | None = None):
        self.guard = ProcessGuard(bpmn, context=context)

    @classmethod
    def get_or_create(cls, instance_id: str, bpmn: BPMNProcess,
                      context: dict | None = None) -> "UiPathGuardSession":
        if instance_id not in cls._instances:
            cls._instances[instance_id] = cls(bpmn, context)
        return cls._instances[instance_id]

    def check_and_commit(self, activity_name: str, args: dict[str, Any]
                         ) -> dict[str, Any]:
        call = ToolCall(name=activity_name, args=args)
        decision = self.guard.check_tool_call(call)
        allow = decision.decision is Decision.ALLOW
        if allow:
            self.guard.commit(call)
        return {
            "allow": allow,
            "decision": decision.decision.value,
            "violation": decision.violation.type.value if decision.violation else None,
            "corrective": decision.corrective_message,
            "allowed_next": decision.allowed_next_tasks,
            "current_node": decision.bpmn_current_node,
        }


if _HAS_FASTAPI:

    class CheckRequest(BaseModel):
        instance_id: str
        bpmn_path: str
        next_activity: str
        args: dict[str, Any] = {}
        context: dict[str, Any] = {}

    router = APIRouter(prefix="/uipath", tags=["uipath"])

    @router.post("/check")
    def uipath_check(req: CheckRequest):
        try:
            bpmn = load_uipath_maestro_bpmn(req.bpmn_path)
        except Exception as e:
            raise HTTPException(400, f"bpmn load failed: {e}")
        session = UiPathGuardSession.get_or_create(req.instance_id, bpmn, req.context)
        session.guard.update_context(**req.context)
        return session.check_and_commit(req.next_activity, req.args)
