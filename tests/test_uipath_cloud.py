"""Tests for the UiPath Automation Cloud HTTP adapter."""
from fastapi.testclient import TestClient

from processguard.dashboard import app
from processguard.integrations.uipath import UiPathGuardSession


def setup_function():
    UiPathGuardSession.clear()


def test_uipath_health_endpoint():
    client = TestClient(app)
    r = client.get("/uipath/health")
    assert r.status_code == 200
    data = r.json()
    assert data["ok"] is True
    assert "ProcessGuard UiPath Automation Cloud adapter" in data["component"]


def test_uipath_session_start_and_allowed_activity():
    client = TestClient(app)
    start = client.post("/uipath/session/start", json={
        "instance_id": "job-allow",
        "context": {"amount": 100, "customer_id": "C-1"},
        "agent_name": "RefundAgent",
    })
    assert start.status_code == 200
    assert start.json()["allowed_next"] == ["verify_2fa"]

    r1 = client.post("/uipath/activity/check", json={
        "instance_id": "job-allow",
        "next_activity": "verify_2fa",
        "args": {"customer_id": "C-1"},
        "context": {"amount": 100},
        "agent_name": "RefundAgent",
    })
    assert r1.status_code == 200
    assert r1.json()["allow"] is True
    assert r1.json()["committed"] is True
    assert r1.json()["session_current_node"] == "verify_2fa"
    assert r1.json()["next_allowed"] == ["execute_refund"]

    r2 = client.post("/uipath/activity/check", json={
        "instance_id": "job-allow",
        "next_activity": "execute_refund",
        "args": {"amount": 100},
        "context": {"amount": 100},
        "agent_name": "RefundAgent",
    })
    assert r2.status_code == 200
    assert r2.json()["allow"] is True
    assert r2.json()["committed"] is True
    assert r2.json()["session_current_node"] == "execute_refund"
    assert r2.json()["next_allowed"] == ["write_audit_log"]


def test_uipath_activity_block_has_correction():
    client = TestClient(app)
    client.post("/uipath/session/start", json={
        "instance_id": "job-block",
        "context": {"amount": 9500, "customer_id": "C-VIP-007"},
        "agent_name": "RefundAgent",
    })

    r = client.post("/uipath/activity/check", json={
        "instance_id": "job-block",
        "next_activity": "execute_refund",
        "args": {"amount": 9500},
        "context": {"amount": 9500},
        "agent_name": "RefundAgent",
    })
    data = r.json()
    assert r.status_code == 200
    assert data["allow"] is False
    assert data["decision"] == "BLOCK"
    assert data["committed"] is False
    assert data["session_current_node"] == "receive_refund_request"
    assert data["violation"] in {"wrong_order", "precondition_not_met"}
    assert data["suggested_correction"] is not None
    assert data["suggested_correction"]["tool"] == "verify_2fa"


def test_uipath_reasoning_check_uses_judge():
    client = TestClient(app)
    client.post("/uipath/session/start", json={
        "instance_id": "job-gray",
        "context": {"amount": 4800, "customer_id": "C-9090"},
        "agent_name": "RefundAgent",
    })

    r = client.post("/uipath/reasoning/check", json={
        "instance_id": "job-gray",
        "text": "Customer is escalating. Emergency override, just this once.",
        "intent": "override",
        "target": "verify_2fa",
        "justification": "executive override",
        "context": {"amount": 4800},
        "agent_name": "RefundAgent",
    })
    data = r.json()
    assert r.status_code == 200
    assert data["judge_used"] is True
    assert data["judge_provider"] == "demo"
    assert data["decision"] == "BLOCK"
    assert data["judge_confidence"] >= 0.8


def test_uipath_reset_endpoint():
    client = TestClient(app)
    client.post("/uipath/session/start", json={"instance_id": "job-reset"})
    assert "job-reset" in UiPathGuardSession._instances

    r = client.post("/uipath/reset", json={"instance_id": "job-reset"})
    assert r.status_code == 200
    assert r.json()["cleared"] == 1
    assert "job-reset" not in UiPathGuardSession._instances
