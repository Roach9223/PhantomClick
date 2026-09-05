"""``BootSplash``: the short boot animation shown while the main window is
built.

It plays the frames in ``packaging/boot`` (rendered in Blender by
``packaging/blender_mark.py``, composed by ``packaging/make_boot.py``) at
30 fps in a frameless, always-on-top window centred on the screen under
the cursor, then emits ``finished``. A click or any key skips it. The
``boot_animation`` config key (default on) and the
``PHANTOMCLICK_NO_BOOT`` environment variable both turn it off, and a
missing frames folder means it simply never shows.

This is the one place in the app where motion is decoration; it runs
before the console exists and never again.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from PySide6.QtCore import QTimer, Qt, Signal
from PySide6.QtGui import QCursor, QGuiApplication, QPainter, QPixmap
from PySide6.QtWidgets import QWidget

FPS = 30


def frames_dir() -> Path:
    from utils.paths import bundled_root
    return bundled_root() / "packaging" / "boot"


def available() -> bool:
    d = frames_dir()
    return d.is_dir() and any(d.glob("frame_*.png"))


class BootSplash(QWidget):
    finished = Signal()

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent, Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setAttribute(Qt.WA_DeleteOnClose, False)
        self._frames: list[QPixmap] = []
        for p in sorted(frames_dir().glob("frame_*.png")):
            pm = QPixmap(str(p))
            if not pm.isNull():
                self._frames.append(pm)
        self._idx = 0
        self._done = False
        w = self._frames[0].width() if self._frames else 640
        h = self._frames[0].height() if self._frames else 320
        self.setFixedSize(w, h)
        self._timer = QTimer(self)
        self._timer.setInterval(int(1000 / FPS))
        self._timer.timeout.connect(self._advance)
        self._center()

    def _center(self) -> None:
        screen = QGuiApplication.screenAt(QCursor.pos()) or QGuiApplication.primaryScreen()
        if screen is None:
            return
        g = screen.availableGeometry()
        self.move(g.x() + (g.width() - self.width()) // 2,
                  g.y() + (g.height() - self.height()) // 2)

    def frame_count(self) -> int:
        return len(self._frames)

    def start(self) -> None:
        if not self._frames:
            self._finish()
            return
        self.show()
        self.raise_()
        self._timer.start()

    def _advance(self) -> None:
        if self._idx < len(self._frames) - 1:
            self._idx += 1
            self.update()
        else:
            # Hold the last frame a beat so the lock-in reads.
            self._timer.stop()
            QTimer.singleShot(350, self._finish)

    def _finish(self) -> None:
        if self._done:
            return
        self._done = True
        self._timer.stop()
        self.finished.emit()

    def skip(self) -> None:
        self._finish()

    def paintEvent(self, _event):  # noqa: N802 (Qt name)
        if not self._frames:
            return
        p = QPainter(self)
        p.drawPixmap(0, 0, self._frames[self._idx])
        p.end()

    def mousePressEvent(self, event):  # noqa: N802 (Qt name)
        self.skip()
        event.accept()

    def keyPressEvent(self, event):  # noqa: N802 (Qt name)
        self.skip()
        event.accept()
