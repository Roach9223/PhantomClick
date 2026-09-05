"""Validate persisted settings without importing the GUI or touching disk."""
from __future__ import annotations

import copy
import math
import re


def validate_config(raw: dict, defaults: dict) -> tuple[dict, list[str]]:
    """Keep unknown keys for forwards compatibility; repair invalid known values."""
    result = copy.deepcopy(raw)
    repaired = []
    enums = {
        "active_mode": {"clicker", "recorder", "ai"},
        "ui_shell": {"deck", "classic"},
        "click_type": {"left", "right", "middle"},
        "click_mode": {"single", "double"},
        "zone_shape": {"rect", "circle", "polygon"},
        "hover_zone_shape": {"rect", "circle", "polygon"},
        "zone_lock_default": {"window", "screen"},
        "hover_selection": {"random", "order"},
        "key_input_method": {"auto", "sendinput", "interception", "serial_hid"},
    }
    bounds = {
        "min_delay": (0.01, 86400), "max_delay": (0.01, 86400),
        "realism": (0, 1), "zone_opacity": (0, 1), "hover_opacity": (0, 1),
        "monitor_port": (1, 65535), "monitor_fps": (1, 60),
        "monitor_jpeg_quality": (30, 95), "ai_tick_rate_hz": (0.5, 60),
        "window_w": (320, 32768), "window_h": (240, 32768),
    }
    for key, default in defaults.items():
        if key not in raw:
            continue
        value = raw[key]
        valid = True
        if isinstance(default, bool):
            valid = isinstance(value, bool)
        elif isinstance(default, (int, float)):
            try:
                valid = (not isinstance(value, bool) and isinstance(value, (int, float))
                         and math.isfinite(value))
                if isinstance(default, int):
                    valid = valid and int(value) == value
                lo, hi = bounds.get(key, (0, 2**31 - 1))
                valid = valid and lo <= value <= hi
            except (TypeError, ValueError, OverflowError):
                valid = False
        elif isinstance(default, str):
            valid = isinstance(value, str)
            if key == "target_monitor":
                # Stored as "auto" or the Qt screen index as a string
                # ("1"), which is what the Settings combo and
                # App.set_target_monitor write. A bare int is tolerated.
                valid = (value == "auto"
                         or (isinstance(value, str) and value.isdigit())
                         or (type(value) is int and value >= 0))
            if valid and key in enums:
                valid = value in enums[key]
            if valid and key.endswith("_color"):
                valid = bool(re.fullmatch(r"#[0-9a-fA-F]{6}", value))
        elif isinstance(default, (list, dict)):
            valid = isinstance(value, type(default))
        elif value is not None:
            if key in {"window_x", "window_y"}:
                valid = type(value) is int and abs(value) <= 32768
            elif key == "deck_splitter":
                valid = (isinstance(value, list) and len(value) == 2
                         and all(type(v) is int and 0 < v < 32768 for v in value))
            elif key == "zone":
                from modules.zone_selector import Zone
                try:
                    valid = isinstance(value, dict) and Zone.from_json(value) is not None
                except (TypeError, ValueError, KeyError, OverflowError):
                    valid = False
            elif key.endswith("_rect"):
                if key == "monitor_capture_rect":
                    valid = (isinstance(value, dict) and all(type(value.get(k)) is int
                             for k in ("left", "top", "width", "height"))
                             and value["width"] > 0 and value["height"] > 0)
                else:
                    valid = (isinstance(value, list) and len(value) == 4
                             and all(type(v) is int for v in value)
                             and value[2] > 0 and value[3] > 0)
        if not valid:
            result[key] = copy.deepcopy(default)
            repaired.append(key)

    for key in ("hover_zones", "recorder_steps", "key_timers", "ai_user_bot_steps"):
        if key in result:
            values = [v for v in result[key] if isinstance(v, dict)]
            if len(values) != len(result[key]):
                result[key] = values
                repaired.append(key)
    # One damaged sequence entry must not prevent the rest of the app loading.
    from modules.zone_selector import Zone
    from modules.recorder import RecorderStep
    from modules.key_timer import KeyTimer
    for key, reader in (("hover_zones", Zone.from_json),
                        ("recorder_steps", RecorderStep.from_json),
                        ("key_timers", KeyTimer.from_json)):
        if key not in result:
            continue
        kept = []
        for item in result[key]:
            try:
                if reader(item) is None:
                    raise ValueError("invalid entry")
                kept.append(item)
            except (TypeError, ValueError, KeyError, AttributeError, OverflowError):
                repaired.append(key)
        result[key] = kept
    if "ai_orbs_max_fill" in result:
        values = result["ai_orbs_max_fill"]
        cleaned = {k: v for k, v in values.items() if type(v) is int and v >= 0}
        if cleaned != values:
            result["ai_orbs_max_fill"] = cleaned
            repaired.append("ai_orbs_max_fill")
    for key in ("recorder_expanded_steps", "ai_user_bot_items"):
        if key in result:
            values = [v for v in result[key] if isinstance(v, str)]
            if len(values) != len(result[key]):
                result[key] = values
                repaired.append(key)
    for low, high in (("min_delay", "max_delay"), ("break_min_clicks", "break_max_clicks"),
                      ("break_min_duration", "break_max_duration"), ("hover_dwell_min", "hover_dwell_max")):
        lo, hi = result.get(low, defaults[low]), result.get(high, defaults[high])
        if lo > hi:
            result[low], result[high] = hi, lo
            repaired.extend((low, high))
    return result, sorted(set(repaired))
