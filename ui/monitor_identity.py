"""Persist screen identity; Qt and MSS indices are independent fallbacks."""
from __future__ import annotations


def screen_identity(screen):
    g = screen.geometry()
    return {
        "name": screen.name() or "",
        "serial": screen.serialNumber() or "",
        "model": screen.model() or "",
        "geometry": [g.x(), g.y(), g.width(), g.height()],
    }


def match_strict(identity, candidates):
    """Index whose screen identity uniquely matches ``identity``, or
    None. No fallback of any kind lives here."""
    if not (isinstance(identity, dict) and identity):
        return None

    def unique(keys):
        if not all(identity.get(k) for k in keys):
            return None
        matches = [i for i, item in candidates.items()
                   if all(item.get(k) == identity[k] for k in keys)]
        return matches[0] if len(matches) == 1 else None

    for keys in (("serial", "model"), ("name", "geometry"),
                 ("model", "geometry"), ("model",), ("name",), ("geometry",)):
        found = unique(keys)
        if found is not None:
            return found
    return None


def match_identity(identity, candidates, fallback):
    """Prefer unique hardware identity, then name/geometry, then old index,
    then the first attached screen. Display-only convenience; anything
    that acts on the screen goes through :func:`identity_status`.

    candidates maps each API's own index to a JSON screen identity.
    Never overwrite a saved identity on an index fallback (unplug/replug).
    """
    found = match_strict(identity, candidates)
    if found is not None:
        return found
    return fallback if fallback in candidates else next(iter(candidates), None)


def describe_identity(identity) -> str:
    """Human label for a saved identity: ``LG ULTRAWIDE 3440x1440``."""
    if not isinstance(identity, dict) or not identity:
        return "unknown screen"
    name = identity.get("model") or identity.get("name") or "screen"
    g = identity.get("geometry") or []
    size = f" {g[2]}x{g[3]}" if len(g) == 4 else ""
    return f"{name}{size}"


def identity_status(identity, candidates, fallback):
    """``(index, status)`` without a silent fallback.

    ``"ok"``: the saved identity matches one attached screen.
    ``"legacy"``: no identity saved yet, the old index still exists.
    ``"missing"``: an identity is saved but no attached screen matches
    (index None), or there is no identity and the index is gone. Callers
    that act on the screen (start, capture) must treat missing as a
    refusal, never as "use whatever is there".
    """
    if isinstance(identity, dict) and identity:
        idx = match_strict(identity, candidates)
        if idx is not None:
            return idx, "ok"
        return None, "missing"
    if fallback in candidates:
        return fallback, "legacy"
    return None, "missing"


def qt_candidates():
    from ui.screen_utils import screens
    return {i: screen_identity(screen) for i, screen in enumerate(screens())}


def resolve_target(cfg):
    """``(qt_index or None, status)`` for the Click / Record monitor.
    Status is ``"auto"``, ``"ok"``, ``"legacy"`` or ``"missing"``."""
    value = cfg.get("target_monitor", "auto")
    if str(value) == "auto":
        return None, "auto"
    try:
        fallback = int(value)
    except (TypeError, ValueError):
        fallback = -1
    return identity_status(cfg.get("target_monitor_identity"), qt_candidates(), fallback)


def target_index(cfg):
    """Qt index of the chosen monitor, or None for auto AND for a saved
    monitor that is not attached: a missing screen must never resolve
    to a different one, so the deck shows auto and readiness refuses
    to start until the user reselects."""
    idx, _status = resolve_target(cfg)
    return idx


def select_target(cfg, value):
    if value in (None, "auto"):
        cfg["target_monitor"] = "auto"
        cfg["target_monitor_identity"] = {}
        return
    idx = int(value)
    candidates = qt_candidates()
    if idx not in candidates:
        raise ValueError("Selected monitor is no longer connected")
    cfg["target_monitor"] = str(idx)
    cfg["target_monitor_identity"] = candidates[idx]


def mss_candidates(monitors):
    from ui.screen_utils import screens, screen_physical_rect
    attached = [(screen_identity(s), tuple(screen_physical_rect(s))) for s in screens()]
    result = {}
    for i, mon in enumerate(monitors):
        if i == 0:  # MSS virtual desktop is not a physical screen.
            continue
        rect = tuple(int(mon[k]) for k in ("left", "top", "width", "height"))
        matched = [identity for identity, physical in attached if physical == rect]
        result[i] = matched[0] if len(matched) == 1 else {"geometry": list(rect)}
    return result


def resolve_ai(cfg, monitors=None):
    """``(mss_index or None, status)`` for the AI capture monitor.
    Status is ``"virtual"`` (index 0), ``"ok"``, ``"legacy"`` or ``"missing"``."""
    try:
        fallback = int(cfg.get("ai_monitor", 1))
    except (TypeError, ValueError):
        fallback = 1
    if fallback == 0:
        return 0, "virtual"
    if monitors is None:
        import mss
        with mss.mss() as source:
            monitors = source.monitors
    return identity_status(cfg.get("ai_monitor_identity"), mss_candidates(monitors), fallback)


def ai_index(cfg, monitors=None):
    """MSS index for capture tools. A missing screen returns 0 (the
    virtual desktop) so a capture tool still has a frame; the bot start
    path checks :func:`resolve_ai` and refuses on ``"missing"``."""
    idx, _status = resolve_ai(cfg, monitors)
    return 0 if idx is None else idx


def select_ai(cfg, value, monitors=None):
    idx = int(value)
    if idx == 0:
        cfg["ai_monitor"] = 0
        cfg["ai_monitor_identity"] = {}
        return
    if monitors is None:
        import mss
        with mss.mss() as source:
            monitors = source.monitors
    candidates = mss_candidates(monitors)
    if idx not in candidates:
        raise ValueError("Selected capture monitor is no longer connected")
    cfg["ai_monitor"] = idx
    cfg["ai_monitor_identity"] = candidates[idx]


def remember_legacy(cfg):
    """Attach identity in memory only; the normal config save persists it.

    Existing identities survive fallback so reconnecting restores the choice.
    """
    if not cfg.get("target_monitor_identity") and str(cfg.get("target_monitor", "auto")) != "auto":
        idx = target_index(cfg)
        if idx is not None:
            cfg["target_monitor_identity"] = qt_candidates()[idx]
    if not cfg.get("ai_monitor_identity") and int(cfg.get("ai_monitor", 1)) != 0:
        try:
            import mss
            with mss.mss() as source:
                candidates = mss_candidates(source.monitors)
            idx = int(cfg.get("ai_monitor", 1))
            if idx in candidates:
                cfg["ai_monitor_identity"] = candidates[idx]
        except Exception:
            pass  # Capture readiness handles unavailable MSS; preserve config.
