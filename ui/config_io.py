"""Config persistence + filesystem paths shared across the UI layer.

``DEFAULTS`` is the single source of truth for what keys the app expects;
``load_config`` deep-merges with whatever's on disk and runs in-place
migrations (legacy hotkey rename, single→multi hover, palette refresh).
Migrated configs are auto-saved so the next launch sees the canonical shape.

``_templates_dir`` lives here because the per-step PNG path resolution
(used by Track steps) is config-adjacent, both follow the frozen-exe vs.
source-dir rule for finding the install root.
"""

from __future__ import annotations

import json
import copy
import os
import shutil
import sys
import tempfile
import threading
import time
from pathlib import Path

from utils.logger import get_logger

_log = get_logger("config_io")
_save_lock = threading.RLock()


def _config_path() -> Path:
    base = Path(sys.executable).parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parent.parent
    return base / "config.json"


def _config_dir() -> Path:
    """Directory that owns config.json and the per-step templates folder."""
    base = (Path(sys.executable).parent if getattr(sys, "frozen", False)
            else Path(__file__).resolve().parent.parent)
    return base


def _templates_dir() -> Path:
    return _config_dir() / "templates"


def wiki_cache_root() -> Path:
    """``<writable_root>/debug/wiki_cache``: the on-disk cache for icons
    fetched from runescape.wiki. Anchored to the install root (not the
    CWD) so a shortcut launched from another folder finds the same cache
    and a frozen build doesn't write into PyInstaller's temp extract."""
    from utils.paths import writable_root
    return writable_root() / "debug" / "wiki_cache"


def _shot_to_bgr_array(shot):
    """mss ScreenShot → numpy BGR ndarray (drops alpha)."""
    import numpy as np
    return np.array(shot)[:, :, :3]


DEFAULTS: dict = {
    "hotkey_start": "f6",
    "hotkey_stop": "f7",
    # F8 holds / resumes whatever is running: a bot or the click engine.
    "hotkey_pause": "f8",
    "hotkey_capture": "f9",
    # Main window size restored on launch. Mirrors ui.theme.WINDOW_*_DEFAULT
    # as plain ints so this module stays free of Qt imports.
    "window_w": 1280,
    "window_h": 800,
    # Window position. The deck shell restores x / y / w / h only when
    # that rect still touches a connected screen; otherwise it opens at
    # 80% of the screen under the cursor. null until the first close.
    "window_x": None,
    "window_y": None,
    "min_delay": 5.0,
    "max_delay": 20.0,
    "click_type": "left",
    "click_mode": "single",
    "realism": 0.5,
    "zone": None,
    "zone_shape": "rect",
    # The click-zone outline is always the theme accent (ui.theme
    # ZONE_DEFAULT_COLOR); only its opacity is a setting.
    "zone_opacity": 0.25,
    # What a freshly drawn Click / Record zone locks to. "window" ties it
    # to the top-level window under the zone so it follows a dragged game
    # window; "screen" keeps the pre-lock behaviour of fixed coordinates.
    "zone_lock_default": "window",
    "show_zone_overlay": True,
    "prestart_delay": 2.5,
    "idle_wander_enabled": False,
    "idle_wander_frequency": 0.15,
    "idle_wander_padding": 500,
    "fatigue_enabled": True,
    "fatigue_intensity": 0.25,
    "break_bursts_enabled": True,
    # Defaults tuned so a casual user gets a break every ~150 clicks rather
    # than every ~50; previous tighter spacing felt aggressive in short
    # sessions. Realism preset overrides these (see _apply_realism in
    # ui/cards/behavior.py) so users who want frequent breaks still can.
    "break_min_clicks": 100,
    "break_max_clicks": 200,
    "break_min_duration": 20.0,
    "break_max_duration": 60.0,
    "overshoot_enabled": True,
    "overshoot_probability": 0.15,
    "anti_cluster_enabled": True,
    # Reduced from 18 → 8: 18 px repulsion is half the diameter of a
    # typical 30×30 game button, so two consecutive clicks on the same
    # button were getting the second push to (or past) the button edge.
    # The engine also clamps the effective radius to (zone_min_dim / 4)
    # at runtime so anti-cluster never dominates the zone geometry,
    # this default just sets a sensible starting cap.
    "anti_cluster_radius": 8,
    "idle_wander_whole_screen": True,
    "stop_after_clicks_enabled": False,
    "stop_after_clicks": 1000,
    "stop_after_minutes_enabled": False,
    "stop_after_minutes": 60,
    "key_timer_jitter_enabled": True,
    # Corner emergency stop: the watchdog halts the engine when the cursor
    # lands in a screen corner. On by default; the deck's zone-map footer
    # toggles it.
    "corner_abort_enabled": True,
    # Keyboard event backend selector. ``"auto"`` prefers Interception
    # when the driver+wrapper are installed (bypasses NXT-style injected-
    # event filters), otherwise falls back to SendInput. ``"sendinput"``
    # forces the standard path; ``"interception"`` forces hardware mode.
    "key_input_method": "auto",
    # COM port for the Serial HID backend. Empty until the user picks
    # one in Behavior → Key input method. The SerialHidBackend surfaces
    # a clear error if `serial_hid` is selected without a port set.
    "serial_hid_port": "",
    # Plays a short Win32 system beep when the engine halts (corner stop,
    # crash, session-complete). Manual stops stay silent. Default on so a
    # fullscreen-game user knows the engine died without having to alt-tab
    # back to PhantomClick to read the toast.
    "sound_on_stop": True,
    # "auto" → engine targets the monitor containing the active zone, falling
    # back to primary; otherwise the value is the integer index into Qt's
    # QGuiApplication.screens() list captured at app launch.
    "target_monitor": "auto",
    "target_monitor_identity": {},
    "ai_monitor_identity": {},
    "hover_zones": [],
    "hover_selection": "random",
    "hover_zone_shape": "rect",
    "hover_enabled": True,
    "hover_frequency": 0.10,
    "hover_dwell_min": 10.0,
    "hover_dwell_max": 20.0,
    "hover_color": "#9A9C95",
    "hover_opacity": 0.22,
    "active_mode": "clicker",
    "recorder_steps": [],
    "record_filter": "all",   # Record-tab sub-tab: all|clicks|keys|pauses|loops
    # List-of-expanded semantics: step_id present here = body visible.
    # Default empty (all collapsed); newly added steps get appended so
    # the user sees their controls right after creating them.
    "recorder_expanded_steps": [],
    "key_timers": [],
    "mica_enabled": True,
    "nav_section": "click",
    # Main-window layout. "deck" is the command-deck shell (header, three
    # columns, settings drawer). "classic" rebuilds the TopBar + NavRail
    # shell as a fallback.
    "ui_shell": "deck",
    # Play the 1.6 s Blender boot animation before the window opens.
    "boot_animation": True,
    # Deck shell: whether the editor pane (right side of the centre
    # splitter) is open, and the splitter's two sizes in logical px.
    # null means the 62 / 38 default split.
    "deck_editor_open": True,
    "deck_splitter": None,
    # Monitor tab: opt-in local LAN HTTP server. Off by default. Streaming
    # and remote control are gated by separate toggles so the safer view-
    # only mode is the default; the user must explicitly enable control.
    "monitor_enabled": False,
    "monitor_port": 8765,
    "monitor_fps": 15,                        # 5-60; smoother at 30+
    "monitor_jpeg_quality": 85,               # JPEG quality 30-95
    "monitor_max_width": 1920,                # downscale cap; 0 = native (no downscale)
    # "primary" = always use the OS-primary screen (recovers if a monitor is
    # unplugged). Else a Qt-screens() integer index serialized as string.
    "monitor_capture_index": "primary",
    # Resolved {"left","top","width","height"} cached from the Qt screen
    # geometry so the worker thread doesn't have to call into Qt. Recomputed
    # whenever the user picks a different monitor.
    "monitor_capture_rect": None,
    "monitor_token": "",                      # generated on first enable; empty = open
    "monitor_remote_control_enabled": False,  # gates POST /control/*
    # AI tab, third top-level mode that runs RS3_AI rule-based bots
    # through PhantomClick's humanizer + Arduino HID keystroke path.
    # ``active_mode`` may now be "clicker" | "recorder" | "ai".
    "ai_bot_slug": "",                        # last-selected library bot
    "ai_active_bundle": "",                   # slug of the active bots/<slug>/ bundle
    "ai_tick_rate_hz": 5.0,
    "ai_monitor": 1,                          # mss monitor index (1 = primary)
    # Default on: a fresh install evaluates rules and logs actions without
    # touching the mouse until the user opts into live input. The runner
    # ORs this with the bot script's own dry_run flag (script is a floor).
    "ai_dry_run": True,
    "ai_auto_stop_dry_ticks": 60,
    "ai_watchdog_no_click_s": 600.0,
    "ai_auto_camera": True,
    # Awareness layer ROIs, populated by the AI tab's "Calibrate"
    # buttons. Each is [x, y, w, h] in absolute screen pixels, or None
    # when the user hasn't calibrated yet. Bots that read
    # world().inventory / orbs / minimap should bail gracefully on None.
    "ai_inventory_rect": None,
    "ai_orbs_rect": None,
    "ai_minimap_rect": None,                  # Phase 2 stub, reserved
    # Per-orb saturated-pixel count captured at 100% during the orbs
    # calibration. Keys: "hp", "prayer", "summoning", "run_energy".
    # Empty {} until the user calibrates.
    "ai_orbs_max_fill": {},
    # In-GUI bot authoring (Phase 2, Custom Bot surface).
    "ai_user_bot_steps": [],                  # list of AIBotStep JSON dicts
    "ai_use_user_bot": False,                 # picker state: True = custom mode
    "ai_user_bot_name": "My Custom Bot",
    # Per-bot wiki-sourced item library: list of canonical item names
    # like ["Raw trout", "Yew logs"]. Each name has a cached icon at
    # <writable_root>/debug/wiki_cache/items/<slug>.png. The framework
    # rebuilds the ItemLibrary at Start time and attaches it to the Bot.
    "ai_user_bot_items": [],
    # The only outbound-network feature besides the LAN Monitor server:
    # fetching item icons from runescape.wiki. Off by default so a fresh
    # install makes no HTTP requests until the user opts in on Settings.
    "ai_wiki_fetch_enabled": False,
    # AI pane: False shows the consumer view (pick a bot, tick rate, dry
    # run, live status); True adds the author tools (captures, library,
    # rules, calibration, log, in-GUI authoring).
    "ai_author_tools": False,
}

# Keys that older builds wrote but nothing reads any more. Dropped from
# the on-disk file on the next save so config.json stops carrying them.
# ``zone_color`` went with the 2026 deck theme: the outline is always the
# theme accent so it matches the app, and a stale custom pick (blue from
# the pre-deck palette) no longer survives in config.json.
_DEAD_KEYS = ("customize_open", "ai_user_bot_expanded_steps",
              "ai_user_bot_tick_rate_hz", "zone_color")


def _load_rolling_backup(p: Path) -> dict:
    """The last good settings ``save_config`` kept next to config.json,
    or ``{}``. Used instead of bare defaults when config.json is missing
    or unreadable, so a bad write never costs the user their setup."""
    bak = p.with_name(p.name + ".bak")
    try:
        data = json.loads(bak.read_text(encoding="utf-8"))
    except (OSError, ValueError, UnicodeError):
        return {}
    if isinstance(data, dict) and data:
        _log.warning("config.json unusable; restored settings from %s", bak.name)
        return data
    return {}


def load_config() -> dict:
    p = _config_path()
    cfg = copy.deepcopy(DEFAULTS)
    loaded: dict = {}
    backup_path: Path | None = None
    if not p.exists():
        loaded = _load_rolling_backup(p)
    if p.exists():
        try:
            with p.open("r", encoding="utf-8") as f:
                loaded = json.load(f)
            if not isinstance(loaded, dict):
                raise ValueError("settings root must be an object")
        except (json.JSONDecodeError, ValueError) as e:
            # Corrupt JSON, preserve the bad file as a timestamped backup
            # so the user can retrieve any rare-but-real settings, then
            # fall back to defaults. Surface a toast on the next App init
            # via the transient ``_corrupt_backup`` key set below.
            ts = time.time_ns()
            backup_path = p.with_name(f"{p.name}.bak.{ts}")
            try:
                p.rename(backup_path)
            except OSError:
                backup_path = None
            _log.warning(
                "config.json corrupt (%s); backed up to %s",
                e, backup_path.name if backup_path else "<rename failed>",
            )
            loaded = _load_rolling_backup(p)
        except Exception as e:
            # Non-JSON I/O error, log but don't backup; let the defaults
            # path take over without disturbing the file.
            _log.warning("config.json read failed (%s); using defaults", e)
            loaded = {}
    from .config_validation import validate_config
    loaded, repaired = validate_config(loaded, DEFAULTS)
    if repaired:
        try:
            backup_path = p.with_name(f"{p.name}.bak.{time.time_ns()}")
            shutil.copy2(p, backup_path)
        except OSError:
            backup_path = None
        _log.warning("Repaired invalid settings: %s", ", ".join(repaired))
    cfg.update(loaded)

    # Migrate legacy single-toggle hotkey to separate start/stop keys.
    migrated = bool(repaired)
    if "hotkey_toggle" in cfg:
        if "hotkey_start" not in loaded:
            cfg["hotkey_start"] = cfg["hotkey_toggle"]
        cfg.pop("hotkey_toggle", None)
        migrated = True
    if "hotkey_stop" not in loaded:
        cfg.setdefault("hotkey_stop", "f7")
        migrated = True
    if "realism" not in loaded:
        cfg.setdefault("realism", 0.5)
        migrated = True
    # Multi-hover migration: collapse legacy single hover_zone into a list.
    if "hover_zone" in cfg:
        legacy = cfg.pop("hover_zone")
        if "hover_zones" not in loaded and legacy:
            cfg["hover_zones"] = [legacy]
        migrated = True
    if "hover_zones" not in cfg:
        cfg["hover_zones"] = []
        migrated = True
    if "hover_selection" not in loaded:
        cfg.setdefault("hover_selection", "random")
        migrated = True
    if "active_mode" not in loaded:
        cfg.setdefault("active_mode", "clicker")
        migrated = True
    if "recorder_steps" not in loaded:
        cfg.setdefault("recorder_steps", [])
        migrated = True
    # Drop dead keys from prior versions on the next write.
    for dead in _DEAD_KEYS:
        if dead in cfg:
            cfg.pop(dead, None)
            migrated = True
    # 2026 palette refresh: migrate the old hover default so existing users
    # pick up the new accent on next launch. Custom-picked colors are left
    # alone.
    if cfg.get("hover_color") == "#4a90e2":
        cfg["hover_color"] = "#5b8def"
        migrated = True
    if cfg.get("hover_color") == "#5b8def":
        cfg["hover_color"] = "#9A9C95"
        migrated = True
    # Anti-cluster radius migration. The previous default (18) and its
    # realism-derived ceiling (up to 30) were shown to push the second
    # of two consecutive clicks past the edge of typical small game
    # buttons. We pull anything > 12 down to 12 once, on the assumption
    # the user accepted the old default rather than tuned it. Users who
    # explicitly want a wider radius can crank it back up in Behavior →
    # Advanced; the runtime zone-aware clamp protects them either way.
    if not cfg.get("anti_cluster_migrated", False) and cfg["anti_cluster_radius"] > 12:
        cfg["anti_cluster_radius"] = 12
        migrated = True
    if not cfg.get("anti_cluster_migrated", False):
        cfg["anti_cluster_migrated"] = True
        migrated = True
    if migrated:
        save_config(cfg)
    # Transient, read once by App init for a corruption toast, then popped.
    if backup_path is not None:
        cfg["_corrupt_backup"] = str(backup_path)
    if repaired:
        cfg["_repaired_fields"] = repaired
    return cfg


def save_config(cfg: dict) -> bool:
    """Atomically save, keeping the previous valid file and a visible error state."""
    temporary = None
    with _save_lock:
        try:
            out = {k: v for k, v in cfg.items() if not str(k).startswith("_")}
            payload = json.dumps(out, indent=4, allow_nan=False)
            path = _config_path()
            with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent,
                                             prefix=path.name + ".", suffix=".tmp", delete=False) as f:
                temporary = Path(f.name)
                f.write(payload)
                f.flush()
                os.fsync(f.fileno())
            if path.is_file():
                # Never promote an already damaged file to the rolling backup.
                try:
                    previous = json.loads(path.read_text(encoding="utf-8"))
                except (ValueError, UnicodeError):
                    previous = None
                if isinstance(previous, dict):
                    shutil.copy2(path, path.with_name(path.name + ".bak"))
            os.replace(temporary, path)
            cfg.pop("_save_error", None)
            return True
        except Exception as e:
            cfg["_save_error"] = f"Settings could not be saved: {e}"
            _log.exception("Settings save failed")
            return False
        finally:
            if temporary is not None:
                try:
                    temporary.unlink(missing_ok=True)
                except OSError:
                    _log.warning("Could not clean temporary settings file: %s", temporary)
