# ProcessGuard Demo Video Voiceover Script

Target length: under 5 minutes.

## 0:00-0:30 — Problem

AI agents are moving from chat to action.

That changes the risk model. In a normal chatbot, a bad answer is a problem. But in an action-taking agent, a bad decision can become a real API call: approving a refund, skipping two-factor verification, bypassing manager approval, or writing an incomplete audit trail.

In regulated workflows, agents cannot freestyle. They need runtime boundaries.

## 0:30-1:15 — Solution

ProcessGuard is a runtime compliance firewall for AI agents.

The idea is simple: take the BPMN process that compliance and operations teams already use, and turn it into runtime policy. Before an agent calls a tool, ProcessGuard checks the current BPMN node, the legal next steps, required preconditions, and any gateway rules.

If the action is compliant, it is allowed. If it violates the workflow, it is blocked before the API call leaves the runtime. Every decision is written to the audit log.

## 1:15-2:15 — Live Demo: Compliant Scenario

Here is the compliant refund scenario.

The agent starts with a twelve-thousand-five-hundred-dollar refund request. ProcessGuard reads the BPMN state and allows the first legal step: verify two-factor authentication.

Because the amount is over ten thousand dollars, the BPMN gateway routes the flow through fraud check. That node turns active, then completed.

Next, the agent requests manager approval. Once approval is complete, ProcessGuard allows execute refund.

Finally, the audit log is written. The dashboard shows five allowed decisions, with the BPMN path turning blue while active and green after completion.

This is not just visualization. These are runtime decisions made before each tool call.

## 2:15-3:15 — Violation Demo: Skip 2FA for VIP

Now let us run the violation scenario: skip two-factor authentication for a VIP customer.

The agent reasoning says it wants to skip verification to provide faster service. ProcessGuard detects that intent drift immediately.

Then the agent tries to call request manager approval directly. But the BPMN process says the legal next step is verify two-factor authentication.

ProcessGuard blocks the tool call. The attempted BPMN node turns red, the audit stream records a wrong-order violation, and the corrective message tells the agent exactly how to re-plan: call verify two-factor authentication first.

The important part is timing: the non-compliant approval call never leaves the runtime.

## 3:15-4:00 — Gray-Zone Demo: LLM Judge

Some decisions are not simple yes or no.

In this gray-zone scenario, the refund amount is only four-thousand-eight-hundred dollars, so the deterministic rules can allow a direct refund after verification. But the agent reasoning contains suspicious language: emergency override, just this once.

ProcessGuard flags that as a warning and sends the context to the LLM judge.

The judge returns a verdict, confidence score, rationale, and suggested correction. Here, it blocks the bypass intent and recommends the safe BPMN next step.

So the system is hybrid: rules handle deterministic workflow enforcement, and the judge handles the small gray zone where intent matters.

## 4:00-4:40 — Architecture

The architecture is designed to sit between the agent and real-world action.

UiPath Automation Cloud, Maestro, or another agent runtime provides the entrypoint. The agent proposes a tool call. ProcessGuard middleware intercepts it.

The BPMN engine evaluates the process state, allowed next tasks, gateway conditions, and preconditions. The LLM judge can adjudicate gray-zone reasoning. Then the audit dashboard records the final decision for review.

This lets teams keep their existing BPMN process as the source of truth while making it enforceable at runtime.

## 4:40-5:00 — Human Role

ProcessGuard does not remove humans from regulated workflows.

Humans define the BPMN, approve sensitive workflows, review audit logs, and handle escalations.

The agent gets autonomy inside a controlled boundary. Compliance gets evidence. Operations gets speed without losing control.

That is ProcessGuard: BPMN-enforced action control for regulated AI agents.