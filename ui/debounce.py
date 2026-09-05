"""``Debouncer`` for slider-driven saves.

Qt sliders emit ``valueChanged`` on every pixel of a drag. Writing
``config.json`` (and re-pushing the engine config) on each tick is
wasted disk churn and, for the realism dial, a toast storm. Callers keep
updating the visible label live and hand the persist step to a
``Debouncer``, which restarts a single-shot timer on every call and runs
only the latest callable once the user has paused for ``ms``.
"""

from __future__ import annotations

from typing import Callable, Optional

from PySide6.QtCore import QObject, QTimer


DEFAULT_DEBOUNCE_MS = 200


class Debouncer(QObject):
    def __init__(self, ms: int = DEFAULT_DEBOUNCE_MS, parent: Optional[QObject] = None):
        super().__init__(parent)
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(int(ms))
        self._timer.timeout.connect(self._fire)
        self._pending: Optional[Callable[[], None]] = None

    def call(self, fn: Callable[[], None]) -> None:
        """Schedule ``fn``; a later call before the timer fires replaces it."""
        self._pending = fn
        self._timer.start()

    def flush(self) -> None:
        """Run the pending callable now (used on close so nothing is lost)."""
        self._timer.stop()
        self._fire()

    def pending(self) -> bool:
        return self._pending is not None

    def _fire(self) -> None:
        fn = self._pending
        self._pending = None
        if fn is not None:
            fn()
