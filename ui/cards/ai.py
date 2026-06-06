"""AI card — third top-level mode body, in the Click/Record card style.

Five stacked :class:`Card` sections, top to bottom:

1. **Hero** — current bot: picker, goal, phase chips, setup-notes link.
2. **Live** — animated :class:`StatusDot` + state word, last-fired rule,
   tick/clicks/CPM/watchdog stat chips, live screen-preview thumbnail
   driven by the BotRunner's ``frame_captured`` signal.
3. **Rules** — list of every ``@bot.rule`` with phase chip and active
   highlight (the rule that fired this tick lights up).
4. **Config** — :class:`LabeledSlider` tick rate, monitor picker,
   :class:`IOSSwitch` dry-run, :class:`Expander` for the watchdog knobs.
5. **Log** — segmented filter (All / Rules / Errors) + colored output.

The bot picker, dry-run, and tick-rate values still live in
``app.cfg["ai_*"]``; the redesign is purely UI — wiring is unchanged.
``AIPageBody.tick()`` runs each app frame and refreshes whichever bits
need polling (status dot, stat chips, watchdog progress).
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import yaml
from PySide6.QtCore import Qt, QSize, QTimer
from PySide6.QtGui import QColor, QFont, QImage, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (
    QComboBox, QFrame, QGridLayout, QHBoxLayout, QLabel, QPlainTextEdit,
    QPushButton, QSizePolicy, QVBoxLayout, QWidget,
)

from ui.config_io import save_config

from .. import theme as t
from ..widgets.card import Card
from ..widgets.expander import Expander
from ..widgets.ios_switch import IOSSwitch
from ..widgets.labeled_slider import LabeledSlider
from ..widgets.segmented import SegmentedControl
from ..widgets.status_dot import StatusDot


# ─────────────────────────────────────────────────────────────────────────
# Bot enumeration & import (unchanged surface — still called by app.py
# and ui/monitor_server.py via ``from ui.cards.ai import _enumerate_bots``)
# ─────────────────────────────────────────────────────────────────────────


def _enumerate_bots() -> list[dict]:
    """Read ``ai/tasks/library/*.task.yaml`` and return summaries."""
    here = Path(__file__).resolve().parents[2]  # AutoClicker/
    lib = here / "ai" / "tasks" / "library"
    out: list[dict] = []
    if not lib.exists():
        return out
    for path in sorted(lib.glob("*.task.yaml")):
        try:
            data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        except Exception:
            continue
        slug = str(data.get("slug") or path.stem)
        name = str(data.get("name") or slug.replace("_", " ").title())
        goal = str(data.get("goal") or "").strip()
        bot_ref = (data.get("bot") or {}).get("ref")
        if not bot_ref:
            continue
        loc = data.get("location") or {}
        out.append({
            "slug": slug,
            "name": name,
            "goal": goal,
            "bot_ref": str(bot_ref),
            "yaml_path": str(path),
            "phases": list(data.get("phases") or []),
            "tags": list(data.get("tags") or []),
            "region": str(loc.get("region", "")),
            "notes": str(loc.get("notes", "")),
        })
    return out


def _import_bot(bot_ref: str, yaml_path: str):
    """Import the ``bot`` object from a Python file referenced by
    a task.yaml's ``bot.ref`` field."""
    import importlib.util as _ilu

    py_path = (Path(yaml_path).parent / bot_ref).resolve()
    spec = _ilu.spec_from_file_location(f"_aibot_{py_path.stem}", py_path)
    if spec is None or spec.loader is None:
        raise ImportError(f"can't load module spec for {py_path}")
    module = _ilu.module_from_spec(spec)
    spec.loader.exec_module(module)
    bot = getattr(module, "bot", None)
    if bot is None:
        raise ImportError(f"{py_path} has no module-level `bot` symbol")
    return bot


# ─────────────────────────────────────────────────────────────────────────
# Phase color palette — distinct hues so the eye can scan the rules
# list and tell which phases a bot moves through.
# ─────────────────────────────────────────────────────────────────────────


_PHASE_COLORS: dict[str, str] = {
    "scanning":         "#5b8def",   # info blue
    "chopping":         "#34d399",   # green
    "collecting_boon":  "#fbbf24",   # amber
    "banking":          "#a78bfa",   # violet
    "fighting":         "#ef4444",   # danger
    "eating":           "#f97316",   # orange
    "skilling":         "#22d3ee",   # cyan
}


def _phase_color(phase: str) -> str:
    if not phase:
        return t.TEXT_TERTIARY
    return _PHASE_COLORS.get(phase, t.ACCENT_TEXT)


# ─────────────────────────────────────────────────────────────────────────
# Small helpers — phase chip, stat chip, rule pill, preview thumb
# ─────────────────────────────────────────────────────────────────────────


class _PhaseChip(QLabel):
    """Tiny rounded label that color-codes a phase name."""

    def __init__(self, phase: str, parent: Optional[QWidget] = None):
        super().__init__(phase, parent)
        color = _phase_color(phase)
        self.setStyleSheet(
            f"background: rgba(255,255,255,0.04); "
            f"color: {color}; "
            f"border: 1px solid {color}40; "
            f"border-radius: 8px; "
            f"padding: 2px 8px; "
            f"font-family: {t.FONT_FAMILY}; "
            f"font-size: {t.SIZE_XS}px; "
            f"font-weight: 600; "
            f"letter-spacing: 0.4px; "
            f"text-transform: uppercase;"
        )


class _StatChip(QFrame):
    """A label-over-value chip for a single stat. Used in the Live card.

    Layout::

        ┌────────────┐
        │   142      │  ← value (mono, large)
        │   TICK     │  ← label (tertiary, tiny, uppercase)
        └────────────┘
    """

    def __init__(self, label: str, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setProperty("role", "stat-chip")
        self.setStyleSheet(
            f"background: {t.SURFACE_PANEL}; "
            f"border: 1px solid {t.BORDER_SUBTLE}; "
            f"border-radius: 8px; "
            f"padding: 6px 10px;"
        )

        col = QVBoxLayout(self)
        col.setContentsMargins(2, 0, 2, 0)
        col.setSpacing(0)
        col.setAlignment(Qt.AlignCenter)

        self._value = QLabel("—")
        self._value.setStyleSheet(
            f"color: {t.TEXT_PRIMARY}; "
            f"font-family: {t.FONT_MONO}; "
            f"font-size: 18px; "
            f"font-weight: 600;"
        )
        self._value.setAlignment(Qt.AlignCenter)
        col.addWidget(self._value)

        self._label = QLabel(label.upper())
        self._label.setStyleSheet(
            f"color: {t.TEXT_TERTIARY}; "
            f"font-family: {t.FONT_FAMILY}; "
            f"font-size: 9px; "
            f"font-weight: 600; "
            f"letter-spacing: 0.8px;"
        )
        self._label.setAlignment(Qt.AlignCenter)
        col.addWidget(self._label)

    def set_value(self, text: str, color: Optional[str] = None) -> None:
        self._value.setText(text)
        c = color or t.TEXT_PRIMARY
        self._value.setStyleSheet(
            f"color: {c}; "
            f"font-family: {t.FONT_MONO}; "
            f"font-size: 18px; "
            f"font-weight: 600;"
        )


class _RuleRow(QFrame):
    """One row in the Rules card: indicator dot + name + phase chip.

    The row highlights when its rule fires this tick (set via
    :meth:`set_active`); the highlight fades after ~1 s.
    """

    def __init__(self, name: str, phase: str, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._name = name
        self._active_until: float = 0.0

        self.setProperty("role", "rule-row")
        self.setMinimumHeight(34)

        row = QHBoxLayout(self)
        row.setContentsMargins(10, 6, 10, 6)
        row.setSpacing(t.SP_SM)

        self._dot = QLabel("●")
        self._dot.setStyleSheet(f"color: {t.TEXT_DISABLED}; font-size: 10px;")
        row.addWidget(self._dot)

        self._name_label = QLabel(name)
        self._name_label.setStyleSheet(
            f"color: {t.TEXT_PRIMARY}; "
            f"font-family: {t.FONT_MONO}; "
            f"font-size: {t.SIZE_SM}px;"
        )
        row.addWidget(self._name_label)

        row.addStretch(1)

        if phase:
            row.addWidget(_PhaseChip(phase))

        self._refresh_style()

    def set_active(self, *, hold_s: float = 1.0) -> None:
        self._active_until = time.monotonic() + hold_s
        self._refresh_style()

    def tick(self) -> None:
        if self._active_until and time.monotonic() > self._active_until:
            self._active_until = 0.0
            self._refresh_style()

    def _refresh_style(self) -> None:
        active = self._active_until > 0.0
        if active:
            bg = "rgba(34, 211, 238, 0.08)"
            border = "rgba(34, 211, 238, 0.40)"
            self._dot.setStyleSheet(f"color: {t.ACCENT}; font-size: 10px;")
        else:
            bg = "transparent"
            border = "transparent"
            self._dot.setStyleSheet(
                f"color: {t.TEXT_DISABLED}; font-size: 10px;"
            )
        self.setStyleSheet(
            f"QFrame[role=\"rule-row\"] {{"
            f"  background: {bg}; "
            f"  border: 1px solid {border}; "
            f"  border-radius: 6px; "
            f"}}"
        )


class _PreviewThumb(QLabel):
    """Live screen-preview thumbnail. Subscribes to ``frame_captured``
    (a numpy BGR ndarray) and renders it as a downsampled QPixmap.

    Throttled to ~5 FPS regardless of bot tick rate so the GUI stays
    smooth even on a fast bot.
    """

    THUMB_W = 280
    THUMB_H = 158

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setFixedSize(self.THUMB_W, self.THUMB_H)
        self.setAlignment(Qt.AlignCenter)
        self.setStyleSheet(
            f"background: {t.SURFACE_PANEL}; "
            f"border: 1px solid {t.BORDER_SUBTLE}; "
            f"border-radius: 8px; "
            f"color: {t.TEXT_TERTIARY}; "
            f"font-size: {t.SIZE_SM}px;"
        )
        self.setText("waiting for first frame…")
        self._last_render: float = 0.0
        self._min_interval: float = 0.20  # ~5 fps cap

    def update_frame(self, frame) -> None:
        now = time.monotonic()
        if now - self._last_render < self._min_interval:
            return
        self._last_render = now
        try:
            import numpy as np
            arr = np.ascontiguousarray(frame)
            if arr.ndim != 3 or arr.shape[2] < 3:
                return
            h, w = arr.shape[:2]
            # mss gives BGR; QImage Format_BGR888 reads it correctly with
            # no per-pixel swap.
            qimg = QImage(arr.data, w, h, w * arr.shape[2], QImage.Format_BGR888)
            pix = QPixmap.fromImage(qimg).scaled(
                self.THUMB_W, self.THUMB_H,
                Qt.KeepAspectRatio, Qt.SmoothTransformation,
            )
            self.setPixmap(pix)
            self.setText("")
        except Exception:
            pass


# ─────────────────────────────────────────────────────────────────────────
# Sections
# ─────────────────────────────────────────────────────────────────────────


class _HeroSection(Card):
    """Top: bot picker + goal + phase chips."""

    def __init__(self, app, parent_body: "AIPageBody"):
        super().__init__("Bot")
        self.app = app
        self._parent_body = parent_body

        # Big bot dropdown — looks like a heading, not a form field.
        self.bot_combo = QComboBox()
        self.bot_combo.setStyleSheet(
            f"QComboBox {{"
            f"  background: {t.SURFACE_PANEL}; "
            f"  border: 1px solid {t.BORDER}; "
            f"  border-radius: 8px; "
            f"  padding: 8px 12px; "
            f"  color: {t.TEXT_PRIMARY}; "
            f"  font-family: {t.FONT_DISPLAY}; "
            f"  font-size: 18px; "
            f"  font-weight: 600;"
            f"}}"
            f"QComboBox:hover {{ border-color: {t.BORDER_STRONG}; }}"
            f"QComboBox::drop-down {{ width: 28px; border: 0; }}"
            f"QComboBox QAbstractItemView {{"
            f"  background: {t.SURFACE_HIGH}; "
            f"  border: 1px solid {t.BORDER}; "
            f"  selection-background-color: {t.ACCENT_DIM}; "
            f"  color: {t.TEXT_PRIMARY}; "
            f"  padding: 4px;"
            f"}}"
        )
        self.bot_combo.currentIndexChanged.connect(self._on_bot_changed)
        self.add(self.bot_combo)

        # Goal text — wraps, secondary tone.
        self.goal_label = QLabel("")
        self.goal_label.setWordWrap(True)
        self.goal_label.setStyleSheet(
            f"color: {t.TEXT_SECONDARY}; "
            f"font-family: {t.FONT_FAMILY}; "
            f"font-size: {t.SIZE_BODY}px; "
            f"line-height: 1.5;"
        )
        self.add(self.goal_label)

        # Phase chips row.
        self.chips_host = QWidget()
        self._chips_layout = QHBoxLayout(self.chips_host)
        self._chips_layout.setContentsMargins(0, t.SP_XS, 0, 0)
        self._chips_layout.setSpacing(6)
        self._chips_layout.setAlignment(Qt.AlignLeft)
        self.add(self.chips_host)

        # Replay button (D.1) — feeds saved frames into the runtime
        # instead of live mss capture. Useful for tuning detection
        # against a captured fishing-spot directory or replaying a
        # failure case from runs/<session>/failures/. Forced dry_run
        # so the actuator doesn't fire input on stale frames.
        replay_row = QWidget()
        rrow = QHBoxLayout(replay_row)
        rrow.setContentsMargins(0, t.SP_XS, 0, 0)
        rrow.setSpacing(t.SP_SM)
        self.btn_replay = QPushButton("▶ Replay frames…")
        self.btn_replay.setCursor(Qt.PointingHandCursor)
        self.btn_replay.setStyleSheet(
            f"QPushButton {{"
            f"  background: transparent; "
            f"  color: {t.TEXT_SECONDARY}; "
            f"  border: 1px solid {t.BORDER}; "
            f"  border-radius: 8px; "
            f"  padding: 6px 14px; "
            f"  font-family: {t.FONT_FAMILY}; "
            f"  font-size: {t.SIZE_SM}px;"
            f"}}"
            f"QPushButton:hover {{ "
            f"  border-color: {t.ACCENT}; color: {t.ACCENT}; "
            f"}}"
        )
        self.btn_replay.setToolTip(
            "Run the bot against saved PNG frames (a failure folder, a "
            "captured recording, …) instead of live capture. Dry-run is "
            "forced — the actuator won't fire input on stale frames."
        )
        self.btn_replay.clicked.connect(self._on_replay_clicked)
        rrow.addWidget(self.btn_replay)
        rrow.addStretch(1)
        self.add(replay_row)

        # Setup-notes disclosure — only visible if the YAML has notes.
        # Uses the canonical Expander widget (chevron + slide animation)
        # so disclosure looks the same as the Config-section "Advanced"
        # expander; matches the same pattern Record-tab step bodies use.
        self.notes_expander = Expander("Setup notes")
        self.notes_body = QLabel("")
        self.notes_body.setWordWrap(True)
        self.notes_body.setStyleSheet(
            f"background: {t.SURFACE_PANEL}; "
            f"border: 1px solid {t.BORDER_SUBTLE}; "
            f"border-radius: 6px; "
            f"padding: 10px 12px; "
            f"color: {t.TEXT_SECONDARY}; "
            f"font-family: {t.FONT_MONO}; "
            f"font-size: {t.SIZE_SM}px; "
            f"line-height: 1.5;"
        )
        self.notes_expander.set_content(self.notes_body)
        self.add(self.notes_expander)

        self._refresh()

    # Synthetic data value for the legacy in-cfg "Custom Bot (in-GUI)"
    # entry. Kept for transitional back-compat with whatever the user
    # already authored before per-bot bundles existed; new authoring
    # should happen in a Bundle.
    CUSTOM_BOT_DATA = "__custom__"
    NEW_BUNDLE_DATA = "__new_bundle__"
    BUNDLE_PREFIX = "bundle:"

    def _refresh(self) -> None:
        self.bot_combo.blockSignals(True)
        self.bot_combo.clear()
        # 1. Bundles — user-authored bots living in <root>/bots/<slug>/.
        bundles = self._parent_body._bundles or []
        if bundles:
            for b in bundles:
                tag = f"  ({b.target_skill})" if b.target_skill else ""
                self.bot_combo.addItem(
                    f"📁  {b.name}{tag}", f"{self.BUNDLE_PREFIX}{b.slug}",
                )
            self.bot_combo.insertSeparator(self.bot_combo.count())
        # 2. New-bundle action.
        self.bot_combo.addItem("✚  New custom bot…", self.NEW_BUNDLE_DATA)
        # 3. Legacy in-cfg custom entry — only show if there's existing
        # data, so new users don't see a confusing duplicate of the
        # bundle workflow.
        if self.app.cfg.get("ai_user_bot_steps"):
            self.bot_combo.addItem(
                "◇  Custom Bot (legacy / in-cfg)", self.CUSTOM_BOT_DATA,
            )
        # 4. Library bots — Python-authored bots from ai/tasks/library/.
        bots = self._parent_body._bots
        if bots:
            self.bot_combo.insertSeparator(self.bot_combo.count())
            for b in bots:
                self.bot_combo.addItem(b["name"], b["slug"])

        # Restore last selection. Order of preference:
        #   1. active bundle slug (cfg["ai_active_bundle"])
        #   2. legacy custom mode (cfg["ai_use_user_bot"])
        #   3. saved library slug (cfg["ai_bot_slug"])
        active_bundle = str(self.app.cfg.get("ai_active_bundle") or "")
        restored = False
        if active_bundle:
            wanted = f"{self.BUNDLE_PREFIX}{active_bundle}"
            for i in range(self.bot_combo.count()):
                if self.bot_combo.itemData(i) == wanted:
                    self.bot_combo.setCurrentIndex(i)
                    restored = True
                    break
        if not restored and bool(self.app.cfg.get("ai_use_user_bot", False)):
            for i in range(self.bot_combo.count()):
                if self.bot_combo.itemData(i) == self.CUSTOM_BOT_DATA:
                    self.bot_combo.setCurrentIndex(i)
                    restored = True
                    break
        if not restored:
            saved = str(self.app.cfg.get("ai_bot_slug") or "")
            if saved:
                for i in range(self.bot_combo.count()):
                    if self.bot_combo.itemData(i) == saved:
                        self.bot_combo.setCurrentIndex(i)
                        break
        self.bot_combo.blockSignals(False)
        self._sync_to_current()

    def _on_bot_changed(self, _idx: int) -> None:
        idx = self.bot_combo.currentIndex()
        data = self.bot_combo.itemData(idx)
        if data == self.NEW_BUNDLE_DATA:
            # User clicked the "+ New custom bot…" action — prompt for
            # a name, materialize a bundle, switch to it.
            self._prompt_create_bundle()
            return
        if data == self.CUSTOM_BOT_DATA:
            self.app.cfg["ai_use_user_bot"] = True
            self.app.cfg["ai_bot_slug"] = ""
            self.app.cfg["ai_active_bundle"] = ""
            save_config(self.app.cfg)
        elif isinstance(data, str) and data.startswith(self.BUNDLE_PREFIX):
            slug = data[len(self.BUNDLE_PREFIX):]
            self.app.cfg["ai_active_bundle"] = slug
            self.app.cfg["ai_use_user_bot"] = False
            self.app.cfg["ai_bot_slug"] = ""
            save_config(self.app.cfg)
            self._parent_body._activate_bundle(slug)
        else:
            self.app.cfg["ai_use_user_bot"] = False
            self.app.cfg["ai_active_bundle"] = ""
            bots = self._parent_body._bots
            meta = next((b for b in bots if b["slug"] == data), None)
            if meta is not None:
                self.app.cfg["ai_bot_slug"] = meta["slug"]
            save_config(self.app.cfg)
        self._sync_to_current()
        # Tell the page body to re-render rule list etc.
        self._parent_body._on_bot_selection_changed()

    def _on_replay_clicked(self) -> None:
        """Open a folder/file picker and start the bot in replay mode.

        Defaults to the active bundle's most recent failures dir if any,
        else the bundle root, else the user's home directory.
        """
        from PySide6.QtWidgets import QFileDialog
        runner = getattr(self.app, "bot_runner", None)
        if runner is None:
            self.app.toasts.post(
                "⚠ AI mode unavailable — ai/ subpackage didn't load.",
                kind="error",
            )
            return
        if runner.is_running():
            self.app.toasts.post(
                "⚠ Stop the bot first — replay can't share the runner.",
                kind="warn",
            )
            return
        # Pick a sensible starting directory.
        start_dir = ""
        bundle = self._parent_body._active_bundle
        if bundle is not None:
            try:
                runs_root = bundle.root / "runs"
                if runs_root.exists():
                    sessions = sorted(
                        [p for p in runs_root.iterdir() if p.is_dir()]
                    )
                    if sessions:
                        latest_failures = sessions[-1] / "failures"
                        if latest_failures.exists():
                            start_dir = str(latest_failures)
                        else:
                            start_dir = str(sessions[-1])
                if not start_dir:
                    start_dir = str(bundle.root)
            except Exception:
                start_dir = ""
        path = QFileDialog.getExistingDirectory(
            self, "Pick a folder of PNG frames to replay", start_dir,
        )
        if not path:
            return
        # Compile the bundle to a Bot the same way Start does.
        if bundle is None:
            self.app.toasts.post(
                "⚠ Replay needs an active bundle. Pick a bot first.",
                kind="warn",
            )
            return
        bot = self.app._compile_bundle_bot(bundle)
        if bot is None:
            return
        actuator = getattr(self.app, "ai_actuator", None)
        world_calibration = self.app._world_calibration_from_bundle(bundle)
        runner.play_replay(
            bot,
            path,
            tick_rate_hz=float(self.app.cfg.get("ai_tick_rate_hz", 5.0)),
            actuator=actuator,
            world_calibration=world_calibration,
            bundle=bundle,
        )
        self.app.toasts.post(
            "▶ Replay started — frames feed in dry-run.",
            kind="info",
        )

    def _prompt_create_bundle(self) -> None:
        """Show a tiny QInputDialog prompt for the new bundle's name,
        create it on disk, and re-select it in the dropdown."""
        from PySide6.QtWidgets import QInputDialog
        from pathlib import Path
        from ai.bot.bundle import BotBundle, slugify, bundles_root
        from ui.config_io import _config_dir

        name, ok = QInputDialog.getText(
            self, "New custom bot",
            "Bot name (e.g. Menaphos VIP Fishing):",
        )
        if not ok or not (name or "").strip():
            # Re-sync the combo back to whatever was active before.
            self._refresh()
            return
        slug = slugify(name)
        try:
            root = bundles_root(_config_dir())
            bundle = BotBundle.create(root, slug, name=name.strip())
        except FileExistsError:
            self.app.toasts.post(
                f"⚠ A bot named {name!r} already exists.", kind="warn",
            )
            self._refresh()
            return
        except Exception as e:
            self.app.toasts.post(
                f"⚠ Couldn't create bundle: {type(e).__name__}: {e}",
                kind="error",
            )
            self._refresh()
            return
        # Re-enumerate and select the new bundle.
        self._parent_body.refresh_bundles()
        self.app.cfg["ai_active_bundle"] = slug
        self.app.cfg["ai_use_user_bot"] = False
        self.app.cfg["ai_bot_slug"] = ""
        save_config(self.app.cfg)
        self._parent_body._activate_bundle(slug)
        self._refresh()
        self.app.toasts.post(
            f"✓ Created new bot: {bundle.name}", kind="success",
        )

    def _sync_to_current(self) -> None:
        idx = self.bot_combo.currentIndex()
        data = self.bot_combo.itemData(idx)
        if data == self.NEW_BUNDLE_DATA:
            # Transient state — _on_bot_changed re-routes immediately.
            return
        if isinstance(data, str) and data.startswith(self.BUNDLE_PREFIX):
            slug = data[len(self.BUNDLE_PREFIX):]
            bundle = next(
                (b for b in (self._parent_body._bundles or []) if b.slug == slug),
                None,
            )
            if bundle is None:
                self.goal_label.setText("(bundle not found on disk)")
                self._clear_chips()
                self.notes_expander.setVisible(False)
                return
            target = bundle.target_skill or "—"
            n_proc = len((bundle.procedures or {}).get("procedures") or {})
            n_int = len((bundle.procedures or {}).get("interrupts") or [])
            self.goal_label.setText(
                f"Bundle: {bundle.name}  ·  target: {target}  ·  "
                f"{n_proc} procedure{'s' if n_proc != 1 else ''}, "
                f"{n_int} interrupt{'s' if n_int != 1 else ''}."
            )
            self._clear_chips()
            self.notes_expander.setVisible(False)
            return
        if data == self.CUSTOM_BOT_DATA:
            self.goal_label.setText(
                "Build a bot in-GUI by adding steps below. Steps run "
                "top-to-bottom each tick — first match wins."
            )
            self._clear_chips()
            self.notes_expander.setVisible(False)
            return
        bots = self._parent_body._bots
        meta = next((b for b in bots if b["slug"] == data), None)
        if meta is None:
            self.goal_label.setText("Select a bot from the dropdown to begin.")
            self._clear_chips()
            self.notes_expander.setVisible(False)
            return
        self.goal_label.setText(meta.get("goal") or "")
        self._render_chips(meta.get("phases") or [])
        has_notes = bool((meta.get("notes") or "").strip())
        self.notes_expander.setVisible(has_notes)
        if has_notes:
            self.notes_body.setText(meta["notes"])

    def _render_chips(self, phases: list) -> None:
        self._clear_chips()
        for ph in phases:
            self._chips_layout.addWidget(_PhaseChip(str(ph)))
        self._chips_layout.addStretch(1)

    def _clear_chips(self) -> None:
        while self._chips_layout.count():
            it = self._chips_layout.takeAt(0)
            w = it.widget()
            if w is not None:
                w.setParent(None)


class _LiveSection(Card):
    """Middle: state dot + last-fired rule + stat chips + preview."""

    def __init__(self, app):
        super().__init__("Live")
        self.app = app

        # Top row: dot + state word + last-fired rule (right-aligned).
        head = QWidget()
        head_row = QHBoxLayout(head)
        head_row.setContentsMargins(0, 0, 0, 0)
        head_row.setSpacing(t.SP_SM)
        self.dot = StatusDot(self, size=14)
        head_row.addWidget(self.dot)
        self.state_label = QLabel("IDLE")
        self.state_label.setStyleSheet(
            f"color: {t.TEXT_PRIMARY}; "
            f"font-family: {t.FONT_DISPLAY}; "
            f"font-size: 16px; "
            f"font-weight: 700; "
            f"letter-spacing: 1.4px;"
        )
        head_row.addWidget(self.state_label)
        head_row.addStretch(1)
        self.rule_label = QLabel("")
        self.rule_label.setStyleSheet(
            f"color: {t.TEXT_SECONDARY}; "
            f"font-family: {t.FONT_MONO}; "
            f"font-size: {t.SIZE_SM}px;"
        )
        head_row.addWidget(self.rule_label)
        self.add(head)

        # Stat chip grid: 4 across.
        chips = QWidget()
        grid = QGridLayout(chips)
        grid.setContentsMargins(0, t.SP_XS, 0, t.SP_XS)
        grid.setHorizontalSpacing(8)
        grid.setVerticalSpacing(8)
        self.chip_tick = _StatChip("Tick")
        self.chip_clicks = _StatChip("Clicks")
        self.chip_cpm = _StatChip("CPM")
        self.chip_phase = _StatChip("Phase")
        grid.addWidget(self.chip_tick, 0, 0)
        grid.addWidget(self.chip_clicks, 0, 1)
        grid.addWidget(self.chip_cpm, 0, 2)
        grid.addWidget(self.chip_phase, 0, 3)
        # Watchdog row.
        self.chip_dry = _StatChip("Dry ticks")
        self.chip_idle = _StatChip("No-click s")
        grid.addWidget(self.chip_dry, 1, 0, 1, 2)
        grid.addWidget(self.chip_idle, 1, 2, 1, 2)
        self.add(chips)

        # Preview thumbnail.
        self.preview = _PreviewThumb()
        # Center it in the card.
        wrap = QWidget()
        wrow = QHBoxLayout(wrap)
        wrow.setContentsMargins(0, 4, 0, 0)
        wrow.addStretch(1)
        wrow.addWidget(self.preview)
        wrow.addStretch(1)
        self.add(wrap)

    def update_state(self, *, running: bool, last_fired: Optional[str],
                     phase: str, tick: int, clicks: int, cpm: float,
                     dry: int, dry_max: int, no_click_s: float,
                     no_click_max: float, paused: bool = False) -> None:
        if running and paused:
            self.dot.set_state("idle")
            self.state_label.setText("PAUSED")
            self.state_label.setStyleSheet(
                f"color: {t.WARN}; "
                f"font-family: {t.FONT_DISPLAY}; "
                f"font-size: 16px; "
                f"font-weight: 700; "
                f"letter-spacing: 1.4px;"
            )
        elif running:
            self.dot.set_state("active")
            self.state_label.setText("RUNNING")
            self.state_label.setStyleSheet(
                f"color: {t.START}; "
                f"font-family: {t.FONT_DISPLAY}; "
                f"font-size: 16px; "
                f"font-weight: 700; "
                f"letter-spacing: 1.4px;"
            )
        else:
            self.dot.set_state("idle")
            self.state_label.setText("IDLE")
            self.state_label.setStyleSheet(
                f"color: {t.TEXT_PRIMARY}; "
                f"font-family: {t.FONT_DISPLAY}; "
                f"font-size: 16px; "
                f"font-weight: 700; "
                f"letter-spacing: 1.4px;"
            )

        if last_fired:
            self.rule_label.setText(f"last: {last_fired}")
        else:
            self.rule_label.setText("")

        self.chip_tick.set_value(f"{tick}")
        self.chip_clicks.set_value(f"{clicks}")
        self.chip_cpm.set_value(f"{cpm:.0f}" if cpm > 0 else "—")
        self.chip_phase.set_value(phase or "—",
                                   color=_phase_color(phase) if phase else None)

        # Watchdog colors: green when far from limit, amber close, red at.
        dry_color = (t.DANGER if dry >= dry_max else
                     t.WARN if dry >= dry_max * 0.7 else
                     t.TEXT_PRIMARY)
        idle_color = (t.DANGER if no_click_s >= no_click_max else
                      t.WARN if no_click_s >= no_click_max * 0.7 else
                      t.TEXT_PRIMARY)
        self.chip_dry.set_value(f"{dry} / {dry_max}", color=dry_color)
        self.chip_idle.set_value(
            f"{int(no_click_s)} / {int(no_click_max)}",
            color=idle_color,
        )


class _RulesSection(Card):
    """Rules list — populated when a bot is selected."""

    def __init__(self):
        super().__init__("Rules")
        self._rows: dict[str, _RuleRow] = {}
        self._empty = QLabel("Select a bot to see its rules.")
        self._empty.setStyleSheet(
            f"color: {t.TEXT_TERTIARY}; "
            f"font-size: {t.SIZE_SM}px; "
            f"padding: 8px 0;"
        )
        self.add(self._empty)

    def set_rules(self, rules: list) -> None:
        """``rules`` is the bot.rules list (Rule dataclasses)."""
        # Clear existing rows.
        for w in list(self._rows.values()):
            w.setParent(None)
        self._rows.clear()
        if not rules:
            self._empty.setText("This bot has no rules.")
            self._empty.setVisible(True)
            return
        self._empty.setVisible(False)
        for r in rules:
            row = _RuleRow(r.name, r.phase or "")
            self._rows[r.name] = row
            self.add(row)

    def fire(self, rule_name: str) -> None:
        row = self._rows.get(rule_name)
        if row is not None:
            row.set_active(hold_s=1.2)

    def tick(self) -> None:
        for r in self._rows.values():
            r.tick()


class _ConfigSection(Card):
    """Tick rate slider + monitor + dry-run toggle + advanced expander."""

    def __init__(self, app):
        super().__init__("Config")
        self.app = app

        # Tick rate as a real slider with format.
        self.tick_slider = LabeledSlider(
            app, "Tick rate", "ai_tick_rate_hz",
            from_=0.5, to=15.0, steps=29,
            value_fmt="{:.1f} Hz",
            tooltip="How often the bot evaluates rules. 2-5 Hz is the sweet spot for RS3.",
            is_int=False,
            on_change=self._on_tick_changed,
            hint="0.5 = lazy / 2 = relaxed / 5 = brisk / 10+ = aggressive",
        )
        self.add(self.tick_slider)

        # Monitor row.
        mon_row = QWidget()
        mr = QHBoxLayout(mon_row)
        mr.setContentsMargins(0, 4, 0, 0)
        mr.setSpacing(t.SP_SM)
        mlbl = QLabel("Monitor")
        mlbl.setStyleSheet(
            f"color: {t.TEXT_PRIMARY}; "
            f"font-size: {t.SIZE_BODY}px; "
            f"font-weight: 500;"
        )
        mr.addWidget(mlbl)
        mr.addStretch(1)
        self.monitor_combo = QComboBox()
        self.monitor_combo.setMinimumWidth(220)
        self.monitor_combo.setStyleSheet(
            f"QComboBox {{"
            f"  background: {t.SURFACE_PANEL}; "
            f"  border: 1px solid {t.BORDER}; "
            f"  border-radius: 6px; "
            f"  padding: 6px 10px; "
            f"  color: {t.TEXT_PRIMARY};"
            f"}}"
        )
        self._populate_monitors()
        self.monitor_combo.currentIndexChanged.connect(self._on_monitor_changed)
        mr.addWidget(self.monitor_combo)
        self.add(mon_row)

        # Dry-run toggle — IOSSwitch with status text.
        dry_row = QWidget()
        dr = QHBoxLayout(dry_row)
        dr.setContentsMargins(0, 6, 0, 0)
        dr.setSpacing(t.SP_SM)
        dlbl = QLabel("Dry run")
        dlbl.setStyleSheet(
            f"color: {t.TEXT_PRIMARY}; "
            f"font-size: {t.SIZE_BODY}px; "
            f"font-weight: 500;"
        )
        dr.addWidget(dlbl)
        self.dry_status = QLabel("")
        self.dry_status.setStyleSheet(
            f"color: {t.TEXT_TERTIARY}; "
            f"font-size: {t.SIZE_SM}px;"
        )
        dr.addWidget(self.dry_status)
        dr.addStretch(1)
        self.dry_switch = IOSSwitch()
        self.dry_switch.setChecked(bool(app.cfg.get("ai_dry_run", False)))
        self.dry_switch.toggled.connect(self._on_dry_run_changed)
        dr.addWidget(self.dry_switch)
        self.add(dry_row)
        self._refresh_dry_status()

        # Advanced expander — watchdog/auto-camera knobs. The Expander
        # widget owns its own chevron — pass label only, never bake the
        # arrow into the string.
        self.expander = Expander("Advanced — watchdogs & auto-camera")
        adv_body = QWidget()
        adv_layout = QVBoxLayout(adv_body)
        adv_layout.setContentsMargins(0, 6, 0, 0)
        adv_layout.setSpacing(8)
        for label, key, lo, hi, steps, fmt, hint in [
            ("Auto-stop dry ticks", "ai_auto_stop_dry_ticks",
             10, 300, 29, "{:.0f} ticks",
             "Stop the bot if N consecutive ticks fire nothing."),
            ("No-click watchdog", "ai_watchdog_no_click_s",
             60, 1800, 30, "{:.0f} s",
             "Stop the bot if no click occurs in N seconds."),
        ]:
            sl = LabeledSlider(
                app, label, key,
                from_=lo, to=hi, steps=steps,
                value_fmt=fmt, tooltip=hint,
                is_int=True, hint=hint,
            )
            adv_layout.addWidget(sl)
        self.expander.set_content(adv_body)
        self.add(self.expander)

    # ── Slot wires ───────────────────────────────────────────────────────
    def _on_tick_changed(self, v: float) -> None:
        runner = getattr(self.app, "bot_runner", None)
        if runner is not None:
            try:
                runner.set_tick_rate(float(v))
            except Exception:
                pass

    def _on_monitor_changed(self, _idx: int) -> None:
        data = self.monitor_combo.currentData()
        if data is None:
            return
        self.app.cfg["ai_monitor"] = int(data)
        save_config(self.app.cfg)

    def _on_dry_run_changed(self, checked: bool) -> None:
        self.app.cfg["ai_dry_run"] = bool(checked)
        save_config(self.app.cfg)
        try:
            self.app.bot_runner.set_dry_run(bool(checked))
        except Exception:
            pass
        self._refresh_dry_status()

    def _refresh_dry_status(self) -> None:
        on = self.dry_switch.isChecked()
        if on:
            self.dry_status.setText("ON — actions logged only, no real input")
            self.dry_status.setStyleSheet(
                f"color: {t.WARN}; font-size: {t.SIZE_SM}px;"
            )
        else:
            self.dry_status.setText("OFF — clicks & keys ARE firing")
            self.dry_status.setStyleSheet(
                f"color: {t.TEXT_TERTIARY}; font-size: {t.SIZE_SM}px;"
            )

    def _populate_monitors(self) -> None:
        # Try mss; fall back to a 0-3 list if it errors.
        try:
            import mss
            with mss.mss() as s:
                mons = s.monitors
            for i, m in enumerate(mons):
                if i == 0:
                    label = (f"Virtual ({m.get('width')}×{m.get('height')})")
                elif i == 1:
                    label = f"Primary ({m.get('width')}×{m.get('height')})"
                else:
                    label = f"Monitor {i} ({m.get('width')}×{m.get('height')})"
                self.monitor_combo.addItem(label, i)
        except Exception:
            for i in range(4):
                self.monitor_combo.addItem(
                    "Virtual" if i == 0
                    else "Primary" if i == 1
                    else f"Monitor {i}", i,
                )
        saved = int(self.app.cfg.get("ai_monitor", 1))
        for i in range(self.monitor_combo.count()):
            if self.monitor_combo.itemData(i) == saved:
                self.monitor_combo.setCurrentIndex(i)
                break


class _CalibrationSection(Card):
    """Awareness-layer ROI calibration — inventory, orbs, minimap.

    Each row shows the currently-stored rect (or "not calibrated") and
    a button that opens the fullscreen ZoneDrawer. After a successful
    rect capture, the rect is converted ``(x1, y1, x2, y2) → (x, y,
    w, h)`` and persisted to ``config.json``. The orbs row additionally
    captures ``max_fill`` per orb at calibration time — assumes the
    user is at 100% HP/Prayer/Run/Summoning.
    """

    def __init__(self, app):
        super().__init__("Awareness calibration")
        self.app = app
        # When a bundle is active, ROIs are read/written against the
        # bundle's calibration.json. Else the legacy global cfg keys.
        self._active_bundle = None

        # Subtitle hint.
        hint = QLabel(
            "One-time setup — captures where the inventory and orbs "
            "live on your screen so bots can read them."
        )
        hint.setWordWrap(True)
        hint.setStyleSheet(
            f"color: {t.TEXT_TERTIARY}; font-size: {t.SIZE_SM}px;"
        )
        self.add(hint)

        # Inventory row.
        self._inv_caption: QLabel
        self.add(self._build_row(
            label="Inventory ROI",
            caption_attr="_inv_caption",
            cfg_key="ai_inventory_rect",
            on_click=self._calibrate_inventory,
            disabled=False,
        ))

        # Bars row.
        self._orbs_caption: QLabel
        self.add(self._build_row(
            label="Bars ROI (HP / Adren / Prayer / Sum)",
            caption_attr="_orbs_caption",
            cfg_key="ai_orbs_rect",
            on_click=self._calibrate_orbs,
            disabled=False,
            extra_hint=(
                "Draw a TIGHT box around just the bar strip (exclude icons "
                "and numbers — they contain colors that look like the bars "
                "and inflate the readings). Be at 100% HP / Adrenaline / "
                "Prayer / Summoning before clicking."
            ),
        ))

        # Minimap row.
        self._mm_caption: QLabel
        self.add(self._build_row(
            label="Minimap ROI",
            caption_attr="_mm_caption",
            cfg_key="ai_minimap_rect",
            on_click=self._calibrate_minimap,
            disabled=False,
            extra_hint=(
                "Draw a rect around the entire minimap (compass + map + "
                "run-energy orb). Be at 100% run-energy when you click "
                "so the orb's max-fill calibrates. Used for player-move "
                "detection (recovery interrupts) and run-energy reads."
            ),
        ))

        self._refresh_captions()

    def _build_row(
        self, *, label: str, caption_attr: str, cfg_key: str,
        on_click, disabled: bool, extra_hint: str = "",
    ) -> QWidget:
        wrap = QWidget()
        outer = QVBoxLayout(wrap)
        outer.setContentsMargins(0, 8, 0, 0)
        outer.setSpacing(2)

        row = QWidget()
        rl = QHBoxLayout(row)
        rl.setContentsMargins(0, 0, 0, 0)
        rl.setSpacing(t.SP_SM)

        lbl = QLabel(label)
        lbl.setStyleSheet(
            f"color: {t.TEXT_PRIMARY}; "
            f"font-size: {t.SIZE_BODY}px; "
            f"font-weight: 500;"
        )
        rl.addWidget(lbl)

        caption = QLabel("not calibrated")
        caption.setStyleSheet(
            f"color: {t.TEXT_TERTIARY}; "
            f"font-size: {t.SIZE_SM}px; "
            f"font-family: {t.FONT_MONO};"
        )
        setattr(self, caption_attr, caption)
        rl.addWidget(caption)
        rl.addStretch(1)

        btn = QPushButton("Calibrate")
        btn.setMinimumHeight(t.BUTTON_H)
        btn.setCursor(Qt.PointingHandCursor)
        btn.setEnabled(not disabled)
        btn.clicked.connect(on_click)
        rl.addWidget(btn)

        outer.addWidget(row)

        if extra_hint:
            sub = QLabel(extra_hint)
            sub.setWordWrap(True)
            sub.setStyleSheet(
                f"color: {t.TEXT_TERTIARY}; font-size: {t.SIZE_SM}px;"
            )
            outer.addWidget(sub)

        return wrap

    # ── Bundle-awareness ────────────────────────────────────────
    def _on_active_bundle_changed(self, bundle) -> None:
        """Hooked from AIPageBody._activate_bundle. Rebinds the rect
        read/write target so calibration is per-bot when a bundle is
        active."""
        self._active_bundle = bundle
        self._refresh_captions()

    def _read_rect(self, key: str):
        """Read a rect from the active bundle (preferred) or app.cfg
        (fallback). ``key`` is one of inventory_rect / orbs_rect /
        minimap_rect — the bundle uses the same keys without the ``ai_``
        prefix that legacy cfg uses."""
        if self._active_bundle is not None:
            bundle_key = key.removeprefix("ai_")
            return self._active_bundle.calibration.get(bundle_key)
        return self.app.cfg.get(key)

    def _write_rect(self, key: str, value) -> None:
        """Persist a rect to the active bundle or to global cfg."""
        if self._active_bundle is not None:
            bundle_key = key.removeprefix("ai_")
            self._active_bundle.calibration[bundle_key] = value
            self._active_bundle.save_field("calibration")
        else:
            self.app.cfg[key] = value
            save_config(self.app.cfg)

    def _refresh_captions(self) -> None:
        bundle_label = (
            f"  ·  bundle: {self._active_bundle.name}"
            if self._active_bundle is not None else ""
        )
        for cap_attr, cfg_key in (
            ("_inv_caption", "ai_inventory_rect"),
            ("_orbs_caption", "ai_orbs_rect"),
            ("_mm_caption", "ai_minimap_rect"),
        ):
            cap = getattr(self, cap_attr, None)
            if cap is None:
                continue
            rect = self._read_rect(cfg_key)
            if (isinstance(rect, (list, tuple)) and len(rect) == 4):
                x, y, w, h = (int(v) for v in rect)
                cap.setText(f"x={x}  y={y}  w={w}  h={h}{bundle_label}")
                cap.setStyleSheet(
                    f"color: {t.TEXT_SECONDARY}; "
                    f"font-size: {t.SIZE_SM}px; "
                    f"font-family: {t.FONT_MONO};"
                )
            else:
                cap.setText("not calibrated")
                cap.setStyleSheet(
                    f"color: {t.TEXT_TERTIARY}; "
                    f"font-size: {t.SIZE_SM}px; "
                    f"font-family: {t.FONT_MONO};"
                )

    def _capture_rect(self, on_rect):
        """Open the ZoneDrawer; call ``on_rect((x, y, w, h))`` on commit."""
        def _done(zone):
            if zone is None or zone.shape != "rect" or not zone.rect:
                return
            x1, y1, x2, y2 = zone.rect
            x, y = int(min(x1, x2)), int(min(y1, y2))
            w, h = int(abs(x2 - x1)), int(abs(y2 - y1))
            if w < 4 or h < 4:
                self.app.toasts.post(
                    "⚠ Calibration rect too small — try again", kind="warn",
                )
                return
            on_rect((x, y, w, h))
        self.app.open_zone_drawer("rect", _done)

    def _calibrate_inventory(self) -> None:
        def _save(rect):
            self._write_rect("ai_inventory_rect", list(rect))
            self._refresh_captions()
            scope = (
                f" → bundle {self._active_bundle.name!r}"
                if self._active_bundle is not None else ""
            )
            self.app.toasts.post(
                f"✓ Inventory ROI captured: {rect[2]}×{rect[3]}{scope}",
                kind="success",
            )
        self._capture_rect(_save)

    def _calibrate_orbs(self) -> None:
        def _save(rect):
            self._write_rect("ai_orbs_rect", list(rect))
            max_fill = self._capture_orbs_max_fill(rect)
            if max_fill:
                if self._active_bundle is not None:
                    self._active_bundle.calibration["orbs_max_fill"] = max_fill
                    self._active_bundle.save_field("calibration")
                else:
                    self.app.cfg["ai_orbs_max_fill"] = max_fill
                    save_config(self.app.cfg)
            self._refresh_captions()
            if max_fill:
                self.app.toasts.post(
                    "✓ Orbs ROI + max-fill captured "
                    f"(hp={max_fill.get('hp',0)}, "
                    f"prayer={max_fill.get('prayer',0)}, "
                    f"sum={max_fill.get('summoning',0)}, "
                    f"run={max_fill.get('run_energy',0)}). "
                    "Bots can now read percentages.",
                    kind="success",
                )
            else:
                self.app.toasts.post(
                    "✓ Orbs ROI captured (max-fill failed — recalibrate to enable %)",
                    kind="warn",
                )
        self._capture_rect(_save)

    def _calibrate_minimap(self) -> None:
        """Capture the minimap rect + the run-energy orb's max_fill at
        the moment of calibration (assumes player is at 100% run)."""
        def _save(rect):
            self._write_rect("ai_minimap_rect", list(rect))
            max_fill = self._capture_run_energy_max_fill(rect)
            scope = (
                f" → bundle {self._active_bundle.name!r}"
                if self._active_bundle is not None else ""
            )
            if max_fill > 0:
                if self._active_bundle is not None:
                    cal = self._active_bundle.calibration
                    cal.setdefault("orbs_max_fill", {})["run_energy"] = int(max_fill)
                    self._active_bundle.save_field("calibration")
                else:
                    om = dict(self.app.cfg.get("ai_orbs_max_fill") or {})
                    om["run_energy"] = int(max_fill)
                    self.app.cfg["ai_orbs_max_fill"] = om
                    save_config(self.app.cfg)
                self.app.toasts.post(
                    f"✓ Minimap ROI {rect[2]}×{rect[3]}  ·  run-energy max_fill={max_fill}{scope}",
                    kind="success",
                )
            else:
                self.app.toasts.post(
                    f"✓ Minimap ROI captured — run-energy max_fill = 0, "
                    "recalibrate at 100% run for percentages to read.",
                    kind="warn",
                )
            self._refresh_captions()
        self._capture_rect(_save)

    def _capture_run_energy_max_fill(self, rect) -> int:
        """Grab a frame from the configured AI monitor and run
        :func:`ai.algorithms.minimap.calibrate_run_energy_max_fill` on
        the picked rect. Returns 0 on any failure (capture, conversion,
        ROI translation)."""
        try:
            import mss
            import numpy as np
            from ai.algorithms.minimap import calibrate_run_energy_max_fill
            with mss.mss() as sct:
                mons = sct.monitors
                idx = int(self.app.cfg.get("ai_monitor", 1))
                if not (0 <= idx < len(mons)):
                    idx = 1 if len(mons) > 1 else 0
                raw = sct.grab(mons[idx])
                frame = np.ascontiguousarray(
                    np.asarray(raw, dtype=np.uint8)[:, :, :3]
                )
                mon = mons[idx]
                mx = int(mon.get("left", 0))
                my = int(mon.get("top", 0))
            x, y, w, h = rect
            local_rect = (x - mx, y - my, w, h)
            return int(calibrate_run_energy_max_fill(frame, local_rect))
        except Exception as e:
            self.app.toasts.post(
                f"⚠ Run-energy max-fill capture failed: {type(e).__name__}: {e}",
                kind="warn",
            )
            return 0

    def _capture_orbs_max_fill(self, rect) -> dict:
        """Grab a frame and run orbs.calibrate_at_full on the picked rect."""
        try:
            import mss
            import numpy as np
            from ai.algorithms import orbs as _orbs
            with mss.mss() as sct:
                mons = sct.monitors
                idx = int(self.app.cfg.get("ai_monitor", 1))
                if not (0 <= idx < len(mons)):
                    idx = 1 if len(mons) > 1 else 0
                raw = sct.grab(mons[idx])
                frame = np.ascontiguousarray(
                    np.asarray(raw, dtype=np.uint8)[:, :, :3]
                )
            # The captured frame's coordinates are local to the chosen
            # monitor — but the rect is in absolute virtual-screen
            # space. Translate by the monitor's origin.
            mon = mons[idx]
            mx, my = int(mon.get("left", 0)), int(mon.get("top", 0))
            x, y, w, h = rect
            local_rect = (x - mx, y - my, w, h)
            return _orbs.calibrate_at_full(frame, local_rect)
        except Exception as e:
            self.app.toasts.post(
                f"⚠ Orbs max-fill capture failed: {type(e).__name__}: {e}",
                kind="warn",
            )
            return {}


class _LogSection(Card):
    """Tabbed log: All / Rules / Errors. Color-coded lines."""

    def __init__(self):
        super().__init__("Log")

        self._all: list[str] = []          # raw lines
        self._all_html: list[str] = []      # color-tagged
        self._filter = "all"

        # Tab strip
        self.tabs = SegmentedControl(
            options=[("all", "All"), ("rules", "Rule fires"), ("errors", "Errors")],
            value="all",
        )
        self.tabs.valueChanged.connect(self._on_filter)
        # Pull tabs into the card header so they read as a real tab strip.
        self.add_to_header(self.tabs)

        # Log view.
        self.view = QPlainTextEdit()
        self.view.setReadOnly(True)
        self.view.setMinimumHeight(180)
        self.view.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        mono = QFont(t.FONT_MONO.split(",")[0].strip())
        mono.setStyleHint(QFont.TypeWriter)
        mono.setPointSize(9)
        self.view.setFont(mono)
        self.view.setStyleSheet(
            f"QPlainTextEdit {{"
            f"  background: {t.SURFACE_PANEL}; "
            f"  border: 1px solid {t.BORDER_SUBTLE}; "
            f"  border-radius: 6px; "
            f"  padding: 8px; "
            f"  color: {t.TEXT_SECONDARY};"
            f"}}"
        )
        self.add(self.view)

    def append(self, line: str) -> None:
        self._all.append(line)
        if len(self._all) > 1000:
            self._all = self._all[-1000:]
        if self._matches(line, self._filter):
            self._append_styled(line)

    def _on_filter(self, value: str) -> None:
        self._filter = value
        self.view.clear()
        for line in self._all:
            if self._matches(line, value):
                self._append_styled(line)

    @staticmethod
    def _matches(line: str, flt: str) -> bool:
        if flt == "all":
            return True
        if flt == "rules":
            return ("rule " in line) or ("fired" in line)
        if flt == "errors":
            ll = line.lower()
            return any(s in ll for s in ("error", "fail", "crash", "warn"))
        return True

    def _append_styled(self, line: str) -> None:
        ll = line.lower()
        if any(s in ll for s in ("error", "crash", "fail")):
            color = t.DANGER
        elif "warn" in ll:
            color = t.WARN
        elif "rule " in line or "fired" in line:
            color = t.ACCENT_TEXT
        elif "click " in line or "key press" in line:
            color = t.START
        else:
            color = t.TEXT_SECONDARY
        # appendHtml handles per-line color; cheap escape for < > &.
        safe = (line.replace("&", "&amp;")
                    .replace("<", "&lt;")
                    .replace(">", "&gt;"))
        self.view.appendHtml(f'<span style="color:{color};">{safe}</span>')
        sb = self.view.verticalScrollBar()
        sb.setValue(sb.maximum())


# ─────────────────────────────────────────────────────────────────────────
# Page body — composes the five sections + wires runner signals
# ─────────────────────────────────────────────────────────────────────────


class AIPageBody(QWidget):
    """Body widget for the AI page."""

    def __init__(self, app):
        super().__init__()
        self.app = app
        self._bots: list[dict] = _enumerate_bots()
        # Per-bot bundles (bots/<slug>/). Loaded on init and refreshed
        # whenever a bundle is created/deleted via the Hero dropdown.
        from ai.bot.bundle import list_bundles
        from ui.config_io import _config_dir
        self._bundles = list_bundles(_config_dir())
        self._active_bundle = None  # set by _activate_bundle()
        self._loaded_bot = None
        self._session_clicks: int = 0
        self._session_start: float = 0.0

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(t.SP_LG)

        # 1. Hero
        self.hero = _HeroSection(app, self)
        outer.addWidget(self.hero)

        # 1b. Authoring — only visible when "Custom Bot (in-GUI)" is picked.
        from .ai_authoring import AIAuthoringSection
        self.authoring = AIAuthoringSection(app)
        # Re-render the dashboard rule list when the user edits steps.
        self.authoring.stepsChanged.connect(self._on_bot_selection_changed)
        outer.addWidget(self.authoring)

        # 1c. Captures — snapshot / record / colour-label, scoped to the
        # active bundle. Always visible so users can see what's captured.
        from .ai_captures import AICapturesSection
        self.captures = AICapturesSection(app)
        outer.addWidget(self.captures)

        # 1d. Global capture library — every capture promoted from a
        # bundle, browsable across bots. Refreshes automatically when
        # the captures card emits ``globalCapturesChanged``.
        from .ai_library import AILibrarySection
        self.library = AILibrarySection(app)
        self.captures.globalCapturesChanged.connect(self.library.refresh)
        outer.addWidget(self.library)

        # 2. Live
        self.live = _LiveSection(app)
        outer.addWidget(self.live)

        # 3. Rules
        self.rules = _RulesSection()
        outer.addWidget(self.rules)

        # 4. Config
        self.config = _ConfigSection(app)
        outer.addWidget(self.config)

        # 5. Calibration (ROIs for inventory / orbs / minimap).
        self.calibration = _CalibrationSection(app)
        outer.addWidget(self.calibration)

        # 6. Log
        self.log = _LogSection()
        outer.addWidget(self.log, 1)

        outer.addStretch(0)

        self._wire_runner_signals()
        # Activate any bundle that was selected before the previous
        # shutdown so the Calibration / Captures sections can populate
        # immediately rather than after a manual click.
        active_slug = str(self.app.cfg.get("ai_active_bundle") or "")
        if active_slug:
            self._activate_bundle(active_slug)
        self._on_bot_selection_changed()

    # ── Public surface (used by app.py) ─────────────────────────────────
    def refresh_bundles(self) -> None:
        """Re-scan ``bots/`` and update the dropdown. Called after a
        bundle is created, deleted, or renamed."""
        from ai.bot.bundle import list_bundles
        from ui.config_io import _config_dir
        self._bundles = list_bundles(_config_dir())
        self.hero._refresh()

    def _activate_bundle(self, slug: str) -> None:
        """Mark a bundle as the current target. Triggered by the Hero
        dropdown when the user selects a bundle. The Calibration
        section + Captures section read from the active bundle."""
        bundle = next((b for b in self._bundles if b.slug == slug), None)
        self._active_bundle = bundle
        # Switch the editor's data source to the bundle (or back to
        # legacy cfg when bundle is None).
        if hasattr(self.app, "set_ai_authoring_bundle"):
            self.app.set_ai_authoring_bundle(bundle)
        # Notify children that depend on the active bundle.
        for child_attr in ("calibration", "captures", "authoring"):
            child = getattr(self, child_attr, None)
            if child is not None and hasattr(child, "_on_active_bundle_changed"):
                child._on_active_bundle_changed(bundle)
        # Re-render the editor against the new step source.
        if self.authoring is not None:
            self.authoring.render_all()

    def active_bundle(self):
        """Return the currently-selected bundle, or ``None`` for legacy /
        library bot mode. The runner uses this to source calibration +
        assets when starting a bundle bot."""
        return self._active_bundle

    def current_bot_meta(self) -> Optional[dict]:
        idx = self.hero.bot_combo.currentIndex()
        data = self.hero.bot_combo.itemData(idx)
        if data == self.hero.CUSTOM_BOT_DATA:
            return None  # legacy custom mode — handled by _on_start_ai
        if isinstance(data, str) and data.startswith(self.hero.BUNDLE_PREFIX):
            return None  # bundle mode — handled by _on_start_ai
        for b in self._bots:
            if b["slug"] == data:
                return b
        return None

    def load_current_bot(self):
        meta = self.current_bot_meta()
        if meta is None:
            return None
        try:
            bot = _import_bot(meta["bot_ref"], meta["yaml_path"])
            self._loaded_bot = bot
            self.rules.set_rules(bot.rules)
            return bot
        except Exception as e:
            self.app.toasts.post(
                f"⚠ Couldn't load bot {meta['slug']}: {type(e).__name__}: {e}",
                kind="error",
            )
            return None

    def tick(self) -> None:
        """Polled by ``App._tick`` — refreshes the live status board and
        fades rule highlights."""
        self._update_live()
        self.rules.tick()
        self._update_bot_overlay()

    def _update_bot_overlay(self) -> None:
        """Drive the AI BotOverlay HUD from the runner's current state.

        Shows ROI + ``proc:pc — kind`` badge while the bot is running
        and the global overlay toggle is on. Hides cleanly when the
        bot stops or the toggle is off.
        """
        ov = getattr(self.app, "bot_overlay", None)
        if ov is None:
            return
        runner = getattr(self.app, "bot_runner", None)
        show = bool(self.app.cfg.get("show_zone_overlay", True))
        running = bool(runner.is_running()) if runner is not None else False
        if not (running and show):
            if ov.isVisible():
                ov.clear()
                ov.hide()
            return
        info = None
        try:
            info = runner.current_step_info()
        except Exception:
            info = None
        if info is None:
            return
        roi = info.get("roi")
        kind = info.get("kind") or ""
        proc = info.get("proc") or ""
        pc = int(info.get("pc") or 0)
        status = f"{proc}:{pc + 1}"
        if kind:
            status += f" — {kind}"
        ov.set_roi(tuple(roi) if roi else None)
        ov.set_status(status)
        if not ov.isVisible():
            ov.show()

    # ── Internal ───────────────────────────────────────────────────────
    def _on_bot_selection_changed(self) -> None:
        use_custom = bool(self.app.cfg.get("ai_use_user_bot", False))
        bundle_active = self._active_bundle is not None
        # Toggle the authoring surface visibility — show when either
        # the legacy custom mode or a bundle is active.
        self.authoring.setVisible(use_custom or bundle_active)

        if bundle_active:
            from ai.bot.compiler import rule_name_for
            from ai.bot.bot import Rule
            rules = [
                Rule(
                    name=rule_name_for(s),
                    func=lambda: False,
                    phase=s.phase or "",
                    enabled=bool(s.enabled),
                )
                for s in self.app._ai_user_steps
            ]
            self.rules.set_rules(rules)
            return

        if use_custom:
            # Preview the user's compiled rule list for the dashboard.
            # Use the same rule_name_for() helper the compiler uses, so
            # the live highlight (`bot.rule.<name>`) lands on the right
            # row at runtime.
            from ai.bot.compiler import rule_name_for
            from ai.bot.bot import Rule
            rules = [
                Rule(
                    name=rule_name_for(s),
                    func=lambda: False,
                    phase=s.phase or "",
                    enabled=bool(s.enabled),
                )
                for s in self.app._ai_user_steps
            ]
            self.rules.set_rules(rules)
            return

        # Library bot path — try to import lazily so the rule list is
        # populated even before the user hits Start. Failures are silent
        # here; they'll surface loudly on Start via load_current_bot().
        meta = self.current_bot_meta()
        if meta is None:
            self.rules.set_rules([])
            return
        try:
            bot = _import_bot(meta["bot_ref"], meta["yaml_path"])
            self._loaded_bot = bot
            self.rules.set_rules(bot.rules)
        except Exception:
            self.rules.set_rules([])

    def _wire_runner_signals(self) -> None:
        runner = getattr(self.app, "bot_runner", None)
        if runner is None:
            return
        runner.log.connect(self.log.append)
        runner.frame_captured.connect(self.live.preview.update_frame)
        runner.block_executed.connect(self._on_block_executed)
        runner.status.connect(self._on_status)
        runner.finished.connect(self._on_finished)

    def _on_status(self, msg: str) -> None:
        ml = msg.lower()
        if "running" in ml:
            self._session_clicks = 0
            self._session_start = time.monotonic()
            self.authoring.set_running(True)
        elif "stopped" in ml or "idle" in ml:
            self.authoring.set_running(False)

    def _on_finished(self, _reason: str) -> None:
        # Status board picks up "not running" via tick() snapshot.
        self.authoring.set_running(False)
        # Restore the global realism slider if a per-bot override was
        # applied at start. No-op when no override was active.
        try:
            self.app._restore_realism_after_bot()
        except Exception:
            pass
        ov = getattr(self.app, "bot_overlay", None)
        if ov is not None:
            try:
                ov.clear()
                ov.hide()
            except Exception:
                pass

    def _on_block_executed(self, info: dict) -> None:
        ident = (info or {}).get("identifier", "")
        if ident.startswith("bot.rule."):
            rule_name = ident.split(".", 2)[-1]
            self.rules.fire(rule_name)
            # Poor-man's click counter — most rules click. A more accurate
            # count would hook the actuator, but rule-fire is a usable
            # proxy for "things happened" until then.
            self._session_clicks += 1

    def _update_live(self) -> None:
        runner = getattr(self.app, "bot_runner", None)
        rule_phase = ""
        running = False
        last_rule = ""
        tick = 0
        dry = 0
        clicks = 0
        no_click_s = 0.0

        if runner is not None:
            snap = runner.last_fired()
            running = bool(snap.get("running"))
            last_rule = snap.get("last_fired_rule") or ""
            if last_rule and self._loaded_bot is not None:
                for r in self._loaded_bot.rules:
                    if r.name == last_rule:
                        rule_phase = r.phase or ""
                        break
            tick = int(snap.get("current_tick") or 0)
            dry = int(snap.get("consecutive_dry_ticks") or 0)
            clicks = int(snap.get("click_count") or 0)
            no_click_s = float(snap.get("no_click_age_s") or 0.0)

        # CPM from real click count + session elapsed.
        if running and self._session_start > 0.0:
            elapsed = max(0.001, time.monotonic() - self._session_start)
        else:
            elapsed = 0.0
        cpm = (60.0 * clicks / elapsed) if elapsed > 1.0 and clicks > 0 else 0.0

        # Watchdog limits from cfg / bot.
        dry_max = int(self.app.cfg.get("ai_auto_stop_dry_ticks", 60))
        no_click_max = float(self.app.cfg.get("ai_watchdog_no_click_s", 600.0))
        if self._loaded_bot is not None:
            dry_max = int(getattr(self._loaded_bot, "auto_stop_dry_ticks", dry_max))
            no_click_max = float(
                getattr(self._loaded_bot, "watchdog_no_click_s", no_click_max)
            )

        paused = False
        if runner is not None:
            try:
                paused = bool(runner.is_paused())
            except Exception:
                paused = False

        self.live.update_state(
            running=running,
            last_fired=last_rule,
            phase=rule_phase,
            tick=tick,
            clicks=clicks,
            cpm=cpm,
            dry=dry,
            dry_max=max(1, dry_max),
            no_click_s=no_click_s,
            no_click_max=max(1.0, no_click_max),
            paused=paused,
        )
