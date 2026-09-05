"""Resolve a window-locked Zone to where it sits right now.

A ``Zone`` with a ``WindowLock`` stores its geometry relative to the
window rect captured at draw time. Every consumer that needs screen
coordinates (the engine before a click, the overlays, the deck) calls
:func:`resolve` and works with the returned zone instead of the stored
one. Screen-locked zones pass straight through with status ``"screen"``.

The lookup is a couple of Win32 calls per resolve: an ``IsWindow`` plus a
rect read when the cached hwnd is still valid, a full ``EnumWindows``
only when the cache misses. Cheap enough to run before every click; UI
callers should still go through :class:`LockResolver`, which throttles
to about 10 Hz per key so four panels polling on one tick share a result.

GUI-free. Everything that touches Win32 lives in ``utils.window_finder``
and is reached through the module reference so tests can monkeypatch it.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Optional

from utils import dpi_cursor
from utils import window_finder as _wf
from .zone_selector import Zone, WindowLock

STATUS_SCREEN = "screen"
STATUS_LOCKED = "locked"
STATUS_LOST = "lost"
STATUS_MINIMIZED = "minimized"

HOLD_STATUSES = (STATUS_LOST, STATUS_MINIMIZED)


@dataclass(frozen=True)
class ResolvedZone:
    zone: Zone
    status: str                       # screen | locked | lost | minimized
    window: Optional[_wf.WindowInfo]

    @property
    def title(self) -> Optional[str]:
        if self.window is not None and self.window.title:
            return self.window.title
        if self.zone is not None and self.zone.lock is not None:
            return self.zone.lock.title or None
        return None

    @property
    def holding(self) -> bool:
        return self.status in HOLD_STATUSES


def _title_matches(current: str, wanted: str) -> bool:
    """Same tolerance as ``find_window``: exact, or a case-insensitive
    substring either way. Game titles append the character name; browser
    tabs prepend the page. Both still count as the same window."""
    if current == wanted:
        return True
    a = (current or "").lower()
    b = (wanted or "").lower()
    if not a or not b:
        return False
    return a in b or b in a


def resolve(zone: Optional[Zone], cache: dict) -> ResolvedZone:
    """Return ``zone`` translated to the locked window's current rect.

    ``cache`` maps ``(title, cls)`` to the last hwnd so the common path
    skips the window enumeration. A cached hwnd is trusted for as long as
    it names a live window of the locked class, even when its title has
    changed: games rewrite the title bar on login, world hop and loading
    screens, and dropping the lock for that would read as TARGET LOST
    mid-session. The lock's title is updated to follow the window so a
    later re-enumeration (after the hwnd really dies) searches for the
    name it last had. Only a dead hwnd or a class mismatch (the handle
    was recycled by another program) triggers a new ``find_window``.
    """
    if zone is None or zone.lock is None:
        return ResolvedZone(zone, STATUS_SCREEN, None)  # type: ignore[arg-type]
    lock: WindowLock = zone.lock
    key = (lock.title, lock.cls)

    info: Optional[_wf.WindowInfo] = None
    hwnd = cache.get(key)
    if hwnd is not None:
        if _wf.is_window(hwnd):
            info = _wf.window_info(hwnd)
        if info is None or info.cls != lock.cls:
            cache.pop(key, None)
            info = None
        elif info.title != lock.title and info.title:
            # WindowLock is frozen because it is hashed and compared as a
            # value; the title is the one field that is a lookup hint
            # rather than identity, so it is the one field we let track
            # the live window. Re-key the cache to match.
            cache.pop(key, None)
            object.__setattr__(lock, "title", info.title)
            key = (lock.title, lock.cls)
            cache[key] = hwnd
    if info is None:
        info = _wf.find_window(lock.title, lock.cls)
        if info is None:
            return ResolvedZone(zone, STATUS_LOST, None)
        cache[key] = info.hwnd
    if _wf.is_minimized(info.hwnd):
        return ResolvedZone(zone, STATUS_MINIMIZED, info)
    rect = _wf.window_rect_dip(info.hwnd) or info.rect_dip
    if not rect or rect[2] <= 0 or rect[3] <= 0:
        return ResolvedZone(zone, STATUS_LOST, info)
    return ResolvedZone(zone.rebased(tuple(int(v) for v in rect)), STATUS_LOCKED, info)


class LockResolver:
    """Per-thread resolve() wrapper with an hwnd cache and a rate limit.

    ``max_hz <= 0`` disables throttling (the engine wants a fresh answer
    every time). With a limit, repeated calls for the same ``key`` inside
    one period return the previous result, which is how the deck's four
    panels share one Win32 round trip per tick.
    """

    def __init__(self, max_hz: float = 10.0) -> None:
        self.cache: dict = {}
        self._min_gap = (1.0 / max_hz) if max_hz > 0 else 0.0
        self._last: dict[object, tuple[float, int, ResolvedZone]] = {}
        self._last_good: dict[object, tuple[int, Zone]] = {}

    def resolve(self, zone: Optional[Zone], key: object = None) -> ResolvedZone:
        if self._min_gap > 0 and key is not None:
            hit = self._last.get(key)
            # id() guards against a redrawn zone reusing the key within
            # the same period and being shown at the old position.
            if hit is not None and hit[1] == id(zone) and time.monotonic() - hit[0] < self._min_gap:
                return hit[2]
        res = resolve(zone, self.cache)
        if key is not None:
            if res.holding:
                # Display surfaces keep drawing the last place the window
                # was seen rather than snapping back to the draw-time
                # geometry, which would be a lie about where clicks go.
                good = self._last_good.get(key)
                if good is not None and good[0] == id(zone):
                    res = ResolvedZone(good[1], res.status, res.window)
            elif res.status == STATUS_LOCKED:
                self._last_good[key] = (id(zone), res.zone)
            self._last[key] = (time.monotonic(), id(zone), res)
        return res

    def forget(self, key: object) -> None:
        self._last.pop(key, None)
        self._last_good.pop(key, None)


def attach_window_lock(zone: Zone) -> Zone:
    """Return ``zone`` locked to the top-level window under its centre, or
    the unchanged zone when nothing lockable is there (bare desktop, our
    own window only). The centre is converted from DIPs to physical
    pixels because ``WindowFromPoint`` speaks physical.
    """
    if zone is None:
        return zone
    # An already-locked zone stores anchor-relative geometry; re-anchor
    # from where it currently sits on screen, falling back to the stored
    # geometry when the old window is gone.
    base = resolve(zone, {}).zone if zone.lock is not None else zone
    base = base.with_lock(None)
    try:
        cx, cy = base.centroid()
        px, py = dpi_cursor.dip_to_physical(cx, cy)
        info = _wf.window_at_point(px, py)
    except Exception:
        info = None
    if info is None or not info.rect_dip or info.rect_dip[2] <= 0:
        return base
    return base.with_lock(WindowLock(
        title=info.title, cls=info.cls,
        anchor_rect=tuple(int(v) for v in info.rect_dip),  # type: ignore[arg-type]
    ))


def retarget_lock(zone: Zone, info) -> Zone:
    """Lock ``zone`` to the window ``info`` describes (anything with
    ``title``, ``cls`` and ``rect_dip``).

    A zone already locked to another window keeps its place *relative to
    that window*: it is scaled and translated from the old anchor into
    the new window's rect, so switching from one game client to another
    lands the clicks on the same corner of the new one. An unlocked zone
    keeps its screen position and simply gains the new anchor.
    """
    if zone is None or info is None:
        return zone
    rect = tuple(int(v) for v in (getattr(info, "rect_dip", None) or ()))
    if len(rect) != 4 or rect[2] <= 0 or rect[3] <= 0:
        return zone
    lock = WindowLock(title=str(getattr(info, "title", "") or ""),
                      cls=str(getattr(info, "cls", "") or ""),
                      anchor_rect=rect)  # type: ignore[arg-type]
    if zone.lock is not None:
        return zone.rebased(rect).with_lock(lock)
    return zone.with_lock(lock)


def apply_lock_mode(zone: Zone, mode: str) -> Zone:
    """Switch a zone between screen and window lock.

    ``"window"`` re-anchors to whatever window currently sits under the
    zone centre. ``"screen"`` drops the lock and pins the zone where it
    currently shows (the stored geometry when the window is gone).
    """
    if zone is None:
        return zone
    if mode == "window":
        return attach_window_lock(zone)
    if zone.lock is not None:
        zone = resolve(zone, {}).zone
    return zone.with_lock(None)
