"""Shared monitor / screen enumeration helpers.

Both the Monitor card and the Settings page render the user's attached
screens as a friendly label list. This module is the single source of
truth for that label, extracted from prior duplicates that had drifted
apart (the Monitor copy never normalized 3-letter EDID codes like
``"AUS"`` to brand names, so identical hardware rendered differently
between tabs).
"""

from __future__ import annotations


# EDID manufacturer codes → human display names. EDID stores 3-letter
# PNPID-style codes ("AUS" = ASUSTek, "GSM" = LG, etc.) that mean nothing
# to a normal user; this map normalizes the common ones to brand strings
# users actually recognize.
_KNOWN_BRANDS = {
    "aus": "ASUS", "asus": "ASUS", "asustek": "ASUS",
    "gsm": "LG", "lg": "LG", "lge": "LG",
    "sam": "Samsung", "samsung": "Samsung",
    "del": "Dell", "dell": "Dell",
    "aoc": "AOC",
    "ben": "BenQ", "benq": "BenQ",
    "acr": "Acer", "acer": "Acer",
    "msi": "MSI",
    "gbt": "Gigabyte", "gigabyte": "Gigabyte",
    "len": "Lenovo", "lenovo": "Lenovo",
    "vsc": "ViewSonic", "viewsonic": "ViewSonic",
    "hwp": "HP", "hp": "HP",
    "phl": "Philips", "philips": "Philips",
}


def screen_label(screen, *, index: int | None = None,
                 is_primary: bool | None = None) -> str:
    """Build a human-readable label for a Qt ``QScreen``.

    Headline name priority: EDID ``model()`` (e.g. ``PG32UCDM``), then
    ``name()`` (typically ``\\\\.\\DISPLAY1`` on Windows), then
    ``Monitor N``. Manufacturer is normalized through ``_KNOWN_BRANDS``
    and prefixed only when it isn't already implied by the model.
    Resolution always appended; ``is_primary=True`` adds a ``· primary``
    tag.
    """
    model = (screen.model() or "").strip()
    name = (screen.name() or "").strip()
    manu = (screen.manufacturer() or "").strip()

    if model:
        head = model
    elif name:
        head = name
    elif index is not None:
        head = f"Monitor {index + 1}"
    else:
        head = "Monitor"

    if manu:
        short = manu.split()[0].rstrip(",")
        short_lc = short.lower()
        if short_lc in _KNOWN_BRANDS:
            short = _KNOWN_BRANDS[short_lc]
        elif len(short) < 3:
            short = ""  # drop "on" and other short noise
        if short and short.lower() not in head.lower():
            head = f"{short} {head}"

    g = screen.geometry()
    tag = " · primary" if is_primary else ""
    return f"{head} · {g.width()}×{g.height()}{tag}"


# ── Virtual-screen geometry ─────────────────────────────────────────────────
#
# Multi-monitor helpers used by the preflight zone check, the tracker
# preview loop, and the zone thumbnails. Everything below works in Qt's
# DIP space unless the name says physical; physical rects come from
# ``utils.dpi_cursor`` so the whole app shares one conversion path.


def screens() -> list:
    from PySide6.QtGui import QGuiApplication
    app = QGuiApplication.instance()
    if app is None:
        return []
    return list(app.screens() or [])


def virtual_screen_dip_rect() -> tuple[int, int, int, int]:
    """``(x, y, w, h)`` union of every attached screen, DIP space.

    Origins can be negative when a secondary monitor sits left of or above
    the primary. Falls back to a 1920x1080 primary when Qt has no screens
    (headless / offscreen tests).
    """
    scr = screens()
    if not scr:
        return (0, 0, 1920, 1080)
    left = min(s.geometry().left() for s in scr)
    top = min(s.geometry().top() for s in scr)
    right = max(s.geometry().left() + s.geometry().width() for s in scr)
    bottom = max(s.geometry().top() + s.geometry().height() for s in scr)
    return (left, top, right - left, bottom - top)


def screen_at_dip(x: float, y: float):
    """QScreen containing DIP point ``(x, y)``, else the primary screen,
    else None (no screens attached)."""
    from PySide6.QtCore import QPoint
    from PySide6.QtGui import QGuiApplication
    app = QGuiApplication.instance()
    if app is None:
        return None
    s = None
    try:
        s = app.screenAt(QPoint(int(x), int(y)))
    except Exception:
        s = None
    return s or app.primaryScreen()


def screen_physical_rect(screen) -> tuple[int, int, int, int]:
    """``(x, y, w, h)`` of one QScreen in physical pixels."""
    from utils.dpi_cursor import dip_rect_to_physical
    g = screen.geometry()
    return dip_rect_to_physical(g.left(), g.top(), g.width(), g.height())


def zone_screen_info(zone) -> tuple[str, tuple[int, int], tuple[int, int]]:
    """``(label, (w, h), (origin_x, origin_y))`` for the screen that holds
    ``zone``'s centroid, so thumbnails draw the zone relative to its own
    monitor instead of assuming everything lives on the primary at (0, 0).
    Without a zone the primary screen is described."""
    from PySide6.QtGui import QGuiApplication
    app = QGuiApplication.instance()
    primary = app.primaryScreen() if app is not None else None
    screen = primary
    if zone is not None:
        try:
            cx, cy = zone.centroid()
            screen = screen_at_dip(cx, cy) or primary
        except Exception:
            screen = primary
    if screen is None:
        return ("", (0, 0), (0, 0))
    g = screen.geometry()
    is_primary = screen is primary
    label = f"{g.width()} × {g.height()}" + (" · primary" if is_primary else "")
    return (label, (int(g.width()), int(g.height())), (int(g.left()), int(g.top())))
