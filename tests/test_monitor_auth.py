"""MonitorServer auth and control gating, exercised over real HTTP on a free port.

The capture loop is stubbed out so the tests never grab the screen. A fake
``app`` supplies only what the request handler reads: ``cfg``, ``clicker``
with ``stats.snapshot()``, and ``_state_str``.
"""

from __future__ import annotations

import http.client
import logging
import urllib.error
import urllib.request

import pytest

from ui import monitor_server as ms

TOKEN = "unit-test-token-Q7x9"


class _Stats:
    def snapshot(self):
        return {"total": 3, "elapsed": 12.0, "avg_interval": 4.0, "cpm": 15.0,
                "last_pos": [10, 20]}


class _Clicker:
    stats = _Stats()
    current_phase = "idle"
    phase_label = ""
    phase_remaining = 0.0


class _FakeApp:
    def __init__(self):
        self.cfg = {
            "monitor_port": 0,
            "monitor_token": TOKEN,
            "monitor_remote_control_enabled": False,
            "monitor_fps": 15,
            "monitor_jpeg_quality": 85,
            "monitor_max_width": 1920,
        }
        self.clicker = _Clicker()
        self._state_str = "idle"
        self._active_mode = "clicker"


class _ListHandler(logging.Handler):
    def __init__(self):
        super().__init__(level=logging.DEBUG)
        self.messages: list[str] = []

    def emit(self, record):
        self.messages.append(record.getMessage())


@pytest.fixture
def server(monkeypatch):
    # No screen grabs in tests: park the capture thread on the stop event.
    monkeypatch.setattr(ms.MonitorServer, "_capture_loop",
                        lambda self: self._stop.wait())
    app = _FakeApp()
    srv = ms.MonitorServer(app)
    handler = _ListHandler()
    log = logging.getLogger("monitor")
    log.addHandler(handler)
    log.setLevel(logging.DEBUG)
    assert srv.start() is True
    port = srv._server.server_address[1]
    try:
        yield srv, app, port, handler
    finally:
        srv.stop()
        log.removeHandler(handler)


def _get(port, path, headers=None):
    req = urllib.request.Request(f"http://127.0.0.1:{port}{path}", headers=headers or {})
    try:
        with urllib.request.urlopen(req, timeout=5) as r:
            return r.status, r.read(), dict(r.headers)
    except urllib.error.HTTPError as e:
        return e.code, e.read(), dict(e.headers)


def _post(port, path, body=b"", headers=None):
    hdrs = {"Content-Type": "application/x-www-form-urlencoded"}
    hdrs.update(headers or {})
    req = urllib.request.Request(f"http://127.0.0.1:{port}{path}", data=body,
                                 headers=hdrs, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=5) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()


def test_no_token_is_401(server):
    _, _, port, _ = server
    assert _get(port, "/status")[0] == 401
    assert _get(port, "/")[0] == 401


def test_wrong_token_is_401(server):
    _, _, port, _ = server
    assert _get(port, "/status?token=nope")[0] == 401
    assert _get(port, "/status", {"Cookie": "pc_token=nope"})[0] == 401


def test_right_token_via_query_is_200(server):
    _, _, port, _ = server
    code, body, headers = _get(port, f"/status?token={TOKEN}")
    assert code == 200
    assert headers.get("Content-Type", "").startswith("application/json")
    assert b'"state": "idle"' in body
    assert b'"remote_control": false' in body


def test_right_token_via_cookie_is_200(server):
    _, _, port, _ = server
    code, _, _ = _get(port, "/status", {"Cookie": f"pc_token={TOKEN}"})
    assert code == 200


def test_index_sets_httponly_cookie(server):
    _, _, port, _ = server
    code, body, headers = _get(port, f"/?token={TOKEN}")
    assert code == 200
    cookie = headers.get("Set-Cookie", "")
    assert cookie.startswith(f"pc_token={TOKEN}")
    assert "HttpOnly" in cookie
    assert "SameSite=Strict" in cookie
    assert b"PhantomClick" in body


def test_unknown_path_is_404(server):
    _, _, port, _ = server
    assert _get(port, f"/nothing?token={TOKEN}")[0] == 404


def test_control_start_is_403_when_remote_control_off(server):
    _, _, port, _ = server
    code, body = _post(port, f"/control/start?token={TOKEN}")
    assert code == 403
    assert b"Remote control is disabled" in body


def test_control_requires_token_before_remote_check(server):
    _, app, port, _ = server
    app.cfg["monitor_remote_control_enabled"] = True
    assert _post(port, "/control/stop")[0] == 401


def test_close_window_without_confirm_is_400(server):
    _, app, port, _ = server
    app.cfg["monitor_remote_control_enabled"] = True
    code, body = _post(port, f"/control/close-window?token={TOKEN}", b"confirm=false")
    assert code == 400
    assert b"confirm=true" in body


def test_oversized_post_body_is_413(server):
    _, app, port, _ = server
    app.cfg["monitor_remote_control_enabled"] = True
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    # Advertise a body far past the cap; the server must answer before
    # trying to read it.
    conn.putrequest("POST", f"/control/start?token={TOKEN}")
    conn.putheader("Content-Type", "application/x-www-form-urlencoded")
    conn.putheader("Content-Length", str(ms._MAX_POST_BYTES + 1))
    conn.endheaders()
    resp = conn.getresponse()
    assert resp.status == 413
    conn.close()


def test_token_never_appears_in_log(server):
    _, app, port, handler = server
    app.cfg["monitor_remote_control_enabled"] = True
    _get(port, f"/status?token={TOKEN}")
    _get(port, f"/?token={TOKEN}")
    _get(port, "/status?token=wrong")
    _post(port, f"/control/close-window?token={TOKEN}", b"confirm=false")
    joined = "\n".join(handler.messages)
    assert "monitor_server start" in joined
    assert TOKEN not in joined
    assert "wrong" not in joined


def test_stop_is_idempotent_and_frees_port(server):
    srv, _, port, _ = server
    srv.stop()
    srv.stop()
    assert srv.is_running is False
    with pytest.raises((urllib.error.URLError, ConnectionError, OSError)):
        urllib.request.urlopen(f"http://127.0.0.1:{port}/status?token={TOKEN}", timeout=1)
