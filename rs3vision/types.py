"""Lightweight dataclasses for rs3vision results.

The native module returns plain tuples/dicts for speed. These dataclasses
exist for callers who want typed, named access — use `Match.from_tuple(t)`
or `RecognizedLine.from_dict(d)` to lift a raw result.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Tuple

Pt = Tuple[int, int]
Roi = Tuple[int, int, int, int]  # (x, y, w, h)


@dataclass(frozen=True, slots=True)
class Match:
    """A single color-match: pixel coordinate plus match confidence in [0, 1]."""

    x: int
    y: int
    confidence: float

    @classmethod
    def from_tuple(cls, t: tuple[int, int, float]) -> "Match":
        x, y, c = t
        return cls(x=x, y=y, confidence=c)

    @property
    def point(self) -> Pt:
        return (self.x, self.y)


@dataclass(frozen=True, slots=True)
class ColorCount:
    """Aggregate color-count result."""

    count: int
    confidence: float

    @classmethod
    def from_tuple(cls, t: tuple[int, float]) -> "ColorCount":
        c, conf = t
        return cls(count=c, confidence=conf)


@dataclass(frozen=True, slots=True)
class Rect:
    """Axis-aligned rectangle (x, y, w, h)."""

    x: int
    y: int
    w: int
    h: int

    @classmethod
    def from_tuple(cls, t: Roi) -> "Rect":
        x, y, w, h = t
        return cls(x=x, y=y, w=w, h=h)

    def as_tuple(self) -> Roi:
        return (self.x, self.y, self.w, self.h)


@dataclass(frozen=True, slots=True)
class RecognizedLine:
    """One line of recognized text from `rv.ocr.read`."""

    text: str
    bbox: Rect
    confidence: float
    per_char_confidence: List[float] = field(default_factory=list)

    @classmethod
    def from_dict(cls, d: dict) -> "RecognizedLine":
        return cls(
            text=d["text"],
            bbox=Rect.from_tuple(d["bbox"]),
            confidence=float(d["confidence"]),
            per_char_confidence=list(d.get("per_char_confidence", [])),
        )


@dataclass(frozen=True, slots=True)
class FrameDiff:
    """Result of `rv.feature.diff`."""

    changed: List[Roi]
    hash: int

    @classmethod
    def from_tuple(cls, t: tuple) -> "FrameDiff":
        changed, h = t
        return cls(changed=list(changed), hash=int(h))


@dataclass(frozen=True, slots=True)
class ChatEvent:
    """A single chatbox event emitted by `rv.ocr.chatbox_events`."""

    event: str        # event name from chat_colors.toml (e.g. "TreeCutWillow")
    text: str         # raw OCR text that produced the event
    color_bgr: Tuple[int, int, int]
    bbox: Rect
    confidence: float


@dataclass(frozen=True, slots=True)
class Uptext:
    """Top-of-screen action hover text."""

    action: str
    target: str
    bbox: Rect
    confidence: float


@dataclass(frozen=True, slots=True)
class XpDrop:
    """A single XP-drop event (skill icon + amount)."""

    skill: str
    amount: int
    bbox: Rect
    confidence: float
