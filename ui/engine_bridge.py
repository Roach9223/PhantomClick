"""Bridge between the Qt App and the ``Clicker`` engine (and the AI bot runner).

The engine is framework-agnostic: it runs on its own daemon thread and
fires plain-Python callbacks. The bridge marshals those callbacks back
to the Qt main thread via ``QMetaObject.invokeMethod`` (the Qt-native way
to cross thread boundaries) instead of Tk's ``app.after``.

The bot runner already lives on a QThread and speaks Qt signals, but the
topbar has exactly one state machine (START / STOP / pill / WidgetLocker),
so both engines feed the same ``refresh_action_buttons`` path here. The
UI-visible state is the OR of the two: anything running means "running".

This is the only file in ``ui/`` that knows the layout of every cfg
key; cards stop short of mutating the engine directly so this single
push function stays the source of truth.
"""

from __future__ import annotations

from PySide6.QtCore import QMetaObject, Q_ARG, Qt

from modules.clicker import ClickerState
from modules.key_timer import KeyTimer
from ui.config_io import DEFAULTS
from . import theme as t


def _d(cfg: dict, key: str):
    """cfg lookup that falls back to the canonical default instead of a
    duplicated literal, so a default changed in config_io changes here too."""
    return cfg.get(key, DEFAULTS[key])


def push_config_to_clicker(app) -> None:
    """Mirror App cfg + state into the engine before Start.

    Engine has no two-way binding back; whatever's on the engine at
    ``start()`` time is what runs. The WidgetLocker prevents mid-run edits
    so this isn't a desync risk in practice.
    """
    c = app.clicker
    cfg = app.cfg
    c.zone = app._zone
    c.min_delay = float(_d(cfg, "min_delay"))
    c.max_delay = float(_d(cfg, "max_delay"))
    c.click_type = _d(cfg, "click_type")
    c.click_mode = _d(cfg, "click_mode")
    c.prestart_delay = float(_d(cfg, "prestart_delay"))
    c.idle_wander_enabled = bool(_d(cfg, "idle_wander_enabled"))
    c.idle_wander_frequency = float(_d(cfg, "idle_wander_frequency"))
    c.idle_wander_padding = int(_d(cfg, "idle_wander_padding"))
    c.fatigue_enabled = bool(_d(cfg, "fatigue_enabled"))
    c.fatigue_intensity = float(_d(cfg, "fatigue_intensity"))
    c.break_bursts_enabled = bool(_d(cfg, "break_bursts_enabled"))
    c.break_min_clicks = int(_d(cfg, "break_min_clicks"))
    c.break_max_clicks = int(_d(cfg, "break_max_clicks"))
    c.break_min_duration = float(_d(cfg, "break_min_duration"))
    c.break_max_duration = float(_d(cfg, "break_max_duration"))
    c.overshoot_enabled = bool(_d(cfg, "overshoot_enabled"))
    c.overshoot_probability = float(_d(cfg, "overshoot_probability"))
    c.anti_cluster_enabled = bool(_d(cfg, "anti_cluster_enabled"))
    c.anti_cluster_radius = float(_d(cfg, "anti_cluster_radius"))
    c.idle_wander_whole_screen = bool(_d(cfg, "idle_wander_whole_screen"))
    c.stop_after_clicks_enabled = bool(_d(cfg, "stop_after_clicks_enabled"))
    c.stop_after_clicks = int(_d(cfg, "stop_after_clicks"))
    c.stop_after_minutes_enabled = bool(_d(cfg, "stop_after_minutes_enabled"))
    c.stop_after_minutes = int(_d(cfg, "stop_after_minutes"))
    # Resolve target_monitor to absolute (x, y, w, h) so the engine doesn't
    # need to know about Qt screens. App helper handles auto / index / fall-
    # backs; the engine just clamps drift / wander / corner-failsafe to this.
    try:
        c.target_screen_bounds = app.target_screen_bounds()
    except Exception:
        c.target_screen_bounds = tuple(app.virtual_rect)
    c.hover_zones = list(app._hover_zones)
    c.hover_selection = _d(cfg, "hover_selection")
    c.hover_enabled = bool(_d(cfg, "hover_enabled"))
    c.hover_frequency = float(_d(cfg, "hover_frequency"))
    c.hover_dwell_min = float(_d(cfg, "hover_dwell_min"))
    c.hover_dwell_max = float(_d(cfg, "hover_dwell_max"))
    c.key_timers = [
        KeyTimer(key=t.key, interval_min=t.interval_min,
                 interval_max=t.interval_max, enabled=t.enabled,
                 interval_unit=getattr(t, "interval_unit", "min"))
        for t in app._key_timers
    ]
    c.key_timer_jitter_enabled = bool(_d(cfg, "key_timer_jitter_enabled"))
    # Corner watchdog switch. Older engines have no such attribute; setting
    # it there is harmless and the deck footer reads corner_abort_armed().
    c.corner_abort_enabled = bool(_d(cfg, "corner_abort_enabled"))
    c.key_input_method = str(_d(cfg, "key_input_method") or "auto").lower()
    c.serial_hid_port = str(_d(cfg, "serial_hid_port") or "")
    c.mode = app._active_mode
    c.recorder_steps = list(app._steps)
    c.realism = float(_d(cfg, "realism"))
    c.tracker = app._tracker


def schedule_start(app) -> None:
    QMetaObject.invokeMethod(app, "_on_start", Qt.QueuedConnection)


def schedule_stop(app) -> None:
    QMetaObject.invokeMethod(app, "_on_stop", Qt.QueuedConnection)


def schedule_emergency_stop(app) -> None:
    QMetaObject.invokeMethod(app, "_emergency_stop", Qt.QueuedConnection)


def schedule_toggle_pause(app) -> None:
    """Hotkey-thread to UI-thread bridge for the pause / resume toggle.
    Universal: the slot picks the bot runner or the click engine."""
    QMetaObject.invokeMethod(app, "_toggle_pause", Qt.QueuedConnection)


# ── Combined state ──────────────────────────────────────────────────────────


def bot_is_running(app) -> bool:
    runner = getattr(app, "bot_runner", None)
    if runner is None:
        return False
    try:
        return bool(runner.is_running())
    except Exception:
        return False


def engine_paused(app) -> bool:
    """True while whatever is running is on hold: a paused bot, or a click
    engine that reports ``is_paused()`` / a PAUSED state. Paused counts as
    running everywhere else (WidgetLocker, START / STOP), so this is the
    only extra bit the UI needs."""
    if getattr(app, "_bot_running", False):
        runner = getattr(app, "bot_runner", None)
        if runner is not None:
            try:
                return bool(runner.is_paused())
            except Exception:
                return False
        return False
    clicker = getattr(app, "clicker", None)
    if clicker is None or clicker.state == ClickerState.IDLE:
        return False
    if clicker.state == getattr(ClickerState, "PAUSED", "paused"):
        return True
    probe = getattr(clicker, "is_paused", None)
    if callable(probe):
        try:
            return bool(probe())
        except Exception:
            return False
    return False


def effective_state(app) -> str:
    """What the topbar should show: the clicker's own state, or ACTIVE while
    a bot runs (the runner has no STARTING phase worth surfacing)."""
    if getattr(app, "_ai_preparing", False):
        return ClickerState.STARTING
    clicker_state = getattr(app, "_clicker_state_str", ClickerState.IDLE)
    if clicker_state != ClickerState.IDLE:
        return clicker_state
    if getattr(app, "_bot_running", False):
        return ClickerState.ACTIVE
    return ClickerState.IDLE


def on_clicker_state(app, state: str) -> None:
    """Engine-thread callback. Latches state and queues a UI sync."""
    app._clicker_state_str = state
    app._state_str = effective_state(app)
    QMetaObject.invokeMethod(
        app, "_sync_overlay_for_state",
        Qt.QueuedConnection,
    )


def on_bot_running_changed(app, running: bool) -> None:
    """Bot runner started or finished. Runs on the Qt main thread (the
    runner's signals are already delivered there), so the sync is direct."""
    was = bool(getattr(app, "_bot_running", False))
    app._bot_running = bool(running)
    app._state_str = effective_state(app)
    sync_overlay_for_state(app, app._state_str)
    # The runner has no on_event hook, so the bot's start / stop lands in
    # the deck's event log from here (already on the GUI thread).
    log = getattr(app, "event_log", None)
    if log is not None and was != app._bot_running:
        slug = str(app.cfg.get("ai_active_bundle") or app.cfg.get("ai_bot_slug") or "bot")
        log.add("START" if running else "STOP", f"BOT {slug}")


def on_track_error(app, step_id: str, reason: str) -> None:
    """Engine-thread callback. Queues a track-template-failure toast."""
    QMetaObject.invokeMethod(
        app, "_on_track_error",
        Qt.QueuedConnection,
        Q_ARG(str, step_id),
        Q_ARG(str, reason),
    )


def on_session_complete(app, reason: str) -> None:
    """Engine-thread callback. Queues a stop + success toast for the
    "stop after N clicks / minutes" feature."""
    QMetaObject.invokeMethod(
        app, "_on_session_complete",
        Qt.QueuedConnection,
        Q_ARG(str, reason),
    )


def on_engine_halt(app, msg: str, level: str) -> None:
    """Engine-thread (or GUI-thread) callback. Queues a halt/warn toast
    so every silent stop reason becomes visible to the user."""
    QMetaObject.invokeMethod(
        app, "_on_engine_halt",
        Qt.QueuedConnection,
        Q_ARG(str, msg),
        Q_ARG(str, level),
    )


def sync_overlay_for_state(app, state: str) -> None:
    """Apply state-derived UI changes (button enable, overlay show/hide).

    Runs on the Qt main thread (called from App._sync_overlay_for_state slot).
    """
    refresh_action_buttons(app, state)
    om = app.overlay_manager
    if state == ClickerState.IDLE:
        om.hide_main()
        for ov in om._hover_overlays + om._step_overlays:
            ov.hide_zone()
        return
    if app._active_mode == "ai":
        # Bot runs paint their own HUD (BotOverlay); the zone overlays
        # belong to Click / Record and stay hidden.
        return
    if app._active_mode == "recorder":
        om.refresh_step_overlays()
        om.refresh_hover_overlays()
        return
    if app._zone is not None and app.cfg.get("show_zone_overlay", True):
        om.show_main(app._zone, t.ZONE_DEFAULT_COLOR, app.cfg["zone_opacity"])
    om.refresh_hover_overlays()


def refresh_action_buttons(app, state: str) -> None:
    # Any non-IDLE state, PAUSED included, keeps the controls locked: a
    # held engine resumes into whatever config it was started with.
    if state == ClickerState.IDLE:
        app.start_btn.setEnabled(True)
        app.stop_btn.setEnabled(False)
    else:
        app.start_btn.setEnabled(False)
        app.stop_btn.setEnabled(True)
    app.locker.apply(state)
