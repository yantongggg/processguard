"""Week 2 demo: middleware in action — bare functions are auto-guarded.

The agent here is a dumb scripted loop, but it demonstrates that:
  1. Tool functions are called normally (no policy code inside them).
  2. ProcessGuard intercepts every call via the wrapper.
  3. On BLOCK, the agent gets a corrective error and re-plans.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from rich.console import Console
from rich.rule import Rule

from processguard import ProcessGuard, load_bpmn
from processguard.middleware import ProcessGuardViolation, guarded_tools

console = Console()


# ---- "Real" tool implementations (no compliance code anywhere!) ----
def verify_2fa(customer_id: str) -> dict:
    return {"verified": True, "customer_id": customer_id}


def fraud_check(amount: float) -> dict:
    return {"fraud_score": 0.02, "amount": amount}


def request_manager_approval(amount: float) -> dict:
    return {"approved": True, "approver": "M-42", "amount": amount}


def execute_refund(amount: float) -> dict:
    return {"refund_id": "R-99001", "amount": amount, "status": "ok"}


def write_audit_log(event: str) -> dict:
    return {"logged": True, "event": event}


REAL_TOOLS = [
    verify_2fa, fraud_check, request_manager_approval,
    execute_refund, write_audit_log,
]


def naive_agent(plan: list[tuple[str, dict]], tools: dict,
                arg_hints: dict[str, dict] | None = None) -> None:
    """A scripted 'agent' that tries each step. On error, prints + retries with hint."""
    arg_hints = arg_hints or {}
    i = 0
    retries = 0
    while i < len(plan) and retries < 5:
        name, kwargs = plan[i]
        try:
            result = tools[name](**kwargs)
            console.print(f"  [green]→ {name}[/green] returned {result}")
            i += 1
            retries = 0
        except ProcessGuardViolation as exc:
            console.print(f"  [red]✗ {name} BLOCKED[/red]")
            console.print(f"    [yellow]agent re-plans with hint:[/yellow] "
                          f"{exc.decision.allowed_next_tasks}")
            hint = exc.decision.allowed_next_tasks[0]
            plan.insert(i, (hint, arg_hints.get(hint, {})))
            retries += 1


def main():
    bpmn = load_bpmn(ROOT / "examples" / "refund_flow.bpmn")

    # ---- Scenario 1: VIP-skip-2FA agent gets corrected ----
    console.print(Rule("[bold cyan]Scenario 1: Agent tries to skip 2FA, gets corrected"))
    guard = ProcessGuard(bpmn, context={"amount": 9500})
    tools = guarded_tools(guard, REAL_TOOLS)

    plan = [
        ("request_manager_approval", {"amount": 9500}),  # ILLEGAL first move
        ("execute_refund",           {"amount": 9500}),
        ("write_audit_log",          {"event": "refund done"}),
    ]
    naive_agent(plan, tools, arg_hints={"verify_2fa": {"customer_id": "C-VIP-007"}})

    # ---- Scenario 2: $100 small refund, no approval needed ----
    console.print(Rule("[bold cyan]Scenario 2: $100 refund, skips approval branch correctly"))
    guard = ProcessGuard(bpmn, context={"amount": 100})
    tools = guarded_tools(guard, REAL_TOOLS)

    plan = [
        ("verify_2fa",      {"customer_id": "C-555"}),
        ("execute_refund",  {"amount": 100}),
        ("write_audit_log", {"event": "small refund"}),
    ]
    naive_agent(plan, tools)

    console.print(Rule("[bold green]Done"))


if __name__ == "__main__":
    main()
