"""Global capture library — browser card for ``ai/captures/global/``.

Sits below the Captures card on the AI page. Lists every capture that
has been promoted via the Captures card's "★ Promote…" button, so a
user authoring a new bot can see at a glance which Seren-spirit /
Brooch-proc / bank-chest reference assets exist and how to import them.

Each row offers:

- A thumbnail (colour swatch / snapshot first-frame / recording first
  frame) so the user recognises the asset visually.
- The slug + display name.
- A "📋 Copy import" button that puts the appropriate Python import
  line (``from ai.captures import color`` or ``snapshot`` or
  ``recording``) on the clipboard.
- A "🗑" delete button (with a confirm dialog).

The card refreshes when:

- It first mounts.
- The Captures card promotes new entries (via
  ``app.notify_global_captures_changed()``).
- The user clicks the header "Refresh" affordance.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Callable, List, Optional

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QImage, QPainter, QPixmap
from PySide6.QtWidgets import (
    QApplication, QFrame, QHBoxLayout, QLabel, QMessageBox, QPushButton,
    QSizePolicy, QVBoxLayout, QWidget,
)

from ai import captures as global_captures

from .. import theme as t
from ..widgets.card import Card


_THUMB_W = 56
_THUMB_H = 36


class AILibrarySection(Card):
    """The library browser for the global capture root."""

    def __init__(self, app) -> None:
        super().__init__("Global capture library")
        self.app = app

        # Header strip — count + refresh button.
        head_row = QWidget()
        head = QHBoxLayout(head_row)
        head.setContentsMargins(0, 0, 0, 0)
        head.setSpacing(t.SP_SM)

        self._summary = QLabel("")
        self._summary.setStyleSheet(
            f"color: {t.TEXT_SECONDARY}; font-size: {t.SIZE_SM}px;"
        )
        head.addWidget(self._summary)
        head.addStretch(1)

        refresh = QPushButton("⟳ Refresh")
        refresh.setMinimumHeight(t.BUTTON_H)
        refresh.setCursor(Qt.PointingHandCursor)
        refresh.clicked.connect(self.refresh)
        head.addWidget(refresh)

        self.add(head_row)

        # The content host gets cleared and rebuilt on every refresh —
        # keeps the layout simple and avoids stale rows when assets get
        # promoted/deleted out from under us.
        self._host = QWidget()
        self._host_col = QVBoxLayout(self._host)
        self._host_col.setContentsMargins(0, 0, 0, 0)
        self._host_col.setSpacing(t.SP_MD)
        self.add(self._host)

        # Foot hint — only the once.
        self._hint = QLabel(
            "Promoted from a bot bundle's Captures card. "
            "Bots reference these by name: "
            "from ai.captures import color, snapshot, recording."
        )
        self._hint.setWordWrap(True)
        self._hint.setStyleSheet(
            f"color: {t.TEXT_TERTIARY}; "
            f"font-size: {t.SIZE_SM}px; "
            f"padding-top: 4px;"
        )
        self.add(self._hint)

        self.refresh()
        # AIPageBody wires captures.globalCapturesChanged → self.refresh
        # so the library updates on every promote without manual reload.

    # ── Public ──────────────────────────────────────────────────
    def refresh(self) -> None:
        # Tear down the existing rows and rebuild — small dataset,
        # no point diffing.
        while self._host_col.count():
            item = self._host_col.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()

        try:
            colors = global_captures.list_global("colors")
            snaps = global_captures.list_global("snapshots")
            recs = global_captures.list_global("recordings")
            dtms = global_captures.list_global("dtms")
            rois = global_captures.list_global("rois")
        except Exception as e:
            self._summary.setText(f"⚠ library unavailable: {e}")
            return

        n_total = (
            len(colors) + len(snaps) + len(recs) + len(dtms) + len(rois)
        )
        if n_total == 0:
            self._summary.setText(
                "No promoted captures yet. Use the Captures card's "
                "★ Promote… button to start your library."
            )
            empty = QLabel("(library is empty)")
            empty.setAlignment(Qt.AlignCenter)
            empty.setStyleSheet(
                f"color: {t.TEXT_TERTIARY}; "
                f"font-size: {t.SIZE_SM}px; "
                f"padding: 24px;"
            )
            self._host_col.addWidget(empty)
            return

        self._summary.setText(
            f"colours: {len(colors)}  ·  "
            f"snapshots: {len(snaps)}  ·  "
            f"recordings: {len(recs)}  ·  "
            f"dtms: {len(dtms)}  ·  "
            f"rois: {len(rois)}"
        )

        if colors:
            self._host_col.addWidget(_GroupHeader("Colours"))
            for path in colors:
                self._host_col.addWidget(_ColorRow(self, path))

        if rois:
            self._host_col.addWidget(_GroupHeader("Search ROIs"))
            for path in rois:
                self._host_col.addWidget(_RoiRow(self, path))

        if snaps:
            self._host_col.addWidget(_GroupHeader("Snapshots"))
            for path in snaps:
                self._host_col.addWidget(_SnapshotRow(self, path))

        if dtms:
            self._host_col.addWidget(_GroupHeader("DTM templates"))
            for path in dtms:
                self._host_col.addWidget(_DtmRow(self, path))

        if recs:
            self._host_col.addWidget(_GroupHeader("Recordings"))
            for path in recs:
                self._host_col.addWidget(_RecordingRow(self, path))

    # ── Row callbacks ──────────────────────────────────────────
    def copy_to_clipboard(self, text: str, label: str) -> None:
        QApplication.clipboard().setText(text)
        try:
            self.app.toasts.post(
                f"📋 Copied to clipboard: {label}", kind="info",
            )
        except Exception:
            pass

    def confirm_delete(
        self, kind: str, name: str, deleter: Callable[[str], bool],
    ) -> None:
        reply = QMessageBox.question(
            self, f"Delete {kind}?",
            f"Permanently remove “{name}” from the global library?\n\n"
            f"The original capture in the bot bundle is unaffected.",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return
        ok = bool(deleter(name))
        if ok:
            try:
                self.app.toasts.post(
                    f"🗑 Deleted {kind}: {name}", kind="warn",
                )
            except Exception:
                pass
            self.refresh()


# ─────────────────────────────────────────────────────────────────
# Row widgets
# ─────────────────────────────────────────────────────────────────


class _GroupHeader(QLabel):
    """Teal eyebrow — same visual rhythm as Section labels."""

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


class _RowBase(QFrame):
    """Card-like row container with a left-edge thumbnail."""

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("library-row")
        self.setStyleSheet(
            "QFrame#library-row {"
            f"  background: {t.SURFACE_2 if hasattr(t, 'SURFACE_2') else '#1a1d23'};"
            f"  border-radius: 8px;"
            "}"
        )
        self.setFrameShape(QFrame.NoFrame)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        h = QHBoxLayout(self)
        h.setContentsMargins(t.SP_SM, t.SP_SM, t.SP_SM, t.SP_SM)
        h.setSpacing(t.SP_MD)
        self._row = h


class _ColorRow(_RowBase):
    def __init__(self, card: AILibrarySection, path: Path) -> None:
        super().__init__()
        self._card = card
        self._path = path
        slug = path.stem

        meta: dict = {}
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                meta = raw
        except Exception:
            pass
        rgb = meta.get("rgb") or [0, 0, 0]
        try:
            r, g, b = (int(v) & 0xFF for v in rgb)
        except Exception:
            r = g = b = 0
        hex_label = f"#{r:02X}{g:02X}{b:02X}"

        # Color swatch
        swatch = QLabel()
        pix = QPixmap(_THUMB_W, _THUMB_H)
        pix.fill(QColor(r, g, b))
        swatch.setPixmap(pix)
        swatch.setFixedSize(_THUMB_W, _THUMB_H)
        self._row.addWidget(swatch)

        # Text column
        txt = QVBoxLayout()
        txt.setContentsMargins(0, 0, 0, 0)
        txt.setSpacing(2)
        name = QLabel(slug)
        name.setStyleSheet(
            f"color: {t.TEXT_PRIMARY}; "
            f"font-family: {t.FONT_MONO}; "
            f"font-size: {t.SIZE_BODY}px;"
        )
        sub = QLabel(hex_label)
        sub.setStyleSheet(
            f"color: {t.TEXT_TERTIARY}; "
            f"font-family: {t.FONT_MONO}; "
            f"font-size: {t.SIZE_SM}px;"
        )
        txt.addWidget(name)
        txt.addWidget(sub)
        wrap = QWidget()
        wrap.setLayout(txt)
        self._row.addWidget(wrap, 1)

        # Action buttons
        copy_btn = QPushButton("📋 Copy import")
        copy_btn.setCursor(Qt.PointingHandCursor)
        copy_btn.setMinimumHeight(t.BUTTON_H)
        copy_btn.setToolTip(
            f"Copy the Python import line for this colour to clipboard."
        )
        copy_btn.clicked.connect(self._on_copy)
        self._row.addWidget(copy_btn)

        del_btn = QPushButton("🗑")
        del_btn.setCursor(Qt.PointingHandCursor)
        del_btn.setMinimumHeight(t.BUTTON_H)
        del_btn.setMinimumWidth(t.BUTTON_H)
        del_btn.setToolTip("Remove from global library")
        del_btn.clicked.connect(self._on_delete)
        self._row.addWidget(del_btn)

    def _on_copy(self) -> None:
        slug = self._path.stem
        line = (
            f"from ai.captures import color\n"
            f"{slug.upper()} = color({slug!r})"
        )
        self._card.copy_to_clipboard(line, slug)

    def _on_delete(self) -> None:
        slug = self._path.stem
        self._card.confirm_delete(
            "colour", slug, global_captures.delete_color,
        )


class _SnapshotRow(_RowBase):
    def __init__(self, card: AILibrarySection, path: Path) -> None:
        super().__init__()
        self._card = card
        self._path = path
        slug = path.stem

        thumb = QLabel()
        thumb.setFixedSize(_THUMB_W, _THUMB_H)
        thumb.setStyleSheet(
            "background: #0a0a0a; border-radius: 4px;"
        )
        try:
            img = QImage(str(path))
            if not img.isNull():
                pix = QPixmap.fromImage(img).scaled(
                    _THUMB_W, _THUMB_H,
                    Qt.KeepAspectRatio, Qt.SmoothTransformation,
                )
                thumb.setPixmap(pix)
                thumb.setAlignment(Qt.AlignCenter)
        except Exception:
            pass
        self._row.addWidget(thumb)

        txt = QVBoxLayout()
        txt.setContentsMargins(0, 0, 0, 0)
        txt.setSpacing(2)
        name = QLabel(slug)
        name.setStyleSheet(
            f"color: {t.TEXT_PRIMARY}; "
            f"font-family: {t.FONT_MONO}; "
            f"font-size: {t.SIZE_BODY}px;"
        )
        try:
            size = path.stat().st_size
            size_kb = size / 1024.0
            sub = QLabel(f"PNG · {size_kb:.0f} KB")
        except Exception:
            sub = QLabel("PNG")
        sub.setStyleSheet(
            f"color: {t.TEXT_TERTIARY}; "
            f"font-family: {t.FONT_MONO}; "
            f"font-size: {t.SIZE_SM}px;"
        )
        txt.addWidget(name)
        txt.addWidget(sub)
        wrap = QWidget()
        wrap.setLayout(txt)
        self._row.addWidget(wrap, 1)

        copy_btn = QPushButton("📋 Copy import")
        copy_btn.setCursor(Qt.PointingHandCursor)
        copy_btn.setMinimumHeight(t.BUTTON_H)
        copy_btn.clicked.connect(self._on_copy)
        self._row.addWidget(copy_btn)

        del_btn = QPushButton("🗑")
        del_btn.setCursor(Qt.PointingHandCursor)
        del_btn.setMinimumHeight(t.BUTTON_H)
        del_btn.setMinimumWidth(t.BUTTON_H)
        del_btn.clicked.connect(self._on_delete)
        self._row.addWidget(del_btn)

    def _on_copy(self) -> None:
        slug = self._path.stem
        line = (
            f"from ai.captures import snapshot\n"
            f"{slug.upper()}_REF = snapshot({slug!r})"
        )
        self._card.copy_to_clipboard(line, slug)

    def _on_delete(self) -> None:
        self._card.confirm_delete(
            "snapshot", self._path.stem,
            global_captures.delete_snapshot,
        )


class _RecordingRow(_RowBase):
    def __init__(self, card: AILibrarySection, path: Path) -> None:
        super().__init__()
        self._card = card
        self._path = path
        slug = path.name

        thumb = QLabel()
        thumb.setFixedSize(_THUMB_W, _THUMB_H)
        thumb.setStyleSheet("background: #0a0a0a; border-radius: 4px;")
        # Use frame_000.png as the cover image.
        first_frame = path / "frame_000.png"
        if first_frame.exists():
            try:
                img = QImage(str(first_frame))
                if not img.isNull():
                    pix = QPixmap.fromImage(img).scaled(
                        _THUMB_W, _THUMB_H,
                        Qt.KeepAspectRatio, Qt.SmoothTransformation,
                    )
                    thumb.setPixmap(pix)
                    thumb.setAlignment(Qt.AlignCenter)
            except Exception:
                pass
        self._row.addWidget(thumb)

        txt = QVBoxLayout()
        txt.setContentsMargins(0, 0, 0, 0)
        txt.setSpacing(2)
        name = QLabel(slug)
        name.setStyleSheet(
            f"color: {t.TEXT_PRIMARY}; "
            f"font-family: {t.FONT_MONO}; "
            f"font-size: {t.SIZE_BODY}px;"
        )
        # Frame count + duration from meta.json.
        meta_path = path / "meta.json"
        info = "directory"
        if meta_path.exists():
            try:
                meta = json.loads(meta_path.read_text(encoding="utf-8"))
                fps = float(meta.get("fps") or 0)
                count = int(meta.get("frame_count") or 0)
                dur = float(meta.get("duration_s") or 0)
                info = f"{count} frames · {dur:.1f}s @ {fps:.0f} fps"
            except Exception:
                pass
        sub = QLabel(info)
        sub.setStyleSheet(
            f"color: {t.TEXT_TERTIARY}; "
            f"font-family: {t.FONT_MONO}; "
            f"font-size: {t.SIZE_SM}px;"
        )
        txt.addWidget(name)
        txt.addWidget(sub)
        wrap = QWidget()
        wrap.setLayout(txt)
        self._row.addWidget(wrap, 1)

        copy_btn = QPushButton("📋 Copy import")
        copy_btn.setCursor(Qt.PointingHandCursor)
        copy_btn.setMinimumHeight(t.BUTTON_H)
        copy_btn.clicked.connect(self._on_copy)
        self._row.addWidget(copy_btn)

        del_btn = QPushButton("🗑")
        del_btn.setCursor(Qt.PointingHandCursor)
        del_btn.setMinimumHeight(t.BUTTON_H)
        del_btn.setMinimumWidth(t.BUTTON_H)
        del_btn.clicked.connect(self._on_delete)
        self._row.addWidget(del_btn)

    def _on_copy(self) -> None:
        slug = self._path.name
        line = (
            f"from ai.captures import recording\n"
            f"{slug.upper()}_DIR = recording({slug!r})"
        )
        self._card.copy_to_clipboard(line, slug)

    def _on_delete(self) -> None:
        self._card.confirm_delete(
            "recording", self._path.name,
            global_captures.delete_recording,
        )


class _DtmRow(_RowBase):
    def __init__(self, card: AILibrarySection, path: Path) -> None:
        super().__init__()
        self._card = card
        self._path = path
        slug = path.stem

        thumb = QLabel()
        thumb.setFixedSize(_THUMB_W, _THUMB_H)
        thumb.setStyleSheet("background: #0a0a0a; border-radius: 4px;")
        # Paired PNG sits next to the YAML; use it as the thumbnail.
        png_path = path.with_suffix(".png")
        if png_path.exists():
            try:
                img = QImage(str(png_path))
                if not img.isNull():
                    pix = QPixmap.fromImage(img).scaled(
                        _THUMB_W, _THUMB_H,
                        Qt.KeepAspectRatio, Qt.SmoothTransformation,
                    )
                    thumb.setPixmap(pix)
                    thumb.setAlignment(Qt.AlignCenter)
            except Exception:
                pass
        self._row.addWidget(thumb)

        txt = QVBoxLayout()
        txt.setContentsMargins(0, 0, 0, 0)
        txt.setSpacing(2)
        name = QLabel(slug)
        name.setStyleSheet(
            f"color: {t.TEXT_PRIMARY}; "
            f"font-family: {t.FONT_MONO}; "
            f"font-size: {t.SIZE_BODY}px;"
        )
        # Read YAML for a quick "N points" sub-line.
        info = "DTM"
        try:
            import yaml as _yaml
            data = _yaml.safe_load(path.read_text(encoding="utf-8")) or {}
            pts = len(data.get("points") or []) + 1
            info = f"DTM · {pts} points"
        except Exception:
            pass
        sub = QLabel(info)
        sub.setStyleSheet(
            f"color: {t.TEXT_TERTIARY}; "
            f"font-family: {t.FONT_MONO}; "
            f"font-size: {t.SIZE_SM}px;"
        )
        txt.addWidget(name)
        txt.addWidget(sub)
        wrap = QWidget()
        wrap.setLayout(txt)
        self._row.addWidget(wrap, 1)

        copy_btn = QPushButton("📋 Copy import")
        copy_btn.setCursor(Qt.PointingHandCursor)
        copy_btn.setMinimumHeight(t.BUTTON_H)
        copy_btn.clicked.connect(self._on_copy)
        self._row.addWidget(copy_btn)

        del_btn = QPushButton("🗑")
        del_btn.setCursor(Qt.PointingHandCursor)
        del_btn.setMinimumHeight(t.BUTTON_H)
        del_btn.setMinimumWidth(t.BUTTON_H)
        del_btn.clicked.connect(self._on_delete)
        self._row.addWidget(del_btn)

    def _on_copy(self) -> None:
        slug = self._path.stem
        line = (
            f"from ai.captures import dtm\n"
            f"{slug.upper()} = dtm({slug!r})"
        )
        self._card.copy_to_clipboard(line, slug)

    def _on_delete(self) -> None:
        self._card.confirm_delete(
            "dtm", self._path.stem,
            global_captures.delete_dtm,
        )


class _RoiRow(_RowBase):
    def __init__(self, card: AILibrarySection, path: Path) -> None:
        super().__init__()
        self._card = card
        self._path = path
        slug = path.stem

        # Outline rect thumbnail to convey "this is a search rectangle".
        thumb = QLabel()
        thumb.setFixedSize(_THUMB_W, _THUMB_H)
        thumb.setStyleSheet("background: #0a0a0a; border-radius: 4px;")
        try:
            from PySide6.QtGui import QPainter, QPen
            pix = QPixmap(_THUMB_W, _THUMB_H)
            pix.fill(QColor("#0a0a0a"))
            p = QPainter(pix)
            p.setRenderHint(QPainter.Antialiasing, False)
            p.setPen(QPen(QColor(t.ACCENT), 2))
            p.setBrush(Qt.NoBrush)
            p.drawRect(4, 4, _THUMB_W - 8, _THUMB_H - 8)
            p.end()
            thumb.setPixmap(pix)
            thumb.setAlignment(Qt.AlignCenter)
        except Exception:
            pass
        self._row.addWidget(thumb)

        # Read rect for the sub-line.
        info = "ROI"
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                rect = data.get("rect") or [0, 0, 0, 0]
                x, y, w, h = (int(v) for v in rect)
                info = f"{w}×{h} @ ({x}, {y})"
        except Exception:
            pass

        txt = QVBoxLayout()
        txt.setContentsMargins(0, 0, 0, 0)
        txt.setSpacing(2)
        name = QLabel(slug)
        name.setStyleSheet(
            f"color: {t.TEXT_PRIMARY}; "
            f"font-family: {t.FONT_MONO}; "
            f"font-size: {t.SIZE_BODY}px;"
        )
        sub = QLabel(info)
        sub.setStyleSheet(
            f"color: {t.TEXT_TERTIARY}; "
            f"font-family: {t.FONT_MONO}; "
            f"font-size: {t.SIZE_SM}px;"
        )
        txt.addWidget(name)
        txt.addWidget(sub)
        wrap = QWidget()
        wrap.setLayout(txt)
        self._row.addWidget(wrap, 1)

        copy_btn = QPushButton("📋 Copy import")
        copy_btn.setCursor(Qt.PointingHandCursor)
        copy_btn.setMinimumHeight(t.BUTTON_H)
        copy_btn.clicked.connect(self._on_copy)
        self._row.addWidget(copy_btn)

        del_btn = QPushButton("🗑")
        del_btn.setCursor(Qt.PointingHandCursor)
        del_btn.setMinimumHeight(t.BUTTON_H)
        del_btn.setMinimumWidth(t.BUTTON_H)
        del_btn.clicked.connect(self._on_delete)
        self._row.addWidget(del_btn)

    def _on_copy(self) -> None:
        slug = self._path.stem
        line = (
            f"from ai.captures import roi\n"
            f"{slug.upper()} = roi({slug!r})"
        )
        self._card.copy_to_clipboard(line, slug)

    def _on_delete(self) -> None:
        self._card.confirm_delete(
            "roi", self._path.stem,
            global_captures.delete_roi,
        )
