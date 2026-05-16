"""SQLite-backed audit log for every guard decision.

Why: compliance teams need provable, timestamped, tamper-evident records of
every blocked attempt. The dashboard reads this DB.
"""
from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from processguard.models import GuardDecision, ToolCall

DEFAULT_DB = Path("audit.db")


SCHEMA = """
CREATE TABLE IF NOT EXISTS audit_log (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    ts           TEXT NOT NULL,
    trace_id     TEXT,
    agent_name   TEXT,
    bpmn_process TEXT,
    tool_name    TEXT,
    tool_args    TEXT,
    decision     TEXT NOT NULL,
    violation    TEXT,
    bpmn_node    TEXT,
    allowed_next TEXT,
    corrective   TEXT
);
CREATE INDEX IF NOT EXISTS idx_audit_decision ON audit_log(decision);
CREATE INDEX IF NOT EXISTS idx_audit_ts ON audit_log(ts);
"""


class AuditLog:
    # Class-level subscribers: called with the inserted row dict on every record().
    # Used by the dashboard to fan events out to SSE clients.
    on_record: list[Callable[[dict[str, Any]], None]] = []

    def __init__(self, db_path: Path | str = DEFAULT_DB):
        self.db_path = Path(db_path)
        with self._conn() as c:
            c.executescript(SCHEMA)

    @contextmanager
    def _conn(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def record(
        self,
        decision: GuardDecision,
        call: ToolCall | None,
        trace_id: str | None = None,
        agent_name: str | None = None,
        bpmn_process: str | None = None,
    ) -> int:
        v = decision.violation
        ts = datetime.now(timezone.utc).isoformat()
        with self._conn() as c:
            cur = c.execute(
                "INSERT INTO audit_log (ts, trace_id, agent_name, bpmn_process, "
                "tool_name, tool_args, decision, violation, bpmn_node, "
                "allowed_next, corrective) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (
                    ts,
                    trace_id,
                    agent_name,
                    bpmn_process,
                    call.name if call else None,
                    json.dumps(call.args) if call else None,
                    decision.decision.value,
                    v.type.value if v else None,
                    decision.bpmn_current_node,
                    json.dumps(decision.allowed_next_tasks),
                    decision.corrective_message,
                ),
            )
            row_id = cur.lastrowid

        # Fan-out to live subscribers (best-effort, never crash on subscriber error)
        event = {
            "id": row_id,
            "ts": ts,
            "trace_id": trace_id,
            "agent_name": agent_name,
            "bpmn_process": bpmn_process,
            "tool_name": call.name if call else None,
            "tool_args": call.args if call else None,
            "decision": decision.decision.value,
            "violation": v.type.value if v else None,
            "bpmn_node": decision.bpmn_current_node,
            "allowed_next": decision.allowed_next_tasks,
            "corrective": decision.corrective_message,
            # LLM-judge fields (None when judge disabled)
            "judge_used": decision.judge_used,
            "judge_provider": decision.judge_provider,
            "judge_verdict": decision.judge_verdict.value if decision.judge_verdict else None,
            "judge_rationale": decision.judge_rationale,
            "judge_confidence": decision.judge_confidence,
            "suggested_correction": decision.suggested_correction,
        }
        for cb in list(self.on_record):
            try:
                cb(event)
            except Exception:
                pass
        return row_id

    def recent(self, limit: int = 100) -> list[dict]:
        with self._conn() as c:
            rows = c.execute(
                "SELECT * FROM audit_log ORDER BY id DESC LIMIT ?", (limit,)
            ).fetchall()
            return [dict(r) for r in rows]

    def stats(self) -> dict:
        with self._conn() as c:
            row = c.execute(
                "SELECT decision, COUNT(*) AS n FROM audit_log GROUP BY decision"
            ).fetchall()
            return {r["decision"]: r["n"] for r in row}
