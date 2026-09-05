"""humanizer.click button mapping with the pynput controller faked out, so
no real button is ever pressed."""

from __future__ import annotations

import pytest
from pynput.mouse import Button

from utils import humanizer


class FakeMouse:
    def __init__(self):
        self.ops: list[tuple[str, object]] = []

    def press(self, btn):
        self.ops.append(("press", btn))

    def release(self, btn):
        self.ops.append(("release", btn))


@pytest.fixture
def fake_mouse(monkeypatch):
    fm = FakeMouse()
    monkeypatch.setattr(humanizer, "_mouse", fm)
    # Collapse the pre-click pause and the press hold so the test is quick.
    monkeypatch.setattr(humanizer, "_sleep", lambda stop, s: False)
    return fm


@pytest.mark.parametrize("name,expected", [
    ("left", Button.left),
    ("right", Button.right),
    ("middle", Button.middle),
    ("MIDDLE", Button.middle),
    ("bogus", Button.left),
])
def test_click_maps_button_names(fake_mouse, name, expected):
    assert humanizer.click(name, "single") is False
    assert fake_mouse.ops == [("press", expected), ("release", expected)]


def test_double_middle_click_presses_twice(fake_mouse):
    assert humanizer.click("middle", "double") is False
    assert fake_mouse.ops == [
        ("press", Button.middle), ("release", Button.middle),
        ("press", Button.middle), ("release", Button.middle),
    ]
