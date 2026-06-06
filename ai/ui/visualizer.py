"""Live visualizer panel.

Shows the most recent :func:`vision.capture` frame plus overlays for
detections coming out of blocks: points, clusters (as bboxes), ROIs,
and stub markers. Refreshes per-tick — overlays from last tick clear
when a new tick starts.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
from PySide6.QtCore import QPoint, Qt, Signal
from PySide6.QtGui import QBrush, QColor, QImage, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)


# ─────────────────────────────────────────────────────────────────
# Overlay model
# ─────────────────────────────────────────────────────────────────


@dataclass
class Overlay:
    kind: str                    # "point" | "bbox" | "cluster" | "roi" | "line"
    data: Any                    # shape depends on kind
    color: Tuple[int, int, int] = (255, 80, 80)
    label: str = ""
    width: int = 2


@dataclass
class _State:
    frame: Optional[np.ndarray] = None
    overlays: List[Overlay] = field(default_factory=list)


# ─────────────────────────────────────────────────────────────────
# Widget
# ─────────────────────────────────────────────────────────────────


class Visualizer(QWidget):
    """Paints the last captured frame with live overlays.

    Also hosts the region picker: click-drag on the frame to select a
    rectangle, click "Use as default ROI" to commit it as a Studio-wide
    ROI applied to every block that reads `roi` and gets a blank string.
    """

    # Emitted when the user commits or clears the default ROI.
    # Payload: (x, y, w, h) in **source-pixel** coords, or None on clear.
    default_roi_changed = Signal(object)

    # Emitted when the user clicks a pixel (didn't drag). Payload: dict
    # {x, y, bgr, rgb_hex}. Studio listens → clipboard + block integration.
    pixel_picked = Signal(object)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setMinimumSize(360, 240)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self._state = _State()
        self._first_frame_logged = False

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        # Row 1 — view tools (zoom + snapshot). Pan is via middle-mouse drag.
        view_bar = QHBoxLayout()
        view_bar.setContentsMargins(6, 4, 6, 0)
        view_bar.setSpacing(4)

        def _icon_btn(text: str, tip: str, slot) -> QPushButton:
            b = QPushButton(text)
            b.setToolTip(tip)
            b.setFixedWidth(40)
            b.clicked.connect(slot)
            return b

        self._zoom_out_btn = _icon_btn("−", "Zoom out (Ctrl+−)", lambda: self._canvas.zoom_step(1 / 1.15))
        self._zoom_100_btn = _icon_btn("1:1", "Reset zoom to 100% (Ctrl+0)", lambda: self._canvas.zoom_set(1.0))
        self._zoom_in_btn = _icon_btn("+", "Zoom in (Ctrl+=)", lambda: self._canvas.zoom_step(1.15))
        self._zoom_fit_btn = QPushButton("⤢ Fit")
        self._zoom_fit_btn.setToolTip("Fit image to window (resets zoom + pan)")
        self._zoom_fit_btn.clicked.connect(lambda: self._canvas.zoom_fit())
        view_bar.addWidget(self._zoom_out_btn)
        view_bar.addWidget(self._zoom_100_btn)
        view_bar.addWidget(self._zoom_in_btn)
        view_bar.addWidget(self._zoom_fit_btn)

        self._zoom_label = QLabel("100%")
        self._zoom_label.setStyleSheet("color:#888; padding: 0 6px;")
        self._zoom_label.setFixedWidth(56)
        view_bar.addWidget(self._zoom_label)

        view_bar.addStretch(1)

        self._save_snap_btn = QPushButton("📸 Snapshot")
        self._save_snap_btn.setToolTip(
            "Save the current frame as a PNG to F:\\RS3_AI\\debug\\screenshots\\.\n"
            "Path is logged so you can copy/paste it for sharing."
        )
        self._save_snap_btn.clicked.connect(self._save_snapshot)
        view_bar.addWidget(self._save_snap_btn)
        layout.addLayout(view_bar)

        # Row 2 — region tools (selection-driven). Hint text on the left,
        # action buttons on the right; the action buttons disable when
        # there's nothing selected.
        roi_bar = QHBoxLayout()
        roi_bar.setContentsMargins(6, 2, 6, 0)
        roi_bar.setSpacing(4)
        self._roi_label = QLabel(
            "Click = pipette · drag = select ROI · middle-drag = pan · wheel = zoom"
        )
        self._roi_label.setStyleSheet("color:#aaa;")
        roi_bar.addWidget(self._roi_label, 1)

        self._use_roi_btn = QPushButton("📐 Use as ROI")
        self._use_roi_btn.setToolTip("Commit selection as the Studio-wide default ROI.")
        self._use_roi_btn.setEnabled(False)
        self._use_roi_btn.clicked.connect(self._commit_selection)
        roi_bar.addWidget(self._use_roi_btn)
        self._save_bmp_btn = QPushButton("💾 Save Bitmap")
        self._save_bmp_btn.setEnabled(False)
        self._save_bmp_btn.setToolTip(
            "Save the selected region as a PNG in templates/bitmap/ "
            "for use by the Find Bitmap block."
        )
        self._save_bmp_btn.clicked.connect(self._save_roi_as_bitmap)
        roi_bar.addWidget(self._save_bmp_btn)
        self._make_dtm_btn = QPushButton("🎯 Create DTM")
        self._make_dtm_btn.setEnabled(False)
        self._make_dtm_btn.setToolTip(
            "Build a DTM template from the selected region — samples "
            "several pixels and writes a YAML template to templates/dtm/."
        )
        self._make_dtm_btn.clicked.connect(self._create_dtm_from_roi)
        roi_bar.addWidget(self._make_dtm_btn)
        self._clear_roi_btn = QPushButton("✕ Clear")
        self._clear_roi_btn.setToolTip("Clear the committed default ROI.")
        self._clear_roi_btn.setEnabled(False)
        self._clear_roi_btn.clicked.connect(self._clear_committed_roi)
        roi_bar.addWidget(self._clear_roi_btn)
        layout.addLayout(roi_bar)

        self._canvas = _FrameCanvas(self._state)
        self._canvas.zoom_changed.connect(self._on_zoom_changed)
        self._canvas.selection_changed.connect(self._on_canvas_selection)
        self._canvas.pixel_picked.connect(self.pixel_picked)  # forward up
        layout.addWidget(self._canvas)

        # Stats strip below the canvas.
        self._info = QLabel("No frame yet. Start a script with a vision.capture block.")
        self._info.setStyleSheet("color:#888; padding: 4px;")
        layout.addWidget(self._info)

    # ── signal handlers (wired from the Studio's RuntimeController) ──
    def on_tick_started(self, tick_num: int) -> None:
        """Clear per-tick overlays at the start of each execution tick."""
        self._state.overlays = []
        self._canvas.update()

    def on_frame_captured(self, frame: np.ndarray) -> None:
        if frame is None:
            return
        if not self._first_frame_logged:
            # Print once to stderr so console users see the signal path is alive.
            # The Studio's log panel also shows the runtime's capture log.
            print(f"[visualizer] first frame received: shape={frame.shape}")
            self._first_frame_logged = True
        self._state.frame = np.ascontiguousarray(frame)
        h, w = frame.shape[:2]
        self._info.setText(
            f"Frame {w}×{h} · {len(self._state.overlays)} overlay(s) this tick"
        )
        self._canvas.update()

    def on_block_executed(self, info: Dict[str, Any]) -> None:
        identifier = info.get("identifier", "")
        outputs = info.get("outputs", {}) or {}
        added = False

        if identifier in ("color.find", "tpa.centroid") and outputs.get("point"):
            self._state.overlays.append(
                Overlay(kind="point", data=outputs["point"], color=(255, 80, 80),
                        label=identifier.split(".")[-1])
            )
            added = True

        if identifier in ("color.find_all", "tpa.cluster"):
            clusters = outputs.get("clusters") or []
            for i, cluster in enumerate(clusters):
                if not cluster:
                    continue
                bbox = _cluster_bbox(cluster)
                self._state.overlays.append(
                    Overlay(
                        kind="bbox",
                        data=bbox,
                        color=(255, 180, 60) if i == 0 else (200, 140, 80),
                        label=f"{identifier.split('.')[-1]}[{i}]" if i < 3 else "",
                    )
                )
            added = True

        if identifier == "flow.pick_largest" and outputs.get("cluster"):
            bbox = _cluster_bbox(outputs["cluster"])
            self._state.overlays.append(
                Overlay(kind="bbox", data=bbox, color=(80, 255, 80), label="largest")
            )
            added = True

        if identifier == "tpa.bounds" and outputs.get("bbox"):
            self._state.overlays.append(
                Overlay(kind="bbox", data=outputs["bbox"], color=(80, 180, 255),
                        label="bounds")
            )
            added = True

        if identifier == "feature.diff":
            for rect in outputs.get("changed", []) or []:
                self._state.overlays.append(
                    Overlay(kind="bbox", data=rect, color=(220, 100, 220))
                )
            added = True

        if identifier == "input.click" and info.get("inputs", {}).get("point"):
            pt = info["inputs"]["point"]
            self._state.overlays.append(
                Overlay(kind="point", data=pt, color=(255, 255, 80), label="click", width=3)
            )
            added = True

        if added:
            if self._state.frame is not None:
                h, w = self._state.frame.shape[:2]
                self._info.setText(
                    f"Frame {w}×{h} · {len(self._state.overlays)} overlay(s) this tick"
                )
            self._canvas.update()

    # ── region picker ───────────────────────────────────
    def _on_canvas_selection(self, rect) -> None:
        """Called whenever the user finishes a rubber-band drag."""
        if rect is None or rect[2] < 3 or rect[3] < 3:
            self._roi_label.setText(
                "Click = pipette · drag = select ROI · middle-drag = pan · wheel = zoom"
            )
            self._use_roi_btn.setEnabled(False)
            self._save_bmp_btn.setEnabled(False)
            self._make_dtm_btn.setEnabled(False)
            return
        x, y, w, h = rect
        self._roi_label.setText(
            f"Selection: {x},{y}  {w}×{h}  — "
            "Use as ROI / save bitmap / build DTM"
        )
        self._use_roi_btn.setEnabled(True)
        self._save_bmp_btn.setEnabled(True)
        self._make_dtm_btn.setEnabled(True)

    def _current_selection_rect(self):
        """Return (x, y, w, h) of the current selection, or None."""
        return self._canvas.pending_selection()

    def _save_snapshot(self) -> None:
        """Write the current full frame to F:\\RS3_AI\\debug\\screenshots\\."""
        if self._state.frame is None:
            from PySide6.QtWidgets import QMessageBox
            QMessageBox.information(
                self, "No frame yet",
                "There's no captured frame to save. Run a script with a "
                "Capture Screen block, or pick a monitor in the toolbar to "
                "let the live preview kick in.",
            )
            return
        try:
            from .. import debug as _debug
            path = _debug.save_screenshot(self._state.frame, context="manual")
            if path is None:
                from PySide6.QtWidgets import QMessageBox
                QMessageBox.warning(
                    self, "Save failed",
                    "Snapshot didn't write — check the log for details.",
                )
        except Exception as e:
            from PySide6.QtWidgets import QMessageBox
            QMessageBox.critical(
                self, "Save failed", f"{type(e).__name__}: {e}",
            )

    def _save_roi_as_bitmap(self) -> None:
        """Crop the selected ROI from the current frame and save as PNG."""
        rect = self._current_selection_rect()
        if rect is None or self._state.frame is None:
            return
        from PySide6.QtWidgets import QMessageBox
        from pathlib import Path
        from ..algorithms.bitmap import save_png

        x, y, w, h = rect
        default_dir = (
            Path(__file__).resolve().parent.parent.parent / "templates" / "bitmap"
        )
        path = _prompt_template_name(
            self,
            title="Save ROI as bitmap",
            label="Template name (saved to templates/bitmap/):",
            directory=default_dir,
            extensions=(".png",),
            default_name="new_bitmap",
        )
        if path is None:
            return
        try:
            crop = self._state.frame[y : y + h, x : x + w]
            save_png(crop, str(path))
            QMessageBox.information(
                self, "Saved",
                f"Wrote {w}×{h} PNG to:\n{path}\n\nUse it in a Find Bitmap "
                f"block by setting bitmap_path = {path.name!r}."
            )
        except Exception as e:
            QMessageBox.critical(self, "Save failed", f"{type(e).__name__}: {e}")

    def _create_dtm_from_roi(self) -> None:
        """Build a rough DTM template from the selected ROI."""
        rect = self._current_selection_rect()
        if rect is None or self._state.frame is None:
            return
        from PySide6.QtWidgets import QMessageBox
        from pathlib import Path
        from ..algorithms.dtm import build_from_roi, save

        default_dir = (
            Path(__file__).resolve().parent.parent.parent / "templates" / "dtm"
        )
        path = _prompt_template_name(
            self,
            title="Create DTM template",
            label="Template name (saved to templates/dtm/):",
            directory=default_dir,
            extensions=(".yaml", ".yml"),
            default_name="new_template",
        )
        if path is None:
            return
        try:
            tpl = build_from_roi(self._state.frame, rect, name=path.stem, points=5)
        except Exception as e:
            QMessageBox.critical(self, "Build failed", f"{type(e).__name__}: {e}")
            return
        try:
            save(tpl, str(path))
        except Exception as e:
            QMessageBox.critical(self, "Save failed", f"{type(e).__name__}: {e}")
            return
        QMessageBox.information(
            self, "Saved",
            f"Wrote DTM template '{path.stem}' to:\n{path}\n\n"
            f"Use it in a Find DTM block by setting "
            f"template_path = {path.name!r}.\n\n"
            f"Tip: open the YAML file in any editor to tune tolerances "
            f"and remove any noisy points."
        )

    def _commit_selection(self) -> None:
        rect = self._canvas.pending_selection()
        if rect is None:
            return
        self._canvas.set_committed_roi(rect)
        self._use_roi_btn.setEnabled(False)
        self._clear_roi_btn.setEnabled(True)
        x, y, w, h = rect
        self._roi_label.setText(f"Default ROI: {x},{y}  {w}×{h}")
        self.default_roi_changed.emit(rect)

    def _clear_committed_roi(self) -> None:
        self._canvas.set_committed_roi(None)
        self._clear_roi_btn.setEnabled(False)
        self._roi_label.setText(
            "Click = pipette · drag = select ROI · middle-drag = pan · wheel = zoom"
        )
        self.default_roi_changed.emit(None)

    def _on_zoom_changed(self, zoom: float) -> None:
        self._zoom_label.setText(f"{int(round(zoom * 100))}%")


def _cluster_bbox(cluster) -> Tuple[int, int, int, int]:
    xs = [p[0] for p in cluster]
    ys = [p[1] for p in cluster]
    x0, x1 = min(xs), max(xs)
    y0, y1 = min(ys), max(ys)
    return (x0, y0, x1 - x0 + 1, y1 - y0 + 1)


def _prompt_template_name(
    parent,
    *,
    title: str,
    label: str,
    directory,
    extensions,
    default_name: str,
):
    """Single-dialog template name prompt with overwrite confirmation.

    - Lists existing templates of the matching extension(s) in an editable
      combobox so the user can pick one to overwrite or type a new name.
    - Auto-appends the first extension if the user didn't include one.
    - Prompts to confirm overwrite if the resulting file already exists.
    - Returns a `pathlib.Path` to the chosen target, or None on cancel.
    """
    from pathlib import Path
    from PySide6.QtWidgets import (
        QComboBox,
        QDialog,
        QDialogButtonBox,
        QLabel,
        QMessageBox,
        QVBoxLayout,
    )

    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    exts = tuple(e.lower() for e in extensions)

    existing = sorted(
        [p.name for p in directory.iterdir() if p.is_file() and p.suffix.lower() in exts]
    )

    dialog = QDialog(parent)
    dialog.setWindowTitle(title)
    dialog.setMinimumWidth(420)
    layout = QVBoxLayout(dialog)
    layout.addWidget(QLabel(label))

    combo = QComboBox()
    combo.setEditable(True)
    combo.addItem("")  # blank slot so the default text shows first
    for name in existing:
        combo.addItem(name)
    combo.setCurrentText(default_name + exts[0])
    layout.addWidget(combo)

    hint = QLabel(
        f"Existing in folder: {len(existing)}. Pick one to overwrite, "
        f"or type a new name."
    )
    hint.setStyleSheet("color:#888;")
    layout.addWidget(hint)

    btns = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
    btns.accepted.connect(dialog.accept)
    btns.rejected.connect(dialog.reject)
    layout.addWidget(btns)

    if dialog.exec() != QDialog.DialogCode.Accepted:
        return None

    raw = combo.currentText().strip()
    if not raw:
        return None
    # Strip any path components — we always save into `directory`.
    name = Path(raw).name
    if not any(name.lower().endswith(e) for e in exts):
        name += exts[0]
    target = directory / name

    if target.exists():
        resp = QMessageBox.question(
            parent,
            "Overwrite?",
            f"'{name}' already exists in:\n{directory}\n\nOverwrite it?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if resp != QMessageBox.StandardButton.Yes:
            return None
    return target


# ─────────────────────────────────────────────────────────────────
# Canvas that actually paints the frame + overlays
# ─────────────────────────────────────────────────────────────────


class _FrameCanvas(QWidget):
    """Private helper — fit-to-widget pixmap paint + overlay draw.

    Coordinates in `Overlay` are in SOURCE pixels; we compute a
    letterboxed transform each paint so they land correctly even when
    the widget is resized.
    """

    # Emitted when the rubber-band drag finishes. Payload: source-coord
    # (x, y, w, h) or None if released without a valid selection.
    selection_changed = Signal(object)

    # Emitted when the user clicks (doesn't drag) on a pixel. Payload: dict
    # with keys 'x', 'y', 'bgr' (tuple), 'rgb_hex' (int).
    pixel_picked = Signal(object)

    # Emitted when the zoom factor changes. Payload: float (1.0 = 100%).
    zoom_changed = Signal(float)

    _MIN_ZOOM = 0.2
    _MAX_ZOOM = 16.0

    def __init__(self, state: _State, parent=None) -> None:
        super().__init__(parent)
        self._state = state
        self._zoom: float = 1.0  # 1.0 = fit-to-window; scrollwheel changes it.
        self._pan_offset = [0, 0]  # extra display-pixel offset on top of fit-centering
        self.setMinimumHeight(200)
        self.setAutoFillBackground(True)
        self.setStyleSheet("background: #101014;")
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setCursor(Qt.CursorShape.CrossCursor)

        # Rubber-band selection state.
        self._drag_start_source = None  # (x, y) source pixel
        self._drag_end_source = None
        self._pending_selection = None  # (x, y, w, h) source pixel — last drag result
        self._committed_roi = None      # (x, y, w, h) source pixel — persistent

        # Middle-mouse pan state.
        self._pan_drag_origin = None  # display pt where middle-drag began
        self._pan_offset_origin = None  # _pan_offset snapshot at drag start

    # ── public zoom/pan API (toolbar buttons call these) ────
    def zoom_set(self, zoom: float) -> None:
        new = max(self._MIN_ZOOM, min(self._MAX_ZOOM, zoom))
        if new == self._zoom:
            return
        self._zoom = new
        self.zoom_changed.emit(self._zoom)
        self.update()

    def zoom_step(self, factor: float) -> None:
        self._zoom_around(self.rect().center(), factor)

    def zoom_fit(self) -> None:
        self._pan_offset = [0, 0]
        self.zoom_set(1.0)

    # ── interaction ─────────────────────────────────────
    def wheelEvent(self, event):  # noqa: N802 — Qt API
        delta = event.angleDelta().y()
        if delta == 0:
            return
        factor = 1.15 if delta > 0 else (1.0 / 1.15)
        self._zoom_around(event.position().toPoint(), factor)

    def _zoom_around(self, anchor_pt, factor: float) -> None:
        """Zoom by `factor`, keeping the source pixel under `anchor_pt` fixed."""
        if self._state.frame is None:
            self.zoom_set(self._zoom * factor)
            return
        before = self._display_to_source(anchor_pt)
        new_zoom = max(self._MIN_ZOOM, min(self._MAX_ZOOM, self._zoom * factor))
        if new_zoom == self._zoom:
            return
        self._zoom = new_zoom
        # Adjust pan offset so `before` lands back under `anchor_pt`.
        if before is not None:
            after_disp = self._source_to_display_no_offset(before)
            self._pan_offset[0] += anchor_pt.x() - after_disp[0]
            self._pan_offset[1] += anchor_pt.y() - after_disp[1]
        self.zoom_changed.emit(self._zoom)
        self.update()

    def keyPressEvent(self, event):  # noqa: N802 — Qt API
        if (
            event.key() == Qt.Key.Key_0
            and event.modifiers() & Qt.KeyboardModifier.ControlModifier
        ):
            self.zoom_fit()
            return
        if event.key() == Qt.Key.Key_Escape:
            # Esc clears an in-progress rubber-band + any pending selection.
            self._drag_start_source = None
            self._drag_end_source = None
            self._pending_selection = None
            self.selection_changed.emit(None)
            self.update()
            return
        super().keyPressEvent(event)

    def mousePressEvent(self, event):  # noqa: N802 — Qt API
        if event.button() == Qt.MouseButton.MiddleButton and self._state.frame is not None:
            self._pan_drag_origin = event.position().toPoint()
            self._pan_offset_origin = list(self._pan_offset)
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
            return
        if event.button() == Qt.MouseButton.LeftButton and self._state.frame is not None:
            src = self._display_to_source(event.position().toPoint())
            if src is not None:
                self._drag_start_source = src
                self._drag_end_source = src
                self._pending_selection = None
                self.update()

    def mouseMoveEvent(self, event):  # noqa: N802 — Qt API
        if self._pan_drag_origin is not None:
            now = event.position().toPoint()
            self._pan_offset[0] = self._pan_offset_origin[0] + (now.x() - self._pan_drag_origin.x())
            self._pan_offset[1] = self._pan_offset_origin[1] + (now.y() - self._pan_drag_origin.y())
            self.update()
            return
        if self._drag_start_source is not None and self._state.frame is not None:
            src = self._display_to_source(event.position().toPoint())
            if src is not None:
                self._drag_end_source = src
                self.update()

    def mouseReleaseEvent(self, event):  # noqa: N802 — Qt API
        if event.button() == Qt.MouseButton.MiddleButton and self._pan_drag_origin is not None:
            self._pan_drag_origin = None
            self._pan_offset_origin = None
            self.setCursor(Qt.CursorShape.CrossCursor)
            return
        if event.button() == Qt.MouseButton.LeftButton and self._drag_start_source is not None:
            start = self._drag_start_source
            end = self._drag_end_source or start
            self._drag_start_source = None
            self._drag_end_source = None
            # Small movement → treat as a pixel pick (colour pipette).
            # Larger movement → rubber-band selection.
            if abs(end[0] - start[0]) < 4 and abs(end[1] - start[1]) < 4:
                self._emit_pixel_pick(start)
                self.update()
                return
            rect = _rect_from_corners(start, end)
            if rect is not None and rect[2] >= 3 and rect[3] >= 3:
                self._pending_selection = rect
                self.selection_changed.emit(rect)
            else:
                self._pending_selection = None
                self.selection_changed.emit(None)
            self.update()

    def _emit_pixel_pick(self, src) -> None:
        """Sample the pixel at `src` (source coords) and emit pixel_picked."""
        if self._state.frame is None:
            return
        x, y = src
        if not (0 <= y < self._state.frame.shape[0] and 0 <= x < self._state.frame.shape[1]):
            return
        b, g, r = (int(v) for v in self._state.frame[y, x])
        self.pixel_picked.emit(
            {
                "x": x,
                "y": y,
                "bgr": (b, g, r),
                "rgb_hex": (r << 16) | (g << 8) | b,
            }
        )

    # ── public API for the Visualizer host ──────────────
    def pending_selection(self):
        return self._pending_selection

    def set_committed_roi(self, rect) -> None:
        self._committed_roi = rect
        if rect is not None:
            self._pending_selection = None  # subsumed
        self.update()

    # ── coord transforms ────────────────────────────────
    def _layout_metrics(self):
        """Compute (scale, dx, dy) for current widget+frame+zoom+pan."""
        frame = self._state.frame
        w, h = self.width(), self.height()
        fit = min(w / frame.shape[1], h / frame.shape[0])
        scale = max(0.02, fit * self._zoom)
        target_w = max(1, int(frame.shape[1] * scale))
        target_h = max(1, int(frame.shape[0] * scale))
        dx = (w - target_w) // 2 + self._pan_offset[0]
        dy = (h - target_h) // 2 + self._pan_offset[1]
        return scale, dx, dy

    def _display_to_source(self, display_pt: QPoint):
        if self._state.frame is None:
            return None
        frame = self._state.frame
        scale, dx, dy = self._layout_metrics()
        sx = (display_pt.x() - dx) / scale
        sy = (display_pt.y() - dy) / scale
        sx = max(0, min(frame.shape[1] - 1, int(sx)))
        sy = max(0, min(frame.shape[0] - 1, int(sy)))
        return (sx, sy)

    def _source_to_display_no_offset(self, src):
        """Map a source pixel back to display coords using current scale+centering.

        Includes the pan offset — the name is historical from when offset was
        not part of the layout. Used by the cursor-anchored zoom math.
        """
        scale, dx, dy = self._layout_metrics()
        return (int(dx + src[0] * scale), int(dy + src[1] * scale))

    def _source_rect_to_display(self, rect, dx: int, dy: int, scale: float):
        x, y, w, h = rect
        return (
            int(dx + x * scale),
            int(dy + y * scale),
            max(1, int(w * scale)),
            max(1, int(h * scale)),
        )

    def paintEvent(self, _event) -> None:  # noqa: N802 — Qt API
        painter = QPainter(self)
        try:
            painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)
            frame = self._state.frame
            if frame is None:
                painter.setPen(QColor("#888"))
                painter.drawText(
                    self.rect().adjusted(16, 16, -16, -16),
                    int(Qt.AlignmentFlag.AlignCenter | Qt.TextFlag.TextWordWrap),
                    (
                        "No frame yet.\n\n"
                        "To see something here:\n"
                        "  1.  Add an On Start block (Flow category).\n"
                        "  2.  Add a Capture Screen block (Vision).\n"
                        "  3.  Drag from On Start's 'trigger' output "
                        "to Capture Screen's 'trigger' input.\n"
                        "  4.  Press F5 to run.\n\n"
                        "Or try  Run → Send test frame to visualizer  "
                        "to confirm the paint path works."
                    ),
                )
                return

            pix = _bgr_to_pixmap(frame)
            scale, dx, dy = self._layout_metrics()
            target_w = max(1, int(frame.shape[1] * scale))
            target_h = max(1, int(frame.shape[0] * scale))
            scaled = pix.scaled(
                target_w, target_h,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
            painter.drawPixmap(dx, dy, scaled)

            # Source → display transform.
            sx = scaled.width() / frame.shape[1]
            sy = scaled.height() / frame.shape[0]

            for ov in self._state.overlays:
                self._draw_overlay(painter, ov, dx, dy, sx, sy)

            # Rubber-band preview while dragging.
            if self._drag_start_source is not None and self._drag_end_source is not None:
                rb = _rect_from_corners(
                    self._drag_start_source, self._drag_end_source
                )
                if rb is not None:
                    rx, ry, rw, rh = self._source_rect_to_display(rb, dx, dy, sx)
                    pen = QPen(QColor(255, 230, 80))
                    pen.setWidth(2)
                    pen.setStyle(Qt.PenStyle.DashLine)
                    painter.setPen(pen)
                    painter.setBrush(QBrush(QColor(255, 230, 80, 40)))
                    painter.drawRect(rx, ry, rw, rh)

            # Persistent committed ROI (cyan solid).
            if self._committed_roi is not None:
                rx, ry, rw, rh = self._source_rect_to_display(
                    self._committed_roi, dx, dy, sx
                )
                pen = QPen(QColor(80, 230, 230))
                pen.setWidth(2)
                painter.setPen(pen)
                painter.setBrush(QBrush(QColor(80, 230, 230, 25)))
                painter.drawRect(rx, ry, rw, rh)
                painter.drawText(rx + 4, ry + 14, "default ROI")
        finally:
            painter.end()

    def _draw_overlay(
        self, painter: QPainter, ov: Overlay, dx: int, dy: int, sx: float, sy: float
    ) -> None:
        pen = QPen(QColor(*ov.color))
        pen.setWidth(ov.width)
        painter.setPen(pen)

        if ov.kind == "point":
            x, y = ov.data
            px = int(dx + x * sx)
            py = int(dy + y * sy)
            painter.drawEllipse(px - 5, py - 5, 11, 11)
            painter.drawLine(px - 8, py, px + 8, py)
            painter.drawLine(px, py - 8, px, py + 8)
            if ov.label:
                painter.drawText(px + 9, py - 6, ov.label)
        elif ov.kind == "bbox":
            x, y, w, h = ov.data
            rx = int(dx + x * sx)
            ry = int(dy + y * sy)
            rw = max(1, int(w * sx))
            rh = max(1, int(h * sy))
            painter.drawRect(rx, ry, rw, rh)
            if ov.label:
                painter.drawText(rx, max(0, ry - 3), ov.label)


def _rect_from_corners(a, b):
    """Given two (x, y) source points, return the enclosing (x, y, w, h) rect."""
    if a is None or b is None:
        return None
    x0, x1 = sorted([int(a[0]), int(b[0])])
    y0, y1 = sorted([int(a[1]), int(b[1])])
    return (x0, y0, x1 - x0 + 1, y1 - y0 + 1)


def _bgr_to_pixmap(bgr: np.ndarray) -> QPixmap:
    """Convert an HxWx3 BGR uint8 frame to a QPixmap."""
    h, w = bgr.shape[:2]
    # Swap BGR → RGB in a copy (QImage needs RGB).
    rgb = np.ascontiguousarray(bgr[..., ::-1])
    qimg = QImage(rgb.data, w, h, w * 3, QImage.Format.Format_RGB888)
    # Copy so the numpy buffer can be freed without affecting the pixmap.
    return QPixmap.fromImage(qimg.copy())
