"""Central command registry — every action surfaceable via the Ctrl+K palette.

Each :class:`Command` is pure data plus a closure over ``app``. We import
heavy modules lazily inside actions so the registry build stays cheap and
import-cycle-free.

Categories control the empty-search grouping:
    Engine · Mode · Zone · Timing · Record · View · Settings

The ``shortcut`` field is the *display* string ("Ctrl+D"). The ``qt_shortcut``
field is the same string handed to ``QKeySequence`` — set only for commands
the App should bind globally. Many commands have no shortcut (``shortcut=None``)
and are reachable only through the palette; that's fine.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Optional, Sequence


@dataclass
class Command:
    id: str
    label: str
    category: str
    action: Callable[[object], None]
    shortcut: Optional[str] = None
    qt_shortcut: Optional[str] = None
    keywords: Sequence[str] = field(default_factory=tuple)
    available: Callable[[object], bool] = field(default=lambda _app: True)


def _set_timing(app, lo: float, hi: float) -> None:
    cfg = app.cfg
    cfg["min_delay"] = float(lo)
    cfg["max_delay"] = float(hi)
    app.click_page.timing_card.range_slider.set_values(lo, hi)
    app.click_page.timing_card._refresh_entries()
    from ui.config_io import save_config
    save_config(cfg)
    app._push_config_to_clicker()
    # Make sure the user actually sees the change.
    app.nav_rail.set_current("click")


def _toggle_mica(app) -> None:
    cfg = app.cfg
    cfg["mica_enabled"] = not bool(cfg.get("mica_enabled", True))
    from ui.config_io import save_config
    save_config(cfg)
    app.toasts.post(
        "Restart the app to apply the backdrop change.", kind="info",
    )


def register_all(app) -> list[Command]:
    """Build the command list for ``app``. Called once during App construction."""
    return [
        # -- Engine ----------------------------------------------------------
        Command(
            id="engine.start",
            label="Start clicking",
            category="Engine",
            shortcut="F6",
            action=lambda a: a._on_start(),
            keywords=("run", "go", "begin"),
        ),
        Command(
            id="engine.stop",
            label="Stop clicking",
            category="Engine",
            shortcut="F7",
            action=lambda a: a._on_stop(),
            keywords=("halt", "pause", "end"),
        ),
        Command(
            id="engine.emergency",
            label="Emergency stop",
            category="Engine",
            shortcut="Esc",
            action=lambda a: a._emergency_stop(),
            keywords=("kill", "abort", "panic"),
        ),

        # -- Navigation (and Mode, since Click/Record nav also flips engine mode) -
        Command(
            id="nav.click",
            label="Go to Click",
            category="Navigation",
            shortcut="Ctrl+1",
            qt_shortcut="Ctrl+1",
            action=lambda a: a.nav_rail.set_current("click"),
            keywords=("zone", "single", "mode"),
        ),
        Command(
            id="nav.record",
            label="Go to Record",
            category="Navigation",
            shortcut="Ctrl+2",
            qt_shortcut="Ctrl+2",
            action=lambda a: a.nav_rail.set_current("record"),
            keywords=("sequence", "steps", "mode"),
        ),
        Command(
            id="nav.hover",
            label="Go to Hover Zones",
            category="Navigation",
            action=lambda a: a.nav_rail.set_current("hover"),
            keywords=("drift", "wander"),
        ),
        Command(
            id="nav.behavior",
            label="Go to Behavior",
            category="Navigation",
            action=lambda a: a.nav_rail.set_current("behavior"),
            keywords=("realism", "advanced", "fatigue"),
        ),
        Command(
            id="nav.hotkeys",
            label="Go to Hotkeys",
            category="Navigation",
            action=lambda a: a.nav_rail.set_current("hotkeys"),
            keywords=("shortcut", "rebind"),
        ),
        Command(
            id="nav.timers",
            label="Go to Key Timers",
            category="Navigation",
            action=lambda a: a.nav_rail.set_current("timers"),
            keywords=("keypress", "macro", "potion", "passive"),
        ),
        Command(
            id="nav.stats",
            label="Go to Stats",
            category="Navigation",
            action=lambda a: a.nav_rail.set_current("stats"),
            keywords=("clicks", "cpm", "elapsed"),
        ),
        Command(
            id="nav.help",
            label="Go to Help",
            category="Navigation",
            shortcut="F1",
            qt_shortcut="F1",
            action=lambda a: a.nav_rail.set_current("help"),
            keywords=("documentation", "guide", "how"),
        ),

        # -- Zone ------------------------------------------------------------
        Command(
            id="zone.draw",
            label="Draw click zone",
            category="Zone",
            shortcut="Ctrl+D",
            qt_shortcut="Ctrl+D",
            action=lambda a: a.click_page.zone_card._on_draw(),
            available=lambda a: a._active_mode == "clicker",
            keywords=("rectangle", "circle", "polygon"),
        ),
        Command(
            id="zone.clear",
            label="Clear click zone",
            category="Zone",
            action=lambda a: a.click_page.zone_card._on_clear(),
            available=lambda a: a._active_mode == "clicker" and a._zone is not None,
            keywords=("delete", "remove"),
        ),
        Command(
            id="zone.add_hover",
            label="Add hover zone",
            category="Zone",
            action=lambda a: a.hover_zones_card._on_add(),
            keywords=("drift", "wander"),
        ),

        # -- Timing ----------------------------------------------------------
        Command(
            id="timing.fast",
            label="Set timing — Fast (0.5–2 s)",
            category="Timing",
            action=lambda a: _set_timing(a, 0.5, 2.0),
            keywords=("preset", "speed"),
        ),
        Command(
            id="timing.medium",
            label="Set timing — Medium (3–10 s)",
            category="Timing",
            action=lambda a: _set_timing(a, 3.0, 10.0),
            keywords=("preset", "speed"),
        ),
        Command(
            id="timing.slow",
            label="Set timing — Slow (10–30 s)",
            category="Timing",
            action=lambda a: _set_timing(a, 10.0, 30.0),
            keywords=("preset", "speed"),
        ),

        # -- Record ----------------------------------------------------------
        Command(
            id="record.add_click",
            label="Add Click step",
            category="Record",
            action=lambda a: a.record_mode_tab.on_add_click(),
        ),
        Command(
            id="record.add_track",
            label="Add Track step",
            category="Record",
            action=lambda a: a.record_mode_tab.on_add_track(),
            keywords=("template", "follow"),
        ),
        Command(
            id="record.add_color",
            label="Add Color step",
            category="Record",
            action=lambda a: a.record_mode_tab.on_add_color(),
            keywords=("pixel", "eyedropper"),
        ),
        Command(
            id="record.add_pause",
            label="Add Pause step",
            category="Record",
            action=lambda a: a.record_mode_tab.on_add_pause(),
            keywords=("wait", "delay"),
        ),
        Command(
            id="record.add_loop",
            label="Add Loop step",
            category="Record",
            action=lambda a: a.record_mode_tab.on_add_loop(),
            keywords=("repeat", "jump"),
        ),

        # -- Key Timers ------------------------------------------------------
        Command(
            id="timers.add",
            label="Add key timer",
            category="Timers",
            action=lambda a: (
                a.nav_rail.set_current("timers")
                or a.key_timers_card._on_add()
            ),
            keywords=("keypress", "macro", "potion", "passive"),
        ),

        # -- View ------------------------------------------------------------
        Command(
            id="view.toggle_overlays",
            label="Toggle overlays",
            category="View",
            shortcut="Ctrl+H",
            qt_shortcut="Ctrl+H",
            action=lambda a: a.action_bar.on_toggle_overlay(),
            keywords=("hide", "show", "outline"),
        ),
        Command(
            id="view.open_advanced",
            label="Open Behavior · Advanced",
            category="View",
            action=lambda a: (
                a.nav_rail.set_current("behavior")
                or a.behavior_card.advanced.set_open(True)
            ),
            keywords=("realism", "fatigue", "wander"),
        ),
        Command(
            id="view.toggle_backdrop",
            label="Toggle Mica backdrop (restart required)",
            category="View",
            action=_toggle_mica,
            keywords=("transparent", "blur", "wallpaper"),
        ),

        # -- Settings --------------------------------------------------------
        Command(
            id="settings.rebind_start",
            label="Rebind Start hotkey",
            category="Settings",
            action=lambda a: (
                a.nav_rail.set_current("hotkeys")
                or a.hotkeys_card.on_rebind("start")
            ),
        ),
        Command(
            id="settings.rebind_stop",
            label="Rebind Stop hotkey",
            category="Settings",
            action=lambda a: (
                a.nav_rail.set_current("hotkeys")
                or a.hotkeys_card.on_rebind("stop")
            ),
        ),
        Command(
            id="settings.reset_stats",
            label="Reset stats",
            category="Settings",
            action=lambda a: a.stats.reset(),
            keywords=("clear", "zero"),
        ),
    ]
