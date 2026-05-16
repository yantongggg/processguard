"""Demo: replay each trace through ProcessGuard and print a clear verdict.

Run:
    python -m demo.demo_week1
or
    python demo/demo_week1.py
"""
from __future__ import annotations

import sys
from pathlib import Path

# Make sibling packages importable when run as a script
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from examples.traces import ALL_TRACES
from processguard import ProcessGuard, load_bpmn
from processguard.models import Decision

console = Console()
BPMN_PATH = ROOT / "examples" / "refund_flow.bpmn"


def replay(trace_name: str, trace) -> dict:
    bpmn = load_bpmn(BPMN_PATH)
    guard = ProcessGuard(bpmn, context=trace.context)

    console.rule(f"[bold cyan]TRACE: {trace_name}")
    console.print(
        f"[dim]agent={trace.agent_name}  context={trace.context}[/dim]\n"
    )

    intent_warnings = 0
    blocks = 0
    allows = 0

    # Interleave reasoning and tool calls 1:1 (simplification for week 1)
    n = max(len(trace.reasoning), len(trace.tool_calls))
    for i in range(n):
        if i < len(trace.reasoning):
            step = trace.reasoning[i]
            decision = guard.check_reasoning(step)
            colour = "yellow" if decision.decision is Decision.WARN else "white"
            console.print(
                f"💭 [italic {colour}]{step.text}[/italic {colour}]"
            )
            if decision.decision is Decision.WARN:
                intent_warnings += 1
                console.print(
                    f"   [yellow]⚠ INTENT DRIFT[/yellow] "
                    f"intent={step.intent!r} target={step.target!r} "
                    f"→ allowed next: {decision.allowed_next_tasks}"
                )

        if i < len(trace.tool_calls):
            call = trace.tool_calls[i]
            decision = guard.check_tool_call(call)
            if decision.decision is Decision.ALLOW:
                allows += 1
                console.print(
                    f"   [green]✅ ALLOW[/green]  {call.name}({_fmt_args(call.args)})"
                )
                guard.commit(call)
            else:
                blocks += 1
                console.print(
                    f"   [red bold]🛑 BLOCK[/red bold]  {call.name}({_fmt_args(call.args)})"
                )
                v = decision.violation
                console.print(
                    Panel(
                        Text.from_markup(
                            f"[red]{v.type.value}[/red]\n"
                            f"{v.message}\n\n"
                            f"[dim]Corrective message injected to agent:[/dim]\n"
                            f"{decision.corrective_message}"
                        ),
                        border_style="red",
                        title="ProcessGuard verdict",
                        title_align="left",
                    )
                )
                # In a real run we'd stop here; for demo we continue to show all violations
                break

    return {
        "trace": trace_name,
        "allows": allows,
        "blocks": blocks,
        "intent_warnings": intent_warnings,
    }


def _fmt_args(d: dict) -> str:
    return ", ".join(f"{k}={v!r}" for k, v in d.items())


def main():
    console.print(
        Panel.fit(
            "[bold]ProcessGuard — Week 1 Demo[/bold]\n"
            "[dim]Runtime compliance firewall for AI agents (BPMN-enforced)[/dim]",
            border_style="cyan",
        )
    )

    results = []
    for name, factory in ALL_TRACES.items():
        results.append(replay(name, factory()))

    # Summary
    console.rule("[bold]SUMMARY")
    table = Table(show_lines=True)
    table.add_column("Trace", style="cyan")
    table.add_column("ALLOWs", justify="right", style="green")
    table.add_column("BLOCKs", justify="right", style="red")
    table.add_column("Intent warnings", justify="right", style="yellow")
    table.add_column("Verdict", style="bold")
    for r in results:
        verdict = (
            "[green]✅ compliant[/green]" if r["blocks"] == 0
            else "[red]🛑 violation caught[/red]"
        )
        table.add_row(
            r["trace"], str(r["allows"]), str(r["blocks"]),
            str(r["intent_warnings"]), verdict,
        )
    console.print(table)


if __name__ == "__main__":
    main()
