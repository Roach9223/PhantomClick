"""SVG icon registry for the command deck.

Two sources feed one lookup:

1. A built-in set of stroke icons written as SVG strings on a 24 px grid
   (stroke-width 1.5, round caps and joins). These cover the nav rail,
   transport controls, and the small action buttons in cards.
2. Six micrographics from Fox Rockett Studio's Micrographics Vol.1,
   shipped in ``ui/assets/micro/`` as ``mg<N>.svg``. They are stroke-only
   line art drawn in ``#000`` and get recoloured at load time.

``QSvgRenderer`` does not understand ``currentColor``, so every icon is
authored (or rewritten) with ``#000`` strokes and the requested hex is
substituted into the SVG text before rendering. Results are cached by
``(name, size, colour, degrees)`` so repeated calls in paint loops are
free after the first render.

Public helpers::

    icon(name, size=16, color=t.TEXT_SECONDARY) -> QIcon
    pixmap(name, size, color) -> QPixmap
    rotated_pixmap(name, size, color, degrees) -> QPixmap
    NAMES  # tuple of every registered icon name
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Dict

from PySide6.QtCore import QByteArray, QRectF, Qt
from PySide6.QtGui import QIcon, QPainter, QPixmap, QTransform
from PySide6.QtSvg import QSvgRenderer

from utils.paths import bundled_root

from . import theme as t


_MICRO_DIR = Path(__file__).resolve().parent / "assets" / "micro"


def _micro_dir() -> Path:
    """Micrographics folder, valid both in dev and inside the frozen bundle."""
    if _MICRO_DIR.is_dir():
        return _MICRO_DIR
    return bundled_root() / "ui" / "assets" / "micro"


# -- Built-in stroke icons ---------------------------------------------------
# Each entry is the inner markup of a 24x24 viewBox. Strokes are #000 and
# get recoloured at render time. Keep shapes simple: 1.5 px strokes read
# cleanly at 16 px, thinner does not.

_HEAD = (
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" '
    'fill="none" stroke="#000" stroke-width="1.5" '
    'stroke-linecap="round" stroke-linejoin="round">'
)
_TAIL = "</svg>"

_BUILTIN: Dict[str, str] = {
    # -- Nav rail -----------------------------------------------------------
    # Cursor arrow with a click burst.
    "click": (
        '<path d="M8 8l11 4.5-5 1.6-1.6 5z"/>'
        '<path d="M14 14l5 5"/>'
        '<path d="M5 4l1.5 1.5M3.5 9.5h2M9.5 3.5v2"/>'
    ),
    # Stacked list with an ordered marker.
    "record": (
        '<path d="M10 6h10M10 12h10M10 18h10"/>'
        '<path d="M4 6h.01M4 12h.01M4 18h.01" stroke-width="2.5"/>'
    ),
    # Pencil: the deck's EDITOR pane toggle.
    "edit": (
        '<path d="M14.5 5.5l4 4L8 20H4v-4z"/>'
        '<path d="M12.5 7.5l4 4"/>'
    ),
    # Circuit node cluster.
    "ai": (
        '<rect x="4" y="8" width="16" height="12" rx="2.5"/>'
        '<path d="M12 8V5M12 5h.01M2 14h2M20 14h2"/>'
        '<path d="M9 14h.01M15 14h.01" stroke-width="2.5"/>'
        '<path d="M9.5 17.5h5"/>'
    ),
    # Crosshair with an open centre.
    "hover": (
        '<circle cx="12" cy="12" r="7"/>'
        '<path d="M12 3v3M12 18v3M3 12h3M18 12h3"/>'
    ),
    # Sliders / behavior dials.
    "behavior": (
        '<path d="M4 7h16M4 12h16M4 17h16"/>'
        '<circle cx="9" cy="7" r="1.8" fill="#000"/>'
        '<circle cx="15" cy="12" r="1.8" fill="#000"/>'
        '<circle cx="8" cy="17" r="1.8" fill="#000"/>'
    ),
    # Keyboard.
    "hotkeys": (
        '<rect x="3" y="6" width="18" height="12" rx="2"/>'
        '<path d="M7 10h.01M10.5 10h.01M14 10h.01M17.5 10h.01M8 14h8"/>'
    ),
    # Stopwatch.
    "timers": (
        '<circle cx="12" cy="13" r="7"/>'
        '<path d="M12 10v3.5l2.5 1.5M10 3h4M12 3v3"/>'
    ),
    # Bars.
    "stats": (
        '<path d="M4 20h16"/>'
        '<path d="M7 20v-7M12 20V6M17 20v-10"/>'
    ),
    # Antenna / radar sweep.
    "monitor": (
        '<circle cx="12" cy="12" r="2"/>'
        '<path d="M16.2 7.8a6 6 0 0 1 0 8.4M7.8 16.2a6 6 0 0 1 0-8.4"/>'
        '<path d="M19.1 4.9a10 10 0 0 1 0 14.2M4.9 19.1a10 10 0 0 1 0-14.2"/>'
    ),
    # A screen on a stand: monitors in the zone map and target picker.
    "display": (
        '<rect x="2.5" y="4" width="19" height="13" rx="2"/>'
        '<path d="M8.5 20.5h7M12 17v3.5"/>'
    ),
    # Four corner arrows: fullscreen.
    "expand": (
        '<path d="M8 3.5H5.5a2 2 0 0 0-2 2V8M20.5 8V5.5a2 2 0 0 0-2-2H16'
        'M3.5 16v2.5a2 2 0 0 0 2 2H8M16 20.5h2.5a2 2 0 0 0 2-2V16"/>'
    ),
    # Gear (octagonal, simple).
    "settings": (
        '<path d="M12.22 2h-.44a2 2 0 0 0-2 2v.18a2 2 0 0 1-1 1.73l-.43.25a2 2 0 0 1-2 0'
        'l-.15-.08a2 2 0 0 0-2.73.73l-.22.38a2 2 0 0 0 .73 2.73l.15.1a2 2 0 0 1 1 1.72v.51'
        'a2 2 0 0 1-1 1.74l-.15.09a2 2 0 0 0-.73 2.73l.22.38a2 2 0 0 0 2.73.73l.15-.08'
        'a2 2 0 0 1 2 0l.43.25a2 2 0 0 1 1 1.73V20a2 2 0 0 0 2 2h.44a2 2 0 0 0 2-2v-.18'
        'a2 2 0 0 1 1-1.73l.43-.25a2 2 0 0 1 2 0l.15.08a2 2 0 0 0 2.73-.73l.22-.39'
        'a2 2 0 0 0-.73-2.73l-.15-.08a2 2 0 0 1-1-1.74v-.5a2 2 0 0 1 1-1.74l.15-.09'
        'a2 2 0 0 0 .73-2.73l-.22-.38a2 2 0 0 0-2.73-.73l-.15.08a2 2 0 0 1-2 0l-.43-.25'
        'a2 2 0 0 1-1-1.73V4a2 2 0 0 0-2-2z"/>'
        '<circle cx="12" cy="12" r="3"/>'
    ),
    # Question in a box.
    "help": (
        '<rect x="4" y="4" width="16" height="16" rx="2"/>'
        '<path d="M9.5 9.5a2.5 2.5 0 1 1 3.5 2.3c-.7.3-1 .8-1 1.5v.2"/>'
        '<path d="M12 16.5h.01"/>'
    ),
    # -- Transport ----------------------------------------------------------
    "play": '<path d="M7 5v14l11-7z" fill="#000"/>',
    "stop": '<rect x="6" y="6" width="12" height="12" rx="1" fill="#000"/>',
    "pause": '<path d="M8 5v14M16 5v14" stroke-width="2.5"/>',
    "record-dot": '<circle cx="12" cy="12" r="5.5" fill="#000"/>',
    # -- Actions ------------------------------------------------------------
    # Redraw: circular arrow.
    "redraw": (
        '<path d="M19 12a7 7 0 1 1-2.05-4.95"/>'
        '<path d="M19 4v4h-4"/>'
    ),
    # Clear: broom-ish, a box with a diagonal.
    "clear": (
        '<path d="M5 7h14M9 7V5h6v2"/>'
        '<path d="M7 7l1 12h8l1-12"/>'
        '<path d="M10 11v5M14 11v5"/>'
    ),
    "plus": '<path d="M12 5v14M5 12h14"/>',
    "minus": '<path d="M5 12h14"/>',
    "camera": (
        '<path d="M14.5 4h-5L8 6.5H5a2 2 0 0 0-2 2V18a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2V8.5'
        'a2 2 0 0 0-2-2h-3z"/>'
        '<circle cx="12" cy="13" r="3.5"/>'
    ),
    "target": (
        '<circle cx="12" cy="12" r="8"/>'
        '<circle cx="12" cy="12" r="3.5"/>'
        '<path d="M12 2v3M12 19v3M2 12h3M19 12h3"/>'
    ),
    "chevron-down": '<path d="M6 9l6 6 6-6"/>',
    "chevron-up": '<path d="M6 15l6-6 6 6"/>',
    "chevron-right": '<path d="M9 6l6 6-6 6"/>',
    "chevron-left": '<path d="M15 6l-6 6 6 6"/>',
    "arrow-up": '<path d="M12 19V5M5 12l7-7 7 7"/>',
    "arrow-right": '<path d="M5 12h14M12 5l7 7-7 7"/>',
    "arrow-down": '<path d="M12 5v14M5 12l7 7 7-7"/>',
    "arrow-left": '<path d="M19 12H5M12 5l-7 7 7 7"/>',
    "check": '<path d="M5 12.5l4.5 4.5L19 7.5"/>',
    "x": '<path d="M6 6l12 12M18 6L6 18"/>',
    "copy": (
        '<rect x="9" y="9" width="11" height="11" rx="1.5"/>'
        '<path d="M15 9V5.5A1.5 1.5 0 0 0 13.5 4h-8A1.5 1.5 0 0 0 4 5.5v8A1.5 1.5 0 0 0 5.5 15H9"/>'
    ),
    "duplicate": (
        '<rect x="8" y="8" width="12" height="12" rx="1.5"/>'
        '<path d="M16 8V5.5A1.5 1.5 0 0 0 14.5 4h-9A1.5 1.5 0 0 0 4 5.5v9A1.5 1.5 0 0 0 5.5 16H8"/>'
        '<path d="M14 11.5v5M11.5 14h5"/>'
    ),
    "trash": (
        '<path d="M5 7h14M10 7V5h4v2"/>'
        '<path d="M7 7l.8 12h8.4L17 7"/>'
        '<path d="M10 11v5M14 11v5"/>'
    ),
    "star": (
        '<path d="M12 4l2.4 5 5.4.7-4 3.8 1 5.4L12 16.3 7.2 18.9l1-5.4-4-3.8 5.4-.7z"/>'
    ),
    "folder": (
        '<path d="M3.5 7.5A1.5 1.5 0 0 1 5 6h4l2 2h8a1.5 1.5 0 0 1 1.5 1.5v8A1.5 1.5 0 0 1 19 19H5a1.5 1.5 0 0 1-1.5-1.5z"/>'
    ),
    "lock": (
        '<rect x="5" y="11" width="14" height="9" rx="1.5"/>'
        '<path d="M8 11V8a4 4 0 0 1 8 0v3"/>'
    ),
    "alert": (
        '<path d="M12 4l9 16H3z"/>'
        '<path d="M12 10v4M12 17h.01"/>'
    ),
    "eye": (
        '<path d="M2.5 12s3.5-6 9.5-6 9.5 6 9.5 6-3.5 6-9.5 6-9.5-6-9.5-6z"/>'
        '<circle cx="12" cy="12" r="2.8"/>'
    ),
    "eye-off": (
        '<path d="M2.5 12s3.5-6 9.5-6 9.5 6 9.5 6-3.5 6-9.5 6-9.5-6-9.5-6z"/>'
        '<circle cx="12" cy="12" r="2.8"/>'
        '<path d="M4 20L20 4" stroke-width="2"/>'
    ),
    "video": (
        '<rect x="3" y="7" width="13" height="10" rx="1.5"/>'
        '<path d="M16 10.5l5-2.5v8l-5-2.5"/>'
    ),
    "grid": (
        '<rect x="4" y="4" width="16" height="16" rx="1.5"/>'
        '<path d="M4 12h16M12 4v16"/>'
    ),
    "pin": (
        '<path d="M12 21s-6-5.5-6-10.5a6 6 0 0 1 12 0C18 15.5 12 21 12 21z"/>'
        '<circle cx="12" cy="10.5" r="2"/>'
    ),
    "bug": (
        '<rect x="8" y="8" width="8" height="10" rx="4"/>'
        '<path d="M10 8a2 2 0 0 1 4 0M4 12h4M16 12h4M5 18l3-2M19 18l-3-2M5 7l3 2M19 7l-3 2"/>'
    ),
    "key": (
        '<circle cx="8" cy="14" r="4"/>'
        '<path d="M11 11l8-8M15 7l2 2M17 5l2 2"/>'
    ),
    "command": (
        '<path d="M9 9V6a3 3 0 1 0-3 3h3zM15 9V6a3 3 0 1 1 3 3h-3zM9 15v3a3 3 0 1 1-3-3h3zM15 15v3a3 3 0 1 0 3-3h-3zM9 9h6v6H9z"/>'
    ),
    "external": (
        '<path d="M14 5h5v5M19 5l-8 8"/>'
        '<path d="M17 13v5a1 1 0 0 1-1 1H6a1 1 0 0 1-1-1V8a1 1 0 0 1 1-1h5"/>'
    ),
    "loop": (
        '<path d="M17 4l3 3-3 3"/>'
        '<path d="M4 11V9a2 2 0 0 1 2-2h14"/>'
        '<path d="M7 20l-3-3 3-3"/>'
        '<path d="M20 13v2a2 2 0 0 1-2 2H4"/>'
    ),
    "clock": (
        '<circle cx="12" cy="12" r="8"/>'
        '<path d="M12 8v4l3 2"/>'
    ),
    "square": '<rect x="7" y="7" width="10" height="10" rx="1" fill="#000"/>',
    "dot": '<circle cx="12" cy="12" r="4" fill="#000"/>',
}

# -- Micrographics -----------------------------------------------------------
_MICRO: Dict[str, str] = {
    "mg63": "mg63.svg",      # dial: circle + hand
    "mg85": "mg85.svg",      # circle crosshair
    "mg106": "mg106.svg",    # arrow up in a disc
    "mg108": "mg108.svg",    # arrow right in a disc
    "mg124": "mg124.svg",    # anti-cluster ring (square + circle + arrows)
    "mg130": "mg130.svg",    # radar rings
}

NAMES = tuple(list(_BUILTIN.keys()) + list(_MICRO.keys()))


def has(name: str) -> bool:
    """True if ``name`` is a registered icon."""
    return name in _BUILTIN or name in _MICRO


@lru_cache(maxsize=None)
def _source(name: str) -> str:
    """Raw SVG text for ``name`` with strokes in ``#000``."""
    if name in _BUILTIN:
        return _HEAD + _BUILTIN[name] + _TAIL
    if name in _MICRO:
        path = _micro_dir() / _MICRO[name]
        try:
            return path.read_text(encoding="utf-8")
        except OSError:
            return _HEAD + _TAIL
    raise KeyError(f"unknown icon: {name!r}")


def _recolour(svg: str, color: str) -> str:
    color = str(color)
    # Micrographics use CSS "stroke: #000;" plus a few filled shapes with
    # no explicit fill (they default to black). Built-ins use attributes.
    out = svg.replace("stroke: #000", f"stroke: {color}")
    out = out.replace('stroke="#000"', f'stroke="{color}"')
    out = out.replace('fill="#000"', f'fill="{color}"')
    out = out.replace("#000000", color)
    # Unstyled <circle>/<path> in the micrographics default to a black
    # fill. Give the root a fill so those pick up the colour too; shapes
    # that set fill: none in the stylesheet still win via CSS specificity.
    if "<svg" in out and 'fill="none"' not in out.split(">", 1)[0]:
        out = out.replace("<svg ", f'<svg fill="{color}" ', 1)
    return out


@lru_cache(maxsize=512)
def _render(name: str, size: int, color: str, degrees: float) -> QPixmap:
    svg = _recolour(_source(name), color)
    renderer = QSvgRenderer(QByteArray(svg.encode("utf-8")))
    size = max(1, int(size))
    pm = QPixmap(size, size)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing, True)
    p.setRenderHint(QPainter.SmoothPixmapTransform, True)
    if degrees:
        p.translate(size / 2.0, size / 2.0)
        p.rotate(degrees)
        p.translate(-size / 2.0, -size / 2.0)
    renderer.render(p, QRectF(0, 0, size, size))
    p.end()
    return pm


def pixmap(name: str, size: int = 16, color: str = t.TEXT_SECONDARY) -> QPixmap:
    """Rendered icon as a square QPixmap of ``size`` px in ``color``."""
    return _render(name, int(size), str(color), 0.0)


def rotated_pixmap(name: str, size: int, color: str, degrees: float) -> QPixmap:
    """Same as :func:`pixmap` but rotated about the centre. Used for the
    dial hand (``mg63``) and for pointing the disc arrows."""
    return _render(name, int(size), str(color), float(degrees) % 360.0)


def icon(name: str, size: int = 16, color: str = t.TEXT_SECONDARY) -> QIcon:
    """QIcon for buttons. Adds a disabled state in ``TEXT_DISABLED`` so a
    greyed button does not keep a bright glyph."""
    ic = QIcon()
    ic.addPixmap(pixmap(name, size, color), QIcon.Normal)
    ic.addPixmap(pixmap(name, size, t.TEXT_DISABLED), QIcon.Disabled)
    return ic


def flipped(pm: QPixmap, horizontal: bool = False, vertical: bool = False) -> QPixmap:
    """Mirror helper for the rare case an arrow needs flipping instead of
    rotating."""
    tr = QTransform()
    tr.scale(-1 if horizontal else 1, -1 if vertical else 1)
    return pm.transformed(tr, Qt.SmoothTransformation)
