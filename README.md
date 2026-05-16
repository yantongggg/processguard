# ProcessGuard

> **Runtime compliance firewall for AI agents.**
> Make it physically impossible for an AI agent to execute an action that violates a business process rule — at the millisecond before the API call leaves the runtime.

[![Python 3.12+](https://img.shields.io/badge/python-3.12+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

---

## Why this exists

Every other AI-agent observability tool (LangSmith, Helicone, Arize, …) tells you **what your agent did, after the fact**.

Banks, hospitals, and insurance companies don't want a postmortem. They want a **kill switch**: when the agent is about to call `execute_refund()` without `manager_approval()`, **the call never leaves the runtime**.

ProcessGuard takes your existing **BPMN 2.0** process diagram (the one your compliance team already drew) and turns it into a runtime guard that:

1. **ENFORCES** — Wraps every tool call. ALLOW if conformant, BLOCK with corrective re-plan message if not.
2. **OBSERVES** — Parses the agent's reasoning trace and flags *intent drift* before it becomes an action.
3. **LEARNS** — (Week 5+) Watches a human do the workflow once and proposes the BPMN automatically.

---

## Quick start

```bash
git clone https://github.com/yantongggg/processguard.git
cd processguard
python3.12 -m venv .venv && source .venv/bin/activate
pip install -e ".[agents]"

python demo/demo_week1.py
```

You'll see three traces replayed against [`examples/refund_flow.bpmn`](examples/refund_flow.bpmn):

| Trace              | What it does                                          | Verdict                      |
| ------------------ | ----------------------------------------------------- | ---------------------------- |
| `compliant`        | $12,500 refund, follows full flow                     | ✅ 5 ALLOWs, 0 BLOCKs        |
| `skip_2fa_for_vip` | Agent skips 2FA because customer is "VIP"             | 🛑 BLOCK on first tool call  |
| `skip_approval`    | Agent skips manager approval on $8K refund            | 🛑 BLOCK on `execute_refund` |

---

## The hello-world

```python
from processguard import ProcessGuard, load_bpmn
from processguard.models import ToolCall

bpmn = load_bpmn("examples/refund_flow.bpmn")
guard = ProcessGuard(bpmn, context={"amount": 9500})

# Agent decides to skip 2FA and go straight to approval
decision = guard.check_tool_call(ToolCall(name="request_manager_approval"))

print(decision.decision)            # Decision.BLOCK
print(decision.corrective_message)  # 🛑 Action BLOCKED... Legal next steps: ['verify_2fa']
```

That `corrective_message` is designed to be **injected back into the agent's context** as a tool-call result, so the agent re-plans instead of failing.

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│  Your Agent (LangGraph / OpenAI Agents SDK / UiPath / custom)   │
└─────────────────────────┬───────────────────────────────────────┘
                          │ proposed tool call
                          ▼
┌─────────────────────────────────────────────────────────────────┐
│  ProcessGuard.check_tool_call()                                 │
│    1. Is this tool in the BPMN?                                 │
│    2. Is this tool a legal next step from current state?        │
│    3. Are all <pg:requires> preconditions satisfied?            │
│    4. Do gateway conditions evaluate to true?                   │
└─────────────────────────┬───────────────────────────────────────┘
                          │
                ALLOW ◄───┴───► BLOCK + corrective_message
                  │                    │
                  ▼                    ▼
            real API call         re-plan loop
```

The BPMN file is the **single source of truth**. Compliance officers edit it in [bpmn.io](https://bpmn.io); engineers don't write any policy code.

---

## BPMN extensions

ProcessGuard adds one custom namespace, `http://processguard.io/schema`:

```xml
<bpmn:serviceTask id="t_execute_refund" name="execute_refund">
  <bpmn:extensionElements>
    <pg:requires>verify_2fa, manager_approval</pg:requires>
  </bpmn:extensionElements>
</bpmn:serviceTask>
```

Gateway conditions use plain Python expressions over the runtime `context` dict:

```xml
<bpmn:sequenceFlow sourceRef="gw_amount" targetRef="t_fraud_check">
  <bpmn:conditionExpression>amount &gt; 10000</bpmn:conditionExpression>
</bpmn:sequenceFlow>
```

---

## Roadmap

| Week | Deliverable                                                                  | Status |
| ---- | ---------------------------------------------------------------------------- | :----: |
| 1    | BPMN parser + ALLOW/BLOCK engine + 3 example traces + colored demo CLI       | ✅     |
| 2    | LangGraph middleware (auto-intercept every tool call)                        | ⏳     |
| 3    | Live agent demo: Claude Sonnet 4.5 making refund decisions, getting blocked  | ⏳     |
| 4    | Intent-drift detector — parse `<thinking>` blocks for bypass language        | ⏳     |
| 5    | Watch & Learn — record a human session, auto-generate BPMN                   | ⏳     |
| 6    | Next.js dashboard with replay, BPMN viewer, violation timeline               | ⏳     |
| 7    | UiPath Test Cloud integration + demo video                                   | ⏳     |

**Go/no-go checkpoint:** May 31 — if Week 3 live-agent kill switch isn't working, Week 4 intent-drift gets cut.

---

## Project layout

```
processguard/
├── processguard/
│   ├── __init__.py
│   ├── models.py          # Pydantic: Decision, Violation, ToolCall, AgentTrace, GuardDecision
│   ├── bpmn_engine.py     # lxml-based BPMN 2.0 loader (custom, not SpiffWorkflow)
│   └── guard.py           # the kill switch
├── examples/
│   ├── refund_flow.bpmn   # 8-node refund workflow with 3-way gateway
│   └── traces.py          # 3 example agent traces
├── demo/
│   └── demo_week1.py      # the headline demo
└── tests/                 # (Week 2)
```

---

## Anti-goals

These are deliberately **out of scope**:

- ❌ Replacing your agent framework — we wrap, we don't replace.
- ❌ Generic policy DSL — BPMN is the only input format.
- ❌ PDF→BPMN auto-extraction — Watch & Learn (recording a human) is more reliable.
- ❌ Multi-agent orchestration — one process, one agent, one guard.
- ❌ Pre-built integrations for every framework — start with LangGraph + Claude SDK.

---

## License

MIT © 2026 [yantongggg](https://github.com/yantongggg)
