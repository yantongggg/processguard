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
  <title>ProcessGuard — Live Console</title>
  <link rel="stylesheet"
        href="https://unpkg.com/bpmn-js@17.11.1/dist/assets/diagram-js.css"/>
  <link rel="stylesheet"
        href="https://unpkg.com/bpmn-js@17.11.1/dist/assets/bpmn-js.css"/>
  <link rel="stylesheet"
        href="https://unpkg.com/bpmn-js@17.11.1/dist/assets/bpmn-font/css/bpmn.css"/>
  <link rel="stylesheet"
        href="https://unpkg.com/vis-timeline@7.7.3/styles/vis-timeline-graph2d.min.css"/>
  <script src="https://unpkg.com/bpmn-js@17.11.1/dist/bpmn-navigated-viewer.development.js"></script>
  <script src="https://unpkg.com/vis-timeline@7.7.3/standalone/umd/vis-timeline-graph2d.min.js"></script>
  <style>
    :root {
      --bg:#0d1117; --panel:#161b22; --border:#30363d;
      --text:#e6edf3; --muted:#7d8590;
      --green:#3fb950; --red:#f85149; --yellow:#d29922; --blue:#58a6ff;
    }
    * { box-sizing: border-box; }
    html, body { margin:0; padding:0; height:100%; background:var(--bg); color:var(--text);
                 font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; }
    header { padding:12px 20px; border-bottom:1px solid var(--border);
             display:flex; align-items:center; justify-content:space-between;
             background:var(--panel); }
    h1 { font-size:15px; margin:0; font-weight:600; letter-spacing:0.3px; }
    .tag { font-size:10px; padding:2px 8px; border:1px solid var(--border);
           border-radius:4px; color:var(--muted); margin-left:8px; }
    .live-dot { width:8px; height:8px; border-radius:50%;
                background:var(--green); display:inline-block;
                box-shadow:0 0 8px var(--green); animation:pulse 1.5s infinite; }
    @keyframes pulse { 0%,100% {opacity:1;} 50% {opacity:0.4;} }
    .controls { display:flex; gap:8px; align-items:center; }
    select, button { background:#21262d; border:1px solid var(--border);
                     color:var(--text); padding:6px 12px; border-radius:6px;
                     font-size:12px; cursor:pointer; }
    button.primary { background:var(--blue); border-color:var(--blue);
                     color:#001530; font-weight:600; }
    button:hover { filter: brightness(1.15); }
    main { display:grid; grid-template-columns: 1.2fr 1fr; gap:12px;
           padding:12px; height:calc(100vh - 56px); }
    .col { display:flex; flex-direction:column; gap:12px; min-height:0; }
    .panel { background:var(--panel); border:1px solid var(--border);
             border-radius:8px; padding:12px; display:flex; flex-direction:column;
             min-height:0; }
    .panel-title { font-size:11px; text-transform:uppercase; color:var(--muted);
                   letter-spacing:0.5px; margin-bottom:8px; font-weight:600; }
    .stats { display:grid; grid-template-columns: repeat(4, 1fr); gap:8px; }
    .stat { background:#0d1117; border:1px solid var(--border); border-radius:6px;
            padding:10px; text-align:center; }
    .stat .label { color:var(--muted); font-size:10px; text-transform:uppercase; }
    .stat .value { font-size:22px; font-weight:600; margin-top:2px; }
    .stat.allow .value { color:var(--green); }
    .stat.block .value { color:var(--red); }
    .stat.warn  .value { color:var(--yellow); }

    /* bpmn-js viewer */
    #canvas { flex:1; min-height: 340px; background:#0d1117;
              border:1px solid var(--border); border-radius:6px; }
    .djs-element.pg-current  .djs-visual > :nth-child(1) {
      fill: #1f6feb !important; stroke: #58a6ff !important; stroke-width:3px !important;
    }
    .djs-element.pg-completed .djs-visual > :nth-child(1) {
      fill: #1a4d2e !important; stroke: var(--green) !important;
    }
    .djs-element.pg-blocked   .djs-visual > :nth-child(1) {
      fill: #5a1a1a !important; stroke: var(--red) !important; stroke-width:3px !important;
      animation: flashRed 0.7s ease-in-out 4;
    }
    .djs-element.pg-warned    .djs-visual > :nth-child(1) {
      stroke: var(--yellow) !important; stroke-dasharray: 4 2;
    }
    @keyframes flashRed {
      0%, 100% { fill: #5a1a1a; }
      50%      { fill: var(--red); }
    }

    /* timeline */
    #timeline { flex:1; min-height: 180px; background:#0d1117; border-radius:6px; }
    .vis-timeline { border-color: var(--border) !important; background:#0d1117 !important; }
    .vis-panel { background:#0d1117 !important; border-color: var(--border) !important; }
    .vis-label, .vis-time-axis .vis-text { color: var(--muted) !important; }
    .vis-item { border-radius:3px; border:none; font-size:10px; padding:1px 4px; }
    .vis-item.ALLOW { background:rgba(63,185,80,.7); color:white; }
    .vis-item.BLOCK { background:rgba(248,81,73,.8); color:white; font-weight:600; }
    .vis-item.WARN  { background:rgba(210,153,34,.7); color:#1a1a1a; }

    /* log table */
    .log { flex:1; overflow-y:auto; font-size:12px; }
    table { width:100%; border-collapse:collapse; }
    th { position:sticky; top:0; background:#1c2128; color:var(--muted);
         font-weight:500; font-size:10px; text-transform:uppercase;
         text-align:left; padding:6px 8px; }
    td { padding:6px 8px; border-top:1px solid var(--border); vertical-align:top; }
    tr.new { animation: flashRow 1.2s ease-out; }
    @keyframes flashRow {
      0% { background: rgba(88, 166, 255, 0.25); }
      100% { background: transparent; }
    }
    .decision { display:inline-block; padding:1px 6px; border-radius:3px;
                font-size:10px; font-weight:600; }
    .decision.ALLOW { background:rgba(63,185,80,.15); color:var(--green); }
    .decision.BLOCK { background:rgba(248,81,73,.15); color:var(--red); }
    .decision.WARN  { background:rgba(210,153,34,.15); color:var(--yellow); }
    code { background:#0d1117; padding:1px 5px; border-radius:3px;
           font-size:11px; color:var(--blue); }
    .muted { color:var(--muted); font-size:10px; }
    .corrective { color:var(--muted); font-size:10px; max-width:280px;
                  line-height:1.3; }
    .empty { padding:20px; text-align:center; color:var(--muted); }
  </style>
</head>
<body>
  <header>
    <div>
      <h1>🛡 ProcessGuard <span class="tag">Live Console</span></h1>
    </div>
    <div class="controls">
      <span class="live-dot" id="liveDot" title="SSE connected"></span>
      <span class="muted" id="liveStatus">connecting…</span>
      &nbsp;|&nbsp;
      <select id="scenario">
        <option value="compliant">✅ compliant — $12,500 full flow</option>
        <option value="skip_2fa_for_vip" selected>🛑 skip 2FA for VIP — $9,500</option>
        <option value="skip_approval">🛑 skip approval — $8,000</option>
        <option value="all">▶ run all three</option>
      </select>
      <button class="primary" id="runBtn">▶ Run scenario</button>
      <button id="resetBtn">⟲ Reset audit log</button>
    </div>
  </header>

  <main>
    <!-- LEFT column: BPMN diagram + stats -->
    <div class="col">
      <div class="panel" style="flex: 0 0 auto;">
        <div class="panel-title">Decisions</div>
        <div class="stats">
          <div class="stat"><div class="label">Total</div><div class="value" id="sTotal">0</div></div>
          <div class="stat allow"><div class="label">Allowed</div><div class="value" id="sAllow">0</div></div>
          <div class="stat block"><div class="label">Blocked</div><div class="value" id="sBlock">0</div></div>
          <div class="stat warn"><div class="label">Warnings</div><div class="value" id="sWarn">0</div></div>
        </div>
      </div>
      <div class="panel" style="flex:1; min-height:0;">
        <div class="panel-title">BPMN process — live agent position</div>
        <div id="canvas"></div>
      </div>
    </div>

    <!-- RIGHT column: timeline + audit log -->
    <div class="col">
      <div class="panel" style="flex: 0 0 230px;">
        <div class="panel-title">Timeline</div>
        <div id="timeline"></div>
      </div>
      <div class="panel" style="flex:1; min-height:0;">
        <div class="panel-title">Audit log (live SSE)</div>
        <div class="log">
          <table>
            <thead><tr>
              <th style="width:80px;">Time</th>
              <th>Tool</th>
              <th style="width:60px;">Decision</th>
              <th>Violation / corrective</th>
            </tr></thead>
            <tbody id="logBody">
              <tr><td colspan="4" class="empty">No events yet. Click <b>▶ Run scenario</b>.</td></tr>
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
    ? `<b style="color:var(--red)">${ev.violation}</b><br/>`
    : '';
  const corrective = (ev.corrective || '').slice(0, 160);
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
