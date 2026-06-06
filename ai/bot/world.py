"""WorldState — per-tick parsed game-state cache.

Every tick, :class:`ai.bot.runner._BotWorker` builds a fresh
:class:`WorldState` and attaches it to ``ctx.world``. Bot rules read
state through :func:`ai.bot.api.world` rather than re-scanning the
frame in every rule body. Fields use ``@cached_property`` so a tick
where no rule reads ``world().inventory`` skips the inventory scan
entirely — zero overhead for unused awareness primitives.

ROIs come from user calibration persisted in ``config.json`` and
plumbed through ``BotRunner.play(world_calibration={...})``. If the
user hasn't calibrated a given surface, the corresponding property
returns ``None`` (it does not raise) — bot rules should bail with
``if (inv := world().inventory) is None: return False``.

Lifetime is tick-scoped:
    1. ``_BotWorker.run()`` constructs ``WorldState`` after capture,
       before binding the contextvars context.
    2. The contextvars-bound ``api.world()`` returns this instance.
    3. First access to a ``@cached_property`` runs the scan and stores
       the result in ``__dict__``.
    4. Subsequent accesses (same tick) return the stored value.
    5. Next tick clobbers ``ctx.world`` with a new instance — the
       prior one becomes garbage.

Threading: WorldState lives entirely on the bot worker thread. Don't
expose it on Qt signals — that would cross threads.
"""

from __future__ import annotations

from functools import cached_property
from typing import Any, Dict, Optional, Tuple

import numpy as np


class WorldState:
    """Per-tick lazy aggregator of parsed game state."""

    def __init__(self, ctx: Any, frame: np.ndarray, tick: int) -> None:
        self._ctx = ctx
        self.frame = frame
        self.tick = tick
        # Calibration ROIs — pulled from ctx._world_calibration which
        # the runner populates from config.json once at startup.
        calib = getattr(ctx, "_world_calibration", None) or {}
        self._inventory_rect: Optional[Tuple[int, int, int, int]] = (
            _coerce_rect(calib.get("inventory_rect"))
        )
        self._orbs_rect: Optional[Tuple[int, int, int, int]] = (
            _coerce_rect(calib.get("orbs_rect"))
        )
        self._minimap_rect: Optional[Tuple[int, int, int, int]] = (
            _coerce_rect(calib.get("minimap_rect"))
        )
        self._orbs_max_fill: Dict[str, int] = dict(
            calib.get("orbs_max_fill") or {}
        )
        # Per-bot item library. The runner attaches an ItemLibrary
        # instance to ctx if the bot has any registered items;
        # otherwise this stays None and item-matching helpers return
        # empty results.
        self._item_library: Any = getattr(ctx, "item_library", None)

    # ── Inventory ──────────────────────────────────────────────────
    @cached_property
    def inventory(self):
        """4×7 inventory snapshot, or ``None`` if uncalibrated."""
        if self._inventory_rect is None:
            self._warn_once("inventory")
            return None
        from ..algorithms import inventory as _inv
        try:
            return _inv.scan(self.frame, self._inventory_rect)
        except Exception as e:
            self._ctx.log(
                f"[world] inventory scan failed: {type(e).__name__}: {e}"
            )
            return None

    # ── Orbs (HP / Prayer / Run-energy / Summoning) ────────────────
    @cached_property
    def orbs(self):
        """Orb percentages, or ``None`` if uncalibrated / not yet shipped."""
        if self._orbs_rect is None:
            self._warn_once("orbs")
            return None
        try:
            from ..algorithms import orbs as _orbs
        except ImportError:
            return None
        try:
            return _orbs.scan(
                self.frame, self._orbs_rect, max_fill=self._orbs_max_fill,
            )
        except Exception as e:
            self._ctx.log(
                f"[world] orbs scan failed: {type(e).__name__}: {e}"
            )
            return None

    # ── Minimap ─────────────────────────────────────────────────────
    @cached_property
    def minimap(self):
        """Read the runner-installed minimap state (preferred) or fall
        back to a stateless one-shot scan when no tracker is running.

        The runner's :class:`ai.algorithms.minimap.MinimapTracker`
        keeps the previous frame across ticks so motion detection
        actually works; a one-shot scan can't do that and will always
        report ``motion_score == 0``.
        """
        ms = getattr(self._ctx, "minimap_state", None)
        if ms is not None:
            return ms
        if self._minimap_rect is None:
            return None
        try:
            from ..algorithms import minimap as _mm
            return _mm.scan(self.frame, self._minimap_rect)
        except Exception:
            return None

    # ── Uptext (cursor-anchored RS3 tooltip) ───────────────────────
    @cached_property
    def uptext(self) -> Optional[Dict[str, Any]]:
        # Delegates to the existing api.uptext() for symmetry. That
        # function reads ctx._uptext_reader; calling it once and
        # caching here means subsequent reads in the same tick are
        # free.
        from .api import uptext as _uptext
        try:
            return _uptext()
        except Exception:
            return None

    # ── Item-aware inventory ──────────────────────────────────────
    @cached_property
    def inventory_matches(self):
        """Per-slot item identification, lazy. ``None`` when no library
        is loaded or inventory is unavailable / low-confidence."""
        inv = self.inventory
        lib = self._item_library
        if inv is None or lib is None or len(lib) == 0:
            return None
        from ..algorithms import items as _items
        return _items.match_inventory(self.frame, inv, lib)

    def slots_with_item(self, name: str) -> list[int]:
        """Slot indices whose contents match ``name`` against the item library."""
        matches = self.inventory_matches
        if matches is None:
            return []
        from ..algorithms import items as _items
        return _items.slots_with_item(matches, name)

    def count_item(self, name: str) -> int:
        """How many slots contain ``name``. 0 when uncalibrated / library
        empty / no slots match. Pairs naturally with ``world().count_item('Raw
        trout') >= 10`` predicates."""
        return len(self.slots_with_item(name))

    # ── Convenience accessors for the most common readings ────────
    def hp_pct(self) -> Optional[float]:
        o = self.orbs
        return None if o is None or o.hp is None else o.hp.pct

    def adrenaline_pct(self) -> Optional[float]:
        o = self.orbs
        return None if o is None or o.adrenaline is None else o.adrenaline.pct

    def prayer_pct(self) -> Optional[float]:
        o = self.orbs
        return None if o is None or o.prayer is None else o.prayer.pct

    def summoning_pct(self) -> Optional[float]:
        o = self.orbs
        return None if o is None or o.summoning is None else o.summoning.pct

    def run_energy_pct(self) -> Optional[float]:
        """Run-energy comes from the minimap orb (top-right of the
        minimap ROI), not the bar strip. Returns ``None`` if the
        minimap isn't calibrated yet."""
        mm = self.minimap
        if mm is None:
            return None
        return getattr(mm, "run_energy_pct", None)

    # ── Internals ──────────────────────────────────────────────────
    def _warn_once(self, surface: str) -> None:
        """Log a missing-calibration warning at most once per session."""
        flag = f"_world_warned_{surface}"
        if getattr(self._ctx, flag, False):
            return
        setattr(self._ctx, flag, True)
        self._ctx.log(
            f"[world] {surface} not calibrated — "
            f"world().{surface} returns None. Run "
            f"\"Calibrate {surface.title()} ROI\" in the AI tab."
        )


def _coerce_rect(raw) -> Optional[Tuple[int, int, int, int]]:
    """Accept tuple/list of 4 ints, return a clean tuple or None."""
    if raw is None:
        return None
    if not isinstance(raw, (list, tuple)) or len(raw) != 4:
        return None
    try:
        return (int(raw[0]), int(raw[1]), int(raw[2]), int(raw[3]))
    except (TypeError, ValueError):
        return None


def build_world(ctx: Any, frame: np.ndarray, tick: int) -> WorldState:
    """Factory used by :class:`ai.bot.runner._BotWorker` per tick."""
    return WorldState(ctx, frame, tick)
