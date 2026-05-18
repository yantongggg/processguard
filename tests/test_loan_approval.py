"""Conformance tests for the loan_approval BPMN — second industry vertical.

Proves ProcessGuard enforces a completely different regulatory workflow
(consumer lending) with the same engine.

Regulatory refs:
    MAS Notice 635 — Consumer Credit
    EU Consumer Credit Directive 2023/2225
    FCA CONC 5 — Creditworthiness assessment
"""
import unittest
from pathlib import Path

from processguard import ProcessGuard, load_bpmn
from processguard.models import Decision, ToolCall, ViolationType

BPMN = Path(__file__).parent.parent / "examples" / "loan_approval.bpmn"


class TestLoanApprovalCompliant(unittest.TestCase):
    """Happy-path tests — all compliant flows must ALLOW."""

    def setUp(self):
        self.bpmn = load_bpmn(BPMN)

    def test_small_loan_compliant(self):
        """$20K, DTI 0.28 — full auto-approve path must succeed."""
        g = ProcessGuard(self.bpmn, context={"loan_amount": 20000, "dti_ratio": 0.28})
        for name in [
            "verify_identity", "pull_credit_report", "calculate_dti_ratio",
            "approve_loan", "disburse_funds", "send_regulatory_disclosure",
        ]:
            d = g.check_tool_call(ToolCall(name=name))
            self.assertIs(d.decision, Decision.ALLOW, f"{name} should be ALLOW")
            g.commit(ToolCall(name=name))

    def test_large_loan_underwriter_path(self):
        """$75K loan must route through underwriter_review before approve_loan."""
        g = ProcessGuard(self.bpmn, context={"loan_amount": 75000, "dti_ratio": 0.35})
        for name in [
            "verify_identity", "pull_credit_report", "calculate_dti_ratio",
            "underwriter_review", "approve_loan", "disburse_funds",
            "send_regulatory_disclosure",
        ]:
            d = g.check_tool_call(ToolCall(name=name))
            self.assertIs(d.decision, Decision.ALLOW, f"{name} should be ALLOW")
            g.commit(ToolCall(name=name))

    def test_decline_loan_path(self):
        """High DTI — decline_loan must be allowed after calculate_dti_ratio."""
        g = ProcessGuard(self.bpmn, context={"loan_amount": 30000, "dti_ratio": 0.55})
        for name in ["verify_identity", "pull_credit_report", "calculate_dti_ratio"]:
            g.commit(ToolCall(name=name))
        d = g.check_tool_call(ToolCall(name="decline_loan"))
        self.assertIs(d.decision, Decision.ALLOW)


class TestLoanApprovalViolations(unittest.TestCase):
    """Violation tests — all out-of-order or skipped-step attempts must BLOCK."""

    def setUp(self):
        self.bpmn = load_bpmn(BPMN)

    def test_approve_loan_without_credit_check_blocked(self):
        """Skipping pull_credit_report + calculate_dti_ratio must be blocked.

        Violates MAS Notice 635 §4 — creditworthiness assessment mandatory.
        """
        g = ProcessGuard(self.bpmn, context={"loan_amount": 30000})
        g.commit(ToolCall(name="verify_identity"))
        # Skip pull_credit_report and calculate_dti_ratio
        d = g.check_tool_call(ToolCall(name="approve_loan"))
        self.assertIs(d.decision, Decision.BLOCK)
        self.assertIs(d.violation.type, ViolationType.WRONG_ORDER)

    def test_disburse_before_approval_blocked(self):
        """Attempting disburse_funds before approve_loan must be blocked.

        This is the loan equivalent of executing a refund before 2FA —
        the most critical financial control.
        """
        g = ProcessGuard(self.bpmn, context={"loan_amount": 15000})
        for name in ["verify_identity", "pull_credit_report", "calculate_dti_ratio"]:
            g.commit(ToolCall(name=name))
        # Skip approve_loan → attempt disburse directly
        d = g.check_tool_call(ToolCall(name="disburse_funds"))
        self.assertIs(d.decision, Decision.BLOCK)
        self.assertIs(d.violation.type, ViolationType.WRONG_ORDER)

    def test_disclosure_before_disburse_blocked(self):
        """send_regulatory_disclosure must come AFTER disburse_funds, not before."""
        g = ProcessGuard(self.bpmn, context={"loan_amount": 20000})
        for name in [
            "verify_identity", "pull_credit_report", "calculate_dti_ratio",
            "approve_loan",
        ]:
            g.commit(ToolCall(name=name))
        # Skip disburse_funds → attempt disclosure directly
        d = g.check_tool_call(ToolCall(name="send_regulatory_disclosure"))
        self.assertIs(d.decision, Decision.BLOCK)

    def test_unknown_tool_blocked(self):
        """No tools outside the BPMN process definition are ever allowed."""
        g = ProcessGuard(self.bpmn, context={"loan_amount": 10000})
        d = g.check_tool_call(ToolCall(name="override_credit_score"))
        self.assertIs(d.decision, Decision.BLOCK)
        self.assertIs(d.violation.type, ViolationType.UNKNOWN_TOOL)

    def test_first_step_must_be_verify_identity(self):
        """Agent cannot call any other step as the first action."""
        g = ProcessGuard(self.bpmn, context={"loan_amount": 10000})
        d = g.check_tool_call(ToolCall(name="pull_credit_report"))
        self.assertIs(d.decision, Decision.BLOCK)

    def test_credit_report_before_identity_blocked(self):
        """pull_credit_report requires verify_identity to have completed first."""
        g = ProcessGuard(self.bpmn, context={"loan_amount": 25000})
        # Do NOT commit verify_identity
        d = g.check_tool_call(ToolCall(name="pull_credit_report"))
        self.assertIs(d.decision, Decision.BLOCK)


class TestLoanBpmnLoaded(unittest.TestCase):
    """Sanity checks on the loan_approval BPMN structure."""

    def setUp(self):
        self.bpmn = load_bpmn(BPMN)

    def test_process_id(self):
        self.assertEqual(self.bpmn.process_id, "loan_approval")

    def test_expected_tasks_present(self):
        task_names = {t.name for t in self.bpmn.tasks.values()}
        for expected in [
            "verify_identity", "pull_credit_report", "calculate_dti_ratio",
            "approve_loan", "decline_loan", "disburse_funds",
            "send_regulatory_disclosure",
        ]:
            self.assertIn(expected, task_names, f"Task '{expected}' missing from BPMN")

    def test_requires_extension_present(self):
        """pull_credit_report must declare pg:requires verify_identity."""
        credit_task = self.bpmn.tasks.get("t_pull_credit_report")
        if credit_task is None:
            # Try by name lookup
            credit_task = next(
                (t for t in self.bpmn.tasks.values() if t.name == "pull_credit_report"),
                None,
            )
        self.assertIsNotNone(credit_task)
        self.assertIn("verify_identity", credit_task.requires)


if __name__ == "__main__":
    unittest.main()
