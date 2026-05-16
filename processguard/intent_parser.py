"""Intent-drift detector.

Goal: parse a free-text reasoning step from an LLM and extract structured
(intent, target, justification) so the guard can flag drift BEFORE any tool call.

Two modes:
  - `RuleBasedIntentParser` (default, no API key): regex + keyword extraction.
    Catches the common patterns: "I'll skip X", "let me just X", "bypass Y",
    "going directly to Z".
  - `LLMIntentParser`: uses Claude/OpenAI for harder cases. Slow + costs money,
    only used if explicitly requested.

Both return a `ReasoningStep` with intent/target/justification populated.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from processguard.models import ReasoningStep


BYPASS_VERBS = {
    "skip": "skip",
    "bypass": "bypass",
    "override": "override",
    "ignore": "ignore",
    "circumvent": "bypass",
    "avoid": "skip",
    "omit": "skip",
}

ACTION_VERBS = {
    "execute", "call", "invoke", "run", "trigger", "submit", "send",
    "verify", "check", "request", "approve", "log", "write", "process",
    "perform", "go to", "do",
}

SHORTCUT_PHRASES = [
    r"let me just",
    r"i'?ll just",
    r"going (?:straight|directly) to",
    r"to save time",
    r"to speed (?:this|it) up",
    r"shortcut",
    r"no need to",
    r"why bother",
    r"trust me",
]


@dataclass
class ParsedIntent:
    intent: str | None
    target: str | None
    justification: str | None
    bypass_score: float  # 0.0 (safe) → 1.0 (clear bypass attempt)


class RuleBasedIntentParser:
    """Regex + keyword parser. No external API calls."""

    def __init__(self, known_tools: list[str] | None = None):
        # Normalize tool names for fuzzy matching: split on _ and lowercase
        self.known_tools = known_tools or []
        self._tool_index: dict[str, str] = {}
        for t in self.known_tools:
            self._tool_index[t.lower()] = t
            # Also index the deunderscored form: "verify_2fa" → "verify 2fa"
            self._tool_index[t.lower().replace("_", " ")] = t

    def parse(self, text: str) -> ParsedIntent:
        lower = text.lower()

        # 1. Look for known tool name mentions (preferred signal)
        target = None
        for key, real in self._tool_index.items():
            if key in lower:
                target = real
                break

        # 2. Detect bypass intent
        intent = None
        score = 0.0
        for verb, canonical in BYPASS_VERBS.items():
            if re.search(rf"\b{verb}\b", lower):
                intent = canonical
                score = max(score, 0.85)
                break

        for phrase in SHORTCUT_PHRASES:
            if re.search(phrase, lower):
                score = max(score, 0.7)
                intent = intent or "shortcut"

        # 3. Otherwise extract a benign action verb as intent
        if intent is None:
            for verb in ACTION_VERBS:
                if re.search(rf"\b{verb}\b", lower):
                    intent = verb
                    break

        # 4. Justification = the "because" / "to" clause
        justification = None
        m = re.search(r"\b(?:because|since|to|so that)\b[^.?!]+", lower)
        if m:
            justification = m.group(0).strip()

        return ParsedIntent(
            intent=intent,
            target=target,
            justification=justification,
            bypass_score=score,
        )

    def enrich(self, step: ReasoningStep) -> ReasoningStep:
        """Fill missing intent/target/justification fields on a ReasoningStep."""
        parsed = self.parse(step.text)
        return ReasoningStep(
            text=step.text,
            intent=step.intent or parsed.intent,
            target=step.target or parsed.target,
            justification=step.justification or parsed.justification,
            timestamp=step.timestamp,
        )
