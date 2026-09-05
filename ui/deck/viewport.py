"""Live viewport: a downscaled capture of the target monitor with the click
zone, recent clicks, rulers and readouts painted over it.

Capture runs on :class:`CaptureWorker`, a QThread with its own ``mss``
handle (same persistent-handle pattern as ``ui/monitor_server.py``). It
emits a ``QImage`` per frame; the widget only ever touches Qt from the
GUI thread. The worker is stopped when the window hides, when the
splitter collapses the viewport to zero width, and on window close, so
an idle app does not keep grabbing the screen.

Resolution: the widget tells the worker its paint area in DEVICE pixels
(``size * devicePixelRatioF``) and the worker scales the native grab once
to fit it, downscaling only (cv2 INTER_AREA when available, else Qt
smooth). The emitted image carries the widget's DPR so ``drawImage``
maps device pixels 1:1 and text in the capture stays crisp on a 150%
monitor instead of being shrunk to 1024 wide and stretched back up.

Zoom (1x, 1.5x, 2x, 3x) shrinks the worker's target rect around the
active zone, so a zoomed frame costs less to grab, not more. Nothing
about zoom is persisted; it is a look, not a setting.

Fit: the frame is letterboxed to its aspect when the bands would be
small. When the viewport is much taller than the frame (editor pane
open on a wide monitor) the frame covers the area instead: scaled to
the height and cropped left and right around the zone, so the centre
of the screen shows the game, not empty grid. Rulers, clicks and the
reticle all clip to the visible part.
"""

from __future__ import annotations

import math
import threading
import time
from typing import Optional

from PySide6.QtCore import QRect, QRectF, QThread, Qt, Signal
from PySide6.QtGui import QColor, QFont, QImage, QPainter, QPen, QRegion
from PySide6.QtWidgets import QApplication, QWidget

from modules.clicker import ClickerState
from modules.zone_lock import HOLD_STATUSES, STATUS_SCREEN

from . import common as c
from .zone_map import _brackets


# Device-pixel ceiling on an emitted frame. A 4K monitor at 1x is the
# widest anything sensible asks for; beyond it the frame is pure cost.
_MAX_FRAME_W = 3840
_RULER = 20
_ZOOM_RAIL_W = 26
_ZOOM_LEVELS = (1.0, 1.5, 2.0, 3.0)
_RAIL_HIT_H = 24   # px at each end of the rail that act as + / -
# Letterbox bands taller than this share of the area switch the fit to
# cover (cropped), so a pane-narrowed viewport still shows the game.
_FILL_THRESHOLD = 0.25


def _hairline(color: str) -> QPen:
    """1 device pixel wide at any DPR. A plain 1 px pen is 1 logical pixel,
    which at 150% is a 1.5 px smear across two device rows."""
    pen = QPen(QColor(color))
    pen.setWidth(1)
    pen.setCosmetic(True)
    return pen


def _fit_scale(src_w: int, src_h: int, out_w: int, out_h: int) -> float:
    """Downscale factor that fits ``src`` inside ``out``. Never above 1.0:
    a target larger than the native grab keeps the grab as it is, since
    upscaling on the worker only invents pixels the painter would have
    interpolated anyway."""
    if src_w <= 0 or src_h <= 0:
        return 1.0
    scale = min(out_w / src_w, out_h / src_h, 1.0)
    if src_w * scale > _MAX_FRAME_W:
        scale = _MAX_FRAME_W / src_w
    return max(scale, 1.0 / src_w)


def _scale_frame(shot, out_w: int, out_h: int, cv2_mod, np_mod) -> QImage:
    """Native mss grab to a QImage no larger than ``out_w x out_h`` device
    pixels, scaled once. INTER_AREA is the right kernel for shrinking
    screen text (it averages, so thin strokes do not alias away); the
    Qt smooth path is the fallback when cv2 / numpy are missing."""
    w, h = int(shot.width), int(shot.height)
    scale = _fit_scale(w, h, out_w, out_h)
    tw = max(1, int(round(w * scale)))
    th = max(1, int(round(h * scale)))
    if tw >= w and th >= h:
        # mss hands back BGRA, which is ARGB32 on little-endian.
        return QImage(shot.bgra, w, h, w * 4, QImage.Format_ARGB32).copy()
    if cv2_mod is not None and np_mod is not None:
        arr = np_mod.frombuffer(shot.bgra, dtype=np_mod.uint8).reshape(h, w, 4)
        small = np_mod.ascontiguousarray(
            cv2_mod.resize(arr, (tw, th), interpolation=cv2_mod.INTER_AREA))
        return QImage(small.data, tw, th, tw * 4, QImage.Format_ARGB32).copy()
    img = QImage(shot.bgra, w, h, w * 4, QImage.Format_ARGB32)
    return img.scaled(tw, th, Qt.IgnoreAspectRatio, Qt.SmoothTransformation)


class CaptureWorker(QThread):
    frameReady = Signal(QImage, tuple)   # scaled frame, DIP rect captured (x, y, w, h)
    failed = Signal(str)

    def __init__(self, fps: float = 5.0, parent=None):
        super().__init__(parent)
        self.setObjectName("deck-viewport-capture")
        self._stop = threading.Event()
        self._fps = max(1.0, float(fps))
        # Tuple assignment is atomic in CPython, so the GUI thread can
        # swap the target rect and the output size without a lock.
        self._rect_dip: tuple[int, int, int, int] = (0, 0, 1920, 1080)
        # Output budget in device pixels plus the DPR to stamp on frames.
        self._out: tuple[int, int, float] = (1024, 576, 1.0)

    def set_target_rect(self, rect: tuple[int, int, int, int]) -> None:
        self._rect_dip = tuple(int(v) for v in rect)

    def target_rect(self) -> tuple[int, int, int, int]:
        return self._rect_dip

    def set_output_size(self, w_px: int, h_px: int, dpr: float) -> None:
        self._out = (max(1, int(w_px)), max(1, int(h_px)), max(1.0, float(dpr)))

    def output_size(self) -> tuple[int, int, float]:
        return self._out

    def stop(self) -> None:
        self._stop.set()

    def run(self) -> None:  # noqa: D401
        try:
            import mss
            sct = mss.mss()
        except Exception as e:
            self.failed.emit(f"capture init failed: {e}")
            return
        try:
            import cv2 as cv2_mod
            import numpy as np_mod
        except Exception:
            cv2_mod = np_mod = None
        failures = 0
        try:
            while not self._stop.is_set():
                rect = self._rect_dip
                out_w, out_h, dpr = self._out
                try:
                    from utils.dpi_cursor import dip_rect_to_physical
                    px, py, pw, ph = dip_rect_to_physical(*rect)
                    if pw <= 0 or ph <= 0:
                        raise ValueError("empty capture rect")
                    shot = sct.grab({"left": px, "top": py, "width": pw, "height": ph})
                    img = _scale_frame(shot, out_w, out_h, cv2_mod, np_mod)
                    img.setDevicePixelRatio(dpr)
                    failures = 0
                    self.frameReady.emit(img, rect)
                except Exception as e:
                    failures += 1
                    if failures == 3:
                        self.failed.emit(str(e))
                # After repeated failures back off so a wedged display
                # driver does not get hammered five times a second.
                wait = 1.0 / self._fps if failures < 3 else 2.0
                if self._stop.wait(wait):
                    break
        finally:
            try:
                sct.close()
            except Exception:
                pass


class Viewport(QWidget):
    def __init__(self, app, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.app = app
        self.setObjectName("deck-viewport")
        self.setMinimumSize(320, 200)
        self.setToolTip(
            "Live view of the target monitor with the click zone and recent clicks. "
            "Wheel or the + / - rail zooms around the zone; double-click toggles 2x; "
            "right-click for zone, monitor and pane actions.")
        c.fill_policy(self)
        self._worker: Optional[CaptureWorker] = None
        self._frame: Optional[QImage] = None
        # Rect the current frame covers, and the monitor it was cut from.
        # Rulers label monitor-local DIPs, so both are needed under zoom.
        self._frame_rect: tuple[int, int, int, int] = (0, 0, 1920, 1080)
        self._monitor_rect: tuple[int, int, int, int] = (0, 0, 1920, 1080)
        self._no_capture = False
        self._fail_reason = ""
        # Wait-progress tracking for the NEXT dial: seconds_until_next
        # jumps up when a new wait starts; remember that peak.
        self._wait_total = 0.0
        self._last_secs = 0.0
        self._last_frame_at = 0.0
        self._zoom_idx = 0
        # Last output budget handed to the worker: (w_px, h_px, dpr).
        self._requested_out: tuple[int, int, float] = (0, 0, 1.0)

    # -- Worker lifecycle -----------------------------------------------------

    def start(self) -> None:
        if self.is_capturing():
            return
        self._no_capture = False
        # Unparented on purpose: a parented QThread that is still running
        # when its parent is destroyed aborts the process. deleteLater on
        # finished frees it once the thread has actually exited.
        w = CaptureWorker(fps=5.0)
        w.set_target_rect(self._target_rect_dip())
        self._worker = w
        self._push_output_size()
        w.frameReady.connect(self._on_frame, Qt.QueuedConnection)
        w.failed.connect(self._on_failed, Qt.QueuedConnection)
        w.finished.connect(lambda w=w: self._on_worker_finished(w))
        w.finished.connect(w.deleteLater)
        self._worker = w
        w.start()

    def stop(self, wait_ms: int = 1500) -> None:
        w = self._worker
        if w is None:
            return
        try:
            w.stop()
            if w.isRunning() and not w.wait(wait_ms):
                try:
                    self.app.log.warning("viewport capture thread still alive after stop")
                except Exception:
                    pass
        except RuntimeError:
            # Already deleted by deleteLater after a self-exit.
            pass
        self._worker = None

    def _on_worker_finished(self, w) -> None:
        # A worker that exits on its own (capture init failed) drops its
        # reference here so is_capturing() never touches a deleted object.
        if self._worker is w:
            self._worker = None

    def is_capturing(self) -> bool:
        w = self._worker
        if w is None:
            return False
        try:
            return bool(w.isRunning())
        except RuntimeError:
            self._worker = None
            return False

    def worker_rect(self) -> Optional[tuple[int, int, int, int]]:
        """DIP rect the worker is currently asked to grab (tests, tooling)."""
        w = self._worker
        if w is None:
            return None
        try:
            return w.target_rect()
        except RuntimeError:
            return None

    # -- Output size (device pixels) -----------------------------------------------

    def _dpr(self) -> float:
        try:
            return max(1.0, float(self.devicePixelRatioF()))
        except Exception:
            return 1.0

    def _push_output_size(self) -> None:
        """Tell the worker how many device pixels the image area spans so
        it scales the grab to that once. Re-sent on resize, zoom and a
        DPR change (window dragged to another monitor). In cover mode
        the budget is the covering frame, wider than the area, so the
        crop is not an upscale."""
        avail = self._avail_rect()
        dpr = self._dpr()
        _x, _y, fw, fh = self._frame_rect
        out_w, out_h = avail.width(), avail.height()
        if self._cover(avail) and fh > 0:
            out_w = int(round(out_h * fw / fh))
        out = (max(1, int(round(out_w * dpr))),
               max(1, int(round(out_h * dpr))), dpr)
        self._requested_out = out
        w = self._worker
        if w is None:
            return
        try:
            w.set_output_size(*out)
        except RuntimeError:
            self._worker = None

    def requested_output_size(self) -> tuple[int, int, float]:
        """``(w_px, h_px, dpr)`` last requested from the worker (tests)."""
        return self._requested_out

    def resizeEvent(self, event):  # noqa: N802 (Qt name)
        super().resizeEvent(event)
        self._push_output_size()

    def _on_frame(self, img: QImage, rect: tuple) -> None:
        self._frame = img
        self._frame_rect = tuple(rect)
        self._no_capture = False
        self._last_frame_at = time.monotonic()
        self.update()

    def _on_failed(self, reason: str) -> None:
        self._no_capture = True
        self._fail_reason = reason
        self.update()

    def has_frame(self) -> bool:
        return self._frame is not None

    # -- Zoom ---------------------------------------------------------------------

    def zoom(self) -> float:
        return _ZOOM_LEVELS[self._zoom_idx]

    def zoom_levels(self) -> tuple[float, ...]:
        return _ZOOM_LEVELS

    def set_zoom_index(self, idx: int) -> None:
        idx = int(c.clamp(idx, 0, len(_ZOOM_LEVELS) - 1))
        if idx == self._zoom_idx:
            return
        self._zoom_idx = idx
        # Push the new rect straight away so the next grab is already
        # zoomed instead of waiting a tick.
        w = self._worker
        if w is not None:
            try:
                w.set_target_rect(self._target_rect_dip())
            except RuntimeError:
                pass
        self._push_output_size()
        self.update()

    def zoom_in(self) -> None:
        self.set_zoom_index(self._zoom_idx + 1)

    def zoom_out(self) -> None:
        self.set_zoom_index(self._zoom_idx - 1)

    def toggle_zoom(self) -> None:
        """Double-click: 1x when zoomed, else 2x."""
        self.set_zoom_index(0 if self._zoom_idx != 0 else _ZOOM_LEVELS.index(2.0))

    # -- Geometry helpers -------------------------------------------------

    def _monitor_rect_dip(self) -> tuple[int, int, int, int]:
        try:
            return tuple(int(v) for v in self.app.target_screen_bounds())
        except Exception:
            return tuple(self.app.virtual_rect)

    def _target_rect_dip(self) -> tuple[int, int, int, int]:
        """What the worker should grab: the whole monitor at 1x, else a
        window ``1/zoom`` of it centred on the active zone (or the monitor
        centre), clamped inside the monitor."""
        mx, my, mw, mh = self._monitor_rect_dip()
        self._monitor_rect = (mx, my, mw, mh)
        z = self.zoom()
        if z <= 1.0 or mw <= 0 or mh <= 0:
            return (mx, my, mw, mh)
        w = max(1, int(round(mw / z)))
        h = max(1, int(round(mh / z)))
        zone = self._active_zone()
        if zone is not None:
            try:
                cx, cy = zone.centroid()
            except Exception:
                cx, cy = mx + mw / 2, my + mh / 2
        else:
            cx, cy = mx + mw / 2, my + mh / 2
        x = int(round(c.clamp(cx - w / 2, mx, mx + mw - w)))
        y = int(round(c.clamp(cy - h / 2, my, my + mh - h)))
        return (x, y, w, h)

    def _monitor_index(self) -> int:
        """1-based index of the Qt screen matching the captured monitor."""
        x, y, w, h = self._monitor_rect
        try:
            for i, s in enumerate(QApplication.instance().screens()):
                g = s.geometry()
                if (g.left(), g.top(), g.width(), g.height()) == (x, y, w, h):
                    return i + 1
        except Exception:
            pass
        return 1

    def _avail_rect(self) -> QRect:
        return QRect(_RULER, _RULER,
                     self.width() - _RULER - _ZOOM_RAIL_W, self.height() - _RULER)

    def _cover(self, avail: Optional[QRect] = None) -> bool:
        """True when letterboxing would waste more than _FILL_THRESHOLD of
        the height, so the frame covers the area and crops instead."""
        avail = avail or self._avail_rect()
        _x, _y, fw, fh = self._frame_rect
        if fw <= 0 or fh <= 0 or avail.width() <= 0 or avail.height() <= 0:
            return False
        fit_h = avail.width() * fh / fw
        return fit_h < avail.height() * (1.0 - _FILL_THRESHOLD)

    def cover_mode(self) -> bool:
        """Whether the frame is currently cropped to cover the area (tests)."""
        return self._cover()

    def _image_rect(self) -> QRect:
        """Where the frame paints: inside the rulers and left of the zoom
        rail. Letterboxed to the captured rect's aspect ratio, or when
        the bands would be large, scaled to cover the area and centred
        on the zone (the rect then overhangs the area and is clipped)."""
        avail = self._avail_rect()
        fx, fy, fw, fh = self._frame_rect
        if fw <= 0 or fh <= 0 or avail.width() <= 0 or avail.height() <= 0:
            return avail
        if self._cover(avail):
            scale = max(avail.width() / fw, avail.height() / fh)
            w = int(fw * scale)
            h = int(fh * scale)
            # Centre the crop on the zone when there is one, else the frame.
            zone = self._active_zone()
            cx, cy = fx + fw / 2, fy + fh / 2
            if zone is not None:
                try:
                    cx, cy = zone.centroid()
                except Exception:
                    pass
            left = avail.left() + avail.width() // 2 - int((cx - fx) * scale)
            top = avail.top() + avail.height() // 2 - int((cy - fy) * scale)
            left = int(c.clamp(left, avail.right() - w + 1, avail.left()))
            top = int(c.clamp(top, avail.bottom() - h + 1, avail.top()))
            return QRect(left, top, w, h)
        scale = min(avail.width() / fw, avail.height() / fh)
        w = int(fw * scale)
        h = int(fh * scale)
        return QRect(avail.left() + (avail.width() - w) // 2,
                     avail.top() + (avail.height() - h) // 2, w, h)

    def _visible_rect(self) -> QRect:
        """The part of the image rect that is actually on screen."""
        return self._image_rect().intersected(self._avail_rect())

    def _to_px(self, x: float, y: float, img: QRect) -> tuple[float, float]:
        fx, fy, fw, fh = self._frame_rect
        sx = img.width() / max(1, fw)
        sy = img.height() / max(1, fh)
        return img.left() + (x - fx) * sx, img.top() + (y - fy) * sy

    def widget_to_dip(self, pos) -> Optional[tuple[int, int]]:
        """Screen DIP under a widget point, or None when the point is
        outside the painted frame."""
        img = self._image_rect()
        if not self._visible_rect().contains(pos) or not self.has_frame():
            return None
        fx, fy, fw, fh = self._frame_rect
        sx = img.width() / max(1, fw)
        sy = img.height() / max(1, fh)
        return (int(round(fx + (pos.x() - img.left()) / sx)),
                int(round(fy + (pos.y() - img.top()) / sy)))

    def contextMenuEvent(self, event):  # noqa: N802 (Qt name)
        from .context_menus import viewport_menu
        dip = self.widget_to_dip(event.pos())
        menu = viewport_menu(self.app, self, dip, parent=self)
        menu.exec(event.globalPos())
        event.accept()

    def _active_zone(self):
        zone, _status, _title = c.lock_view(self.app)
        return zone

    def _zone_monitor_index(self, zone) -> int:
        """1-based Qt screen index holding the zone centroid, falling back
        to the captured monitor."""
        try:
            cx, cy = zone.centroid()
            for i, s in enumerate(QApplication.instance().screens()):
                g = s.geometry()
                if g.left() <= cx < g.left() + g.width() and g.top() <= cy < g.top() + g.height():
                    return i + 1
        except Exception:
            pass
        return self._monitor_index()

    def _next_seconds(self) -> Optional[float]:
        """Seconds to the next action, or None while idle. AI mode reads
        the bot runner's tick clock; Click / Record read the engine."""
        app = self.app
        if app._state_str == ClickerState.IDLE:
            return None
        if app._active_mode == "ai":
            fn = getattr(getattr(app, "bot_runner", None), "seconds_until_next_tick", None)
            if callable(fn):
                try:
                    v = fn()
                    return float(v) if v is not None else None
                except Exception:
                    return None
            return None
        try:
            return float(app.clicker.seconds_until_next())
        except Exception:
            return None

    # -- Tick (called by the shell at 10 Hz) -------------------------------

    def tick(self) -> None:
        w = self._worker
        if w is not None:
            try:
                w.set_target_rect(self._target_rect_dip())
            except RuntimeError:
                self._worker = None
        # A DPR change has no resize event of its own; catch it here.
        if abs(self._dpr() - self._requested_out[2]) > 1e-3:
            self._push_output_size()
        secs = self._next_seconds()
        if secs is not None:
            if secs > self._last_secs + 0.05:
                self._wait_total = secs
            self._last_secs = secs
        else:
            self._last_secs = 0.0
        self.update()

    # -- Input --------------------------------------------------------------------

    def _rail_rect(self) -> QRect:
        return QRect(self.width() - _ZOOM_RAIL_W, _RULER, _ZOOM_RAIL_W, self.height() - _RULER)

    def mousePressEvent(self, event):  # noqa: N802 (Qt name)
        if event.button() == Qt.LeftButton:
            pos = event.position().toPoint()
            rail = self._rail_rect()
            if rail.contains(pos):
                if pos.y() < rail.top() + _RAIL_HIT_H:
                    self.zoom_in()
                elif pos.y() > rail.bottom() - _RAIL_HIT_H:
                    self.zoom_out()
                event.accept()
                return
        super().mousePressEvent(event)

    def mouseDoubleClickEvent(self, event):  # noqa: N802 (Qt name)
        if event.button() == Qt.LeftButton and self._avail_rect().contains(event.position().toPoint()):
            self.toggle_zoom()
            event.accept()
            return
        super().mouseDoubleClickEvent(event)

    def wheelEvent(self, event):  # noqa: N802 (Qt name)
        dy = event.angleDelta().y()
        if dy > 0:
            self.zoom_in()
        elif dy < 0:
            self.zoom_out()
        event.accept()

    # -- Painting ---------------------------------------------------------

    def paintEvent(self, _event):  # noqa: N802 (Qt name)
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.fillRect(self.rect(), QColor(c.SURFACE_PANEL))
        img = self._image_rect()
        avail = self._avail_rect()
        vis = img.intersected(avail)
        self._paint_letterbox(p, img)
        if self._frame is None:
            self._paint_no_capture(p, vis)
        else:
            p.save()
            p.setClipRect(avail)
            p.drawImage(img, self._frame)
            # Slight darkening keeps the overlays legible on a bright game.
            p.fillRect(img, QColor(0, 0, 0, 70))
            p.restore()
        self._paint_rulers(p, img)
        self._paint_zoom_rail(p)
        self._paint_frame(p, vis)
        self._paint_chips(p, vis)
        self._paint_clicks(p, img, vis)
        self._paint_reticle(p, img, vis)
        self._paint_readouts(p, img, vis)
        p.end()

    def _paint_frame(self, p: QPainter, vis: QRect) -> None:
        """Corner brackets on the visible frame: green while the engine
        runs, quiet otherwise. Same marks as the zone map."""
        if vis.width() <= 0:
            return
        running = self.app._state_str != ClickerState.IDLE
        r = QRectF(vis).adjusted(1.5, 1.5, -1.5, -1.5)
        _brackets(p, r, c.RUN if running else c.TEXT_TERTIARY, arm=18.0, width=1.5)

    def _paint_grid(self, p: QPainter, area: QRect, step: int = 32) -> None:
        p.save()
        p.setRenderHint(QPainter.Antialiasing, False)
        p.setPen(_hairline(c.BORDER))
        for x in range(area.left(), area.right(), step):
            p.drawLine(x, area.top(), x, area.bottom())
        for y in range(area.top(), area.bottom(), step):
            p.drawLine(area.left(), y, area.right(), y)
        p.restore()

    def _paint_letterbox(self, p: QPainter, img: QRect) -> None:
        """Bands outside the aspect-fit image: panel colour with the same
        hairline grid the no-capture state uses, so the frame reads as
        sitting on the deck instead of floating in black."""
        avail = self._avail_rect()
        if avail == img or avail.width() <= 0 or img.contains(avail):
            return
        p.save()
        p.setClipRegion(QRegion(avail).subtracted(QRegion(img)))
        self._paint_grid(p, avail)
        p.restore()

    def _paint_no_capture(self, p: QPainter, img: QRect) -> None:
        self._paint_grid(p, img)
        p.setPen(QColor(c.TEXT_TERTIARY))
        p.setFont(c.mono_font(c.SIZE_LG, QFont.DemiBold))
        label = "NO CAPTURE" if (self._no_capture or not self.is_capturing()) else "ACQUIRING"
        p.drawText(img, Qt.AlignCenter, label)

    def _ruler_step(self, px_per_dip: float) -> int:
        """Tick spacing in DIPs: the smallest power-of-two step that keeps
        ticks at least 40 px apart, so zooming in relabels finer."""
        step = 16
        while step * px_per_dip < 40 and step < 4096:
            step *= 2
        return step

    def _paint_rulers(self, p: QPainter, img: QRect) -> None:
        p.fillRect(QRect(0, 0, self.width(), _RULER), QColor(c.SURFACE))
        p.fillRect(QRect(0, 0, _RULER, self.height()), QColor(c.SURFACE))
        # Hairlines and ticks are cosmetic pens drawn without antialiasing
        # so they land on exactly one device pixel row at any DPR.
        p.save()
        p.setRenderHint(QPainter.Antialiasing, False)
        p.setPen(_hairline(c.BORDER))
        p.drawLine(0, _RULER, self.width(), _RULER)
        p.drawLine(_RULER, 0, _RULER, self.height())
        fx, fy, fw, fh = self._frame_rect
        mx, my, _mw, _mh = self._monitor_rect
        if fw <= 0 or fh <= 0 or img.width() <= 0:
            p.restore()
            return
        # 9 pt DemiBold: the smallest weight that survives a 150% scale
        # without the digits smearing into the tick marks.
        p.setFont(c.mono_font(c.SIZE_XS, QFont.DemiBold))
        tick_pen = _hairline(c.BORDER_STRONG)
        text_color = QColor(c.TEXT_MICRO)
        step = self._ruler_step(img.width() / fw)
        major_every = step * 5
        # Labels are monitor-local DIPs (0 at the monitor's top-left), so a
        # zoomed frame starting at x=640 shows 640 at its left edge.
        v0 = int(math.floor((fx - mx) / step)) * step
        v1 = int(fx - mx + fw)
        vis = img.intersected(self._avail_rect())
        for v in range(v0, v1 + 1, step):
            x, _ = self._to_px(mx + v, my, img)
            # Clip to the visible extent so ticks never run into the bands.
            if x < vis.left() or x > vis.right():
                continue
            major = v % major_every == 0
            p.setPen(tick_pen)
            p.drawLine(int(x), _RULER - (8 if major else 4), int(x), _RULER)
            if major:
                p.setPen(text_color)
                p.drawText(int(x) + 3, 12, str(v))
        v0 = int(math.floor((fy - my) / step)) * step
        v1 = int(fy - my + fh)
        for v in range(v0, v1 + 1, step):
            _, y = self._to_px(mx, my + v, img)
            if y < vis.top() or y > vis.bottom():
                continue
            major = v % major_every == 0
            p.setPen(tick_pen)
            p.drawLine(_RULER - (8 if major else 4), int(y), _RULER, int(y))
            if major:
                p.setPen(text_color)
                p.save()
                p.translate(12, int(y) - 3)
                p.rotate(-90)
                p.drawText(0, 0, str(v))
                p.restore()
        p.restore()

    def _paint_zoom_rail(self, p: QPainter) -> None:
        rail = self._rail_rect()
        p.fillRect(rail, QColor(c.SURFACE))
        cx = rail.center().x()
        top, bottom = rail.top() + 28, rail.bottom() - 28
        p.save()
        p.setRenderHint(QPainter.Antialiasing, False)
        p.setPen(_hairline(c.BORDER))
        p.drawLine(rail.left(), rail.top(), rail.left(), rail.bottom())
        p.setPen(_hairline(c.BORDER_STRONG))
        p.drawLine(cx, top, cx, bottom)
        p.restore()
        at_max = self._zoom_idx == len(_ZOOM_LEVELS) - 1
        at_min = self._zoom_idx == 0
        p.setFont(c.mono_font(c.SIZE_XS))
        p.setPen(QColor(c.TEXT_DISABLED if at_max else c.TEXT_SECONDARY))
        p.drawText(QRect(rail.left(), rail.top() + 6, rail.width(), 14), Qt.AlignCenter, "+")
        p.setPen(QColor(c.TEXT_DISABLED if at_min else c.TEXT_SECONDARY))
        p.drawText(QRect(rail.left(), rail.bottom() - 20, rail.width(), 14), Qt.AlignCenter, "-")
        # Level stops along the track, current one filled in ice.
        n = len(_ZOOM_LEVELS)
        span = max(1, bottom - top)
        for i in range(n):
            # Highest zoom sits at the top, next to "+".
            y = bottom - int(span * i / (n - 1))
            if i == self._zoom_idx:
                p.fillRect(QRect(cx - 5, y - 1, 10, 3), QColor(c.ACCENT))
            else:
                p.fillRect(QRect(cx - 2, y, 4, 1), QColor(c.BORDER_STRONG))
        p.setPen(QColor(c.ACCENT if self._zoom_idx else c.TEXT_MICRO))
        p.save()
        p.translate(rail.left() + 7, (top + bottom) // 2 + 14)
        p.rotate(-90)
        p.drawText(0, 0, f"{self.zoom():0.1f}X")
        p.restore()

    def _chip(self, p: QPainter, x: int, y: int, text: str, color: str,
              dot: Optional[str] = None, align_right: bool = False) -> QRect:
        p.setFont(c.mono_font(c.SIZE_XS, QFont.DemiBold))
        fm = p.fontMetrics()
        w = fm.horizontalAdvance(text) + 14 + (12 if dot else 0)
        h = 18
        if align_right:
            x -= w
        r = QRect(x, y, w, h)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(c.SURFACE))
        p.drawRoundedRect(r, 4, 4)
        p.setPen(_hairline(c.BORDER))
        p.setBrush(Qt.NoBrush)
        p.drawRoundedRect(r, 4, 4)
        tx = x + 7
        if dot:
            p.fillRect(QRect(tx, y + 6, 6, 6), QColor(dot))
            tx += 12
        p.setPen(QColor(color))
        p.drawText(QRect(tx, y, w, h), Qt.AlignVCenter | Qt.AlignLeft, text)
        return r

    def _track_chip(self) -> Optional[tuple[str, str]]:
        """``(text, color)`` for the TRK confidence chip, or None when no
        Track step is in play. Green at or above the step's threshold,
        amber below, red when the engine runs a Track step and the
        tracker reports nothing."""
        app = self.app
        step = c.current_track_step(app)
        if step is None:
            return None
        fn = getattr(app.clicker, "tracker_confidence", None)
        conf = None
        if callable(fn):
            try:
                conf = fn()
            except Exception:
                conf = None
        if conf is None:
            if app._state_str != ClickerState.IDLE:
                return "TRK ··", c.STOP
            return None
        conf = float(conf)
        thr = float(getattr(step, "tracker_threshold", 0.65) or 0.65)
        return f"TRK {conf:0.2f}", (c.RUN if conf >= thr else c.WARN)

    def _paint_chips(self, p: QPainter, img: QRect) -> None:
        live = self._frame is not None
        dot = c.RUN if live else c.STATUS_IDLE
        r = self._chip(p, img.left() + 12, img.top() + 12,
                       f"{'LIVE' if live else 'OFFLINE'} · MON{self._monitor_index()}",
                       c.TEXT_PRIMARY, dot=dot)
        trk = self._track_chip()
        if trk is not None:
            self._chip(p, img.left() + 12, r.bottom() + 4, trk[0], trk[1])
        right = img.right() - 12
        r = self._chip(p, right, img.top() + 12, c.format_clock(), c.TEXT_PRIMARY, align_right=True)
        self._chip(p, right, r.bottom() + 4, c.format_dtg(), c.TEXT_TERTIARY, align_right=True)

    def _paint_clicks(self, p: QPainter, img: QRect, vis: QRect) -> None:
        pts = self.app.click_ring.last(10)
        if not pts:
            return
        now = time.monotonic()
        p.setPen(Qt.NoPen)
        for i, (t0, x, y) in enumerate(pts):
            px, py = self._to_px(x, y, img)
            if not vis.contains(int(px), int(py)):
                continue
            # Newest dot is solid; older ones fade both by rank and by age.
            rank = (i + 1) / len(pts)
            age = max(0.0, 1.0 - (now - t0) / 30.0)
            alpha = int(255 * max(0.15, rank * 0.7 + age * 0.3))
            col = QColor(c.TEXT_PRIMARY)
            col.setAlpha(alpha)
            p.setBrush(col)
            p.drawEllipse(QRectF(px - 1.5, py - 1.5, 3, 3))

    def _paint_reticle(self, p: QPainter, img: QRect, vis: QRect) -> None:
        zone, status, title = c.lock_view(self.app)
        if zone is None:
            return
        # Amber while the locked window is away: the reticle then marks
        # where the window was last seen, not where a click would land.
        holding = status in HOLD_STATUSES
        color = c.WARN if holding else c.ACCENT
        x1, y1, x2, y2 = zone.aabb()
        ax, ay = self._to_px(x1, y1, img)
        bx, by = self._to_px(x2, y2, img)
        r = QRectF(ax, ay, max(2.0, bx - ax), max(2.0, by - ay))
        p.save()
        # A zoomed or cropped frame can put part of the zone off screen.
        p.setClipRect(vis)
        pen = QPen(QColor(color))
        pen.setWidthF(1.5)
        p.setPen(pen)
        p.setBrush(Qt.NoBrush)
        arm = min(14.0, r.width() / 2, r.height() / 2)
        for (cx, cy, dx, dy) in (
            (r.left(), r.top(), 1, 1), (r.right(), r.top(), -1, 1),
            (r.left(), r.bottom(), 1, -1), (r.right(), r.bottom(), -1, -1),
        ):
            p.drawLine(QRectF(cx, cy, 0, 0).topLeft(), QRectF(cx + dx * arm, cy, 0, 0).topLeft())
            p.drawLine(QRectF(cx, cy, 0, 0).topLeft(), QRectF(cx, cy + dy * arm, 0, 0).topLeft())
        pm = c.icon_pixmap("mg85", 26, color)
        p.drawPixmap(int(r.center().x() - 13), int(r.center().y() - 13), pm)
        p.setFont(c.label_font(c.SIZE_XS, QFont.DemiBold, 0.8))
        p.setPen(QColor(c.WARN if holding else c.TEXT_SECONDARY))
        anchor = c.elide(title, 24).upper() if (status != STATUS_SCREEN and title) else "SCREEN"
        label = f"TARGET  ZONE-01 · MON{self._zone_monitor_index(zone)} · {anchor}"
        ty = int(r.bottom() + 16)
        if ty > vis.bottom() - 4:
            ty = int(r.top() - 6)
        p.drawText(int(r.left()), ty, label)
        p.restore()

    def _paint_readouts(self, p: QPainter, img: QRect, vis: QRect) -> None:
        app = self.app
        snap = app.stats.snapshot()
        cpm = snap.get("cpm", 0.0) or 0.0
        secs = self._next_seconds()
        img = vis
        x = img.left() + 10
        y = img.top() + img.height() // 2 - 26
        # Backing plate so the readouts stay legible over a busy frame.
        plate = QRect(x - 6, y - 14, 118, 88)
        p.setPen(Qt.NoPen)
        plate_col = QColor(c.SURFACE_PANEL)
        plate_col.setAlpha(215)
        p.setBrush(plate_col)
        p.drawRoundedRect(plate, 4, 4)
        p.setFont(c.label_font(c.SIZE_XS, QFont.DemiBold, 1.0))
        p.setPen(QColor(c.TEXT_MICRO))
        p.drawText(x, y, "CPM")
        p.setPen(QColor(c.TEXT_PRIMARY))
        p.setFont(c.mono_font(c.SIZE_XL, QFont.DemiBold))
        p.drawText(x, y + 22, f"{cpm:0.1f}")
        y2 = y + 46
        p.setFont(c.label_font(c.SIZE_XS, QFont.DemiBold, 1.0))
        p.setPen(QColor(c.TEXT_MICRO))
        p.drawText(x, y2, "NEXT TICK" if app._active_mode == "ai" else "NEXT")
        p.setPen(QColor(c.RUN if secs is not None else c.TEXT_TERTIARY))
        p.setFont(c.mono_font(c.SIZE_XL, QFont.DemiBold))
        next_text = f"{secs:0.1f}S" if secs is not None else "··"
        p.drawText(x, y2 + 22, next_text)
        # Dial hand sweeps once per wait: 0 deg at the start of the wait,
        # 360 as the click fires.
        frac = 0.0
        if secs is not None and self._wait_total > 0:
            frac = c.clamp(1.0 - secs / self._wait_total, 0.0, 1.0)
        dial_x = x + p.fontMetrics().horizontalAdvance(next_text) + 10
        pm = c.icon_pixmap("mg63", 22, c.RUN if secs is not None else c.TEXT_TERTIARY,
                           degrees=frac * 360.0)
        p.drawPixmap(dial_x, y2 + 4, pm)

        last = snap.get("last_pos")
        if last:
            last_text = f"LAST CLICK  X {int(last[0]):04d} · Y {int(last[1]):04d} PX"
        else:
            last_text = "LAST CLICK  ··"
        self._chip(p, img.left() + 12, img.bottom() - 30, last_text, c.TEXT_SECONDARY)
        mode = {"clicker": "CLICK", "recorder": "RECORD", "ai": "AI"}.get(app._active_mode, "CLICK")
        self._chip(p, img.right() - 12, img.bottom() - 30, f"MODE  {mode}", c.TEXT_SECONDARY,
                   align_right=True)
