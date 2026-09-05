"""Shared pytest setup.

Puts the repo root on ``sys.path`` so ``modules.*`` / ``ui.*`` / ``utils.*``
import the same way they do from ``main.py``, and forces Qt's offscreen
platform so any module that transitively imports PySide6 can load on a
headless runner.

Two guards keep the developer's real ``config.json`` out of reach:

* every test gets ``config_io._config_path`` pointed at its own temp dir
  (tests that need a specific path patch it again themselves);
* the session fails if the real ``config.json`` next to ``main.py`` is
  not byte-identical after the run. A populated config was once replaced
  with defaults during a test / tooling pass; this makes that loud.
"""

from __future__ import annotations

import hashlib
import os
import sys
from pathlib import Path

import pytest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

_REAL_CONFIG = Path(ROOT) / "config.json"


def _digest(path: Path) -> str | None:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return None


@pytest.fixture(autouse=True)
def _isolated_config_path(tmp_path, monkeypatch):
    from ui import config_io
    monkeypatch.setattr(config_io, "_config_path", lambda: tmp_path / "config.json")
    yield


@pytest.fixture(scope="session", autouse=True)
def _real_config_untouched():
    before = _digest(_REAL_CONFIG)
    yield
    after = _digest(_REAL_CONFIG)
    if before != after:
        pytest.fail(
            f"{_REAL_CONFIG} changed during the test session. A test wrote "
            "to the real config path; patch config_io._config_path in it.",
            pytrace=False,
        )
