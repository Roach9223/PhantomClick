"""Install-root path resolution that works both in dev and when frozen
by PyInstaller.

Two distinct roots matter once the app ships as an .exe:

- **writable_root** — where user data lives (``config.json``,
  ``phantomclick.log``, ``templates/``, captured PNGs, the global
  capture library). When frozen this MUST be the directory next to the
  .exe, never PyInstaller's ``_MEIPASS`` temp extract (which is wiped
  on exit, so a ``--onefile`` build would lose every write). This
  mirrors the logic already in :func:`ui.config_io._config_dir` —
  keep the two in sync.

- **bundled_root** — where read-only resources shipped inside the
  build live (``rs3vision`` data, the ``ai/tasks/library`` manifests).
  When frozen that's ``sys._MEIPASS``; in dev it's the repo root.
"""

from __future__ import annotations

import sys
from pathlib import Path


def writable_root() -> Path:
    """User-data root: next to the .exe when frozen, else the repo root."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent


def bundled_root() -> Path:
    """Read-only resource root: PyInstaller ``_MEIPASS`` when frozen,
    else the repo root."""
    base = getattr(sys, "_MEIPASS", None)
    return Path(base) if base else Path(__file__).resolve().parent.parent
