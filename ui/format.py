"""Display + parse helpers for numeric values.

Single source of truth for how the GUI renders delays, counts, rates,
and screen positions. Centralizing these rules keeps the surface
visually consistent — no tab gets to invent its own decimal precision
or comma-separator habit.

Storage is always seconds (float) for delays. ``fmt_delay`` is the
canonical time formatter; ``fmt_count`` / ``fmt_rate`` / ``fmt_position``
cover the other displays that previously each rolled their own f-string.
"""

from __future__ import annotations

from typing import Optional


def fmt_delay(seconds: float) -> str:
    """Render a seconds value as ``X.XXX s`` (sub-10) or ``X.XX s`` (≥10).

    Single global rule — no mixed ms/s units. Short delays read
    ``0.075 s`` not ``75 ms``; longer delays drop a decimal once they
    exceed 10 s where extra precision is noise. Storage is always
    seconds (float), so this is purely display.
    """
    s = float(seconds)
    if s < 10.0:
        return f"{s:.3f} s"
    return f"{s:.2f} s"


def fmt_count(n: int) -> str:
    """Render an integer with locale-style comma separators.

    Canonical for "how many things" displays — total clicks, event
    counts, list lengths. No unit; callers append the noun
    (``f"{fmt_count(n)} events"``).
    """
    return f"{int(n):,}"


def fmt_position(x: int, y: int) -> str:
    """Render a screen coordinate as ``(X, Y)``.

    Canonical for any "where on screen" readout — last click pos, zone
    center, click area origin. Space after the comma, parentheses
    around the pair.
    """
    return f"({int(x)}, {int(y)})"


def fmt_rate(value: float, unit: str, decimals: int = 1) -> str:
    """Render a rate value with consistent precision and unit suffix.

    ``fmt_rate(125.34, "CPM") -> "125.3 CPM"``. Default 1 decimal so
    rate readouts don't flicker on every tick. Pass ``decimals=0`` for
    integer-valued rates.
    """
    return f"{float(value):.{int(decimals)}f} {unit}"


def parse_delay(raw: str) -> Optional[float]:
    """Parse user input into a seconds value.

    Accepts ``"50ms"``, ``"0.05s"``, ``"0.05"`` (bare → seconds for
    backwards compat with the old `.1f` entries), case-insensitive,
    whitespace-tolerant. Returns ``None`` on parse failure so callers
    can keep the previous value.
    """
    if raw is None:
        return None
    s = str(raw).strip().lower().replace(" ", "")
    if not s:
        return None
    try:
        if s.endswith("ms"):
            return float(s[:-2]) / 1000.0
        if s.endswith("s"):
            return float(s[:-1])
        return float(s)
    except (TypeError, ValueError):
        return None
