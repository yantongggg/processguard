"""ProcessGuard CLI.

Commands:
  processguard show <bpmn>           — print BPMN structure (tasks + flows)
  processguard check <bpmn> <trace>  — run a JSON trace through the guard
  processguard learn <out.bpmn>      — read traces from stdin (JSON) → draft BPMN
  processguard dashboard             — launch the audit-log dashboard
  processguard demo                  — run the Week 1 demo
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from rich.console import Console
from rich.table import Table

from processguard import ProcessGuard, load_bpmn
from processguard.models import AgentTrace, Decision, ToolCall

console = Console()


def _cmd_show(args):
    bpmn = load_bpmn(args.bpmn)
    console.print(f"[bold cyan]Process[/bold cyan]: {bpmn.process_id}")
    t = Table(title="Tasks")
    t.add_column("ID"); t.add_column("Name"); t.add_column("Kind"); t.add_column("Requires")
    for task in bpmn.tasks.values():
        t.add_row(task.id, task.name, task.kind, ", ".join(task.requires))
    console.print(t)
    f = Table(title="Flows")
    f.add_column("Source"); f.add_column("Target"); f.add_column("Condition")
    for flow in bpmn.flows:
        f.add_row(flow.source, flow.target, flow.condition or "")
    console.print(f)


def _cmd_check(args):
    bpmn = load_bpmn(args.bpmn)
    data = json.loads(Path(args.trace).read_text())
    trace = AgentTrace(**data)
    guard = ProcessGuard(bpmn, context=trace.context)
    n_allow = n_block = 0
    for call in trace.tool_calls:
        d = guard.check_tool_call(call)
        if d.decision is Decision.ALLOW:
            n_allow += 1
            console.print(f"[green]ALLOW[/green]  {call.name}")
            guard.commit(call)
        else:
            n_block += 1
            console.print(f"[red]BLOCK[/red]  {call.name}  — {d.violation.message}")
            break
    console.rule()
    console.print(f"Allowed: {n_allow}   Blocked: {n_block}")
    sys.exit(0 if n_block == 0 else 1)


def _cmd_learn(args):
    from processguard.learn import learn_from_traces, to_bpmn_xml

    raw = sys.stdin.read()
    payload = json.loads(raw)
    traces = [AgentTrace(**t) for t in payload]
    g = learn_from_traces(traces)
    xml = to_bpmn_xml(g)
    Path(args.out).write_text(xml)
    console.print(f"[green]✓[/green] Wrote draft BPMN to {args.out} "
                  f"({len(g.nodes)} tasks, {len(g.edges)} edges)")


def _cmd_dashboard(args):
    try:
        import uvicorn
    except ImportError:
        console.print("[red]Dashboard extras not installed.[/red] "
                      "Run: pip install -e '.[dashboard]'")
        sys.exit(1)
    uvicorn.run("processguard.dashboard:app", host="127.0.0.1",
                port=args.port, reload=False)


def _cmd_demo(args):
    import subprocess
    here = Path(__file__).resolve().parent.parent
    subprocess.run([sys.executable, str(here / "demo" / "demo_week1.py")], check=False)


def main():
    p = argparse.ArgumentParser(prog="processguard")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("show", help="Print BPMN structure")
    s.add_argument("bpmn"); s.set_defaults(func=_cmd_show)

    c = sub.add_parser("check", help="Check a trace against a BPMN")
    c.add_argument("bpmn"); c.add_argument("trace"); c.set_defaults(func=_cmd_check)

    l = sub.add_parser("learn", help="Learn draft BPMN from traces (JSON on stdin)")
    l.add_argument("out"); l.set_defaults(func=_cmd_learn)

    d = sub.add_parser("dashboard", help="Launch audit dashboard")
    d.add_argument("--port", type=int, default=8765); d.set_defaults(func=_cmd_dashboard)

    sub.add_parser("demo", help="Run Week 1 demo").set_defaults(func=_cmd_demo)

    args = p.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
