"""Week 3-6 unified demo: live agent loop + intent drift + audit log + watch & learn.

This is what we'll record as the submission video.

Run:
    python demo/demo_full.py

Then in another shell:
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

from examples.traces import ALL_TRACES
from processguard import (
    AuditLog,
    ProcessGuard,
    ProcessGuardViolation,
    RuleBasedIntentParser,
    guarded_tools,
    load_bpmn,
)
from processguard.learn import learn_from_traces, to_bpmn_xml
from processguard.models import Decision, ToolCall

console = Console()
BPMN = ROOT / "examples" / "refund_flow.bpmn"
AUDIT_DB = ROOT / "audit.db"


# ---- fake tool implementations ----
def verify_2fa(customer_id: str): return {"verified": True}
def fraud_check(amount: float):   return {"fraud_score": 0.01}
def request_manager_approval(amount: float): return {"approved": True}
def execute_refund(amount: float): return {"refund_id": f"R-{int(amount)}"}
def write_audit_log(event: str):   return {"logged": True}
TOOLS = [verify_2fa, fraud_check, request_manager_approval, execute_refund, write_audit_log]


def run_with_full_stack(trace_name: str, trace):
    bpmn = load_bpmn(BPMN)
    guard = ProcessGuard(bpmn, context=trace.context)
    audit = AuditLog(AUDIT_DB)
    parser = RuleBasedIntentParser(known_tools=[t.name for t in bpmn.tasks.values()])
    tools = guarded_tools(guard, TOOLS)

    console.print(Rule(f"[bold cyan]TRACE: {trace_name}"))
    console.print(f"[dim]context={trace.context}[/dim]\n")

    # Pair reasoning + tool calls 1:1
    n = max(len(trace.reasoning), len(trace.tool_calls))
    for i in range(n):
        # 1. Reasoning → intent drift check
        if i < len(trace.reasoning):
            step = trace.reasoning[i]
            enriched = parser.enrich(step)
            console.print(f"💭 [italic]{step.text}[/italic]")
            warn = guard.check_reasoning(enriched)
            if warn.decision is Decision.WARN:
                console.print(f"   [yellow]⚠ intent drift[/yellow]: "
                              f"target={enriched.target} → allowed: "
                              f"{warn.allowed_next_tasks}")
                audit.record(warn, call=None, trace_id=trace.trace_id,
                             agent_name=trace.agent_name, bpmn_process=bpmn.process_id)

        # 2. Tool call → kill switch
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
                console.print(Panel(exc.decision.corrective_message,
                                    border_style="red", title="ProcessGuard"))
                break
            except Exception as e:
                console.print(f"   [red]tool error: {e}[/red]")
                break


def main():
    if AUDIT_DB.exists():
        AUDIT_DB.unlink()

    console.print(Panel.fit(
        "[bold]ProcessGuard — Full-Stack Demo[/bold]\n"
        "[dim]Kill-switch + intent-drift + audit log + watch-&-learn[/dim]",
        border_style="cyan"))

    # ---- Part 1: enforce on three traces ----
    traces = []
    for name, factory in ALL_TRACES.items():
        trace = factory()
        traces.append(trace)
        run_with_full_stack(name, trace)
        time.sleep(0.1)

    # ---- Part 2: Watch & Learn ----
    console.print(Rule("[bold cyan]Part 2: Watch & Learn — inferring BPMN from traces"))
    # Only learn from the compliant trace (we don't want to learn violations as policy)
    compliant_traces = [t for t in traces if "skip" not in (t.agent_name or "") and
                        len([c for c in t.tool_calls]) >= 4]
    g = learn_from_traces(compliant_traces)
    out = ROOT / "examples" / "learned_refund_flow.bpmn"
    out.write_text(to_bpmn_xml(g, process_id="learned_refund"))
    console.print(f"  [green]✓[/green] Learned {len(g.nodes)} tasks, "
                  f"{len(g.edges)} edges → wrote {out.name}")
    console.print(f"  [dim]required-before rules:[/dim] {g.required_before}")

    # ---- Part 3: round-trip check the learned BPMN ----
    console.print(Rule("[bold cyan]Part 3: round-trip — learned BPMN catches the same violation"))
    learned_bpmn = load_bpmn(out)
    learned_guard = ProcessGuard(learned_bpmn, context={"amount": 9500})
    d = learned_guard.check_tool_call(ToolCall(name="execute_refund"))
    if d.decision is Decision.BLOCK:
        console.print(f"  [green]✓[/green] Learned BPMN correctly blocks "
                      f"premature execute_refund: {d.violation.type.value}")
    else:
        console.print(f"  [yellow]learned BPMN allowed it — refine the learning algo[/yellow]")

    console.print(Rule("[bold green]Done"))
    console.print(f"\n[dim]Audit log written to:[/dim] {AUDIT_DB}")
    console.print("[dim]View dashboard:[/dim] [cyan]processguard dashboard[/cyan] "
                  "→ open http://localhost:8765")


if __name__ == "__main__":
    main()
