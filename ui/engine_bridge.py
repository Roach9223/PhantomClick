"""Bridge between the Qt App and the ``Clicker`` engine.

The engine is framework-agnostic: it runs on its own daemon thread and
fires plain-Python callbacks. The bridge marshals those callbacks back
to the Qt main thread via ``QMetaObject.invokeMethod`` (the Qt-native way
to cross thread boundaries) instead of Tk's ``app.after``.

This is the only file in ``ui/`` that knows the layout of every cfg
key; cards stop short of mutating the engine directly so this single
push function stays the source of truth.
"""

from __future__ import annotations

from PySide6.QtCore import QMetaObject, Q_ARG, Qt, Slot

from modules.clicker import ClickerState
from modules.key_timer import KeyTimer


def push_config_to_clicker(app) -> None:
    """Mirror App cfg + state into the engine before Start.

    Engine has no two-way binding back; whatever's on the engine at
    ``start()`` time is what runs. The WidgetLocker prevents mid-run edits
    so this isn't a desync risk in practice.
    """
    c = app.clicker
    cfg = app.cfg
    c.zone = app._zone
    c.min_delay = float(cfg["min_delay"])
    c.max_delay = float(cfg["max_delay"])
    c.click_type = cfg["click_type"]
    c.click_mode = cfg["click_mode"]
    c.prestart_delay = float(cfg["prestart_delay"])
    c.idle_wander_enabled = bool(cfg["idle_wander_enabled"])
    c.idle_wander_frequency = float(cfg["idle_wander_frequency"])
    c.idle_wander_padding = int(cfg["idle_wander_padding"])
    c.fatigue_enabled = bool(cfg["fatigue_enabled"])
    c.fatigue_intensity = float(cfg.get("fatigue_intensity", 0.25))
    c.break_bursts_enabled = bool(cfg["break_bursts_enabled"])
    c.break_min_clicks = int(cfg.get("break_min_clicks", 40))
    c.break_max_clicks = int(cfg.get("break_max_clicks", 70))
    c.break_min_duration = float(cfg.get("break_min_duration", 30.0))
    c.break_max_duration = float(cfg.get("break_max_duration", 90.0))
    c.overshoot_enabled = bool(cfg["overshoot_enabled"])
    c.overshoot_probability = float(cfg.get("overshoot_probability", 0.15))
    c.anti_cluster_enabled = bool(cfg["anti_cluster_enabled"])
    c.anti_cluster_radius = float(cfg.get("anti_cluster_radius", 18))
    c.idle_wander_whole_screen = bool(cfg.get("idle_wander_whole_screen", False))
    c.stop_after_clicks_enabled = bool(cfg.get("stop_after_clicks_enabled", False))
    c.stop_after_clicks = int(cfg.get("stop_after_clicks", 1000))
    c.stop_after_minutes_enabled = bool(cfg.get("stop_after_minutes_enabled", False))
    c.stop_after_minutes = int(cfg.get("stop_after_minutes", 60))
    # Resolve target_monitor → absolute (x, y, w, h) so the engine doesn't
    # need to know about Qt screens. App helper handles auto / index / fall-
    # backs; the engine just clamps drift / wander / corner-failsafe to this.
    try:
        c.target_screen_bounds = app.target_screen_bounds()
    except Exception:
        c.target_screen_bounds = (0, 0, app.monitor_w, app.monitor_h)
    c.hover_zone = None  # legacy single-zone slot stays empty
    c.hover_zones = list(app._hover_zones)
    c.hover_selection = cfg.get("hover_selection", "random")
    c.hover_enabled = bool(cfg.get("hover_enabled", True))
    c.hover_frequency = float(cfg.get("hover_frequency", 0.15))
    c.hover_dwell_min = float(cfg.get("hover_dwell_min", 1.0))
    c.hover_dwell_max = float(cfg.get("hover_dwell_max", 4.0))
    c.key_timers = [
        KeyTimer(key=t.key, interval_min=t.interval_min,
                 interval_max=t.interval_max, enabled=t.enabled,
                 interval_unit=getattr(t, "interval_unit", "min"))
        for t in app._key_timers
    ]
    c.key_timer_jitter_enabled = bool(cfg.get("key_timer_jitter_enabled", True))
    c.key_input_method = str(cfg.get("key_input_method", "auto") or "auto").lower()
    c.serial_hid_port = str(cfg.get("serial_hid_port", "") or "")
    c.mode = app._active_mode
    c.recorder_steps = list(app._steps)
    c.realism = float(cfg.get("realism", 0.5))
    c.tracker = app._tracker


def schedule_start(app) -> None:
    QMetaObject.invokeMethod(app, "_on_start", Qt.QueuedConnection)


def schedule_stop(app) -> None:
    QMetaObject.invokeMethod(app, "_on_stop", Qt.QueuedConnection)


def schedule_emergency_stop(app) -> None:
    QMetaObject.invokeMethod(app, "_emergency_stop", Qt.QueuedConnection)


def schedule_toggle_pause(app) -> None:
    """Hotkey-thread → UI-thread bridge for the AI pause/resume toggle."""
    QMetaObject.invokeMethod(app, "_toggle_ai_pause", Qt.QueuedConnection)


def on_clicker_state(app, state: str) -> None:
    """Engine-thread callback. Latches state and queues a UI sync."""
    app._state_str = state
    QMetaObject.invokeMethod(
        app, "_sync_overlay_for_state",
        Qt.QueuedConnection,
    )


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
    if app._active_mode == "recorder":
        om.refresh_step_overlays()
        om.refresh_hover_overlays()
        return
    if app._zone is not None and app.cfg.get("show_zone_overlay", True):
        om.show_main(app._zone, app.cfg["zone_color"], app.cfg["zone_opacity"])
    om.refresh_hover_overlays()


def refresh_action_buttons(app, state: str) -> None:
    if state == ClickerState.IDLE:
        app.start_btn.setEnabled(True)
        app.stop_btn.setEnabled(False)
    else:
        app.start_btn.setEnabled(False)
        app.stop_btn.setEnabled(True)
    app.locker.apply(state)
