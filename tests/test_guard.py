"""Smoke tests — run with `python -m unittest tests/test_guard.py`."""
import unittest
from pathlib import Path

from processguard import ProcessGuard, load_bpmn
from processguard.models import Decision, ToolCall, ViolationType

BPMN = Path(__file__).parent.parent / "examples" / "refund_flow.bpmn"


class TestGuard(unittest.TestCase):
    def setUp(self):
        self.bpmn = load_bpmn(BPMN)

    def test_compliant_flow(self):
        g = ProcessGuard(self.bpmn, context={"amount": 12500})
        for name in [
            "verify_2fa", "fraud_check", "request_manager_approval",
            "execute_refund", "write_audit_log",
        ]:
            d = g.check_tool_call(ToolCall(name=name))
            self.assertIs(d.decision, Decision.ALLOW, f"{name} should ALLOW")
            g.commit(ToolCall(name=name))

    def test_skip_2fa_blocked(self):
        g = ProcessGuard(self.bpmn, context={"amount": 9500})
        d = g.check_tool_call(ToolCall(name="request_manager_approval"))
        self.assertIs(d.decision, Decision.BLOCK)
        self.assertIs(d.violation.type, ViolationType.WRONG_ORDER)

    def test_skip_approval_blocked(self):
        g = ProcessGuard(self.bpmn, context={"amount": 8000})
        g.commit(ToolCall(name="verify_2fa"))
        d = g.check_tool_call(ToolCall(name="execute_refund"))
        self.assertIs(d.decision, Decision.BLOCK)

    def test_unknown_tool_blocked(self):
        g = ProcessGuard(self.bpmn, context={"amount": 100})
        d = g.check_tool_call(ToolCall(name="drop_database"))
        self.assertIs(d.decision, Decision.BLOCK)
        self.assertIs(d.violation.type, ViolationType.UNKNOWN_TOOL)

    def test_small_amount_skips_approval(self):
        g = ProcessGuard(self.bpmn, context={"amount": 100})
        g.commit(ToolCall(name="verify_2fa"))
        # $100 ≤ $5K so approval branch is bypassed; execute_refund is legal
        d = g.check_tool_call(ToolCall(name="execute_refund"))
        self.assertIs(d.decision, Decision.ALLOW)


if __name__ == "__main__":
    unittest.main()
