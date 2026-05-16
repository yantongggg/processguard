"""ProcessGuard live dashboard — FastAPI + bpmn-js + SSE + in-browser demo.

Run:
    processguard dashboard
    open http://127.0.0.1:8765

Features:
  A. bpmn-js viewer of the active process; current node = blue,
     blocked attempts flash red, completed = green.
  B. SSE stream — every guard decision appears instantly (no polling).
  C. Timeline panel (vis-timeline) — multi-trace event timeline.
  D. In-browser demo runner — pick a scenario, click Run, watch it live.
"""
from __future__ import annotations

import asyncio
import json
from pathlib import Path
from queue import Empty, Queue
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
from pydantic import BaseModel

from processguard.audit import AuditLog
from processguard.bpmn_engine import load_bpmn

# ---------------------------------------------------------------------------
# App + state
# ---------------------------------------------------------------------------
app = FastAPI(title="ProcessGuard")
ROOT = Path(__file__).resolve().parent.parent
DB_PATH = ROOT / "audit.db"
BPMN_PATH = ROOT / "examples" / "refund_flow.bpmn"
audit = AuditLog(DB_PATH)

# Mount UiPath runtime hook (optional)
try:
    from processguard.integrations.uipath import router as uipath_router
    app.include_router(uipath_router)
except Exception:
    pass

# SSE subscriber queues (one per connected client)
_subscribers: list[Queue] = []


def _fanout(event: dict[str, Any]) -> None:
    """AuditLog callback — push the event to every connected SSE client."""
    for q in list(_subscribers):
        try:
            q.put_nowait(event)
        except Exception:
            pass


# Register fan-out as a class-level subscriber (works for every AuditLog instance)
if _fanout not in AuditLog.on_record:
    AuditLog.on_record.append(_fanout)


# ---------------------------------------------------------------------------
# Static API
# ---------------------------------------------------------------------------
@app.get("/api/bpmn")
def api_bpmn():
    if not BPMN_PATH.exists():
        raise HTTPException(404, "BPMN file not found")
    return JSONResponse({
        "xml": BPMN_PATH.read_text(),
        "task_name_to_id": _task_name_to_id(),
    })


@app.get("/api/recent")
def api_recent(limit: int = 100):
    return JSONResponse(audit.recent(limit=limit))


@app.get("/api/stats")
def api_stats():
    return JSONResponse(audit.stats())


def _task_name_to_id() -> dict[str, str]:
    bpmn = load_bpmn(BPMN_PATH)
    return {t.name: t.id for t in bpmn.tasks.values()}


# ---------------------------------------------------------------------------
# SSE
# ---------------------------------------------------------------------------
@app.get("/api/stream")
async def api_stream(request: Request):
    """Server-Sent Events stream of every new audit event."""
    q: Queue = Queue(maxsize=1000)
    _subscribers.append(q)

    async def gen():
        try:
            yield f"event: hello\ndata: {json.dumps({'subscribers': len(_subscribers)})}\n\n"
            while True:
                if await request.is_disconnected():
                    break
                try:
                    event = q.get_nowait()
                    yield f"event: decision\ndata: {json.dumps(event, default=str)}\n\n"
                except Empty:
                    await asyncio.sleep(0.1)
                    # heartbeat every ~30 idle cycles
                    yield ": ping\n\n"
                    await asyncio.sleep(0)
        finally:
            try:
                _subscribers.remove(q)
            except ValueError:
                pass

    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache",
                                      "X-Accel-Buffering": "no"})


# ---------------------------------------------------------------------------
# Demo runner (D)
# ---------------------------------------------------------------------------
class RunRequest(BaseModel):
    scenario: str  # "compliant" | "skip_2fa_for_vip" | "skip_approval" | "all"
    reset: bool = False


@app.post("/api/demo/run")
async def api_demo_run(req: RunRequest):
    """Run a demo scenario in-process. Events stream out via SSE."""
    # Lazy import (so dashboard works without examples on path)
    import sys
    sys.path.insert(0, str(ROOT))
    from examples.traces import ALL_TRACES  # type: ignore
    from processguard import ProcessGuard
    from processguard.models import Decision

    if req.reset and DB_PATH.exists():
        DB_PATH.unlink()
        global audit
        audit = AuditLog(DB_PATH)

    bpmn = load_bpmn(BPMN_PATH)

    if req.scenario == "all":
        scenarios = list(ALL_TRACES.items())
    elif req.scenario in ALL_TRACES:
        scenarios = [(req.scenario, ALL_TRACES[req.scenario])]
    else:
        raise HTTPException(400, f"unknown scenario '{req.scenario}'")

    async def run():
        for name, factory in scenarios:
            trace = factory()
            guard = ProcessGuard(bpmn, context=trace.context)
            local_audit = AuditLog(DB_PATH)
            n = max(len(trace.reasoning), len(trace.tool_calls))
            for i in range(n):
                if i < len(trace.reasoning):
                    step = trace.reasoning[i]
                    d = guard.check_reasoning(step)
                    if d.decision is Decision.WARN:
                        local_audit.record(
                            d, call=None, trace_id=trace.trace_id,
                            agent_name=trace.agent_name,
                            bpmn_process=bpmn.process_id,
                        )
                if i < len(trace.tool_calls):
                    call = trace.tool_calls[i]
                    d = guard.check_tool_call(call)
                    local_audit.record(
                        d, call=call, trace_id=trace.trace_id,
                        agent_name=trace.agent_name,
                        bpmn_process=bpmn.process_id,
                    )
                    if d.decision is Decision.ALLOW:
                        guard.commit(call)
                    else:
                        break
                await asyncio.sleep(0.6)  # visible pacing for the UI
            await asyncio.sleep(0.8)

    asyncio.create_task(run())
    return {"started": True, "scenarios": [s[0] for s in scenarios]}


@app.post("/api/demo/reset")
async def api_demo_reset():
    global audit
    if DB_PATH.exists():
        DB_PATH.unlink()
    audit = AuditLog(DB_PATH)
    return {"reset": True}


# ---------------------------------------------------------------------------
# Backward-compat partial (HTMX)
# ---------------------------------------------------------------------------
@app.get("/_partial/dashboard", response_class=HTMLResponse)
def partial_dashboard():
    stats = audit.stats()
    rows = audit.recent(50)
    total = sum(stats.values())
    body = "".join(
        f"<tr><td>{r['ts'][:19].replace('T', ' ')}</td>"
        f"<td>{r['agent_name'] or ''}</td>"
        f"<td>{r['tool_name'] or ''}</td>"
        f"<td>{r['decision']}</td>"
        f"<td>{r['violation'] or ''}</td></tr>"
        for r in rows
    )
    return (
        f"<p>Total: {total} | ALLOW: {stats.get('ALLOW',0)} | "
        f"BLOCK: {stats.get('BLOCK',0)} | WARN: {stats.get('WARN',0)}</p>"
        f"<table>{body}</table>"
    )


# ---------------------------------------------------------------------------
# Main UI
# ---------------------------------------------------------------------------
@app.get("/", response_class=HTMLResponse)
def index():
    return INDEX_HTML


INDEX_HTML = r"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8"/>
  <title>ProcessGuard — Where AI meets compliance</title>
  <link rel="preconnect" href="https://fonts.googleapis.com"/>
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin/>
  <link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700;800;900&family=JetBrains+Mono:wght@400;500&display=swap" rel="stylesheet"/>
  <link rel="stylesheet" href="https://unpkg.com/bpmn-js@17.11.1/dist/assets/diagram-js.css"/>
  <link rel="stylesheet" href="https://unpkg.com/bpmn-js@17.11.1/dist/assets/bpmn-js.css"/>
  <link rel="stylesheet" href="https://unpkg.com/bpmn-js@17.11.1/dist/assets/bpmn-font/css/bpmn.css"/>
  <link rel="stylesheet" href="https://unpkg.com/vis-timeline@7.7.3/styles/vis-timeline-graph2d.min.css"/>
  <script src="https://unpkg.com/bpmn-js@17.11.1/dist/bpmn-navigated-viewer.development.js"></script>
  <script src="https://unpkg.com/vis-timeline@7.7.3/standalone/umd/vis-timeline-graph2d.min.js"></script>
  <style>
    :root {
      --bg:#000000;
      --bg-soft:#08070d;
      --surface:rgba(18, 16, 28, 0.55);
      --surface-strong:rgba(24, 21, 36, 0.78);
      --hairline:rgba(255,255,255,0.08);
      --hairline-strong:rgba(255,255,255,0.16);
      --text:#f5f5f7;
      --text-dim:#a8a8b3;
      --text-mute:#6a6a78;
      --cyan:#00e5ff;
      --violet:#b388ff;
      --lime:#c6ff00;
      --rose:#ff4d7d;
      --amber:#ffb347;
    }
    * { box-sizing: border-box; }
    html, body {
      margin:0; padding:0; min-height:100%; background:var(--bg); color:var(--text);
      font-family:'Inter',-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;
      font-feature-settings:'ss01','cv11';
      -webkit-font-smoothing:antialiased;
      letter-spacing:-0.01em;
    }
    body {
      background:
        radial-gradient(900px 600px at 12% -10%,  rgba(179,136,255,0.22), transparent 60%),
        radial-gradient(900px 700px at 95% 10%,   rgba(0,229,255,0.18),   transparent 60%),
        radial-gradient(700px 600px at 60% 110%,  rgba(198,255,0,0.10),   transparent 60%),
        radial-gradient(1200px 800px at 50% 50%,  rgba(255,77,125,0.05),  transparent 70%),
        var(--bg);
      background-attachment: fixed;
      overflow-x:hidden;
    }
    /* Animated mesh blob */
    body::before {
      content:''; position:fixed; inset:0; pointer-events:none; z-index:0;
      background:
        radial-gradient(400px 400px at var(--mx,30%) var(--my,30%), rgba(0,229,255,0.10), transparent 70%);
      transition: background 0.6s ease;
    }
    /* Grain overlay */
    body::after {
      content:''; position:fixed; inset:0; pointer-events:none; z-index:1; opacity:0.035;
      background-image:url("data:image/svg+xml;utf8,<svg viewBox='0 0 200 200' xmlns='http://www.w3.org/2000/svg'><filter id='n'><feTurbulence type='fractalNoise' baseFrequency='0.85' numOctaves='2'/></filter><rect width='100%25' height='100%25' filter='url(%23n)'/></svg>");
    }

    nav {
      position:relative; z-index:5;
      display:flex; align-items:center; justify-content:space-between;
      padding:22px 48px;
      border-bottom:1px solid var(--hairline);
      backdrop-filter: blur(20px);
      background:rgba(0,0,0,0.35);
    }
    .brand { display:flex; align-items:center; gap:12px; font-weight:700; font-size:15px; letter-spacing:-0.02em; }
    .brand-mark {
      width:28px; height:28px; border-radius:8px;
      background:conic-gradient(from 220deg, var(--cyan), var(--violet), var(--lime), var(--cyan));
      filter:saturate(1.2);
      position:relative;
    }
    .brand-mark::after {
      content:''; position:absolute; inset:5px; border-radius:5px; background:#000;
    }
    .brand-mark::before {
      content:''; position:absolute; inset:9px; border-radius:3px;
      background:conic-gradient(from 220deg, var(--cyan), var(--violet)); z-index:1;
    }
    .nav-links { display:flex; gap:32px; font-size:13px; color:var(--text-dim); }
    .nav-links a { color:inherit; text-decoration:none; transition:color .2s; }
    .nav-links a:hover { color:var(--text); }
    .nav-cta {
      display:flex; gap:10px; align-items:center;
    }
    .pill {
      display:inline-flex; align-items:center; gap:6px;
      padding:7px 14px; border-radius:999px; font-size:11px; font-weight:500;
      border:1px solid var(--hairline-strong); color:var(--text-dim);
      background:rgba(255,255,255,0.03); backdrop-filter:blur(10px);
    }
    .live-dot {
      width:6px; height:6px; border-radius:50%;
      background:var(--lime);
      box-shadow:0 0 12px var(--lime), 0 0 24px rgba(198,255,0,0.4);
      animation:pulse 1.6s infinite;
    }
    @keyframes pulse { 0%,100% {opacity:1; transform:scale(1);} 50% {opacity:.5; transform:scale(.85);} }

    /* HERO */
    .hero {
      position:relative; z-index:2;
      padding: 64px 48px 36px;
      display:grid; grid-template-columns: 1.4fr 1fr; gap:48px; align-items:end;
    }
    .hero h1 {
      font-size: clamp(48px, 6.2vw, 92px);
      line-height:0.98; letter-spacing:-0.035em; font-weight:800;
      margin:0; color:#fff;
    }
    .hero h1 .accent {
      background:linear-gradient(120deg, var(--cyan) 0%, var(--violet) 55%, var(--lime) 100%);
      -webkit-background-clip:text; background-clip:text; color:transparent;
      font-style:italic; font-weight:900;
    }
    .hero .kicker {
      display:inline-flex; gap:8px; align-items:center;
      font-size:12px; color:var(--text-dim); margin-bottom:24px;
      text-transform:uppercase; letter-spacing:0.18em; font-weight:500;
    }
    .hero .kicker .bar { width:32px; height:1px; background:linear-gradient(90deg, var(--cyan), transparent); }
    .hero p.lede {
      font-size:18px; line-height:1.55; color:var(--text-dim); margin:28px 0 0;
      max-width:540px; font-weight:300;
    }
    .hero p.lede b { color:var(--text); font-weight:500; }

    .hero-stats {
      display:grid; grid-template-columns: repeat(2, 1fr); gap:18px; padding-bottom:8px;
    }
    .h-stat { padding:20px 22px; border:1px solid var(--hairline);
              background:var(--surface); backdrop-filter:blur(14px); border-radius:16px;
              position:relative; overflow:hidden; }
    .h-stat::before {
      content:''; position:absolute; inset:0; opacity:.5;
      background:radial-gradient(120px 80px at 80% 0%, var(--c, var(--cyan)), transparent 70%);
      mix-blend-mode:screen;
    }
    .h-stat .v { font-size:38px; font-weight:700; letter-spacing:-0.04em; line-height:1; }
    .h-stat .l { font-size:11px; color:var(--text-dim); margin-top:8px; text-transform:uppercase; letter-spacing:0.12em; }
    .h-stat.allow .v { color:#fff; }
    .h-stat.allow { --c:rgba(198,255,0,0.35); }
    .h-stat.block .v { color:#fff; }
    .h-stat.block { --c:rgba(255,77,125,0.45); }
    .h-stat.warn  .v { color:#fff; }
    .h-stat.warn  { --c:rgba(255,179,71,0.4); }
    .h-stat.total { --c:rgba(0,229,255,0.4); }

    /* CONTROLS bar */
    .control-bar {
      position:relative; z-index:2;
      margin: 28px 48px 18px;
      padding: 18px 22px;
      border:1px solid var(--hairline);
      background:var(--surface); backdrop-filter:blur(20px);
      border-radius:18px;
      display:flex; gap:14px; align-items:center; flex-wrap:wrap;
    }
    .label-tag {
      font-size:10px; text-transform:uppercase; letter-spacing:0.18em;
      color:var(--text-mute); font-weight:600;
    }
    select.scenario {
      flex:1; min-width:220px; max-width:380px;
      background:rgba(255,255,255,0.04); color:var(--text);
      border:1px solid var(--hairline-strong); border-radius:12px;
      padding:12px 16px; font-size:13px; font-family:inherit;
      cursor:pointer; outline:none; transition:all .2s;
      appearance:none;
      background-image:url("data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 12 8'><path d='M1 1l5 5 5-5' stroke='%23a8a8b3' stroke-width='1.5' fill='none'/></svg>");
      background-repeat:no-repeat; background-position:right 14px center; background-size:10px;
      padding-right:36px;
    }
    select.scenario:hover, select.scenario:focus { border-color:var(--cyan); }
    .btn {
      display:inline-flex; align-items:center; gap:8px;
      padding:12px 22px; border-radius:999px; font-size:13px; font-weight:600;
      cursor:pointer; transition:all .2s; font-family:inherit;
      border:1px solid var(--hairline-strong); color:var(--text);
      background:rgba(255,255,255,0.04);
    }
    .btn:hover { background:rgba(255,255,255,0.08); border-color:var(--hairline-strong); transform:translateY(-1px); }
    .btn.primary {
      background:linear-gradient(110deg, var(--cyan), var(--violet));
      color:#000; border-color:transparent;
      box-shadow:0 8px 28px rgba(0,229,255,0.25), 0 0 0 1px rgba(255,255,255,0.1) inset;
    }
    .btn.primary:hover {
      filter:brightness(1.1) saturate(1.1);
      box-shadow:0 12px 36px rgba(179,136,255,0.4), 0 0 0 1px rgba(255,255,255,0.18) inset;
    }
    .btn.primary svg { transition: transform .2s; }
    .btn.primary:hover svg { transform: translateX(3px); }

    /* MAIN grid */
    main {
      position:relative; z-index:2;
      padding: 0 48px 48px;
      display:grid; grid-template-columns: 1.45fr 1fr; gap:22px;
    }
    .panel {
      position:relative;
      background:var(--surface);
      border:1px solid var(--hairline);
      border-radius:20px;
      backdrop-filter:blur(20px);
      overflow:hidden;
      display:flex; flex-direction:column;
    }
    .panel-head {
      padding:18px 22px 14px;
      display:flex; align-items:center; justify-content:space-between;
      border-bottom:1px solid var(--hairline);
    }
    .panel-title {
      font-size:11px; text-transform:uppercase; letter-spacing:0.18em;
      color:var(--text-mute); font-weight:600;
    }
    .panel-subtitle { font-size:11px; color:var(--text-dim); }

    /* BPMN canvas */
    #canvas { flex:1; min-height: 460px; background:transparent;
              border-radius:0 0 20px 20px; }
    .djs-element.pg-current  .djs-visual > :nth-child(1) {
      fill: rgba(0,229,255,0.18) !important;
      stroke: var(--cyan) !important; stroke-width:3px !important;
      filter: drop-shadow(0 0 12px rgba(0,229,255,0.6));
    }
    .djs-element.pg-completed .djs-visual > :nth-child(1) {
      fill: rgba(198,255,0,0.12) !important;
      stroke: var(--lime) !important; stroke-width:2px !important;
    }
    .djs-element.pg-blocked   .djs-visual > :nth-child(1) {
      fill: rgba(255,77,125,0.22) !important;
      stroke: var(--rose) !important; stroke-width:3px !important;
      animation: flashRed 0.7s ease-in-out 4;
      filter: drop-shadow(0 0 16px rgba(255,77,125,0.7));
    }
    .djs-element.pg-warned    .djs-visual > :nth-child(1) {
      stroke: var(--amber) !important; stroke-dasharray: 5 3;
    }
    @keyframes flashRed {
      0%, 100% { fill: rgba(255,77,125,0.22); }
      50%      { fill: rgba(255,77,125,0.6); }
    }
    /* bpmn-js text colors */
    .djs-element text { fill: var(--text) !important; font-family:'Inter',sans-serif !important; }
    .djs-connection .djs-visual path { stroke: rgba(255,255,255,0.4) !important; }
    marker path { fill: rgba(255,255,255,0.4) !important; stroke: rgba(255,255,255,0.4) !important; }

    /* TIMELINE */
    #timeline { padding:14px; min-height:200px; }
    .vis-timeline { border:none !important; background:transparent !important; font-family:'Inter',sans-serif !important; }
    .vis-panel.vis-background, .vis-panel.vis-bottom, .vis-panel.vis-center, .vis-panel.vis-left, .vis-panel.vis-right, .vis-panel.vis-top {
      background:transparent !important; border-color:var(--hairline) !important;
    }
    .vis-label, .vis-time-axis .vis-text { color: var(--text-dim) !important; }
    .vis-time-axis .vis-grid.vis-vertical { border-color: var(--hairline) !important; }
    .vis-item { border-radius:6px; border:none; font-size:11px; padding:3px 8px; font-weight:500; }
    .vis-item.ALLOW { background:linear-gradient(90deg, rgba(198,255,0,0.85), rgba(198,255,0,0.55)); color:#000; }
    .vis-item.BLOCK { background:linear-gradient(90deg, rgba(255,77,125,0.95), rgba(255,77,125,0.6)); color:#fff; font-weight:700; box-shadow:0 0 12px rgba(255,77,125,0.4); }
    .vis-item.WARN  { background:linear-gradient(90deg, rgba(255,179,71,0.9), rgba(255,179,71,0.55)); color:#000; }

    /* LOG */
    .log { flex:1; overflow-y:auto; font-size:13px; }
    .log::-webkit-scrollbar { width:8px; }
    .log::-webkit-scrollbar-thumb { background:var(--hairline-strong); border-radius:4px; }
    table { width:100%; border-collapse:collapse; }
    th { position:sticky; top:0; background:rgba(8,7,13,0.92); backdrop-filter:blur(8px);
         color:var(--text-mute); font-weight:600; font-size:10px;
         text-transform:uppercase; letter-spacing:0.14em;
         text-align:left; padding:12px 18px; border-bottom:1px solid var(--hairline); }
    td { padding:14px 18px; border-bottom:1px solid var(--hairline); vertical-align:top; }
    tr.new { animation: flashRow 1.5s ease-out; }
    @keyframes flashRow {
      0% { background: rgba(0,229,255,0.18); }
      100% { background: transparent; }
    }
    .decision { display:inline-flex; align-items:center; gap:5px;
                padding:4px 10px; border-radius:999px;
                font-size:10px; font-weight:700; text-transform:uppercase; letter-spacing:0.08em; }
    .decision::before {
      content:''; width:5px; height:5px; border-radius:50%;
    }
    .decision.ALLOW { background:rgba(198,255,0,0.14); color:var(--lime); }
    .decision.ALLOW::before { background:var(--lime); box-shadow:0 0 6px var(--lime); }
    .decision.BLOCK { background:rgba(255,77,125,0.16); color:var(--rose); }
    .decision.BLOCK::before { background:var(--rose); box-shadow:0 0 6px var(--rose); }
    .decision.WARN  { background:rgba(255,179,71,0.16); color:var(--amber); }
    .decision.WARN::before  { background:var(--amber); box-shadow:0 0 6px var(--amber); }
    code, .mono { font-family:'JetBrains Mono',monospace; font-size:12px;
                  background:rgba(255,255,255,0.05); padding:2px 8px; border-radius:5px;
                  color:var(--cyan); border:1px solid var(--hairline); }
    .muted { color:var(--text-mute); font-size:11px; font-variant-numeric: tabular-nums; }
    .corrective { color:var(--text-dim); font-size:11px; max-width:320px; line-height:1.5; }
    .violation-tag { color:var(--rose); font-weight:600; font-size:11px; display:block; margin-bottom:3px; }
    .empty { padding:48px 20px; text-align:center; color:var(--text-mute); font-size:13px; }
    .empty b { color:var(--cyan); font-weight:500; }

    @media (max-width: 1100px) {
      .hero { grid-template-columns:1fr; padding:48px 24px 24px; }
      main { grid-template-columns:1fr; padding:0 24px 32px; }
      nav { padding:18px 24px; }
      .control-bar { margin:20px 24px; }
      .nav-links { display:none; }
    }
  </style>
</head>
<body>
  <nav>
    <div class="brand">
      <div class="brand-mark"></div>
      ProcessGuard
    </div>
    <div class="nav-links">
      <a href="#">Console</a>
      <a href="https://github.com/yantongggg/processguard" target="_blank">GitHub</a>
      <a href="#">Docs</a>
      <a href="#">Hackathon</a>
    </div>
    <div class="nav-cta">
      <span class="pill"><span class="live-dot" id="liveDot"></span><span id="liveStatus">live</span></span>
    </div>
  </nav>

  <section class="hero">
    <div>
      <div class="kicker"><span class="bar"></span> Runtime compliance · BPMN-native</div>
      <h1>Where AI<br/>meets <span class="accent">compliance</span>.</h1>
      <p class="lede">
        ProcessGuard is the runtime firewall that turns your <b>BPMN process</b>
        into hard guardrails for autonomous agents — every tool call checked,
        every drift blocked, every decision audit-logged. <b>Live, no polling.</b>
      </p>
    </div>
    <div class="hero-stats">
      <div class="h-stat total"><div class="v" id="sTotal">0</div><div class="l">Total decisions</div></div>
      <div class="h-stat allow"><div class="v" id="sAllow">0</div><div class="l">Allowed</div></div>
      <div class="h-stat block"><div class="v" id="sBlock">0</div><div class="l">Blocked</div></div>
      <div class="h-stat warn"><div class="v" id="sWarn">0</div><div class="l">Warnings</div></div>
    </div>
  </section>

  <div class="control-bar">
    <span class="label-tag">Scenario</span>
    <select class="scenario" id="scenario">
      <option value="compliant">✅  compliant — $12,500 full flow</option>
      <option value="skip_2fa_for_vip" selected>🛑  skip 2FA for VIP — $9,500</option>
      <option value="skip_approval">🛑  skip manager approval — $8,000</option>
      <option value="all">▶  run all three back-to-back</option>
    </select>
    <button class="btn primary" id="runBtn">
      Run scenario
      <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><path d="M5 12h14M13 5l7 7-7 7"/></svg>
    </button>
    <button class="btn" id="resetBtn">Reset</button>
  </div>

  <main>
    <div class="panel">
      <div class="panel-head">
        <span class="panel-title">BPMN process · live agent position</span>
        <span class="panel-subtitle">refund_flow.bpmn</span>
      </div>
      <div id="canvas"></div>
    </div>
    <div class="panel" style="display:grid; grid-template-rows: 280px 1fr;">
      <div style="border-bottom:1px solid var(--hairline); display:flex; flex-direction:column;">
        <div class="panel-head" style="border-bottom:none;">
          <span class="panel-title">Decision timeline</span>
          <span class="panel-subtitle">per agent</span>
        </div>
        <div id="timeline" style="flex:1;"></div>
      </div>
      <div style="display:flex; flex-direction:column; min-height:0;">
        <div class="panel-head">
          <span class="panel-title">Audit stream · SSE</span>
          <span class="panel-subtitle">no polling</span>
        </div>
        <div class="log">
          <table>
            <thead><tr>
              <th style="width:74px;">Time</th>
              <th>Tool</th>
              <th style="width:88px;">Decision</th>
              <th>Violation / corrective</th>
            </tr></thead>
            <tbody id="logBody">
              <tr><td colspan="4" class="empty">Pick a scenario and click <b>Run scenario</b> to see ProcessGuard react in real time.</td></tr>
            </tbody>
          </table>
        </div>
      </div>
    </div>
  </main>

<script>
// ----- bpmn-js viewer ------------------------------------------------------
const viewer = new BpmnJS({ container: '#canvas' });
let nameToId = {};
let currentId = null;

async function loadBpmn() {
  const r = await fetch('/api/bpmn');
  const data = await r.json();
  nameToId = data.task_name_to_id;
  try {
    await viewer.importXML(data.xml);
    viewer.get('canvas').zoom('fit-viewport', 'auto');
  } catch (e) { console.error('bpmn import failed:', e); }
}

function clearMarkers() {
  const canvas = viewer.get('canvas');
  const reg = viewer.get('elementRegistry');
  reg.forEach(el => {
    canvas.removeMarker(el.id, 'pg-current');
    canvas.removeMarker(el.id, 'pg-completed');
    canvas.removeMarker(el.id, 'pg-blocked');
    canvas.removeMarker(el.id, 'pg-warned');
  });
  currentId = null;
}

function mark(taskName, kind) {
  const id = nameToId[taskName];
  if (!id) return;
  const canvas = viewer.get('canvas');
  if (kind === 'current') {
    if (currentId) {
      canvas.removeMarker(currentId, 'pg-current');
      canvas.addMarker(currentId, 'pg-completed');
    }
    canvas.addMarker(id, 'pg-current');
    currentId = id;
  } else if (kind === 'blocked') {
    canvas.addMarker(id, 'pg-blocked');
    setTimeout(() => canvas.removeMarker(id, 'pg-blocked'), 4000);
  } else if (kind === 'warned') {
    canvas.addMarker(id, 'pg-warned');
    setTimeout(() => canvas.removeMarker(id, 'pg-warned'), 3000);
  }
}

// ----- timeline ------------------------------------------------------------
const timelineContainer = document.getElementById('timeline');
const tlItems = new vis.DataSet();
const tlGroups = new vis.DataSet();
const timeline = new vis.Timeline(timelineContainer, tlItems, tlGroups, {
  stack: true, height: '180px', orientation: 'top',
  showCurrentTime: false, zoomable: true,
});

function addToTimeline(ev) {
  const group = ev.agent_name || 'unknown';
  if (!tlGroups.get(group)) tlGroups.add({ id: group, content: group });
  tlItems.add({
    id: ev.id + '_' + Math.random(),
    group,
    content: (ev.tool_name || ev.violation || '?') + ' [' + ev.decision + ']',
    start: ev.ts,
    className: ev.decision,
    title: ev.corrective || '',
  });
  // Auto-scroll window to latest
  const now = new Date(ev.ts);
  timeline.setWindow(new Date(now.getTime() - 30000), new Date(now.getTime() + 5000));
}

// ----- stats + log ---------------------------------------------------------
const stats = { ALLOW: 0, BLOCK: 0, WARN: 0 };
function refreshStats() {
  document.getElementById('sAllow').textContent = stats.ALLOW;
  document.getElementById('sBlock').textContent = stats.BLOCK;
  document.getElementById('sWarn').textContent  = stats.WARN;
  document.getElementById('sTotal').textContent = stats.ALLOW + stats.BLOCK + stats.WARN;
}

function addRow(ev) {
  const tbody = document.getElementById('logBody');
  if (tbody.querySelector('.empty')) tbody.innerHTML = '';
  const tr = document.createElement('tr');
  tr.className = 'new';
  const ts = (ev.ts || '').replace('T', ' ').slice(11, 19);
  const violation = ev.violation
    ? `<span class="violation-tag">${ev.violation}</span>`
    : '';
  const corrective = (ev.corrective || '').slice(0, 200);
  tr.innerHTML = `
    <td class="muted">${ts}</td>
    <td>${ev.tool_name ? '<code>'+ev.tool_name+'</code>' : '<span class="muted">(reasoning)</span>'}</td>
    <td><span class="decision ${ev.decision}">${ev.decision}</span></td>
    <td class="corrective">${violation}${corrective}</td>`;
  tbody.insertBefore(tr, tbody.firstChild);
  while (tbody.children.length > 80) tbody.removeChild(tbody.lastChild);
}

// ----- SSE -----------------------------------------------------------------
function connectSSE() {
  const es = new EventSource('/api/stream');
  const dot = document.getElementById('liveDot');
  const status = document.getElementById('liveStatus');
  es.addEventListener('hello', () => { status.textContent = 'live'; dot.style.background = 'var(--green)'; });
  es.addEventListener('decision', e => {
    const ev = JSON.parse(e.data);
    stats[ev.decision] = (stats[ev.decision] || 0) + 1;
    refreshStats();
    addRow(ev);
    addToTimeline(ev);

    if (ev.decision === 'ALLOW' && ev.tool_name) {
      mark(ev.tool_name, 'current');
    } else if (ev.decision === 'BLOCK' && ev.tool_name) {
      mark(ev.tool_name, 'blocked');
    } else if (ev.decision === 'WARN') {
      // intent drift: warned ring around the current node
      const node = ev.bpmn_node;
      if (node) mark(node, 'warned');
    }
  });
  es.onerror = () => {
    status.textContent = 'reconnecting…';
    dot.style.background = 'var(--yellow)';
  };
}

// ----- demo controls -------------------------------------------------------
document.getElementById('runBtn').addEventListener('click', async () => {
  clearMarkers();
  const scenario = document.getElementById('scenario').value;
  await fetch('/api/demo/run', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({ scenario, reset: false }),
  });
});

document.getElementById('resetBtn').addEventListener('click', async () => {
  clearMarkers();
  document.getElementById('logBody').innerHTML =
    '<tr><td colspan="4" class="empty">Reset. Click ▶ Run scenario.</td></tr>';
  tlItems.clear();
  tlGroups.clear();
  stats.ALLOW = stats.BLOCK = stats.WARN = 0;
  refreshStats();
  await fetch('/api/demo/reset', { method: 'POST' });
});

// ----- init ----------------------------------------------------------------
// Mouse-tracking gradient blob (subtle parallax accent)
document.addEventListener('mousemove', (e) => {
  const x = (e.clientX / window.innerWidth) * 100;
  const y = (e.clientY / window.innerHeight) * 100;
  document.body.style.setProperty('--mx', x + '%');
  document.body.style.setProperty('--my', y + '%');
});

(async function init() {
  await loadBpmn();
  // Preload existing audit rows into the log + stats
  const recent = await fetch('/api/recent?limit=50').then(r => r.json());
  recent.reverse().forEach(r => {
    const ev = {
      id: r.id, ts: r.ts, agent_name: r.agent_name,
      tool_name: r.tool_name, decision: r.decision,
      violation: r.violation, corrective: r.corrective,
      bpmn_node: r.bpmn_node,
    };
    stats[ev.decision] = (stats[ev.decision] || 0) + 1;
    addRow(ev);
    addToTimeline(ev);
  });
  refreshStats();
  connectSSE();
})();
</script>
</body>
</html>
"""
