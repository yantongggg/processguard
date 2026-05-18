"""Loan Approval demo — ProcessGuard second industry vertical.

Demonstrates that ProcessGuard is a platform, not a one-flow demo.
Same engine, different BPMN, different industry (consumer lending).

Run:
    python demo/demo_loan.py

Then open the dashboard to see the loan approval BPMN:
    processguard dashboard
    open http://localhost:8765
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from rich.console import Console
from rich.panel import Panel
from rich.rule import Rule

from examples.loan_traces import ALL_TRACES
from processguard import (
    AuditLog,
    ProcessGuard,
    ProcessGuardViolation,
    RuleBasedIntentParser,
    guarded_tools,
    load_bpmn,
)
from processguard.models import Decision

console = Console()
BPMN = ROOT / "examples" / "loan_approval.bpmn"
AUDIT_DB = ROOT / "audit.db"


# ── Simulated tool implementations (no real bank required) ────────────────────
def verify_identity(applicant_id: str):
    return {"kyc_status": "verified", "applicant_id": applicant_id}

def pull_credit_report(applicant_id: str):
    return {"credit_score": 720, "applicant_id": applicant_id}

def calculate_dti_ratio(applicant_id: str):
    return {"dti_ratio": 0.31, "applicant_id": applicant_id}

def underwriter_review(loan_amount: float, dti: float = 0.0):
    return {"underwriter_decision": "approved", "loan_amount": loan_amount}

def approve_loan(loan_amount: float):
    return {"approval_id": f"LA-{int(loan_amount)}", "loan_amount": loan_amount}

def decline_loan(reason: str = "DTI exceeds threshold"):
    return {"declined": True, "reason": reason}

def disburse_funds(loan_amount: float, account: str = ""):
    return {"disbursement_ref": f"D-{int(loan_amount)}", "status": "sent"}

def send_regulatory_disclosure(applicant_id: str):
    return {"disclosure_sent": True, "applicant_id": applicant_id}

TOOLS = [
    verify_identity, pull_credit_report, calculate_dti_ratio,
    underwriter_review, approve_loan, decline_loan,
    disburse_funds, send_regulatory_disclosure,
]


def run_trace(trace_name: str, trace):
    bpmn = load_bpmn(BPMN)
    guard = ProcessGuard(bpmn, context=trace.context)
    audit = AuditLog(AUDIT_DB)
    parser = RuleBasedIntentParser(known_tools=[t.name for t in bpmn.tasks.values()])
    tools = guarded_tools(guard, TOOLS)

    console.print(Rule(f"[bold cyan]LOAN TRACE: {trace_name}"))
    console.print(f"[dim]context={trace.context}[/dim]\n")

    n = max(len(trace.reasoning), len(trace.tool_calls))
    for i in range(n):
        if i < len(trace.reasoning):
            step = trace.reasoning[i]
            enriched = parser.enrich(step)
            console.print(f"💭 [italic]{step.text}[/italic]")
            warn = guard.check_reasoning(enriched)
            if warn.decision is Decision.WARN:
                console.print(
                    f"   [yellow]⚠ intent drift[/yellow]: "
                    f"target={enriched.target} → allowed: {warn.allowed_next_tasks}"
                )
                audit.record(warn, call=None, trace_id=trace.trace_id,
                             agent_name=trace.agent_name, bpmn_process=bpmn.process_id)

        if i < len(trace.tool_calls):
            call = trace.tool_calls[i]
            decision = guard.check_tool_call(call)
            audit.record(decision, call=call, trace_id=trace.trace_id,
                         agent_name=trace.agent_name, bpmn_process=bpmn.process_id)
            try:
                result = tools[call.name](**call.args)
                console.print(f"   [green]✓ {call.name}[/green] = {result}")
            except ProcessGuardViolation as exc:
                console.print(f"   [red bold]🛑 BLOCKED[/red bold] {call.name}")
                console.print(Panel(
                    exc.decision.corrective_message,
                    border_style="red",
                    title="ProcessGuard — Loan Approval Policy Violation",
                ))
                break
            except Exception as e:
                console.print(f"   [red]tool error: {e}[/red]")
                break

    console.print()


def main():
    console.print(Panel.fit(
        "[bold]ProcessGuard — Loan Approval Demo[/bold]\n"
        "[dim]BPMN: examples/loan_approval.bpmn[/dim]\n"
        "[dim]Regulatory refs: MAS Notice 635 · EU Consumer Credit Directive · FCA CONC 5[/dim]",
        border_style="cyan",
    ))

    trace_labels = {
        "small_loan_compliant":     ("✅", "Small loan ($20K, DTI 0.28) — auto-approved"),
        "large_loan_compliant":     ("✅", "Large loan ($75K, DTI 0.35) — underwriter path"),
        "skip_credit_check":        ("🛑", "SKIP credit check — approve without DTI"),
        "disburse_before_approval": ("🛑", "DISBURSE before approval — the dangerous case"),
        "fast_track_vip":           ("🌫️ ", "GRAY ZONE — premium 'fast-track' reasoning"),
    }

    for name, factory in ALL_TRACES.items():
        emoji, label = trace_labels.get(name, ("▶", name))
        console.print(f"\n{emoji} [bold]{label}[/bold]")
        trace = factory()
        run_trace(name, trace)
        time.sleep(0.05)

    console.print(Rule("[bold green]Loan Demo Complete"))
    console.print(f"\n[dim]Audit log appended to:[/dim] {AUDIT_DB}")
    console.print(
        "\n[bold]Key demonstration:[/bold] "
        "same ProcessGuard engine, different BPMN — "
        "proves the platform generalizes across industries."
    )
    console.print("[dim]View dashboard:[/dim] [cyan]processguard dashboard[/cyan] "
                  "→ open http://localhost:8765")


if __name__ == "__main__":
    main()
