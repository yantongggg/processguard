"""Core data models for ProcessGuard."""
from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field


class Decision(str, Enum):
    """Final decision returned by the guard."""

    ALLOW = "ALLOW"
    BLOCK = "BLOCK"
    WARN = "WARN"  # intent-level drift, action not yet committed


class ViolationType(str, Enum):
    SKIPPED_REQUIRED_TASK = "skipped_required_task"
    WRONG_ORDER = "wrong_order"
    UNAUTHORIZED_BRANCH = "unauthorized_branch"
    PRECONDITION_NOT_MET = "precondition_not_met"
    UNKNOWN_TOOL = "unknown_tool"
    INTENT_DRIFT = "intent_drift"


class ReasoningStep(BaseModel):
    """A single chain-of-thought step from the agent."""

    text: str
    # Optional structured extraction (filled by intent parser in Week 4)
    intent: str | None = None
    target: str | None = None
    justification: str | None = None
    timestamp: datetime = Field(default_factory=_utcnow)


class ToolCall(BaseModel):
    """A tool/API call the agent wants to (or did) execute."""

    name: str  # must match a BPMN task name
    args: dict[str, Any] = Field(default_factory=dict)
    timestamp: datetime = Field(default_factory=_utcnow)
    # Filled after execution
    result: Any | None = None
    succeeded: bool | None = None


class AgentTrace(BaseModel):
    """One end-to-end agent run."""

    trace_id: str = Field(default_factory=lambda: str(uuid4()))
    agent_name: str
    started_at: datetime = Field(default_factory=datetime.utcnow)
    reasoning: list[ReasoningStep] = Field(default_factory=list)
    tool_calls: list[ToolCall] = Field(default_factory=list)
    context: dict[str, Any] = Field(default_factory=dict)


class Violation(BaseModel):
    type: ViolationType
    message: str
    bpmn_task_id: str | None = None
    bpmn_task_name: str | None = None
    offending_tool_call: ToolCall | None = None
    offending_reasoning: ReasoningStep | None = None
    severity: str = "high"  # low | medium | high | critical


class GuardDecision(BaseModel):
    """Output of a single ALLOW/BLOCK check."""

    decision: Decision
    violation: Violation | None = None
    corrective_message: str | None = None  # injected into agent on BLOCK
    allowed_next_tasks: list[str] = Field(default_factory=list)
    bpmn_current_node: str | None = None

    # ---- LLM-as-judge fields (Week 8) ----
    # Populated when the optional LLM judge adjudicates a WARN or proposes
    # a correction for a BLOCK. Pure rule output if the judge is disabled.
    judge_used: bool = False
    judge_provider: str | None = None           # "anthropic" | "openai" | "demo"
    judge_verdict: Decision | None = None        # judge's own ALLOW / BLOCK
    judge_rationale: str | None = None           # human-readable reasoning
    judge_confidence: float | None = None        # 0..1
    suggested_correction: dict[str, Any] | None = None  # e.g. {"tool": "...", "args": {...}}
