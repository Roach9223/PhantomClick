"""Back-compat shim — re-exports :class:`App` and :func:`run` from :mod:`ui.app`.

The real class lives in ``ui/app.py``; this module exists so existing
``from app import …`` callers (notably ``main.py`` and any user shortcut)
keep working unchanged.
"""

from __future__ import annotations

from ui.app import App, run

__all__ = ["App", "run"]
