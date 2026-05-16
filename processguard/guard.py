"""The core kill-switch: ALLOW / BLOCK decisions for tool calls."""
from __future__ import annotations

from dataclasses import dataclass, field

from processguard.bpmn_engine import BPMNProcess, BPMNTask
from processguard.models import (
    Decision,
    GuardDecision,
    ReasoningStep,
    ToolCall,
    Violation,
    ViolationType,
)


@dataclass
class _RunState:
    """Mutable per-run state tracked by the guard."""

    current_task_id: str
    completed_task_names: set[str] = field(default_factory=set)
    context: dict = field(default_factory=dict)


class ProcessGuard:
    """Runtime compliance firewall.

    Usage:
        guard = ProcessGuard(bpmn_process, context={"amount": 12500})
        decision = guard.check_tool_call(ToolCall(name="execute_refund"))
        if decision.decision is Decision.BLOCK:
            raise_or_correct(decision.corrective_message)
        else:
            guard.commit(tool_call)  # advance state machine
    """

    def __init__(self, bpmn: BPMNProcess, context: dict | None = None):
        self.bpmn = bpmn
        self.state = _RunState(
            current_task_id=bpmn.start_task_id,
            context=context or {},
        )

    # ---- public API ----
    def update_context(self, **kwargs) -> None:
        self.state.context.update(kwargs)

    def allowed_next(self) -> list[BPMNTask]:
        return self.bpmn.expand_through_gateways(
            self.state.current_task_id, self.state.context
        )

    def check_tool_call(self, call: ToolCall) -> GuardDecision:
        """The kill-switch entry point. Does NOT mutate state."""
        target = self.bpmn.task_by_name(call.name)

        # Unknown tool — not in BPMN at all
        if target is None:
            return self._block(
                ViolationType.UNKNOWN_TOOL,
                f"Tool '{call.name}' is not defined in BPMN process "
                f"'{self.bpmn.process_id}'.",
                call=call,
            )

        allowed = self.allowed_next()
        allowed_ids = {t.id for t in allowed}
        allowed_names = [t.name for t in allowed]

        # Wrong order / unauthorized branch
        if target.id not in allowed_ids:
            return self._block(
                ViolationType.WRONG_ORDER,
                (
                    f"Tool '{call.name}' cannot run now. "
                    f"Current BPMN node: '{self._current_name()}'. "
                    f"Legal next steps: {allowed_names}."
                ),
                call=call,
                bpmn_task=target,
                allowed_names=allowed_names,
            )

        # Preconditions (required prior tasks)
        missing = [r for r in target.requires if r not in self.state.completed_task_names]
        if missing:
            return self._block(
                ViolationType.PRECONDITION_NOT_MET,
                (
                    f"Tool '{call.name}' requires prior completion of "
                    f"{missing}. Compliance bypass attempt detected."
                ),
                call=call,
                bpmn_task=target,
                allowed_names=allowed_names,
            )

        return GuardDecision(
            decision=Decision.ALLOW,
            allowed_next_tasks=allowed_names,
            bpmn_current_node=self._current_name(),
        )

    def check_reasoning(self, step: ReasoningStep) -> GuardDecision:
        """Intent-drift check on a reasoning step. Returns WARN, never BLOCK.

        Looks at parsed (intent, target) and flags if target is a tool the
        agent isn't allowed to call next OR if the justification contains
        bypass language ("skip", "bypass", "override").
        """
        if step.target is None:
            return GuardDecision(decision=Decision.ALLOW)

        allowed = {t.name for t in self.allowed_next()}
        bypass_keywords = ("skip", "bypass", "override", "ignore", "circumvent")
        intent_l = (step.intent or "").lower()
        justification_l = (step.justification or "").lower()

        is_bypass_intent = any(k in intent_l for k in bypass_keywords) or any(
            k in justification_l for k in bypass_keywords
        )

        target_not_allowed = step.target not in allowed and bool(self.bpmn.task_by_name(step.target))

        if is_bypass_intent or target_not_allowed:
            return GuardDecision(
                decision=Decision.WARN,
                violation=Violation(
                    type=ViolationType.INTENT_DRIFT,
                    message=(
                        f"Reasoning suggests bypass: target='{step.target}', "
                        f"intent='{step.intent}'. "
                        f"Allowed next: {sorted(allowed)}."
                    ),
                    offending_reasoning=step,
                    severity="medium",
                ),
                corrective_message=(
                    f"⚠ Intent drift detected. You are about to attempt "
                    f"'{step.target}', which is not in the allowed next steps "
                    f"{sorted(allowed)}. Re-plan before acting."
                ),
                allowed_next_tasks=sorted(allowed),
                bpmn_current_node=self._current_name(),
            )

        return GuardDecision(decision=Decision.ALLOW)

    def commit(self, call: ToolCall) -> None:
        """Advance the state machine. Call only after ALLOW."""
        target = self.bpmn.task_by_name(call.name)
        if target is None:
            raise ValueError(f"Cannot commit unknown tool '{call.name}'")
        self.state.completed_task_names.add(target.name)
        self.state.current_task_id = target.id

    # ---- helpers ----
    def _current_name(self) -> str:
        cur = self.bpmn.tasks.get(self.state.current_task_id)
        return cur.name if cur else self.state.current_task_id

    def _block(
        self,
        vtype: ViolationType,
        message: str,
        call: ToolCall,
        bpmn_task: BPMNTask | None = None,
        allowed_names: list[str] | None = None,
    ) -> GuardDecision:
        allowed_names = allowed_names or [t.name for t in self.allowed_next()]
        corrective = (
            f"🛑 Action BLOCKED by ProcessGuard.\n"
            f"Reason: {message}\n"
            f"You MUST choose your next action from: {allowed_names}.\n"
            f"Re-plan and try again."
        )
        return GuardDecision(
            decision=Decision.BLOCK,
            violation=Violation(
                type=vtype,
                message=message,
                bpmn_task_id=bpmn_task.id if bpmn_task else None,
                bpmn_task_name=bpmn_task.name if bpmn_task else None,
                offending_tool_call=call,
                severity="critical",
            ),
            corrective_message=corrective,
            allowed_next_tasks=allowed_names,
            bpmn_current_node=self._current_name(),
        )
