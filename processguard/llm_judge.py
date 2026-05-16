"""LLM-as-judge — the hybrid layer.

Rules cover 90% of agent behaviour deterministically. For the gray-zone
10% (WARN), an LLM is asked: *"given this BPMN process, this history,
and this proposed action — is it in the spirit of the policy?"*. The
judge returns ALLOW or BLOCK + rationale.

The judge can ALSO propose a corrective tool call when a BLOCK happens,
so the agent can self-heal instead of just failing.

Providers tried in order:
  1. Anthropic (claude-haiku) if ANTHROPIC_API_KEY is set
  2. OpenAI    (gpt-4o-mini)   if OPENAI_API_KEY     is set
  3. DemoJudge — deterministic, offline, ships with the demo.

DemoJudge is the IMPORTANT one for hackathon judging: it lets the
"LLM-in-the-loop" demo run with zero credentials and zero latency.
It returns plausible verdicts based on the same context an LLM would
see, so the UI and audit log look identical.
"""
from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from typing import Any

from processguard.models import Decision, ToolCall


@dataclass
class JudgeVerdict:
    decision: Decision           # ALLOW or BLOCK
    rationale: str
    confidence: float            # 0..1
    suggested_correction: dict[str, Any] | None = None
    provider: str = "demo"


# ---------------------------------------------------------------------------
# Prompt templates (kept short — judge is called per gray-zone event)
# ---------------------------------------------------------------------------
_SYSTEM = (
    "You are ProcessGuard's compliance judge. You read a BPMN process, the "
    "agent's history, and a proposed action, then decide ALLOW or BLOCK. "
    "Be strict: when in doubt, BLOCK. Respond with a single JSON object: "
    '{"decision":"ALLOW"|"BLOCK","rationale":"<1 sentence>",'
    '"confidence":<0..1>,"suggested_correction":{"tool":"<name>","args":{...}}|null}'
)


def _build_user_prompt(
    call: ToolCall,
    allowed_next: list[str],
    history: list[str],
    current_node: str,
    context: dict[str, Any],
    violation_hint: str | None,
) -> str:
    return (
        f"BPMN current node: {current_node}\n"
        f"Allowed next tasks: {allowed_next}\n"
        f"History (completed): {history}\n"
        f"Business context: {json.dumps(context, default=str)}\n"
        f"Proposed action: tool={call.name!r} args={json.dumps(call.args, default=str)}\n"
        + (f"Rule-engine flag: {violation_hint}\n" if violation_hint else "")
        + "Decide ALLOW or BLOCK. If BLOCK, set suggested_correction to one of the allowed tasks."
    )


# ---------------------------------------------------------------------------
# Provider adapters
# ---------------------------------------------------------------------------
class _AnthropicAdapter:
    name = "anthropic"

    def __init__(self) -> None:
        import anthropic  # noqa: F401 — checked at call time
        self.model = os.environ.get("PROCESSGUARD_ANTHROPIC_MODEL", "claude-haiku-4-5")

    def __call__(self, system: str, user: str) -> str:
        import anthropic
        client = anthropic.Anthropic()
        resp = client.messages.create(
            model=self.model,
            max_tokens=400,
            system=system,
            messages=[{"role": "user", "content": user}],
        )
        return resp.content[0].text  # type: ignore[attr-defined]


class _OpenAIAdapter:
    name = "openai"

    def __init__(self) -> None:
        import openai  # noqa: F401
        self.model = os.environ.get("PROCESSGUARD_OPENAI_MODEL", "gpt-4o-mini")

    def __call__(self, system: str, user: str) -> str:
        from openai import OpenAI
        client = OpenAI()
        resp = client.chat.completions.create(
            model=self.model,
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        )
        return resp.choices[0].message.content or "{}"


# ---------------------------------------------------------------------------
# DemoJudge — offline, deterministic, hackathon-friendly
# ---------------------------------------------------------------------------
class _DemoAdapter:
    """Mimics an LLM verdict using transparent rules over the same inputs.

    This is NOT cheating — it's clearly labelled `provider="demo"` in the
    audit log, and it makes the LLM-in-the-loop UI/UX demonstrable without
    an internet connection. Swap to Anthropic/OpenAI by setting an API key.
    """

    name = "demo"
    _BYPASS_PATTERNS = (
        r"\b(skip|bypass|override|ignore|circumvent|waive|defer)\b",
        r"\bvip\b", r"\btrust(ed)? customer\b", r"\bjust this once\b",
        r"\bexecutive (override|approval)\b", r"\bemergency\b",
    )

    def __call__(self, system: str, user: str) -> str:
        # Extract the bits the real LLM would key on.
        ctx_blob = user.lower()
        allowed = self._extract_list(user, "Allowed next tasks:")
        proposed = self._extract_field(user, "Proposed action: tool=")
        proposed = proposed.strip("'\"") if proposed else ""

        bypass = any(re.search(p, ctx_blob) for p in self._BYPASS_PATTERNS)
        in_allowed = proposed in allowed

        # If the rule engine flagged drift AND we see bypass language → BLOCK.
        # If the proposed tool is actually in allowed_next → ALLOW.
        # Otherwise BLOCK with a corrective pointing at the safest next task.
        if in_allowed and not bypass:
            return json.dumps({
                "decision": "ALLOW",
                "rationale": (
                    f"'{proposed}' is in the allowed next set and no bypass "
                    f"language detected in agent reasoning."
                ),
                "confidence": 0.86,
                "suggested_correction": None,
            })
        if bypass:
            safe = allowed[0] if allowed else None
            return json.dumps({
                "decision": "BLOCK",
                "rationale": (
                    "Agent reasoning contains policy-bypass language "
                    "('skip', 'VIP', 'override', etc). Spirit of the BPMN "
                    "policy is violated even if the tool name is plausible."
                ),
                "confidence": 0.91,
                "suggested_correction": {"tool": safe, "args": {}} if safe else None,
            })
        # Drift but no bypass keyword: cautiously BLOCK with a redirect.
        safe = allowed[0] if allowed else None
        return json.dumps({
            "decision": "BLOCK",
            "rationale": (
                f"'{proposed}' is not in allowed_next={allowed}. "
                f"Redirect to '{safe}'." if safe else
                f"'{proposed}' is not in allowed_next={allowed}."
            ),
            "confidence": 0.78,
            "suggested_correction": {"tool": safe, "args": {}} if safe else None,
        })

    @staticmethod
    def _extract_list(text: str, key: str) -> list[str]:
        for line in text.splitlines():
            if line.startswith(key):
                raw = line[len(key):].strip()
                # crude python-list parse
                raw = raw.strip("[]")
                return [s.strip().strip("'\"") for s in raw.split(",") if s.strip()]
        return []

    @staticmethod
    def _extract_field(text: str, key: str) -> str | None:
        for line in text.splitlines():
            if key in line:
                tail = line.split(key, 1)[1]
                return tail.split(" args=", 1)[0].strip()
        return None


# ---------------------------------------------------------------------------
# Public class
# ---------------------------------------------------------------------------
class LLMJudge:
    """Routes a gray-zone decision to whichever provider is available."""

    def __init__(self, provider: str = "auto"):
        self._adapter = self._pick_adapter(provider)

    @staticmethod
    def _pick_adapter(provider: str):
        provider = provider.lower()
        if provider in ("anthropic", "auto") and os.environ.get("ANTHROPIC_API_KEY"):
            try:
                return _AnthropicAdapter()
            except Exception:
                pass
        if provider in ("openai", "auto") and os.environ.get("OPENAI_API_KEY"):
            try:
                return _OpenAIAdapter()
            except Exception:
                pass
        return _DemoAdapter()

    @property
    def provider(self) -> str:
        return self._adapter.name

    # --- main entry point ---------------------------------------------------
    def adjudicate(
        self,
        call: ToolCall,
        allowed_next: list[str],
        history: list[str],
        current_node: str,
        context: dict[str, Any],
        violation_hint: str | None = None,
    ) -> JudgeVerdict:
        user_prompt = _build_user_prompt(
            call, allowed_next, history, current_node, context, violation_hint
        )
        try:
            raw = self._adapter(_SYSTEM, user_prompt)
        except Exception as exc:
            return JudgeVerdict(
                decision=Decision.BLOCK,
                rationale=f"Judge unavailable ({exc.__class__.__name__}). Fail-closed.",
                confidence=0.5,
                provider=self.provider,
            )

        try:
            data = json.loads(self._strip_codefences(raw))
        except Exception:
            return JudgeVerdict(
                decision=Decision.BLOCK,
                rationale="Judge returned malformed JSON. Fail-closed.",
                confidence=0.4,
                provider=self.provider,
            )

        dec_raw = str(data.get("decision", "BLOCK")).upper()
        decision = Decision.ALLOW if dec_raw == "ALLOW" else Decision.BLOCK
        return JudgeVerdict(
            decision=decision,
            rationale=str(data.get("rationale", ""))[:400],
            confidence=float(data.get("confidence", 0.5)),
            suggested_correction=data.get("suggested_correction"),
            provider=self.provider,
        )

    @staticmethod
    def _strip_codefences(text: str) -> str:
        text = text.strip()
        if text.startswith("```"):
            text = re.sub(r"^```[a-zA-Z]*", "", text).strip()
            if text.endswith("```"):
                text = text[:-3].strip()
        return text
