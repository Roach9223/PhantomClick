"""Config persistence + filesystem paths shared across the UI layer.

``DEFAULTS`` is the single source of truth for what keys the app expects;
``load_config`` deep-merges with whatever's on disk and runs in-place
migrations (legacy hotkey rename, single→multi hover, palette refresh).
Migrated configs are auto-saved so the next launch sees the canonical shape.

``_templates_dir`` lives here because the per-step PNG path resolution
(used by Track steps) is config-adjacent — both follow the frozen-exe vs.
source-dir rule for finding the install root.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

from utils.logger import get_logger

_log = get_logger("config_io")


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


def _shot_to_bgr_array(shot):
    """mss ScreenShot → numpy BGR ndarray (drops alpha)."""
    import numpy as np
    return np.array(shot)[:, :, :3]


DEFAULTS: dict = {
    "hotkey_start": "f6",
    "hotkey_stop": "f7",
    "hotkey_capture": "f9",
    "min_delay": 5.0,
    "max_delay": 20.0,
    "click_type": "left",
    "click_mode": "single",
    "realism": 0.5,
    "zone": None,
    "zone_shape": "rect",
    "zone_color": "#22d3ee",
    "zone_opacity": 0.25,
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
    # at runtime so anti-cluster never dominates the zone geometry —
    # this default just sets a sensible starting cap.
    "anti_cluster_radius": 8,
    "idle_wander_whole_screen": True,
    "stop_after_clicks_enabled": False,
    "stop_after_clicks": 1000,
    "stop_after_minutes_enabled": False,
    "stop_after_minutes": 60,
    "key_timer_jitter_enabled": True,
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
    "hover_zones": [],
    "hover_selection": "random",
    "hover_zone_shape": "rect",
    "hover_enabled": True,
    "hover_frequency": 0.10,
    "hover_dwell_min": 10.0,
    "hover_dwell_max": 20.0,
    "hover_color": "#5b8def",
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
    # AI tab — third top-level mode that runs RS3_AI rule-based bots
    # through PhantomClick's humanizer + Arduino HID keystroke path.
    # ``active_mode`` may now be "clicker" | "recorder" | "ai".
    "ai_bot_slug": "",                        # last-selected library bot
    "ai_tick_rate_hz": 5.0,
    "ai_monitor": 1,                          # mss monitor index (1 = primary)
    "ai_dry_run": False,
    "ai_auto_stop_dry_ticks": 60,
    "ai_watchdog_no_click_s": 600.0,
    "ai_auto_camera": True,
    # Awareness layer ROIs — populated by the AI tab's "Calibrate"
    # buttons. Each is [x, y, w, h] in absolute screen pixels, or None
    # when the user hasn't calibrated yet. Bots that read
    # world().inventory / orbs / minimap should bail gracefully on None.
    "ai_inventory_rect": None,
    "ai_orbs_rect": None,
    "ai_minimap_rect": None,                  # Phase 2 stub — reserved
    # Per-orb saturated-pixel count captured at 100% during the orbs
    # calibration. Keys: "hp", "prayer", "summoning", "run_energy".
    # Empty {} until the user calibrates.
    "ai_orbs_max_fill": {},
    # In-GUI bot authoring (Phase 2 — Custom Bot surface).
    "ai_user_bot_steps": [],                  # list of AIBotStep JSON dicts
    "ai_user_bot_expanded_steps": [],         # which step cards are expanded
    "ai_use_user_bot": False,                 # picker state: True = custom mode
    "ai_user_bot_name": "My Custom Bot",
    "ai_user_bot_tick_rate_hz": 5.0,
    # Per-bot wiki-sourced item library — list of canonical item names
    # like ["Raw trout", "Yew logs"]. Each name has a cached icon at
    # debug/wiki_cache/items/<slug>.png. The framework rebuilds the
    # ItemLibrary at Start time and attaches it to the compiled Bot.
    "ai_user_bot_items": [],
}


def load_config() -> dict:
    p = _config_path()
    cfg = dict(DEFAULTS)
    loaded: dict = {}
    backup_path: Path | None = None
    if p.exists():
        try:
            with p.open("r", encoding="utf-8") as f:
                loaded = json.load(f)
        except json.JSONDecodeError as e:
            # Corrupt JSON — preserve the bad file as a timestamped backup
            # so the user can retrieve any rare-but-real settings, then
            # fall back to defaults. Surface a toast on the next App init
            # via the transient ``_corrupt_backup`` key set below.
            ts = int(time.time())
            backup_path = p.with_name(f"{p.name}.bak.{ts}")
            try:
                p.rename(backup_path)
            except OSError:
                backup_path = None
            _log.warning(
                "config.json corrupt (%s); backed up to %s",
                e, backup_path.name if backup_path else "<rename failed>",
            )
            loaded = {}
        except Exception as e:
            # Non-JSON I/O error — log but don't backup; let the defaults
            # path take over without disturbing the file.
            _log.warning("config.json read failed (%s); using defaults", e)
            loaded = {}
    cfg.update(loaded)

    # Migrate legacy single-toggle hotkey to separate start/stop keys.
    migrated = False
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
    if "customize_open" in cfg:
        cfg.pop("customize_open", None)
        migrated = True
    # 2026 palette refresh: migrate the old defaults so existing users pick up
    # the new accents on next launch. Custom-picked colors are left alone.
    if cfg.get("zone_color") == "#e94560":
        cfg["zone_color"] = "#22d3ee"
        migrated = True
    # Coral → teal accent migration (was the previous default for ~2 weeks).
    if cfg.get("zone_color") == "#ff5470":
        cfg["zone_color"] = "#22d3ee"
        migrated = True
    if cfg.get("hover_color") == "#4a90e2":
        cfg["hover_color"] = "#5b8def"
        migrated = True
    # Anti-cluster radius migration. The previous default (18) and its
    # realism-derived ceiling (up to 30) were shown to push the second
    # of two consecutive clicks past the edge of typical small game
    # buttons. We pull anything > 12 down to 12 once, on the assumption
    # the user accepted the old default rather than tuned it. Users who
    # explicitly want a wider radius can crank it back up in Behavior →
    # Advanced; the runtime zone-aware clamp protects them either way.
    if "anti_cluster_radius" in loaded and int(loaded.get("anti_cluster_radius", 0)) > 12:
        cfg["anti_cluster_radius"] = 12
        migrated = True
    if migrated:
        save_config(cfg)
    # Transient — read once by App init for a corruption toast, then popped.
    if backup_path is not None:
        cfg["_corrupt_backup"] = str(backup_path)
    return cfg


def save_config(cfg: dict) -> None:
    try:
        # Strip transient keys (those starting with _) so they never
        # round-trip to disk. Keeps load_config's transient channel from
        # bleeding into the persisted shape.
        out = {k: v for k, v in cfg.items() if not str(k).startswith("_")}
        with _config_path().open("w", encoding="utf-8") as f:
            json.dump(out, f, indent=4)
    except Exception:
        pass
