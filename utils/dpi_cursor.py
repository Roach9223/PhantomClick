"""DPI-aware cursor wrapper.

The engine works in **DIPs** (virtual desktop logical pixels) — that's
what Qt stores in zones, what the drawer captures, and what every UI
overlay paints with. The Win32 cursor APIs (``SetCursorPos`` /
``GetCursorPos``) operate in **physical pixels** when the process is
per-monitor-v2 DPI aware. On a 150% monitor that's a 1.5× mismatch:
``SetCursorPos(1000, 500)`` lands at DIP (667, 333), not (1000, 500).

This module bridges both directions so the engine can keep its DIPs
abstraction:

* :func:`set_pos` accepts DIPs, converts to physical, calls SetCursorPos.
* :func:`get_pos` reads physical via GetCursorPos, returns DIPs.

Conversion uses a cached snapshot of each screen's DIP rect, DPR, and
physical origin captured by :func:`refresh_screens` (call from the Qt
main thread at app init / screen change).
"""

from __future__ import annotations

import ctypes
from ctypes import wintypes
from typing import Optional


# -- Win32 plumbing ---------------------------------------------------------

_user32 = ctypes.windll.user32


class _RECT(ctypes.Structure):
    _fields_ = [
        ("left", ctypes.c_long),
        ("top", ctypes.c_long),
        ("right", ctypes.c_long),
        ("bottom", ctypes.c_long),
    ]


class _MONITORINFO(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.DWORD),
        ("rcMonitor", _RECT),
        ("rcWork", _RECT),
        ("dwFlags", wintypes.DWORD),
    ]


class _POINT(ctypes.Structure):
    _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]


_MONITORENUMPROC = ctypes.WINFUNCTYPE(
    ctypes.c_int,
    ctypes.c_void_p,
    ctypes.c_void_p,
    ctypes.POINTER(_RECT),
    ctypes.c_void_p,
)


def _enum_physical_monitors() -> list[tuple[int, int, int, int]]:
    """Return each monitor's physical pixel rect (left, top, right, bottom)."""
    out: list[tuple[int, int, int, int]] = []

    def _cb(hmon, hdc, lprect, data):
        info = _MONITORINFO()
        info.cbSize = ctypes.sizeof(_MONITORINFO)
        if _user32.GetMonitorInfoW(hmon, ctypes.byref(info)):
            r = info.rcMonitor
            out.append((r.left, r.top, r.right, r.bottom))
        return 1

    _user32.EnumDisplayMonitors(None, None, _MONITORENUMPROC(_cb), 0)
    return out


# -- Screen cache ----------------------------------------------------------

# Each entry: dict(dip_rect=(l,t,r,b), dpr=float, physical_origin=(x,y))
_SCREENS: list[dict] = []


def refresh_screens() -> None:
    """Snapshot Qt screens + Win32 monitors. Call from the Qt main thread.

    Matches Qt screens to Win32 monitors by comparing each Qt screen's DIP
    size × DPR against the Win32 ``rcMonitor`` size (which is in physical
    pixels). For dual monitors with the same physical resolution this
    falls back to assuming the DIP origin equals the physical origin
    (true on DPR=1 screens or when Qt and Win32 agree on monitor
    ordering).
    """
    try:
        from PySide6.QtWidgets import QApplication
    except Exception:
        return
    app = QApplication.instance()
    if app is None:
        return
    physical = _enum_physical_monitors()
    out: list[dict] = []
    for screen in app.screens():
        g = screen.geometry()  # DIPs in virtual desktop
        dpr = float(screen.devicePixelRatio())
        target_w = round(g.width() * dpr)
        target_h = round(g.height() * dpr)
        match: Optional[tuple[int, int]] = None
        # Match by physical size first (most reliable for distinct monitors).
        for (l, t, r, b) in physical:
            if abs((r - l) - target_w) <= 2 and abs((b - t) - target_h) <= 2:
                match = (l, t)
                break
        if match is None:
            # Fallback: same as DIP origin (correct for DPR=1).
            match = (g.left(), g.top())
        out.append({
            "dip_rect": (g.left(), g.top(),
                         g.left() + g.width(), g.top() + g.height()),
            "dpr": dpr,
            "physical_origin": match,
        })
    _SCREENS.clear()
    _SCREENS.extend(out)


def _screen_for_dip(x: float, y: float) -> Optional[dict]:
    # Interior check (strict less-than on the right/bottom).
    for s in _SCREENS:
        l, t, r, b = s["dip_rect"]
        if l <= x < r and t <= y < b:
            return s
    # Boundary fallback — points exactly on the right/bottom edge of a
    # screen are still "of" that screen for conversion purposes. Without
    # this, edge points (e.g. the bottom-right corner of a rect drawn to
    # the screen edge) hit the identity-fallback in dip_to_physical and
    # produce a mangled physical-space rect. Bug surfaced when an mss
    # capture clipped to 2560×1440 of a 3840×2160 monitor — the bottom-
    # right geom corner fell outside any _SCREENS entry.
    for s in _SCREENS:
        l, t, r, b = s["dip_rect"]
        if l <= x <= r and t <= y <= b:
            return s
    return None


def _screen_for_physical(x: float, y: float) -> Optional[dict]:
    for s in _SCREENS:
        ox, oy = s["physical_origin"]
        l, t, r, b = s["dip_rect"]
        dpr = s["dpr"]
        w = round((r - l) * dpr)
        h = round((b - t) * dpr)
        if ox <= x < ox + w and oy <= y < oy + h:
            return s
    return None


# -- Public API -------------------------------------------------------------


def dip_to_physical(x: float, y: float) -> tuple[int, int]:
    """Convert a virtual-desktop DIP point to a physical pixel point.

    Falls back to the input on lookup failure (e.g. point outside any
    known screen, or cache empty). On DPR=1 screens this is a no-op.
    """
    s = _screen_for_dip(x, y)
    if s is None:
        return (int(round(x)), int(round(y)))
    l, t, _r, _b = s["dip_rect"]
    dpr = s["dpr"]
    ox, oy = s["physical_origin"]
    px = ox + (x - l) * dpr
    py = oy + (y - t) * dpr
    return (int(round(px)), int(round(py)))


def dip_rect_to_physical(
    x: float, y: float, w: float, h: float,
) -> tuple[int, int, int, int]:
    """Convert a DIP rect to a physical-pixel rect on the same screen.

    Uses the rect's CENTER for screen lookup — that's guaranteed to be
    in the screen's interior even when the rect's bottom-right corner
    is exactly on the screen edge (where ``dip_to_physical`` would
    otherwise fall back to identity and produce a wrong-sized physical
    rect on a DPR≠1 screen).

    Returns ``(px, py, pw, ph)`` in physical pixels. Falls back to
    identity (the input cast to ints) on lookup failure, just like
    ``dip_to_physical``.
    """
    cx = x + w / 2.0
    cy = y + h / 2.0
    s = _screen_for_dip(cx, cy)
    if s is None:
        return (int(round(x)), int(round(y)), int(round(w)), int(round(h)))
    l, t, _r, _b = s["dip_rect"]
    dpr = s["dpr"]
    ox, oy = s["physical_origin"]
    px = ox + (x - l) * dpr
    py = oy + (y - t) * dpr
    pw = w * dpr
    ph = h * dpr
    return (
        int(round(px)), int(round(py)),
        int(round(pw)), int(round(ph)),
    )


def physical_to_dip(x: float, y: float) -> tuple[int, int]:
    """Convert a physical pixel point to virtual-desktop DIPs."""
    s = _screen_for_physical(x, y)
    if s is None:
        return (int(round(x)), int(round(y)))
    l, t, _r, _b = s["dip_rect"]
    dpr = s["dpr"]
    ox, oy = s["physical_origin"]
    dx = l + (x - ox) / dpr
    dy = t + (y - oy) / dpr
    return (int(round(dx)), int(round(dy)))


def set_pos(x: float, y: float) -> None:
    """Set the cursor to a DIP point (engine's coordinate space)."""
    px, py = dip_to_physical(x, y)
    _user32.SetCursorPos(int(px), int(py))
    # Trace every cursor write at the chokepoint so every caller (move,
    # drift, jitter, post-click wander) is captured uniformly. Lazy
    # import to avoid a hard dep cycle and a no-op fast-path inside
    # mouse_trace itself when tracing is off.
    try:
        from . import mouse_trace as _mt
        if _mt.is_enabled():
            _mt.event("set", x=int(round(x)), y=int(round(y)),
                      px=int(px), py=int(py))
    except Exception:
        pass


def set_pos_physical(x: float, y: float) -> None:
    """Set the cursor to a *physical* (Win32) pixel coord.

    Bypasses DIP conversion. Use this when the caller has already
    resolved coordinates to physical px — most importantly the
    humanizer's path walker, which generates Wind/Hooke / Bezier paths
    in physical-px space so that a path crossing two monitors with
    different DPRs stays smooth (DIP-space paths teleport at the
    bezel because DIPs aren't uniform across monitors with mixed DPI).
    """
    _user32.SetCursorPos(int(x), int(y))
    try:
        from . import mouse_trace as _mt
        if _mt.is_enabled():
            # Provide DIP equivalent for analysis convenience so the
            # trace stays comparable to set_pos events.
            dx, dy = physical_to_dip(x, y)
            _mt.event("set", x=int(round(dx)), y=int(round(dy)),
                      px=int(round(x)), py=int(round(y)))
    except Exception:
        pass


def get_pos() -> tuple[int, int]:
    """Return the cursor's current position in DIPs."""
    pt = _POINT()
    _user32.GetCursorPos(ctypes.byref(pt))
    out = physical_to_dip(pt.x, pt.y)
    try:
        from . import mouse_trace as _mt
        if _mt.is_enabled():
            _mt.event("get", x=out[0], y=out[1], px=int(pt.x), py=int(pt.y))
    except Exception:
        pass
    return out


def get_pos_physical() -> tuple[int, int]:
    """Return the cursor's current position in physical Win32 pixels.

    Sister to :func:`set_pos_physical` for the humanizer path walker.
    """
    pt = _POINT()
    _user32.GetCursorPos(ctypes.byref(pt))
    return (int(pt.x), int(pt.y))
