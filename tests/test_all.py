"""Tests for middleware, intent parser, learn, audit, and UiPath adapter."""
import json
import tempfile
import unittest
from pathlib import Path

from processguard import (
    AuditLog,
    ProcessGuard,
    ProcessGuardViolation,
    RuleBasedIntentParser,
    guarded_tools,
    load_bpmn,
)
from processguard.learn import learn_from_traces, to_bpmn_xml
from processguard.models import AgentTrace, Decision, ReasoningStep, ToolCall

BPMN = Path(__file__).parent.parent / "examples" / "refund_flow.bpmn"


class TestMiddleware(unittest.TestCase):
    def test_wrap_blocks_illegal_call(self):
        bpmn = load_bpmn(BPMN)
        guard = ProcessGuard(bpmn, context={"amount": 9500})

        def request_manager_approval(amount): return {"approved": True}
        tools = guarded_tools(guard, [request_manager_approval])
        with self.assertRaises(ProcessGuardViolation):
            tools["request_manager_approval"](amount=9500)

    def test_wrap_allows_and_commits(self):
        bpmn = load_bpmn(BPMN)
        guard = ProcessGuard(bpmn, context={"amount": 100})

        def verify_2fa(customer_id): return {"ok": True}
        def execute_refund(amount): return {"refund_id": "X"}
        tools = guarded_tools(guard, [verify_2fa, execute_refund])

        self.assertEqual(tools["verify_2fa"](customer_id="C-1"), {"ok": True})
        # Small amount → execute_refund is legal next
        self.assertEqual(tools["execute_refund"](amount=100), {"refund_id": "X"})


class TestIntentParser(unittest.TestCase):
    def setUp(self):
        bpmn = load_bpmn(BPMN)
        self.parser = RuleBasedIntentParser(
            known_tools=[t.name for t in bpmn.tasks.values()]
        )

    def test_detects_skip_bypass(self):
        p = self.parser.parse("I'll skip the 2FA verification for speed.")
        self.assertEqual(p.intent, "skip")
        self.assertGreaterEqual(p.bypass_score, 0.85)

    def test_detects_shortcut_phrase(self):
        p = self.parser.parse("Let me just execute the refund directly.")
        self.assertGreater(p.bypass_score, 0.5)

    def test_extracts_tool_target(self):
        p = self.parser.parse("Now calling execute_refund for this customer.")
        self.assertEqual(p.target, "execute_refund")

    def test_enrich_preserves_existing_fields(self):
        step = ReasoningStep(text="anything", intent="custom", target="verify_2fa")
        out = self.parser.enrich(step)
        self.assertEqual(out.intent, "custom")
        self.assertEqual(out.target, "verify_2fa")


class TestLearn(unittest.TestCase):
    def test_learn_then_round_trip(self):
        compliant = AgentTrace(
            agent_name="t", context={"amount": 12500},
            tool_calls=[
                ToolCall(name="verify_2fa", args={}),
                ToolCall(name="fraud_check", args={}),
                ToolCall(name="request_manager_approval", args={}),
                ToolCall(name="execute_refund", args={}),
                ToolCall(name="write_audit_log", args={}),
            ],
        )
        g = learn_from_traces([compliant])
        self.assertEqual(len(g.nodes), 5)
        self.assertIn(("verify_2fa", "fraud_check"), g.edges)
        xml = to_bpmn_xml(g)

        with tempfile.NamedTemporaryFile("w", suffix=".bpmn", delete=False) as f:
            f.write(xml)
            path = f.name
        bpmn = load_bpmn(path)
        guard = ProcessGuard(bpmn, context={})
        d = guard.check_tool_call(ToolCall(name="execute_refund"))
        self.assertIs(d.decision, Decision.BLOCK)


class TestAuditLog(unittest.TestCase):
    def test_record_and_recent(self):
        with tempfile.TemporaryDirectory() as d:
            audit = AuditLog(Path(d) / "a.db")
            bpmn = load_bpmn(BPMN)
            guard = ProcessGuard(bpmn, context={"amount": 9500})
            decision = guard.check_tool_call(ToolCall(name="execute_refund"))
            audit.record(decision, call=ToolCall(name="execute_refund"),
                         agent_name="test", bpmn_process="refund_flow")
            rows = audit.recent()
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["decision"], "BLOCK")
            self.assertEqual(audit.stats(), {"BLOCK": 1})


class TestUiPathAdapter(unittest.TestCase):
    def test_session_check_and_commit(self):
        from processguard.integrations.uipath import UiPathGuardSession
        UiPathGuardSession._instances.clear()
        bpmn = load_bpmn(BPMN)
        s = UiPathGuardSession.get_or_create("inst-1", bpmn, {"amount": 100})

        r1 = s.check_and_commit("verify_2fa", {"customer_id": "C"})
        self.assertTrue(r1["allow"])
        r2 = s.check_and_commit("execute_refund", {"amount": 100})
        self.assertTrue(r2["allow"])

    def test_session_blocks_violation(self):
        from processguard.integrations.uipath import UiPathGuardSession
        UiPathGuardSession._instances.clear()
        bpmn = load_bpmn(BPMN)
        s = UiPathGuardSession.get_or_create("inst-2", bpmn, {"amount": 9500})
        r = s.check_and_commit("execute_refund", {"amount": 9500})
        self.assertFalse(r["allow"])
        self.assertEqual(r["decision"], "BLOCK")


if __name__ == "__main__":
    unittest.main()
