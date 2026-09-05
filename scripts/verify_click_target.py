"""Interactive Windows integration check; sends real clicks only into its test window.

Run explicitly: python scripts/verify_click_target.py
Uses temporary in-memory engine settings, never the user's configuration.
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import main  # DPI awareness before Qt creation
from PySide6.QtCore import QPoint, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QLabel

from modules.clicker import Clicker, ClickerState
from modules.stats import Stats
from modules.recorder import RecorderStep, KIND_CLICK, KIND_KEY, KIND_PAUSE, KIND_LOOP
from modules.zone_selector import Zone, WindowLock
from utils import dpi_cursor, window_finder


class Target(QLabel):
    def __init__(self):
        super().__init__("PhantomClick integration test\nPlease leave this window unobstructed.\nEsc stops the test.")
        self.setWindowTitle("PhantomClick controlled click target")
        self.setWindowFlag(Qt.WindowStaysOnTopHint)
        self.setAlignment(Qt.AlignCenter)
        self.setStyleSheet("background: #17231b; color: white; font-size: 18px;")
        self.resize(600, 400)
        self.received = []
        self.keys = []
        self.setFocusPolicy(Qt.StrongFocus)

    def mousePressEvent(self, event):
        self.received.append((event.position().x(), event.position().y()))

    def keyPressEvent(self, event):
        if event.text():
            self.keys.append(event.text())
        if event.key() == Qt.Key_Escape:
            self.close()


def run():
    qt = QApplication([])
    target = Target()
    target.show()
    target.raise_()
    target.activateWindow()
    QTest.qWait(350)
    dpi_cursor.refresh_screens()
    engine = Clicker(Stats())
    engine.realism = 0
    engine.prestart_delay = 0.5
    engine.min_delay = engine.max_delay = 0.25
    engine.fatigue_enabled = False
    engine.break_bursts_enabled = False
    engine.hover_enabled = False
    engine.idle_wander_enabled = False
    engine.overshoot_enabled = False
    screen = target.screen().geometry()
    engine.target_screen_bounds = (screen.x(), screen.y(), screen.width(), screen.height())
    pos = target.mapToGlobal(QPoint(220, 160))
    zone = Zone.make_rect(pos.x(), pos.y(), pos.x() + 100, pos.y() + 80)
    info = window_finder.window_info(int(target.winId()))
    assert info is not None
    engine.zone = zone.with_lock(WindowLock(title=info.title, cls=info.cls, anchor_rect=info.rect_dip))
    def start():
        engine.start()
        # Enumeration deliberately excludes our own process. Seed the known
        # test HWND during the countdown, then exercise real Win32 geometry,
        # minimized-state checks and the production hold/reacquire path.
        engine._lock_cache[(info.title, info.cls)] = info.hwnd
    target.destroyed.connect(engine.stop)
    def until(predicate, seconds=8):
        deadline = time.monotonic() + seconds
        while not predicate() and time.monotonic() < deadline:
            if not target.isVisible():
                raise AssertionError("test window closed")
            QTest.qWait(20)
        assert predicate(), "integration check timed out"
    try:
        engine.stop_after_clicks_enabled = True
        engine.stop_after_clicks = 3
        start()
        until(lambda: engine.state == ClickerState.IDLE)
        QTest.qWait(100)
        assert len(target.received) == 3, target.received
        assert all(210 <= x <= 330 and 150 <= y <= 250 for x, y in target.received)
        print("PASS: 3 actual clicks received inside the target area", flush=True)

        engine.stop_after_clicks_enabled = False
        start()
        until(lambda: len(target.received) >= 4)
        engine.pause()
        QTest.qWait(300)  # settle any press already in flight
        paused_count = len(target.received)
        QTest.qWait(600)
        assert len(target.received) == paused_count
        engine.resume()
        until(lambda: len(target.received) > paused_count)
        print("PASS: pause suppresses clicks; resume restores them", flush=True)

        engine.pause()
        QTest.qWait(200)
        target.showMinimized()
        QTest.qWait(300)
        engine.resume()
        count = len(target.received)
        QTest.qWait(800)
        assert len(target.received) == count
        target.showNormal()
        target.raise_()
        target.activateWindow()
        until(lambda: len(target.received) > count)
        print("PASS: minimized target holds; restored target reacquires", flush=True)

        before = time.monotonic()
        engine.stop()
        elapsed = time.monotonic() - before
        QTest.qWait(100)
        stopped_count = len(target.received)
        QTest.qWait(600)
        assert engine.state == ClickerState.IDLE
        assert len(target.received) == stopped_count
        assert elapsed < 1.0, elapsed
        print(f"PASS: stop took {elapsed:.3f}s; no later clicks", flush=True)

        target.setFocus()
        target.activateWindow()
        engine.mode = "recorder"
        engine.key_input_method = "sendinput"
        first = RecorderStep(kind=KIND_CLICK, zone=engine.zone,
                             delay_min=0.05, delay_max=0.05)
        engine.recorder_steps = [
            first,
            RecorderStep(kind=KIND_KEY, key_combo="a", key_repeat=2,
                         delay_min=0.05, delay_max=0.05),
            RecorderStep(kind=KIND_PAUSE, delay_min=0.05, delay_max=0.05),
            RecorderStep(kind=KIND_LOOP, loop_target_step_id=first.step_id, loop_count=1),
            RecorderStep(kind=KIND_KEY, key_combo="b", delay_min=0.05, delay_max=0.05),
        ]
        engine.on_event = lambda kind, text: engine._stop.set() if text == "KEY B" else None
        before_clicks = len(target.received)
        start()
        until(lambda: engine.state == ClickerState.IDLE)
        QTest.qWait(150)
        assert target.keys == ["a", "a", "a", "a", "b"], target.keys
        assert len(target.received) - before_clicks == 2
        print("PASS: Record click/key/pause/finite-loop macro delivered two clicks and A A A A B", flush=True)

    finally:
        engine.stop()
        target.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
