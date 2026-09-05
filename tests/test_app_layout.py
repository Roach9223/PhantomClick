"""Build the real GUI without capture, global hooks, or production settings."""
import copy

import pytest
from PySide6.QtCore import QPoint
from PySide6.QtWidgets import QApplication
from PySide6.QtTest import QTest


@pytest.fixture
def window(tmp_path, monkeypatch):
    import main
    from ui import app as app_module, config_io
    from ui.deck.viewport import Viewport
    from utils import paths
    qt = QApplication.instance() or QApplication([])
    main.apply_app_font(qt, main.load_fonts())
    monkeypatch.setattr(config_io, "_config_path", lambda: tmp_path / "config.json")
    monkeypatch.setattr(config_io, "_config_dir", lambda: tmp_path)
    monkeypatch.setattr(app_module, "_config_dir", lambda: tmp_path)
    monkeypatch.setattr(paths, "writable_root", lambda: tmp_path)
    monkeypatch.setattr(app_module, "load_config", lambda: copy.deepcopy(config_io.DEFAULTS))
    monkeypatch.setattr(app_module.HotkeyManager, "start", lambda self: None)
    monkeypatch.setattr(Viewport, "start", lambda self: None)
    monkeypatch.setattr(app_module.App, "_apply_native_chrome", lambda self: None)
    app = app_module.App()
    app.show()
    qt.processEvents()
    yield app
    app.close()
    qt.processEvents()


@pytest.mark.parametrize("width,height", [(960, 640), (1200, 720), (1440, 900), (1920, 1080)])
@pytest.mark.parametrize("mode", ["click", "record", "ai"])
def test_editors_fit_at_supported_sizes(window, tmp_path, width, height, mode):
    window.resize(width, height)
    window.show_page(mode)
    for _ in range(4):
        QApplication.processEvents()
    QTest.qWait(250)  # let expander animations reach their final layout
    window._tick()
    deck = window.deck
    pane = deck.editor_pane
    origin = pane.mapTo(window, QPoint(0, 0))
    assert pane.isVisible()
    assert origin.x() >= 0
    assert origin.x() + pane.width() <= window.width()
    assert pane.width() >= 540
    assert window.width() == width
    assert window.height() == height
    if mode == "click":
        assert not window.click_page.timing_expander.is_open()
    if deck.deck_page.isVisible():
        controls = deck.control_deck
        for widget in (controls.loop_btn, controls.hold_btn, controls.min_slider,
                       controls.max_slider, controls.realism_slider):
            pos = widget.mapTo(controls, QPoint(0, 0))
            assert 0 <= pos.x() and pos.x() + widget.width() <= controls.width()
    window.grab().save(str(tmp_path / f"{mode}-{width}.png"))


def test_key_only_sequence_can_start(window):
    from modules.recorder import RecorderStep, KIND_KEY
    window._steps = [RecorderStep(kind=KIND_KEY, key_combo="a")]
    window._active_mode = "recorder"
    assert not window._preflight_failures()


def test_save_error_is_visible_and_clears_after_retry(window, monkeypatch):
    from ui import config_io
    with monkeypatch.context() as m:
        m.setattr(config_io.os, "replace", lambda *args: (_ for _ in ()).throw(PermissionError("locked")))
        assert not config_io.save_config(window.cfg)
        window._tick()
        assert "locked" in window.statusBar().currentMessage()
        assert not window.close()
    assert config_io.save_config(window.cfg)
    window._tick()
    assert not window.statusBar().currentMessage()


def test_cancelled_asset_start_never_launches_a_bot(window, monkeypatch):
    import threading
    from ai import wiki
    from test_asset_preparation import pump_until
    entered, release = threading.Event(), threading.Event()
    started, completed = [], []
    class Client:
        def fetch_item_image(self, name):
            entered.set()
            release.wait(2)
            return "cached.png"
    monkeypatch.setattr(wiki, "default_client", lambda _: Client())
    monkeypatch.setattr(window, "_on_start_ai", lambda **kw: started.append(kw))
    window._ai_item_names = ["Test item"]
    window._prepare_ai_assets()
    job = window._asset_job
    job.completed.connect(completed.append)
    pump_until(entered.is_set)
    assert not window.start_btn.isEnabled()
    assert window.stop_btn.isEnabled()
    window._on_stop()
    release.set()
    pump_until(lambda: bool(completed))
    assert not started
    assert not window._ai_preparing
    assert window.start_btn.isEnabled()


def test_closing_waits_for_bot_worker(window, monkeypatch):
    from ui import app as app_module
    deferred = []
    with monkeypatch.context() as m:
        m.setattr(window.bot_runner, "wait", lambda _: False)
        m.setattr(app_module.QTimer, "singleShot", lambda delay, callback: deferred.append(callback))
        assert not window.close()
        assert window.isVisible()
        assert deferred
        assert "Stopping" in window.statusBar().currentMessage()


def test_compact_timing_panel_has_real_anti_cluster_state(window, tmp_path):
    from PySide6.QtWidgets import QLabel
    from ui.deck.columns import CadencePanel, RunProgressPanel
    window.resize(1920, 1080)
    window.show_page("click")
    QTest.qWait(250)
    panel = window.findChild(CadencePanel)
    window.cfg["anti_cluster_enabled"] = True
    window.cfg["anti_cluster_radius"] = 17
    panel.tick()
    QApplication.processEvents()
    assert panel.height() == 166
    text = " ".join(label.text() for label in panel.findChildren(QLabel))
    assert "ANTI-CLUSTER" in text and "17px" in text
    assert window.findChild(RunProgressPanel).isVisible()
    window.grab().save(str(tmp_path / "compact-timing.png"))


def test_wide_short_window_stays_within_requested_size(window):
    window.resize(1920, 640)
    window.show_page("click")
    QTest.qWait(250)
    assert window.height() == 640
    assert window.deck.right.geometry().bottom() <= window.deck.height()


def test_idle_run_card_and_explicit_timing(window):
    from ui.deck.columns import RunProgressPanel
    panel = window.findChild(RunProgressPanel)
    panel.tick()
    assert panel.title.text() == "RUN READINESS"
    assert "Draw" in panel.phase.text() or "draw" in panel.phase.text()
    assert not window.click_page.timing_expander.is_open()
    window.click_page.reveal_timing()
    QTest.qWait(250)
    assert window.click_page.timing_expander.is_open()
    assert window.click_page.timing_card.height() >= 280
