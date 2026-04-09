#!/usr/bin/env python3
"""
server.py
Live preview web server for sci-viz-mcp.

Serves a WebSocket-driven dashboard that shows every render from any of
the MCP servers (crystal, ovito, blender, comsol_viz) in real time.

Architecture:
    MCP servers  ──POST /api/render──▶  this server  ──WebSocket──▶  browser
                                            │
                                       GET /file/{id}  (serves rendered images)

Launch:
    python -m preview.server          # from sci-viz-mcp root
    python preview/server.py          # direct

The server auto-opens the dashboard in your default browser on startup.
"""

import asyncio
import json
import mimetypes
import os
import signal
import sys
import webbrowser
from datetime import datetime
from pathlib import Path

from aiohttp import web

PREVIEW_PORT = int(os.environ.get("SCIVIZ_PREVIEW_PORT", "8765"))

render_history: list[dict] = []
ws_clients: set[web.WebSocketResponse] = set()


# ── Routes ────────────────────────────────────────────────────────────────────

routes = web.RouteTableDef()


@routes.get("/health")
async def health(request):
    return web.json_response({"status": "ok", "renders": len(render_history)})


@routes.get("/")
async def dashboard(request):
    return web.Response(text=DASHBOARD_HTML, content_type="text/html")


@routes.get("/ws")
async def websocket_handler(request):
    ws = web.WebSocketResponse(heartbeat=20)
    await ws.prepare(request)
    ws_clients.add(ws)

    history = [
        {**r, "id": i} for i, r in enumerate(render_history[-200:])
    ]
    await ws.send_json({"type": "history", "renders": history})

    try:
        async for msg in ws:
            pass
    finally:
        ws_clients.discard(ws)
    return ws


@routes.post("/api/render")
async def notify_render(request):
    data = await request.json()
    data["timestamp"] = datetime.now().isoformat()
    render_id = len(render_history)
    data["id"] = render_id
    render_history.append(data)

    payload = {"type": "new_render", "render": data}
    dead = set()
    for ws in ws_clients:
        try:
            await ws.send_json(payload)
        except Exception:
            dead.add(ws)
    ws_clients.difference_update(dead)

    return web.json_response({"status": "ok", "id": render_id})


@routes.get("/file/{render_id}")
async def serve_render_file(request):
    try:
        render_id = int(request.match_info["render_id"])
    except ValueError:
        raise web.HTTPBadRequest(text="render_id must be an integer")

    if render_id < 0 or render_id >= len(render_history):
        raise web.HTTPNotFound(text=f"render {render_id} not found")

    file_path = Path(render_history[render_id]["output_file"])
    if not file_path.exists():
        raise web.HTTPNotFound(text=f"file not found: {file_path}")

    ct, _ = mimetypes.guess_type(str(file_path))
    return web.FileResponse(file_path, headers={"Content-Type": ct or "application/octet-stream"})


# ── Dashboard HTML ────────────────────────────────────────────────────────────

DASHBOARD_HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>sci-viz-mcp — Live Preview</title>
<style>
:root {
  --bg:         #0d1117;
  --surface:    #161b22;
  --surface2:   #21262d;
  --border:     #30363d;
  --text:       #e6edf3;
  --text2:      #8b949e;
  --accent:     #58a6ff;
  --purple:     #d2a8ff;
  --cyan:       #79c0ff;
  --green:      #3fb950;
  --red:        #f85149;
  --orange:     #d29922;
  --mono:       'SF Mono', 'Fira Code', 'Cascadia Code', 'JetBrains Mono', monospace;
}

* { margin: 0; padding: 0; box-sizing: border-box; }

body {
  font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Helvetica, Arial, sans-serif;
  background: var(--bg);
  color: var(--text);
  height: 100vh;
  overflow: hidden;
  display: grid;
  grid-template-rows: 48px 1fr 140px;
  grid-template-columns: 1fr 320px;
}

/* ── Header ── */
header {
  grid-column: 1 / -1;
  display: flex;
  align-items: center;
  padding: 0 20px;
  background: var(--surface);
  border-bottom: 1px solid var(--border);
  gap: 12px;
  z-index: 10;
}
.logo {
  font-size: 13px;
  font-weight: 600;
  color: var(--text2);
  letter-spacing: 0.5px;
}
.logo span { color: var(--accent); }
.spacer { flex: 1; }
.render-count {
  font-family: var(--mono);
  font-size: 12px;
  color: var(--text2);
  background: var(--surface2);
  padding: 4px 10px;
  border-radius: 12px;
}
.status {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 12px;
  color: var(--text2);
}
.status-dot {
  width: 8px; height: 8px;
  border-radius: 50%;
  background: var(--red);
  transition: background 0.3s;
}
.status-dot.on { background: var(--green); }
.status-dot.on::after {
  content: '';
  display: block;
  width: 8px; height: 8px;
  border-radius: 50%;
  background: var(--green);
  animation: pulse 2s ease-in-out infinite;
}
@keyframes pulse {
  0%, 100% { opacity: 1; transform: scale(1); }
  50% { opacity: 0.4; transform: scale(1.8); }
}

/* ── Preview area ── */
.preview {
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 24px;
  background: var(--bg);
  overflow: hidden;
  position: relative;
}
.preview img {
  max-width: 100%;
  max-height: 100%;
  object-fit: contain;
  border-radius: 4px;
  transition: opacity 0.25s ease;
  image-rendering: auto;
}
.preview iframe {
  width: 100%;
  height: 100%;
  border: none;
  border-radius: 4px;
  background: white;
}
.preview .empty-state {
  text-align: center;
  color: var(--text2);
}
.preview .empty-state h2 {
  font-size: 18px;
  font-weight: 500;
  margin-bottom: 8px;
  color: var(--border);
}
.preview .empty-state p {
  font-size: 13px;
  line-height: 1.6;
}
.flash {
  position: absolute;
  inset: 0;
  border: 2px solid var(--accent);
  border-radius: 8px;
  opacity: 0;
  pointer-events: none;
  animation: flash-border 0.6s ease-out;
}
@keyframes flash-border {
  0% { opacity: 0.8; }
  100% { opacity: 0; }
}

/* ── Metadata panel ── */
.metadata {
  background: var(--surface);
  border-left: 1px solid var(--border);
  padding: 16px;
  overflow-y: auto;
  font-size: 12px;
  display: flex;
  flex-direction: column;
  gap: 16px;
}
.meta-section {
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.meta-label {
  font-size: 10px;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.8px;
  color: var(--text2);
}
.meta-value {
  color: var(--text);
  font-family: var(--mono);
  font-size: 12px;
  word-break: break-all;
}
.meta-value.tool { color: var(--purple); font-size: 13px; }
.meta-value.server { color: var(--cyan); }
.meta-value.file { color: var(--orange); }
.meta-params {
  background: var(--surface2);
  border-radius: 6px;
  padding: 10px;
  font-family: var(--mono);
  font-size: 11px;
  color: var(--text);
  white-space: pre-wrap;
  word-break: break-all;
  max-height: 300px;
  overflow-y: auto;
  line-height: 1.5;
}
.meta-empty {
  color: var(--text2);
  font-style: italic;
  padding-top: 40px;
  text-align: center;
}

/* ── History strip ── */
.history-bar {
  grid-column: 1 / -1;
  background: var(--surface);
  border-top: 1px solid var(--border);
  padding: 10px 16px;
  display: flex;
  gap: 8px;
  overflow-x: auto;
  align-items: center;
  scrollbar-width: thin;
  scrollbar-color: var(--border) transparent;
}
.history-bar::-webkit-scrollbar { height: 6px; }
.history-bar::-webkit-scrollbar-thumb { background: var(--border); border-radius: 3px; }

.hist-item {
  flex-shrink: 0;
  width: 110px; height: 110px;
  border-radius: 6px;
  border: 2px solid transparent;
  overflow: hidden;
  cursor: pointer;
  background: var(--surface2);
  transition: border-color 0.15s, transform 0.15s;
  position: relative;
}
.hist-item:hover { border-color: var(--border); transform: translateY(-2px); }
.hist-item.active { border-color: var(--accent); }
.hist-item img {
  width: 100%; height: 100%;
  object-fit: cover;
}
.hist-item .hist-badge {
  position: absolute;
  bottom: 4px; left: 4px;
  background: rgba(0,0,0,0.75);
  color: var(--text2);
  font-size: 9px;
  font-family: var(--mono);
  padding: 2px 5px;
  border-radius: 3px;
  max-width: calc(100% - 8px);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.hist-placeholder {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 100%; height: 100%;
  color: var(--text2);
  font-size: 10px;
  font-family: var(--mono);
  text-align: center;
  padding: 8px;
}

/* ── Keyboard hint ── */
.keyboard-hint {
  position: fixed;
  bottom: 152px;
  right: 332px;
  font-size: 10px;
  color: var(--text2);
  opacity: 0.5;
  pointer-events: none;
}
kbd {
  background: var(--surface2);
  border: 1px solid var(--border);
  border-radius: 3px;
  padding: 1px 5px;
  font-family: var(--mono);
  font-size: 10px;
}
</style>
</head>
<body>

<header>
  <div class="logo">sci-viz-mcp <span>Live Preview</span></div>
  <div class="spacer"></div>
  <div class="render-count" id="renderCount">0 renders</div>
  <div class="status">
    <div class="status-dot" id="statusDot"></div>
    <span id="statusText">connecting</span>
  </div>
</header>

<div class="preview" id="preview">
  <div class="empty-state">
    <h2>Waiting for renders ...</h2>
    <p>
      Use any sci-viz-mcp tool — crystal, OVITO, Blender, or COMSOL —<br>
      and renders will appear here in real time.
    </p>
  </div>
</div>

<div class="metadata" id="metadata">
  <div class="meta-empty">No renders yet</div>
</div>

<div class="history-bar" id="historyBar"></div>
<div class="keyboard-hint"><kbd>←</kbd> <kbd>→</kbd> navigate &nbsp; <kbd>Space</kbd> latest</div>

<script>
const preview    = document.getElementById('preview');
const metadata   = document.getElementById('metadata');
const historyBar = document.getElementById('historyBar');
const statusDot  = document.getElementById('statusDot');
const statusText = document.getElementById('statusText');
const renderCountEl = document.getElementById('renderCount');

let renders = [];
let activeIdx = -1;
let ws;

/* ── WebSocket ── */
function connect() {
  ws = new WebSocket(`ws://${location.host}/ws`);
  ws.onopen = () => {
    statusDot.classList.add('on');
    statusText.textContent = 'connected';
  };
  ws.onclose = () => {
    statusDot.classList.remove('on');
    statusText.textContent = 'reconnecting …';
    setTimeout(connect, 2000);
  };
  ws.onmessage = (e) => {
    const msg = JSON.parse(e.data);
    if (msg.type === 'history') {
      renders = msg.renders;
      rebuildHistory();
      if (renders.length) showRender(renders.length - 1);
    } else if (msg.type === 'new_render') {
      renders.push(msg.render);
      addHistoryThumb(renders.length - 1);
      showRender(renders.length - 1);
      flashBorder();
    }
    renderCountEl.textContent = `${renders.length} render${renders.length !== 1 ? 's' : ''}`;
  };
}

/* ── Render display ── */
function fileUrl(r) { return `/file/${r.id}`; }

function isImg(name) { return /\.(png|jpe?g|gif|svg|tiff?|webp)$/i.test(name); }

function showRender(idx) {
  if (idx < 0 || idx >= renders.length) return;
  activeIdx = idx;
  const r = renders[idx];
  const url = fileUrl(r);

  if (isImg(r.file_name)) {
    preview.innerHTML = `<img src="${url}" alt="${r.file_name}" draggable="false">`;
  } else {
    preview.innerHTML = `<iframe src="${url}"></iframe>`;
  }

  metadata.innerHTML = `
    <div class="meta-section">
      <div class="meta-label">Tool</div>
      <div class="meta-value tool">${esc(r.tool)}</div>
    </div>
    <div class="meta-section">
      <div class="meta-label">Server</div>
      <div class="meta-value server">${esc(r.server)}</div>
    </div>
    <div class="meta-section">
      <div class="meta-label">File</div>
      <div class="meta-value file">${esc(r.file_name)}</div>
    </div>
    <div class="meta-section">
      <div class="meta-label">Time</div>
      <div class="meta-value">${new Date(r.timestamp).toLocaleTimeString()}</div>
    </div>
    <div class="meta-section">
      <div class="meta-label">Full path</div>
      <div class="meta-value" style="font-size:10px;color:var(--text2)">${esc(r.output_file)}</div>
    </div>
    <div class="meta-section">
      <div class="meta-label">Parameters</div>
      <div class="meta-params">${formatParams(r.params)}</div>
    </div>`;

  document.querySelectorAll('.hist-item').forEach((el, i) => {
    el.classList.toggle('active', i === idx);
  });

  const active = historyBar.children[idx];
  if (active) active.scrollIntoView({ behavior: 'smooth', block: 'nearest', inline: 'center' });
}

/* ── History strip ── */
function addHistoryThumb(idx) {
  const r = renders[idx];
  const div = document.createElement('div');
  div.className = 'hist-item';
  div.onclick = () => showRender(idx);

  if (isImg(r.file_name)) {
    div.innerHTML = `<img src="${fileUrl(r)}" alt="" loading="lazy">
      <div class="hist-badge">${esc(r.tool.split('.').pop())}</div>`;
  } else {
    div.innerHTML = `<div class="hist-placeholder">${esc(r.file_name)}</div>
      <div class="hist-badge">${esc(r.tool.split('.').pop())}</div>`;
  }
  historyBar.appendChild(div);
  historyBar.scrollLeft = historyBar.scrollWidth;
}

function rebuildHistory() {
  historyBar.innerHTML = '';
  renders.forEach((_, i) => addHistoryThumb(i));
}

/* ── Flash effect ── */
function flashBorder() {
  const el = document.createElement('div');
  el.className = 'flash';
  preview.appendChild(el);
  el.addEventListener('animationend', () => el.remove());
}

/* ── Keyboard nav ── */
document.addEventListener('keydown', (e) => {
  if (e.key === 'ArrowLeft')  showRender(activeIdx - 1);
  if (e.key === 'ArrowRight') showRender(activeIdx + 1);
  if (e.key === ' ') { e.preventDefault(); showRender(renders.length - 1); }
});

/* ── Helpers ── */
function esc(s) {
  const d = document.createElement('div');
  d.textContent = s || '';
  return d.innerHTML;
}

function formatParams(p) {
  if (!p || Object.keys(p).length === 0) return '<span style="color:var(--text2)">none</span>';
  return esc(JSON.stringify(p, null, 2));
}

connect();
</script>
</body>
</html>
"""


# ── App setup ─────────────────────────────────────────────────────────────────

def create_app() -> web.Application:
    app = web.Application()
    app.router.add_routes(routes)
    return app


def main():
    app = create_app()

    def _open_browser():
        import time
        time.sleep(1.0)
        webbrowser.open(f"http://localhost:{PREVIEW_PORT}")

    import threading
    threading.Thread(target=_open_browser, daemon=True).start()

    print(f"sci-viz-mcp preview server → http://localhost:{PREVIEW_PORT}", file=sys.stderr)

    try:
        web.run_app(app, host="localhost", port=PREVIEW_PORT, print=None)
    except OSError as e:
        if "Address already in use" in str(e) or e.errno == 48:
            print(f"Port {PREVIEW_PORT} already in use — preview server likely already running.", file=sys.stderr)
            sys.exit(0)
        raise


if __name__ == "__main__":
    main()
