"""Local LAN HTTP server for the Monitor tab.

Streams the screen as MJPEG, exposes engine status as JSON, and (when the
user opts in) accepts POST control actions to start/stop the bot or close
RuneScape — all from the user's phone over the same Wi-Fi.

Threading model
---------------
- Capture thread: persistent ``mss.mss()`` handle, grabs ``monitors[0]``
  at the configured FPS, resizes to ≤1280px wide, JPEG-encodes via Pillow,
  writes the bytes to ``self._latest_frame``.
- Server thread: ``ThreadingHTTPServer`` accepting connections; each
  handler runs in its own thread (stdlib default).
- Lifetime: created once by ``ui.app.App`` at startup; ``start()`` /
  ``stop()`` cycle the threads. ``stop()`` is called from ``closeEvent``.

Security
--------
- Off by default; the user must enable it explicitly.
- Random URL token (``secrets.token_urlsafe(24)``) gates every endpoint.
- Token comparison is constant-time (``hmac.compare_digest``).
- Read endpoints (``/``, ``/stream``, ``/snapshot.jpg``, ``/status``) work
  whenever the server is up.
- Write endpoints (``POST /control/*``) additionally require
  ``cfg["monitor_remote_control_enabled"]`` — a separate toggle so
  view-only is the safer default.
- ``/control/close-window`` requires ``confirm=true`` in the form body so
  a stray request can't kick the user out of their game.
"""

from __future__ import annotations

import hmac
import io
import json
import logging
import secrets
import socket
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Optional
from urllib.parse import parse_qs, urlparse

from PIL import Image

from ui.config_io import save_config
from utils.logger import get_logger
from utils.window_finder import close_all_runescape_windows, find_runescape_windows


_log = get_logger("monitor")
# Resize floor — anything below this is too small to be useful on a phone
# screen. Hard cap on the upper end is whatever the source resolution is
# (no upscale).
_MIN_FRAME_WIDTH = 640


# ---- HTML page -----------------------------------------------------------

_PAGE_HTML = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, maximum-scale=1">
<title>PhantomClick · Monitor</title>
<style>
  :root {
    --bg: #161312; --surface: #1f1c1b; --border: #2c2826;
    --text: #f5efea; --muted: #a39b95; --accent: #ff8266; --warn: #f0b14b;
    --ok: #6dc278; --bad: #d96868;
  }
  * { box-sizing: border-box; }
  body { margin: 0; background: var(--bg); color: var(--text);
         font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", system-ui, sans-serif;
         -webkit-tap-highlight-color: transparent; }
  header { padding: 12px 14px; background: var(--surface); border-bottom: 1px solid var(--border);
           display: flex; align-items: center; justify-content: space-between; gap: 12px; }
  header h1 { font-size: 16px; margin: 0; font-weight: 600; }
  .pill { font-size: 12px; padding: 4px 10px; border-radius: 999px;
          background: var(--border); color: var(--muted); font-variant-numeric: tabular-nums; }
  .pill.ok { background: rgba(109, 194, 120, 0.18); color: var(--ok); }
  .pill.active { background: rgba(255, 130, 102, 0.18); color: var(--accent); }
  .stream { display: block; width: 100%; height: auto; background: #000; }
  .stats { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; padding: 12px 14px;
           font-size: 13px; }
  .stats div { display: flex; justify-content: space-between;
               padding: 6px 10px; background: var(--surface); border-radius: 6px; }
  .stats .k { color: var(--muted); }
  .stats .v { font-variant-numeric: tabular-nums; }
  .controls { padding: 12px 14px; display: grid; grid-template-columns: 1fr 1fr; gap: 8px; }
  .controls.three { grid-template-columns: 1fr 1fr 1fr; }
  button { font: inherit; padding: 14px 8px; border: 1px solid var(--border);
           background: var(--surface); color: var(--text); border-radius: 8px;
           cursor: pointer; touch-action: manipulation; }
  button.primary { background: var(--accent); color: #1a0e0a; border-color: var(--accent);
                   font-weight: 600; }
  button.danger { background: var(--bad); color: #1a0e0a; border-color: var(--bad);
                  font-weight: 600; }
  button:active { transform: scale(0.98); }
  button:disabled { opacity: 0.45; cursor: not-allowed; }
  .toast { position: fixed; left: 50%; bottom: 16px; transform: translateX(-50%);
           background: var(--surface); border: 1px solid var(--border);
           padding: 10px 14px; border-radius: 8px; font-size: 13px;
           opacity: 0; pointer-events: none; transition: opacity 0.2s; }
  .toast.show { opacity: 1; }
  .hidden { display: none !important; }
</style>
</head>
<body>
<header>
  <h1>PhantomClick · Monitor</h1>
  <span id="state" class="pill">…</span>
</header>
<img class="stream" src="/stream?token=__TOKEN__" alt="Live screen">
<div class="stats">
  <div><span class="k">Clicks</span><span class="v" id="s-total">—</span></div>
  <div><span class="k">CPM</span><span class="v" id="s-cpm">—</span></div>
  <div><span class="k">Elapsed</span><span class="v" id="s-elapsed">—</span></div>
  <div><span class="k">Last pos</span><span class="v" id="s-pos">—</span></div>
</div>
<div id="controls" class="controls three hidden">
  <button id="btn-start" class="primary">▶ Start</button>
  <button id="btn-stop">■ Stop</button>
  <button id="btn-close" class="danger">Close RS</button>
</div>
<div id="toast" class="toast"></div>
<script>
  const TOKEN = "__TOKEN__";
  const REMOTE = __REMOTE__;
  if (REMOTE) document.getElementById('controls').classList.remove('hidden');

  function fmtElapsed(s) {
    s = Math.floor(s || 0);
    const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60), sec = s % 60;
    return String(h).padStart(2,'0') + ':' + String(m).padStart(2,'0') + ':' + String(sec).padStart(2,'0');
  }
  function setPill(text, cls) {
    const el = document.getElementById('state');
    el.textContent = text;
    el.className = 'pill' + (cls ? ' ' + cls : '');
  }
  let toastTimer = null;
  function toast(msg) {
    const t = document.getElementById('toast');
    t.textContent = msg;
    t.classList.add('show');
    if (toastTimer) clearTimeout(toastTimer);
    toastTimer = setTimeout(() => t.classList.remove('show'), 2400);
  }
  async function refresh() {
    try {
      const r = await fetch('/status?token=' + encodeURIComponent(TOKEN), { cache: 'no-store' });
      if (!r.ok) { setPill('Auth error', ''); return; }
      const j = await r.json();
      const s = j.state || 'idle';
      setPill(s.charAt(0).toUpperCase() + s.slice(1) + (j.phase_label ? ' · ' + j.phase_label : ''),
              s === 'active' ? 'active' : (s === 'idle' ? '' : 'ok'));
      document.getElementById('s-total').textContent = j.stats.total ?? '—';
      document.getElementById('s-cpm').textContent = (j.stats.cpm || 0).toFixed(1);
      document.getElementById('s-elapsed').textContent = fmtElapsed(j.stats.elapsed);
      const p = j.stats.last_pos;
      document.getElementById('s-pos').textContent = p ? p[0] + ', ' + p[1] : '—';
    } catch (e) {
      setPill('Offline', '');
    }
  }
  async function post(path, extra) {
    const body = new URLSearchParams(extra || {});
    const r = await fetch(path + '?token=' + encodeURIComponent(TOKEN), {
      method: 'POST',
      headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
      body: body.toString(),
    });
    let msg = 'OK';
    try { const j = await r.json(); msg = j.message || (r.ok ? 'OK' : 'Error'); } catch {}
    toast(msg);
    refresh();
  }
  if (REMOTE) {
    document.getElementById('btn-start').onclick = () => post('/control/start');
    document.getElementById('btn-stop').onclick  = () => post('/control/stop');
    document.getElementById('btn-close').onclick = () => {
      if (confirm('Close RuneScape on your PC?')) post('/control/close-window', { confirm: 'true' });
    };
  }
  refresh();
  setInterval(refresh, 1500);
</script>
</body>
</html>
"""


# ---- Server --------------------------------------------------------------


class MonitorServer:
    def __init__(self, app):
        self.app = app
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._capture_thread: Optional[threading.Thread] = None
        self._server: Optional[ThreadingHTTPServer] = None
        self._server_thread: Optional[threading.Thread] = None
        self._latest_frame: bytes = b""
        self._latest_frame_lock = threading.Lock()
        self._is_running: bool = False
        self._last_error: str = ""

    # -- Public API -------------------------------------------------------

    @property
    def is_running(self) -> bool:
        return self._is_running

    @property
    def last_error(self) -> str:
        return self._last_error

    def lan_url(self) -> str:
        ip = _detect_lan_ip()
        port = int(self.app.cfg.get("monitor_port", 8765))
        token = self.app.cfg.get("monitor_token", "")
        suffix = f"/?token={token}" if token else "/"
        return f"http://{ip}:{port}{suffix}"

    def regenerate_token(self) -> str:
        token = secrets.token_urlsafe(24)
        self.app.cfg["monitor_token"] = token
        save_config(self.app.cfg)
        return token

    def start(self) -> bool:
        """Start (or restart) the server. Returns True on success.
        Idempotent: stops any running instance first so port/fps changes
        take effect."""
        self.stop()
        cfg = self.app.cfg
        port = int(cfg.get("monitor_port", 8765))
        if not cfg.get("monitor_token"):
            self.regenerate_token()
        try:
            self._server = ThreadingHTTPServer(("0.0.0.0", port), _make_handler(self))
        except OSError as e:
            self._last_error = f"Port {port}: {e.strerror or e}"
            _log.warning("monitor_server bind failed port=%d err=%s", port, e)
            self._server = None
            return False

        self._stop.clear()
        self._latest_frame = b""
        self._last_error = ""

        self._server_thread = threading.Thread(
            target=self._server.serve_forever, daemon=True, name="monitor-http",
        )
        self._capture_thread = threading.Thread(
            target=self._capture_loop, daemon=True, name="monitor-capture",
        )
        self._server_thread.start()
        self._capture_thread.start()
        self._is_running = True
        _log.info("monitor_server start port=%d url=%s", port, self.lan_url())
        return True

    def stop(self) -> None:
        if not self._is_running and self._server is None:
            return
        self._stop.set()
        if self._server is not None:
            try:
                self._server.shutdown()
                self._server.server_close()
            except Exception:
                pass
            self._server = None
        # Threads are daemons; join briefly to keep shutdown clean.
        for t in (self._server_thread, self._capture_thread):
            if t is not None and t.is_alive():
                t.join(timeout=1.5)
        self._server_thread = None
        self._capture_thread = None
        self._is_running = False
        _log.info("monitor_server stop")

    def get_latest_frame(self) -> bytes:
        with self._latest_frame_lock:
            return self._latest_frame

    # -- Capture loop -----------------------------------------------------

    @staticmethod
    def _resolve_capture_rect(sct, cfg: dict) -> dict:
        """Pick the rect to grab. Prefers the cached cfg["monitor_capture_rect"]
        (resolved by the card from the user-picked Qt screen), then falls back
        to mss's primary monitor. Always returns an mss-compatible dict.

        Sanity-clamps degenerate rects (width or height ≤ 0) back to primary —
        this can happen if a monitor was unplugged since the rect was cached.
        """
        rect = cfg.get("monitor_capture_rect")
        if isinstance(rect, dict):
            try:
                w = int(rect.get("width", 0))
                h = int(rect.get("height", 0))
                if w > 0 and h > 0:
                    return {
                        "left": int(rect.get("left", 0)),
                        "top": int(rect.get("top", 0)),
                        "width": w,
                        "height": h,
                    }
            except (TypeError, ValueError):
                pass
        # Fallback: mss primary (monitors[1]); if that's missing, virtual
        # union (monitors[0]) — old behavior.
        if len(sct.monitors) > 1:
            return sct.monitors[1]
        return sct.monitors[0]

    def _capture_loop(self) -> None:
        """Persistent mss handle (per modules/tracker.py:70+ pattern) — avoids
        DC handle leak from per-frame open/close."""
        import mss
        try:
            sct = mss.mss()
        except Exception as e:
            self._last_error = f"Screen capture init failed: {e}"
            _log.warning("monitor_capture init failed err=%s", e)
            return
        try:
            while not self._stop.is_set():
                cfg = self.app.cfg
                # Cap raised from 30 → 60. Practical achievable frame rate
                # depends on source resolution + quality + CPU; the slider
                # asks for it, the encoder delivers what it can.
                fps = max(1, min(60, int(cfg.get("monitor_fps", 15))))
                quality = max(30, min(95, int(cfg.get("monitor_jpeg_quality", 85))))
                # 0 = "native, no downscale". Otherwise a positive width cap.
                max_w = int(cfg.get("monitor_max_width", 1920))
                if max_w > 0:
                    max_w = max(_MIN_FRAME_WIDTH, max_w)
                try:
                    monitor = self._resolve_capture_rect(sct, cfg)
                    shot = sct.grab(monitor)
                    img = Image.frombytes("RGB", shot.size, shot.rgb)
                    # Downscale only — never upscale a smaller monitor up to
                    # the cap (would just blur for no clarity gain). max_w==0
                    # means "send native" (no resize at all).
                    if max_w > 0 and img.width > max_w:
                        ratio = max_w / img.width
                        # LANCZOS is meaningfully sharper than BILINEAR for
                        # screen content (text, UI edges) at the cost of ~2x
                        # CPU on the resize step — still trivial at 10 fps.
                        img = img.resize(
                            (max_w, int(img.height * ratio)),
                            Image.LANCZOS,
                        )
                    buf = io.BytesIO()
                    img.save(buf, format="JPEG", quality=quality, optimize=False)
                    with self._latest_frame_lock:
                        self._latest_frame = buf.getvalue()
                except Exception as e:
                    # Transient capture errors (e.g. DPI changes, RDP screen-locks)
                    # — log once per kind, keep going so the stream resumes when the
                    # underlying issue clears.
                    _log.debug("monitor_capture frame error: %s", e)
                self._stop.wait(1.0 / fps)
        finally:
            try:
                sct.close()
            except Exception:
                pass


# ---- Request handler -----------------------------------------------------


def _make_handler(server: "MonitorServer"):
    """Bind the MonitorServer instance into a fresh handler class. The
    handler is instantiated per-request by ThreadingHTTPServer, so we
    can't pass instance state via __init__ — closure is the cleanest
    bridge."""

    class _Handler(BaseHTTPRequestHandler):
        # Quiet the default "127.0.0.1 - - [time] GET /stream" stderr spam;
        # routed through the project logger instead at debug level.
        def log_message(self, fmt, *args):
            _log.debug("monitor_http " + fmt, *args)

        def log_error(self, fmt, *args):
            _log.warning("monitor_http " + fmt, *args)

        # -- Auth ---------------------------------------------------------

        def _check_token(self) -> bool:
            expected = server.app.cfg.get("monitor_token", "")
            if not expected:
                # Empty token = open access (warning surfaced loudly in UI).
                return True
            qs = parse_qs(urlparse(self.path).query)
            supplied = (qs.get("token") or [""])[0]
            if not supplied:
                # Fall back to cookie set by the / page.
                cookie = self.headers.get("Cookie") or ""
                for part in cookie.split(";"):
                    k, _, v = part.strip().partition("=")
                    if k == "pc_token":
                        supplied = v
                        break
            return hmac.compare_digest(str(expected), str(supplied))

        def _client_ip(self) -> str:
            try:
                return self.client_address[0]
            except Exception:
                return "?"

        def _send_json(self, code: int, payload: dict) -> None:
            body = json.dumps(payload).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def _send_text(self, code: int, msg: str) -> None:
            body = msg.encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _require_auth(self) -> bool:
            if not self._check_token():
                self._send_text(401, "Unauthorized")
                return False
            return True

        # -- GET ----------------------------------------------------------

        def do_GET(self):  # noqa: N802 (BaseHTTPRequestHandler API)
            path = urlparse(self.path).path
            if not self._require_auth():
                return
            try:
                if path == "/":
                    return self._serve_index()
                if path == "/stream":
                    return self._serve_stream()
                if path == "/snapshot.jpg":
                    return self._serve_snapshot()
                if path == "/status":
                    return self._serve_status()
                if path == "/ai/bots":
                    return self._serve_ai_bots()
            except (BrokenPipeError, ConnectionResetError):
                # Client closed the stream — normal, especially on phones
                # backgrounding the browser.
                return
            self._send_text(404, "Not found")

        def _serve_index(self) -> None:
            cfg = server.app.cfg
            token = cfg.get("monitor_token", "")
            remote = "true" if cfg.get("monitor_remote_control_enabled", False) else "false"
            html = _PAGE_HTML.replace("__TOKEN__", token).replace("__REMOTE__", remote)
            body = html.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            if token:
                self.send_header("Set-Cookie", f"pc_token={token}; Path=/; SameSite=Strict")
            self.end_headers()
            self.wfile.write(body)

        def _serve_snapshot(self) -> None:
            frame = server.get_latest_frame()
            if not frame:
                self._send_text(503, "No frame yet")
                return
            self.send_response(200)
            self.send_header("Content-Type", "image/jpeg")
            self.send_header("Content-Length", str(len(frame)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(frame)

        def _serve_stream(self) -> None:
            boundary = "phantomclick-frame"
            self.send_response(200)
            self.send_header(
                "Content-Type",
                f"multipart/x-mixed-replace; boundary={boundary}",
            )
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            last: bytes = b""
            cfg = server.app.cfg
            while not server._stop.is_set():
                fps = max(1, min(60, int(cfg.get("monitor_fps", 15))))
                frame = server.get_latest_frame()
                if frame and frame is not last:
                    try:
                        self.wfile.write(b"--" + boundary.encode() + b"\r\n")
                        self.wfile.write(b"Content-Type: image/jpeg\r\n")
                        self.wfile.write(
                            f"Content-Length: {len(frame)}\r\n\r\n".encode()
                        )
                        self.wfile.write(frame)
                        self.wfile.write(b"\r\n")
                        self.wfile.flush()
                        last = frame
                    except (BrokenPipeError, ConnectionResetError):
                        return
                time.sleep(1.0 / fps)

        def _serve_status(self) -> None:
            app = server.app
            try:
                stats = app.clicker.stats.snapshot()
            except Exception:
                stats = {"total": 0, "elapsed": 0.0, "avg_interval": 0.0,
                         "cpm": 0.0, "last_pos": None}
            try:
                state = str(getattr(app, "_state_str", "idle"))
            except Exception:
                state = "idle"
            try:
                phase = str(app.clicker.current_phase)
                phase_label = str(app.clicker.phase_label)
                phase_remaining = float(app.clicker.phase_remaining)
            except Exception:
                phase, phase_label, phase_remaining = "", "", 0.0
            ai = {
                "active_mode": str(getattr(app, "_active_mode", "")),
                "bot_slug": str(app.cfg.get("ai_bot_slug", "")),
                "running": False,
                "last_fired_rule": None,
                "current_tick": 0,
                "consecutive_dry_ticks": 0,
                "dry_run": bool(app.cfg.get("ai_dry_run", False)),
            }
            runner = getattr(app, "bot_runner", None)
            if runner is not None:
                try:
                    snap = runner.last_fired()
                    ai.update({
                        "running": bool(snap.get("running")),
                        "last_fired_rule": snap.get("last_fired_rule"),
                        "current_tick": int(snap.get("current_tick") or 0),
                        "consecutive_dry_ticks": int(snap.get("consecutive_dry_ticks") or 0),
                    })
                except Exception:
                    pass
            self._send_json(200, {
                "state": state,
                "phase": phase,
                "phase_label": phase_label,
                "phase_remaining": phase_remaining,
                "stats": stats,
                "remote_control": bool(
                    app.cfg.get("monitor_remote_control_enabled", False)
                ),
                "ai": ai,
            })

        def _serve_ai_bots(self) -> None:
            try:
                from ui.cards.ai import _enumerate_bots
                bots = _enumerate_bots()
                summary = [
                    {"slug": b["slug"], "name": b["name"], "goal": b["goal"]}
                    for b in bots
                ]
                self._send_json(200, {"bots": summary})
            except Exception as e:
                self._send_json(500, {"error": f"{type(e).__name__}: {e}"})

        # -- POST ---------------------------------------------------------

        def do_POST(self):  # noqa: N802
            path = urlparse(self.path).path
            if not self._require_auth():
                return
            if not server.app.cfg.get("monitor_remote_control_enabled", False):
                self._send_json(403, {"ok": False,
                                      "message": "Remote control is disabled"})
                return
            length = int(self.headers.get("Content-Length") or 0)
            raw = self.rfile.read(length) if length > 0 else b""
            form = parse_qs(raw.decode("utf-8", errors="replace"))

            if path == "/control/start":
                return self._control_start()
            if path == "/control/stop":
                return self._control_stop()
            if path == "/control/close-window":
                return self._control_close_window(form)
            if path == "/ai/select":
                return self._control_ai_select(form)
            self._send_text(404, "Not found")

        def _control_start(self) -> None:
            client = self._client_ip()
            try:
                # Route through the App's mode-aware dispatcher so AI mode
                # spawns BotRunner instead of Clicker. schedule_start is
                # thread-safe (QMetaObject.invokeMethod queues onto the GUI
                # thread); calling it here from the HTTP-handler thread is
                # the supported pattern.
                from ui import engine_bridge
                engine_bridge.schedule_start(server.app)
                _log.info("monitor_control action=start client=%s ok=True mode=%s",
                          client, getattr(server.app, "_active_mode", "?"))
                self._send_json(200, {"ok": True, "message": "Started"})
            except Exception as e:
                _log.warning("monitor_control action=start client=%s err=%s", client, e)
                self._send_json(500, {"ok": False, "message": f"Start failed: {e}"})

        def _control_stop(self) -> None:
            client = self._client_ip()
            try:
                from ui import engine_bridge
                engine_bridge.schedule_stop(server.app)
                _log.info("monitor_control action=stop client=%s ok=True", client)
                self._send_json(200, {"ok": True, "message": "Stopped"})
            except Exception as e:
                _log.warning("monitor_control action=stop client=%s err=%s", client, e)
                self._send_json(500, {"ok": False, "message": f"Stop failed: {e}"})

        def _control_close_window(self, form: dict) -> None:
            client = self._client_ip()
            confirm = (form.get("confirm") or [""])[0].lower() == "true"
            if not confirm:
                _log.info("monitor_control action=close-window client=%s rejected=no-confirm",
                          client)
                self._send_json(400, {"ok": False,
                                      "message": "Missing confirm=true"})
                return
            try:
                hwnds = find_runescape_windows()
                count = close_all_runescape_windows()
                _log.info("monitor_control action=close-window client=%s matched=%d ok=True",
                          client, count)
                if count == 0:
                    self._send_json(200, {"ok": True,
                                          "message": "No RuneScape window found"})
                else:
                    word = "window" if count == 1 else "windows"
                    self._send_json(200, {"ok": True,
                                          "message": f"Closed {count} RuneScape {word}",
                                          "matched": count})
            except Exception as e:
                _log.warning("monitor_control action=close-window client=%s err=%s",
                             client, e)
                self._send_json(500, {"ok": False, "message": f"Close failed: {e}"})

        def _control_ai_select(self, form: dict) -> None:
            client = self._client_ip()
            slug = (form.get("slug") or [""])[0].strip()
            if not slug:
                self._send_json(400, {"ok": False, "message": "Missing slug"})
                return
            try:
                from ui.cards.ai import _enumerate_bots
                from ui.config_io import save_config
                bots = _enumerate_bots()
                if not any(b["slug"] == slug for b in bots):
                    self._send_json(404, {
                        "ok": False,
                        "message": f"Bot {slug!r} not in library",
                    })
                    return
                server.app.cfg["ai_bot_slug"] = slug
                save_config(server.app.cfg)
                # Best-effort GUI refresh — the dropdown updates next user
                # interaction. Skipping cross-thread Qt mutation here keeps
                # the server thread Qt-free.
                _log.info("monitor_control action=ai-select client=%s slug=%s ok=True",
                          client, slug)
                self._send_json(200, {"ok": True, "slug": slug})
            except Exception as e:
                _log.warning("monitor_control action=ai-select client=%s err=%s",
                             client, e)
                self._send_json(500, {"ok": False, "message": f"Select failed: {e}"})

    return _Handler


# ---- Helpers -------------------------------------------------------------


def _detect_lan_ip() -> str:
    """Best-effort LAN IP detection. Uses the connectionless UDP-route trick
    (no packet sent — getsockname returns the interface that *would* be used
    to reach 8.8.8.8). Falls back to 127.0.0.1 if no route exists."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        return s.getsockname()[0]
    except Exception:
        return "127.0.0.1"
    finally:
        try:
            s.close()
        except Exception:
            pass


# Quiet noisy http.server stderr at module import time (defensive — the
# handler also overrides log_message but the base class still logs to
# stderr on certain socket errors before our override runs).
logging.getLogger("http.server").setLevel(logging.WARNING)
