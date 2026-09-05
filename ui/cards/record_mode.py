"""Record mode editor: header, step list, loop footer.

Step body rendering (per kind: click / track / color / pause / key / loop)
lives in :mod:`ui.cards.steps` because the kinds share too much scratch
state to fragment cleanly. This module is the shell + dispatcher.

Built for the deck's editor pane (480 to 700 px beside the live
viewport): a one-line header with the step count and the one primary
action (ADD STEP), sequence-wide actions (save / load / clear / clear log)
behind a single overflow menu, then the step cards. There is no kind
filter: the engine runs every step top to bottom and hiding some of them
from the list only ever confused what the sequence would do.
"""

from __future__ import annotations

from typing import Iterable, Optional

from PySide6.QtCore import QPoint, Qt, QTimer
from PySide6.QtGui import QAction, QCursor, QFont, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QFrame, QInputDialog, QLabel, QMenu, QMessageBox, QScrollArea,
    QToolButton, QVBoxLayout, QWidget,
)

from modules import sequence_library
from modules.recorder import (
    KIND_CLICK, KIND_COLOR, KIND_KEY, KIND_LOOP, KIND_PAUSE, KIND_TRACK,
    RecorderStep, orphaned_template_paths,
)
from ui.config_io import _config_dir
from utils.logger import clear_log, log_path

from .. import icons, theme as t
from ..widgets.empty_state import EmptyState
from ..widgets.page_header import EditorHeader
from ..widgets.state_pill import StatePill
from .steps import StepRowBuilder


class RecordModeTab(QWidget):
    def __init__(self, app):
        super().__init__()
        self.app = app
        self._row_builder = StepRowBuilder(app)
        # step_id -> card widget from the last render, so the deck's
        # SEQUENCE panel can scroll a chosen step into view.
        self._row_widgets: dict[str, QFrame] = {}
        self._selected_step_id: Optional[str] = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(t.SP_SM)

        # -- Header: title, count, add, overflow -----------------------------
        self.header = EditorHeader(
            "Sequence", "Build a macro from steps. Runs top to bottom and repeats; input is not recorded automatically.")
        self.count_pill = StatePill("0 steps", tone="neutral")
        self.header.add_trailing(self.count_pill)

        self.add_btn = app.locker.register(self._build_add_button())
        self.header.add_trailing(self.add_btn)

        self.more_btn = app.locker.register(self._build_more_button())
        self.header.add_trailing(self.more_btn)
        layout.addWidget(self.header)

        # -- Steps list (scrollable) ----------------------------------------
        self._steps_scroll = QScrollArea()
        self._steps_scroll.setWidgetResizable(True)
        self._steps_scroll.setMinimumHeight(240)
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

        # -- Loop footer: what happens after the last step -------------------
        self._footer = QLabel("")
        self._footer.setWordWrap(True)
        self._footer.setAlignment(Qt.AlignCenter)
        self._footer.setStyleSheet(
            f"QLabel {{"
            f"  background: {t.SURFACE_PANEL}; "
            f"  border: 1px solid {t.BORDER}; "
            f"  border-radius: {t.RADIUS_BUTTON}px; "
            f"  padding: 6px 10px; "
            f"  color: {t.TEXT_TERTIARY}; "
            f"  font-family: {t.FONT_MONO}; "
            f"  font-size: {t.SIZE_SM}px; "
            f"  font-weight: 600; "
            f"}}"
        )
        font = self._footer.font()
        font.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, t.LABEL_TRACKING)
        self._footer.setFont(font)
        layout.addWidget(self._footer)

        # -- Trash footer (only visible when the trash is non-empty) ---------
        self._trash_footer = QLabel("")
        self._trash_footer.setWordWrap(True)
        self._trash_footer.setProperty("role", "hint")
        self._trash_footer.setTextFormat(Qt.RichText)
        self._trash_footer.setOpenExternalLinks(False)
        self._trash_footer.linkActivated.connect(self._on_restore_clicked)
        self._trash_footer.setVisible(False)
        layout.addWidget(self._trash_footer)
        app._step_trash_listeners.append(self._refresh_trash_footer)

        # Ctrl+Z anywhere inside this tab restores the last deleted step.
        shortcut = QShortcut(QKeySequence.Undo, self)
        shortcut.setContext(Qt.WidgetWithChildrenShortcut)
        shortcut.activated.connect(self._on_restore_clicked)

        self.render_all()
        self._refresh_trash_footer()

    # -- Header buttons --------------------------------------------------------

    def _build_add_button(self) -> QToolButton:
        btn = QToolButton()
        btn.setText("ADD STEP")
        btn.setIcon(icons.icon("plus", 14, t.TEXT_ON_ACCENT))
        btn.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        btn.setObjectName("add-step-btn")
        btn.setFixedHeight(t.BUTTON_H)
        btn.setCursor(Qt.PointingHandCursor)
        btn.setToolTip("Append a step to the end of the sequence.")
        btn.setPopupMode(QToolButton.InstantPopup)
        font = btn.font()
        font.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 1.0)
        btn.setFont(font)
        # The one primary action on the page: lime fill, dark text.
        btn.setStyleSheet(
            f"QToolButton#add-step-btn {{ background: {t.ACCENT}; "
            f"color: {t.TEXT_ON_ACCENT}; border: 1px solid {t.ACCENT}; "
            f"border-radius: {t.RADIUS_BUTTON}px; padding: 0 10px 0 8px; "
            f"font-size: {t.SIZE_SM}px; font-weight: 700; }}"
            f"QToolButton#add-step-btn::menu-indicator {{ image: none; width: 0; }}"
            f"QToolButton#add-step-btn:hover {{ background: {t.ACCENT_HOVER}; "
            f"border-color: {t.ACCENT_HOVER}; }}"
            f"QToolButton#add-step-btn:pressed {{ background: {t.ACCENT_PRESSED}; }}"
            f"QToolButton#add-step-btn:disabled {{ background: {t.SURFACE_PANEL}; "
            f"color: {t.TEXT_DISABLED}; border-color: {t.BORDER_SUBTLE}; }}"
        )

        menu = QMenu(btn)
        vision_kinds: Iterable[tuple[str, str, str, callable]] = [
            ("click", "Click", "Click inside a fixed area", self.on_add_click),
            ("target", "Track", "Follow a moving target and click it", self.on_add_track),
            ("dot", "Color", "Click any pixel of a chosen colour", self.on_add_color),
        ]
        flow_kinds: Iterable[tuple[str, str, str, callable]] = [
            ("key", "Keyboard", "Press a key or combo", self.on_add_key),
            ("pause", "Pause", "Wait without clicking", self.on_add_pause),
            ("loop", "Loop", "Jump back to an earlier step", self.on_add_loop),
        ]
        for icon_name, label, desc, handler in vision_kinds:
            act = QAction(icons.icon(icon_name), f"{label}    {desc}", menu)
            act.triggered.connect(handler)
            menu.addAction(act)
        menu.addSeparator()
        for icon_name, label, desc, handler in flow_kinds:
            act = QAction(icons.icon(icon_name), f"{label}    {desc}", menu)
            act.triggered.connect(handler)
            menu.addAction(act)
        btn.setMenu(menu)
        return btn

    def _build_more_button(self) -> QToolButton:
        """Sequence-wide actions behind one button, so the header stays a
        single line at the pane's narrowest."""
        btn = QToolButton()
        btn.setText("···")
        btn.setObjectName("more-btn")
        btn.setFixedSize(t.BUTTON_H, t.BUTTON_H)
        btn.setCursor(Qt.PointingHandCursor)
        btn.setToolTip("Save, load or clear the whole sequence.")
        btn.setPopupMode(QToolButton.InstantPopup)
        btn.setStyleSheet(
            f"QToolButton#more-btn {{ background: {t.SURFACE_PANEL}; "
            f"color: {t.TEXT_SECONDARY}; border: 1px solid {t.BORDER}; "
            f"border-radius: {t.RADIUS_BUTTON}px; padding: 0; "
            f"font-size: {t.SIZE_LG}px; font-weight: 700; }}"
            f"QToolButton#more-btn::menu-indicator {{ image: none; width: 0; }}"
            f"QToolButton#more-btn:hover {{ background: {t.SURFACE_HIGH}; "
            f"color: {t.TEXT_PRIMARY}; border-color: {t.BORDER_STRONG}; }}"
        )
        menu = QMenu(btn)
        self.save_action = QAction(icons.icon("folder"), "Save sequence as preset", menu)
        self.save_action.setToolTip("Save the current steps under a name in sequences/.")
        self.save_action.triggered.connect(self._on_save_sequence)
        menu.addAction(self.save_action)
        self.load_action = QAction(icons.icon("folder"), "Load preset (replaces steps)", menu)
        self.load_action.triggered.connect(self._on_load_sequence)
        menu.addAction(self.load_action)
        menu.addSeparator()
        self.clear_all_action = QAction(icons.icon("trash"), "Clear all steps", menu)
        self.clear_all_action.triggered.connect(self._on_clear_all_steps)
        menu.addAction(self.clear_all_action)
        menu.addSeparator()
        self.clear_log_action = QAction(icons.icon("clear"), "Clear phantomclick.log", menu)
        self.clear_log_action.triggered.connect(self._on_clear_log)
        menu.addAction(self.clear_log_action)
        btn.setMenu(menu)
        return btn

    # -- Step rendering --------------------------------------------------------

    def render_all(self) -> None:
        # Clear the layout (keeping the trailing stretch).
        while self._steps_layout.count() > 1:
            item = self._steps_layout.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()
        steps = self.app._steps
        self._row_widgets = {}
        if not steps:
            self._steps_layout.insertWidget(0, self._empty_state())
        else:
            for idx in range(len(steps)):
                row = self._row_builder.build_row(idx, refresh_cb=self.render_all)
                self._steps_layout.insertWidget(idx, row)
                self._row_widgets[steps[idx].step_id] = row
        n = len(steps)
        self.count_pill.set_state(
            f"{n} step" if n == 1 else f"{n} steps",
            "accent" if n else "neutral",
        )
        self._refresh_footer()
        self.app.locker.apply(self.app._state_str)

    def _empty_state(self) -> QWidget:
        return EmptyState(
            "No steps yet",
            "Add a click, a key press, a pause or a loop. The engine runs "
            "them top to bottom and repeats.",
            cta_text="Add first step",
            on_cta=lambda: self.show_add_menu(),
        )

    # -- Hooks for the deck's SEQUENCE panel ------------------------------------

    def select_step(self, step_id: str) -> bool:
        """Expand one step's card and scroll it into view. Returns False
        when no step carries ``step_id``."""
        step = next((s for s in self.app._steps if s.step_id == step_id), None)
        if step is None:
            return False
        self._selected_step_id = step_id
        # One card open at a time when a step is picked from the deck.
        self._row_builder.expand_only(step_id)
        self.render_all()
        # The scroll range is only right after the layout pass has run.
        QTimer.singleShot(0, lambda sid=step_id: self._reveal_step(sid))
        return True

    def _reveal_step(self, step_id: str) -> None:
        row = self._row_widgets.get(step_id)
        if row is None:
            return
        try:
            self._steps_scroll.ensureWidgetVisible(row, 0, 24)
        except RuntimeError:
            pass

    def selected_step_id(self) -> Optional[str]:
        """Last step picked through :meth:`select_step`."""
        return self._selected_step_id

    def show_add_menu(self, global_pos: Optional[QPoint] = None) -> None:
        """Pop the same add-step menu the header button owns."""
        menu = self.add_btn.menu()
        if menu is None:
            return
        if global_pos is None:
            # Under the button when called from the page itself.
            global_pos = self.add_btn.mapToGlobal(
                QPoint(0, self.add_btn.height())) if self.add_btn.isVisible() else QCursor.pos()
        menu.popup(global_pos)

    def _refresh_footer(self) -> None:
        steps = self.app._steps
        if not steps:
            self._footer.setVisible(False)
            return
        self._footer.setVisible(True)
        if any(s.kind == KIND_LOOP for s in steps):
            self._footer.setText("LOOP STEP SETS THE JUMP-BACK POINT")
        else:
            self._footer.setText(f"AFTER STEP {len(steps)}: BACK TO STEP 1, FOREVER")

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
            f"text-decoration: none;'>Restore last deleted</a> (Ctrl+Z)"
        )
        self._trash_footer.setVisible(True)

    def _on_restore_clicked(self, *_args) -> None:
        """linkActivated handler, also reused by the Ctrl+Z shortcut.
        No-op when the trash is empty."""
        try:
            self.app._restore_last_deleted_step()
        except Exception:
            pass

    # -- Add handlers ----------------------------------------------------------

    def on_add_click(self) -> None:
        self.app._steps.append(RecorderStep(kind=KIND_CLICK))
        self.app._save_steps()
        self._after_add()

    def on_add_track(self) -> None:
        self.app._steps.append(RecorderStep(
            kind=KIND_TRACK, click_count=1, delay_min=1.0, delay_max=3.0,
        ))
        self.app._save_steps()
        self._after_add()

    def on_add_color(self) -> None:
        self.app._steps.append(RecorderStep(
            kind=KIND_COLOR, click_count=1, delay_min=1.0, delay_max=3.0,
        ))
        self.app._save_steps()
        self._after_add()

    def on_add_pause(self) -> None:
        self.app._steps.append(RecorderStep(
            kind=KIND_PAUSE, delay_min=5.0, delay_max=10.0,
        ))
        self.app._save_steps()
        self._after_add()

    def on_add_key(self) -> None:
        self.app._steps.append(RecorderStep(
            kind=KIND_KEY, key_combo="", key_repeat=1, key_hold_s=0.0,
            delay_min=0.5, delay_max=1.5,
        ))
        self.app._save_steps()
        self._after_add()

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
        self._after_add()

    def _after_add(self) -> None:
        # A new step opens expanded so its controls are right there;
        # every other step keeps whatever state it had.
        if self.app._steps:
            sid = self.app._steps[-1].step_id
            self._row_builder.expand_only(sid)
            self._selected_step_id = sid
        self.render_all()
        if self.app._steps:
            QTimer.singleShot(0, lambda sid=self.app._steps[-1].step_id: self._reveal_step(sid))

    # -- Log control ------------------------------------------------------------

    def _on_clear_log(self) -> None:
        """Truncate the log file and confirm in a dialog so the user sees
        it happened (a toast was easy to miss)."""
        ok = clear_log()
        if ok:
            QMessageBox.information(
                self,
                "Log cleared",
                f"Log history deleted.\n\n"
                f"Fresh entries land in {log_path().name} on the next event.",
            )
        else:
            QMessageBox.warning(
                self,
                "Couldn't clear log",
                f"Couldn't truncate {log_path().name}, another process "
                f"may be holding it.\n\nClose any tail viewers and retry.",
            )

    # -- Clear all / save / load sequence ----------------------------------------

    def _trash_all_steps(self) -> None:
        """Move every step to the trash (newest index first) so Ctrl+Z can
        bring them back one at a time."""
        from pathlib import Path
        while self.app._steps:
            idx = len(self.app._steps) - 1
            step = self.app._steps[idx]
            # Only PNGs no surviving step still references travel to the
            # trash (legacy duplicates may share one file).
            template_paths: list[Path] = []
            for rel in orphaned_template_paths(step, self.app._steps):
                p = Path(rel)
                if not p.is_absolute():
                    p = _config_dir() / p
                template_paths.append(p)
            self.app._push_step_to_trash(step, idx, template_paths)
            del self.app._steps[idx]

    def _on_clear_all_steps(self) -> None:
        n = len(self.app._steps)
        if n == 0:
            self.app.toasts.post("Sequence is already empty.", kind="info")
            return
        plural = "step" if n == 1 else "steps"
        if QMessageBox.question(
            self,
            "Clear all steps",
            f"Remove all {n} {plural}? Ctrl+Z restores them one at a time "
            f"until the app closes.",
        ) != QMessageBox.Yes:
            return
        self._trash_all_steps()
        self.app._save_steps()
        self.app.overlay_manager.refresh_step_overlays()
        self.render_all()
        self.app.toasts.post(
            f"Cleared {n} {plural}. Ctrl+Z restores one at a time.",
            kind="info",
        )

    def _on_save_sequence(self) -> None:
        if not self.app._steps:
            self.app.toasts.post("Nothing to save, sequence is empty.",
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
            sequence_library.save_sequence(clean, self.app._steps)
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
                "There are no saved sequences yet. Use 'Save sequence as preset' first.",
            )
            return
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
        # mistaken Load.
        self._trash_all_steps()
        self.app._steps.extend(new_steps)
        self.app._save_steps()
        self.app.overlay_manager.refresh_step_overlays()
        self.render_all()
        self.app.toasts.post(
            f"Loaded '{name}' ({len(new_steps)} steps).", kind="info"
        )
