"""Chat color→event config loader.

Reads TOML from ``rs3vision/templates/chat_colors.toml`` (or a path you
pass in) and returns a typed config object. The loader is mtime-cached —
call :func:`load_chat_config` on every tick; it will return the cached
object until the file changes on disk.

Schema (see ``chat_colors.toml`` for the canonical example)::

    [font]
    path = "templates/fonts/plain_11.rvf"

    [chat_roi]
    x = 10
    y = 720
    w = 520
    h = 180

    [defaults]
    cts = 2
    tol = 20.0
    hue_mod = 0.2
    sat_mod = 0.2
    regex_flags = "i"

    [events.some_name]
    color   = 0xFFFF00
    pattern = "..."
    emit    = "SomeEvent"

Use :meth:`ChatConfig.by_color` to iterate events grouped by shared color,
which is how the chatbox parser minimises OCR passes: one pass per unique
color rather than one pass per event.
"""

from __future__ import annotations

import re
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Tuple

# -----------------------------------------------------------------
# Dataclasses
# -----------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ChatEventSpec:
    """A single event rule."""

    name: str
    color_rgb: int
    color_bgr: Tuple[int, int, int]
    pattern: re.Pattern
    emit: str

    @property
    def color_hex(self) -> str:
        return f"0x{self.color_rgb:06X}"


@dataclass(frozen=True, slots=True)
class ChatRoi:
    x: int
    y: int
    w: int
    h: int

    def as_tuple(self) -> Tuple[int, int, int, int]:
        return (self.x, self.y, self.w, self.h)


@dataclass(frozen=True, slots=True)
class ChatDefaults:
    cts: int = 2
    tol: float = 20.0
    hue_mod: float = 0.2
    sat_mod: float = 0.2
    regex_flags_str: str = "i"


@dataclass
class ChatConfig:
    font_path: Path
    roi: ChatRoi
    defaults: ChatDefaults
    events: list[ChatEventSpec] = field(default_factory=list)

    def by_color(self) -> dict[Tuple[int, int, int], list[ChatEventSpec]]:
        """Group events by their BGR color — the chatbox parser iterates
        this map, running one OCR pass per unique color."""
        out: dict[Tuple[int, int, int], list[ChatEventSpec]] = {}
        for e in self.events:
            out.setdefault(e.color_bgr, []).append(e)
        return out


# -----------------------------------------------------------------
# Loader with mtime cache
# -----------------------------------------------------------------

_cache: dict[Path, tuple[float, ChatConfig]] = {}


def _regex_flags(s: str) -> int:
    f = 0
    s = (s or "").lower()
    if "i" in s:
        f |= re.IGNORECASE
    if "m" in s:
        f |= re.MULTILINE
    if "s" in s:
        f |= re.DOTALL
    return f


def _rgb_to_bgr(hex_rgb: int) -> Tuple[int, int, int]:
    r = (hex_rgb >> 16) & 0xFF
    g = (hex_rgb >> 8) & 0xFF
    b = hex_rgb & 0xFF
    return (b, g, r)


def load_chat_config(path: Path | str | None = None) -> ChatConfig:
    """Load and cache chat config. Re-reads when the file's mtime changes.

    `path` defaults to the bundled `chat_colors.toml` shipped with the
    rs3vision package — edit that one in place for quick iteration.
    """
    if path is None:
        path = Path(__file__).resolve().parent / "templates" / "chat_colors.toml"
    path = Path(path).resolve()
    try:
        mtime = path.stat().st_mtime
    except FileNotFoundError as e:
        raise FileNotFoundError(f"chat config not found: {path}") from e

    cached = _cache.get(path)
    if cached is not None and cached[0] == mtime:
        return cached[1]

    with open(path, "rb") as f:
        raw = tomllib.load(f)

    font_section = raw.get("font") or {}
    roi_section = raw.get("chat_roi") or {}
    defaults_section = raw.get("defaults") or {}

    # Font path is relative to the package root (= dir holding this file).
    package_root = Path(__file__).resolve().parent
    font_rel = font_section.get("path", "templates/fonts/plain_11.rvf")
    font_path = (package_root / font_rel).resolve()

    roi = ChatRoi(
        x=int(roi_section.get("x", 0)),
        y=int(roi_section.get("y", 0)),
        w=int(roi_section.get("w", 0)),
        h=int(roi_section.get("h", 0)),
    )
    defaults = ChatDefaults(
        cts=int(defaults_section.get("cts", 2)),
        tol=float(defaults_section.get("tol", 20.0)),
        hue_mod=float(defaults_section.get("hue_mod", 0.2)),
        sat_mod=float(defaults_section.get("sat_mod", 0.2)),
        regex_flags_str=str(defaults_section.get("regex_flags", "i")),
    )

    flags = _regex_flags(defaults.regex_flags_str)

    events: list[ChatEventSpec] = []
    events_section = raw.get("events") or {}
    for name, e in events_section.items():
        if not isinstance(e, dict):
            continue
        color = int(e.get("color", 0xFFFFFF))
        pattern = re.compile(str(e.get("pattern", "")), flags)
        emit = str(e.get("emit", name))
        events.append(
            ChatEventSpec(
                name=name,
                color_rgb=color,
                color_bgr=_rgb_to_bgr(color),
                pattern=pattern,
                emit=emit,
            )
        )

    cfg = ChatConfig(
        font_path=font_path,
        roi=roi,
        defaults=defaults,
        events=events,
    )
    _cache[path] = (mtime, cfg)
    return cfg


def clear_cache() -> None:
    """Drop the mtime cache (useful for tests)."""
    _cache.clear()
