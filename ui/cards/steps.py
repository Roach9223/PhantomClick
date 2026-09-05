"""Step row builder, per-kind body rendering for the recorder list.

Each step row is a self-contained card with:
- Header (kind label + reorder/duplicate/remove icon buttons)
- Kind-specific body (click area + delay + advanced expander, etc.)
- Optional advanced expander for shape/click-type tweaks

Track-step capture, color-step eyedropper, and loop target picking are
wired to the App's overlay/toast layer; the actual interactive overlays
are pending tasks E2/E3 (zone drawer + color picker), and they post a
toast warning until those land.

The builder keeps a per-step ``_advanced_open`` map so re-rendering the
list (which destroys + recreates rows) doesn't lose the open/closed state.
"""

from __future__ import annotations

import copy
import os
import shutil
from pathlib import Path
from typing import Callable, Optional

from PySide6.QtCore import QObject, Qt, QTimer, Signal
from PySide6.QtGui import QAction, QFontMetrics, QPixmap
from PySide6.QtWidgets import (
    QButtonGroup, QCheckBox, QComboBox, QFrame, QHBoxLayout, QLabel, QLineEdit,
    QMenu, QMessageBox, QPushButton, QRadioButton, QSizePolicy, QToolButton,
    QVBoxLayout, QWidget,
)

from modules.recorder import (
    CAPTURE_SPACE_PHYSICAL, KIND_CLICK, KIND_COLOR, KIND_KEY, KIND_LOOP,
    KIND_PAUSE, KIND_TRACK, RecorderStep, new_view_id,
    orphaned_template_paths,
)
from modules.key_timer import (
    display as combo_display, fire as fire_combo, parse_combo,
)

from utils.logger import get_logger
from ui.config_io import _config_dir, _templates_dir, save_config

from .. import icons, theme as t
from ..format import fmt_delay
from ..screen_utils import screen_at_dip, screen_physical_rect
from ..widgets.expander import Expander
from ..widgets.field import Field
from ..widgets.ios_switch import IOSSwitch
from ..widgets.key_chip import KeyChip
from ..widgets.lock_control import ZoneLockControl
from ..widgets.range_spin_slider import RangeSpinSlider
from ..widgets.section import Section


_log = get_logger()


_MOD_KEYS = ("ctrl", "shift", "alt")
_MOD_LABELS = {"ctrl": "Ctrl", "shift": "Shift", "alt": "Alt"}
# pynput sends "ctrl_l" / "shift_r" / etc.; collapse to canonical names so a
# captured modifier matches our toggle keys.
_MOD_ALIASES = {
    "ctrl_l": "ctrl", "ctrl_r": "ctrl",
    "shift_l": "shift", "shift_r": "shift",
    "alt_l": "alt", "alt_r": "alt", "alt_gr": "alt",
    "cmd_l": "cmd", "cmd_r": "cmd", "cmd": "cmd",
}
_KEY_CAPTURE_TIMEOUT_MS = 8000


def _split_combo(combo: str) -> tuple[set[str], str]:
    """Parse a stored combo string into (selected modifier toggles, base).

    Tolerant: accepts whitespace tokens (spacebar) and lowercases everything.
    Returns ({}, "") for an empty/malformed combo so the UI starts blank.
    """
    if not combo:
        return (set(), "")
    parts: list[str] = []
    for p in combo.split("+"):
        if p and not p.strip():
            parts.append("space")
        elif p.strip():
            parts.append(p.strip().lower())
    mods: set[str] = set()
    base = ""
    for p in parts:
        canonical = _MOD_ALIASES.get(p, p)
        if canonical in _MOD_KEYS:
            mods.add(canonical)
        else:
            base = p  # last non-modifier wins
    return (mods, base)


def _join_combo(mods: set[str], base: str) -> str:
    """Build a canonical "ctrl+shift+f5" string from the UI state. Empty
    base → empty combo (a partial combo with no base is unrunnable)."""
    if not base:
        return ""
    ordered = [m for m in _MOD_KEYS if m in mods]
    return "+".join(ordered + [base])


def _pretty_base(base: str) -> str:
    """Display form of the base key for the KeyChip / chip text."""
    if not base:
        return ", "
    if len(base) == 1:
        return base.upper()
    if base.startswith("f") and base[1:].isdigit():
        return base.upper()
    return base.replace("_", " ").title()


class _ElidedLabel(QLabel):
    """Single-line label that elides on the right to whatever width the
    row gives it. The full text stays in the tooltip."""

    def __init__(self, text: str, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._full = text
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        self.setMinimumWidth(40)
        self._apply()

    def _apply(self) -> None:
        avail = max(0, self.width() - 2)
        fm = QFontMetrics(self.font())
        self.setText(fm.elidedText(self._full, Qt.ElideRight, avail) if avail > 20 else self._full)

    def resizeEvent(self, event):  # noqa: N802 (Qt name)
        super().resizeEvent(event)
        self._apply()

    def minimumSizeHint(self):  # noqa: N802 (Qt name)
        hint = super().minimumSizeHint()
        hint.setWidth(40)
        return hint


class _StepCard(QFrame):
    """A step's card. ``menu`` is the overflow menu the header builds;
    a right-click anywhere on the card pops it."""

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.menu: Optional[QMenu] = None

    def contextMenuEvent(self, event):  # noqa: N802 (Qt name)
        if self.menu is not None:
            self.menu.exec(event.globalPos())
            event.accept()
            return
        super().contextMenuEvent(event)


class _KeyCaptureBridge(QObject):
    """Thread-safe pipe from the pynput listener thread to the Qt main
    thread for key-step capture.

    ``HotkeyManager.capture_next``'s callback fires on the listener
    thread; touching Qt widgets from there is unsafe (silent corruption
    on Windows, crashes elsewhere). Emitting a Qt signal across threads
    is the canonical fix, Qt detects the thread mismatch and queues
    the slot call through the receiver's event loop. Each StepRowBuilder
    owns one bridge whose ``captured`` signal carries (step_id, key_name).
    """
    captured = Signal(str, str)


class StepRowBuilder:
    """Stateless-ish builder. Carries per-step UI state (advanced open map)
    so re-rendering the list doesn't lose collapse state."""

    def __init__(self, app):
        self.app = app
        # Keyed by step_id (not list index) so reorder / delete above a
        # step doesn't hand its open state to a neighbour.
        self._advanced_open: dict[str, bool] = {}
        # Body collapsibility, list-of-expanded semantics. step_id present
        # in this set = body visible; default = collapsed. Newly-added
        # steps get marked expanded via :meth:`mark_expanded` so the user
        # sees their controls immediately. Persisted to cfg so collapse
        # state survives launches.
        self._expanded: set[str] = set(
            app.cfg.get("recorder_expanded_steps", []) or []
        )
        # Per-step keyboard UI state. Keyed by step.step_id so re-rendering
        # the row (which destroys + recreates widgets) keeps the toggles
        # and chip in sync with the saved combo. Each entry holds the live
        # widget refs needed by the capture flow:
        #   {"chip": KeyChip, "btn": QPushButton, "checks": {mod: QCheckBox},
        #    "timer": QTimer | None, "lbl": QLabel}
        self._key_widgets: dict[str, dict] = {}
        # Lazy keyboard controller for the per-step "Test" button.
        self._test_kb_controller = None
        # Cross-thread bridge: the pynput listener (capture_next callback)
        # runs on its own thread; the Qt-side handler must run on the main
        # thread. Connecting via a signal lets Qt auto-pick QueuedConnection
        # so the emit is safe from any thread.
        self._key_bridge = _KeyCaptureBridge(parent=app if isinstance(
            app, QObject) else None)
        self._key_bridge.captured.connect(self._on_key_captured_main_thread)

    # -- Collapsibility helpers --------------------------------------------

    def is_expanded(self, step_id: str) -> bool:
        return step_id in self._expanded

    def set_expanded(self, step_id: str, expanded: bool) -> None:
        if expanded:
            self._expanded.add(step_id)
        else:
            self._expanded.discard(step_id)
        self.app.cfg["recorder_expanded_steps"] = sorted(self._expanded)
        save_config(self.app.cfg)

    def mark_expanded(self, step_id: str) -> None:
        """Convenience: expand a single step (used after on_add_*)."""
        self.set_expanded(step_id, True)

    def expand_only(self, step_id: str) -> None:
        """Expand ``step_id`` and collapse every other step, so a step
        picked from the deck's SEQUENCE panel is the one card open."""
        self._expanded = {step_id}
        self.app.cfg["recorder_expanded_steps"] = sorted(self._expanded)
        save_config(self.app.cfg)

    # -- Action row (Test + Clear, equal weight, divider above) ------------

    def _build_action_row(
        self,
        *,
        on_test: Optional[Callable[[], None]] = None,
        on_clear: Optional[Callable[[], None]] = None,
        clear_enabled: bool = True,
        test_label: str = "Test step",
        clear_label: str = "Clear",
    ) -> QWidget:
        """Trailing action row for step bodies. Two ghost buttons at equal
        weight (no competing visual hierarchy), preceded by a hairline
        divider so the row reads as separate from the body content."""
        wrap = QWidget()
        col = QVBoxLayout(wrap)
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(t.SP_SM)

        rule = QFrame()
        rule.setProperty("role", "row-divider")
        rule.setFixedHeight(1)
        col.addWidget(rule)

        row = QHBoxLayout()
        row.setSpacing(t.SP_SM)

        if on_test is not None:
            # Plain "Test step", was prefixed with ▶ which read as a
            # disclosure chevron rather than a play icon and confused the
            # button's affordance. The ghost-button shape already says
            # "click me" without an icon.
            test_btn = self.app.locker.register(QPushButton(test_label))
            test_btn.setProperty("variant", "ghost")
            test_btn.setMinimumHeight(t.BUTTON_H)
            test_btn.setCursor(Qt.PointingHandCursor)
            test_btn.clicked.connect(lambda _=False: on_test())
            row.addWidget(test_btn)

        if on_clear is not None:
            clear_btn = self.app.locker.register(QPushButton(clear_label))
            clear_btn.setProperty("variant", "ghost")
            clear_btn.setMinimumHeight(t.BUTTON_H)
            clear_btn.setCursor(Qt.PointingHandCursor)
            clear_btn.setEnabled(bool(clear_enabled))
            clear_btn.clicked.connect(lambda _=False: on_clear())
            row.addWidget(clear_btn)

        row.addStretch(1)
        col.addLayout(row)
        return wrap

    def _step_fallback_summary(self, step: RecorderStep) -> str:
        """When ``step.label`` is empty, return a short kind-specific
        identifier so the collapsed card row stays distinguishable. With
        many similar steps in a sequence (e.g. five unlabeled CLICKs at
        different coords), this is what makes the list scannable."""
        if step.kind == KIND_CLICK:
            if step.zone is None:
                return "unset"
            try:
                x1, y1, x2, y2 = step.zone.aabb()
                return f"({(x1 + x2) // 2}, {(y1 + y2) // 2})"
            except Exception:
                return "unset"
        if step.kind == KIND_TRACK:
            if not step.template_path:
                return "no template"
            from pathlib import Path
            return Path(step.template_path).stem
        if step.kind == KIND_COLOR:
            rgb = step.color_target_rgb
            if rgb is None:
                return "no color"
            return "#{:02x}{:02x}{:02x}".format(*rgb)
        if step.kind == KIND_KEY:
            return step.key_combo or "unbound"
        if step.kind == KIND_PAUSE:
            return f"{step.delay_min:.3f}–{step.delay_max:.3f} s"
        if step.kind == KIND_LOOP:
            for s in self.app._steps:
                if s.step_id == step.loop_target_step_id:
                    return f"to {s.label or s.kind}"
            return "loop target unset"
        return ""

    def _label_section(self, idx: int, step: RecorderStep) -> Section:
        """Standard 'Label' section, single text input, used by every
        step kind that supports human-readable labels (all except LOOP)."""
        section = Section("Label")
        edit = self.app.locker.register(QLineEdit(step.label or ""))
        edit.setPlaceholderText(
            "Optional label (e.g. 'Drop logs', 'Bank deposit')"
        )
        edit.setMaxLength(80)
        edit.editingFinished.connect(
            lambda i=idx, e=edit: self._on_label_change(i, e.text())
        )
        section.add(edit)
        return section

    def _details_expander(self, idx: int, step: RecorderStep, *,
                          resilience: bool = False) -> Expander:
        """Collapsed 'Details' block at the foot of a step body: the
        optional label and, for the poll-based kinds, the resilience
        (timeout) settings. Kept out of the way so a body opens on the
        target and the timing, which is what the user came to change."""
        parts = ["label", "resilience"] if resilience else ["label"]
        exp = Expander("Details", preview=", ".join(parts))
        body = QWidget()
        col = QVBoxLayout(body)
        col.setContentsMargins(0, t.SP_XS, 0, 0)
        col.setSpacing(t.SECTION_GAP)
        col.addWidget(self._label_section(idx, step))
        if resilience:
            col.addWidget(self._timeout_section(idx, step))
        exp.set_content(body)
        key = f"{step.step_id}:details"
        if self._advanced_open.get(key, False):
            exp.set_open(True)
        exp._toggle.clicked.connect(
            lambda k=key, e=exp: self._set_advanced_open(k, e.is_open())
        )
        return exp

    def _timeout_section(self, idx: int, step: RecorderStep) -> Section:
        """Per-step 'Resilience' section: timeout + on-timeout action for
        the poll-based kinds (Track, Color) that can stall on a target."""
        from PySide6.QtWidgets import QDoubleSpinBox

        section = Section(
            "Resilience",
            hint="auto-recovery for unattended runs",
        )
        row = QHBoxLayout()
        row.setSpacing(t.SP_MD)

        # Timeout column
        t_col = QVBoxLayout()
        t_col.setSpacing(4)
        t_lbl = QLabel("Timeout")
        t_lbl.setStyleSheet(
            f"color: {t.TEXT_PRIMARY}; "
            f"font-size: {t.SIZE_FIELD_LABEL}px; font-weight: 600;"
        )
        t_col.addWidget(t_lbl)
        spin = self.app.locker.register(QDoubleSpinBox())
        spin.setRange(0.0, 600.0)
        spin.setSingleStep(1.0)
        spin.setDecimals(1)
        spin.setSuffix(" s")
        spin.setSpecialValueText("off")
        spin.setValue(float(step.timeout_seconds))
        spin.setMaximumWidth(140)
        spin.setToolTip(
            "After this many seconds without finding the target, do the "
            "selected on-timeout action. 0 = wait forever (default)."
        )
        t_col.addWidget(spin)
        t_wrap = QWidget()
        t_wrap.setLayout(t_col)
        t_wrap.setMaximumWidth(160)
        row.addWidget(t_wrap)

        # On-timeout column
        a_col = QVBoxLayout()
        a_col.setSpacing(4)
        a_lbl = QLabel("On timeout")
        a_lbl.setStyleSheet(
            f"color: {t.TEXT_PRIMARY}; "
            f"font-size: {t.SIZE_FIELD_LABEL}px; font-weight: 600;"
        )
        a_col.addWidget(a_lbl)
        action = self.app.locker.register(QComboBox())
        action.addItem("Skip step", "skip")
        action.addItem("Stop engine", "stop")
        idx_default = 0 if (step.on_timeout or "skip") != "stop" else 1
        action.setCurrentIndex(idx_default)
        action.setEnabled(float(step.timeout_seconds) > 0.0)
        a_col.addWidget(action)
        a_wrap = QWidget()
        a_wrap.setLayout(a_col)
        row.addWidget(a_wrap, 1)

        # Wire interactions.
        def _on_spin(v: float, i: int = idx, a: QComboBox = action) -> None:
            self._on_timeout_seconds_change(i, v)
            a.setEnabled(v > 0.0)
        spin.valueChanged.connect(_on_spin)
        action.currentIndexChanged.connect(
            lambda _, a=action, i=idx: self._on_on_timeout_change(i, a.currentData())
        )
        section.addLayout(row)
        return section

    # -- Public entry ------------------------------------------------------

    def build_row(self, idx: int, refresh_cb: Callable[[], None]) -> QFrame:
        step = self.app._steps[idx]
        card = _StepCard()
        card.setObjectName("step-card")
        # Drives the QSS [expanded="true"] left-stripe rule so the editor
        # target is visually distinguishable from collapsed sibling steps.
        expanded_now = self.is_expanded(step.step_id)
        card.setProperty("expanded", "true" if expanded_now else "false")
        outer = QVBoxLayout(card)
        outer.setContentsMargins(t.SP_MD, t.SP_SM, t.SP_MD, t.SP_SM)
        outer.setSpacing(t.SP_SM)

        # Body lives in its own QWidget so the header chevron can toggle
        # visibility without disturbing the card's layout. SECTION_GAP
        # spacing between children gives named sections breathing room.
        body_widget = QWidget()
        body_layout = QVBoxLayout(body_widget)
        body_layout.setContentsMargins(0, 0, 0, 0)
        body_layout.setSpacing(t.SECTION_GAP)

        # Header row, chevron + title + actions. Header builder needs the
        # body widget so the chevron click can toggle visibility directly.
        outer.addLayout(self._build_header(idx, step, refresh_cb, body_widget, card))

        # Kind-specific body painted into body_layout (was outer).
        if step.kind == KIND_PAUSE:
            self._build_pause_body(body_layout, idx, step, refresh_cb)
        elif step.kind == KIND_LOOP:
            self._build_loop_body(body_layout, idx, step, refresh_cb)
        elif step.kind == KIND_TRACK:
            self._build_track_body(body_layout, idx, step, refresh_cb)
        elif step.kind == KIND_COLOR:
            self._build_color_body(body_layout, idx, step, refresh_cb)
        elif step.kind == KIND_KEY:
            self._build_key_body(body_layout, idx, step, refresh_cb)
        else:
            self._build_click_body(body_layout, idx, step, refresh_cb)

        body_widget.setVisible(expanded_now)
        outer.addWidget(body_widget)

        return card

    # -- Header (title + reorder/duplicate/remove) -------------------------

    def _build_header(self, idx: int, step: RecorderStep,
                      refresh_cb: Callable[[], None],
                      body_widget: QWidget,
                      card: QFrame) -> QHBoxLayout:
        kind_meta = {
            KIND_PAUSE: ("PAUSE", t.WARN),
            KIND_TRACK: ("TRACK", t.INFO),
            KIND_LOOP:  ("LOOP",  t.WARN),
            KIND_COLOR: ("COLOR", t.START),
            KIND_CLICK: ("CLICK", t.ACCENT),
            KIND_KEY:   ("KEY",   t.TEXT_PRIMARY),
        }
        kind_label, color = kind_meta.get(step.kind, ("", t.ACCENT))

        head = QHBoxLayout()
        head.setSpacing(t.SP_SM)

        # Chevron toggles the body. ▾ open / ▸ collapsed. icon variant so
        # it matches the trailing Up / Down / Delete buttons in style.
        expanded_now = self.is_expanded(step.step_id)
        chevron = QPushButton()
        chevron.setIcon(icons.icon("chevron-down" if expanded_now else "chevron-right"))
        chevron.setProperty("variant", "icon")
        chevron.setMaximumSize(t.ICON_BUTTON, t.ICON_BUTTON)
        chevron.setMinimumSize(t.ICON_BUTTON, t.ICON_BUTTON)
        chevron.setCursor(Qt.PointingHandCursor)
        chevron.setToolTip(
            "Collapse this step" if expanded_now else "Expand this step"
        )

        def _toggle(_checked=False, sid=step.step_id, btn=chevron,
                     body=body_widget, c=card):
            new_expanded = not body.isVisible()
            body.setVisible(new_expanded)
            btn.setIcon(icons.icon("chevron-down" if new_expanded else "chevron-right"))
            btn.setToolTip(
                "Collapse this step" if new_expanded else "Expand this step"
            )
            # Repaint the [expanded] QSS rule (left-stripe) on the card.
            c.setProperty("expanded", "true" if new_expanded else "false")
            c.style().unpolish(c)
            c.style().polish(c)
            self.set_expanded(sid, new_expanded)

        chevron.clicked.connect(_toggle)
        head.addWidget(chevron)

        # Step number reads as a quiet caption; the colored kind tag carries
        # the visual identity. Splitting them lets the kind colour ride
        # alone without smearing across the whole title.
        step_lbl = QLabel(f"Step {idx + 1}")
        step_lbl.setProperty("role", "hint")
        head.addWidget(step_lbl)

        kind_lbl = QLabel(kind_label)
        kind_lbl.setStyleSheet(
            f"color: {color}; font-family: {t.FONT_MONO}; "
            f"font-size: {t.SIZE_BODY}px; font-weight: 700; "
            f"letter-spacing: 1.2px;"
        )
        head.addWidget(kind_lbl)

        # Optional human-readable label rendered between the kind tag and
        # the warning indicator. Italic + secondary so the kind tag still
        # owns the visual identity. Elided so a long label can't push the
        # icon buttons off the row; full text remains in the tooltip.
        # Falls back to a kind-specific summary (coords / hex / combo /
        # delay range / loop target) when no user label is set, so
        # collapsed sibling steps stay distinguishable.
        label_text = (step.label or "").strip()
        if not label_text:
            label_text = self._step_fallback_summary(step)
            label_is_fallback = True
        else:
            label_is_fallback = False
        if label_text:
            label_lbl = _ElidedLabel(label_text)
            # Fallbacks render in tertiary tone (still visible but quieter
            # than a deliberate user label) so the user can tell at a
            # glance whether a step has been named.
            color = t.TEXT_TERTIARY if label_is_fallback else t.TEXT_SECONDARY
            label_lbl.setStyleSheet(
                f"color: {color}; font-style: italic; "
                f"font-family: {t.FONT_MONO}; "
                f"font-size: {t.SIZE_BODY}px;"
            )
            label_lbl.setToolTip(label_text)
            # Takes the slack in the row and elides, so a long label can
            # never push the switch and the menu off a narrow pane.
            head.addWidget(label_lbl, 1)

        # Inline error indicator, visible when the step is missing required
        # data so the user catches it BEFORE running the engine instead of
        # via a missed toast mid-run. The same predicate the engine uses to
        # decide "skip this step" (see Clicker._peek_recorder_step).
        problem = self._step_problem(step, idx)
        if problem:
            warn_lbl = QLabel()
            warn_lbl.setPixmap(icons.pixmap("alert", 14, t.WARN))
            warn_lbl.setFixedSize(14, 14)
            warn_lbl.setToolTip(problem)
            head.addWidget(warn_lbl)

        if not label_text:
            head.addStretch(1)

        # Per-step enable toggle. Disabled steps rotate past silently in
        # the engine (see Clicker._peek_recorder_step), same effect as
        # commenting the step out for testing, no need to delete +
        # recreate. Persists via the standard step JSON save.
        enable_switch = self.app.locker.register(IOSSwitch())
        enable_switch.setChecked(bool(getattr(step, "enabled", True)))
        enable_switch.setToolTip("Enable or pause this step (disabled steps are skipped at run time).")
        enable_switch.toggled.connect(
            lambda checked, i=idx: self._on_step_enabled_toggled(i, checked)
        )
        head.addWidget(enable_switch)

        # Reorder / duplicate / remove live behind one menu button so the
        # header stays a single line inside the editor pane.
        n_steps = len(self.app._steps)
        more = self.app.locker.register(QToolButton())
        more.setText("···")
        more.setObjectName("step-more-btn")
        more.setFixedSize(t.ICON_BUTTON, t.ICON_BUTTON)
        more.setCursor(Qt.PointingHandCursor)
        more.setToolTip("Move, duplicate or remove this step.")
        more.setPopupMode(QToolButton.InstantPopup)
        more.setStyleSheet(
            f"QToolButton#step-more-btn {{ background: {t.SURFACE_PANEL}; "
            f"color: {t.TEXT_SECONDARY}; border: 1px solid {t.BORDER}; "
            f"border-radius: {t.RADIUS_BUTTON}px; padding: 0; "
            f"font-size: {t.SIZE_LG}px; font-weight: 700; }}"
            f"QToolButton#step-more-btn::menu-indicator {{ image: none; width: 0; }}"
            f"QToolButton#step-more-btn:hover {{ background: {t.SURFACE_HIGH}; "
            f"color: {t.TEXT_PRIMARY}; border-color: {t.BORDER_STRONG}; }}"
        )
        menu = QMenu(more)
        for icon, text, handler, enabled in [
            ("arrow-up", "Move up", lambda: self._move(idx, -1, refresh_cb), idx > 0),
            ("arrow-down", "Move down", lambda: self._move(idx, +1, refresh_cb), idx < n_steps - 1),
            ("duplicate", "Duplicate", lambda: self._duplicate(idx, refresh_cb), True),
        ]:
            act = QAction(icons.icon(icon), text, menu)
            act.setEnabled(bool(enabled))
            act.triggered.connect(lambda _c=False, h=handler: h())
            menu.addAction(act)
        menu.addSeparator()
        rm = QAction(icons.icon("trash", 16, t.DANGER), "Remove step", menu)
        rm.triggered.connect(lambda _c=False: self._remove(idx, refresh_cb))
        menu.addAction(rm)
        more.setMenu(menu)
        head.addWidget(more)
        if isinstance(card, _StepCard):
            card.menu = menu
        return head

    # -- Pause body -------------------------------------------------------

    def _build_pause_body(self, layout: QVBoxLayout, idx: int, step: RecorderStep,
                          refresh_cb: Callable[[], None]) -> None:
        # WAIT
        wait_section = Section("Wait", hint="cursor still drifts during the wait")
        delay_lbl = QLabel(self._delay_text("Wait for", step))
        delay_lbl.setProperty("role", "body")
        wait_section.add(delay_lbl)
        rng = RangeSpinSlider(
            from_=0.01, to=300.0, steps=14990,
            init_min=step.delay_min, init_max=step.delay_max,
        )
        rng.valueChanged.connect(
            lambda lo, hi, i=idx, lbl=delay_lbl: self._on_delay_change(
                i, lo, hi, "Wait for", lbl,
            )
        )
        wait_section.add(rng)
        layout.addWidget(wait_section)
        layout.addWidget(self._details_expander(idx, step))

    # -- Click body -------------------------------------------------------

    def _build_click_body(self, layout: QVBoxLayout, idx: int, step: RecorderStep,
                          refresh_cb: Callable[[], None]) -> None:
        # CLICK TARGET, empty state shows the prominent CTA, configured
        # state demotes Pick to a small "Redraw" and surfaces the
        # captured rect as the section's primary content.
        target_section = Section("Click target")
        if step.zone is None:
            empty = QHBoxLayout()
            prompt = QLabel("No click area set")
            prompt.setProperty("role", "hint")
            empty.addWidget(prompt)
            empty.addStretch(1)
            pick_btn = self.app.locker.register(
                QPushButton("Pick click area")
            )
            pick_btn.setProperty("variant", "primary")
            pick_btn.setMinimumHeight(t.BUTTON_H_PRIMARY)
            pick_btn.setCursor(Qt.PointingHandCursor)
            pick_btn.clicked.connect(lambda: self._on_draw_step(idx))
            empty.addWidget(pick_btn)
            target_section.addLayout(empty)
        else:
            row = QHBoxLayout()
            data = QLabel(self._zone_summary(step))
            data.setStyleSheet(
                f"color: {t.TEXT_PRIMARY}; "
                f"font-family: {t.FONT_MONO}; "
                f"font-size: {t.SIZE_BODY}px;"
            )
            data.setWordWrap(True)
            row.addWidget(data, 1)
            redraw = self.app.locker.register(QPushButton("Redraw"))
            redraw.setIcon(icons.icon("redraw"))
            redraw.setProperty("variant", "ghost")
            redraw.setCursor(Qt.PointingHandCursor)
            redraw.clicked.connect(lambda: self._on_draw_step(idx))
            row.addWidget(redraw)
            target_section.addLayout(row)
            target_section.add(self._lock_row(idx, step))
        layout.addWidget(target_section)

        # TIMING: clicks-per-visit on one row, the delay slider under it.
        # Stacked, not side by side, so the section fits the editor pane.
        timing_section = Section("Timing")
        clicks_row = QHBoxLayout()
        clicks_row.setSpacing(t.SP_SM)
        clicks_lbl = QLabel("Clicks before the next step")
        clicks_lbl.setStyleSheet(
            f"color: {t.TEXT_PRIMARY}; "
            f"font-size: {t.SIZE_FIELD_LABEL}px; font-weight: 600;"
        )
        clicks_row.addWidget(clicks_lbl)
        clicks_row.addStretch(1)
        clicks_entry = self.app.locker.register(QLineEdit(str(int(step.click_count))))
        clicks_entry.setFixedWidth(88)
        clicks_entry.setAlignment(Qt.AlignCenter)
        clicks_entry.setProperty("role", "mono")
        clicks_entry.editingFinished.connect(
            lambda i=idx, e=clicks_entry: self._on_click_count_change(i, e.text())
        )
        clicks_row.addWidget(clicks_entry)
        timing_section.addLayout(clicks_row)

        delay_lbl = QLabel(self._delay_text("Delay between clicks", step))
        delay_lbl.setStyleSheet(
            f"color: {t.TEXT_PRIMARY}; "
            f"font-size: {t.SIZE_FIELD_LABEL}px; font-weight: 600;"
        )
        timing_section.add(delay_lbl)
        rng = RangeSpinSlider(
            from_=0.01, to=120.0, steps=11990,
            init_min=step.delay_min, init_max=step.delay_max,
        )
        rng.valueChanged.connect(
            lambda lo, hi, i=idx, lbl=delay_lbl: self._on_delay_change(
                i, lo, hi, "Delay between clicks", lbl,
            )
        )
        timing_section.add(rng)
        layout.addWidget(timing_section)

        # ADVANCED expander (collapsed by default, with content preview).
        is_open = self._advanced_open.get(step.step_id, False)
        adv = Expander("Details", preview="label, shape, button, mode")
        adv_body = QWidget()
        adv_layout = QVBoxLayout(adv_body)
        adv_layout.setContentsMargins(0, t.SP_XS, 0, 0)
        adv_layout.setSpacing(t.SP_SM)
        adv_layout.addWidget(self._label_section(idx, step))
        adv_layout.addSpacing(t.SP_XS)
        self._build_step_advanced(adv_layout, idx, step)
        adv.set_content(adv_body)
        if is_open:
            adv.set_open(True)
        adv._toggle.clicked.connect(
            lambda sid=step.step_id, e=adv: self._set_advanced_open(sid, e.is_open())
        )
        layout.addWidget(adv)

        # ACTION ROW, Test + Clear, equal weight, divider above.
        layout.addWidget(self._build_action_row(
            on_test=lambda: self._on_test(idx),
            on_clear=(
                (lambda i=idx, r=refresh_cb: self._on_clear_step_zone(i, r))
                if step.zone is not None else None
            ),
            clear_enabled=step.zone is not None,
        ))

    # -- Track body -------------------------------------------------------

    def _build_track_body(self, layout: QVBoxLayout, idx: int, step: RecorderStep,
                          refresh_cb: Callable[[], None]) -> None:
        # TARGET, thumbnail + meta when set, big primary CTA when empty.
        target_section = Section("Target")
        if not step.template_path:
            empty = QHBoxLayout()
            prompt = QLabel("No target captured")
            prompt.setProperty("role", "hint")
            empty.addWidget(prompt)
            empty.addStretch(1)
            cap_btn = self.app.locker.register(QPushButton("Capture target"))
            cap_btn.setIcon(icons.icon("target", 16, t.TEXT_ON_ACCENT))
            cap_btn.setProperty("variant", "primary")
            cap_btn.setMinimumHeight(t.BUTTON_H_PRIMARY)
            cap_btn.setCursor(Qt.PointingHandCursor)
            cap_btn.clicked.connect(lambda: self._on_track_capture(idx))
            empty.addWidget(cap_btn)
            target_section.addLayout(empty)
        else:
            row = QHBoxLayout()
            row.setSpacing(t.SP_MD)
            row.addWidget(self._template_thumb(step.template_path))

            info = QLabel(self._track_info_text(step))
            info.setWordWrap(True)
            info.setStyleSheet(
                f"color: {t.TEXT_PRIMARY}; "
                f"font-family: {t.FONT_MONO}; "
                f"font-size: {t.SIZE_BODY}px;"
            )
            row.addWidget(info, 1)

            redraw = self.app.locker.register(QPushButton("Recapture"))
            redraw.setIcon(icons.icon("redraw"))
            redraw.setProperty("variant", "ghost")
            redraw.setCursor(Qt.PointingHandCursor)
            redraw.clicked.connect(lambda: self._on_track_capture(idx))
            row.addWidget(redraw)
            target_section.addLayout(row)
        layout.addWidget(target_section)

        # ALTERNATE VIEWS. Extra captures of the same target (rotated NPC,
        # different camera angle). Only offered once a primary exists,
        # since the engine sizes the click box by whichever view wins.
        if step.template_path:
            views_section = Section(
                "Alternate views",
                hint="more captures of the same target; best match wins",
            )
            for v_idx, rel in enumerate(step.extra_template_paths or []):
                vrow = QHBoxLayout()
                vrow.setSpacing(t.SP_MD)
                vrow.addWidget(self._template_thumb(rel, 72, 48))
                sizes = step.extra_template_sizes or []
                vw, vh = sizes[v_idx] if v_idx < len(sizes) else (0, 0)
                meta = QLabel(f"View {v_idx + 1}  ·  {vw}×{vh} px")
                meta.setStyleSheet(
                    f"color: {t.TEXT_SECONDARY}; "
                    f"font-family: {t.FONT_MONO}; "
                    f"font-size: {t.SIZE_BODY}px;"
                )
                vrow.addWidget(meta, 1)
                rm = self.app.locker.register(QPushButton())
                rm.setIcon(icons.icon("x"))
                rm.setProperty("variant", "icon-danger")
                rm.setMaximumSize(t.ICON_BUTTON, t.ICON_BUTTON)
                rm.setMinimumSize(t.ICON_BUTTON, t.ICON_BUTTON)
                rm.setCursor(Qt.PointingHandCursor)
                rm.setToolTip("Remove this view")
                rm.clicked.connect(
                    lambda _=False, i=idx, v=v_idx, r=refresh_cb:
                    self._on_remove_track_view(i, v, r)
                )
                vrow.addWidget(rm)
                views_section.addLayout(vrow)
            add_row = QHBoxLayout()
            add_row.addStretch(1)
            add_view = self.app.locker.register(QPushButton("+ Add view"))
            add_view.setProperty("variant", "ghost")
            add_view.setMinimumHeight(t.BUTTON_H)
            add_view.setCursor(Qt.PointingHandCursor)
            add_view.setToolTip(
                "Drag a rectangle around the same target as seen from "
                "another angle. Saved as templates/<step>_view_<id>.png."
            )
            add_view.clicked.connect(lambda: self._on_track_add_view(idx))
            add_row.addWidget(add_view)
            views_section.addLayout(add_row)
            layout.addWidget(views_section)

        # TIMING
        timing_section = Section("Timing")
        delay_lbl = QLabel(self._delay_text("Delay between clicks", step))
        delay_lbl.setStyleSheet(
            f"color: {t.TEXT_PRIMARY}; "
            f"font-size: {t.SIZE_FIELD_LABEL}px; font-weight: 600;"
        )
        timing_section.add(delay_lbl)
        rng = RangeSpinSlider(
            from_=0.01, to=120.0, steps=11990,
            init_min=step.delay_min, init_max=step.delay_max,
        )
        rng.valueChanged.connect(
            lambda lo, hi, i=idx, lbl=delay_lbl: self._on_delay_change(
                i, lo, hi, "Delay between clicks", lbl,
            )
        )
        timing_section.add(rng)
        layout.addWidget(timing_section)

        # DETAILS: label + resilience (timeout, on-timeout action).
        layout.addWidget(self._details_expander(idx, step, resilience=True))

    # -- Color body -------------------------------------------------------

    def _build_color_body(self, layout: QVBoxLayout, idx: int, step: RecorderStep,
                          refresh_cb: Callable[[], None]) -> None:
        # TARGET, swatch + hex/rgb when set, primary CTA when empty.
        target_section = Section("Target")
        rgb = step.color_target_rgb
        if rgb is None:
            empty = QHBoxLayout()
            prompt = QLabel("No color picked")
            prompt.setProperty("role", "hint")
            empty.addWidget(prompt)
            empty.addStretch(1)
            pick_btn = self.app.locker.register(QPushButton("Pick target color"))
            pick_btn.setIcon(icons.icon("target", 16, t.TEXT_ON_ACCENT))
            pick_btn.setProperty("variant", "primary")
            pick_btn.setMinimumHeight(t.BUTTON_H_PRIMARY)
            pick_btn.setCursor(Qt.PointingHandCursor)
            pick_btn.clicked.connect(lambda: self._on_color_pick(idx))
            empty.addWidget(pick_btn)
            target_section.addLayout(empty)
        else:
            row = QHBoxLayout()
            swatch = QLabel()
            swatch.setFixedSize(40, 28)
            hex_color = "#{:02x}{:02x}{:02x}".format(*rgb)
            swatch.setStyleSheet(
                f"background: {hex_color}; border: 1px solid {t.BORDER_SUBTLE}; "
                f"border-radius: {t.RADIUS_INPUT}px;"
            )
            row.addWidget(swatch)
            data = QLabel(
                f"rgb({rgb[0]}, {rgb[1]}, {rgb[2]})    {hex_color}"
            )
            data.setStyleSheet(
                f"color: {t.TEXT_PRIMARY}; "
                f"font-family: {t.FONT_MONO}; "
                f"font-size: {t.SIZE_BODY}px;"
            )
            row.addWidget(data, 1)
            redraw = self.app.locker.register(QPushButton("Recapture"))
            redraw.setIcon(icons.icon("redraw"))
            redraw.setProperty("variant", "ghost")
            redraw.setCursor(Qt.PointingHandCursor)
            redraw.clicked.connect(lambda: self._on_color_pick(idx))
            row.addWidget(redraw)
            target_section.addLayout(row)

            # Extra accepted shades from the multi-sample eyedropper. Any
            # pixel matching any swatch counts; each swatch has its own
            # remove so a stray click can be undone without re-picking.
            extras = list(step.color_extra_rgbs or [])
            if extras:
                also = QLabel("Also matches")
                also.setProperty("role", "hint")
                target_section.add(also)
                srow = QHBoxLayout()
                srow.setSpacing(t.SP_XS)
                for e_idx, e_rgb in enumerate(extras):
                    e_hex = "#{:02x}{:02x}{:02x}".format(*e_rgb)
                    sw = self.app.locker.register(QPushButton(""))
                    sw.setFixedSize(22, 22)
                    sw.setCursor(Qt.PointingHandCursor)
                    sw.setToolTip(
                        f"rgb({e_rgb[0]}, {e_rgb[1]}, {e_rgb[2]})  {e_hex}\n"
                        "Click to remove this shade."
                    )
                    sw.setStyleSheet(
                        f"background: {e_hex}; border: 1px solid {t.BORDER_SUBTLE}; "
                        f"border-radius: {t.RADIUS_INPUT}px;"
                    )
                    sw.clicked.connect(
                        lambda _=False, i=idx, e=e_idx, r=refresh_cb:
                        self._on_remove_color_extra(i, e, r)
                    )
                    srow.addWidget(sw)
                srow.addStretch(1)
                target_section.addLayout(srow)
        layout.addWidget(target_section)

        # CLICK AREA. Optional zone that limits where matches count, for
        # colors that also appear on the HUD. Same drawer as Click steps.
        area_section = Section(
            "Click area",
            hint="optional; only matches inside it are clicked",
        )
        if step.zone is None:
            arow = QHBoxLayout()
            aprompt = QLabel("Whole monitor")
            aprompt.setProperty("role", "hint")
            arow.addWidget(aprompt)
            arow.addStretch(1)
            set_btn = self.app.locker.register(QPushButton("Set click area"))
            set_btn.setProperty("variant", "ghost")
            set_btn.setMinimumHeight(t.BUTTON_H)
            set_btn.setCursor(Qt.PointingHandCursor)
            set_btn.clicked.connect(lambda: self._on_color_zone_draw(idx))
            arow.addWidget(set_btn)
            area_section.addLayout(arow)
        else:
            arow = QHBoxLayout()
            adata = QLabel(self._zone_summary(step))
            adata.setStyleSheet(
                f"color: {t.TEXT_PRIMARY}; "
                f"font-family: {t.FONT_MONO}; "
                f"font-size: {t.SIZE_BODY}px;"
            )
            adata.setWordWrap(True)
            arow.addWidget(adata, 1)
            aredraw = self.app.locker.register(QPushButton("Redraw"))
            aredraw.setIcon(icons.icon("redraw"))
            aredraw.setProperty("variant", "ghost")
            aredraw.setCursor(Qt.PointingHandCursor)
            aredraw.clicked.connect(lambda: self._on_color_zone_draw(idx))
            arow.addWidget(aredraw)
            aclear = self.app.locker.register(QPushButton("Clear"))
            aclear.setProperty("variant", "ghost")
            aclear.setCursor(Qt.PointingHandCursor)
            aclear.clicked.connect(
                lambda _=False, i=idx, r=refresh_cb: self._on_clear_step_zone(i, r)
            )
            arow.addWidget(aclear)
            area_section.addLayout(arow)
            area_section.add(self._lock_row(idx, step))
        layout.addWidget(area_section)

        # TOLERANCE
        tol_section = Section("Tolerance")
        from PySide6.QtWidgets import QSlider
        tol_row = QHBoxLayout()
        tol_row.setSpacing(t.SP_SM)
        tol_slider = self.app.locker.register(QSlider(Qt.Horizontal))
        tol_slider.setRange(0, 100)
        tol_slider.setValue(int(step.color_tolerance))
        tol_val_lbl = QLabel(f"{int(step.color_tolerance)}")
        tol_val_lbl.setMinimumWidth(40)
        tol_val_lbl.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        tol_val_lbl.setStyleSheet(
            f"color: {t.TEXT_PRIMARY}; "
            f"font-family: {t.FONT_MONO}; "
            f"font-size: {t.SIZE_BODY}px;"
        )
        tol_slider.valueChanged.connect(
            lambda v, i=idx, lbl=tol_val_lbl: self._on_color_tolerance(i, v, lbl)
        )
        tol_row.addWidget(tol_slider, 1)
        tol_row.addWidget(tol_val_lbl)
        tol_section.addLayout(tol_row)
        layout.addWidget(tol_section)

        # TIMING
        timing_section = Section("Timing")
        delay_lbl = QLabel(self._delay_text("Delay between clicks", step))
        delay_lbl.setStyleSheet(
            f"color: {t.TEXT_PRIMARY}; "
            f"font-size: {t.SIZE_FIELD_LABEL}px; font-weight: 600;"
        )
        timing_section.add(delay_lbl)
        rng = RangeSpinSlider(
            from_=0.01, to=120.0, steps=11990,
            init_min=step.delay_min, init_max=step.delay_max,
        )
        rng.valueChanged.connect(
            lambda lo, hi, i=idx, lbl=delay_lbl: self._on_delay_change(
                i, lo, hi, "Delay between clicks", lbl,
            )
        )
        timing_section.add(rng)
        layout.addWidget(timing_section)

        # DETAILS: label + resilience (timeout, on-timeout action).
        layout.addWidget(self._details_expander(idx, step, resilience=True))

    # -- Loop body --------------------------------------------------------

    def _build_loop_body(self, layout: QVBoxLayout, idx: int, step: RecorderStep,
                         refresh_cb: Callable[[], None]) -> None:
        # TARGET, which prior step to loop back to.
        target_section = Section("Target")
        tgt_lbl = QLabel("Loop back to")
        tgt_lbl.setStyleSheet(
            f"color: {t.TEXT_PRIMARY}; "
            f"font-size: {t.SIZE_FIELD_LABEL}px; font-weight: 600;"
        )
        target_section.add(tgt_lbl)
        combo = self.app.locker.register(QComboBox())
        for i, s in enumerate(self.app._steps):
            if i == idx:
                continue
            combo.addItem(self._loop_target_label(i, s), s.step_id)
            if s.step_id == step.loop_target_step_id:
                combo.setCurrentIndex(combo.count() - 1)
        combo.currentIndexChanged.connect(
            lambda _, c=combo, i=idx: self._on_loop_target_change(i, c.currentData())
        )
        target_section.add(combo)
        layout.addWidget(target_section)

        # COUNT, engine semantic: N = "loop back N more times" so a
        # CLICK→LOOP block with loop_count=2 runs the CLICK three times
        # (initial pass + 2 loop-backs).
        count_section = Section("Count")
        cnt_lbl = QLabel("Loop back N more times")
        cnt_lbl.setStyleSheet(
            f"color: {t.TEXT_PRIMARY}; "
            f"font-size: {t.SIZE_FIELD_LABEL}px; font-weight: 600;"
        )
        count_section.add(cnt_lbl)
        cnt_row = QHBoxLayout()
        cnt_row.setSpacing(t.SP_MD)
        count_entry = self.app.locker.register(
            QLineEdit(str(int(step.loop_count)))
        )
        count_entry.setMaximumWidth(80)
        count_entry.setAlignment(Qt.AlignCenter)
        count_entry.setProperty("role", "mono")
        count_entry.setToolTip(
            "0 = loop forever.\n"
            "1 = run the block once more after the first pass (2 total).\n"
            "N = N extra loop-backs after the first pass (N+1 total)."
        )
        count_entry.editingFinished.connect(
            lambda i=idx, e=count_entry: self._on_loop_count_change(i, e.text())
        )
        cnt_row.addWidget(count_entry)
        cnt_hint = QLabel("0 = forever")
        cnt_hint.setProperty("role", "hint")
        cnt_row.addWidget(cnt_hint)
        cnt_row.addStretch(1)
        count_section.addLayout(cnt_row)

        summary = QLabel(self._loop_summary(step))
        summary.setProperty("role", "hint")
        summary.setWordWrap(True)
        count_section.add(summary)
        layout.addWidget(count_section)

    # -- Key body ---------------------------------------------------------

    def _build_key_body(self, layout: QVBoxLayout, idx: int, step: RecorderStep,
                         refresh_cb: Callable[[], None]) -> None:
        sid = step.step_id
        mods, base = _split_combo(step.key_combo)

        # KEYBINDING, modifier toggles + key chip + Capture button.
        # When key is unset, Capture is the prominent primary CTA. When
        # set, the chip carries the value and Capture demotes to a small
        # ghost "Recapture" inline.
        binding_section = Section(
            "Keybinding",
            hint="run as admin if the target app is elevated",
        )

        mod_lbl = QLabel("Modifiers")
        mod_lbl.setStyleSheet(
            f"color: {t.TEXT_PRIMARY}; "
            f"font-size: {t.SIZE_FIELD_LABEL}px; font-weight: 600;"
        )
        binding_section.add(mod_lbl)
        mod_row = QHBoxLayout()
        mod_row.setSpacing(t.SP_LG)
        checks: dict[str, QCheckBox] = {}
        for m in _MOD_KEYS:
            cb = self.app.locker.register(QCheckBox(_MOD_LABELS[m]))
            cb.setChecked(m in mods)
            cb.setCursor(Qt.PointingHandCursor)
            cb.toggled.connect(
                lambda on, mod=m, i=idx, s=sid: self._on_key_mod_toggle(
                    i, s, mod, on)
            )
            mod_row.addWidget(cb)
            checks[m] = cb
        mod_row.addStretch(1)
        binding_section.addLayout(mod_row)

        # Key chip + Capture button row.
        key_lbl = QLabel("Key")
        key_lbl.setStyleSheet(
            f"color: {t.TEXT_PRIMARY}; "
            f"font-size: {t.SIZE_FIELD_LABEL}px; font-weight: 600; "
            f"margin-top: 4px;"
        )
        binding_section.add(key_lbl)

        cap_row = QHBoxLayout()
        cap_row.setSpacing(t.SP_SM)
        chip = KeyChip(self._chip_text(mods, base))
        chip.setMinimumWidth(160)
        cap_row.addWidget(chip)
        cap_row.addStretch(1)

        # Capture button, primary when no key set, ghost ↻ when set.
        capture_btn = self.app.locker.register(
            QPushButton("Press a key" if not base else "Recapture")
        )
        capture_btn.setProperty(
            "variant", "primary" if not base else "ghost"
        )
        capture_btn.setMinimumHeight(t.BUTTON_H)
        capture_btn.setCursor(Qt.PointingHandCursor)
        capture_btn.setToolTip(
            "Click, then press the key you want to bind. "
            "Pressing a modifier (Ctrl / Shift / Alt) auto-toggles it "
            "and keeps listening for the base key."
        )
        capture_btn.clicked.connect(
            lambda _=False, i=idx, s=sid: self._on_key_capture_start(i, s)
        )
        cap_row.addWidget(capture_btn)
        binding_section.addLayout(cap_row)

        # Validity hint.
        valid_lbl = QLabel(self._key_validity(mods, base))
        valid_lbl.setProperty("role", "hint")
        valid_lbl.setWordWrap(True)
        binding_section.add(valid_lbl)
        layout.addWidget(binding_section)

        # Stash widgets so the capture handler can update them.
        self._key_widgets[sid] = {
            "chip": chip,
            "btn": capture_btn,
            "checks": checks,
            "lbl": valid_lbl,
            "timer": None,
        }

        # REPEAT, count + hold duration in a 2-col grid.
        repeat_section = Section("Repeat")
        rgrid = QHBoxLayout()
        rgrid.setSpacing(t.SP_LG)

        rcol = QVBoxLayout()
        rcol.setSpacing(4)
        rl = QLabel("Repeat")
        rl.setStyleSheet(
            f"color: {t.TEXT_PRIMARY}; "
            f"font-size: {t.SIZE_FIELD_LABEL}px; font-weight: 600;"
        )
        rcol.addWidget(rl)
        repeat_entry = self.app.locker.register(QLineEdit(str(int(step.key_repeat))))
        repeat_entry.setMaximumWidth(80)
        repeat_entry.setAlignment(Qt.AlignCenter)
        repeat_entry.setProperty("role", "mono")
        repeat_entry.editingFinished.connect(
            lambda i=idx, e=repeat_entry: self._on_key_repeat_change(i, e.text())
        )
        rcol.addWidget(repeat_entry)
        rcol.addStretch(1)
        rwrap = QWidget()
        rwrap.setLayout(rcol)
        rwrap.setMaximumWidth(120)
        rgrid.addWidget(rwrap)

        hcol = QVBoxLayout()
        hcol.setSpacing(4)
        hl = QLabel("Hold (s)")
        hl.setStyleSheet(
            f"color: {t.TEXT_PRIMARY}; "
            f"font-size: {t.SIZE_FIELD_LABEL}px; font-weight: 600;"
        )
        hcol.addWidget(hl)
        hold_entry = self.app.locker.register(
            QLineEdit(f"{float(step.key_hold_s):.2f}")
        )
        hold_entry.setMaximumWidth(80)
        hold_entry.setAlignment(Qt.AlignCenter)
        hold_entry.setProperty("role", "mono")
        hold_entry.editingFinished.connect(
            lambda i=idx, e=hold_entry: self._on_key_hold_change(i, e.text())
        )
        hcol.addWidget(hold_entry)
        hcol.addStretch(1)
        hwrap = QWidget()
        hwrap.setLayout(hcol)
        hwrap.setMaximumWidth(120)
        rgrid.addWidget(hwrap)
        rgrid.addStretch(1)
        repeat_section.addLayout(rgrid)
        layout.addWidget(repeat_section)

        # TIMING, wait time AFTER the keypress before the next step.
        timing_section = Section("Timing")
        delay_lbl = QLabel(self._delay_text("Wait after press", step))
        delay_lbl.setStyleSheet(
            f"color: {t.TEXT_PRIMARY}; "
            f"font-size: {t.SIZE_FIELD_LABEL}px; font-weight: 600;"
        )
        timing_section.add(delay_lbl)
        rng = RangeSpinSlider(
            from_=0.01, to=120.0, steps=11990,
            init_min=step.delay_min, init_max=step.delay_max,
        )
        rng.valueChanged.connect(
            lambda lo, hi, i=idx, lbl=delay_lbl: self._on_delay_change(
                i, lo, hi, "Wait after press", lbl,
            )
        )
        timing_section.add(rng)
        layout.addWidget(timing_section)
        layout.addWidget(self._details_expander(idx, step))

        # ACTION ROW
        layout.addWidget(self._build_action_row(
            on_test=lambda i=idx, s=sid: self._on_key_test(i, s),
            on_clear=lambda i=idx, s=sid: self._on_key_clear(i, s),
            clear_enabled=bool(base),
        ))

    # -- Step Advanced (shape + button/mode for click steps) --------------

    def _build_step_advanced(self, layout: QVBoxLayout, idx: int,
                             step: RecorderStep) -> None:
        # Shape row.
        srow = QHBoxLayout()
        srow.setSpacing(t.SP_SM)
        srow.addWidget(self._field_label("Shape:"))
        shape_group = QButtonGroup(layout.parent())
        for label, val in [("Rect", "rect"), ("Circle", "circle"),
                           ("Custom", "polygon")]:
            rb = QRadioButton(label)
            rb.setChecked(val == step.shape)
            rb.toggled.connect(
                lambda checked, v=val, i=idx: checked and self._on_step_shape(i, v)
            )
            srow.addWidget(rb)
            shape_group.addButton(rb)
        srow.addStretch(1)
        layout.addLayout(srow)

        # Button row.
        brow = QHBoxLayout()
        brow.setSpacing(t.SP_SM)
        brow.addWidget(self._field_label("Button:"))
        btn_group = QButtonGroup(layout.parent())
        for label, val in [("Left", "left"), ("Right", "right")]:
            rb = QRadioButton(label)
            rb.setChecked(val == step.click_type)
            rb.toggled.connect(
                lambda checked, v=val, i=idx: checked and self._on_step_click_type(i, v)
            )
            brow.addWidget(rb)
            btn_group.addButton(rb)
        brow.addStretch(1)
        layout.addLayout(brow)

        # Mode row.
        mrow = QHBoxLayout()
        mrow.setSpacing(t.SP_SM)
        mrow.addWidget(self._field_label("Mode:"))
        mode_group = QButtonGroup(layout.parent())
        for label, val in [("Single", "single"), ("Double", "double")]:
            rb = QRadioButton(label)
            rb.setChecked(val == step.click_mode)
            rb.toggled.connect(
                lambda checked, v=val, i=idx: checked and self._on_step_click_mode(i, v)
            )
            mrow.addWidget(rb)
            mode_group.addButton(rb)
        mrow.addStretch(1)
        layout.addLayout(mrow)

    # -- Helpers ----------------------------------------------------------

    def _step_problem(self, step: RecorderStep, idx: int) -> str:
        """Return a human-readable problem string when this step is
        unrunnable, or empty string when fine. Mirrors the predicate
        Clicker._peek_recorder_step uses to decide whether to skip a
        step at run time (clicker.py, checks template_path / zone /
        color_target_rgb / valid key_combo / loop target). Surfaces the
        same conditions in the UI so users catch broken steps before
        they hit Start."""
        if step.kind == KIND_PAUSE:
            return ""
        if step.kind == KIND_LOOP:
            target_id = step.loop_target_step_id
            if not target_id:
                return ("Loop has no target step, pick which earlier "
                        "step to loop back to.")
            steps = self.app._steps
            for i, s in enumerate(steps):
                if s.step_id == target_id:
                    if i >= idx:
                        return ("Loop must point to an EARLIER step, "
                                "not itself or later.")
                    return ""
            return "Loop target step was deleted, pick a new target."
        if step.kind == KIND_TRACK:
            if not step.template_path:
                return "No target captured, tap Capture target."
            return ""
        if step.kind == KIND_COLOR:
            if step.color_target_rgb is None:
                return "No color picked, tap Pick target color."
            return ""
        if step.kind == KIND_CLICK:
            if step.zone is None:
                return "No click area, tap Pick click area."
            return ""
        if step.kind == KIND_KEY:
            if not step.key_combo:
                return "No key bound. Tap Press a key to bind one."
            if parse_combo(step.key_combo) is None:
                return f"Key combo '{step.key_combo}' isn't recognized."
            return ""
        return ""

    def _field_label(self, text: str) -> QLabel:
        lbl = QLabel(text)
        lbl.setProperty("role", "secondary")
        return lbl

    def _delay_text(self, prefix: str, step: RecorderStep) -> str:
        # Field labels now show ONLY the field name; the live values are
        # already visible in the RangeSpinSlider's min/max input boxes
        # below. Dropping the redundant values from the header also lets
        # the TIMING two-column grid height-balance with the narrower
        # Clicks input on the left.
        return prefix

    def _zone_summary(self, step: RecorderStep) -> str:
        if step.zone is None:
            return "No click area picked yet, tap “Pick click area” above"
        z = step.zone
        if z.shape == "rect":
            x1, y1, x2, y2 = z.rect
            return f"Click area: {x2-x1}×{y2-y1} at ({x1},{y1})"
        if z.shape == "circle":
            cx, cy, r = z.circle
            return f"Click area: circle r={r} at ({cx},{cy})"
        return f"Click area: custom shape ({len(z.vertices)} corners)"

    def _track_info_text(self, step: RecorderStep) -> str:
        if not step.template_path:
            return "No target captured yet. Tap Capture target."
        rect = step.capture_rect or (0, 0, 0, 0)
        n_views = len(step.extra_template_paths or [])
        views = f"\n+{n_views} alternate view{'s' if n_views != 1 else ''}" if n_views else ""
        return (f"Captured at ({rect[0]},{rect[1]}) "
                f"{rect[2] - rect[0]}×{rect[3] - rect[1]} px{views}")

    def _resolve_template(self, rel_or_abs: str) -> Path:
        p = Path(rel_or_abs)
        return p if p.is_absolute() else _config_dir() / p

    def _template_thumb(self, rel_or_abs: Optional[str], w: int = 96, h: int = 64) -> QLabel:
        thumb = QLabel()
        thumb.setFixedSize(w, h)
        thumb.setStyleSheet(
            f"background: {t.BG}; border: 1px solid {t.BORDER_SUBTLE}; "
            f"border-radius: {t.RADIUS_INPUT}px;"
        )
        thumb.setAlignment(Qt.AlignCenter)
        pix = QPixmap(str(self._resolve_template(rel_or_abs))) if rel_or_abs else QPixmap()
        if not pix.isNull():
            thumb.setPixmap(pix.scaled(
                w - 4, h - 4, Qt.KeepAspectRatio, Qt.SmoothTransformation,
            ))
        else:
            thumb.setText("?")
        return thumb

    def _loop_target_label(self, i: int, s: RecorderStep) -> str:
        kind_word = {
            KIND_CLICK: "Click", KIND_TRACK: "Track",
            KIND_COLOR: "Color", KIND_PAUSE: "Pause", KIND_LOOP: "Loop",
        }.get(s.kind, "")
        # Picking your loop target by name beats picking by step number every
        # time, surface step.label here when present.
        label = (s.label or "").strip()
        if label:
            return f"Step {i+1}, {label} · {kind_word}"
        return f"Step {i+1}: {kind_word}"

    def _loop_summary(self, step: RecorderStep) -> str:
        # Find the target index.
        idx = next(
            (i for i, s in enumerate(self.app._steps)
             if s.step_id == step.loop_target_step_id),
            None,
        )
        if idx is None:
            return "Loop target missing, pick one above."
        if step.loop_count <= 0:
            return f"Loops back to Step {idx+1} forever."
        return f"Loops back to Step {idx+1}, {step.loop_count} more times."

    # -- Edit handlers ---------------------------------------------------

    def _on_delay_change(self, idx: int, lo: float, hi: float,
                         prefix: str, lbl: QLabel) -> None:
        if not (0 <= idx < len(self.app._steps)):
            return
        self.app._steps[idx].delay_min = float(lo)
        self.app._steps[idx].delay_max = float(hi)
        # Fires per slider pixel; the spinboxes already show the live value.
        self.app.save_steps_later()
        # Label is the static field name now ("Delay range" / "Wait for")
        #, values live in the slider's min/max input boxes. Re-set the
        # label to ``prefix`` (cheap; harmless if the text didn't change)
        # so any caller that wires this up still sees a consistent state.
        lbl.setText(prefix)

    def _on_step_enabled_toggled(self, idx: int, checked: bool) -> None:
        """Persist the new enable state. The engine's _peek_recorder_step
        will naturally skip disabled steps on the next cycle, no engine
        restart needed. We don't trigger a row re-render here because Qt
        is mid-emit on the switch widget itself; the live switch state
        is the source of truth until the next structural refresh."""
        if not (0 <= idx < len(self.app._steps)):
            return
        self.app._steps[idx].enabled = bool(checked)
        self.app._save_steps()

    def _on_click_count_change(self, idx: int, raw: str) -> None:
        if not (0 <= idx < len(self.app._steps)):
            return
        try:
            n = int(str(raw).strip())
        except (TypeError, ValueError):
            n = 1
        n = max(1, min(1000, n))
        self.app._steps[idx].click_count = n
        self.app._save_steps()

    def _on_step_shape(self, idx: int, shape: str) -> None:
        if 0 <= idx < len(self.app._steps):
            self.app._steps[idx].shape = shape
            self.app._save_steps()

    def _on_label_change(self, idx: int, raw: str) -> None:
        """Persist a new step label. Empty input clears it (header reverts
        to step + kind only). We don't trigger a structural refresh here
        because the body widget that just lost focus would die mid-callback;
        the next natural refresh (add / move / delete) re-renders the header
        with the saved value."""
        if not (0 <= idx < len(self.app._steps)):
            return
        self.app._steps[idx].label = str(raw or "").strip()[:80]
        self.app._save_steps()

    def _on_timeout_seconds_change(self, idx: int, value: float) -> None:
        if not (0 <= idx < len(self.app._steps)):
            return
        self.app._steps[idx].timeout_seconds = max(0.0, float(value or 0.0))
        self.app._save_steps()

    def _on_on_timeout_change(self, idx: int, action: object) -> None:
        if not (0 <= idx < len(self.app._steps)):
            return
        action_str = str(action) if action is not None else "skip"
        if action_str not in ("skip", "stop"):
            action_str = "skip"
        self.app._steps[idx].on_timeout = action_str
        self.app._save_steps()

    def _on_step_click_type(self, idx: int, value: str) -> None:
        if 0 <= idx < len(self.app._steps):
            self.app._steps[idx].click_type = value
            self.app._save_steps()

    def _on_step_click_mode(self, idx: int, value: str) -> None:
        if 0 <= idx < len(self.app._steps):
            self.app._steps[idx].click_mode = value
            self.app._save_steps()

    def _chip_text(self, mods: set[str], base: str) -> str:
        """Pretty-printed combo for the KeyChip. Empty when nothing's bound."""
        if not base:
            return ", "
        ordered = [_MOD_LABELS[m] for m in _MOD_KEYS if m in mods]
        # KeyChip uppercases; show pretty case with " + " separator.
        parts = ordered + [_pretty_base(base)]
        return " + ".join(parts)

    def _key_validity(self, mods: set[str], base: str) -> str:
        """Sub-label that reflects the current state: hint, ok, or error."""
        if not base:
            return "Press the capture button to bind a key."
        combo = _join_combo(mods, base)
        if parse_combo(combo) is None:
            return f"unrecognized key: {base!r}"
        return f"bound: {combo_display(combo)}"

    def _on_key_mod_toggle(self, idx: int, sid: str, mod: str, on: bool) -> None:
        if not (0 <= idx < len(self.app._steps)):
            return
        step = self.app._steps[idx]
        # Read the full toggle state, what the user sees is the truth.
        mods = self._mods_from_checks(sid)
        if on:
            mods.add(mod)
        else:
            mods.discard(mod)
        _old_mods, base = _split_combo(step.key_combo)
        step.key_combo = _join_combo(mods, base)
        self.app._save_steps()
        self._refresh_key_widgets(sid, mods, base)

    def _on_key_clear(self, idx: int, sid: str) -> None:
        if not (0 <= idx < len(self.app._steps)):
            return
        step = self.app._steps[idx]
        # Modifier toggles stay as the user set them; only the base goes.
        mods = self._mods_from_checks(sid)
        step.key_combo = _join_combo(mods, "")
        self.app._save_steps()
        self._refresh_key_widgets(sid, mods, "")

    def _on_key_capture_start(self, idx: int, sid: str) -> None:
        widgets = self._key_widgets.get(sid)
        if widgets is None:
            return
        # Cancel any prior capture so a stale callback can't clobber a fresh one.
        prior = widgets.get("timer")
        if prior is not None:
            prior.stop()
        try:
            self.app.hotkeys.cancel_capture()
        except Exception:
            pass
        btn = widgets["btn"]
        btn.setText("Press any key…")
        btn.setEnabled(False)
        widgets["lbl"].setText(
            "Listening, press the key you want bound (Esc to cancel)."
        )
        # Modifier-aware capture: feed the next press through the QObject
        # signal bridge so the slot runs on the Qt main thread. Modifiers
        # auto-toggle and re-arm; the first non-modifier ends capture.
        bridge = self._key_bridge
        self.app.hotkeys.capture_next(
            lambda name, s=sid: bridge.captured.emit(s, name)
        )
        # Safety net: if no key is captured (window loses focus, user walks
        # away), restore the button after a short timeout.
        timer = QTimer(self.app)
        timer.setSingleShot(True)
        timer.timeout.connect(lambda i=idx, s=sid: self._on_key_capture_timeout(i, s))
        timer.start(_KEY_CAPTURE_TIMEOUT_MS)
        widgets["timer"] = timer

    def _on_key_captured_main_thread(self, sid: str, name: str) -> None:
        """Bridge slot, runs on the Qt main thread regardless of which
        thread emitted ``captured``. Resolves sid → idx and dispatches."""
        _log.info("key capture delivered sid=%s name=%r", sid, name)
        idx = next(
            (i for i, s in enumerate(self.app._steps)
             if getattr(s, "step_id", None) == sid),
            None,
        )
        if idx is None:
            # Step was deleted while capture was pending; just clean up.
            self._end_capture(sid)
            return
        self._on_key_captured(idx, sid, name)

    def _on_key_captured(self, idx: int, sid: str, name: str) -> None:
        widgets = self._key_widgets.get(sid)
        if widgets is None or not (0 <= idx < len(self.app._steps)):
            return
        step = self.app._steps[idx]
        canonical = _MOD_ALIASES.get(name, name)

        # Modifiers live in the checkbox state, not in step.key_combo , 
        # that way the Clear button (which empties the combo because a
        # bare modifier is unrunnable) doesn't drop the user's chosen
        # modifier toggles.
        mods = self._mods_from_checks(sid)

        # Esc cancels the capture without binding (matches the global hotkey
        # card's behaviour and gives the user an easy escape hatch).
        if canonical == "esc":
            self._end_capture(sid)
            self.app.toasts.post(
                "Capture cancelled, Esc isn't bound to this step.",
                kind="info",
            )
            return

        # Modifier press → toggle the matching checkbox and keep listening.
        if canonical in _MOD_KEYS:
            mods.add(canonical)
            _old_mods, base = _split_combo(step.key_combo)
            step.key_combo = _join_combo(mods, base)
            self.app._save_steps()
            self._refresh_key_widgets(sid, mods, base)
            # Re-arm the listener for the next press, again via the bridge
            # so we stay on the main thread for widget updates.
            bridge = self._key_bridge
            self.app.hotkeys.capture_next(
                lambda n, s=sid: bridge.captured.emit(s, n)
            )
            return

        # Base key, accept it, finalize the capture.
        if not name:
            self._end_capture(sid)
            return
        # Normalize whitespace-as-space (defensive; pynput shouldn't send "").
        if not name.strip():
            name = "space"
        step.key_combo = _join_combo(mods, name.strip().lower())
        self.app._save_steps()
        _log.info(
            "key bound idx=%d sid=%s combo=%r (steps=%d)",
            idx, sid, step.key_combo, len(self.app._steps),
        )
        new_mods, new_base = _split_combo(step.key_combo)
        self._refresh_key_widgets(sid, new_mods, new_base)
        self._end_capture(sid)

    def _mods_from_checks(self, sid: str) -> set[str]:
        """Snapshot the live checkbox state for a key step. Used as the
        source of truth for modifiers because the saved combo doesn't
        retain bare modifier-only state (no base = empty combo)."""
        widgets = self._key_widgets.get(sid)
        if widgets is None:
            return set()
        return {m for m, cb in widgets["checks"].items() if cb.isChecked()}

    def _on_key_capture_timeout(self, idx: int, sid: str) -> None:
        widgets = self._key_widgets.get(sid)
        if widgets is None:
            return
        try:
            self.app.hotkeys.cancel_capture()
        except Exception:
            pass
        widgets["timer"] = None
        # Restore widget state to whatever the saved combo says.
        if 0 <= idx < len(self.app._steps):
            mods, base = _split_combo(self.app._steps[idx].key_combo)
            self._refresh_key_widgets(sid, mods, base)
        widgets["btn"].setText("Press a key")
        widgets["btn"].setEnabled(True)
        if hasattr(self.app, "toasts"):
            self.app.toasts.post(
                "Key capture timed out, nothing was bound.", kind="info",
            )

    def _end_capture(self, sid: str) -> None:
        """Restore the capture button and stop the timeout. Idempotent."""
        widgets = self._key_widgets.get(sid)
        if widgets is None:
            return
        timer = widgets.get("timer")
        if timer is not None:
            timer.stop()
            widgets["timer"] = None
        try:
            self.app.hotkeys.cancel_capture()
        except Exception:
            pass
        btn = widgets.get("btn")
        if btn is not None:
            btn.setText("Press a key")
            btn.setEnabled(True)

    def _on_key_test(self, idx: int, sid: str) -> None:
        if not (0 <= idx < len(self.app._steps)):
            return
        step = self.app._steps[idx]
        if not step.key_combo or parse_combo(step.key_combo) is None:
            self.app.toasts.post(
                "Bind a key first, nothing to test.", kind="warn",
            )
            return
        # Route through the engine so Test exercises whichever backend
        # the user picked (Serial HID / Interception / SendInput), the
        # old pynput-Controller path always used SendInput regardless
        # of UI selection, which made Test useless for verifying that
        # NXT actually sees keystrokes from the configured backend.
        # The 3-second delay gives the user time to alt-tab to the
        # target window (typically RuneScape) so the keystroke lands
        # there and they can see the chatbox / quick-action react.
        countdown_s = 3.0
        scheduled = self.app.clicker.fire_step_once(step, delay_s=countdown_s)
        if scheduled:
            self.app.toasts.post(
                f"Firing {combo_display(step.key_combo)} in "
                f"{countdown_s:.0f}s, alt-tab to your target window now.",
                kind="info",
            )
        else:
            self.app.toasts.post(
                "Can't test right now, engine is running. Stop it first.",
                kind="warn",
            )

    def _refresh_key_widgets(
        self, sid: str, mods: set[str], base: str,
    ) -> None:
        """Sync the chip / checkboxes / validity label to a (mods, base) pair.
        Safe to call from any handler, block-signals on the checkboxes so
        the toggled signal doesn't recurse into _on_key_mod_toggle."""
        widgets = self._key_widgets.get(sid)
        if widgets is None:
            return
        widgets["chip"].set_text(self._chip_text(mods, base))
        for m, cb in widgets["checks"].items():
            want = m in mods
            if cb.isChecked() != want:
                cb.blockSignals(True)
                cb.setChecked(want)
                cb.blockSignals(False)
        widgets["lbl"].setText(self._key_validity(mods, base))

    def _on_key_repeat_change(self, idx: int, raw: str) -> None:
        if not (0 <= idx < len(self.app._steps)):
            return
        try:
            n = int(str(raw).strip())
        except (TypeError, ValueError):
            n = 1
        self.app._steps[idx].key_repeat = max(1, min(50, n))
        self.app._save_steps()

    def _on_key_hold_change(self, idx: int, raw: str) -> None:
        if not (0 <= idx < len(self.app._steps)):
            return
        try:
            v = float(str(raw).strip())
        except (TypeError, ValueError):
            v = 0.0
        self.app._steps[idx].key_hold_s = max(0.0, min(10.0, v))
        self.app._save_steps()

    def _set_advanced_open(self, step_id: str, open_: bool) -> None:
        self._advanced_open[step_id] = open_

    def cancel_all_captures(self) -> None:
        """Stop every pending key-capture timer (app close)."""
        for sid in list(self._key_widgets):
            try:
                self._end_capture(sid)
            except Exception:
                pass

    # -- Reorder / duplicate / remove ------------------------------------

    def _move(self, idx: int, delta: int, refresh_cb) -> None:
        new = idx + delta
        if 0 <= idx < len(self.app._steps) and 0 <= new < len(self.app._steps):
            self.app._steps[idx], self.app._steps[new] = \
                self.app._steps[new], self.app._steps[idx]
            self.app._save_steps()
            refresh_cb()
            self.app.overlay_manager.refresh_step_overlays()

    def _duplicate(self, idx: int, refresh_cb) -> None:
        if not (0 <= idx < len(self.app._steps)):
            return
        from modules.recorder import _new_step_id
        new_step = copy.deepcopy(self.app._steps[idx])
        # Every step gets a fresh id (loop targets and expanded-state keys
        # are id-based). Track steps also get their own copies of the PNGs
        # so a later Recapture / remove on either step can't touch the
        # other's files.
        new_step.step_id = _new_step_id()
        if new_step.kind == KIND_TRACK:
            new_step.template_path = self._copy_template(
                new_step.template_path, f"{new_step.step_id}.png",
            )
            new_step.extra_template_paths = [
                self._copy_template(p, f"{new_step.step_id}_view_{new_view_id()}.png")
                for p in (new_step.extra_template_paths or [])
            ]
        self.app._steps.insert(idx + 1, new_step)
        self.app._save_steps()
        refresh_cb()
        self.app.overlay_manager.refresh_step_overlays()

    def _copy_template(self, src_rel: Optional[str], dst_name: str) -> Optional[str]:
        """Copy a template PNG to ``templates/<dst_name>`` and return the new
        relative path. On any failure the original path is returned so the
        duplicate still works, merely sharing the file as before."""
        if not src_rel:
            return src_rel
        try:
            src = self._resolve_template(src_rel)
            if not src.exists():
                return src_rel
            tdir = _templates_dir()
            tdir.mkdir(parents=True, exist_ok=True)
            dst = tdir / dst_name
            shutil.copy2(str(src), str(dst))
            return os.path.relpath(str(dst), str(_config_dir())).replace("\\", "/")
        except Exception:
            _log.warning("template copy failed for %r", src_rel, exc_info=True)
            return src_rel

    def _remove(self, idx: int, refresh_cb) -> None:
        if not (0 <= idx < len(self.app._steps)):
            return
        if QMessageBox.question(
            self.app, "Remove step",
            f"Remove step {idx + 1}? You can restore it from the "
            "Record-tab footer until the app closes.",
        ) != QMessageBox.Yes:
            return
        step = self.app._steps[idx]
        # Tear down any keyboard-step capture state for the deleted step
        # so a stuck timer / capture callback can't fire after the row is gone.
        sid = getattr(step, "step_id", None)
        if sid is not None and sid in self._key_widgets:
            self._end_capture(sid)
            self._key_widgets.pop(sid, None)
        # Template files go to .trash/ (restorable until app close), but
        # only the ones no surviving step still references. Legacy
        # duplicates shared a single PNG; taking it would break the twin.
        template_paths = [
            self._resolve_template(p)
            for p in orphaned_template_paths(step, self.app._steps)
        ]
        # Push to trash BEFORE removing from the list so the restore
        # index reflects the pre-delete position.
        self.app._push_step_to_trash(step, idx, template_paths)
        del self.app._steps[idx]
        self.app._save_steps()
        refresh_cb()
        self.app.overlay_manager.refresh_step_overlays()

    # -- Capture / pick / draw stubs (overlays land in E2/E3) -----------

    def _on_clear_step_zone(self, idx: int, refresh_cb: Callable[[], None]) -> None:
        if not (0 <= idx < len(self.app._steps)):
            return
        step = self.app._steps[idx]
        if step.zone is None:
            return
        step.zone = None
        self.app._save_steps()
        refresh_cb()
        self.app.overlay_manager.refresh_step_overlays()

    def _lock_row(self, idx: int, step: RecorderStep) -> QWidget:
        """LOCK  WINDOW | SCREEN row for a step's click area."""
        ctl = self.app.locker.register(ZoneLockControl())
        ctl.set_zone(step.zone)
        ctl.modeChanged.connect(lambda m, i=idx: self._on_step_lock_mode(i, m))
        return ctl

    def _on_step_lock_mode(self, idx: int, mode: str) -> None:
        if not (0 <= idx < len(self.app._steps)):
            return
        step = self.app._steps[idx]
        if step.zone is None:
            return
        from modules.zone_lock import apply_lock_mode
        new_zone = apply_lock_mode(step.zone, mode)
        if mode == "window" and new_zone.lock is None:
            self.app.toasts.post(
                "No window under the click area centre, so it stays screen-locked.",
                kind="warn",
            )
        step.zone = new_zone
        self.app.zone_locks.forget(step.step_id)
        self.app._save_steps()
        self.app.record_mode_tab.render_all()
        self.app.overlay_manager.refresh_step_overlays()

    def _on_draw_step(self, idx: int) -> None:
        if not (0 <= idx < len(self.app._steps)):
            return
        from modules.clicker import ClickerState
        if self.app.clicker.state != ClickerState.IDLE:
            return
        step = self.app._steps[idx]

        def _done(zone):
            if zone is None:
                return
            if 0 <= idx < len(self.app._steps):
                self.app._steps[idx].zone = zone
                self.app._steps[idx].shape = zone.shape
                self.app.zone_locks.forget(self.app._steps[idx].step_id)
                self.app._save_steps()
                self.app.record_mode_tab.render_all()
                self.app.overlay_manager.refresh_step_overlays()

        self.app.open_zone_drawer(step.shape, _done, attach_lock=True)

    def _on_track_capture(self, idx: int) -> None:
        if not (0 <= idx < len(self.app._steps)):
            return
        from modules.clicker import ClickerState
        if self.app.clicker.state != ClickerState.IDLE:
            return

        def _done(zone):
            if zone is None or zone.shape != "rect":
                return
            self._adopt_track_template(idx, zone)

        # Track captures use rect bounds.
        self.app.open_zone_drawer("rect", _done)

    def _grab_zone_png(self, zone, dst_name: str):
        """Grab the screen inside ``zone`` (drawn in Qt DIPs) and write it
        to ``templates/<dst_name>``.

        Returns ``(rel_path, (w, h), (x1, y1, x2, y2))`` with the rect in
        PHYSICAL pixels. mss addresses physical pixels, so on a 150% DPI
        monitor a DIP rect grabbed as-is captured the wrong (smaller,
        offset) region; the conversion goes through ``dpi_cursor`` so it
        matches how the engine moves the cursor.
        """
        import cv2
        import mss
        from ui.config_io import _shot_to_bgr_array
        from utils.dpi_cursor import dip_rect_to_physical
        x1, y1, x2, y2 = zone.aabb()
        x1, x2 = sorted((x1, x2))
        y1, y2 = sorted((y1, y2))
        px, py, pw, ph = dip_rect_to_physical(x1, y1, x2 - x1, y2 - y1)
        if pw < 1 or ph < 1:
            raise ValueError("capture area is empty")
        with mss.mss() as sct:
            shot = sct.grab({"left": px, "top": py, "width": pw, "height": ph})
        bgr = _shot_to_bgr_array(shot)
        tdir = _templates_dir()
        tdir.mkdir(parents=True, exist_ok=True)
        dst = tdir / dst_name
        cv2.imwrite(str(dst), bgr)
        rel = os.path.relpath(str(dst), str(_config_dir())).replace("\\", "/")
        return rel, (int(bgr.shape[1]), int(bgr.shape[0])), (px, py, px + pw, py + ph)

    def _adopt_track_template(self, idx: int, zone) -> None:
        """Capture the screen region inside ``zone`` and save it as this
        step's primary template PNG."""
        if not (0 <= idx < len(self.app._steps)):
            return
        step = self.app._steps[idx]
        try:
            rel, size, phys_rect = self._grab_zone_png(zone, f"{step.step_id}.png")
            step.template_path = rel
            step.template_size = size
            step.capture_rect = phys_rect
            step.capture_rect_space = CAPTURE_SPACE_PHYSICAL
            self.app._save_steps()
            self.app.record_mode_tab.render_all()
            # Push as the live preview for the tracker tick.
            if hasattr(self.app, "tracker_preview"):
                self.app.tracker_preview.set_preview_step(step)
        except Exception as e:
            self.app.toasts.post(f"Capture failed: {e}", kind="danger")

    def _on_track_add_view(self, idx: int) -> None:
        """Capture another look at the same target (rotated NPC, other
        camera angle). Stored beside the primary and matched every frame."""
        if not (0 <= idx < len(self.app._steps)):
            return
        from modules.clicker import ClickerState
        if self.app.clicker.state != ClickerState.IDLE:
            return

        def _done(zone):
            if zone is None or zone.shape != "rect":
                return
            self._adopt_track_view(idx, zone)

        self.app.open_zone_drawer("rect", _done)

    def _adopt_track_view(self, idx: int, zone) -> None:
        if not (0 <= idx < len(self.app._steps)):
            return
        step = self.app._steps[idx]
        try:
            rel, size, _rect = self._grab_zone_png(
                zone, f"{step.step_id}_view_{new_view_id()}.png",
            )
            step.extra_template_paths.append(rel)
            step.extra_template_sizes.append(size)
            self.app._save_steps()
            self.app.record_mode_tab.render_all()
            if hasattr(self.app, "tracker_preview"):
                self.app.tracker_preview.set_preview_step(step)
        except Exception as e:
            self.app.toasts.post(f"View capture failed: {e}", kind="danger")

    def _on_remove_track_view(self, idx: int, view_idx: int,
                              refresh_cb: Callable[[], None]) -> None:
        if not (0 <= idx < len(self.app._steps)):
            return
        step = self.app._steps[idx]
        if not (0 <= view_idx < len(step.extra_template_paths)):
            return
        rel = step.extra_template_paths.pop(view_idx)
        if view_idx < len(step.extra_template_sizes):
            step.extra_template_sizes.pop(view_idx)
        # Delete the PNG only if nothing else (this step's primary, or any
        # other step) still points at it.
        probe = copy.copy(step)
        probe.template_path = rel
        probe.extra_template_paths = []
        if orphaned_template_paths(probe, self.app._steps):
            try:
                self._resolve_template(rel).unlink(missing_ok=True)
            except Exception:
                pass
        self.app._save_steps()
        refresh_cb()
        if hasattr(self.app, "tracker_preview"):
            self.app.tracker_preview.set_preview_step(step)

    def _on_color_pick(self, idx: int) -> None:
        if not (0 <= idx < len(self.app._steps)):
            return
        from modules.clicker import ClickerState
        if self.app.clicker.state != ClickerState.IDLE:
            return

        def _done(result):
            if result is None:
                return
            # ColorPickResult (samples + last_xy) or a legacy (rgb, x, y)
            # tuple; both unpack the same way for the primary.
            (rgb, x, y) = result
            samples = list(getattr(result, "samples", None) or [tuple(rgb)])
            if not (0 <= idx < len(self.app._steps)):
                return
            step = self.app._steps[idx]
            step.color_target_rgb = tuple(int(c) for c in samples[0])
            # Additional eyedropper clicks become alternate accepted colors
            # (gradient shades, anti-aliased edges). Duplicates dropped.
            extras: list[tuple[int, int, int]] = []
            for s in samples[1:]:
                rgb_t = tuple(int(c) for c in s)
                if rgb_t != step.color_target_rgb and rgb_t not in extras:
                    extras.append(rgb_t)
            step.color_extra_rgbs = extras
            # Bound the per-cycle scan to the monitor the pick landed on,
            # in mss physical pixels (the engine grabs with these numbers).
            screen = screen_at_dip(x, y)
            if screen is not None:
                px, py, pw, ph = screen_physical_rect(screen)
                step.color_search_rect = (px, py, px + pw, py + ph)
            else:
                step.color_search_rect = None
            self.app._save_steps()
            self.app.record_mode_tab.render_all()

        self.app.open_color_picker(_done)

    def _on_test(self, idx: int) -> None:
        if 0 <= idx < len(self.app._steps):
            try:
                self.app.clicker.fire_step_once(self.app._steps[idx])
            except Exception as e:
                self.app.toasts.post(f"Test failed: {e}", kind="danger")

    def _on_color_tolerance(self, idx: int, value: int, lbl: QLabel) -> None:
        if not (0 <= idx < len(self.app._steps)):
            return
        self.app._steps[idx].color_tolerance = int(value)
        lbl.setText(str(int(value)))
        self.app.save_steps_later()

    def _on_remove_color_extra(self, idx: int, extra_idx: int,
                               refresh_cb: Callable[[], None]) -> None:
        if not (0 <= idx < len(self.app._steps)):
            return
        extras = self.app._steps[idx].color_extra_rgbs
        if 0 <= extra_idx < len(extras):
            del extras[extra_idx]
            self.app._save_steps()
            refresh_cb()

    def _on_color_zone_draw(self, idx: int) -> None:
        """Restrict where color matches count. Same drawer the Click step
        uses; the engine intersects this zone with the search rect."""
        if not (0 <= idx < len(self.app._steps)):
            return
        from modules.clicker import ClickerState
        if self.app.clicker.state != ClickerState.IDLE:
            return
        step = self.app._steps[idx]

        def _done(zone):
            if zone is None:
                return
            if 0 <= idx < len(self.app._steps):
                self.app._steps[idx].zone = zone
                self.app._steps[idx].shape = zone.shape
                self.app.zone_locks.forget(self.app._steps[idx].step_id)
                self.app._save_steps()
                self.app.record_mode_tab.render_all()
                self.app.overlay_manager.refresh_step_overlays()

        self.app.open_zone_drawer(step.shape or "rect", _done, attach_lock=True)

    def _on_loop_target_change(self, idx: int, target_id) -> None:
        if 0 <= idx < len(self.app._steps) and target_id:
            self.app._steps[idx].loop_target_step_id = str(target_id)
            self.app._save_steps()

    def _on_loop_count_change(self, idx: int, raw: str) -> None:
        if not (0 <= idx < len(self.app._steps)):
            return
        try:
            n = max(0, int(str(raw).strip()))
        except (TypeError, ValueError):
            n = 0
        self.app._steps[idx].loop_count = n
        self.app._save_steps()
