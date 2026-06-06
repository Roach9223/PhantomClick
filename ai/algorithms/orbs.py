"""Resource-bar reader — HP / Adrenaline / Prayer / Summoning %.

Reads RuneScape NXT's horizontal resource bars (the strip at the top
or bottom of the action bar with four coloured fills). Each bar fills
from left as the resource depletes — at 100% the whole bar is its
signature colour; at 0% it's gone entirely.

Detection is colour-keyed per bar rather than position-based: we
``rs3vision.color.count`` each known signature colour over the ROI
and divide by a calibrated ``max_fill`` (captured at 100% in the AI
tab's "Calibrate Orbs ROI" handler). This is robust to HUD scale
changes and layout shifts because we never assume a specific bar
lives at a specific x-offset.

The legacy RS3 client's vertical orb stack is no longer supported —
PhantomClick targets RS3 NXT, the modern client. The file is still
named ``orbs.py`` for back-compat with WorldState's import path; the
public types are :class:`OrbReading` and :class:`OrbsState`.

Calibration assumes the player is at 100% HP / 100% Prayer / 100%
Run-energy (= 100% adrenaline) / 100% Summoning when calibrating —
the AI tab prompt explicitly says so. The captured pixel counts
become the divisor for runtime percentages.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Dict, Optional, Tuple

import numpy as np


# ── Signature colours (BGR — matches mss / cv2 / rs3vision frames) ──
# Sampled from a real NXT screenshot (assets/exampes/...). The
# ``find_color`` tolerance below absorbs anti-aliasing and gradient
# noise, so the exact centre value matters less than the colour being
# unambiguous within the strip.
_SIGNATURES_BGR: Dict[str, Tuple[int, int, int]] = {
    "hp":          (19, 53, 229),     # red
    "adrenaline":  (9, 131, 201),     # gold/yellow
    "prayer":      (139, 55, 79),     # violet/purple
    "summoning":   (39, 130, 59),     # green
}

# Per-channel match tolerance for each signature. CTS2 (HSL) handles
# antialiasing best; falls back to euclidean BGR distance via the
# numpy path if rs3vision isn't importable for any reason.
_DEFAULT_TOL: float = 30.0
_DEFAULT_CTS: int = 2

# Public ordering matches NXT layout (left-to-right): HP first, then
# Adrenaline, Prayer, Summoning. Run-energy lives in the minimap orb
# corner and is read by the minimap module instead — included here as
# an alias resolved on the OrbsState for callers that expect it.
ORB_NAMES: Tuple[str, ...] = ("hp", "adrenaline", "prayer", "summoning")


@dataclass
class OrbReading:
    """One bar's parsed state for a single tick."""

    pct: Optional[float]                 # 0..100, or None if uncalibrated
    raw_filled_px: int                   # signature-pixel count this tick
    raw_total_px: int                    # max_fill calibration value (or 0)


@dataclass
class OrbsState:
    """All four resource bars."""

    hp: Optional[OrbReading]
    adrenaline: Optional[OrbReading]
    prayer: Optional[OrbReading]
    summoning: Optional[OrbReading]
    roi: Tuple[int, int, int, int]
    elapsed_ms: float

    # Run-energy aliasing — modern bots tend to ask for run_energy via
    # the minimap orb, but plenty of bots only care about "is run
    # available" and treat adrenaline as the proxy. We don't auto-fill
    # this here; minimap.scan() populates a separate field. Provided
    # as a property so older code that referenced ``.run_energy``
    # doesn't crash with AttributeError.
    @property
    def run_energy(self) -> Optional[OrbReading]:
        return None

    def by_name(self, name: str) -> Optional[OrbReading]:
        return getattr(self, name, None)


def scan(
    frame: np.ndarray,
    roi: Tuple[int, int, int, int],
    *,
    max_fill: Optional[Dict[str, int]] = None,
    tol: float = _DEFAULT_TOL,
    cts: int = _DEFAULT_CTS,
) -> OrbsState:
    """Parse all four NXT bars into :class:`OrbReading`s.

    ``frame`` is a BGR uint8 array (mss output convention). ``roi`` is
    the absolute screen rectangle of the bar strip — calibrated once
    via the AI tab. ``max_fill`` is a dict keyed by ``"hp"``,
    ``"adrenaline"``, ``"prayer"``, ``"summoning"`` mapping to each
    bar's signature-pixel count at 100%. Missing keys → ``OrbReading``
    with ``pct=None`` (raw counts still populated for debugging).
    """
    t0 = time.perf_counter()
    if frame is None:
        raise ValueError("orbs.scan: frame is None")
    x, y, w, h = (int(v) for v in roi)
    fh, fw = frame.shape[:2]
    x = max(0, min(x, fw - 1))
    y = max(0, min(y, fh - 1))
    w = max(4, min(w, fw - x))
    h = max(4, min(h, fh - y))

    region = frame[y:y + h, x:x + w]
    max_fill = max_fill or {}

    readings: Dict[str, OrbReading] = {}
    for name, sig in _SIGNATURES_BGR.items():
        filled = _count_signature(region, sig, tol=tol, cts=cts)
        full = int(max_fill.get(name) or 0)
        if full <= 0:
            readings[name] = OrbReading(pct=None, raw_filled_px=filled, raw_total_px=0)
            continue
        pct = max(0.0, min(100.0, (filled / float(full)) * 100.0))
        readings[name] = OrbReading(pct=pct, raw_filled_px=filled, raw_total_px=full)

    elapsed_ms = (time.perf_counter() - t0) * 1000.0
    return OrbsState(
        hp=readings.get("hp"),
        adrenaline=readings.get("adrenaline"),
        prayer=readings.get("prayer"),
        summoning=readings.get("summoning"),
        roi=(x, y, w, h),
        elapsed_ms=elapsed_ms,
    )


def calibrate_at_full(
    frame: np.ndarray,
    roi: Tuple[int, int, int, int],
    *,
    tol: float = _DEFAULT_TOL,
    cts: int = _DEFAULT_CTS,
) -> Dict[str, int]:
    """Capture the per-bar pixel count at 100%.

    Called by the AI tab's calibrate handler immediately after the
    user draws the bar-strip box — assumes player is at 100% HP /
    Adrenaline / Prayer / Summoning. The returned dict is what
    callers should store as ``cfg["ai_orbs_max_fill"]``.
    """
    state = scan(frame, roi, max_fill=None, tol=tol, cts=cts)
    out: Dict[str, int] = {}
    for name in ORB_NAMES:
        r = state.by_name(name)
        if r is not None and r.raw_filled_px > 0:
            out[name] = int(r.raw_filled_px)
    return out


# ─────────────────────────────────────────────────────────────────
# Internals
# ─────────────────────────────────────────────────────────────────


def _count_signature(
    region: np.ndarray,
    bgr: Tuple[int, int, int],
    *,
    tol: float,
    cts: int,
) -> int:
    """Count pixels in ``region`` matching ``bgr`` within ``tol``.

    Prefers ``rs3vision.color.count`` (Rust CTS) when available; falls
    back to a numpy euclidean-distance count if the native module
    isn't loaded.
    """
    try:
        import rs3vision as rv
        count, _conf = rv.color.count(
            region, bgr, cts=int(cts), tol=float(tol),
        )
        return int(count)
    except Exception:
        # Numpy fallback — slightly slower (~1 ms vs <0.1 ms on a
        # 1000×80 strip) but always available.
        target = np.array(bgr, dtype=np.int16)
        diff = np.abs(region.astype(np.int16) - target).max(axis=2)
        return int((diff <= int(tol)).sum())
