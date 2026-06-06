"""PhantomClick Qt main window — landscape NavRail shell.

QMainWindow with three pieces stacked: a 52-px ``TopBar`` (brand + status
pill + Start/Stop + icon buttons), a left ``NavRail`` that switches the
active page, and a ``QStackedWidget`` of pages on the right. Each page
hosts existing :class:`Card` widgets without any wrapper logic of its own.

Most cross-cutting state (cfg, engine, tracker, zones, steps, hotkeys)
lives on this class as the canonical reference; cards take ``app: App``
and reach in. That's the same composition pattern from the Tk refactor.
"""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Optional

from PySide6.QtCore import Qt, QTimer, Signal, Slot
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QApplication, QHBoxLayout, QMainWindow, QStackedWidget, QVBoxLayout,
    QWidget,
)

from modules.clicker import Clicker, ClickerState
from modules.hotkey_manager import HotkeyManager
from modules.key_timer import deserialize_timers
from modules.recorder import (
    KIND_CLICK, KIND_COLOR, KIND_PAUSE, KIND_TRACK, deserialize_steps,
    serialize_steps,
)
from modules.stats import Stats
from modules.tracker import TemplateTracker, TrackerConfig
from modules.zone_selector import Zone

from ui.config_io import DEFAULTS, _config_dir, load_config, save_config
from utils import dpi_cursor
from utils.logger import get_logger

from . import engine_bridge, theme as t
from .cards.behavior import BehaviorCard
from .cards.hotkeys import HotkeysCard
from .cards.hover_zones import HoverZonesCard
from .cards.record_mode import RecordModeTab
from .cards.stats import StatsCard
from .commands import register_all as register_commands
from .pages.ai_page import build_ai_page
from .pages.behavior_page import build_behavior_page
from .pages.click_page import ClickPage
from .pages.help_page import HelpPage
from .pages.hotkeys_page import build_hotkeys_page
from .pages.hover_page import build_hover_page
from .pages.monitor_page import build_monitor_page
from .pages.settings_page import build_settings_page
from .pages.simple_page import SimplePage
from .pages.stats_page import build_stats_page
from .pages.timers_page import build_timers_page
from .monitor_server import MonitorServer
from .qss import build_stylesheet
from .overlay_manager import OverlayManager
from .topbar import TopBar
from .tracker_preview import TrackerPreview
from .widget_lock import WidgetLocker
from .widgets.nav_rail import NavRail
from .widgets.toast import ToastHost


class App(QMainWindow):
    # Cross-thread marshal for the F9 capture hotkey. pynput's listener
    # fires on its own daemon thread, and ``QTimer.singleShot`` from a
    # thread without an event loop is silently discarded in Qt6. A
    # queued-connection signal hops cleanly back to the main thread.
    _captureHotkeyFired = Signal(int, int)  # cursor x, y in DIPs

    # Engine-thread → Qt-main marshal for the click-marker flash. The
    # engine fires ``on_click_fired`` from its own daemon thread, so this
    # follows the same Signal pattern as ``_captureHotkeyFired`` — naked
    # ``QTimer.singleShot`` from a non-event-loop thread is silently
    # dropped in Qt6.
    _engineClickFired = Signal(int, int, int, int, str)
    # tx, ty, ax, ay, kind

    def __init__(self):
        super().__init__()
        self.log = get_logger()
        self.cfg = load_config()

        # Snapshot DIP / physical screen geometry so the engine thread can
        # convert between Qt's DIP coords (used for zones, overlays) and
        # Win32's physical pixels (used by SetCursorPos / GetCursorPos).
        # Without this, on a >100% DPI monitor pynput moves at 1/DPR of
        # the requested DIP coord and clicks miss the visible zone.
        dpi_cursor.refresh_screens()

        def _on_screens_changed(_s=None):
            dpi_cursor.refresh_screens()
            # Settings card may not exist yet during early init.
            card = getattr(self, "settings_card", None)
            if card is not None:
                try:
                    card.refresh_monitors()
                except Exception:
                    pass
            # Also re-push monitor bounds to the engine so a freshly
            # plugged-in display becomes the new auto-detect target.
            self._push_config_to_clicker()

        QApplication.instance().screenAdded.connect(_on_screens_changed)
        QApplication.instance().screenRemoved.connect(_on_screens_changed)

        self.setWindowTitle("PhantomClick")
        self.setMinimumSize(t.WINDOW_W_MIN, t.WINDOW_H_MIN)
        self.resize(
            int(self.cfg.get("window_w", t.WINDOW_W_DEFAULT)),
            int(self.cfg.get("window_h", t.WINDOW_H_DEFAULT)),
        )
        QApplication.instance().setStyleSheet(build_stylesheet())

        # -- Core state ----------------------------------------------------
        self.stats = Stats()
        self.clicker = Clicker(
            self.stats,
            on_state_change=lambda s: engine_bridge.on_clicker_state(self, s),
        )
        self.clicker.on_click_fired = self._on_engine_click_fired
        self.clicker.on_track_error = lambda sid, reason: (
            engine_bridge.on_track_error(self, sid, reason)
        )
        self.clicker.on_session_complete = lambda reason: (
            engine_bridge.on_session_complete(self, reason)
        )
        self.clicker.on_engine_halt = lambda msg, level: (
            engine_bridge.on_engine_halt(self, msg, level)
        )
        # AI mode — RS3_AI bot framework with PhantomClick as actuator.
        # Construct lazily-imported so users without the ai/ tree on disk
        # (e.g. an auto-clicker-only fork) still launch.
        self.bot_runner = None
        self.ai_actuator = None
        try:
            from ai.bot.runner import BotRunner as _BotRunner
            from ai.input.clicker_actuator import ClickerActuatorBackend
            self.bot_runner = _BotRunner()
            self.ai_actuator = ClickerActuatorBackend(self)
        except Exception as e:
            self.log.warning("AI mode disabled — could not import: %s", e)
        self.overlay_manager = OverlayManager(self)
        # AI live overlay (D.2) — translucent click-through HUD wired
        # to bot_runner.tick_started + block_executed. Lazy-imported so
        # AI failures don't break Click/Record mode startup. Lifetime
        # is App-scoped; visibility tracks bot run state + the topbar
        # 👁 toggle.
        self.bot_overlay = None
        try:
            from ui.overlays.bot_overlay import BotOverlay
            self.bot_overlay = BotOverlay()
        except Exception as e:
            self.log.warning("BotOverlay disabled — could not import: %s", e)
        self._bot_overlay_timer = None  # set up lazily once Qt is alive
        self.locker = WidgetLocker()
        self._monitor_size_init()
        self.hotkeys = HotkeyManager(
            start_name=self.cfg.get("hotkey_start", "f6"),
            stop_name=self.cfg.get("hotkey_stop", "f7"),
            on_start=lambda: engine_bridge.schedule_start(self),
            on_stop=lambda: engine_bridge.schedule_stop(self),
            on_emergency_stop=lambda: engine_bridge.schedule_emergency_stop(self),
            pause_name=self.cfg.get("hotkey_pause", "f8"),
            on_pause=lambda: engine_bridge.schedule_toggle_pause(self),
            capture_name=self.cfg.get("hotkey_capture", "f9"),
            on_capture=self._on_capture_hotkey,
        )
        self._captureHotkeyFired.connect(
            self._run_capture_hotkey, Qt.QueuedConnection,
        )
        self._engineClickFired.connect(
            self._flash_click_marker_main, Qt.QueuedConnection,
        )

        # User data
        self._zone: Optional[Zone] = Zone.from_json(self.cfg.get("zone"))
        self._zone_shape: str = self.cfg.get("zone_shape", "rect")
        self._hover_zones: list[Zone] = [
            z for z in (Zone.from_json(d) for d in self.cfg.get("hover_zones", []))
            if z is not None
        ]
        self._hover_shape: str = self.cfg.get("hover_zone_shape", "rect")
        self._steps = deserialize_steps(self.cfg.get("recorder_steps", []))
        # In-GUI AI bot authoring — each AIBotStep maps to one synthesized
        # @bot.rule at Start time via ai.bot.compile_user_bot.
        from ai.bot.authoring import deserialize_steps as _deserialize_ai_steps
        self._ai_user_steps = _deserialize_ai_steps(
            self.cfg.get("ai_user_bot_steps", [])
        )
        # Names of wiki-sourced items the user has added to this bot's
        # library. Each name has a cached icon under debug/wiki_cache/items/.
        # The library is rebuilt at Start time (App._build_ai_item_library)
        # and attached to the compiled Bot.
        self._ai_item_names: list[str] = [
            str(n) for n in (self.cfg.get("ai_user_bot_items") or [])
            if isinstance(n, str) and n.strip()
        ]
        # Session-scoped LIFO trash for deleted steps so accidental delete
        # is recoverable. Each entry = (step_obj, original_index, [moved_files]).
        # Capacity 10; oldest pushed off the cap has its trashed templates
        # actually unlinked. Cleared on app close (templates/.trash/ purged).
        self._step_trash: list[tuple[object, int, list[Path]]] = []
        # Listeners that re-render when trash changes (footer affordance, etc.)
        self._step_trash_listeners: list = []
        self._key_timers = deserialize_timers(self.cfg.get("key_timers", []))
        self._active_mode: str = self.cfg.get("active_mode", "clicker")
        self._state_str: str = ClickerState.IDLE
        self._tracker: TemplateTracker = TemplateTracker(TrackerConfig())
        self.tracker_preview = TrackerPreview(self)

        # Scratch state for the single-active-zone-drawer invariant.
        self._track_snapshot = None
        self._capturing_track_step_idx: Optional[int] = None
        self._drawing_step_idx: Optional[int] = None
        self._drawing_hover_idx: Optional[int] = None

        # Shared Realism→Advanced registry. Behavior + Hover cards both
        # register their controls here; the realism slider walks it on
        # change to push values back into widgets.
        self._adv_sliders: dict = {}   # cfg_key -> (RangeSlider/Slider, value-label, fmt, is_int)
        self._adv_vars: dict = {}       # cfg_key -> QCheckBox

        # -- UI scaffold ---------------------------------------------------
        self._build_ui()

        engine_bridge.push_config_to_clicker(self)
        engine_bridge.refresh_action_buttons(self, ClickerState.IDLE)
        self.hotkeys.start()

        # Seed live tracker preview from the most-recent track step (if any).
        self.tracker_preview.seed_from_steps()
        # Restore overlays for any persisted zones.
        if self._zone is not None and self.cfg.get("show_zone_overlay", True) \
                and self._active_mode == "clicker":
            self.overlay_manager.show_main(
                self._zone, self.cfg["zone_color"], self.cfg["zone_opacity"],
            )
        self.overlay_manager.refresh_hover_overlays()
        self.overlay_manager.refresh_step_overlays()

        # 100 ms tick drives status / stats / countdown.
        self._tick_timer = QTimer(self)
        self._tick_timer.timeout.connect(self._tick)
        self._tick_timer.start(100)

    # -- Native chrome (Mica + dark titlebar) ----------------------------
    def showEvent(self, event):  # noqa: N802 (Qt name)
        super().showEvent(event)
        if not getattr(self, "_chrome_applied", False):
            self._chrome_applied = True
            self._apply_native_chrome()

    def _apply_native_chrome(self) -> None:
        from .win32_native import apply_dark_titlebar, apply_mica
        hwnd = int(self.winId())
        apply_dark_titlebar(hwnd)
        if self.cfg.get("mica_enabled", True) and apply_mica(hwnd):
            # Mica needs the window + central widget to NOT paint a solid
            # background. We append a transparency override here so the
            # solid-BG default still applies when Mica isn't active.
            extra = (
                "\nQMainWindow { background: transparent; }"
                "\n#central { background: transparent; }"
            )
            qa = QApplication.instance()
            qa.setStyleSheet(qa.styleSheet() + extra)

    def _monitor_size_init(self) -> None:
        try:
            import ctypes
            u = ctypes.windll.user32
            self.monitor_w, self.monitor_h = (u.GetSystemMetrics(0), u.GetSystemMetrics(1))
        except Exception:
            self.monitor_w, self.monitor_h = (1920, 1080)

    # -- UI construction --------------------------------------------------

    def _build_ui(self) -> None:
        # -- Shell: TopBar / NavRail / QStackedWidget ---------------------
        central = QWidget(self)
        central.setObjectName("central")
        central_layout = QVBoxLayout(central)
        central_layout.setContentsMargins(0, 0, 0, 0)
        central_layout.setSpacing(0)
        self.setCentralWidget(central)

        # Topbar (status pill + Start/Stop + palette + overlay toggle).
        # Pinned full-width at the top.
        self.topbar = TopBar(self)
        # Engine bridge / hotkeys / commands look for these on the App.
        self.start_btn = self.topbar.start_btn
        self.stop_btn = self.topbar.stop_btn
        # The HotkeysCard rebind flow calls ``app.action_bar.refresh_hint()``
        # to update the Start/Stop button tooltips after rebind. Topbar
        # exposes the same method, so we alias it for back-compat.
        self.action_bar = self.topbar
        central_layout.addWidget(self.topbar)

        # Body: rail on the left, swappable pages on the right.
        body = QWidget(central)
        body_layout = QHBoxLayout(body)
        body_layout.setContentsMargins(0, 0, 0, 0)
        body_layout.setSpacing(0)
        central_layout.addWidget(body, 1)

        nav_items = [
            ("click",    "▣", "Click"),
            ("record",   "▦", "Record"),
            ("ai",       "🧠", "AI"),
            ("hover",    "⌖", "Hover"),
            ("behavior", "⚙", "Behavior"),
            ("hotkeys",  "⌨", "Hotkeys"),
            ("timers",   "⏲", "Timers"),
            ("stats",    "📊", "Stats"),
            ("monitor",  "📡", "Monitor"),
            ("settings", "🖥", "Settings"),
            ("help",     "❔", "Help"),
        ]
        self.nav_rail = NavRail(nav_items, body)
        self.nav_rail.currentChanged.connect(self._on_nav_changed)
        body_layout.addWidget(self.nav_rail)

        self.stack = QStackedWidget(body)
        body_layout.addWidget(self.stack, 1)

        # -- Pages: instantiate the cards inside their host widgets. ------
        # Click + Record use bespoke pages; the small-card pages
        # (Hover/Behavior/Hotkeys/Stats) use TwoColPage with a context-
        # aware InfoPanel on the right so the wide canvas isn't empty.
        # The card builders return (page, card) so App can keep a direct
        # reference to the card for engine_bridge / commands.
        self.click_page = ClickPage(self)
        self.record_mode_tab = RecordModeTab(self)

        # commands.py reads app.commands during palette population;
        # build_hotkeys_page() needs the registry to render the
        # shortcut reference, so commands are registered before pages.
        self.commands = register_commands(self)

        ai_page, self.ai_card = build_ai_page(self)
        hover_page, self.hover_zones_card = build_hover_page(self)
        behavior_page, self.behavior_card = build_behavior_page(self)
        hotkeys_page, self.hotkeys_card = build_hotkeys_page(self)
        timers_page, self.key_timers_card = build_timers_page(self)
        stats_page, self.stats_card = build_stats_page(self)
        # MonitorServer must exist before the page — MonitorCard reads
        # self.app.monitor_server.lan_url() during init for the URL display.
        self.monitor_server = MonitorServer(self)
        monitor_page, self.monitor_card = build_monitor_page(self)
        settings_page, self.settings_card = build_settings_page(self)
        help_page = HelpPage(self)

        self._page_index: dict[str, int] = {}
        for item_id, page in [
            ("click",    self.click_page),
            ("record",   SimplePage(self.record_mode_tab, max_card_w=None)),
            ("ai",       ai_page),
            ("hover",    hover_page),
            ("behavior", behavior_page),
            ("hotkeys",  hotkeys_page),
            ("timers",   timers_page),
            ("stats",    stats_page),
            ("monitor",  monitor_page),
            ("settings", settings_page),
            ("help",     help_page),
        ]:
            self._page_index[item_id] = self.stack.addWidget(page)

        # -- Tickers ------------------------------------------------------
        # Topbar pill ticks every frame (state + countdown). Stats card too,
        # since its values move continuously while the engine runs.
        self._ticking_cards = [self.topbar, self.stats_card, self.ai_card]

        # -- Toast host (floats over everything) --------------------------
        self.toasts = ToastHost(central)
        self.toasts.setGeometry(0, 0, 1, 1)  # repositioned on resize

        # If load_config() backed up a corrupt config.json, tell the user
        # — silent fallback to defaults is a footgun for anyone who's
        # configured a long sequence and doesn't notice it's gone.
        backup_path = self.cfg.pop("_corrupt_backup", None)
        if backup_path:
            from pathlib import Path as _Path
            QTimer.singleShot(150, lambda p=backup_path: self.toasts.post(
                f"⚠ config.json was corrupt — backed up to "
                f"{_Path(p).name}. Defaults loaded.",
                kind="warn",
            ))

        # -- Restore last-selected nav section ---------------------------
        last = str(self.cfg.get("nav_section", "click"))
        if last not in self._page_index:
            last = "click"
        self.nav_rail.set_current(last)

        # -- Command palette shortcuts ------------------------------------
        # ``self.commands`` was registered above before pages so the
        # Hotkeys page could render the shortcut reference. Bind globals.
        self._palette = None  # lazy

        QShortcut(QKeySequence("Ctrl+K"), self).activated.connect(self._open_palette)
        QShortcut(QKeySequence("Ctrl+Shift+P"), self).activated.connect(self._open_palette)
        for cmd in self.commands:
            if cmd.qt_shortcut:
                sc = QShortcut(QKeySequence(cmd.qt_shortcut), self)
                sc.activated.connect(lambda c=cmd: self._run_command(c))

        # -- Auto-start Monitor server if user left it enabled --------------
        # Deferred via singleShot so the window is fully shown before the
        # server thread spawns; Windows Firewall prompts (if any) appear on
        # top of a visible app rather than a black screen.
        if self.cfg.get("monitor_enabled", False):
            QTimer.singleShot(200, self._auto_start_monitor)

    def _auto_start_monitor(self) -> None:
        ok = self.monitor_server.start()
        if not ok:
            self.toasts.post(
                f"Monitor server didn't start: {self.monitor_server.last_error}",
                kind="warn",
            )
        # Refresh the card pill regardless so the UI matches reality.
        try:
            self.monitor_card.refresh()
        except Exception:
            pass

    def _open_palette(self) -> None:
        from .command_palette import CommandPalette
        # Reuse a single instance so its position is sticky across opens.
        if self._palette is None:
            self._palette = CommandPalette(self)
        self._palette.search.clear()
        self._palette._refresh()
        self._palette.show()
        self._palette.raise_()
        self._palette.activateWindow()

    def _run_command(self, cmd) -> None:
        if not cmd.available(self):
            return
        try:
            cmd.action(self)
        except Exception:
            self.log.exception(f"command failed: {cmd.id}")

    # -- Nav change ------------------------------------------------------

    def _on_nav_changed(self, nav_id: str) -> None:
        idx = self._page_index.get(nav_id)
        if idx is not None:
            # Direct switch — earlier prototypes used a QGraphicsOpacityEffect
            # cross-fade but it's lifecycle-fragile during app shutdown
            # (animation outlives its target widget). Plain swap is fine.
            self.stack.setCurrentIndex(idx)
        # Click / Record nav entries also flip the engine-side active_mode
        # so a Start press from any page runs the right thing. Other nav
        # entries (Hover/Behavior/Hotkeys/Stats) leave active_mode alone.
        if nav_id == "click":
            self._set_active_mode("clicker")
        elif nav_id == "record":
            self._set_active_mode("recorder")
        elif nav_id == "ai":
            self._set_active_mode("ai")
        # Persist the selection.
        self.cfg["nav_section"] = nav_id
        save_config(self.cfg)

    def _set_active_mode(self, mode: str) -> None:
        if mode == self._active_mode:
            return
        self._active_mode = mode
        self.cfg["active_mode"] = mode
        save_config(self.cfg)
        engine_bridge.push_config_to_clicker(self)
        # Swap which set of zone overlays paints on screen — click-mode
        # main overlay vs. per-step overlays — so the user sees only the
        # active tab's drawn lines.
        self.overlay_manager.apply_visibility()

    # -- Periodic tick ---------------------------------------------------

    def _tick(self) -> None:
        for card in getattr(self, "_ticking_cards", []):
            try:
                card.tick()
            except Exception:
                pass
        # Tracker preview overlay sync.
        try:
            self.tracker_preview.tick()
        except Exception:
            pass

    # -- Slots invoked from non-Qt threads -------------------------------

    @Slot()
    def _on_start(self) -> None:
        if self._active_mode == "ai":
            self._on_start_ai()
            return
        engine_bridge.push_config_to_clicker(self)
        failures = self._preflight_failures()
        if failures:
            for msg in failures:
                self.toasts.post(msg, kind="error")
            return
        self.clicker.start()

    @Slot()
    def _on_stop(self) -> None:
        # Stop both engines unconditionally — the inactive one's stop()
        # is a no-op, and Esc / F7 should always halt whatever's running.
        try:
            self.clicker.stop()
        except Exception:
            pass
        runner = getattr(self, "bot_runner", None)
        if runner is not None:
            try:
                runner.stop()
            except Exception:
                pass

    def _on_capture_hotkey(self) -> None:
        """Pynput-listener-thread entry point for the capture hotkey.

        Marshals to the Qt main thread via the ``_captureHotkeyFired``
        queued-connection signal — pynput's listener has no Qt event
        loop, so ``QTimer.singleShot`` from here is silently dropped.
        """
        try:
            self.log.info("app._on_capture_hotkey fired (pynput thread)")
        except Exception:
            pass
        try:
            from PySide6.QtGui import QCursor
            cursor_pt = QCursor.pos()
            cx, cy = int(cursor_pt.x()), int(cursor_pt.y())
        except Exception:
            cx, cy = 0, 0
        self._captureHotkeyFired.emit(cx, cy)

    def _run_capture_hotkey(self, cx: int, cy: int) -> None:
        """Main-thread implementation of the capture hotkey: freezes a
        frame and routes to the captures card's frozen-frame flow.

        Requires an active bundle (the saved snapshot lands in that
        bundle's ``assets/snapshots/``). Without a bundle there's
        nowhere to save and we surface a toast instead of silently
        eating the keypress.
        """
        cursor_xy = (int(cx), int(cy))
        try:
            self.log.info("app._run_capture_hotkey starting cursor=%r", cursor_xy)
        except Exception:
            pass
        bundle = None
        ai_card = None
        try:
            ai_card = getattr(self, "ai_card", None)
            if ai_card is not None and hasattr(ai_card, "active_bundle"):
                bundle = ai_card.active_bundle()
        except Exception:
            bundle = None
        try:
            self.log.info(
                "app._run_capture_hotkey ai_card=%s bundle=%s",
                ai_card is not None, bundle is not None,
            )
        except Exception:
            pass
        if bundle is None:
            try:
                self.toasts.post(
                    "⚠ Capture hotkey needs an active bundle — pick one "
                    "on the AI tab.",
                    kind="warn",
                )
            except Exception:
                pass
            return
        captures = getattr(ai_card, "captures", None)
        if captures is None or not hasattr(captures, "capture_via_frozen_frame"):
            self.toasts.post(
                "⚠ Capture hotkey: captures card not ready.", kind="error",
            )
            return
        try:
            captures.capture_via_frozen_frame(cursor_xy)
        except Exception as e:
            try:
                self.log.exception("capture_via_frozen_frame failed")
            except Exception:
                pass
            self.toasts.post(
                f"⚠ Capture failed: {type(e).__name__}: {e}", kind="error",
            )

    def _on_start_ai(self) -> None:
        runner = getattr(self, "bot_runner", None)
        actuator = getattr(self, "ai_actuator", None)
        if runner is None or actuator is None:
            self.toasts.post(
                "⚠ AI mode unavailable — ai/ subpackage didn't load.",
                kind="error",
            )
            return
        if runner.is_running():
            return
        # Three start paths in priority order:
        #   1. Active bundle (bots/<slug>/) — preferred for new bots
        #   2. Legacy in-cfg "Custom Bot (in-GUI)" — back-compat
        #   3. Library bot (ai/tasks/library/) — Python-authored bots
        active_bundle = (
            self.ai_card.active_bundle()
            if hasattr(self.ai_card, "active_bundle") else None
        )
        bundle_world_calibration = None
        if active_bundle is not None:
            bot = self._compile_bundle_bot(active_bundle)
            if bot is None:
                return
            bundle_world_calibration = self._world_calibration_from_bundle(active_bundle)
        elif bool(self.cfg.get("ai_use_user_bot", False)):
            from ai.bot import compile_user_bot
            item_library = self._build_ai_item_library()
            bot, errors = compile_user_bot(
                self._ai_user_steps,
                name=str(self.cfg.get("ai_user_bot_name") or "Custom Bot"),
                tick_rate_hz=float(self.cfg.get("ai_tick_rate_hz", 5.0)),
                dry_run=bool(self.cfg.get("ai_dry_run", False)),
                auto_camera=bool(self.cfg.get("ai_auto_camera", False)),
                auto_stop_dry_ticks=int(self.cfg.get("ai_auto_stop_dry_ticks", 60)),
                watchdog_no_click_s=float(self.cfg.get("ai_watchdog_no_click_s", 600.0)),
                item_library=item_library,
            )
            for err in errors:
                self.toasts.post(f"⚠ {err}", kind="warn")
            if not bot.rules:
                # No registerable rules — fail loudly rather than spinning.
                return
        else:
            bot = self.ai_card.load_current_bot()
            if bot is None:
                self.toasts.post(
                    "⚠ Select an AI bot first.", kind="warn",
                )
                return
        # Ensure the keyboard backend Clicker uses is also visible to
        # key_timer.fire (the actuator's press_key path). Mirrors what
        # Clicker.start() does when the user runs Click/Record mode.
        try:
            from modules import key_input_backend, key_timer
            kb = key_input_backend.get_backend(
                str(self.cfg.get("key_input_method", "auto") or "auto"),
                serial_port=str(self.cfg.get("serial_hid_port", "") or ""),
            )
            key_timer.set_backend(kb)
            if (str(self.cfg.get("key_input_method", "")).lower() == "serial_hid"
                    and not getattr(kb, "available", True)):
                self.toasts.post(
                    "⚠ Serial HID picked but board unavailable: "
                    + getattr(kb, "_init_error", "unknown error"),
                    kind="warn",
                )
        except Exception:
            pass

        # Hand the bot the user's awareness-layer calibration. None
        # entries are tolerated by WorldState — bots that read
        # uncalibrated surfaces just see None and should bail.
        # Bundles bring their own calibration; everything else falls
        # back to the global cfg keys.
        world_calibration = bundle_world_calibration or {
            "inventory_rect": self.cfg.get("ai_inventory_rect"),
            "orbs_rect": self.cfg.get("ai_orbs_rect"),
            "minimap_rect": self.cfg.get("ai_minimap_rect"),
            "orbs_max_fill": dict(self.cfg.get("ai_orbs_max_fill") or {}),
        }

        # Per-bot realism override (C.1). Bundles can pin a fixed
        # realism level so a bot tuned at, say, 0.7 doesn't drift when
        # the user later moves the slider for a different bot. We snap
        # the slider to the bundle's value for the run and restore the
        # prior value when the runner finishes — see
        # ``_restore_realism_after_bot`` for the restore hook.
        self._pre_bot_realism = None
        if active_bundle is not None:
            override = (active_bundle.settings or {}).get("realism")
            if override is not None:
                try:
                    r = max(0.0, min(1.0, float(override)))
                except (TypeError, ValueError):
                    r = None
                if r is not None and abs(r - float(self.cfg.get("realism", 0.5))) > 1e-6:
                    self._pre_bot_realism = float(self.cfg.get("realism", 0.5))
                    try:
                        self.behavior_card.apply_realism_preset(r)
                    except Exception:
                        # Fallback: at least put the value into cfg so
                        # it's visible in the snapshot, even if the UI
                        # walk failed.
                        self.cfg["realism"] = r
                    if actuator is not None:
                        try:
                            actuator.rebuild_fatigue()
                        except Exception:
                            pass

        runner.play(
            bot,
            tick_rate_hz=float(self.cfg.get("ai_tick_rate_hz", 5.0)),
            default_monitor=int(self.cfg.get("ai_monitor", 1)),
            dry_run=bool(self.cfg.get("ai_dry_run", False)),
            actuator=actuator,
            world_calibration=world_calibration,
            bundle=active_bundle,
        )

    def _restore_realism_after_bot(self) -> None:
        """Restore the global realism slider after a per-bot override.

        Hooked into ``bot_runner.finished`` from the AI card — called
        once per run, no-ops when no override was active.
        """
        prior = getattr(self, "_pre_bot_realism", None)
        if prior is None:
            return
        self._pre_bot_realism = None
        try:
            self.behavior_card.apply_realism_preset(float(prior))
        except Exception:
            self.cfg["realism"] = float(prior)
        actuator = getattr(self, "ai_actuator", None)
        if actuator is not None:
            try:
                actuator.rebuild_fatigue()
            except Exception:
                pass

    @Slot()
    def _emergency_stop(self) -> None:
        self.clicker.stop()

    @Slot()
    def _toggle_ai_pause(self) -> None:
        """F8 toggles AI bot pause/resume. No-op when no bot is running.

        Click/Record mode are unaffected — pause is AI-mode only.
        """
        runner = getattr(self, "bot_runner", None)
        if runner is None or not runner.is_running():
            return
        new_state = runner.toggle_pause()
        if new_state is None:
            return
        if new_state:
            self.toasts.post("⏸ Bot paused — F8 to resume.", kind="info")
        else:
            self.toasts.post("▶ Bot resumed.", kind="info")

    @Slot()
    def _sync_overlay_for_state(self) -> None:
        engine_bridge.sync_overlay_for_state(self, self._state_str)

    @Slot(str, str)
    def _on_track_error(self, step_id: str, reason: str) -> None:
        """Engine-thread track-template-load failure surfaces here."""
        idx = None
        for i, s in enumerate(self._steps):
            if getattr(s, "step_id", None) == step_id:
                idx = i + 1
                break
        if idx is None:
            label = "a track step"
        else:
            label = f"track step {idx}"
        if reason == "no_template_path":
            msg = f"⚠ {label.capitalize()} has no captured template — capture one to fix."
        else:
            msg = f"⚠ {label.capitalize()} template missing or unreadable — recapture to fix."
        self.toasts.post(msg, kind="error")

    @Slot(str)
    def _on_session_complete(self, reason: str) -> None:
        """Engine reached a stop-after limit. Stop the engine cleanly and
        surface a success toast so the user sees the session ended on
        their terms, not a silent halt."""
        self.clicker.stop()
        self.toasts.post(f"✓ {reason}", kind="success")
        self._play_stop_sound()

    @Slot(str, str)
    def _on_engine_halt(self, msg: str, level: str) -> None:
        """Engine surfaced a stop / stall reason that would otherwise be
        silent (no usable steps, watchdog corner-trigger, stuck Track or
        Color step, uncaught exception, etc.)."""
        kind = level if level in ("error", "warn", "info", "success") else "info"
        self.toasts.post(msg, kind=kind)
        self._play_stop_sound()

    def _play_stop_sound(self) -> None:
        """Win32 system beep so a fullscreen-game user notices the engine
        halted without having to alt-tab back to PhantomClick. Gated by
        the ``sound_on_stop`` toggle (Hotkeys page → Alerts). Best-effort:
        any audio failure is swallowed since the toast is the primary
        signal."""
        if not bool(self.cfg.get("sound_on_stop", True)):
            return
        try:
            import winsound
            winsound.MessageBeep(winsound.MB_ICONHAND)
        except Exception:
            pass

    # -- Engine click fired (background thread) --------------------------

    def _on_engine_click_fired(self, target_x, target_y, actual_x, actual_y, kind):
        # Marshal to Qt main thread via queued signal. ``QTimer.singleShot``
        # from the engine thread is silently dropped in Qt6 — see the class
        # docstring on ``_engineClickFired``.
        self._engineClickFired.emit(
            int(target_x), int(target_y),
            int(actual_x), int(actual_y), str(kind),
        )

    @Slot(int, int, int, int, str)
    def _flash_click_marker_main(self, tx: int, ty: int, ax: int, ay: int, kind: str) -> None:
        self.overlay_manager.flash_click_marker(tx, ty, ax, ay, kind)

    # -- Mode readiness (called by start guard + status card) ------------

    def _explicit_target_screen_index(self) -> Optional[int]:
        """Return the explicitly-selected screen index, or None for auto.

        Shared by :meth:`target_screen` (drawers) and
        :meth:`target_screen_bounds` (engine ambient features) so that
        an explicit pick honors the same screen everywhere — only the
        ``"auto"`` fallback differs between the two.
        """
        target = str(self.cfg.get("target_monitor", "auto"))
        if target == "auto":
            return None
        try:
            idx = int(target)
        except ValueError:
            return None
        screens = QApplication.instance().screens()
        if 0 <= idx < len(screens):
            return idx
        return None

    def target_screen(self):
        """Return the ``QScreen`` to use for fullscreen drawers (zone /
        future per-monitor overlays).

        * Explicit selection → that monitor.
        * ``"auto"`` → cursor's current screen (so drawing without a
          configured monitor follows where the user is looking).
        * Falls back to primary on any failure.
        """
        qa = QApplication.instance()
        screens = qa.screens()
        if not screens:
            return None
        primary = qa.primaryScreen() or screens[0]
        idx = self._explicit_target_screen_index()
        if idx is not None:
            return screens[idx]
        # Auto: cursor's screen. Different from target_screen_bounds()'s
        # auto (which uses the zone's monitor) because drawing a NEW
        # zone should follow the cursor, not a stale zone elsewhere.
        try:
            from PySide6.QtGui import QCursor
            s = QApplication.screenAt(QCursor.pos())
            if s is not None:
                return s
        except Exception:
            pass
        return primary

    def target_screen_bounds(self) -> tuple[int, int, int, int]:
        """Return ``(x, y, w, h)`` of the monitor the engine should treat
        as "the screen" for ambient features (post-click drift clamp,
        idle wander, watchdog corners, tracker locate).

        * Explicit selection → that monitor's bounds.
        * ``"auto"`` → bounds of the monitor containing the active zone,
          else the primary monitor. Different from :meth:`target_screen`'s
          auto (which uses the cursor) because ambient drift should
          stay scoped to where the clicks land, not where the user
          glances.

        Returned coordinates are in DIPs (matches the rest of the engine).
        """
        qa = QApplication.instance()
        screens = qa.screens()
        if not screens:
            return (0, 0, self.monitor_w, self.monitor_h)
        primary = qa.primaryScreen() or screens[0]

        idx = self._explicit_target_screen_index()
        if idx is not None:
            g = screens[idx].geometry()
            return (g.left(), g.top(), g.width(), g.height())

        # Auto: zone's monitor.
        if self._zone is not None:
            cx, cy = self._zone.centroid()
            for s in screens:
                g = s.geometry()
                if g.left() <= cx < g.right() and g.top() <= cy < g.bottom():
                    return (g.left(), g.top(), g.width(), g.height())
        g = primary.geometry()
        return (g.left(), g.top(), g.width(), g.height())

    def _is_mode_ready(self) -> bool:
        if self._active_mode == "recorder":
            return any(
                (s.kind == KIND_CLICK and s.zone is not None)
                or (s.kind == KIND_TRACK and s.template_path)
                or (s.kind == KIND_COLOR and s.color_target_rgb is not None)
                for s in self._steps
            )
        return self._zone is not None

    def _preflight_failures(self) -> list[str]:
        """Return a list of user-facing strings describing why the engine
        can't start right now. Empty list = green-light. Toasts come from
        ``_on_start`` which posts one per item. Designed so future checks
        can be added without touching the start path itself.
        """
        import os
        failures: list[str] = []
        # Hotkey conflict — covers the case where an external edit slipped
        # past the rebind validator (e.g. config.json hand-edit).
        seen: dict[str, str] = {}
        for k, v in self.cfg.items():
            if not str(k).startswith("hotkey_"):
                continue
            name = str(v).lower()
            if not name:
                continue
            if name in seen and seen[name] != k:
                failures.append(
                    f"⚠ Hotkey '{name}' is bound to two actions "
                    f"({seen[name][len('hotkey_'):]} and "
                    f"{str(k)[len('hotkey_'):]})."
                )
            else:
                seen[name] = str(k)

        if self._active_mode == "recorder":
            if not self._steps:
                failures.append("⚠ Record mode has no steps. Add a Click / Track / Color step.")
            else:
                runnable = False
                for i, s in enumerate(self._steps):
                    user_label = (getattr(s, "label", "") or "").strip()
                    label = (f"step {i + 1} '{user_label}'" if user_label
                             else f"step {i + 1}")
                    if s.kind == KIND_CLICK:
                        if s.zone is None:
                            failures.append(f"⚠ Click {label} has no zone — draw one or remove the step.")
                            continue
                        runnable = True
                    elif s.kind == KIND_TRACK:
                        if not s.template_path:
                            failures.append(f"⚠ Track {label} has no captured template.")
                            continue
                        # Resolve relative to install root (mirrors _read_template_png).
                        path = s.template_path
                        if not os.path.isabs(path):
                            path = os.path.join(_config_dir(), path)
                        if not os.path.exists(path):
                            failures.append(
                                f"⚠ Track {label} template missing on disk — recapture to fix."
                            )
                            continue
                        runnable = True
                    elif s.kind == KIND_COLOR:
                        if s.color_target_rgb is None:
                            failures.append(f"⚠ Color {label} has no target color picked.")
                            continue
                        runnable = True
                    elif s.kind == KIND_PAUSE:
                        # Pause-only sequences are valid (loop/idle), but we
                        # need at least one runnable step somewhere.
                        pass
                    else:
                        # Loop / unknown — handled in engine; not a pre-flight failure.
                        pass
                if not runnable:
                    failures.append(
                        "⚠ Record mode has no runnable Click / Track / Color step."
                    )
        else:
            if self._zone is None:
                failures.append("⚠ Click mode has no zone. Press 'Draw on screen' first.")
            else:
                # Sanity: zone AABB intersects the screen at all.
                x1, y1, x2, y2 = self._zone.aabb()
                if x2 < 0 or y2 < 0 or x1 > self.monitor_w or y1 > self.monitor_h:
                    failures.append(
                        "⚠ Click zone is entirely off-screen "
                        "(maybe resolution changed). Redraw it."
                    )
        return failures

    # -- Color picker entry point -----------------------------------------

    def open_color_picker(self, on_done) -> None:
        """Spawn a fullscreen ColorPicker; ``on_done((rgb, x, y) or None)``."""
        from .overlays.color_picker import ColorPicker
        self.overlay_manager.hide_for_drawing()
        self.showMinimized()
        # Bind the picker to a single screen — same mixed-DPI fix as
        # the ZoneDrawer. Without this, Qt6 paints a scrim across the
        # virtual desktop but only one monitor accepts events, locking
        # the user out of dismissing the overlay on the other monitor.
        picker = ColorPicker(screen=self.target_screen())

        def _finished(result):
            # Restore the main window BEFORE invoking the callback so
            # any QInputDialog spawned by ``on_done`` (e.g. asset-name
            # prompt) follows the active window onto the visible
            # screen instead of landing off-screen.
            picker.deleteLater()
            self.showNormal()
            self.raise_()
            self.activateWindow()
            on_done(result)
        picker.finished.connect(_finished)
        QTimer.singleShot(180, picker.show)
        QTimer.singleShot(220, picker.activateWindow)

    # -- Zone drawer entry point ------------------------------------------

    def open_zone_drawer(self, shape: str, on_done) -> None:
        """Spawn a fullscreen ZoneDrawer for ``shape``; ``on_done(zone_or_none)``
        fires when the user commits or cancels.

        Hides every overlay first so the drawer has a clean canvas. Restores
        the main window's visibility after capture so the user lands back
        in the app even if they cancelled.
        """
        from .overlays.zone_drawer import ZoneDrawer
        self.overlay_manager.hide_for_drawing()
        self.showMinimized()

        # Honor the Settings → Target Monitor selection so picking
        # "ASUS PG32UCDM" actually opens the drawer on the ASUS, not
        # on whatever screen the GUI window is currently on.
        drawer = ZoneDrawer(shape, screen=self.target_screen())

        def _finished(zone):
            # Restore the main window BEFORE invoking the callback —
            # ``on_done`` typically opens a QInputDialog (asset name
            # prompt for snapshots / recordings), and Qt picks the
            # dialog's screen from the active window. Without this the
            # dialog gets parented to a still-minimized window and
            # lands in a random corner of whichever monitor Windows
            # chooses, often off-screen on multi-monitor setups.
            drawer.deleteLater()
            self.showNormal()
            self.raise_()
            self.activateWindow()
            on_done(zone)
        drawer.finished.connect(_finished)
        # Tiny delay so the iconify animation completes before paint.
        QTimer.singleShot(180, drawer.show)
        QTimer.singleShot(220, drawer.activateWindow)

    # -- Save / push helpers ---------------------------------------------

    def _save_steps(self) -> None:
        self.cfg["recorder_steps"] = serialize_steps(self._steps)
        save_config(self.cfg)
        engine_bridge.push_config_to_clicker(self)

    def _save_ai_user_steps(self) -> None:
        """Persist the in-GUI AI bot's step list to its active source.

        When an authoring bundle is active, edits land in the bundle's
        ``procedures.json`` under the entry procedure. Otherwise they
        land in the legacy ``ai_user_bot_steps`` cfg key.

        The bot runner doesn't read this on the fly — steps are baked
        into a compiled :class:`Bot` at Start time. So edits while the
        bot is running don't affect the live snapshot.
        """
        from ai.bot.authoring import serialize_steps as _serialize_ai_steps
        b = getattr(self, "_ai_authoring_bundle", None)
        if b is not None:
            entry = str(b.procedures.get("entry") or "main")
            procs = b.procedures.setdefault("procedures", {})
            serialized = _serialize_ai_steps(self._ai_user_steps)
            existing = procs.get(entry)
            if isinstance(existing, dict):
                existing["steps"] = serialized
            else:
                procs[entry] = serialized
            b.procedures["entry"] = entry
            b.save_field("procedures")
            return
        self.cfg["ai_user_bot_steps"] = _serialize_ai_steps(self._ai_user_steps)
        save_config(self.cfg)

    def set_ai_authoring_bundle(self, bundle) -> None:
        """Switch the in-GUI editor's data source to a bundle (or back
        to legacy cfg when ``bundle`` is None).

        Called by ``AIPageBody._activate_bundle`` whenever the user
        picks a bundle in the dropdown. The editor then renders the
        bundle's procedure steps; saves go to ``procedures.json``.
        """
        from ai.bot.authoring import deserialize_steps as _deserialize_ai_steps
        self._ai_authoring_bundle = bundle
        if bundle is None:
            self._ai_user_steps = _deserialize_ai_steps(
                self.cfg.get("ai_user_bot_steps", [])
            )
            return
        entry = str(bundle.procedures.get("entry") or "main")
        procs = (bundle.procedures.get("procedures") or {})
        raw = procs.get(entry)
        if isinstance(raw, dict):
            raw = raw.get("steps") or []
        elif raw is None:
            raw = []
        self._ai_user_steps = _deserialize_ai_steps(raw)

    def _compile_bundle_bot(self, bundle):
        """Compile a per-bot bundle into a runnable Bot.

        Until Phase B (procedures + interrupts) lands, the bundle's
        ``procedures.json`` is treated as a single-procedure flat list:
        ``procedures["procedures"]["main"]`` runs as a priority list,
        identical semantics to the legacy custom bot.
        """
        from ai.bot import compile_user_bot
        from ai.bot.authoring import deserialize_steps as _deserialize_ai_steps

        proc = bundle.procedures or {}
        entry_name = str(proc.get("entry") or "main")
        procedures = proc.get("procedures") or {}
        raw_steps_obj = procedures.get(entry_name) or []
        raw_steps = (
            raw_steps_obj.get("steps", [])
            if isinstance(raw_steps_obj, dict) else (raw_steps_obj or [])
        )
        steps = _deserialize_ai_steps(raw_steps)
        if not steps:
            self.toasts.post(
                f"⚠ Bundle {bundle.name!r} has no steps in procedure "
                f"{entry_name!r}. Add steps in the editor first.",
                kind="warn",
            )
            return None

        # Per-bot settings override the global cfg defaults.
        settings = bundle.settings or {}
        item_library = self._build_bundle_item_library(bundle)
        # Use the procedural compile path so bundle-resolving step
        # kinds (find_capture_click) can find their assets. The
        # legacy compile_user_bot path drops bundle context.
        from ai.bot import compile_program
        from ai.bot.procedures import program_from_bundle_dict
        program = program_from_bundle_dict(bundle.procedures)

        # Pre-run sanity check (B.3): surface things compile won't catch
        # (missing snapshots, uncalibrated ROIs, dangling handlers, …).
        # Non-blocking — incremental authoring may legitimately have
        # unfinished steps, so we toast the count and dump details to
        # the log rather than refusing to start.
        try:
            from ai.bot.lint import lint_bundle
            issues = lint_bundle(bundle, program)
        except Exception:
            issues = []
        if issues:
            self.toasts.post(
                f"⚠ {len(issues)} lint issue{'s' if len(issues) != 1 else ''} "
                f"— check log for details. Starting anyway.",
                kind="warn",
            )
            try:
                from utils.logger import get_logger
                _lint_log = get_logger()
                for msg in issues:
                    _lint_log.warning(f"[lint] {msg}")
            except Exception:
                for msg in issues:
                    print(f"[lint] {msg}")

        bot, errors = compile_program(
            program,
            name=bundle.name,
            tick_rate_hz=float(settings.get("tick_rate_hz", self.cfg.get("ai_tick_rate_hz", 5.0))),
            dry_run=bool(settings.get("dry_run", self.cfg.get("ai_dry_run", False))),
            auto_camera=bool(settings.get("auto_camera", self.cfg.get("ai_auto_camera", False))),
            auto_stop_dry_ticks=int(settings.get("auto_stop_dry_ticks", self.cfg.get("ai_auto_stop_dry_ticks", 60))),
            watchdog_no_click_s=float(settings.get("watchdog_no_click_s", self.cfg.get("ai_watchdog_no_click_s", 600.0))),
            item_library=item_library,
            bundle=bundle,
        )
        for err in errors:
            self.toasts.post(f"⚠ {err}", kind="warn")
        if not bot.rules:
            return None
        return bot

    def _world_calibration_from_bundle(self, bundle) -> dict:
        """Convert the bundle's calibration.json into the world_calibration
        dict shape BotRunner expects."""
        cal = bundle.calibration or {}
        return {
            "inventory_rect": cal.get("inventory_rect"),
            "orbs_rect": cal.get("orbs_rect") or cal.get("bars_rect"),
            "minimap_rect": cal.get("minimap_rect"),
            "orbs_max_fill": dict(cal.get("orbs_max_fill") or {}),
        }

    def _build_bundle_item_library(self, bundle):
        """ItemLibrary for a bundle, using player-captured icons first
        and falling back to wiki-cached icons by name."""
        from ai.algorithms.items import ItemLibrary
        lib = ItemLibrary()
        # 1. Bundle-local item captures (player-sourced).
        for icon_path in bundle.list_items():
            name = icon_path.stem.replace("_", " ").title()
            lib.add_from_path(name, icon_path)
        return lib if len(lib) else None

    def _build_ai_item_library(self):
        """Construct an :class:`ai.algorithms.items.ItemLibrary` from the
        user's added item names + cached wiki icons. Returns None when
        the list is empty so we don't pay the load cost for bots that
        don't use item identification.
        """
        names = list(self._ai_item_names or [])
        if not names:
            return None
        from pathlib import Path
        from ai.algorithms.items import ItemLibrary
        from ai.wiki import default_client
        from ai.wiki.client import _slugify
        cache_root = Path("debug/wiki_cache")
        items_dir = cache_root / "items"
        client = default_client(cache_root)
        lib = ItemLibrary()
        missing: list[str] = []
        for nm in names:
            slug = _slugify(nm)
            path = items_dir / f"{slug}.png"
            if not path.exists():
                # Lazy refresh — re-fetch on Start if the cache was wiped.
                fetched = client.fetch_item_image(nm)
                if fetched is not None:
                    path = fetched
            if path.exists():
                lib.add_from_path(nm, path)
            else:
                missing.append(nm)
        if missing:
            self.toasts.post(
                f"⚠ Couldn't load item icons for: {', '.join(missing)}",
                kind="warn",
            )
        return lib if len(lib) else None

    # -- Step trash (undo for delete) -----------------------------------

    _STEP_TRASH_CAP = 10

    def _trash_dir(self) -> Path:
        """Sub-dir under templates/ where deleted-step PNGs are parked
        until the user either restores them or the app exits."""
        return _config_dir() / "templates" / ".trash"

    def _push_step_to_trash(self, step, original_index: int,
                              template_paths: list[Path]) -> None:
        """Move template files into the trash dir and push a LIFO entry.

        ``template_paths`` are absolute paths to PNGs that should be
        moved aside (KIND_TRACK primary + extra views). For non-track
        steps pass an empty list — there's nothing on disk to move.

        Past the capacity, the oldest entry's files are actually unlinked
        (the trash is in-memory; an entry that falls off the cap can no
        longer be restored, so it's safe to free the disk space).
        """
        trash_root = self._trash_dir()
        moved: list[Path] = []
        if template_paths:
            slot = trash_root / step.step_id
            try:
                slot.mkdir(parents=True, exist_ok=True)
            except Exception:
                slot = None
            if slot is not None:
                for src in template_paths:
                    try:
                        if not src.exists():
                            continue
                        dst = slot / src.name
                        # Atomic rename on the same volume; templates dir
                        # and its .trash subdir are always co-located.
                        src.replace(dst)
                        moved.append(dst)
                    except Exception:
                        # Best-effort; if a move fails the file stays put
                        # and restore won't bring it back, but the step
                        # row is still gone. Acceptable degradation.
                        pass
        self._step_trash.append((step, int(original_index), moved))
        # Cap: drop oldest, unlink its parked files.
        while len(self._step_trash) > self._STEP_TRASH_CAP:
            old_step, _idx, old_moved = self._step_trash.pop(0)
            for p in old_moved:
                try:
                    p.unlink(missing_ok=True)
                except Exception:
                    pass
            # Also try to remove the now-empty per-step trash dir.
            try:
                (trash_root / old_step.step_id).rmdir()
            except Exception:
                pass
        self._notify_trash_changed()

    def _restore_last_deleted_step(self) -> bool:
        """Pop the most recent trash entry and re-insert. Returns True if
        anything was restored, False when the trash is empty."""
        if not self._step_trash:
            return False
        step, original_index, moved = self._step_trash.pop()
        # Move template files back to their original templates/ locations.
        for trashed in moved:
            try:
                # Files were stored as templates/.trash/<step_id>/<basename>;
                # restore to templates/<basename>.
                dst = (_config_dir() / "templates" / trashed.name)
                dst.parent.mkdir(parents=True, exist_ok=True)
                trashed.replace(dst)
            except Exception:
                pass
        # Try to clean up the now-empty per-step trash dir.
        try:
            (self._trash_dir() / step.step_id).rmdir()
        except Exception:
            pass
        # Clamp the restore index to current list length so deletions
        # past the original position can't cause an IndexError.
        idx = max(0, min(int(original_index), len(self._steps)))
        self._steps.insert(idx, step)
        self._save_steps()
        self.overlay_manager.refresh_step_overlays()
        # Refresh the Record tab so the row reappears.
        try:
            self.record_mode_tab.render_all()
        except Exception:
            pass
        self._notify_trash_changed()
        return True

    def _notify_trash_changed(self) -> None:
        """Fire any subscribers (e.g. the footer "Restore last deleted"
        affordance) so they can re-render."""
        for cb in list(getattr(self, "_step_trash_listeners", []) or []):
            try:
                cb()
            except Exception:
                pass

    def _purge_step_trash_dir(self) -> None:
        """Delete the entire templates/.trash/ tree. Called on app close
        so we don't accumulate orphaned templates from past sessions."""
        d = self._trash_dir()
        if d.exists():
            try:
                shutil.rmtree(d, ignore_errors=True)
            except Exception:
                pass

    def _push_config_to_clicker(self) -> None:
        engine_bridge.push_config_to_clicker(self)

    # -- Lifecycle -------------------------------------------------------

    def closeEvent(self, event):  # noqa: N802 (Qt name)
        self.cfg["window_w"] = self.width()
        self.cfg["window_h"] = self.height()
        save_config(self.cfg)
        # Trash is in-memory only — drop the parked PNGs on the way out
        # so they don't accumulate across sessions.
        self._purge_step_trash_dir()
        try:
            self.tracker_preview.stop_loop()
        except Exception:
            pass
        try:
            self.clicker.stop()
        except Exception:
            pass
        # Stop the Monitor HTTP server so the listening port is freed
        # before the process exits.
        try:
            self.monitor_server.stop()
        except Exception:
            pass
        # Release the tracker's persistent mss handle so Windows DC count
        # drops back. Engine's mss handle is closed inside Clicker.stop().
        try:
            self._tracker.close()
        except Exception:
            pass
        try:
            self.hotkeys.stop()
        except Exception:
            pass
        # Tear down overlays so stale frameless windows don't linger.
        for ov in [self.overlay_manager._main]:
            if ov is not None:
                try:
                    ov.deleteLater()
                except Exception:
                    pass
        for ov in self.overlay_manager._hover_overlays + self.overlay_manager._step_overlays:
            try:
                ov.deleteLater()
            except Exception:
                pass
        super().closeEvent(event)


def run() -> None:
    import sys
    app = QApplication.instance() or QApplication(sys.argv)
    # Stylesheet applied lazily inside App.__init__ so each spawned App can
    # customize before show.
    window = App()
    window.show()
    app.exec()


if __name__ == "__main__":
    run()
