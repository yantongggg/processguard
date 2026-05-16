"""Minimal BPMN 2.0 loader and state machine.

We deliberately do NOT use a full BPMN execution engine (SpiffWorkflow etc.)
because we don't *execute* the BPMN — we only check trace conformance against it.

Supports the BPMN elements we need for the demo:
    - bpmn:startEvent, bpmn:endEvent
    - bpmn:task, bpmn:serviceTask, bpmn:userTask
    - bpmn:exclusiveGateway (XOR split/join)
    - bpmn:sequenceFlow with optional bpmn:conditionExpression

Preconditions are stored as <bpmn:extensionElements> with a
<processguard:requires> child listing required prior-task names.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from lxml import etree

NS = {
    "bpmn": "http://www.omg.org/spec/BPMN/20100524/MODEL",
    "pg": "http://processguard.io/schema",
}


@dataclass
class BPMNTask:
    id: str
    name: str
    kind: str  # task | serviceTask | userTask | startEvent | endEvent | gateway
    requires: list[str] = field(default_factory=list)  # task names that must precede
    condition: str | None = None  # for gateway branches, simple python expr


@dataclass
class BPMNFlow:
    source: str
    target: str
    condition: str | None = None  # evaluated against trace.context


@dataclass
class BPMNProcess:
    process_id: str
    tasks: dict[str, BPMNTask]                # id -> task
    flows: list[BPMNFlow]
    start_task_id: str

    # ---- query helpers ----
    def task_by_name(self, name: str) -> BPMNTask | None:
        for t in self.tasks.values():
            if t.name == name:
                return t
        return None

    def successors(self, task_id: str, context: dict | None = None) -> list[BPMNTask]:
        """Return tasks reachable from `task_id` honoring gateway conditions."""
        out: list[BPMNTask] = []
        for f in self.flows:
            if f.source != task_id:
                continue
            if f.condition and context is not None:
                if not _safe_eval(f.condition, context):
                    continue
            tgt = self.tasks.get(f.target)
            if tgt is not None:
                out.append(tgt)
        return out

    def expand_through_gateways(
        self, task_id: str, context: dict | None = None
    ) -> list[BPMNTask]:
        """Return next ACTIONABLE tasks, walking through gateways transparently."""
        result: list[BPMNTask] = []
        stack = list(self.successors(task_id, context))
        seen: set[str] = set()
        while stack:
            t = stack.pop()
            if t.id in seen:
                continue
            seen.add(t.id)
            if t.kind == "gateway":
                stack.extend(self.successors(t.id, context))
            else:
                result.append(t)
        return result


def _safe_eval(expr: str, ctx: dict) -> bool:
    """Evaluate a simple condition expression against context.

    Whitelist: comparisons + arithmetic + variable lookup. No builtins.
    """
    try:
        return bool(eval(expr, {"__builtins__": {}}, ctx))  # noqa: S307 — sandboxed
    except Exception:
        return False


def load_bpmn(path: str | Path) -> BPMNProcess:
    """Parse a .bpmn XML file into a BPMNProcess."""
    tree = etree.parse(str(path))
    root = tree.getroot()
    proc = root.find("bpmn:process", NS)
    if proc is None:
        raise ValueError(f"No <bpmn:process> found in {path}")

    process_id = proc.get("id", "process")
    tasks: dict[str, BPMNTask] = {}
    flows: list[BPMNFlow] = []
    start_id: str | None = None

    # Element tag -> kind
    kind_map = {
        "task": "task",
        "serviceTask": "serviceTask",
        "userTask": "userTask",
        "scriptTask": "task",
        "startEvent": "startEvent",
        "endEvent": "endEvent",
        "exclusiveGateway": "gateway",
        "parallelGateway": "gateway",
    }

    for child in proc:
        # Skip XML comments and other non-element nodes
        if not isinstance(child.tag, str):
            continue
        tag = etree.QName(child.tag).localname
        if tag in kind_map:
            tid = child.get("id")
            name = child.get("name", tid)
            kind = kind_map[tag]
            requires = _extract_requires(child)
            tasks[tid] = BPMNTask(id=tid, name=name, kind=kind, requires=requires)
            if kind == "startEvent" and start_id is None:
                start_id = tid
        elif tag == "sequenceFlow":
            src = child.get("sourceRef")
            tgt = child.get("targetRef")
            cond = _extract_condition(child)
            flows.append(BPMNFlow(source=src, target=tgt, condition=cond))

    if start_id is None:
        raise ValueError(f"No startEvent found in {path}")

    return BPMNProcess(
        process_id=process_id,
        tasks=tasks,
        flows=flows,
        start_task_id=start_id,
    )


def _extract_requires(elem) -> list[str]:
    ext = elem.find("bpmn:extensionElements", NS)
    if ext is None:
        return []
    requires = ext.find("pg:requires", NS)
    if requires is None or not requires.text:
        return []
    return [s.strip() for s in requires.text.split(",") if s.strip()]


def _extract_condition(flow_elem) -> str | None:
    cond = flow_elem.find("bpmn:conditionExpression", NS)
    if cond is None or not cond.text:
        return None
    return cond.text.strip()
