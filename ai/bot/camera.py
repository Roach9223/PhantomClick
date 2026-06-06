"""Camera control — zoom, rotate, pitch.

A module-level API (like :mod:`rs3vision_studio.bot.api` for clicks
and waits) so rule bodies can just call ``camera.zoom_in(3)`` without
plumbing a context around.

Maps high-level concepts onto the humanized input backend:

- ``zoom_in/out`` → ``backend.scroll(dy)``.
- ``rotate_left/right`` → ``backend.drag(start, end, "middle")``
  with horizontal delta = ``degrees * PIXELS_PER_DEGREE``.
- ``pitch_up/down`` → same drag but vertical delta.

Calibration constants live at module level; users can override by
assigning to ``camera.PIXELS_PER_DEGREE`` before ``bot.run()``.
"""

from __future__ import annotations

from typing import Tuple

from . import api as _api


# ─────────────────────────────────────────────────────────────────
# Calibration — tune these if RS3 camera sensitivity is non-default
# ─────────────────────────────────────────────────────────────────

# Middle-mouse drag distance (in pixels) that produces one degree of
# camera rotation at RS3 default sensitivity on a 3840-wide monitor.
# Empirically ~10; users can override by assigning a new value to
# ``camera.PIXELS_PER_DEGREE`` in their bot script before ``bot.run()``.
PIXELS_PER_DEGREE = 10.0

# Scroll notches → zoom step. One wheel notch in RS3 is typically one
# "zoom tick". No tuning needed for most users.
ZOOM_NOTCH = 1


# ─────────────────────────────────────────────────────────────────
# Internal helpers
# ─────────────────────────────────────────────────────────────────


def _viewport_center() -> Tuple[int, int]:
    """Return a point safely inside the game viewport to anchor drags.

    Best effort: the default target monitor's geometry centre minus a
    small offset away from the minimap (top-right UI).
    """
    try:
        import mss
        ctx = _api._ctx()
        mon_idx = int(getattr(ctx, "default_monitor", 1))
        with mss.mss() as sct:
            mons = list(sct.monitors)
            if 0 <= mon_idx < len(mons):
                m = mons[mon_idx]
                cx = int(m["left"]) + int(m["width"]) // 2
                cy = int(m["top"]) + int(m["height"]) // 2
                # Nudge slightly away from minimap (top-right) and
                # chatbox (bottom-left).
                return (cx - 100, cy - 50)
    except Exception:
        pass
    return (960, 540)


def _drag_delta(dx: int, dy: int) -> None:
    """Perform a middle-click drag of ``(dx, dy)`` pixels from viewport centre."""
    ctx = _api._ctx()
    cx, cy = _viewport_center()
    start = (cx, cy)
    end = (cx + int(dx), cy + int(dy))
    if getattr(ctx, "dry_run", False):
        ctx.log(f"🧪 [dry-run] camera drag {start} → {end}")
        return
    try:
        ctx.input_backend.drag(start, end, button="middle")
    except NotImplementedError as e:
        ctx.log(f"[camera] drag unavailable: {e}")


def _scroll(notches: int) -> None:
    ctx = _api._ctx()
    if getattr(ctx, "dry_run", False):
        ctx.log(f"🧪 [dry-run] camera scroll {notches:+d}")
        return
    try:
        ctx.input_backend.scroll(notches)
    except NotImplementedError as e:
        ctx.log(f"[camera] scroll unavailable: {e}")


# ─────────────────────────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────────────────────────


def zoom_in(ticks: int = 3) -> None:
    """Scroll up ``ticks`` wheel notches — zooms the RS3 camera in."""
    if ticks <= 0:
        return
    _scroll(int(ticks) * int(ZOOM_NOTCH))
    _api._ctx().log(f"🎥 zoom in {ticks}")


def zoom_out(ticks: int = 3) -> None:
    """Scroll down ``ticks`` wheel notches — zooms the RS3 camera out."""
    if ticks <= 0:
        return
    _scroll(-int(ticks) * int(ZOOM_NOTCH))
    _api._ctx().log(f"🎥 zoom out {ticks}")


def rotate_left(degrees: float = 45) -> None:
    """Rotate the camera left by ``degrees`` via middle-mouse drag."""
    rotate(horizontal=-abs(float(degrees)), vertical=0)


def rotate_right(degrees: float = 45) -> None:
    """Rotate the camera right by ``degrees`` via middle-mouse drag."""
    rotate(horizontal=abs(float(degrees)), vertical=0)


def pitch_up(degrees: float = 15) -> None:
    """Pitch the camera up (look higher)."""
    rotate(horizontal=0, vertical=-abs(float(degrees)))


def pitch_down(degrees: float = 15) -> None:
    """Pitch the camera down (look lower)."""
    rotate(horizontal=0, vertical=abs(float(degrees)))


def rotate(horizontal: float = 0, vertical: float = 0) -> None:
    """Composite rotation — positive horizontal = right, positive vertical = down."""
    dx = int(round(float(horizontal) * PIXELS_PER_DEGREE))
    dy = int(round(float(vertical) * PIXELS_PER_DEGREE))
    if dx == 0 and dy == 0:
        return
    _drag_delta(dx, dy)
    _api._ctx().log(
        f"🎥 rotate h={horizontal:+.0f}° v={vertical:+.0f}°  (drag {dx:+d},{dy:+d}px)"
    )
