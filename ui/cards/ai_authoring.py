"""AI-mode authoring surface — the in-GUI bot builder.

Each ``AIBotStep`` renders as a collapsible row; the user adds, edits,
reorders, and removes steps here. At Start time the AI tab routes
``app._ai_user_steps`` through :func:`ai.bot.compile_user_bot` to
produce a runnable :class:`Bot` that the runner executes the same way
it executes library bots.

This editor follows the Record-mode StepCard pattern but is more
compact — the goal is feature-complete authoring on day one, not
pixel-perfect parity with Record. The shared design rules:
    * 3-px teal stripe via ``[expanded="true"]`` for the open card.
    * `Expander` owns its own chevron — never bake one into a label.
    * Footer hint: "FIRST-MATCH WINS EACH TICK" — the single most
      important pedagogical signal, since priority-order semantics
      differ from Record's program-counter.
"""

from __future__ import annotations

from typing import List, Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QComboBox, QFrame, QHBoxLayout, QLabel, QLineEdit, QMenu,
    QPushButton, QSizePolicy, QSpinBox, QToolButton, QVBoxLayout,
    QWidget,
)

from ai.bot.authoring import (
    AIBotStep,
    KIND_FIND_ANIMATION_CLICK,
    KIND_FIND_CAPTURE_CLICK,
    KIND_FIND_COLOR_CLICK,
    KIND_FIND_COLOR_KEY,
    KIND_FIND_DTM_CLICK,
    KIND_IF_HP_BELOW,
    KIND_IF_INVENTORY_FULL,
    KIND_IF_ITEM_COUNT,
    KIND_KEY_PRESS,
    KIND_LABELS,
    KIND_LOOP_BACK,
    KIND_UPTEXT_CHECK,
    KIND_WAIT,
    KIND_ZONE_CLICK,
    VALID_KINDS,
    new_step_id,
)
from ai.bot.compiler import rule_name_for

from .. import theme as t
from ..widgets.card import Card
from ..widgets.ios_switch import IOSSwitch


# Order steps appear in the "+ Add step" menu. Deliberate grouping:
# detection actions first (the workhorse of a color bot), then
# control flow, then conditionals.
_ADD_MENU_ORDER: list[tuple[str, str]] = [
    (KIND_FIND_CAPTURE_CLICK, "Find captured snapshot → click  (preferred for static targets)"),
    (KIND_ZONE_CLICK, "Click in zone  (random point in a drawn area)"),
    (KIND_FIND_ANIMATION_CLICK, "Find animation → click  (e.g. fishing spot)"),
    ("__sep__", ""),
    (KIND_FIND_COLOR_CLICK, "Find color → click"),
    (KIND_FIND_COLOR_KEY, "Find color → press key"),
    (KIND_FIND_DTM_CLICK, "Find DTM template → click"),
    ("__sep__", ""),
    (KIND_WAIT, "Wait"),
    (KIND_KEY_PRESS, "Press key"),
    ("__sep__", ""),
    (KIND_IF_INVENTORY_FULL, "If inventory full"),
    (KIND_IF_HP_BELOW, "If HP below %"),
    (KIND_IF_ITEM_COUNT, "If item count …"),
    (KIND_UPTEXT_CHECK, "Check uptext"),
    (KIND_LOOP_BACK, "Loop back"),
]


class AIAuthoringSection(Card):
    """The full step-list editor card."""

    stepsChanged = Signal()

    def __init__(self, app) -> None:
        super().__init__("Custom bot steps")
        self.app = app
        self._active_bundle = None

        # Header — "+ Add step" menu (becomes a submenu so we can group).
        self.add_btn = QPushButton("+  Add step")
        self.add_btn.setMinimumHeight(t.BUTTON_H)
        self.add_btn.setCursor(Qt.PointingHandCursor)
        self.add_btn.setProperty("variant", "accent")
        menu = QMenu(self.add_btn)
        for kind, label in _ADD_MENU_ORDER:
            if kind == "__sep__":
                menu.addSeparator()
                continue
            act = menu.addAction(label)
            act.triggered.connect(
                lambda _checked=False, k=kind: self._on_add_step(k)
            )
        self.add_btn.setMenu(menu)
        self.add_to_header(self.add_btn)

        # Items library — small panel, can be collapsed.
        self._items_panel = _ItemLibraryPanel(app, self)
        self.add(self._items_panel)

        # Body container — vertical list of step rows.
        self._rows_host = QWidget()
        self._rows_layout = QVBoxLayout(self._rows_host)
        self._rows_layout.setContentsMargins(0, 0, 0, 0)
        self._rows_layout.setSpacing(t.SP_SM)
        self.add(self._rows_host)

        # Empty-state hint.
        self._empty_hint = QLabel(
            "No steps yet. Click ‘+ Add step’ to start building. "
            "Steps run top-to-bottom each tick — the first one that "
            "fires wins the tick (other steps run on later ticks)."
        )
        self._empty_hint.setWordWrap(True)
        self._empty_hint.setStyleSheet(
            f"color: {t.TEXT_TERTIARY}; "
            f"font-size: {t.SIZE_SM}px; padding: 12px 4px;"
        )
        self.add(self._empty_hint)

        # Lock banner — shown when bot is running. Edits to the live
        # bot snapshot don't take effect until the user stops + restarts.
        self._lock_banner = QLabel(
            "🔒 Bot is running — changes apply on next start."
        )
        self._lock_banner.setStyleSheet(
            f"color: {t.WARN}; font-size: {t.SIZE_SM}px; "
            f"padding: 6px 8px; border-radius: 6px; "
            f"background: rgba(245, 158, 11, 0.10);"
        )
        self._lock_banner.setVisible(False)
        self.add(self._lock_banner)

        # Footer hint — the single most important pedagogical signal.
        footer = QLabel(
            "↻  FIRST-MATCH WINS EACH TICK · priority = step order"
        )
        footer.setAlignment(Qt.AlignCenter)
        footer.setStyleSheet(
            f"color: {t.ACCENT}; "
            f"font-size: {t.SIZE_SM}px; "
            f"font-weight: 500; "
            f"letter-spacing: 1px; "
            f"padding: 8px 0;"
        )
        self.add(footer)

        self.render_all()

    # ── Bundle awareness ─────────────────────────────────────────
    def _on_active_bundle_changed(self, bundle) -> None:
        """The active bundle changed — relabel the card so users know
        whether they're editing a bundle's procedure or the legacy
        cfg-backed steps. The data source itself is swapped by
        ``App.set_ai_authoring_bundle`` before this hook fires."""
        self._active_bundle = bundle
        if bundle is None:
            self._empty_hint.setText(
                "No steps yet. Click '+ Add step' to start building. "
                "Steps run top-to-bottom each tick — the first one that "
                "fires wins the tick (other steps run on later ticks)."
            )
        else:
            entry = str(bundle.procedures.get("entry") or "main")
            self._empty_hint.setText(
                f"Editing bundle {bundle.name!r} → procedure {entry!r}. "
                f"Add steps with '+ Add step'. Procedures + interrupts "
                f"can be authored by hand-editing "
                f"{bundle.root / 'procedures.json'} for v1."
            )
        self.render_all()

    # ── Public API ──────────────────────────────────────────────
    def render_all(self) -> None:
        """Rebuild the row list from ``app._ai_user_steps``."""
        # Clear existing rows.
        while self._rows_layout.count():
            item = self._rows_layout.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()

        steps: list[AIBotStep] = list(getattr(self.app, "_ai_user_steps", []))
        self._empty_hint.setVisible(not steps)
        for i, step in enumerate(steps):
            row = _StepRow(self.app, self, step, index=i, total=len(steps))
            self._rows_layout.addWidget(row)

    def set_running(self, running: bool) -> None:
        """Toggle the locked-banner; called by AIPageBody."""
        self._lock_banner.setVisible(bool(running))

    # ── Slots ────────────────────────────────────────────────────
    def _on_add_step(self, kind: str) -> None:
        if kind not in VALID_KINDS:
            return
        step = AIBotStep(kind=kind, step_id=new_step_id())
        self.app._ai_user_steps.append(step)
        self.app._save_ai_user_steps()
        self.render_all()
        self.stepsChanged.emit()

    def remove_step(self, step_id: str) -> None:
        steps = list(self.app._ai_user_steps)
        self.app._ai_user_steps = [s for s in steps if s.step_id != step_id]
        self.app._save_ai_user_steps()
        self.render_all()
        self.stepsChanged.emit()

    def duplicate_step(self, step_id: str) -> None:
        steps = list(self.app._ai_user_steps)
        for i, s in enumerate(steps):
            if s.step_id == step_id:
                # Deep-copy via JSON round-trip so we don't share lists.
                from copy import deepcopy
                copy = deepcopy(s)
                copy.step_id = new_step_id()
                if copy.label:
                    copy.label = (copy.label + " (copy)")[:80]
                steps.insert(i + 1, copy)
                self.app._ai_user_steps = steps
                self.app._save_ai_user_steps()
                self.render_all()
                self.stepsChanged.emit()
                return

    def move_step(self, step_id: str, delta: int) -> None:
        steps = list(self.app._ai_user_steps)
        for i, s in enumerate(steps):
            if s.step_id == step_id:
                j = max(0, min(len(steps) - 1, i + delta))
                if i == j:
                    return
                steps.pop(i)
                steps.insert(j, s)
                self.app._ai_user_steps = steps
                self.app._save_ai_user_steps()
                self.render_all()
                self.stepsChanged.emit()
                return

    def step_changed(self) -> None:
        """A child row notifies it edited a field; persist and refresh."""
        self.app._save_ai_user_steps()
        self.stepsChanged.emit()

    # ── Per-step Test ────────────────────────────────────────────
    def test_step(self, step) -> None:
        """Fire ``step`` once in a transient ctx with dry_run=True.

        The runner machinery isn't started — we capture one frame,
        compile the step's closure, run it. Result is toasted so the
        author can iterate on detection params without the full
        Start → watch → Stop cycle.
        """
        from ai.bot import api as _api
        from ai.bot.compiler import _compile_step
        from ai.graph.runtime import RuntimeContext
        import mss
        import numpy as np
        import time

        bundle = getattr(self, "_active_bundle", None)

        # Capture a fresh frame from the configured AI monitor.
        try:
            with mss.mss() as sct:
                mons = sct.monitors
                idx = int(self.app.cfg.get("ai_monitor", 1))
                if not (0 <= idx < len(mons)):
                    idx = 1 if len(mons) > 1 else 0
                raw = sct.grab(mons[idx])
                frame = np.ascontiguousarray(
                    np.asarray(raw, dtype=np.uint8)[:, :, :3]
                )
        except Exception as e:
            self.app.toasts.post(
                f"⚠ Test capture failed: {type(e).__name__}: {e}",
                kind="error",
            )
            return

        # Compile the step closure (dry-run via ctx).
        closure, errs = _compile_step(step, step_index=0, bundle=bundle)
        if closure is None:
            for e in errs:
                self.app.toasts.post(f"⚠ {e}", kind="warn")
            return

        # Build a transient ctx + WorldState so primitives have what they need.
        from ai.bot.world import build_world
        ctx = RuntimeContext(log_fn=lambda m: None, input_backend=None,
                              dry_run=True)
        # Pull world calibration from active bundle (or cfg fallback).
        if bundle is not None:
            cal = bundle.calibration or {}
            ctx._world_calibration = {
                "inventory_rect": cal.get("inventory_rect"),
                "orbs_rect": cal.get("orbs_rect") or cal.get("bars_rect"),
                "minimap_rect": cal.get("minimap_rect"),
                "orbs_max_fill": dict(cal.get("orbs_max_fill") or {}),
            }
        else:
            ctx._world_calibration = {}
        ctx.current_frame = frame
        ctx.world = build_world(ctx, frame, tick=1)

        # Stub input_backend so click.at routes to a no-op (dry_run
        # already short-circuits but be defensive).
        class _DryBackend:
            def click(self, x, y, button="left"): _DryBackend.last_click = (x, y, button)
            def move(self, x, y): pass
            def press_key(self, k): _DryBackend.last_key = k
            last_click = None
            last_key = None
        ctx.input_backend = _DryBackend()

        token = _api._set_ctx(ctx)
        t0 = time.perf_counter()
        try:
            try:
                fired = bool(closure())
            except Exception as e:
                self.app.toasts.post(
                    f"⚠ Test crashed: {type(e).__name__}: {e}",
                    kind="error",
                )
                return
        finally:
            _api._reset_ctx(token)
        elapsed_ms = (time.perf_counter() - t0) * 1000.0

        # Build result message
        backend = ctx.input_backend
        if fired:
            click_info = ""
            if getattr(backend, "last_click", None):
                x, y, _b = backend.last_click
                click_info = f"  → click ({x}, {y})"
            elif getattr(backend, "last_key", None):
                click_info = f"  → key {backend.last_key!r}"
            self.app.toasts.post(
                f"✓ Step fired in {elapsed_ms:.1f} ms{click_info}",
                kind="success",
            )
        else:
            self.app.toasts.post(
                f"✗ Step did NOT fire ({elapsed_ms:.1f} ms — no detection match / "
                "predicate False)",
                kind="warn",
            )


# ─────────────────────────────────────────────────────────────────
# Step row
# ─────────────────────────────────────────────────────────────────


class _StepRow(QFrame):
    """One step's collapsible row."""

    def __init__(
        self, app, parent: AIAuthoringSection,
        step: AIBotStep, *, index: int, total: int,
    ) -> None:
        super().__init__()
        self.app = app
        self.parent_section = parent
        self.step = step
        self.index = index
        self.total = total

        self.setObjectName("aibot-step-row")
        self.setProperty("role", "step-card")
        self.setProperty("expanded", "false")
        self.setStyleSheet(
            f"QFrame#aibot-step-row {{"
            f"  background: {t.SURFACE_PANEL}; "
            f"  border: 1px solid {t.BORDER_SUBTLE}; "
            f"  border-radius: 8px; "
            f"}}"
            f"QFrame#aibot-step-row[expanded=\"true\"] {{"
            f"  border-left: 3px solid {t.ACCENT}; "
            f"}}"
        )

        outer = QVBoxLayout(self)
        outer.setContentsMargins(t.SP_SM, t.SP_SM, t.SP_SM, t.SP_SM)
        outer.setSpacing(t.SP_SM)

        # ── Header row ──────────────────────────────────────
        header = QWidget()
        h = QHBoxLayout(header)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(t.SP_SM)

        self._chevron = QToolButton()
        self._chevron.setText("▸")
        self._chevron.setAutoRaise(True)
        self._chevron.setCursor(Qt.PointingHandCursor)
        self._chevron.clicked.connect(self._toggle_expanded)
        h.addWidget(self._chevron)

        idx_lbl = QLabel(f"{index + 1}.")
        idx_lbl.setStyleSheet(
            f"color: {t.TEXT_TERTIARY}; "
            f"font-size: {t.SIZE_BODY}px; "
            f"font-weight: 600; "
            f"min-width: 24px;"
        )
        h.addWidget(idx_lbl)

        kind_lbl = QLabel(KIND_LABELS.get(step.kind, step.kind).upper())
        kind_lbl.setStyleSheet(
            f"color: {t.ACCENT}; "
            f"font-size: 11px; "
            f"font-weight: 700; "
            f"letter-spacing: 0.5px;"
        )
        h.addWidget(kind_lbl)

        self._summary = QLabel(self._summary_text())
        self._summary.setStyleSheet(
            f"color: {t.TEXT_SECONDARY}; "
            f"font-size: {t.SIZE_BODY}px;"
        )
        h.addWidget(self._summary, 1)

        # Action buttons — up, down, duplicate, remove.
        for label, tip, delta in [("▲", "Move up", -1), ("▼", "Move down", +1)]:
            b = QToolButton()
            b.setText(label)
            b.setToolTip(tip)
            b.setAutoRaise(True)
            b.setCursor(Qt.PointingHandCursor)
            b.clicked.connect(
                lambda _checked=False, d=delta: self.parent_section.move_step(self.step.step_id, d)
            )
            h.addWidget(b)
        dup_btn = QToolButton()
        dup_btn.setText("⎘")
        dup_btn.setToolTip("Duplicate step")
        dup_btn.setAutoRaise(True)
        dup_btn.setCursor(Qt.PointingHandCursor)
        dup_btn.clicked.connect(
            lambda: self.parent_section.duplicate_step(self.step.step_id)
        )
        h.addWidget(dup_btn)
        rm_btn = QToolButton()
        rm_btn.setText("✕")
        rm_btn.setToolTip("Remove step")
        rm_btn.setAutoRaise(True)
        rm_btn.setCursor(Qt.PointingHandCursor)
        rm_btn.clicked.connect(
            lambda: self.parent_section.remove_step(self.step.step_id)
        )
        h.addWidget(rm_btn)

        # Per-step enable.
        self._switch = IOSSwitch()
        self._switch.setChecked(bool(step.enabled))
        self._switch.toggled.connect(self._on_enabled_toggled)
        h.addWidget(self._switch)

        outer.addWidget(header)

        # ── Body (collapsed by default) ─────────────────────
        self._body = QWidget()
        body_layout = QVBoxLayout(self._body)
        body_layout.setContentsMargins(0, 4, 0, 0)
        body_layout.setSpacing(t.SP_SM)

        # Common: editable label + phase.
        body_layout.addWidget(
            self._make_label_row("Label", step.label,
                                  on_change=self._on_label_changed,
                                  placeholder=rule_name_for(step))
        )
        body_layout.addWidget(
            self._make_label_row("Phase", step.phase,
                                  on_change=self._on_phase_changed,
                                  placeholder="optional — drives chip color")
        )

        # Per-kind body.
        kbody = self._build_kind_body()
        if kbody is not None:
            body_layout.addWidget(kbody)

        # After-action wait + Test button for kinds that perform an action.
        if step.kind in (
            KIND_FIND_COLOR_CLICK, KIND_FIND_COLOR_KEY, KIND_FIND_DTM_CLICK,
            KIND_FIND_ANIMATION_CLICK, KIND_FIND_CAPTURE_CLICK, KIND_ZONE_CLICK,
            KIND_KEY_PRESS,
        ):
            body_layout.addWidget(self._build_after_wait_row())
            body_layout.addWidget(self._build_test_row())

        self._body.setVisible(False)
        outer.addWidget(self._body)

    # ── Header / body interaction ─────────────────────────────
    def _toggle_expanded(self) -> None:
        new = not self._body.isVisible()
        self._body.setVisible(new)
        self._chevron.setText("▾" if new else "▸")
        self.setProperty("expanded", "true" if new else "false")
        # Re-polish so the QSS [expanded="true"] selector lands.
        self.style().unpolish(self)
        self.style().polish(self)

    def _summary_text(self) -> str:
        s = self.step
        if s.kind == KIND_FIND_COLOR_CLICK or s.kind == KIND_FIND_COLOR_KEY:
            rgb = s.color_target_rgb
            hex_s = (
                f"#{rgb[0]:02X}{rgb[1]:02X}{rgb[2]:02X}" if rgb else "(no colour)"
            )
            extra = f"  →  {s.key_combo!r}" if s.kind == KIND_FIND_COLOR_KEY and s.key_combo else ""
            return f"{hex_s}  tol={s.color_tolerance}  min={s.color_min_pixels}{extra}"
        if s.kind == KIND_FIND_DTM_CLICK:
            return s.dtm_template_path or "(no template)"
        if s.kind == KIND_FIND_ANIMATION_CLICK:
            roi_s = self._roi_text_str()
            return f"{roi_s}  win={s.anim_window_frames} flick≥{s.anim_min_flickers}"
        if s.kind == KIND_FIND_CAPTURE_CLICK:
            cap = s.capture_name or "(no capture)"
            return f"{cap}  thr={int(s.capture_match_threshold * 100)}%"
        if s.kind == KIND_ZONE_CLICK:
            return self._zone_text_str()
        if s.kind == KIND_IF_ITEM_COUNT:
            tgt = "→ run another step" if s.branch_target_step_id else "(predicate only)"
            return f"{s.item_name!r}  {s.item_count_op} {s.item_count_threshold}  {tgt}"
        if s.kind == KIND_WAIT:
            return f"{s.wait_min_ms}–{s.wait_max_ms} ms"
        if s.kind == KIND_KEY_PRESS:
            return f"{s.key_combo or '(no key)'}  ×{s.key_repeat}"
        if s.kind == KIND_IF_INVENTORY_FULL:
            tgt = "→ run another step" if s.branch_target_step_id else "(predicate only)"
            return f"≥{s.inventory_threshold} filled  {tgt}"
        if s.kind == KIND_IF_HP_BELOW:
            tgt = "→ run another step" if s.branch_target_step_id else "(predicate only)"
            return f"<{s.hp_threshold_pct}%  {tgt}"
        if s.kind == KIND_LOOP_BACK:
            return "forever" if s.loop_count == 0 else f"next {s.loop_count} ticks"
        if s.kind == KIND_UPTEXT_CHECK:
            return f"{'regex' if s.uptext_is_regex else 'contains'} {s.uptext_pattern!r}"
        return ""

    def _refresh_summary(self) -> None:
        self._summary.setText(self._summary_text())

    # ── Body builders ────────────────────────────────────────
    def _build_kind_body(self) -> Optional[QWidget]:
        kind = self.step.kind
        if kind in (KIND_FIND_COLOR_CLICK, KIND_FIND_COLOR_KEY):
            return self._build_color_body(with_key=(kind == KIND_FIND_COLOR_KEY))
        if kind == KIND_FIND_DTM_CLICK:
            return self._build_dtm_body()
        if kind == KIND_FIND_ANIMATION_CLICK:
            return self._build_animation_body()
        if kind == KIND_FIND_CAPTURE_CLICK:
            return self._build_capture_click_body()
        if kind == KIND_ZONE_CLICK:
            return self._build_zone_click_body()
        if kind == KIND_WAIT:
            return self._build_wait_body()
        if kind == KIND_KEY_PRESS:
            return self._build_key_body()
        if kind == KIND_IF_INVENTORY_FULL:
            return self._build_if_inventory_body()
        if kind == KIND_IF_HP_BELOW:
            return self._build_if_hp_body()
        if kind == KIND_IF_ITEM_COUNT:
            return self._build_if_item_count_body()
        if kind == KIND_LOOP_BACK:
            return self._build_loop_body()
        if kind == KIND_UPTEXT_CHECK:
            return self._build_uptext_body()
        return None

    def _build_color_body(self, *, with_key: bool) -> QWidget:
        wrap = QWidget()
        v = QVBoxLayout(wrap)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(t.SP_XS)

        # Pick colour row.
        row = QWidget()
        rl = QHBoxLayout(row)
        rl.setContentsMargins(0, 0, 0, 0)
        rl.setSpacing(t.SP_SM)
        rl.addWidget(self._field_label("Colour"))

        self._color_swatch = QLabel()
        self._color_swatch.setFixedSize(36, 24)
        self._refresh_swatch()
        rl.addWidget(self._color_swatch)

        self._color_text = QLabel(self._color_text_str())
        self._color_text.setStyleSheet(
            f"color: {t.TEXT_SECONDARY}; "
            f"font-family: {t.FONT_MONO}; "
            f"font-size: {t.SIZE_SM}px;"
        )
        rl.addWidget(self._color_text)
        rl.addStretch(1)

        pick_btn = QPushButton("Pick from screen")
        pick_btn.setMinimumHeight(t.BUTTON_H)
        pick_btn.setCursor(Qt.PointingHandCursor)
        pick_btn.clicked.connect(self._on_pick_color)
        rl.addWidget(pick_btn)
        v.addWidget(row)

        # Tolerance + min-pixels — two spinboxes side by side.
        knobs = QWidget()
        kl = QHBoxLayout(knobs)
        kl.setContentsMargins(0, 0, 0, 0)
        kl.setSpacing(t.SP_SM)
        kl.addWidget(self._field_label("Tolerance"))
        self._tol_spin = QSpinBox()
        self._tol_spin.setRange(0, 100)
        self._tol_spin.setValue(int(self.step.color_tolerance))
        self._tol_spin.valueChanged.connect(self._on_tol_changed)
        kl.addWidget(self._tol_spin)
        kl.addSpacing(12)
        kl.addWidget(self._field_label("Min pixels"))
        self._minpx_spin = QSpinBox()
        self._minpx_spin.setRange(1, 5000)
        self._minpx_spin.setValue(int(self.step.color_min_pixels))
        self._minpx_spin.valueChanged.connect(self._on_min_pix_changed)
        kl.addWidget(self._minpx_spin)
        kl.addStretch(1)
        v.addWidget(knobs)

        # ROI row — "Set ROI" button + caption.
        roi_row = QWidget()
        rr = QHBoxLayout(roi_row)
        rr.setContentsMargins(0, 0, 0, 0)
        rr.setSpacing(t.SP_SM)
        rr.addWidget(self._field_label("ROI"))
        self._roi_caption = QLabel(self._roi_text_str())
        self._roi_caption.setStyleSheet(
            f"color: {t.TEXT_SECONDARY}; "
            f"font-family: {t.FONT_MONO}; "
            f"font-size: {t.SIZE_SM}px;"
        )
        rr.addWidget(self._roi_caption)
        rr.addStretch(1)
        roi_btn = QPushButton("Set ROI")
        roi_btn.setMinimumHeight(t.BUTTON_H)
        roi_btn.setCursor(Qt.PointingHandCursor)
        roi_btn.clicked.connect(self._on_set_roi)
        rr.addWidget(roi_btn)
        if self.step.roi:
            clr_btn = QPushButton("Clear")
            clr_btn.setMinimumHeight(t.BUTTON_H)
            clr_btn.setCursor(Qt.PointingHandCursor)
            clr_btn.clicked.connect(self._on_clear_roi)
            rr.addWidget(clr_btn)
        v.addWidget(roi_row)

        if with_key:
            v.addWidget(self._build_key_combo_row())

        return wrap

    def _build_dtm_body(self) -> QWidget:
        wrap = QWidget()
        v = QVBoxLayout(wrap)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(t.SP_XS)
        v.addWidget(self._make_label_row(
            "Template path", self.step.dtm_template_path or "",
            on_change=self._on_dtm_path_changed,
            placeholder="templates/dtm/your_template.yaml",
        ))
        return wrap

    def _build_animation_body(self) -> QWidget:
        wrap = QWidget()
        v = QVBoxLayout(wrap)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(t.SP_XS)

        # ROI is REQUIRED for animation. Reuse the color-body ROI row.
        roi_row = QWidget()
        rr = QHBoxLayout(roi_row)
        rr.setContentsMargins(0, 0, 0, 0)
        rr.setSpacing(t.SP_SM)
        rr.addWidget(self._field_label("Search area"))
        cap = QLabel(self._roi_text_str())
        cap.setStyleSheet(
            f"color: {t.TEXT_SECONDARY}; "
            f"font-family: {t.FONT_MONO}; "
            f"font-size: {t.SIZE_SM}px;"
        )
        self._roi_caption = cap
        rr.addWidget(cap)
        rr.addStretch(1)
        roi_btn = QPushButton("Set ROI" if self.step.roi is None else "Change ROI")
        roi_btn.setMinimumHeight(t.BUTTON_H)
        roi_btn.setCursor(Qt.PointingHandCursor)
        roi_btn.clicked.connect(self._on_set_roi)
        rr.addWidget(roi_btn)
        v.addWidget(roi_row)

        # Window + min flickers spinboxes.
        knobs = QWidget()
        kl = QHBoxLayout(knobs)
        kl.setContentsMargins(0, 0, 0, 0)
        kl.setSpacing(t.SP_SM)
        kl.addWidget(self._field_label("Window (frames)"))
        win_spin = QSpinBox()
        win_spin.setRange(2, 30)
        win_spin.setValue(int(self.step.anim_window_frames))
        win_spin.valueChanged.connect(self._on_anim_window_changed)
        kl.addWidget(win_spin)
        kl.addSpacing(12)
        kl.addWidget(self._field_label("Min flickers"))
        flick_spin = QSpinBox()
        flick_spin.setRange(1, 20)
        flick_spin.setValue(int(self.step.anim_min_flickers))
        flick_spin.valueChanged.connect(self._on_anim_flickers_changed)
        kl.addWidget(flick_spin)
        kl.addStretch(1)
        v.addWidget(knobs)

        hint = QLabel(
            "Detects regions whose pixels flicker over the window — "
            "fishing spots (bubble surface), hunter trap motion, etc. "
            "Tighten the ROI to the exact area you expect activity in; "
            "wider ROIs catch more noise (camera pan, NPC walks)."
        )
        hint.setWordWrap(True)
        hint.setStyleSheet(
            f"color: {t.TEXT_TERTIARY}; font-size: {t.SIZE_SM}px;"
        )
        v.addWidget(hint)
        return wrap

    def _build_capture_click_body(self) -> QWidget:
        wrap = QWidget()
        v = QVBoxLayout(wrap)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(t.SP_XS)

        # Asset dropdown — populated from the active bundle's snapshots.
        row = QWidget()
        rl = QHBoxLayout(row)
        rl.setContentsMargins(0, 0, 0, 0)
        rl.setSpacing(t.SP_SM)
        rl.addWidget(self._field_label("Capture"))
        cb = QComboBox()
        bundle = getattr(self.parent_section, "_active_bundle", None)
        snapshots = bundle.list_snapshots() if bundle is not None else []
        if not snapshots:
            cb.addItem(
                "(no snapshots yet — capture one in the Captures section)", "",
            )
        else:
            cb.addItem("(choose snapshot)", "")
            for p in snapshots:
                cb.addItem(p.stem, p.stem)
        # Restore current selection
        idx = 0
        for i in range(cb.count()):
            if cb.itemData(i) == self.step.capture_name:
                idx = i
                break
        cb.setCurrentIndex(idx)
        cb.currentIndexChanged.connect(
            lambda _i, c=cb: self._on_capture_name_changed(c.currentData() or "")
        )
        rl.addWidget(cb, 1)
        v.addWidget(row)

        # Match threshold (0.1..1.0).
        thr_row = QWidget()
        tr = QHBoxLayout(thr_row)
        tr.setContentsMargins(0, 0, 0, 0)
        tr.setSpacing(t.SP_SM)
        tr.addWidget(self._field_label("Match threshold"))
        spin = QSpinBox()
        spin.setRange(10, 100)
        spin.setSuffix(" %")
        spin.setValue(int(round(self.step.capture_match_threshold * 100)))
        spin.valueChanged.connect(self._on_capture_threshold_changed)
        tr.addWidget(spin)
        tr.addStretch(1)
        v.addWidget(thr_row)

        # Optional ROI — restricts the search area, faster + more precise.
        roi_row = QWidget()
        rr = QHBoxLayout(roi_row)
        rr.setContentsMargins(0, 0, 0, 0)
        rr.setSpacing(t.SP_SM)
        rr.addWidget(self._field_label("Search area"))
        cap = QLabel(self._roi_text_str())
        cap.setStyleSheet(
            f"color: {t.TEXT_SECONDARY}; "
            f"font-family: {t.FONT_MONO}; "
            f"font-size: {t.SIZE_SM}px;"
        )
        self._roi_caption = cap
        rr.addWidget(cap)
        rr.addStretch(1)
        roi_btn = QPushButton(
            "Set ROI" if self.step.roi is None else "Change ROI"
        )
        roi_btn.setMinimumHeight(t.BUTTON_H)
        roi_btn.setCursor(Qt.PointingHandCursor)
        roi_btn.clicked.connect(self._on_set_roi)
        rr.addWidget(roi_btn)
        if self.step.roi:
            clr = QPushButton("Clear")
            clr.setMinimumHeight(t.BUTTON_H)
            clr.setCursor(Qt.PointingHandCursor)
            clr.clicked.connect(self._on_clear_roi)
            rr.addWidget(clr)
        v.addWidget(roi_row)

        hint = QLabel(
            "Template-matches the chosen snapshot against the screen. "
            "Best for static UI / scenery where colour alone won't "
            "identify the target. Tighter Search area = faster + fewer "
            "false matches."
        )
        hint.setWordWrap(True)
        hint.setStyleSheet(
            f"color: {t.TEXT_TERTIARY}; font-size: {t.SIZE_SM}px;"
        )
        v.addWidget(hint)
        return wrap

    def _build_zone_click_body(self) -> QWidget:
        wrap = QWidget()
        v = QVBoxLayout(wrap)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(t.SP_XS)

        # Shape picker.
        shape_row = QWidget()
        sr = QHBoxLayout(shape_row)
        sr.setContentsMargins(0, 0, 0, 0)
        sr.setSpacing(t.SP_SM)
        sr.addWidget(self._field_label("Shape"))
        cb = QComboBox()
        for label, val in (("Rectangle", "rect"), ("Circle", "circle"),
                            ("Polygon", "polygon")):
            cb.addItem(label, val)
        # Restore current
        cur_shape = (self.step.zone_json or {}).get("shape") or "rect"
        for i in range(cb.count()):
            if cb.itemData(i) == cur_shape:
                cb.setCurrentIndex(i)
                break
        cb.currentIndexChanged.connect(
            lambda _i, c=cb: self._on_zone_shape_changed(c.currentData() or "rect")
        )
        sr.addWidget(cb)
        sr.addStretch(1)
        v.addWidget(shape_row)

        # Set / clear zone + caption.
        zone_row = QWidget()
        zr = QHBoxLayout(zone_row)
        zr.setContentsMargins(0, 0, 0, 0)
        zr.setSpacing(t.SP_SM)
        zr.addWidget(self._field_label("Zone"))
        cap = QLabel(self._zone_text_str())
        cap.setStyleSheet(
            f"color: {t.TEXT_SECONDARY}; "
            f"font-family: {t.FONT_MONO}; "
            f"font-size: {t.SIZE_SM}px;"
        )
        self._zone_caption = cap
        zr.addWidget(cap)
        zr.addStretch(1)
        set_btn = QPushButton(
            "Set zone" if self.step.zone_json is None else "Redraw zone"
        )
        set_btn.setMinimumHeight(t.BUTTON_H)
        set_btn.setCursor(Qt.PointingHandCursor)
        set_btn.clicked.connect(self._on_set_zone)
        zr.addWidget(set_btn)
        if self.step.zone_json is not None:
            clr = QPushButton("Clear")
            clr.setMinimumHeight(t.BUTTON_H)
            clr.setCursor(Qt.PointingHandCursor)
            clr.clicked.connect(self._on_clear_zone)
            zr.addWidget(clr)
        v.addWidget(zone_row)

        hint = QLabel(
            "Picks a random point inside the drawn area and clicks. "
            "Best for static targets at a known screen position "
            "(bank chest, action-bar buttons, fixed UI). Pair with a "
            "Verify check (uptext_match or inv_change) to catch the "
            "rare case where the world isn't where you expect."
        )
        hint.setWordWrap(True)
        hint.setStyleSheet(
            f"color: {t.TEXT_TERTIARY}; font-size: {t.SIZE_SM}px;"
        )
        v.addWidget(hint)
        return wrap

    def _zone_text_str(self) -> str:
        z = self.step.zone_json
        if not z:
            return "no zone drawn"
        shape = z.get("shape") or "?"
        if shape == "rect" and z.get("rect"):
            x1, y1, x2, y2 = z["rect"]
            return f"rect  {abs(x2-x1)}×{abs(y2-y1)}  @ ({min(x1,x2)},{min(y1,y2)})"
        if shape == "circle" and z.get("circle"):
            cx, cy, r = z["circle"]
            return f"circle  r={r}  @ ({cx},{cy})"
        if shape == "polygon" and z.get("vertices"):
            n = len(z["vertices"])
            return f"polygon  {n} vertices"
        return shape

    def _build_if_item_count_body(self) -> QWidget:
        wrap = QWidget()
        v = QVBoxLayout(wrap)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(t.SP_XS)

        # Item picker — combobox of items in the bot's library.
        row = QWidget()
        rl = QHBoxLayout(row)
        rl.setContentsMargins(0, 0, 0, 0)
        rl.setSpacing(t.SP_SM)
        rl.addWidget(self._field_label("Item"))
        cb = QComboBox()
        items = list(getattr(self.app, "_ai_item_names", []))
        if not items:
            cb.addItem("(library is empty — add items below)", "")
        else:
            cb.addItem("(none)", "")
            for nm in items:
                cb.addItem(nm, nm)
        # Restore.
        idx = 0
        for i in range(cb.count()):
            if cb.itemData(i) == self.step.item_name:
                idx = i
                break
        cb.setCurrentIndex(idx)
        cb.currentIndexChanged.connect(
            lambda _i, c=cb: self._on_item_name_changed(c.currentData() or "")
        )
        rl.addWidget(cb, 1)
        v.addWidget(row)

        # Op + threshold.
        row2 = QWidget()
        rl2 = QHBoxLayout(row2)
        rl2.setContentsMargins(0, 0, 0, 0)
        rl2.setSpacing(t.SP_SM)
        rl2.addWidget(self._field_label("Predicate"))
        op_cb = QComboBox()
        for op in (">=", "<=", "==", ">", "<"):
            op_cb.addItem(op, op)
        for i in range(op_cb.count()):
            if op_cb.itemData(i) == self.step.item_count_op:
                op_cb.setCurrentIndex(i)
                break
        op_cb.currentIndexChanged.connect(
            lambda _i, c=op_cb: self._on_item_op_changed(c.currentData())
        )
        rl2.addWidget(op_cb)
        thr_spin = QSpinBox()
        thr_spin.setRange(0, 28)
        thr_spin.setValue(int(self.step.item_count_threshold))
        thr_spin.valueChanged.connect(self._on_item_threshold_changed)
        rl2.addWidget(thr_spin)
        rl2.addStretch(1)
        v.addWidget(row2)

        v.addWidget(self._build_branch_target_combo())

        hint = QLabel(
            "Counts inventory slots whose contents match the named "
            "wiki item. Requires Inventory ROI calibrated and the item "
            "added to the bot's library (panel below)."
        )
        hint.setWordWrap(True)
        hint.setStyleSheet(
            f"color: {t.TEXT_TERTIARY}; font-size: {t.SIZE_SM}px;"
        )
        v.addWidget(hint)
        return wrap

    def _build_wait_body(self) -> QWidget:
        wrap = QWidget()
        h = QHBoxLayout(wrap)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(t.SP_SM)
        h.addWidget(self._field_label("Wait (ms)"))
        self._wait_min = QSpinBox()
        self._wait_min.setRange(0, 600000)
        self._wait_min.setValue(int(self.step.wait_min_ms))
        self._wait_min.valueChanged.connect(self._on_wait_min_changed)
        h.addWidget(self._wait_min)
        h.addWidget(QLabel("–"))
        self._wait_max = QSpinBox()
        self._wait_max.setRange(0, 600000)
        self._wait_max.setValue(int(self.step.wait_max_ms))
        self._wait_max.valueChanged.connect(self._on_wait_max_changed)
        h.addWidget(self._wait_max)
        h.addStretch(1)
        return wrap

    def _build_key_body(self) -> QWidget:
        wrap = QWidget()
        v = QVBoxLayout(wrap)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(t.SP_XS)
        v.addWidget(self._build_key_combo_row())

        rep_row = QWidget()
        rl = QHBoxLayout(rep_row)
        rl.setContentsMargins(0, 0, 0, 0)
        rl.setSpacing(t.SP_SM)
        rl.addWidget(self._field_label("Repeat"))
        self._key_rep = QSpinBox()
        self._key_rep.setRange(1, 20)
        self._key_rep.setValue(int(self.step.key_repeat))
        self._key_rep.valueChanged.connect(self._on_key_repeat_changed)
        rl.addWidget(self._key_rep)
        rl.addStretch(1)
        v.addWidget(rep_row)
        return wrap

    def _build_key_combo_row(self) -> QWidget:
        return self._make_label_row(
            "Key combo", self.step.key_combo,
            on_change=self._on_key_combo_changed,
            placeholder="e.g. f1, ctrl+shift+z",
            mono=True,
        )

    def _build_if_inventory_body(self) -> QWidget:
        wrap = QWidget()
        v = QVBoxLayout(wrap)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(t.SP_XS)

        row = QWidget()
        rl = QHBoxLayout(row)
        rl.setContentsMargins(0, 0, 0, 0)
        rl.setSpacing(t.SP_SM)
        rl.addWidget(self._field_label("Threshold (slots filled)"))
        spin = QSpinBox()
        spin.setRange(1, 28)
        spin.setValue(int(self.step.inventory_threshold))
        spin.valueChanged.connect(self._on_inv_threshold_changed)
        rl.addWidget(spin)
        rl.addStretch(1)
        v.addWidget(row)

        v.addWidget(self._build_branch_target_combo())

        hint = QLabel(
            "Requires Inventory ROI calibration. "
            "world().inventory must be populated for this rule to fire."
        )
        hint.setWordWrap(True)
        hint.setStyleSheet(
            f"color: {t.TEXT_TERTIARY}; font-size: {t.SIZE_SM}px;"
        )
        v.addWidget(hint)
        return wrap

    def _build_if_hp_body(self) -> QWidget:
        wrap = QWidget()
        v = QVBoxLayout(wrap)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(t.SP_XS)

        row = QWidget()
        rl = QHBoxLayout(row)
        rl.setContentsMargins(0, 0, 0, 0)
        rl.setSpacing(t.SP_SM)
        rl.addWidget(self._field_label("HP below %"))
        spin = QSpinBox()
        spin.setRange(1, 100)
        spin.setSuffix(" %")
        spin.setValue(int(self.step.hp_threshold_pct))
        spin.valueChanged.connect(self._on_hp_threshold_changed)
        rl.addWidget(spin)
        rl.addStretch(1)
        v.addWidget(row)

        v.addWidget(self._build_branch_target_combo())

        hint = QLabel(
            "Requires Orbs ROI calibration at 100% HP."
        )
        hint.setWordWrap(True)
        hint.setStyleSheet(
            f"color: {t.TEXT_TERTIARY}; font-size: {t.SIZE_SM}px;"
        )
        v.addWidget(hint)
        return wrap

    def _build_branch_target_combo(self) -> QWidget:
        row = QWidget()
        rl = QHBoxLayout(row)
        rl.setContentsMargins(0, 0, 0, 0)
        rl.setSpacing(t.SP_SM)
        rl.addWidget(self._field_label("Then run step"))
        cb = QComboBox()
        cb.addItem("(predicate only — return True)", None)
        for s in self.app._ai_user_steps:
            if s.step_id == self.step.step_id:
                continue
            cb.addItem(f"  {rule_name_for(s)}", s.step_id)
        # Set current.
        target = self.step.branch_target_step_id
        idx = 0
        for i in range(cb.count()):
            if cb.itemData(i) == target:
                idx = i
                break
        cb.setCurrentIndex(idx)
        cb.currentIndexChanged.connect(
            lambda _idx, c=cb: self._on_branch_target_changed(c.currentData())
        )
        rl.addWidget(cb, 1)
        return row

    def _build_loop_body(self) -> QWidget:
        wrap = QWidget()
        h = QHBoxLayout(wrap)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(t.SP_SM)
        h.addWidget(self._field_label("Loop count"))
        spin = QSpinBox()
        spin.setRange(0, 1000)
        spin.setSpecialValueText("forever")
        spin.setValue(int(self.step.loop_count))
        spin.valueChanged.connect(self._on_loop_count_changed)
        h.addWidget(spin)
        hint = QLabel(
            "Tick-scoped: this rule wins the next N ticks (0 = forever). "
            "NOT a program-counter jump."
        )
        hint.setWordWrap(True)
        hint.setStyleSheet(
            f"color: {t.TEXT_TERTIARY}; font-size: {t.SIZE_SM}px;"
        )
        h.addWidget(hint, 1)
        return wrap

    def _build_uptext_body(self) -> QWidget:
        wrap = QWidget()
        v = QVBoxLayout(wrap)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(t.SP_XS)
        v.addWidget(self._make_label_row(
            "Pattern", self.step.uptext_pattern,
            on_change=self._on_uptext_pattern_changed,
            placeholder="e.g. Chop down",
        ))
        row = QWidget()
        h = QHBoxLayout(row)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(t.SP_SM)
        h.addWidget(self._field_label("Regex mode"))
        sw = IOSSwitch()
        sw.setChecked(bool(self.step.uptext_is_regex))
        sw.toggled.connect(self._on_uptext_regex_toggled)
        h.addWidget(sw)
        h.addStretch(1)
        v.addWidget(row)
        return wrap

    def _build_test_row(self) -> QWidget:
        """A '▶ Test' button that fires this step ONCE in dry-run with
        a freshly captured frame, then toasts the result. Tight feedback
        loop for tuning detection thresholds without starting the bot."""
        wrap = QWidget()
        h = QHBoxLayout(wrap)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(t.SP_SM)
        h.addStretch(1)
        btn = QPushButton("▶  Test step")
        btn.setMinimumHeight(t.BUTTON_H)
        btn.setCursor(Qt.PointingHandCursor)
        btn.setProperty("variant", "accent")
        btn.clicked.connect(self._on_test_step)
        h.addWidget(btn)
        return wrap

    def _on_test_step(self) -> None:
        """Compile this step in dry-run, capture a frame, fire it
        once, toast the outcome."""
        # Delegate to the parent section so the work happens in one
        # place and can also be invoked from elsewhere later.
        self.parent_section.test_step(self.step)

    def _build_after_wait_row(self) -> QWidget:
        wrap = QWidget()
        h = QHBoxLayout(wrap)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(t.SP_SM)
        h.addWidget(self._field_label("After-action wait (ms)"))
        self._after_min = QSpinBox()
        self._after_min.setRange(0, 60000)
        self._after_min.setValue(int(self.step.after_min_ms))
        self._after_min.valueChanged.connect(self._on_after_min_changed)
        h.addWidget(self._after_min)
        h.addWidget(QLabel("–"))
        self._after_max = QSpinBox()
        self._after_max.setRange(0, 60000)
        self._after_max.setValue(int(self.step.after_max_ms))
        self._after_max.valueChanged.connect(self._on_after_max_changed)
        h.addWidget(self._after_max)
        h.addStretch(1)
        return wrap

    # ── Field helpers ────────────────────────────────────────
    def _field_label(self, text: str) -> QLabel:
        lbl = QLabel(text)
        lbl.setStyleSheet(
            f"color: {t.TEXT_SECONDARY}; "
            f"font-size: {t.SIZE_SM}px; "
            f"font-weight: 500; "
            f"min-width: 100px;"
        )
        return lbl

    def _make_label_row(
        self, label: str, value: str, *, on_change, placeholder: str = "",
        mono: bool = False,
    ) -> QWidget:
        row = QWidget()
        h = QHBoxLayout(row)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(t.SP_SM)
        h.addWidget(self._field_label(label))
        edit = QLineEdit(value)
        edit.setPlaceholderText(placeholder)
        if mono:
            font = QFont(t.FONT_MONO.split(",")[0].strip())
            font.setPixelSize(t.SIZE_BODY)
            font.setStyleHint(QFont.TypeWriter)
            edit.setFont(font)
        edit.editingFinished.connect(lambda e=edit: on_change(e.text()))
        h.addWidget(edit, 1)
        return row

    def _color_text_str(self) -> str:
        rgb = self.step.color_target_rgb
        if not rgb:
            return "(no colour picked)"
        return f"#{rgb[0]:02X}{rgb[1]:02X}{rgb[2]:02X}  rgb({rgb[0]}, {rgb[1]}, {rgb[2]})"

    def _refresh_swatch(self) -> None:
        rgb = self.step.color_target_rgb
        css = (f"background: rgb({rgb[0]}, {rgb[1]}, {rgb[2]}); "
               if rgb else f"background: {t.SURFACE_PANEL}; ")
        self._color_swatch.setStyleSheet(
            css + f"border: 1px solid {t.BORDER}; border-radius: 4px;"
        )

    def _roi_text_str(self) -> str:
        r = self.step.roi
        if not r:
            return "whole screen"
        return f"x={r[0]}  y={r[1]}  w={r[2]}  h={r[3]}"

    def _refresh_roi_caption(self) -> None:
        if hasattr(self, "_roi_caption"):
            self._roi_caption.setText(self._roi_text_str())

    # ── Event handlers ────────────────────────────────────────
    def _on_label_changed(self, value: str) -> None:
        self.step.label = (value or "")[:80]
        self.parent_section.step_changed()
        self._refresh_summary()

    def _on_phase_changed(self, value: str) -> None:
        self.step.phase = (value or "")[:32]
        self.parent_section.step_changed()

    def _on_enabled_toggled(self, checked: bool) -> None:
        self.step.enabled = bool(checked)
        self.parent_section.step_changed()

    def _on_pick_color(self) -> None:
        def _done(result):
            if result is None:
                return
            (rgb, _x, _y) = result
            self.step.color_target_rgb = tuple(rgb)
            self.parent_section.step_changed()
            self._refresh_swatch()
            self._color_text.setText(self._color_text_str())
            self._refresh_summary()
        self.app.open_color_picker(_done)

    def _on_tol_changed(self, value: int) -> None:
        self.step.color_tolerance = int(value)
        self.parent_section.step_changed()
        self._refresh_summary()

    def _on_min_pix_changed(self, value: int) -> None:
        self.step.color_min_pixels = int(value)
        self.parent_section.step_changed()
        self._refresh_summary()

    def _on_set_roi(self) -> None:
        def _done(zone):
            if zone is None or zone.shape != "rect" or not zone.rect:
                return
            x1, y1, x2, y2 = zone.rect
            x, y = int(min(x1, x2)), int(min(y1, y2))
            w, h = int(abs(x2 - x1)), int(abs(y2 - y1))
            if w < 4 or h < 4:
                return
            self.step.roi = (x, y, w, h)
            self.parent_section.step_changed()
            self._refresh_roi_caption()
            self.parent_section.render_all()  # re-render to add Clear button
        self.app.open_zone_drawer("rect", _done)

    def _on_clear_roi(self) -> None:
        self.step.roi = None
        self.parent_section.step_changed()
        self.parent_section.render_all()

    def _on_dtm_path_changed(self, value: str) -> None:
        self.step.dtm_template_path = (value or "").strip() or None
        self.parent_section.step_changed()
        self._refresh_summary()

    def _on_wait_min_changed(self, value: int) -> None:
        self.step.wait_min_ms = int(value)
        self.parent_section.step_changed()
        self._refresh_summary()

    def _on_wait_max_changed(self, value: int) -> None:
        self.step.wait_max_ms = int(value)
        self.parent_section.step_changed()
        self._refresh_summary()

    def _on_key_combo_changed(self, value: str) -> None:
        self.step.key_combo = (value or "").strip()
        self.parent_section.step_changed()
        self._refresh_summary()

    def _on_key_repeat_changed(self, value: int) -> None:
        self.step.key_repeat = max(1, int(value))
        self.parent_section.step_changed()
        self._refresh_summary()

    def _on_inv_threshold_changed(self, value: int) -> None:
        self.step.inventory_threshold = int(value)
        self.parent_section.step_changed()
        self._refresh_summary()

    def _on_hp_threshold_changed(self, value: int) -> None:
        self.step.hp_threshold_pct = int(value)
        self.parent_section.step_changed()
        self._refresh_summary()

    def _on_branch_target_changed(self, target_id) -> None:
        self.step.branch_target_step_id = target_id
        self.parent_section.step_changed()
        self._refresh_summary()

    def _on_loop_count_changed(self, value: int) -> None:
        self.step.loop_count = int(value)
        self.parent_section.step_changed()
        self._refresh_summary()

    def _on_uptext_pattern_changed(self, value: str) -> None:
        self.step.uptext_pattern = value or ""
        self.parent_section.step_changed()
        self._refresh_summary()

    def _on_uptext_regex_toggled(self, checked: bool) -> None:
        self.step.uptext_is_regex = bool(checked)
        self.parent_section.step_changed()
        self._refresh_summary()

    def _on_after_min_changed(self, value: int) -> None:
        self.step.after_min_ms = int(value)
        self.parent_section.step_changed()

    def _on_after_max_changed(self, value: int) -> None:
        self.step.after_max_ms = int(value)
        self.parent_section.step_changed()

    def _on_anim_window_changed(self, value: int) -> None:
        self.step.anim_window_frames = max(2, int(value))
        self.parent_section.step_changed()

    def _on_anim_flickers_changed(self, value: int) -> None:
        self.step.anim_min_flickers = max(1, int(value))
        self.parent_section.step_changed()

    # ── find_capture_click handlers ─────────────────────────────
    def _on_capture_name_changed(self, value: str) -> None:
        self.step.capture_name = value or ""
        self.parent_section.step_changed()
        self._refresh_summary()

    def _on_capture_threshold_changed(self, value: int) -> None:
        # Spinner is integer percent; store as 0..1 float.
        self.step.capture_match_threshold = max(0.1, min(1.0, value / 100.0))
        self.parent_section.step_changed()
        self._refresh_summary()

    # ── zone_click handlers ─────────────────────────────────────
    def _on_zone_shape_changed(self, value: str) -> None:
        # Changing the shape clears the existing zone — geometries
        # don't translate (a rect's coords don't make sense as a
        # circle's centre+radius).
        if value not in ("rect", "circle", "polygon"):
            return
        existing = self.step.zone_json or {}
        if existing.get("shape") == value:
            return
        self.step.zone_json = None
        self.parent_section.step_changed()
        self.parent_section.render_all()  # re-render to reflect cleared zone

    def _on_set_zone(self) -> None:
        shape = (self.step.zone_json or {}).get("shape") or "rect"

        def _done(zone):
            if zone is None:
                return
            try:
                self.step.zone_json = zone.to_json()
            except Exception:
                self.step.zone_json = None
            self.parent_section.step_changed()
            self.parent_section.render_all()
        self.app.open_zone_drawer(shape, _done)

    def _on_clear_zone(self) -> None:
        self.step.zone_json = None
        self.parent_section.step_changed()
        self.parent_section.render_all()

    def _on_item_name_changed(self, value: str) -> None:
        self.step.item_name = value or ""
        self.parent_section.step_changed()
        self._refresh_summary()

    def _on_item_op_changed(self, value: str) -> None:
        if value in (">=", "<=", "==", ">", "<"):
            self.step.item_count_op = value
            self.parent_section.step_changed()
            self._refresh_summary()

    def _on_item_threshold_changed(self, value: int) -> None:
        self.step.item_count_threshold = int(value)
        self.parent_section.step_changed()
        self._refresh_summary()


# ─────────────────────────────────────────────────────────────────
# Item library panel (collapsible, lives inside AIAuthoringSection)
# ─────────────────────────────────────────────────────────────────


class _ItemLibraryPanel(QFrame):
    """Per-bot list of known items, fetched from runescape.wiki.

    Each item the user adds gets its inventory icon downloaded once
    via :meth:`WikiClient.fetch_item_image` and cached on disk. The
    full library is rebuilt at Start time and attached to the
    compiled Bot, so ``world().count_item("Raw trout")`` works.
    """

    def __init__(self, app, parent_section: "AIAuthoringSection") -> None:
        super().__init__()
        self.app = app
        self.parent_section = parent_section
        self.setObjectName("aibot-items-panel")
        self.setStyleSheet(
            f"QFrame#aibot-items-panel {{"
            f"  background: {t.SURFACE_PANEL}; "
            f"  border: 1px solid {t.BORDER_SUBTLE}; "
            f"  border-radius: 8px; "
            f"}}"
        )
        outer = QVBoxLayout(self)
        outer.setContentsMargins(t.SP_SM, t.SP_SM, t.SP_SM, t.SP_SM)
        outer.setSpacing(t.SP_XS)

        # Header.
        header = QWidget()
        h = QHBoxLayout(header)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(t.SP_SM)
        title = QLabel("Items library")
        title.setStyleSheet(
            f"color: {t.ACCENT}; "
            f"font-size: 11px; "
            f"font-weight: 700; "
            f"letter-spacing: 0.5px;"
        )
        h.addWidget(title)
        self._status = QLabel("")
        self._status.setStyleSheet(
            f"color: {t.TEXT_TERTIARY}; font-size: {t.SIZE_SM}px;"
        )
        h.addWidget(self._status, 1)
        outer.addWidget(header)

        # Add row.
        add_row = QWidget()
        ar = QHBoxLayout(add_row)
        ar.setContentsMargins(0, 0, 0, 0)
        ar.setSpacing(t.SP_SM)
        self._name_edit = QLineEdit()
        self._name_edit.setPlaceholderText(
            "Item name (e.g. Raw trout, Yew logs, Coins) — uses the wiki"
        )
        self._name_edit.returnPressed.connect(self._on_add_clicked)
        ar.addWidget(self._name_edit, 1)
        add_btn = QPushButton("+ Add from wiki")
        add_btn.setMinimumHeight(t.BUTTON_H)
        add_btn.setCursor(Qt.PointingHandCursor)
        add_btn.clicked.connect(self._on_add_clicked)
        ar.addWidget(add_btn)
        outer.addWidget(add_row)

        # List.
        self._list_host = QWidget()
        self._list_layout = QVBoxLayout(self._list_host)
        self._list_layout.setContentsMargins(0, 0, 0, 0)
        self._list_layout.setSpacing(t.SP_XS)
        outer.addWidget(self._list_host)

        # Hint.
        hint = QLabel(
            "Each item's inventory icon is fetched from runescape.wiki "
            "once and cached locally. Use these names in “If item count …” "
            "rules or to filter “Find color → click” to specific items."
        )
        hint.setWordWrap(True)
        hint.setStyleSheet(
            f"color: {t.TEXT_TERTIARY}; font-size: {t.SIZE_SM}px; "
            f"padding-top: 4px;"
        )
        outer.addWidget(hint)

        self.refresh()

    def refresh(self) -> None:
        # Drop existing rows.
        while self._list_layout.count():
            it = self._list_layout.takeAt(0)
            w = it.widget()
            if w is not None:
                w.deleteLater()
        names: list[str] = list(getattr(self.app, "_ai_item_names", []))
        if not names:
            empty = QLabel("(no items yet)")
            empty.setStyleSheet(
                f"color: {t.TEXT_TERTIARY}; font-size: {t.SIZE_SM}px; "
                f"padding: 4px 0;"
            )
            self._list_layout.addWidget(empty)
        for nm in names:
            self._list_layout.addWidget(self._build_item_row(nm))
        self._status.setText(f"{len(names)} item{'s' if len(names) != 1 else ''}")

    def _build_item_row(self, name: str) -> QWidget:
        row = QWidget()
        h = QHBoxLayout(row)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(t.SP_SM)
        bullet = QLabel("•")
        bullet.setStyleSheet(f"color: {t.ACCENT}; font-size: {t.SIZE_SM}px;")
        h.addWidget(bullet)
        lbl = QLabel(name)
        lbl.setStyleSheet(
            f"color: {t.TEXT_PRIMARY}; font-size: {t.SIZE_BODY}px;"
        )
        h.addWidget(lbl, 1)
        # Link to view the cached icon path (informational).
        cached = self._cached_path_for(name)
        if cached and cached.exists():
            sz_lbl = QLabel(f"{cached.stat().st_size // 1024} KB")
        else:
            sz_lbl = QLabel("(not cached)")
        sz_lbl.setStyleSheet(
            f"color: {t.TEXT_TERTIARY}; font-size: {t.SIZE_SM}px;"
        )
        h.addWidget(sz_lbl)
        rm = QPushButton("Remove")
        rm.setMinimumHeight(t.BUTTON_H)
        rm.setCursor(Qt.PointingHandCursor)
        rm.clicked.connect(lambda _checked=False, n=name: self._on_remove(n))
        h.addWidget(rm)
        return row

    # ── Actions ──────────────────────────────────────────────────
    def _on_add_clicked(self) -> None:
        name = self._name_edit.text().strip()
        if not name:
            return
        self._name_edit.setEnabled(False)
        self._status.setText(f"Fetching {name}…")
        try:
            ok = self._fetch_and_register(name)
        finally:
            self._name_edit.setEnabled(True)
        if ok:
            self._name_edit.clear()

    def _fetch_and_register(self, name: str) -> bool:
        """Fetch the item icon, add to the bot's library config."""
        try:
            from ai.wiki import default_client
            from pathlib import Path
            cache_root = Path("debug/wiki_cache")
            client = default_client(cache_root)
            path = client.fetch_item_image(name)
        except Exception as e:
            self.app.toasts.post(
                f"⚠ Wiki fetch error: {type(e).__name__}: {e}",
                kind="error",
            )
            return False
        if path is None:
            self.app.toasts.post(
                f"⚠ Couldn't find an inventory icon for {name!r} on the wiki.",
                kind="warn",
            )
            return False
        names = list(getattr(self.app, "_ai_item_names", []))
        if name not in names:
            names.append(name)
        self.app._ai_item_names = names
        self.app.cfg["ai_user_bot_items"] = names
        from ui.config_io import save_config
        save_config(self.app.cfg)
        self.app.toasts.post(
            f"✓ Added {name!r} → {path.name}", kind="success",
        )
        self.refresh()
        # The combobox in any open if_item_count step body needs re-render.
        self.parent_section.render_all()
        return True

    def _on_remove(self, name: str) -> None:
        names = [n for n in getattr(self.app, "_ai_item_names", []) if n != name]
        self.app._ai_item_names = names
        self.app.cfg["ai_user_bot_items"] = names
        from ui.config_io import save_config
        save_config(self.app.cfg)
        self.refresh()
        self.parent_section.render_all()

    def _cached_path_for(self, name: str):
        from pathlib import Path
        from ai.wiki.client import _slugify
        return Path("debug/wiki_cache/items") / f"{_slugify(name)}.png"
