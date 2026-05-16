"""Tests for the LLM judge + guard integration."""
from pathlib import Path

from processguard import ProcessGuard
from processguard.bpmn_engine import load_bpmn
from processguard.llm_judge import LLMJudge, JudgeVerdict
from processguard.models import Decision, ReasoningStep, ToolCall

BPMN = Path(__file__).parent.parent / "examples" / "refund_flow.bpmn"


def test_demo_judge_blocks_bypass_reasoning():
    judge = LLMJudge()
    assert judge.provider == "demo"  # no API keys in CI
    bpmn = load_bpmn(BPMN)
    guard = ProcessGuard(bpmn, context={"amount": 9500}, judge=judge)

    step = ReasoningStep(
        text="VIP customer, skip 2FA this once",
        intent="skip", target="request_manager_approval",
        justification="VIP override",
    )
    d = guard.check_reasoning(step)

    assert d.judge_used is True
    assert d.judge_provider == "demo"
    assert d.decision is Decision.BLOCK  # judge promoted WARN -> BLOCK
    assert d.judge_verdict is Decision.BLOCK
    assert d.suggested_correction is not None
    assert d.suggested_correction["tool"] == "verify_2fa"


def test_judge_correction_on_block():
    judge = LLMJudge()
    bpmn = load_bpmn(BPMN)
    guard = ProcessGuard(bpmn, context={"amount": 12500}, judge=judge)

    # Try to execute_refund as the very first call -> rule BLOCK,
    # judge then proposes a corrective tool call.
    d = guard.check_tool_call(ToolCall(name="execute_refund", args={"amount": 12500}))
    assert d.decision is Decision.BLOCK
    assert d.judge_used is True
    assert d.suggested_correction is not None
    assert d.suggested_correction["tool"] in {t.name for t in guard.allowed_next()}


def test_guard_without_judge_unchanged():
    bpmn = load_bpmn(BPMN)
    guard = ProcessGuard(bpmn, context={"amount": 12500})  # no judge

    d = guard.check_tool_call(ToolCall(name="execute_refund"))
    assert d.decision is Decision.BLOCK
    assert d.judge_used is False
    assert d.judge_provider is None


def test_demo_judge_allows_in_path_action():
    judge = LLMJudge()
    bpmn = load_bpmn(BPMN)
    guard = ProcessGuard(bpmn, context={"amount": 1000}, judge=judge)

    # In-path tool call with no bypass language → judge should NOT be invoked
    # (rule engine returns ALLOW immediately).
    d = guard.check_tool_call(ToolCall(name="verify_2fa"))
    assert d.decision is Decision.ALLOW
    assert d.judge_used is False
