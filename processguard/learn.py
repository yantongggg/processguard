"""Watch & Learn: infer a draft BPMN process from observed agent/human traces.

Algorithm (v1, single linear path with branches):
  1. Collect all (prev_tool, next_tool) pairs across N traces.
  2. Build a directed graph; nodes = tool names, edges = transitions weighted
     by frequency.
  3. Detect branches: if a node has >1 successor, infer an exclusive gateway.
     If the branch correlates with a context key (e.g., amount > 5000), embed
     it as a conditionExpression.
  4. Emit BPMN 2.0 XML with <pg:requires> hints derived from "this task never
     appeared without that task before it" rules.

This is intentionally simple — it produces a *draft* BPMN the compliance team
edits in bpmn.io, not a finished policy.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass, field

from processguard.models import AgentTrace


@dataclass
class _LearnedGraph:
    nodes: set[str] = field(default_factory=set)
    edges: Counter = field(default_factory=Counter)  # (src, dst) → count
    starts: Counter = field(default_factory=Counter)
    ends: Counter = field(default_factory=Counter)
    # For each (src, dst) edge, record which context key/value distinguished it
    # from sibling edges (e.g., {("gw_amount","fraud"): ("amount", "> 10000")})
    edge_conditions: dict[tuple[str, str], str] = field(default_factory=dict)
    # required_before[X] = set of tools that ALWAYS appeared before X
    required_before: dict[str, set[str]] = field(default_factory=dict)


def learn_from_traces(traces: list[AgentTrace]) -> _LearnedGraph:
    g = _LearnedGraph()
    # Track "ever seen before" set for each tool across all traces
    ever_seen_before: dict[str, set[str]] = defaultdict(lambda: None)  # type: ignore

    for trace in traces:
        names = [tc.name for tc in trace.tool_calls]
        if not names:
            continue
        g.starts[names[0]] += 1
        g.ends[names[-1]] += 1
        seen: set[str] = set()
        for i, n in enumerate(names):
            g.nodes.add(n)
            if i > 0:
                g.edges[(names[i - 1], n)] += 1
            # Update required-before: intersection across all traces
            if ever_seen_before[n] is None:
                ever_seen_before[n] = set(seen)
            else:
                ever_seen_before[n] &= seen
            seen.add(n)

    g.required_before = {k: v for k, v in ever_seen_before.items() if v}

    # Branch-condition inference: when a source has multiple destinations,
    # look at the trace `context` to find which key correlates.
    src_to_dsts: dict[str, list[str]] = defaultdict(list)
    for (src, dst), _ in g.edges.items():
        src_to_dsts[src].append(dst)

    for src, dsts in src_to_dsts.items():
        if len(dsts) < 2:
            continue
        # For each dst, collect contexts from traces where src→dst was taken
        dst_contexts: dict[str, list[dict]] = defaultdict(list)
        for trace in traces:
            names = [tc.name for tc in trace.tool_calls]
            for i in range(len(names) - 1):
                if names[i] == src and names[i + 1] in dsts:
                    dst_contexts[names[i + 1]].append(trace.context)
        # Numeric threshold inference on "amount"-like keys
        for dst, contexts in dst_contexts.items():
            for key in _numeric_keys(contexts):
                values = [c[key] for c in contexts if key in c]
                if not values:
                    continue
                lo, hi = min(values), max(values)
                g.edge_conditions[(src, dst)] = f"{lo} <= {key} <= {hi}"

    return g


def _numeric_keys(contexts: list[dict]) -> set[str]:
    keys: set[str] = set()
    for c in contexts:
        for k, v in c.items():
            if isinstance(v, (int, float)) and not isinstance(v, bool):
                keys.add(k)
    return keys


def to_bpmn_xml(g: _LearnedGraph, process_id: str = "learned_process") -> str:
    """Emit a BPMN 2.0 XML draft from the learned graph."""
    # Pick the most common start/end
    start_tool = g.starts.most_common(1)[0][0] if g.starts else None
    end_tool = g.ends.most_common(1)[0][0] if g.ends else None

    def task_id(name: str) -> str:
        return f"t_{name}"

    parts: list[str] = []
    parts.append('<?xml version="1.0" encoding="UTF-8"?>')
    parts.append(
        '<bpmn:definitions '
        'xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL" '
        'xmlns:pg="http://processguard.io/schema" '
        'id="defs_learned" targetNamespace="http://processguard.io/learned">'
    )
    parts.append(f'  <bpmn:process id="{process_id}" name="Learned process" isExecutable="true">')
    parts.append('    <bpmn:startEvent id="start" name="start"/>')

    # Tasks
    for n in sorted(g.nodes):
        requires = g.required_before.get(n, set())
        if requires:
            req_str = ", ".join(sorted(requires))
            parts.append(
                f'    <bpmn:serviceTask id="{task_id(n)}" name="{n}">\n'
                f'      <bpmn:extensionElements>\n'
                f'        <pg:requires>{req_str}</pg:requires>\n'
                f'      </bpmn:extensionElements>\n'
                f'    </bpmn:serviceTask>'
            )
        else:
            parts.append(f'    <bpmn:serviceTask id="{task_id(n)}" name="{n}"/>')

    parts.append('    <bpmn:endEvent id="end" name="end"/>')

    # Flows
    flow_idx = 0
    if start_tool:
        flow_idx += 1
        parts.append(
            f'    <bpmn:sequenceFlow id="f{flow_idx}" sourceRef="start" '
            f'targetRef="{task_id(start_tool)}"/>'
        )
    for (src, dst), _ in g.edges.most_common():
        flow_idx += 1
        cond = g.edge_conditions.get((src, dst))
        if cond:
            parts.append(
                f'    <bpmn:sequenceFlow id="f{flow_idx}" '
                f'sourceRef="{task_id(src)}" targetRef="{task_id(dst)}">\n'
                f'      <bpmn:conditionExpression>{_xml_escape(cond)}'
                f'</bpmn:conditionExpression>\n'
                f'    </bpmn:sequenceFlow>'
            )
        else:
            parts.append(
                f'    <bpmn:sequenceFlow id="f{flow_idx}" '
                f'sourceRef="{task_id(src)}" targetRef="{task_id(dst)}"/>'
            )
    if end_tool:
        flow_idx += 1
        parts.append(
            f'    <bpmn:sequenceFlow id="f{flow_idx}" '
            f'sourceRef="{task_id(end_tool)}" targetRef="end"/>'
        )

    parts.append('  </bpmn:process>')
    parts.append('</bpmn:definitions>')
    return "\n".join(parts)


def _xml_escape(s: str) -> str:
    return (
        s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    )
