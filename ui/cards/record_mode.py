"""Record Mode tab — sub-tab filter, scrollable step list, loop footer.

Step body rendering (per-kind: click / track / color / pause / key / loop)
lives in :mod:`ui.cards.steps` because the kinds share too much scratch
state to fragment cleanly. This module is the shell + dispatcher.

The sub-tabs filter the visible step list by kind ("All / Clicks / Keys /
Pauses / Loops"). Filtering doesn't reorder — steps keep their canonical
indices because the engine still runs the full sequence top to bottom.
"""

from __future__ import annotations

from typing import Iterable

from PySide6.QtCore import Qt
from PySide6.QtGui import QAction, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QFrame, QHBoxLayout, QInputDialog, QLabel, QMenu, QMessageBox, QPushButton,
    QScrollArea, QToolButton, QVBoxLayout, QWidget,
)

from modules import sequence_library
from modules.recorder import (
    KIND_CLICK, KIND_COLOR, KIND_KEY, KIND_LOOP, KIND_PAUSE, KIND_TRACK,
    RecorderStep,
)
from ui.config_io import _config_dir, save_config
from utils.logger import clear_log, log_path

from .. import theme as t
from ..widgets.segmented import SegmentedControl
from .steps import StepRowBuilder


# Filter id → set of step kinds to show. "All" passes everything.
_FILTER_KINDS: dict[str, frozenset[str]] = {
    "all": frozenset({KIND_CLICK, KIND_TRACK, KIND_COLOR,
                      KIND_KEY, KIND_PAUSE, KIND_LOOP}),
    "clicks": frozenset({KIND_CLICK, KIND_TRACK, KIND_COLOR}),
    "keys": frozenset({KIND_KEY}),
    "pauses": frozenset({KIND_PAUSE}),
    "loops": frozenset({KIND_LOOP}),
}


class RecordModeTab(QWidget):
    def __init__(self, app):
        super().__init__()
        self.app = app
        self._row_builder = StepRowBuilder(app)
        self._filter: str = str(app.cfg.get("record_filter", "all")).lower()
        if self._filter not in _FILTER_KINDS:
            self._filter = "all"

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(t.SP_MD)

        # -- Realism stub (hosted inside a proper Card so it matches the
        # step cards below — was double-wrapped frame-in-frame before). ---
        from ..widgets.card import Card
        from .behavior import RealismStub
        realism_card = Card("Realism")
        realism_card.add(RealismStub(app, compact=True))
        layout.addWidget(realism_card)

        # -- Header + add-step menu --------------------------------------
        header_row = QHBoxLayout()
        header_row.setSpacing(t.SP_SM)

        title = QLabel("Sequence")
        title.setProperty("role", "section")
        header_row.addWidget(title)

        sub = QLabel("runs top → bottom, then loops")
        sub.setProperty("role", "hint")
        header_row.addWidget(sub)

        header_row.addStretch(1)

        # Sequence preset operations (save/load/clear). These mutate the
        # full step list, so they're locker-registered like add-step —
        # disabled while the engine is running.
        self.save_btn = app.locker.register(QPushButton("Save"))
        self.save_btn.setProperty("variant", "ghost")
        self.save_btn.setCursor(Qt.PointingHandCursor)
        self.save_btn.setToolTip(
            "Save the current step list as a named preset under sequences/."
        )
        self.save_btn.clicked.connect(self._on_save_sequence)
        header_row.addWidget(self.save_btn)

        self.load_btn = app.locker.register(QPushButton("Load"))
        self.load_btn.setProperty("variant", "ghost")
        self.load_btn.setCursor(Qt.PointingHandCursor)
        self.load_btn.setToolTip(
            "Load a saved sequence — REPLACES the current step list."
        )
        self.load_btn.clicked.connect(self._on_load_sequence)
        header_row.addWidget(self.load_btn)

        self.clear_all_btn = app.locker.register(QPushButton("Clear all"))
        self.clear_all_btn.setProperty("variant", "ghost")
        self.clear_all_btn.setCursor(Qt.PointingHandCursor)
        self.clear_all_btn.setToolTip(
            "Remove every step from the sequence. Sent to the deleted-step "
            "trash so you can Ctrl+Z them back until the app closes."
        )
        self.clear_all_btn.clicked.connect(self._on_clear_all_steps)
        header_row.addWidget(self.clear_all_btn)

        # Debug-aid button: wipes phantomclick.log so the next Start
        # writes into a clean file. Lets the user tail-debug a single
        # session (e.g. troubleshooting a key step) without scrolling
        # past prior runs. The logger re-opens the file on the next
        # emit so no app restart is needed.
        self.clear_log_btn = app.locker.register(QPushButton("Clear log"))
        self.clear_log_btn.setProperty("variant", "ghost")
        self.clear_log_btn.setCursor(Qt.PointingHandCursor)
        self.clear_log_btn.setToolTip(
            f"Truncate {log_path().name} so a fresh debugging session "
            f"starts empty. The next engine event repopulates it."
        )
        self.clear_log_btn.clicked.connect(self._on_clear_log)
        header_row.addWidget(self.clear_log_btn)

        self.add_btn = app.locker.register(self._build_add_button())
        header_row.addWidget(self.add_btn)
        layout.addLayout(header_row)

        # -- Sub-tab filter ----------------------------------------------
        self._filter_seg = SegmentedControl(
            options=[
                ("all", "All"),
                ("clicks", "Clicks"),
                ("keys", "Keys"),
                ("pauses", "Pauses"),
                ("loops", "Loops"),
            ],
            value=self._filter,
        )
        self._filter_seg.valueChanged.connect(self._on_filter_change)
        filter_row = QHBoxLayout()
        filter_row.setSpacing(t.SP_SM)
        filter_lbl = QLabel("Show:")
        filter_lbl.setProperty("role", "hint")
        filter_row.addWidget(filter_lbl)
        filter_row.addWidget(self._filter_seg, 1)
        layout.addLayout(filter_row)

        # -- Steps list (scrollable) -------------------------------------
        self._steps_scroll = QScrollArea()
        self._steps_scroll.setWidgetResizable(True)
        self._steps_scroll.setMinimumHeight(360)
        self._steps_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._steps_scroll.setFrameShape(QScrollArea.NoFrame)
        self._steps_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self._steps_inner = QWidget()
        self._steps_layout = QVBoxLayout(self._steps_inner)
        self._steps_layout.setContentsMargins(0, 0, 0, 0)
        self._steps_layout.setSpacing(t.SP_SM)
        self._steps_layout.addStretch(1)
        self._steps_scroll.setWidget(self._steps_inner)
        layout.addWidget(self._steps_scroll, 1)

        # -- Loop footer -------------------------------------------------
        # Loop footer — a chip-styled badge so the "this sequence loops"
        # behavior is visible at a glance, not buried in tiny grey hint
        # text. Centered, accent-tinted, with the ↻ glyph oversized.
        self._footer = QLabel("")
        self._footer.setWordWrap(True)
        self._footer.setAlignment(Qt.AlignCenter)
        self._footer.setStyleSheet(
            f"QLabel {{"
            f"  background: {t.ACCENT_DIM_FALLBACK}; "
            f"  border: 1px solid {t.ACCENT}40; "
            f"  border-radius: 10px; "
            f"  padding: 10px 14px; "
            f"  color: {t.ACCENT_TEXT}; "
            f"  font-family: {t.FONT_DISPLAY}; "
            f"  font-size: 13px; "
            f"  font-weight: 600; "
            f"  letter-spacing: 0.3px;"
            f"}}"
        )
        layout.addWidget(self._footer)

        # -- Trash footer (only visible when the trash is non-empty) ----
        # A small clickable affordance to restore the most recently deleted
        # step. We use a QLabel with link markup so it renders in-line with
        # the loop hint above, and connect linkActivated to the App's
        # _restore_last_deleted_step.
        self._trash_footer = QLabel("")
        self._trash_footer.setWordWrap(True)
        self._trash_footer.setProperty("role", "hint")
        self._trash_footer.setTextFormat(Qt.RichText)
        self._trash_footer.setOpenExternalLinks(False)
        self._trash_footer.linkActivated.connect(self._on_restore_clicked)
        self._trash_footer.setVisible(False)
        layout.addWidget(self._trash_footer)
        # Subscribe to trash changes so the footer re-renders when the
        # user deletes / restores a step from anywhere.
        app._step_trash_listeners.append(self._refresh_trash_footer)

        # Ctrl+Z anywhere inside this tab restores the last deleted step.
        # Scoped to the widget (not application-wide) so it doesn't fight
        # other tabs that may want their own undo behavior later.
        shortcut = QShortcut(QKeySequence.Undo, self)
        shortcut.setContext(Qt.WidgetWithChildrenShortcut)
        shortcut.activated.connect(self._on_restore_clicked)

        self.render_all()
        self._refresh_trash_footer()

    # -- Add-step menu (replaces the 6-button grid) ---------------------

    def _build_add_button(self) -> QToolButton:
        btn = QToolButton()
        btn.setText("+ Add step")
        # Ghost variant — matches Save / Load / Clear siblings: invisible
        # at rest, gains border + background on hover. Was solid coral
        # ``primary`` which read as the only actionable button on the row.
        btn.setProperty("variant", "ghost")
        btn.setMinimumHeight(t.BUTTON_H)
        btn.setCursor(Qt.PointingHandCursor)
        btn.setToolTip("Append a new step to the sequence.")
        btn.setPopupMode(QToolButton.InstantPopup)

        menu = QMenu(btn)
        # Each item carries a one-liner so the kinds are self-explanatory.
        # A divider separates the vision-matchers (Click/Track/Color) from
        # the control-flow kinds (Keyboard/Pause/Loop).
        vision_kinds: Iterable[tuple[str, str, callable]] = [
            ("Click", "Fire in a fixed area", self.on_add_click),
            ("Track", "Click follows a moving target", self.on_add_track),
            ("Color", "Click any pixel of a chosen color", self.on_add_color),
        ]
        flow_kinds: Iterable[tuple[str, str, callable]] = [
            ("Keyboard", "Press a key or combo", self.on_add_key),
            ("Pause", "Wait without clicking", self.on_add_pause),
            ("Loop", "Jump back to an earlier step", self.on_add_loop),
        ]
        for label, desc, handler in vision_kinds:
            act = QAction(f"{label}    —    {desc}", menu)
            act.triggered.connect(handler)
            menu.addAction(act)
        menu.addSeparator()
        for label, desc, handler in flow_kinds:
            act = QAction(f"{label}    —    {desc}", menu)
            act.triggered.connect(handler)
            menu.addAction(act)
        btn.setMenu(menu)
        # Remove inline styleSheet — let the global ghost-variant QSS drive
        # the resting + hover look so the button matches Save / Load / Clear.
        # The menu chevron is QToolButton's default position, which is fine.
        return btn

    # -- Step rendering --------------------------------------------------

    def render_all(self) -> None:
        # Clear the layout (keeping the trailing stretch).
        while self._steps_layout.count() > 1:
            item = self._steps_layout.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()
        steps = self.app._steps
        kinds = _FILTER_KINDS.get(self._filter, _FILTER_KINDS["all"])
        visible_indices = [
            i for i, s in enumerate(steps) if s.kind in kinds
        ]
        if not steps:
            self._steps_layout.insertWidget(0, self._empty_state(
                "No steps yet — use “+ Add step” to start your sequence."
            ))
        elif not visible_indices:
            self._steps_layout.insertWidget(0, self._empty_state(
                f"No {self._filter_label()} in this sequence yet."
            ))
        else:
            insert_at = 0
            for idx in visible_indices:
                row = self._row_builder.build_row(idx, refresh_cb=self.render_all)
                self._steps_layout.insertWidget(insert_at, row)
                insert_at += 1
        self._refresh_footer()
        self.app.locker.apply(self.app._state_str)

    def _empty_state(self, msg: str) -> QLabel:
        lbl = QLabel(msg)
        lbl.setWordWrap(True)
        lbl.setProperty("role", "hint")
        lbl.setAlignment(Qt.AlignCenter)
        lbl.setContentsMargins(0, t.SP_LG, 0, t.SP_LG)
        return lbl

    def _filter_label(self) -> str:
        return {
            "clicks": "click steps",
            "keys": "keyboard steps",
            "pauses": "pauses",
            "loops": "loops",
            "all": "steps",
        }.get(self._filter, "steps")

    def _refresh_footer(self) -> None:
        steps = self.app._steps
        if not steps:
            self._footer.setVisible(False)
            return
        self._footer.setVisible(True)
        if any(s.kind == KIND_LOOP for s in steps):
            self._footer.setText(
                "↻   CUSTOM LOOP   ·   see the Loop step for the jump-back point"
            )
        else:
            n = len(steps)
            self._footer.setText(
                f"↻   LOOPS FOREVER   ·   back to step 1 after step {n}"
            )

    def _refresh_trash_footer(self) -> None:
        """Show / hide the "Restore last deleted" affordance based on the
        current trash state. Called on init, after every delete (via the
        App-side listener registry), and after every restore."""
        trash = getattr(self.app, "_step_trash", []) or []
        n = len(trash)
        if n == 0:
            self._trash_footer.setVisible(False)
            self._trash_footer.setText("")
            return
        plural = "step" if n == 1 else "steps"
        self._trash_footer.setText(
            f"{n} deleted {plural} can still be restored · "
            f"<a href='restore' style='color: {t.ACCENT}; "
            f"text-decoration: none;'>Restore last deleted</a>"
        )
        self._trash_footer.setVisible(True)

    def _on_restore_clicked(self, *_args) -> None:
        """linkActivated handler — also reused by the Ctrl+Z shortcut.
        No-op when the trash is empty (so a stray Ctrl+Z press does
        nothing instead of erroring)."""
        try:
            self.app._restore_last_deleted_step()
        except Exception:
            pass

    def _on_filter_change(self, value: str) -> None:
        if value not in _FILTER_KINDS:
            return
        self._filter = value
        self.app.cfg["record_filter"] = value
        save_config(self.app.cfg)
        self.render_all()

    # -- Add handlers ----------------------------------------------------

    def on_add_click(self) -> None:
        self.app._steps.append(RecorderStep(kind=KIND_CLICK))
        self.app._save_steps()
        self._after_add(KIND_CLICK)

    def on_add_track(self) -> None:
        self.app._steps.append(RecorderStep(
            kind=KIND_TRACK, click_count=1, delay_min=1.0, delay_max=3.0,
        ))
        self.app._save_steps()
        self._after_add(KIND_TRACK)

    def on_add_color(self) -> None:
        self.app._steps.append(RecorderStep(
            kind=KIND_COLOR, click_count=1, delay_min=1.0, delay_max=3.0,
        ))
        self.app._save_steps()
        self._after_add(KIND_COLOR)

    def on_add_pause(self) -> None:
        self.app._steps.append(RecorderStep(
            kind=KIND_PAUSE, delay_min=5.0, delay_max=10.0,
        ))
        self.app._save_steps()
        self._after_add(KIND_PAUSE)

    def on_add_key(self) -> None:
        self.app._steps.append(RecorderStep(
            kind=KIND_KEY, key_combo="", key_repeat=1, key_hold_s=0.0,
            delay_min=0.5, delay_max=1.5,
        ))
        self.app._save_steps()
        self._after_add(KIND_KEY)

    def on_add_loop(self) -> None:
        if not self.app._steps:
            self.app.toasts.post(
                "Add at least one step before adding a Loop.", kind="warn",
            )
            return
        target_id = self.app._steps[0].step_id
        self.app._steps.append(RecorderStep(
            kind=KIND_LOOP, loop_target_step_id=target_id, loop_count=0,
        ))
        self.app._save_steps()
        self._after_add(KIND_LOOP)

    # -- Log control -----------------------------------------------------

    def _on_clear_log(self) -> None:
        """Truncate the log file and surface a modal confirmation so the
        user definitively sees it happened. Toast was easy to miss
        (auto-dismiss + bottom-right placement); a modal blocks until
        acknowledged, which is the right trade-off for an action the
        user explicitly initiated by clicking 'Clear log'."""
        ok = clear_log()
        if ok:
            QMessageBox.information(
                self,
                "Log cleared",
                f"✓ Log history successfully deleted.\n\n"
                f"Fresh entries land in {log_path().name} on the next event.",
            )
        else:
            QMessageBox.warning(
                self,
                "Couldn't clear log",
                f"Couldn't truncate {log_path().name} — another process "
                f"may be holding it.\n\nTry closing any tail viewers and "
                f"retry.",
            )

    # -- Clear all / save / load sequence ---------------------------------

    def _on_clear_all_steps(self) -> None:
        n = len(self.app._steps)
        if n == 0:
            self.app.toasts.post("Sequence is already empty.", kind="info")
            return
        plural = "step" if n == 1 else "steps"
        if QMessageBox.question(
            self,
            "Clear all steps",
            f"Remove all {n} {plural}? You can Ctrl+Z to restore them "
            f"individually until the app closes.",
        ) != QMessageBox.Yes:
            return
        # Push every step to the existing trash so Ctrl+Z still works one
        # at a time. Iterate from the end so original_index reflects the
        # step's position at the moment it was removed.
        from pathlib import Path
        while self.app._steps:
            idx = len(self.app._steps) - 1
            step = self.app._steps[idx]
            template_paths: list[Path] = []
            if step.kind == KIND_TRACK:
                for rel in [getattr(step, "template_path", ""),
                            *getattr(step, "extra_template_paths", [])]:
                    if not rel:
                        continue
                    p = Path(rel)
                    if not p.is_absolute():
                        p = _config_dir() / p
                    template_paths.append(p)
            self.app._push_step_to_trash(step, idx, template_paths)
            del self.app._steps[idx]
        self.app._save_steps()
        self.app.overlay_manager.refresh_step_overlays()
        self.render_all()
        self.app.toasts.post(
            f"Cleared {n} {plural}. Ctrl+Z restores one at a time.",
            kind="info",
        )

    def _on_save_sequence(self) -> None:
        if not self.app._steps:
            self.app.toasts.post("Nothing to save — sequence is empty.",
                                 kind="warn")
            return
        name, ok = QInputDialog.getText(
            self,
            "Save sequence",
            "Name this preset:",
            text="My sequence",
        )
        if not ok:
            return
        clean = sequence_library.sanitize_name(name)
        if not clean:
            self.app.toasts.post(
                "That name has no usable characters. Try letters / numbers.",
                kind="warn",
            )
            return
        if sequence_library.exists(clean):
            if QMessageBox.question(
                self,
                "Overwrite preset",
                f"A sequence named '{clean}' already exists. Overwrite?",
            ) != QMessageBox.Yes:
                return
        try:
            path = sequence_library.save_sequence(clean, self.app._steps)
        except Exception as e:
            QMessageBox.warning(
                self, "Save failed",
                f"Couldn't write the sequence file:\n\n{e}",
            )
            return
        self.app.toasts.post(
            f"Saved '{clean}' ({len(self.app._steps)} steps).", kind="info"
        )

    def _on_load_sequence(self) -> None:
        seqs = sequence_library.list_sequences()
        if not seqs:
            QMessageBox.information(
                self, "No sequences saved",
                "There are no saved sequences yet. Use 'Save' to create one first.",
            )
            return
        # Items shown in the picker get a step-count suffix so the user
        # can tell similar names apart at a glance.
        items = [
            f"{e['name']}   ·   {e['step_count']} steps" for e in seqs
        ]
        names = [e["name"] for e in seqs]
        choice, ok = QInputDialog.getItem(
            self,
            "Load sequence",
            "Pick a saved sequence to load (replaces your current steps):",
            items,
            current=0,
            editable=False,
        )
        if not ok or choice not in items:
            return
        name = names[items.index(choice)]
        if self.app._steps:
            if QMessageBox.question(
                self,
                "Replace current steps",
                f"Loading '{name}' will replace your current "
                f"{len(self.app._steps)}-step sequence. Continue?",
            ) != QMessageBox.Yes:
                return
        try:
            new_steps = sequence_library.load_sequence(name)
        except Exception as e:
            QMessageBox.warning(
                self, "Load failed",
                f"Couldn't read the sequence file:\n\n{e}",
            )
            return
        # Clear current steps via trash so Ctrl+Z can recover from a
        # mistaken Load if the user didn't mean to replace anything.
        from pathlib import Path
        while self.app._steps:
            idx = len(self.app._steps) - 1
            step = self.app._steps[idx]
            template_paths: list[Path] = []
            if step.kind == KIND_TRACK:
                for rel in [getattr(step, "template_path", ""),
                            *getattr(step, "extra_template_paths", [])]:
                    if not rel:
                        continue
                    p = Path(rel)
                    if not p.is_absolute():
                        p = _config_dir() / p
                    template_paths.append(p)
            self.app._push_step_to_trash(step, idx, template_paths)
            del self.app._steps[idx]
        self.app._steps.extend(new_steps)
        self.app._save_steps()
        self.app.overlay_manager.refresh_step_overlays()
        self.render_all()
        self.app.toasts.post(
            f"Loaded '{name}' ({len(new_steps)} steps).", kind="info"
        )

    def _after_add(self, kind: str) -> None:
        # Newly added step starts expanded so the user sees its controls
        # immediately — every other step is collapsed by default.
        if self.app._steps:
            self._row_builder.mark_expanded(self.app._steps[-1].step_id)
        # If the active filter would hide the step we just added, switch
        # the filter so the user actually sees the new row appear.
        kinds = _FILTER_KINDS.get(self._filter, _FILTER_KINDS["all"])
        if kind not in kinds:
            target = {
                KIND_CLICK: "clicks", KIND_TRACK: "clicks", KIND_COLOR: "clicks",
                KIND_KEY: "keys", KIND_PAUSE: "pauses", KIND_LOOP: "loops",
            }.get(kind, "all")
            self._filter_seg.setValue(target)
            return  # _on_filter_change re-renders
        self.render_all()
