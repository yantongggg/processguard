"""Middleware: wrap tool functions so ProcessGuard auto-intercepts every call.

Two layers:

1. `guard_tool(guard, fn)` — wraps any sync callable. If BLOCKed, raises
   `ProcessGuardViolation` (which agents see as a tool error and re-plan).
2. `guarded_tools(guard, tools)` — convenience wrapper for a dict/list of tools.
3. `LangGraphGuard` — adapter that wraps a LangGraph `ToolNode` so every tool
   invocation flows through the guard.

Design rule: the guard is the ONLY source of truth. The middleware never makes
a policy decision; it just relays the verdict.
"""
from __future__ import annotations

import functools
import inspect
from typing import Any, Callable

from processguard.guard import ProcessGuard
from processguard.models import Decision, ToolCall


class ProcessGuardViolation(RuntimeError):
    """Raised when the guard BLOCKs a tool call.

    The agent framework will see this as a tool error. The `corrective_message`
    is attached so it can be injected back into the agent's context for replanning.
    """

    def __init__(self, decision):
        self.decision = decision
        super().__init__(decision.corrective_message)


def guard_tool(guard: ProcessGuard, fn: Callable, tool_name: str | None = None) -> Callable:
    """Wrap a single tool function. Raises ProcessGuardViolation on BLOCK."""
    name = tool_name or fn.__name__

    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        call = ToolCall(name=name, args=_capture_args(fn, args, kwargs))
        # Allow tool callers to update guard context via a magic kwarg
        ctx = kwargs.pop("__pg_context__", None)
        if ctx:
            guard.update_context(**ctx)

        decision = guard.check_tool_call(call)
        if decision.decision is Decision.BLOCK:
            raise ProcessGuardViolation(decision)

        result = fn(*args, **kwargs)
        call.result = result
        call.succeeded = True
        guard.commit(call)
        return result

    wrapper.__processguard_wrapped__ = True  # type: ignore[attr-defined]
    wrapper.__processguard_name__ = name      # type: ignore[attr-defined]
    return wrapper


def guarded_tools(
    guard: ProcessGuard, tools: dict[str, Callable] | list[Callable]
) -> dict[str, Callable]:
    """Wrap a collection of tools. Returns a name→wrapped-fn dict."""
    if isinstance(tools, list):
        tools = {t.__name__: t for t in tools}
    return {name: guard_tool(guard, fn, tool_name=name) for name, fn in tools.items()}


def _capture_args(fn: Callable, args: tuple, kwargs: dict) -> dict:
    try:
        sig = inspect.signature(fn)
        bound = sig.bind_partial(*args, **kwargs)
        return dict(bound.arguments)
    except (TypeError, ValueError):
        return {"_args": list(args), "_kwargs": kwargs}


# ---------------------------------------------------------------------------
# LangGraph adapter
# ---------------------------------------------------------------------------
class LangGraphGuard:
    """Wrap a LangGraph tool list so every invocation passes through ProcessGuard.

    Usage:
        from langgraph.prebuilt import create_react_agent
        from processguard.middleware import LangGraphGuard

        guard = ProcessGuard(bpmn, context={"amount": 9500})
        tools = LangGraphGuard(guard).wrap([verify_2fa, request_manager_approval, ...])
        agent = create_react_agent(model, tools)

    On BLOCK the wrapped tool returns a string starting with
    "PROCESSGUARD_BLOCK: ..." which the LLM sees as the tool output and re-plans.
    """

    def __init__(self, guard: ProcessGuard, raise_on_block: bool = False):
        self.guard = guard
        self.raise_on_block = raise_on_block

    def wrap(self, tools: list[Callable]) -> list[Callable]:
        return [self._wrap_one(t) for t in tools]

    def _wrap_one(self, fn: Callable) -> Callable:
        name = getattr(fn, "name", None) or fn.__name__

        @functools.wraps(fn)
        def wrapper(*args, **kwargs) -> Any:
            call = ToolCall(name=name, args=_capture_args(fn, args, kwargs))
            decision = self.guard.check_tool_call(call)
            if decision.decision is Decision.BLOCK:
                if self.raise_on_block:
                    raise ProcessGuardViolation(decision)
                return f"PROCESSGUARD_BLOCK: {decision.corrective_message}"
            result = fn(*args, **kwargs)
            call.result = result
            call.succeeded = True
            self.guard.commit(call)
            return result

        # Preserve LangChain Tool attributes if present
        for attr in ("name", "description", "args_schema"):
            if hasattr(fn, attr):
                try:
                    setattr(wrapper, attr, getattr(fn, attr))
                except Exception:
                    pass
        return wrapper
