"""Saved-frame integration: PNG decoding → Rust detection → rules → actuator.

Synthetic fixtures establish reproducible behavior, not game success rates.
"""
import numpy as np
import pytest
from PIL import Image

from ai.bot import api
from ai.bot.bot import Bot
from ai.bot.replay import FrameReplay
from ai.bot.runner import _BotWorker
from ai.input.frame_source import ReplaySource


class RecordingActuator:
    def __init__(self):
        self.clicks = []
        self.listener = None

    def set_input_listener(self, listener):
        self.listener = listener

    def click(self, x, y, button="left"):
        self.clicks.append((x, y, button))
        if self.listener:
            self.listener("click")


def make_worker(tmp_path, frames, *, dry_run=False, dry_limit=60):
    for i, frame in enumerate(frames):
        Image.fromarray(frame).save(tmp_path / f"{i:03}.png")
    bot = Bot("Replay regression", dry_run=dry_run, auto_camera=False,
              auto_stop_dry_ticks=dry_limit)
    matches = []
    @bot.rule()
    def find_and_click():
        match = api.find_color(0xFFFF00, cts=1, tol=1, min_pixels=20)
        matches.append(bool(match))
        if match:
            api.click.at(match.point)
            return True
        return False
    actuator = RecordingActuator()
    worker = _BotWorker(bot, tick_rate_hz=1000, default_monitor=1, actuator=actuator)
    worker._frame_source = ReplaySource(FrameReplay(tmp_path), origin=(-200, 100))
    return worker, actuator, matches


def scene(with_target):
    frame = np.zeros((80, 100, 3), dtype=np.uint8)
    # Small distractor must be rejected by the cluster-size threshold.
    frame[1:3, 1:3] = (255, 255, 0)
    if with_target:
        frame[20:30, 40:50] = (255, 255, 0)
    return frame


@pytest.mark.parametrize("dry_run", [False, True])
def test_target_loss_reacquisition_and_dry_run(tmp_path, dry_run):
    worker, actuator, matches = make_worker(
        tmp_path, [scene(True), scene(False), scene(True)], dry_run=dry_run)
    reasons = []
    worker.finished.connect(reasons.append)
    worker.run()
    assert matches == [True, False, True]
    assert reasons == ["replay finished"]
    if dry_run:
        assert actuator.clicks == []
    else:
        assert len(actuator.clicks) == 2
        for x, y, button in actuator.clicks:
            assert -160 <= x < -150 and 120 <= y < 130
            assert button == "left"


def test_missing_target_stops_at_dry_tick_limit(tmp_path):
    worker, actuator, matches = make_worker(tmp_path, [scene(False)] * 5, dry_limit=2)
    reasons = []
    worker.finished.connect(reasons.append)
    worker.run()
    assert len(matches) == 2
    assert not actuator.clicks
    assert reasons and "dry" in reasons[0].lower()
