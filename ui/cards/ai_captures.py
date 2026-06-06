"""Captures section — snapshot / record / colour-label, all into the
active bot bundle's ``assets/`` folder.

Player captures are the *primary* source of vision data for bots.
Wiki templates are a fallback for assets the player hasn't captured
yet. This card is where players build their per-bot asset library.

Three buttons:

- **Snapshot** — opens the ZoneDrawer, captures ONE frame of the
  selected ROI via ``mss``, saves to ``assets/snapshots/<slug>.png``.
- **Record (3-10s)** — same drawer, but captures N frames at the
  bundle's tick rate. Lands at ``assets/recordings/<slug>/`` with a
  ``meta.json`` describing fps/frame count.
- **Colour label** — reuses the existing ``ColorPicker`` overlay,
  saves the eyedropped RGB + monitor index to
  ``assets/colors/<slug>.json``.

All three require an active bundle. Without one the buttons are
disabled with an explanatory hint.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

import numpy as np
from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QCheckBox, QDialog, QDialogButtonBox, QFrame, QHBoxLayout, QInputDialog,
    QLabel, QPushButton, QScrollArea, QVBoxLayout, QWidget,
)

from ai import captures as global_captures
from ai.bot.bundle import BotBundle, slugify

from .. import theme as t
from ..widgets.card import Card


_DEFAULT_RECORDING_S: float = 5.0       # how long to record by default
_RECORDING_FPS_FALLBACK: float = 5.0    # used when bundle has no tick rate


class AICapturesSection(Card):
    """The card the user clicks to grow their bundle's asset library."""

    # Emitted after the user promotes one or more captures into the
    # global library. ``AIPageBody`` connects this to the library
    # browser card's ``refresh()`` slot so the UI stays in sync.
    globalCapturesChanged = Signal()

    def __init__(self, app) -> None:
        super().__init__("Captures")
        self.app = app
        self._active_bundle: Optional[BotBundle] = None
        # Recording state — driven by a QTimer when a recording is in flight.
        self._recording_timer: Optional[QTimer] = None
        self._recording_frames: List[np.ndarray] = []
        self._recording_rect: Optional[tuple] = None
        self._recording_total: int = 0
        self._recording_label: str = ""

        # Status / hint line.
        self._status = QLabel("Select a bot bundle in the dropdown above to enable captures.")
        self._status.setWordWrap(True)
        self._status.setStyleSheet(
            f"color: {t.TEXT_TERTIARY}; font-size: {t.SIZE_SM}px;"
        )
        self.add(self._status)

        # Three capture buttons.
        row = QWidget()
        h = QHBoxLayout(row)
        h.setContentsMargins(0, t.SP_SM, 0, 0)
        h.setSpacing(t.SP_SM)

        self._snap_btn = QPushButton("📸  Snapshot")
        self._snap_btn.setMinimumHeight(t.BUTTON_H)
        self._snap_btn.setCursor(Qt.PointingHandCursor)
        self._snap_btn.clicked.connect(self._on_snapshot)
        h.addWidget(self._snap_btn)

        self._rec_btn = QPushButton("🎥  Record (5s)")
        self._rec_btn.setMinimumHeight(t.BUTTON_H)
        self._rec_btn.setCursor(Qt.PointingHandCursor)
        self._rec_btn.clicked.connect(self._on_record)
        h.addWidget(self._rec_btn)

        self._color_btn = QPushButton("🎯  Colour label")
        self._color_btn.setMinimumHeight(t.BUTTON_H)
        self._color_btn.setCursor(Qt.PointingHandCursor)
        self._color_btn.clicked.connect(self._on_color)
        h.addWidget(self._color_btn)

        self._dtm_btn = QPushButton("📐  DTM")
        self._dtm_btn.setMinimumHeight(t.BUTTON_H)
        self._dtm_btn.setCursor(Qt.PointingHandCursor)
        self._dtm_btn.setToolTip(
            "Drag a rectangle around a UI element / object. The app "
            "samples N coloured points in a rigid layout and saves a "
            "DTM template — robust against single-pixel false positives. "
            "Best for chests, NPCs, icons, anvils."
        )
        self._dtm_btn.clicked.connect(self._on_dtm)
        h.addWidget(self._dtm_btn)

        self._roi_btn = QPushButton("📍  Search ROI")
        self._roi_btn.setMinimumHeight(t.BUTTON_H)
        self._roi_btn.setCursor(Qt.PointingHandCursor)
        self._roi_btn.setToolTip(
            "Drag a rectangle to save as a named search ROI (e.g. "
            "vip_pool_west, vip_chest_search). Bots reference these "
            "by name so you don't have to paste tuples into Python "
            "files: from ai.captures import roi; POOL_ROI = roi('vip_pool_west')."
        )
        self._roi_btn.clicked.connect(self._on_roi)
        h.addWidget(self._roi_btn)

        self._promote_btn = QPushButton("★  Promote to global…")
        self._promote_btn.setMinimumHeight(t.BUTTON_H)
        self._promote_btn.setCursor(Qt.PointingHandCursor)
        self._promote_btn.setToolTip(
            "Copy selected captures to ai/captures/global/ so any bot can "
            "import them by name. Reusable across every skilling bot."
        )
        self._promote_btn.clicked.connect(self._on_promote)
        h.addWidget(self._promote_btn)

        self._debug_btn = QPushButton("🐛  Debug frame")
        self._debug_btn.setMinimumHeight(t.BUTTON_H)
        self._debug_btn.setCursor(Qt.PointingHandCursor)
        self._debug_btn.setToolTip(
            "Save the current target-screen capture to bots/<slug>/debug/ "
            "with a timestamp. Useful when a bot rule isn't matching — "
            "open the saved frame and compare it to your captures."
        )
        self._debug_btn.clicked.connect(self._on_debug_frame)
        h.addWidget(self._debug_btn)

        h.addStretch(1)
        self.add(row)

        # Summary line + inline asset rows. The summary is a one-line
        # count ("snapshots: 3 · recordings: 1 · …"); the rows below
        # are the actual list, each with a thumbnail + delete button so
        # the user can prune the library without leaving the card.
        self._inventory = QLabel("")
        self._inventory.setWordWrap(True)
        self._inventory.setStyleSheet(
            f"color: {t.TEXT_SECONDARY}; "
            f"font-size: {t.SIZE_SM}px; "
            f"font-family: {t.FONT_MONO}; "
            f"padding-top: 6px;"
        )
        self.add(self._inventory)

        self._rows_host = QWidget()
        self._rows_col = QVBoxLayout(self._rows_host)
        self._rows_col.setContentsMargins(0, 4, 0, 0)
        self._rows_col.setSpacing(t.SP_SM)
        self.add(self._rows_host)

        # Hint footer.
        hint = QLabel(
            "Snapshots = single frame for landmarks/icons. "
            "Recordings = motion (fishing spot bubbles, animated targets). "
            "Colour labels = eyedropped pixel for fallback colour matching."
        )
        hint.setWordWrap(True)
        hint.setStyleSheet(
            f"color: {t.TEXT_TERTIARY}; "
            f"font-size: {t.SIZE_SM}px; "
            f"padding-top: 4px;"
        )
        self.add(hint)

        self._update_enabled_state()

    # ── Bundle awareness ─────────────────────────────────────────
    def _on_active_bundle_changed(self, bundle: Optional[BotBundle]) -> None:
        self._active_bundle = bundle
        self._update_enabled_state()

    def _update_enabled_state(self) -> None:
        has_bundle = self._active_bundle is not None
        self._snap_btn.setEnabled(has_bundle)
        self._rec_btn.setEnabled(has_bundle)
        self._color_btn.setEnabled(has_bundle)
        self._dtm_btn.setEnabled(has_bundle)
        self._roi_btn.setEnabled(has_bundle)
        self._debug_btn.setEnabled(has_bundle)
        self._promote_btn.setEnabled(
            has_bundle and self._bundle_has_any_assets()
        )
        if not has_bundle:
            self._status.setText(
                "Select or create a bot bundle in the dropdown above to enable captures."
            )
            self._inventory.setText("")
            return
        b = self._active_bundle
        self._status.setText(
            f"Active bundle: {b.name}  ·  assets at {b.assets_dir}"
        )
        self._refresh_inventory()

    def _refresh_inventory(self) -> None:
        b = self._active_bundle
        # Tear down any existing asset rows so the rebuild is clean.
        while self._rows_col.count():
            w = self._rows_col.takeAt(0).widget()
            if w is not None:
                w.deleteLater()
        if b is None:
            self._inventory.setText("")
            return
        snaps = b.list_snapshots()
        recs = b.list_recordings()
        items = b.list_items()
        cols = b.list_colors()
        dtms = b.list_dtms()
        rois = b.list_rois()
        self._inventory.setText(
            f"snapshots: {len(snaps)}  ·  recordings: {len(recs)}  ·  "
            f"items: {len(items)}  ·  colours: {len(cols)}  ·  "
            f"dtms: {len(dtms)}  ·  rois: {len(rois)}"
        )
        # Build per-asset rows grouped by kind.
        if cols:
            self._rows_col.addWidget(_KindHeader("Colours"))
            for p in cols:
                self._rows_col.addWidget(_AssetRow(self, p, "color"))
        if rois:
            self._rows_col.addWidget(_KindHeader("Search ROIs"))
            for p in rois:
                self._rows_col.addWidget(_AssetRow(self, p, "roi"))
        if snaps:
            self._rows_col.addWidget(_KindHeader("Snapshots"))
            for p in snaps:
                self._rows_col.addWidget(_AssetRow(self, p, "snapshot"))
        if dtms:
            self._rows_col.addWidget(_KindHeader("DTMs"))
            for p in dtms:
                self._rows_col.addWidget(_AssetRow(self, p, "dtm"))
        if recs:
            self._rows_col.addWidget(_KindHeader("Recordings"))
            for p in recs:
                self._rows_col.addWidget(_AssetRow(self, p, "recording"))
        if items:
            self._rows_col.addWidget(_KindHeader("Items"))
            for p in items:
                self._rows_col.addWidget(_AssetRow(self, p, "item"))
        # Keep the Promote button accurate as captures land / are deleted.
        self._promote_btn.setEnabled(self._bundle_has_any_assets())

    # ── Delete (per-row) ────────────────────────────────────────
    def delete_asset(self, kind: str, path: Path) -> None:
        """Confirm + remove a per-bundle capture file from disk and drop
        its slug from the kind's index.json. Called by an _AssetRow
        when the user clicks 🗑.
        """
        from PySide6.QtWidgets import QMessageBox

        slug = path.stem if kind != "recording" else path.name
        reply = QMessageBox.question(
            self, f"Delete {kind}?",
            f"Permanently remove “{slug}” from this bundle?\n\n"
            f"The file will be deleted from disk. If a copy was promoted "
            f"to the global library, that copy is unaffected.",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return
        try:
            if kind == "recording":
                import shutil as _sh
                _sh.rmtree(path)
            elif kind == "dtm":
                # DTM is a YAML + paired PNG thumbnail — remove both.
                path.unlink()
                paired_png = path.with_suffix(".png")
                if paired_png.exists():
                    paired_png.unlink()
            else:
                path.unlink()
            self._drop_from_index(kind, slug)
        except Exception as e:
            self.app.toasts.post(
                f"⚠ Delete failed: {type(e).__name__}: {e}",
                kind="error",
            )
            return
        self.app.toasts.post(
            f"🗑 Deleted {kind}: {slug}", kind="warn",
        )
        self._refresh_inventory()

    def _drop_from_index(self, kind: str, slug: str) -> None:
        """Strip a slug entry from the kind's index.json. Silent on
        missing index — many older bundles don't have one."""
        b = self._active_bundle
        if b is None:
            return
        if kind == "snapshot":
            idx = b.snapshots_dir / "index.json"
        elif kind == "recording":
            idx = b.recordings_dir / "index.json"
        elif kind == "color":
            idx = b.colors_dir / "index.json"
        elif kind == "item":
            idx = b.items_dir / "index.json"
        elif kind == "dtm":
            idx = b.dtm_dir / "index.json"
        elif kind == "roi":
            idx = b.rois_dir / "index.json"
        else:
            return
        if not idx.exists():
            return
        try:
            payload = json.loads(idx.read_text(encoding="utf-8"))
        except Exception:
            return
        if not isinstance(payload, list):
            return
        payload = [e for e in payload if e.get("slug") != slug]
        idx.write_text(
            json.dumps(payload, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

    def _bundle_has_any_assets(self) -> bool:
        b = self._active_bundle
        if b is None:
            return False
        return bool(
            b.list_colors() or b.list_snapshots() or b.list_recordings()
            or b.list_dtms() or b.list_rois()
        )

    # ── Promote to global library ───────────────────────────────
    def _on_promote(self) -> None:
        """Open a dialog listing every per-bundle capture; promote
        whichever the user checks. Reuses the global library at
        ``ai/captures/global/`` so every bot can ``from ai.captures
        import color, snapshot, recording`` by name."""
        b = self._active_bundle
        if b is None:
            return
        dialog = _PromoteDialog(self, b)
        if dialog.exec() != QDialog.Accepted:
            return
        promoted = dialog.promote_selected()
        if not promoted:
            return
        names = ", ".join(promoted)
        self.app.toasts.post(
            f"★ Promoted {len(promoted)} capture(s) to global: {names}",
            kind="success",
        )
        # Notify the library browser (mounted by AIPageBody) so it
        # refreshes without the user having to click Refresh manually.
        self.globalCapturesChanged.emit()

    # ── Snapshot ────────────────────────────────────────────────
    def _on_snapshot(self) -> None:
        if self._active_bundle is None:
            return
        self._capture_rect_then(lambda rect: self._do_snapshot(rect))

    def _do_snapshot(self, rect: tuple) -> None:
        b = self._active_bundle
        if b is None:
            return
        name, ok = QInputDialog.getText(
            self, "Save snapshot",
            "Asset name (e.g. bank_chest, fishing_anchor):",
        )
        if not ok or not (name or "").strip():
            return
        slug = slugify(name)
        try:
            frame = self._grab_full_frame()
            crop = self._crop_to_rect(frame, rect)
        except Exception as e:
            self.app.toasts.post(
                f"⚠ Snapshot capture failed: {type(e).__name__}: {e}",
                kind="error",
            )
            return
        try:
            self._save_png(crop, b.snapshots_dir / f"{slug}.png")
            self._append_index(b.snapshots_dir / "index.json", {
                "slug": slug,
                "name": name.strip(),
                "rect": list(rect),
                "captured_at": time.time(),
            })
        except Exception as e:
            self.app.toasts.post(
                f"⚠ Snapshot save failed: {type(e).__name__}: {e}",
                kind="error",
            )
            return
        self.app.toasts.post(
            f"✓ Snapshot saved: {slug}.png ({rect[2]}×{rect[3]})",
            kind="success",
        )
        self._refresh_inventory()

    # ── Recording ───────────────────────────────────────────────
    def _on_record(self) -> None:
        if self._active_bundle is None:
            return
        if self._recording_timer is not None:
            return                              # already recording
        self._capture_rect_then(lambda rect: self._do_record(rect))

    def _do_record(self, rect: tuple) -> None:
        b = self._active_bundle
        if b is None:
            return
        name, ok = QInputDialog.getText(
            self, "Save recording",
            "Asset name (e.g. fishing_spot_west, trap_active):",
        )
        if not ok or not (name or "").strip():
            return
        slug = slugify(name)

        # Pick FPS from the bundle's tick rate; fall back to 5 Hz.
        tick_rate = float(
            (b.settings or {}).get("tick_rate_hz")
            or self.app.cfg.get("ai_tick_rate_hz")
            or _RECORDING_FPS_FALLBACK
        )
        fps = max(1.0, min(15.0, tick_rate))
        total_frames = int(_DEFAULT_RECORDING_S * fps)

        # Timer-driven capture so the GUI doesn't freeze.
        self._recording_frames = []
        self._recording_rect = rect
        self._recording_total = total_frames
        self._recording_label = name.strip()
        self._recording_slug = slug
        self._recording_fps = fps
        timer = QTimer(self)
        interval_ms = int(1000.0 / fps)
        timer.setInterval(interval_ms)
        timer.timeout.connect(self._on_record_tick)
        self._recording_timer = timer
        self.app.toasts.post(
            f"🎥 Recording {total_frames} frames @ {fps:.0f} fps "
            f"({_DEFAULT_RECORDING_S:.0f}s)…",
            kind="info",
        )
        timer.start()

    def _on_record_tick(self) -> None:
        b = self._active_bundle
        rect = self._recording_rect
        if b is None or rect is None:
            self._stop_recording(success=False)
            return
        try:
            full = self._grab_full_frame()
            crop = self._crop_to_rect(full, rect)
        except Exception:
            crop = None
        if crop is not None:
            self._recording_frames.append(crop)
        if len(self._recording_frames) >= self._recording_total:
            self._stop_recording(success=True)

    def _stop_recording(self, *, success: bool) -> None:
        timer = self._recording_timer
        if timer is not None:
            timer.stop()
            timer.deleteLater()
        self._recording_timer = None
        if not success or not self._recording_frames:
            self._recording_frames = []
            self._recording_rect = None
            return
        b = self._active_bundle
        if b is None:
            return
        slug = self._recording_slug
        target_dir = b.recordings_dir / slug
        try:
            target_dir.mkdir(parents=True, exist_ok=True)
            for i, frame in enumerate(self._recording_frames):
                self._save_png(frame, target_dir / f"frame_{i:03d}.png")
            meta = {
                "slug": slug,
                "name": self._recording_label,
                "rect": list(self._recording_rect),
                "fps": self._recording_fps,
                "frame_count": len(self._recording_frames),
                "duration_s": len(self._recording_frames) / self._recording_fps,
                "captured_at": time.time(),
            }
            (target_dir / "meta.json").write_text(
                json.dumps(meta, indent=2), encoding="utf-8",
            )
        except Exception as e:
            self.app.toasts.post(
                f"⚠ Recording save failed: {type(e).__name__}: {e}",
                kind="error",
            )
            self._recording_frames = []
            self._recording_rect = None
            return
        self.app.toasts.post(
            f"✓ Recording saved: {slug} ({len(self._recording_frames)} frames)",
            kind="success",
        )
        self._recording_frames = []
        self._recording_rect = None
        self._refresh_inventory()

    # ── Capture via frozen-frame overlay (hotkey-driven) ────────
    def capture_via_frozen_frame(self, cursor_xy: tuple) -> None:
        """Hotkey entry point: freeze a frame, let the user crop it, save.

        Reuses ``_grab_full_frame()`` for the capture, then displays a
        ``FrozenFrameDrawer`` overlay so the user can crop the captured
        pixels (not a live feed). After the user releases the rect,
        the same save machinery the regular Snapshot button uses runs —
        prompt for asset name, crop via ``_crop_to_rect``, write PNG +
        index entry. The cursor's position when the hotkey fired is
        passed in as ``cursor_xy`` (Qt DIP coords) so the overlay can
        render a marker for visual reference.
        """
        if self._active_bundle is None:
            self.app.toasts.post(
                "⚠ Pick a bundle before capturing.", kind="warn",
            )
            return
        try:
            frame = self._grab_full_frame()
        except Exception as e:
            self.app.toasts.post(
                f"⚠ Capture failed: {type(e).__name__}: {e}", kind="error",
            )
            return
        # Convert Qt DIP cursor coords → physical px (the unit the
        # frozen drawer uses for the marker placement math).
        try:
            from utils.dpi_cursor import dip_to_physical
            phys_xy = dip_to_physical(int(cursor_xy[0]), int(cursor_xy[1]))
        except Exception:
            phys_xy = (int(cursor_xy[0]), int(cursor_xy[1]))

        # Spawn the overlay on the same screen the frame came from.
        from ..overlays.frozen_frame_drawer import FrozenFrameDrawer
        try:
            self.app.overlay_manager.hide_for_drawing()
        except Exception:
            pass
        self.app.showMinimized()
        target = (
            self.app.target_screen() if hasattr(self.app, "target_screen")
            else None
        )
        drawer = FrozenFrameDrawer(frame, cursor_xy=phys_xy, screen=target)

        def _finished(rect):
            # Restore main window BEFORE invoking any dialog so the
            # asset-name prompt follows the active monitor (same fix
            # as open_zone_drawer's _finished).
            drawer.deleteLater()
            self.app.showNormal()
            self.app.raise_()
            self.app.activateWindow()
            if rect is None:
                return
            self._save_frozen_capture(frame, rect)

        drawer.finished.connect(_finished)
        QTimer.singleShot(180, drawer.show)
        QTimer.singleShot(220, drawer.activateWindow)

    def _save_frozen_capture(self, frame, rect: tuple) -> None:
        """Common save path for a frozen-frame crop. Reuses the regular
        Snapshot save machinery so the on-disk artefact is byte-identical
        to a ZoneDrawer-routed snapshot."""
        b = self._active_bundle
        if b is None:
            return
        name, ok = QInputDialog.getText(
            self, "Save hover snapshot",
            "Asset name (e.g. vip_spot_tooltip, vip_chest_tooltip):",
        )
        if not ok or not (name or "").strip():
            return
        slug = slugify(name)
        try:
            crop = self._crop_to_rect(frame, rect)
        except Exception as e:
            self.app.toasts.post(
                f"⚠ Crop failed: {type(e).__name__}: {e}", kind="error",
            )
            return
        try:
            self._save_png(crop, b.snapshots_dir / f"{slug}.png")
            self._append_index(b.snapshots_dir / "index.json", {
                "slug": slug,
                "name": name.strip(),
                "rect": list(rect),
                "source": "hotkey_frozen",
                "captured_at": time.time(),
            })
        except Exception as e:
            self.app.toasts.post(
                f"⚠ Snapshot save failed: {type(e).__name__}: {e}",
                kind="error",
            )
            return
        self.app.toasts.post(
            f"✓ Hover snapshot saved: {slug}.png ({rect[2]}×{rect[3]})",
            kind="success",
        )
        self._refresh_inventory()

    # ── Debug frame ─────────────────────────────────────────────
    def _on_debug_frame(self) -> None:
        """Save the current target-screen capture to the bundle's debug
        folder with a timestamped filename. When a promoted Colour
        capture exists in the global library, also emits a side-by-side
        match-overlay PNG showing where each sample lit up — fast way
        to diagnose ``find_interactable`` / ``find_any_color`` misses
        without re-running the whole bot."""
        b = self._active_bundle
        if b is None:
            return
        try:
            frame = self._grab_full_frame()
        except Exception as e:
            self.app.toasts.post(
                f"⚠ Debug capture failed: {type(e).__name__}: {e}",
                kind="error",
            )
            return
        # bots/<slug>/debug/ — created on demand.
        debug_dir = b.debug_dir
        try:
            debug_dir.mkdir(parents=True, exist_ok=True)
        except Exception as e:
            self.app.toasts.post(
                f"⚠ Couldn't create debug dir: {e}", kind="error",
            )
            return
        ts = time.strftime("%Y%m%d_%H%M%S")
        path = debug_dir / f"frame_{ts}.png"
        try:
            self._save_png(frame, path)
        except Exception as e:
            self.app.toasts.post(
                f"⚠ Debug save failed: {type(e).__name__}: {e}",
                kind="error",
            )
            return
        # Also emit a match-overlay PNG for every promoted colour
        # capture in the global library. One file per colour so the
        # output is readable instead of one giant collage.
        overlay_saved: list[str] = []
        try:
            from ai.captures import list_global, colors as _colors
            for entry in list_global("colors") or []:
                slug = str(entry.get("slug") or "").strip()
                if not slug:
                    continue
                try:
                    samples = _colors(slug)
                except Exception:
                    continue
                overlay_path = (
                    debug_dir / f"frame_{ts}_match_{slug}.png"
                )
                ok = self._save_color_match_overlay(
                    frame, samples, slug, overlay_path,
                )
                if ok:
                    overlay_saved.append(slug)
        except Exception:
            pass  # overlay is best-effort; raw frame already saved.

        msg = f"🐛 Debug frame saved → {path.name}"
        if overlay_saved:
            msg += f"  ·  +overlay × {len(overlay_saved)}"
        self.app.toasts.post(msg, kind="info")
        # Try to open the file's containing folder so the user can
        # find it without hunting through the bundle directory.
        try:
            import os, subprocess
            if hasattr(os, "startfile"):
                # /select,<path> highlights the file in Explorer.
                subprocess.Popen(
                    ["explorer", "/select,", str(path)],
                )
        except Exception:
            pass

    def _save_color_match_overlay(
        self, frame, samples, slug: str, out_path,
    ) -> bool:
        """Render a side-by-side diagnostic image: raw frame on the
        left, the same frame with every sample's matching pixels
        tinted green + cluster centroids marked on the right. Stats
        text in the top-left corner of the overlay half tells you
        per-sample hit counts. Returns True on success."""
        try:
            import cv2
            import numpy as np
            import rs3vision as rv
        except Exception:
            return False
        if not samples:
            return False

        try:
            h, w = frame.shape[:2]
            overlay = frame.copy()
            # Per-sample stats for the annotation block.
            stats: list[tuple[int, int, int]] = []  # (hex_rgb, hits, clusters)
            for hex_rgb in samples:
                try:
                    bgr = (
                        int(hex_rgb) & 0xFF,
                        (int(hex_rgb) >> 8) & 0xFF,
                        (int(hex_rgb) >> 16) & 0xFF,
                    )
                except Exception:
                    continue
                try:
                    hits = rv.color.find(
                        frame, bgr, cts=2, tol=25.0, roi=None,
                    )
                except Exception:
                    hits = []
                pts = [(int(x), int(y)) for x, y, *_ in hits]
                # Paint matched pixels — bright lime green.
                for x, y in pts:
                    if 0 <= x < w and 0 <= y < h:
                        overlay[y, x] = (0, 255, 0)
                clusters = []
                try:
                    clusters = (
                        rv.tpa.cluster(pts, dist=4) if pts else []
                    )
                except Exception:
                    clusters = []
                # Filter to min_pixels >= 20 (the bot's default).
                strong = [c for c in clusters if len(c) >= 20]
                for c in strong:
                    try:
                        cx, cy = rv.tpa.centroid(c)
                        cv2.circle(
                            overlay, (int(cx), int(cy)),
                            12, (0, 0, 255), 2,
                        )
                    except Exception:
                        pass
                stats.append((int(hex_rgb), len(pts), len(strong)))

            # Annotate top-left of the overlay with per-sample counts.
            y0 = 24
            cv2.rectangle(
                overlay, (8, 8), (520, 24 + 22 * (len(stats) + 1)),
                (0, 0, 0), -1,
            )
            cv2.putText(
                overlay, f"match_overlay: {slug}",
                (16, y0), cv2.FONT_HERSHEY_SIMPLEX, 0.6,
                (255, 255, 255), 1, cv2.LINE_AA,
            )
            for i, (hex_rgb, hits, clust) in enumerate(stats):
                line = f"0x{hex_rgb:06X}  hits={hits}  clusters>=20px={clust}"
                cv2.putText(
                    overlay, line,
                    (16, y0 + 22 * (i + 1)),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5,
                    (255, 255, 255), 1, cv2.LINE_AA,
                )

            # Side-by-side compose.
            sep = np.zeros((h, 4, 3), dtype=frame.dtype)
            sep[:, :, :] = (64, 64, 64)
            composed = np.hstack([frame, sep, overlay])
            self._save_png(composed, out_path)
            return True
        except Exception:
            return False

    # ── Search ROI ──────────────────────────────────────────────
    def _on_roi(self) -> None:
        if self._active_bundle is None:
            return
        self._capture_rect_then(lambda rect: self._do_roi(rect))

    def _do_roi(self, rect: tuple) -> None:
        b = self._active_bundle
        if b is None:
            return
        name, ok = QInputDialog.getText(
            self, "Save search ROI",
            "ROI name (e.g. vip_pool_west, vip_chest_search):",
        )
        if not ok or not (name or "").strip():
            return
        slug = slugify(name)
        # Rect is already in physical pixels (converted in
        # _capture_rect_then). Persist as {x, y, w, h} so bots can
        # call ``roi('vip_pool_west')`` and pass the result straight
        # into ``find_color(roi=...)`` etc.
        x, y, w, h = rect
        payload = {
            "slug": slug,
            "name": name.strip(),
            "rect": [int(x), int(y), int(w), int(h)],
            "captured_at": time.time(),
        }
        try:
            (b.rois_dir / f"{slug}.json").write_text(
                json.dumps(payload, indent=2), encoding="utf-8",
            )
            self._append_index(b.rois_dir / "index.json", payload)
        except Exception as e:
            self.app.toasts.post(
                f"⚠ ROI save failed: {type(e).__name__}: {e}",
                kind="error",
            )
            return
        self.app.toasts.post(
            f"✓ ROI saved: {slug} → {w}×{h} @ ({x}, {y})",
            kind="success",
        )
        self._refresh_inventory()

    # ── DTM template ────────────────────────────────────────────
    def _on_dtm(self) -> None:
        if self._active_bundle is None:
            return
        self._capture_rect_then(lambda rect: self._do_dtm(rect))

    def _do_dtm(self, rect: tuple) -> None:
        b = self._active_bundle
        if b is None:
            return
        name, ok = QInputDialog.getText(
            self, "Save DTM template",
            "Template name (e.g. bank_chest, anvil, npc_banker):",
        )
        if not ok or not (name or "").strip():
            return
        slug = slugify(name)
        # Snap a frame and crop to the rect for the build_from_roi
        # synthesis. The PNG is stored alongside the YAML so the user
        # has a thumbnail / debugging reference.
        try:
            full = self._grab_full_frame()
            crop = self._crop_to_rect(full, rect)
        except Exception as e:
            self.app.toasts.post(
                f"⚠ DTM capture failed: {type(e).__name__}: {e}",
                kind="error",
            )
            return
        # Build template from the frame in absolute coords, since
        # build_from_roi expects (x, y, w, h) inside the frame array.
        try:
            from ai.algorithms.dtm import build_from_roi, save as _dtm_save
        except Exception as e:
            self.app.toasts.post(
                f"⚠ DTM module unavailable: {e}", kind="error",
            )
            return
        try:
            ox, oy = getattr(self, "_monitor_origin", (0, 0))
            x, y, w, h = rect
            local_rect = (
                max(0, x - ox), max(0, y - oy), int(w), int(h),
            )
            tpl = build_from_roi(full, local_rect, name=slug, points=5)
        except Exception as e:
            self.app.toasts.post(
                f"⚠ DTM build failed: {type(e).__name__}: {e}",
                kind="error",
            )
            return
        try:
            yaml_path = b.dtm_dir / f"{slug}.yaml"
            png_path = b.dtm_dir / f"{slug}.png"
            _dtm_save(tpl, str(yaml_path))
            self._save_png(crop, png_path)
            self._append_index(b.dtm_dir / "index.json", {
                "slug": slug,
                "name": name.strip(),
                "rect": list(rect),
                "captured_at": time.time(),
            })
        except Exception as e:
            self.app.toasts.post(
                f"⚠ DTM save failed: {type(e).__name__}: {e}",
                kind="error",
            )
            return
        self.app.toasts.post(
            f"✓ DTM saved: {slug} ({rect[2]}×{rect[3]}, "
            f"{len(tpl.points) + 1} points)",
            kind="success",
        )
        self._refresh_inventory()

    # ── Colour label ────────────────────────────────────────────
    def _on_color(self) -> None:
        if self._active_bundle is None:
            return

        def _done(result):
            if result is None:
                return
            # ColorPicker now emits a ColorPickResult that contains the
            # whole sample stack. Tuple unpacking still gives
            # (primary_rgb, x, y) for backward compatibility.
            samples = list(getattr(result, "samples", None) or [])
            primary = getattr(result, "primary", None)
            last_xy = getattr(result, "last_xy", None)
            if primary is None or last_xy is None:
                # Older single-sample tuple shape — adapt.
                try:
                    primary, x, y = result
                    samples = [tuple(primary)]
                    last_xy = (int(x), int(y))
                except Exception:
                    return
            x, y = last_xy
            name, ok = QInputDialog.getText(
                self, "Save colour label",
                "Asset name (e.g. seren_spirit_halo, vip_fishing_spot):",
            )
            if not ok or not (name or "").strip():
                return
            slug = slugify(name)
            b = self._active_bundle
            if b is None:
                return
            primary_rgb = [int(primary[0]), int(primary[1]), int(primary[2])]
            extras = [
                [int(s[0]), int(s[1]), int(s[2])]
                for s in samples[1:]
            ]
            payload = {
                "slug": slug,
                "name": name.strip(),
                "rgb": primary_rgb,
                "extra_rgbs": extras,
                "screen_xy": [int(x), int(y)],
                "captured_at": time.time(),
            }
            try:
                (b.colors_dir / f"{slug}.json").write_text(
                    json.dumps(payload, indent=2), encoding="utf-8",
                )
            except Exception as e:
                self.app.toasts.post(
                    f"⚠ Colour save failed: {type(e).__name__}: {e}",
                    kind="error",
                )
                return
            count_str = (
                f"{len(samples)} samples" if len(samples) > 1
                else "1 sample"
            )
            self.app.toasts.post(
                f"✓ Colour saved: {slug} ({count_str}) → "
                f"#{primary_rgb[0]:02X}{primary_rgb[1]:02X}{primary_rgb[2]:02X}",
                kind="success",
            )
            self._refresh_inventory()

        self.app.open_color_picker(_done)

    # ── Helpers ─────────────────────────────────────────────────
    def _capture_rect_then(self, on_rect) -> None:
        """Open the ZoneDrawer, validate the result, hand the rect off
        to ``on_rect`` in PHYSICAL-PIXEL coordinates.

        ZoneDrawer emits rectangles in Qt's logical (DIP) coordinate
        space because that's where the user's mouse events live. Every
        downstream consumer (mss capture cropping, meta.json rects,
        bot runtime ROIs that slice physical-px mss frames) needs the
        rect in PHYSICAL pixels. Converting at this boundary keeps the
        rest of the capture pipeline consistent with the bot side —
        a recording's stored rect can be passed straight to
        ``is_animating(rect)`` without any per-call DPI maths.

        Uses :func:`dip_rect_to_physical` (rect-aware, center-point
        lookup) instead of two corner-point ``dip_to_physical`` calls,
        which would fail when a rect corner sits exactly on the screen
        edge — that hit the identity-fallback path and produced a
        half-scaled rect on DPR>1 monitors.
        """
        from utils.dpi_cursor import dip_rect_to_physical

        def _done(zone):
            if zone is None or zone.shape != "rect" or not zone.rect:
                return
            x1, y1, x2, y2 = zone.rect
            x, y = int(min(x1, x2)), int(min(y1, y2))
            w, h = int(abs(x2 - x1)), int(abs(y2 - y1))
            if w < 4 or h < 4:
                self.app.toasts.post(
                    "⚠ Capture rect too small — try again", kind="warn",
                )
                return
            px, py, pw, ph = dip_rect_to_physical(x, y, w, h)
            on_rect((int(px), int(py), int(pw), int(ph)))

        self.app.open_zone_drawer("rect", _done)

    def _grab_full_frame(self) -> np.ndarray:
        """Capture the configured target monitor as a BGR uint8 array.

        Uses ``app.target_screen()`` so the ZoneDrawer and this capture
        always agree on WHICH monitor — without this alignment, the
        drawer might bind to one screen while mss grabs another, and
        crops land outside the player's actual screen.

        Falls back to the legacy ``ai_monitor`` config index when the
        app doesn't expose ``target_screen()`` (older entry points).
        """
        import mss
        from utils.dpi_cursor import dip_rect_to_physical

        target = (
            self.app.target_screen() if hasattr(self.app, "target_screen")
            else None
        )
        with mss.mss() as sct:
            if target is not None:
                # DIP rect (Qt geometry) → physical rect via the rect-aware
                # helper. Using corner-point lookups via ``dip_to_physical``
                # previously failed when the bottom-right corner fell
                # exactly on the screen edge — the lookup returned None
                # and the identity-fallback produced a half-size physical
                # rect, so mss only grabbed the top-left of the monitor.
                geom = target.geometry()
                px, py, pw, ph = dip_rect_to_physical(
                    geom.left(), geom.top(),
                    geom.width(), geom.height(),
                )
                region = {
                    "left": px, "top": py,
                    "width": pw, "height": ph,
                }
                self._monitor_origin = (px, py)
            else:
                mons = sct.monitors
                idx = int(self.app.cfg.get("ai_monitor", 1))
                if not (0 <= idx < len(mons)):
                    idx = 1 if len(mons) > 1 else 0
                mon = mons[idx]
                region = {
                    "left": int(mon.get("left", 0)),
                    "top": int(mon.get("top", 0)),
                    "width": int(mon.get("width", 0)),
                    "height": int(mon.get("height", 0)),
                }
                self._monitor_origin = (
                    int(mon.get("left", 0)), int(mon.get("top", 0)),
                )
            raw = sct.grab(region)
            frame = np.ascontiguousarray(
                np.asarray(raw, dtype=np.uint8)[:, :, :3]
            )
        return frame

    def _crop_to_rect(self, frame: np.ndarray, rect: tuple) -> np.ndarray:
        """Crop ``frame`` to an absolute screen rect, accounting for the
        monitor origin offset (for multi-monitor setups)."""
        ox, oy = getattr(self, "_monitor_origin", (0, 0))
        x, y, w, h = rect
        lx = max(0, x - ox)
        ly = max(0, y - oy)
        return np.ascontiguousarray(frame[ly:ly + h, lx:lx + w])

    def _save_png(self, bgr: np.ndarray, path: Path) -> None:
        """BGR → RGB → PNG via PIL. Reuses the convention used by
        ai/algorithms/bitmap.save_png."""
        from PIL import Image
        if bgr.ndim != 3 or bgr.shape[2] != 3 or bgr.size == 0:
            raise ValueError(f"can't save shape {bgr.shape}")
        rgb = np.ascontiguousarray(bgr[..., ::-1])
        Image.fromarray(rgb).save(str(path))

    def _append_index(self, path: Path, entry: Dict[str, Any]) -> None:
        """Append-only JSONL-ish index.json that lists every capture's
        metadata in order. Lets the editor enumerate captures without
        reading every PNG header."""
        existing: List[Dict[str, Any]] = []
        if path.exists():
            try:
                existing = json.loads(path.read_text(encoding="utf-8"))
                if not isinstance(existing, list):
                    existing = []
            except Exception:
                existing = []
        # Replace any existing entry with the same slug — captures
        # overwrite the asset on disk, the index should match.
        existing = [e for e in existing if e.get("slug") != entry.get("slug")]
        existing.append(entry)
        path.write_text(
            json.dumps(existing, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )


# ─────────────────────────────────────────────────────────────────────
# Promote dialog — checkbox list per kind, copies to global library
# ─────────────────────────────────────────────────────────────────────


class _PromoteDialog(QDialog):
    """Modal listing every per-bundle capture with a checkbox, plus a
    Promote/Cancel button row. On Accept, copies each checked entry into
    ``ai/captures/global/`` via :mod:`ai.captures.registry`.

    Items already present in the global library are pre-checked-out
    (label suffix " · already in global") so the user can intentionally
    re-promote to overwrite — that's a feature, not a footgun, since
    captures evolve as the user retunes them.
    """

    def __init__(self, parent_card, bundle: BotBundle) -> None:
        super().__init__(parent_card)
        self._bundle = bundle
        self._checks: List[tuple] = []      # [(checkbox, kind, src_path)]
        self.setWindowTitle("Promote captures to global library")
        self.setMinimumWidth(420)
        self.setSizeGripEnabled(True)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(t.SP_MD, t.SP_MD, t.SP_MD, t.SP_MD)
        outer.setSpacing(t.SP_MD)

        intro = QLabel(
            "Tick each capture to copy into the project-wide library. "
            "Promoted captures stay in this bundle too — promotion is "
            "a copy, not a move."
        )
        intro.setWordWrap(True)
        intro.setStyleSheet(
            f"color: {t.TEXT_TERTIARY}; font-size: {t.SIZE_SM}px;"
        )
        outer.addWidget(intro)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        list_host = QWidget()
        list_col = QVBoxLayout(list_host)
        list_col.setContentsMargins(0, 0, 0, 0)
        list_col.setSpacing(t.SP_SM)

        # Existing global slugs (per kind) so we can mark duplicates.
        try:
            global_color_slugs = {
                p.stem for p in global_captures.list_global("colors")
            }
        except Exception:
            global_color_slugs = set()
        try:
            global_snapshot_slugs = {
                p.stem for p in global_captures.list_global("snapshots")
            }
        except Exception:
            global_snapshot_slugs = set()
        try:
            global_recording_slugs = {
                p.name for p in global_captures.list_global("recordings")
            }
        except Exception:
            global_recording_slugs = set()
        try:
            global_dtm_slugs = {
                p.stem for p in global_captures.list_global("dtms")
            }
        except Exception:
            global_dtm_slugs = set()
        try:
            global_roi_slugs = {
                p.stem for p in global_captures.list_global("rois")
            }
        except Exception:
            global_roi_slugs = set()

        def _section(title: str, items: list, kind: str, slug_of) -> None:
            head = QLabel(title)
            head.setStyleSheet(
                f"color: {t.ACCENT}; "
                f"font-size: {t.SIZE_SM}px; "
                f"font-weight: 600; "
                f"text-transform: uppercase; "
                f"letter-spacing: 1px;"
            )
            list_col.addWidget(head)
            if not items:
                empty = QLabel("(none yet)")
                empty.setStyleSheet(
                    f"color: {t.TEXT_TERTIARY}; "
                    f"font-size: {t.SIZE_SM}px; "
                    f"padding-left: 12px;"
                )
                list_col.addWidget(empty)
                return
            for item in items:
                slug = slug_of(item)
                if kind == "color":
                    already = slug in global_color_slugs
                elif kind == "snapshot":
                    already = slug in global_snapshot_slugs
                elif kind == "dtm":
                    already = slug in global_dtm_slugs
                elif kind == "roi":
                    already = slug in global_roi_slugs
                else:
                    already = slug in global_recording_slugs
                label = slug + (
                    "  · already in global" if already else ""
                )
                cb = QCheckBox(label)
                cb.setStyleSheet(f"font-family: {t.FONT_MONO};")
                cb.setChecked(False)
                list_col.addWidget(cb)
                self._checks.append((cb, kind, item))

        _section(
            "Colours", bundle.list_colors(),
            "color", lambda p: p.stem,
        )
        _section(
            "Snapshots", bundle.list_snapshots(),
            "snapshot", lambda p: p.stem,
        )
        _section(
            "DTM templates", bundle.list_dtms(),
            "dtm", lambda p: p.stem,
        )
        _section(
            "Search ROIs", bundle.list_rois(),
            "roi", lambda p: p.stem,
        )
        _section(
            "Recordings", bundle.list_recordings(),
            "recording", lambda p: p.name,
        )

        list_col.addStretch(1)
        scroll.setWidget(list_host)
        outer.addWidget(scroll, 1)

        btns = QDialogButtonBox(
            QDialogButtonBox.Ok | QDialogButtonBox.Cancel, self,
        )
        btns.button(QDialogButtonBox.Ok).setText("★ Promote checked")
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        outer.addWidget(btns)

    def promote_selected(self) -> List[str]:
        """Run promotion for every checked row. Returns the list of
        promoted slugs (for the toast)."""
        promoted: List[str] = []
        for cb, kind, src in self._checks:
            if not cb.isChecked():
                continue
            try:
                if kind == "color":
                    global_captures.promote_color(src)
                    promoted.append(src.stem)
                elif kind == "snapshot":
                    global_captures.promote_snapshot(src)
                    promoted.append(src.stem)
                elif kind == "dtm":
                    global_captures.promote_dtm(src)
                    promoted.append(src.stem)
                elif kind == "roi":
                    global_captures.promote_roi(src)
                    promoted.append(src.stem)
                elif kind == "recording":
                    global_captures.promote_recording(src)
                    promoted.append(src.name)
            except Exception as e:
                # Surface the failure on the toast so the user knows
                # which one failed; keep going for the rest.
                from utils.logger import get_logger
                get_logger("ai_captures").warning(
                    "promote failed for %s/%s: %s", kind, src, e,
                )
        return promoted


# ─────────────────────────────────────────────────────────────────────
# Inline asset rows — replace the comma-separated inventory text with
# clickable rows so the user can see + delete captures without
# leaving the Captures card.
# ─────────────────────────────────────────────────────────────────────


class _KindHeader(QLabel):
    """Teal eyebrow that groups asset rows by kind."""

    def __init__(self, title: str) -> None:
        super().__init__(title)
        self.setStyleSheet(
            f"color: {t.ACCENT}; "
            f"font-size: {t.SIZE_SECTION_LABEL}px; "
            f"font-weight: 600; "
            f"text-transform: uppercase; "
            f"letter-spacing: 1px; "
            f"padding-top: 4px;"
        )


class _AssetRow(QFrame):
    """One bundle-asset row: thumbnail + slug + 🗑 delete.

    Thumbnails:
      - color:     filled swatch in the saved RGB
      - snapshot:  scaled PNG thumb
      - recording: first-frame thumb (frame_000.png)
      - item:      scaled PNG thumb (wiki cache)

    Delete asks for confirmation via the parent card's ``delete_asset``
    method, which also drops the slug from the kind's ``index.json``.
    """

    _THUMB_W = 48
    _THUMB_H = 32

    def __init__(self, card: "AICapturesSection", path: Path, kind: str):
        super().__init__()
        self._card = card
        self._path = path
        self._kind = kind
        self.setObjectName("asset-row")
        self.setStyleSheet(
            "QFrame#asset-row {"
            "  background: rgba(255, 255, 255, 0.03);"
            "  border-radius: 6px;"
            "}"
        )
        self.setFrameShape(QFrame.NoFrame)

        h = QHBoxLayout(self)
        h.setContentsMargins(t.SP_SM, 4, t.SP_SM, 4)
        h.setSpacing(t.SP_SM)

        # Thumbnail
        thumb = QLabel()
        thumb.setFixedSize(self._THUMB_W, self._THUMB_H)
        thumb.setStyleSheet(
            "background: #0a0a0a; border-radius: 4px;"
        )
        self._populate_thumb(thumb)
        h.addWidget(thumb)

        # Name + sub-line
        slug = path.stem if kind != "recording" else path.name
        name = QLabel(slug)
        name.setStyleSheet(
            f"color: {t.TEXT_PRIMARY}; "
            f"font-family: {t.FONT_MONO}; "
            f"font-size: {t.SIZE_BODY}px;"
        )
        sub = QLabel(self._sub_text())
        sub.setStyleSheet(
            f"color: {t.TEXT_TERTIARY}; "
            f"font-family: {t.FONT_MONO}; "
            f"font-size: {t.SIZE_SM}px;"
        )
        col = QVBoxLayout()
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(2)
        col.addWidget(name)
        col.addWidget(sub)
        wrap = QWidget()
        wrap.setLayout(col)
        h.addWidget(wrap, 1)

        # Delete button
        from PySide6.QtWidgets import QPushButton as _QPB
        del_btn = _QPB("🗑")
        del_btn.setCursor(Qt.PointingHandCursor)
        del_btn.setMinimumHeight(t.BUTTON_H - 4)
        del_btn.setMinimumWidth(t.BUTTON_H)
        del_btn.setToolTip(f"Delete this {kind} from the bundle")
        del_btn.clicked.connect(self._on_delete)
        h.addWidget(del_btn)

    # ── Thumbnail builders ──────────────────────────────────────
    def _populate_thumb(self, thumb: QLabel) -> None:
        from PySide6.QtGui import QColor, QImage, QPainter, QPen, QPixmap

        if self._kind == "color":
            try:
                data = json.loads(self._path.read_text(encoding="utf-8"))
                if not isinstance(data, dict):
                    return
                rgb = data.get("rgb") or [0, 0, 0]
                r, g, b = (int(v) & 0xFF for v in rgb)
                pix = QPixmap(self._THUMB_W, self._THUMB_H)
                pix.fill(QColor(r, g, b))
                thumb.setPixmap(pix)
            except Exception:
                pass
            return

        if self._kind == "roi":
            # Render a small rect outline on a transparent background so
            # the row visually reads as "this is a search rectangle".
            try:
                from .. import theme as _t
                pix = QPixmap(self._THUMB_W, self._THUMB_H)
                pix.fill(QColor("#0a0a0a"))
                p = QPainter(pix)
                p.setRenderHint(QPainter.Antialiasing, False)
                p.setPen(QPen(QColor(_t.ACCENT), 2))
                p.setBrush(Qt.NoBrush)
                # Inset 4px so the outline shows clearly.
                p.drawRect(4, 4, self._THUMB_W - 8, self._THUMB_H - 8)
                p.end()
                thumb.setPixmap(pix)
            except Exception:
                pass
            return

        # Image-based thumbnails.
        if self._kind in ("snapshot", "item"):
            img_path = self._path
        elif self._kind == "dtm":
            # DTM YAML lives next to its paired PNG — show that.
            img_path = self._path.with_suffix(".png")
            if not img_path.exists():
                return
        else:  # recording
            img_path = self._path / "frame_000.png"
            if not img_path.exists():
                return
        try:
            img = QImage(str(img_path))
            if img.isNull():
                return
            pix = QPixmap.fromImage(img).scaled(
                self._THUMB_W, self._THUMB_H,
                Qt.KeepAspectRatio, Qt.SmoothTransformation,
            )
            thumb.setPixmap(pix)
            thumb.setAlignment(Qt.AlignCenter)
        except Exception:
            pass

    def _sub_text(self) -> str:
        if self._kind == "color":
            try:
                data = json.loads(self._path.read_text(encoding="utf-8"))
                if isinstance(data, dict):
                    rgb = data.get("rgb") or [0, 0, 0]
                    r, g, b = (int(v) & 0xFF for v in rgb)
                    return f"#{r:02X}{g:02X}{b:02X}"
            except Exception:
                pass
            return "JSON"
        if self._kind == "recording":
            meta_path = self._path / "meta.json"
            if meta_path.exists():
                try:
                    meta = json.loads(meta_path.read_text(encoding="utf-8"))
                    fps = float(meta.get("fps") or 0)
                    count = int(meta.get("frame_count") or 0)
                    dur = float(meta.get("duration_s") or 0)
                    return f"{count} frames · {dur:.1f}s @ {fps:.0f} fps"
                except Exception:
                    pass
            return "directory"
        if self._kind == "dtm":
            # Read the YAML for a lightweight sub-line: # of points.
            try:
                import yaml as _yaml
                data = _yaml.safe_load(self._path.read_text(encoding="utf-8")) or {}
                pts = len(data.get("points") or []) + 1   # +1 for anchor
                return f"DTM · {pts} points"
            except Exception:
                return "DTM"
        if self._kind == "roi":
            try:
                data = json.loads(self._path.read_text(encoding="utf-8"))
                if isinstance(data, dict):
                    rect = data.get("rect") or [0, 0, 0, 0]
                    x, y, w, h = (int(v) for v in rect)
                    return f"{w}×{h} @ ({x}, {y})"
            except Exception:
                pass
            return "ROI"
        # snapshot / item
        try:
            kb = self._path.stat().st_size / 1024.0
            return f"PNG · {kb:.0f} KB"
        except Exception:
            return "PNG"

    def _on_delete(self) -> None:
        self._card.delete_asset(self._kind, self._path)
