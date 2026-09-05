"""Start readiness checks shared by setup feedback and the engine start action."""
from modules.recorder import KIND_CLICK, KIND_TRACK, KIND_COLOR, KIND_PAUSE, KIND_KEY, KIND_LOOP
from ui import config_io


def readiness_message(app) -> str:
    """A short next action for the current mode; empty means ready for preflight."""
    if getattr(app, "_ai_preparing", False):
        return "Preparing bot images. Use Stop or Cancel to cancel startup."
    if app._active_mode == "ai":
        if not app.ai_available:
            return "AI is unavailable. Check the log for the missing component."
        missing = missing_monitor_message(app, "ai")
        if missing:
            return missing
        if not (app.cfg.get("ai_active_bundle") or app.cfg.get("ai_bot_slug")
                or app.cfg.get("ai_use_user_bot")):
            return "Select a bot in the Bot pane before starting."
        if app.cfg.get("ai_use_user_bot") and not app._ai_user_steps:
            return "Add rules to the custom bot before starting."
        return ""
    failures = preflight_failures(app)
    return failures[0].removeprefix("⚠ ") if failures else ""


def missing_monitor_message(app, which: str) -> str:
    """Empty when the chosen monitor for ``which`` ("click" or "ai") is
    attached (or auto / virtual); otherwise the sentence to show."""
    from ui.monitor_identity import describe_identity, resolve_ai, resolve_target
    cfg = app.cfg
    try:
        if which == "ai":
            _idx, status = resolve_ai(cfg)
            identity = cfg.get("ai_monitor_identity")
            where = "the AI page's Monitor list"
            saved = f"MON{int(cfg.get('ai_monitor', 1))}"
        else:
            _idx, status = resolve_target(cfg)
            identity = cfg.get("target_monitor_identity")
            where = "the zone map or Settings"
            saved = f"MON{int(cfg.get('target_monitor', 0)) + 1}"
    except Exception:
        return ""
    if status != "missing":
        return ""
    label = describe_identity(identity) if identity else saved
    return (f"Saved monitor {label} is not connected. Pick a monitor in "
            f"{where}, or choose Auto.")


def preflight_failures(app) -> list[str]:
    """Return a list of user-facing strings describing why the engine
    can't start right now. Empty list = green-light. Toasts come from
    ``_on_start`` which posts one per item. Designed so future checks
    can be added without touching the start path itself.
    """
    import os
    failures: list[str] = []
    # A saved monitor that is not attached is a hard stop: falling back
    # to an index would click on whatever screen sits there now.
    missing = missing_monitor_message(app, "click")
    if missing:
        failures.append("⚠ " + missing)
    # Hotkey conflict, covers the case where an external edit slipped
    # past the rebind validator (e.g. config.json hand-edit).
    seen: dict[str, str] = {}
    for k, v in app.cfg.items():
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

    if app._active_mode == "recorder":
        if not app._steps:
            failures.append("⚠ Record mode has no steps. Add a Click / Track / Color / Key step.")
        else:
            runnable = False
            for i, s in enumerate(app._steps):
                if not s.enabled:
                    continue
                user_label = (getattr(s, "label", "") or "").strip()
                label = (f"step {i + 1} '{user_label}'" if user_label
                         else f"step {i + 1}")
                if s.kind == KIND_CLICK:
                    if s.zone is None:
                        failures.append(f"⚠ Click {label} has no zone, draw one or remove the step.")
                        continue
                    runnable = True
                elif s.kind == KIND_TRACK:
                    if not s.template_path:
                        failures.append(f"⚠ Track {label} has no captured template.")
                        continue
                    # Resolve relative to install root (mirrors _read_template_png).
                    path = s.template_path
                    if not os.path.isabs(path):
                        path = os.path.join(config_io._config_dir(), path)
                    if not os.path.exists(path):
                        failures.append(
                            f"⚠ Track {label} template missing on disk, recapture to fix."
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
                elif s.kind == KIND_KEY:
                    from modules.key_timer import parse_combo
                    if not s.key_combo or parse_combo(s.key_combo) is None:
                        failures.append(f"⚠ Key {label} needs a valid key combination.")
                    else:
                        runnable = True
                elif s.kind == KIND_LOOP:
                    target = next((j for j, other in enumerate(app._steps)
                                   if other.step_id == s.loop_target_step_id), None)
                    if target is None or target >= i:
                        failures.append(f"⚠ Loop {label} needs an earlier target step.")
                else:
                    # Loop / unknown, handled in engine; not a pre-flight failure.
                    pass
            if not runnable:
                failures.append(
                    "⚠ Record mode needs a runnable Click / Track / Color / Key step."
                )
    else:
        if app._zone is None:
            failures.append("⚠ Click mode has no zone. Press 'Draw area' first.")
        else:
            # Sanity: zone AABB intersects the virtual desktop at all.
            # Uses the union of every screen (origin may be negative)
            # so a zone on a secondary monitor isn't rejected.
            x1, y1, x2, y2 = app._zone.aabb()
            vx, vy, vw, vh = app.virtual_rect
            if x2 < vx or y2 < vy or x1 > vx + vw or y1 > vy + vh:
                failures.append(
                    "⚠ Click zone is entirely off-screen "
                    "(maybe resolution changed). Redraw it."
                )

    # Keystrokes need a working backend. Only enforced when the run
    # would actually press keys, so a plain Click session on a machine
    # without the Arduino still starts.
    if app._sequence_uses_keys():
        ok, msg = app.key_backend_status()
        if not ok:
            failures.append(
                f"⚠ Key input method unavailable: {msg}. Fix it under "
                "Settings, Input, or disable the key steps / timers."
            )
    return failures

