"""Log panel — tabbed widget that combines a free-text message log and
a tree-structured per-tick block-I/O inspector.

The two tabs consume the same runtime signals (from
:class:`rs3vision_studio.graph.runtime.RuntimeController`):

    log(str)              → Messages tab appends the string
    tick_started(int)     → Block I/O tab opens a new tick group
    block_executed(dict)  → Block I/O tab appends a block entry to the
                            current tick group
"""

from __future__ import annotations

from typing import Any, Dict

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QCheckBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSpinBox,
    QTabWidget,
    QTextBrowser,
    QTextEdit,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)


# ─────────────────────────────────────────────────────────────────
# Messages tab — plain scrolling log
# ─────────────────────────────────────────────────────────────────


class _MessagesView(QWidget):
    # Emitted when the user clicks an `rsv-help://<tab>[/<anchor>]` link.
    help_link_clicked = Signal(str, str)  # (tab, anchor_or_empty)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        # QTextBrowser supports rich HTML + link clicks — we use HTML
        # links in error messages so users can jump straight to help.
        self._text = QTextBrowser()
        self._text.setReadOnly(True)
        self._text.setOpenLinks(False)  # we intercept
        self._text.anchorClicked.connect(self._on_link)
        self._text.setStyleSheet(
            "QTextBrowser { background-color: #111; color: #ddd; "
            "font-family: Consolas, 'Courier New', monospace; font-size: 11px; }"
            "a { color: #6bc; }"
        )
        layout.addWidget(self._text)

        bar = QHBoxLayout()
        self._autoscroll = QCheckBox("Auto-scroll")
        self._autoscroll.setChecked(True)
        bar.addWidget(self._autoscroll)
        clear = QPushButton("Clear")
        clear.clicked.connect(self._text.clear)
        bar.addWidget(clear)
        bar.addStretch(1)
        layout.addLayout(bar)

    def append(self, msg: str) -> None:
        # Escape HTML then auto-link known error tokens.
        safe = _escape_html(msg)
        enriched = _inject_help_links(safe)
        self._text.append(enriched)
        if self._autoscroll.isChecked():
            sb = self._text.verticalScrollBar()
            sb.setValue(sb.maximum())

    def _on_link(self, url) -> None:
        text = url.toString()
        if not text.startswith("rsv-help://"):
            # External link — just ignore (we could open browser later).
            return
        rest = text[len("rsv-help://"):]
        if "/" in rest:
            tab, anchor = rest.split("/", 1)
        else:
            tab, anchor = rest, ""
        self.help_link_clicked.emit(tab, anchor)


# ─────────────────────────────────────────────────────────────────
# Error-token → help-link enrichment
# ─────────────────────────────────────────────────────────────────


def _escape_html(s: str) -> str:
    return (
        s.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


# Map of (token-to-match, visible-link-label, help-url-tail).
# Keyed on exact case-insensitive substrings that only appear in known
# error / warn lines.
_LINK_RULES = [
    ("graph is empty", "graph is empty",          "Troubleshooting"),
    ("no flow.on_start",                  "no On Start node",         "Troubleshooting"),
    ("no incoming trigger edge",          "capture not wired",        "Troubleshooting"),
    ("no vision.capture",                 "missing Capture Screen",   "Troubleshooting"),
    ("font_path is empty",                "font not set",             "Troubleshooting"),
    ("bitmap_path is empty",              "bitmap not set",           "DTM + Bitmap"),
    ("template_path is empty",            "DTM template not set",     "DTM + Bitmap"),
    ("backend not ready",                 "backend unavailable",      "Troubleshooting"),
    ("grab failed",                       "capture error",            "Troubleshooting"),
]


def _inject_help_links(html: str) -> str:
    """Scan `html` for known error tokens and wrap them in help links."""
    for token, label, tab in _LINK_RULES:
        # Case-insensitive substring search on the plain text body.
        lower = html.lower()
        start = lower.find(token.lower())
        if start == -1:
            continue
        end = start + len(token)
        # Slice + wrap.
        link = (
            f'<a href="rsv-help://{tab}">'
            f'{html[start:end]}  <i>[→ help: {label}]</i></a>'
        )
        html = html[:start] + link + html[end:]
    return html


# ─────────────────────────────────────────────────────────────────
# Block I/O tab — per-tick tree view
# ─────────────────────────────────────────────────────────────────


class _BlockIoView(QWidget):
    MAX_TICKS = 20  # keep the last N ticks; older are discarded

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)

        bar = QHBoxLayout()
        bar.addWidget(QLabel("Keep last"))
        self._spin = QSpinBox()
        self._spin.setRange(1, 200)
        self._spin.setValue(self.MAX_TICKS)
        self._spin.setSuffix(" ticks")
        bar.addWidget(self._spin)
        self._auto_expand = QCheckBox("Expand newest")
        self._auto_expand.setChecked(True)
        bar.addWidget(self._auto_expand)
        clear = QPushButton("Clear")
        clear.clicked.connect(self._clear)
        bar.addWidget(clear)
        bar.addStretch(1)
        layout.addLayout(bar)

        self._tree = QTreeWidget()
        self._tree.setHeaderLabels(["Block / field", "Value", "Elapsed"])
        self._tree.header().setStretchLastSection(False)
        self._tree.setColumnWidth(0, 260)
        self._tree.setColumnWidth(1, 360)
        self._tree.setUniformRowHeights(False)
        self._tree.setFont(QFont("Consolas", 9))
        layout.addWidget(self._tree)

        self._current_tick_item: QTreeWidgetItem | None = None
        # Defer UI updates to a small batch on a timer so high-tick-rate
        # scripts don't pin the GUI thread. Items are queued and flushed
        # at ~30 Hz.
        self._pending: list[tuple] = []
        self._flush_timer = QTimer(self)
        self._flush_timer.setInterval(35)
        self._flush_timer.timeout.connect(self._flush)
        self._flush_timer.start()

    # ── public slots ────────────────────────────────────
    def on_tick_started(self, tick: int) -> None:
        self._pending.append(("tick", tick))

    def on_block_executed(self, info: Dict[str, Any]) -> None:
        self._pending.append(("block", info))

    # ── flush queued updates ────────────────────────────
    def _flush(self) -> None:
        if not self._pending:
            return
        items = self._pending
        self._pending = []
        for kind, data in items:
            if kind == "tick":
                self._start_tick(data)
            else:
                self._append_block(data)
        self._trim()

    def _start_tick(self, tick: int) -> None:
        item = QTreeWidgetItem([f"Tick {tick}", "", ""])
        item.setFirstColumnSpanned(False)
        font = QFont("Consolas", 9)
        font.setBold(True)
        item.setFont(0, font)
        item.setForeground(0, Qt.GlobalColor.gray)
        self._tree.addTopLevelItem(item)
        # Close the previous tick node, auto-expand the new one.
        if self._current_tick_item is not None:
            self._current_tick_item.setExpanded(False)
        if self._auto_expand.isChecked():
            item.setExpanded(True)
        self._current_tick_item = item

    def _append_block(self, info: Dict[str, Any]) -> None:
        parent = self._current_tick_item
        if parent is None:
            # Tick signal missed — create an anonymous tick container.
            self._start_tick(0)
            parent = self._current_tick_item
        identifier = info.get("identifier", "?")
        node_id = info.get("node_id", "")
        elapsed = info.get("elapsed_ms", 0.0)
        row = QTreeWidgetItem(
            parent,
            [f"{identifier}  [{node_id}]", "", f"{elapsed:.2f} ms"],
        )
        # Sub-rows: params, inputs, outputs.
        _add_kv_group(row, "params", info.get("params"))
        _add_kv_group(row, "inputs", info.get("inputs"))
        _add_kv_group(row, "outputs", info.get("outputs"))

    def _trim(self) -> None:
        max_ticks = self._spin.value()
        while self._tree.topLevelItemCount() > max_ticks:
            self._tree.takeTopLevelItem(0)

    def _clear(self) -> None:
        self._tree.clear()
        self._current_tick_item = None


def _add_kv_group(parent: QTreeWidgetItem, title: str, payload: Any) -> None:
    if not payload:
        return
    group = QTreeWidgetItem(parent, [title, "", ""])
    group.setForeground(0, Qt.GlobalColor.darkCyan)
    if not isinstance(payload, dict):
        QTreeWidgetItem(group, ["", _short_repr(payload), ""])
        return
    for k, v in payload.items():
        QTreeWidgetItem(group, [str(k), _short_repr(v), ""])


def _short_repr(value: Any, limit: int = 120) -> str:
    """Compact, safe repr that truncates long values (numpy arrays, lists)."""
    try:
        import numpy as np
        if isinstance(value, np.ndarray):
            return f"ndarray{list(value.shape)} dtype={value.dtype}"
    except Exception:
        pass
    if isinstance(value, (list, tuple)):
        n = len(value)
        if n <= 3:
            inner = ", ".join(_short_repr(v, limit=32) for v in value)
            return f"[{inner}]" if isinstance(value, list) else f"({inner})"
        head = ", ".join(_short_repr(v, limit=32) for v in value[:2])
        return f"[{head}, … {n} items]" if isinstance(value, list) else f"({head}, … {n} items)"
    if isinstance(value, dict):
        n = len(value)
        if n == 0:
            return "{}"
        return f"{{… {n} key(s)}}"
    s = repr(value)
    return s if len(s) <= limit else s[: limit - 1] + "…"


# ─────────────────────────────────────────────────────────────────
# Composite panel
# ─────────────────────────────────────────────────────────────────


class LogPanel(QTabWidget):
    """Bottom dock content — two tabs over the same runtime signals."""

    # Emitted when a clickable help link in the Messages tab is clicked.
    help_link_clicked = Signal(str, str)  # (tab_label, anchor_or_empty)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._messages = _MessagesView()
        self._blockio = _BlockIoView()
        self.addTab(self._messages, "Messages")
        self.addTab(self._blockio, "Block I/O")
        # Forward the messages view's help-link signal upward.
        self._messages.help_link_clicked.connect(self.help_link_clicked)

    # ── public slots (wired by Studio app) ──────────────
    def append_message(self, msg: str) -> None:
        self._messages.append(msg)

    def on_tick_started(self, tick: int) -> None:
        self._blockio.on_tick_started(tick)

    def on_block_executed(self, info: Dict[str, Any]) -> None:
        self._blockio.on_block_executed(info)
