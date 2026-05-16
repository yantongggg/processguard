"""FastAPI + HTMX dashboard for ProcessGuard audit log.

Run:
    pip install -e ".[dashboard]"
    uvicorn processguard.dashboard:app --reload --port 8765

Open: http://localhost:8765
"""
from __future__ import annotations

from pathlib import Path

try:
    from fastapi import FastAPI, Request
    from fastapi.responses import HTMLResponse, JSONResponse
except ImportError as e:  # pragma: no cover
    raise ImportError(
        "Dashboard requires fastapi + uvicorn. Install with `pip install -e '.[dashboard]'`"
    ) from e

from processguard.audit import AuditLog

app = FastAPI(title="ProcessGuard")
DB_PATH = Path("audit.db")
audit = AuditLog(DB_PATH)

# Mount UiPath runtime hook
try:
    from processguard.integrations.uipath import router as uipath_router
    app.include_router(uipath_router)
except Exception:
    pass


INDEX_HTML = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8"/>
  <title>ProcessGuard — Audit Console</title>
  <script src="https://unpkg.com/htmx.org@1.9.12"></script>
  <style>
    :root {
      --bg:#0d1117; --panel:#161b22; --border:#30363d;
      --text:#e6edf3; --muted:#7d8590; --green:#3fb950;
      --red:#f85149; --yellow:#d29922; --blue:#58a6ff;
    }
    * { box-sizing: border-box; }
    body { margin:0; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
           background: var(--bg); color: var(--text); }
    header { padding: 14px 24px; border-bottom:1px solid var(--border);
             display:flex; align-items:center; justify-content:space-between;
             background: var(--panel); }
    h1 { font-size: 16px; margin:0; font-weight: 600; letter-spacing: 0.3px; }
    .tag { font-size: 10px; padding: 2px 8px; border:1px solid var(--border);
           border-radius: 4px; color: var(--muted); }
    main { padding: 24px; max-width: 1400px; margin: 0 auto; }
    .stats { display:grid; grid-template-columns: repeat(4, 1fr); gap:12px; margin-bottom:24px; }
    .stat { background:var(--panel); border:1px solid var(--border); border-radius:8px;
            padding:16px; }
    .stat .label { color: var(--muted); font-size:11px; text-transform: uppercase;
                   letter-spacing: 0.5px; margin-bottom:4px; }
    .stat .value { font-size: 28px; font-weight: 600; }
    .stat.allow .value { color: var(--green); }
    .stat.block .value { color: var(--red); }
    .stat.warn  .value { color: var(--yellow); }
    table { width:100%; border-collapse: collapse; background:var(--panel);
            border:1px solid var(--border); border-radius:8px; overflow:hidden; font-size:13px; }
    th { text-align:left; padding:10px 12px; background:#1c2128; color:var(--muted);
         font-weight:500; font-size:11px; text-transform: uppercase; letter-spacing: 0.4px; }
    td { padding:10px 12px; border-top:1px solid var(--border); vertical-align: top; }
    tr:hover td { background: #1c2128; }
    .decision { display:inline-block; padding:2px 8px; border-radius:4px; font-size:11px;
                font-weight:600; letter-spacing: 0.3px; }
    .decision.ALLOW { background: rgba(63,185,80,.15); color: var(--green); }
    .decision.BLOCK { background: rgba(248,81,73,.15); color: var(--red); }
    .decision.WARN  { background: rgba(210,153,34,.15); color: var(--yellow); }
    code { background:#0d1117; padding:1px 5px; border-radius:3px; font-size:11px;
           color: var(--blue); }
    .muted { color: var(--muted); font-size:11px; }
    .corrective { color: var(--muted); font-size:11px; max-width: 480px; line-height: 1.4; }
    .refresh { background:#21262d; border:1px solid var(--border); color:var(--text);
               padding:6px 12px; border-radius:6px; cursor:pointer; font-size:12px; }
    .refresh:hover { background:#30363d; }
    .empty { padding: 40px; text-align: center; color: var(--muted); }
  </style>
</head>
<body>
  <header>
    <div style="display:flex; align-items:center; gap:12px;">
      <h1>🛡 ProcessGuard</h1>
      <span class="tag">Audit Console</span>
    </div>
    <button class="refresh"
            hx-get="/_partial/dashboard" hx-target="#dash" hx-swap="innerHTML">
      ⟳ Refresh
    </button>
  </header>
  <main>
    <div id="dash"
         hx-get="/_partial/dashboard" hx-trigger="load, every 3s"
         hx-swap="innerHTML">
      Loading…
    </div>
  </main>
</body>
</html>
"""


@app.get("/", response_class=HTMLResponse)
def index():
    return INDEX_HTML


@app.get("/_partial/dashboard", response_class=HTMLResponse)
def partial_dashboard():
    stats = audit.stats()
    rows = audit.recent(50)
    total = sum(stats.values())
    allow = stats.get("ALLOW", 0)
    block = stats.get("BLOCK", 0)
    warn = stats.get("WARN", 0)

    cards = f"""
    <div class="stats">
      <div class="stat"><div class="label">Total decisions</div><div class="value">{total}</div></div>
      <div class="stat allow"><div class="label">Allowed</div><div class="value">{allow}</div></div>
      <div class="stat block"><div class="label">Blocked</div><div class="value">{block}</div></div>
      <div class="stat warn"><div class="label">Warnings</div><div class="value">{warn}</div></div>
    </div>
    """

    if not rows:
        return cards + '<div class="empty">No decisions logged yet. Run the demo to populate.</div>'

    body = []
    for r in rows:
        d = r["decision"]
        v = r["violation"] or ""
        corrective = (r["corrective"] or "")[:200]
        ts = (r["ts"] or "").replace("T", " ")[:19]
        body.append(
            f"<tr>"
            f"<td class='muted'>{ts}</td>"
            f"<td>{r['agent_name'] or ''}</td>"
            f"<td><code>{r['tool_name'] or ''}</code></td>"
            f"<td><span class='decision {d}'>{d}</span></td>"
            f"<td>{v}</td>"
            f"<td class='muted'>{r['bpmn_node'] or ''}</td>"
            f"<td class='corrective'>{corrective}</td>"
            f"</tr>"
        )

    table = f"""
    <table>
      <thead><tr>
        <th>Time</th><th>Agent</th><th>Tool</th><th>Decision</th>
        <th>Violation</th><th>Current BPMN node</th><th>Corrective message</th>
      </tr></thead>
      <tbody>{''.join(body)}</tbody>
    </table>
    """
    return cards + table


@app.get("/api/recent")
def api_recent(limit: int = 100):
    return JSONResponse(audit.recent(limit=limit))


@app.get("/api/stats")
def api_stats():
    return JSONResponse(audit.stats())
