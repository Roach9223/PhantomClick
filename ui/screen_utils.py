"""Shared monitor / screen enumeration helpers.

Both the Monitor card and the Settings page render the user's attached
screens as a friendly label list. This module is the single source of
truth for that label — extracted from prior duplicates that had drifted
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
