"""Regression checks for Record presets and AI lifecycle failures."""
import json
import time
from types import SimpleNamespace

import pytest
from PIL import Image
from PySide6.QtCore import QCoreApplication

from modules.recorder import RecorderStep, KIND_KEY, KIND_TRACK, KIND_LOOP, KIND_CLICK
from modules import sequence_library as library
from ai.bot.bot import Bot
from ai.bot.runner import BotRunner, _BotWorker
from test_ai_replay import make_worker, scene, RecordingActuator


def test_presets_restore_independent_images_and_keep_loop_links(tmp_path, monkeypatch):
    monkeypatch.setattr(library, "_config_dir", lambda: tmp_path)
    source = tmp_path / "track.png"
    Image.new("RGB", (10, 10), "red").save(source)
    track = RecorderStep(kind=KIND_TRACK, template_path="track.png")
    loop = RecorderStep(kind=KIND_LOOP, loop_target_step_id=track.step_id)
    library.save_sequence("example", [track, loop])
    source.unlink()
    first = library.load_sequence("example")
    second = library.load_sequence("example")
    assert first[0].template_path != second[0].template_path
    assert (tmp_path / first[0].template_path).is_file()
    assert first[1].loop_target_step_id == first[0].step_id == track.step_id
    (tmp_path / first[0].template_path).unlink()
    assert (tmp_path / second[0].template_path).is_file()


def test_invalid_preset_rejects_whole_sequence(tmp_path, monkeypatch):
    monkeypatch.setattr(library, "_config_dir", lambda: tmp_path)
    path = library.save_sequence("example", [RecorderStep(kind=KIND_KEY, key_combo="a")])
    data = json.loads(path.read_text())
    data["steps"].append(None)
    path.write_text(json.dumps(data))
    with pytest.raises(ValueError, match="step 2"):
        library.load_sequence("example")


def test_failed_preset_save_preserves_previous(tmp_path, monkeypatch):
    monkeypatch.setattr(library, "_config_dir", lambda: tmp_path)
    path = library.save_sequence("example", [RecorderStep(kind=KIND_KEY, key_combo="a")])
    before = path.read_bytes()
    def locked(*args):
        raise PermissionError("locked")
    monkeypatch.setattr(library.os, "replace", locked)
    with pytest.raises(PermissionError):
        library.save_sequence("example", [])
    assert path.read_bytes() == before


def test_disabled_steps_do_not_block_and_invalid_loop_does():
    from ui.readiness import preflight_failures
    app = SimpleNamespace(cfg={}, _active_mode="recorder",
        _sequence_uses_keys=lambda: True, key_backend_status=lambda: (True, "ready"), _steps=[
        RecorderStep(kind=KIND_CLICK, enabled=False),
        RecorderStep(kind=KIND_KEY, key_combo="a")])
    assert not preflight_failures(app)
    app._steps.append(RecorderStep(kind=KIND_LOOP, loop_target_step_id="missing"))
    assert any("earlier target" in error for error in preflight_failures(app))


def test_replay_toggle_cannot_enable_input(tmp_path):
    worker, actuator, matches = make_worker(tmp_path, [scene(True)], dry_run=False)
    worker.set_dry_run(False)
    worker.run()
    assert matches == [True]
    assert not actuator.clicks


def test_stop_before_worker_start_sends_no_input(tmp_path):
    worker, actuator, matches = make_worker(tmp_path, [scene(True)])
    reasons = []
    worker.finished.connect(reasons.append)
    worker.stop()
    worker.run()
    assert not matches and not actuator.clicks
    assert reasons == ["stopped before startup"]


def test_live_capture_failure_stops_instead_of_spinning():
    class BrokenSource:
        origin = (0, 0)
        calls = 0
        def grab(self):
            self.calls += 1
            raise OSError("capture unavailable")
        def close(self):
            pass
    worker = _BotWorker(Bot("broken", auto_camera=False), tick_rate_hz=1000,
                        default_monitor=1, actuator=RecordingActuator())
    worker._frame_source = source = BrokenSource()
    reasons = []
    worker.finished.connect(reasons.append)
    worker.run()
    assert source.calls == 5
    assert reasons == ["screen capture failed 5 consecutive times"]


def test_startup_backend_failure_finishes_worker(tmp_path):
    worker, actuator, matches = make_worker(tmp_path, [scene(True)])
    def fail():
        raise OSError("backend disconnected")
    actuator.reset_stop = fail
    reasons = []
    worker.finished.connect(reasons.append)
    worker.run()
    assert len(reasons) == 1 and "backend disconnected" in reasons[0]
    assert not matches and not actuator.clicks


def test_public_replay_restarts_ignore_old_completion(tmp_path):
    qt = QCoreApplication.instance()
    if qt is None:
        from PySide6.QtWidgets import QApplication
        qt = QApplication([])
    Image.fromarray(scene(True)).save(tmp_path / "000.png")
    runner = BotRunner()
    actuator = RecordingActuator()
    bot = Bot("thread replay", auto_camera=False, dry_run=False)
    try:
        runner.play_replay(bot, str(tmp_path), tick_rate_hz=1000, actuator=actuator)
        assert runner.wait(3000)
        # Do not dispatch the old completion until the new thread is active.
        runner.play_replay(bot, str(tmp_path), loop=True, tick_rate_hz=100,
                           actuator=actuator)
        runner.set_dry_run(False)
        assert runner.dry_run_reason() == "Replay: input disabled"
        qt.processEvents()
        assert runner.is_running()
        runner.stop()
        assert runner.wait(3000)
        qt.processEvents()
        assert not runner.is_running()
        assert not actuator.clicks
    finally:
        runner.stop()
        runner.wait(3000)
        qt.processEvents()


@pytest.fixture
def bundled_bot(monkeypatch):
    import importlib.util
    from pathlib import Path
    from ai import captures
    monkeypatch.setattr(captures, "snapshot", lambda name: object())
    monkeypatch.setattr(captures, "colors", lambda name: [0x00FFFF])
    monkeypatch.setattr(captures, "roi", lambda name: (0, 0, 100, 100))
    def load(name):
        spec = importlib.util.spec_from_file_location("audit_" + name,
            Path("ai/tasks/library") / (name + ".py"))
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod
    return load


def test_acadia_banks_before_chopping_and_bounds_preset_retry(bundled_bot, monkeypatch):
    mod = bundled_bot("menaphos_acadia")
    names = [rule.func.__name__ for rule in mod.bot.rules]
    assert names.index("bank_when_full") < names.index("chop_acadia_canopy")
    actions = []
    monkeypatch.setattr(mod, "key", lambda key: actions.append(key))
    monkeypatch.setattr(mod, "wait", lambda ms: None)
    monkeypatch.setattr(mod, "stop", lambda reason: actions.append(reason))
    monkeypatch.setattr(mod, "is_bank_open", lambda *a, **kw: True)
    for _ in range(4):
        assert mod.load_bank_preset()
    assert actions[:3] == ["1"] * 3
    assert "three attempts" in actions[3]
    monkeypatch.setattr(mod, "world", lambda: SimpleNamespace(inventory=None))
    assert mod.require_bank_setup()
    assert "Inventory ROI" in actions[-1]


def test_full_inventory_missing_chest_cannot_fall_through_to_chop(bundled_bot, monkeypatch):
    mod = bundled_bot("menaphos_acadia")
    stopped = []
    monkeypatch.setattr(mod, "world", lambda: SimpleNamespace(
        inventory=SimpleNamespace(count_filled=lambda: 28)))
    monkeypatch.setattr(mod, "find_color", lambda **kw: None)
    monkeypatch.setattr(mod, "stop", stopped.append)
    assert mod.bank_when_full()
    assert "bank chest" in stopped[0]


def test_fishing_stops_unproductive_recasts(bundled_bot, monkeypatch):
    mod = bundled_bot("menaphos_vip_fishing")
    clicks, stopped = [], []
    monkeypatch.setattr(mod, "world", lambda: SimpleNamespace(
        inventory=SimpleNamespace(count_filled=lambda: 0)))
    monkeypatch.setattr(mod, "player_is_animating", lambda: False)
    monkeypatch.setattr(mod, "find_interactable", lambda **kw: SimpleNamespace(point=(5, 5), count=40))
    monkeypatch.setattr(mod, "SPOT_TOOLTIP", None)
    monkeypatch.setattr(mod, "move", lambda pos: None)
    monkeypatch.setattr(mod, "wait", lambda ms: None)
    monkeypatch.setattr(mod, "log", lambda msg: None)
    monkeypatch.setattr(mod, "click", SimpleNamespace(fire=lambda: clicks.append(1)))
    monkeypatch.setattr(mod, "stop", stopped.append)
    for _ in range(31):
        mod.recast_when_idle()
    assert len(clicks) == 10
    assert len(stopped) == 1 and "Ten recasts" in stopped[0]



def test_record_template_loss_and_reacquisition(monkeypatch):
    import numpy as np
    from modules.tracker import TemplateTracker, TrackerConfig
    rng = np.random.default_rng(42)
    template = rng.integers(0, 255, (12, 12, 3), dtype=np.uint8)
    screen = np.zeros((80, 100, 4), dtype=np.uint8)
    class Source:
        def grab(self, rect):
            x, y = rect["left"] + 200, rect["top"] - 100
            return screen[y:y+rect["height"], x:x+rect["width"]]
    tracker = TemplateTracker(TrackerConfig(match_threshold=0.95, scale_steps=1,
                                            search_radius=15))
    monkeypatch.setattr(tracker, "_get_sct", lambda: Source())
    tracker.set_template(template, (-180, 120, -168, 132))
    screen[20:32, 20:32, :3] = template
    assert tracker.locate(search_rect=(-200, 100, 100, 80)) == (-174, 126)
    screen[:] = 0
    assert tracker.locate(search_rect=(-200, 100, 100, 80)) is None
    assert not tracker.state.is_locked
    screen[50:62, 70:82, :3] = template
    assert tracker.locate(search_rect=(-200, 100, 100, 80)) == (-124, 156)


def test_record_color_extra_sample_and_target_loss(monkeypatch):
    import numpy as np
    from modules.clicker import Clicker
    from modules.stats import Stats
    from modules.recorder import KIND_COLOR
    from utils import dpi_cursor
    screen = np.zeros((80, 100, 4), dtype=np.uint8)
    screen[20:30, 40:50, :3] = (0, 255, 255)  # BGR yellow, alternate color
    class Source:
        def grab(self, rect):
            return SimpleNamespace(width=100, height=80, bgra=screen.tobytes())
    engine = Clicker(Stats())
    monkeypatch.setattr(engine, "_get_engine_mss", lambda: Source())
    monkeypatch.setattr(dpi_cursor, "physical_to_dip", lambda x, y: (x, y))
    step = RecorderStep(kind=KIND_COLOR, color_target_rgb=(255, 0, 0),
                        color_extra_rgbs=[(255, 255, 0)], color_tolerance=0,
                        color_search_rect=(-200, 100, -100, 180))
    x, y = engine._find_color_target(step)
    assert -160 <= x < -150 and 120 <= y < 130
    screen[:] = 0
    assert engine._find_color_target(step) is None
