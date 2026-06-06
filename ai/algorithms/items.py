"""Item library + per-slot inventory matching.

The framework keeps a per-user library of "known items" — each one is
an inventory icon (downloaded once from the RuneScape wiki, cached
locally) plus a name. At every tick, bot rules can ask
``world().count_item("Raw trout") >= 10`` and the framework matches
each non-empty inventory slot against every known item template,
returning the slot indices that contain it.

Matching strategy:
    1. Load each item's wiki icon as RGBA — transparent pixels are
       background and ignored during comparison.
    2. For each non-empty inventory slot, crop the slot's interior.
    3. Resize the slot crop to the icon's dimensions (or vice-versa,
       whichever's smaller — keeps things cheap).
    4. Compute mean per-channel BGR distance over the icon's
       non-transparent mask. Lower = better match.
    5. The item with the smallest distance below a threshold wins.

This is robust to small icon-position offsets within a slot and to
the slot's variable interior padding. It's sensitive to DPI scaling
of the inventory panel — if the user's HUD scale changes, item
templates may need re-downloading at the new size (handled by
``ItemLibrary.refresh``).

Performance: O(N_slots × N_items × icon_pixels). For 28 slots and
20 items at ~32×32 icons that's ~570K pixel ops per call — sub-ms in
numpy. Scales linearly with library size; fine up to a few hundred
items per bot.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np


# Match threshold — mean per-channel distance below this counts as a
# confident match. 0..255 scale; 30 is generous (catches faded icons,
# rejects clearly-different items).
DEFAULT_MATCH_THRESHOLD: float = 30.0


# ─────────────────────────────────────────────────────────────────
# Public types
# ─────────────────────────────────────────────────────────────────


@dataclass
class ItemTemplate:
    """One entry in the item library — name + cached BGR/alpha arrays."""

    name: str                   # canonical wiki name, e.g. "Raw trout"
    slug: str                   # filesystem slug, e.g. "raw_trout"
    bgr: np.ndarray             # (H, W, 3) uint8
    alpha: np.ndarray           # (H, W) uint8 — 0..255 transparency
    source_path: Path           # where the icon lives on disk

    @property
    def shape(self) -> Tuple[int, int]:
        return self.bgr.shape[:2]


@dataclass
class ItemMatch:
    """Result of matching one slot crop against the library."""

    slot_index: int             # 0..27
    item_name: Optional[str]    # None when no item beat the threshold
    distance: float             # mean per-channel distance for this best match


# ─────────────────────────────────────────────────────────────────
# Library
# ─────────────────────────────────────────────────────────────────


class ItemLibrary:
    """Loaded item templates, keyed by canonical name."""

    def __init__(self) -> None:
        self._templates: Dict[str, ItemTemplate] = {}

    def __len__(self) -> int:
        return len(self._templates)

    def __contains__(self, name: str) -> bool:
        return name in self._templates

    def names(self) -> List[str]:
        return list(self._templates.keys())

    def get(self, name: str) -> Optional[ItemTemplate]:
        return self._templates.get(name)

    # ── Loading ─────────────────────────────────────────────────
    def add_from_path(self, name: str, path: Path) -> Optional[ItemTemplate]:
        """Load a PNG icon and register it under ``name``.

        Returns the registered template, or ``None`` on load error.
        Replaces any existing entry under the same name.
        """
        try:
            tpl = _load_template(name, path)
        except Exception:
            return None
        self._templates[name] = tpl
        return tpl

    def add_many(self, items: Dict[str, Path]) -> List[str]:
        """Bulk-load. Returns list of names that loaded successfully."""
        ok: List[str] = []
        for name, path in items.items():
            if self.add_from_path(name, path) is not None:
                ok.append(name)
        return ok

    def remove(self, name: str) -> bool:
        return self._templates.pop(name, None) is not None

    # ── Matching ────────────────────────────────────────────────
    def best_match(
        self, slot_bgr: np.ndarray,
        *,
        threshold: float = DEFAULT_MATCH_THRESHOLD,
        margin: float = 5.0,
    ) -> Optional[Tuple[str, float]]:
        """Find the best-matching item for a given slot crop.

        Returns ``(name, distance)`` for the winner only if:
          1. Best distance ≤ ``threshold``, AND
          2. Best beats second-best by at least ``margin`` —
             otherwise the slot has visually-similar candidates
             (common with multi-piece equipment sets) and we'd
             rather return ``None`` than guess wrong.
        """
        if slot_bgr is None or slot_bgr.size == 0 or not self._templates:
            return None
        ranked: List[Tuple[float, str]] = []
        for tpl in self._templates.values():
            d = _template_distance(slot_bgr, tpl)
            ranked.append((d, tpl.name))
        ranked.sort(key=lambda p: p[0])
        if not ranked:
            return None
        best_dist, best_name = ranked[0]
        if best_dist > threshold:
            return None
        if len(ranked) >= 2:
            second_dist = ranked[1][0]
            if second_dist - best_dist < margin:
                return None         # too-close call
        return best_name, best_dist


# ─────────────────────────────────────────────────────────────────
# Inventory matching
# ─────────────────────────────────────────────────────────────────


def match_inventory(
    frame: np.ndarray,
    inv_state,                   # InventoryState (typed loosely to avoid cycle)
    library: ItemLibrary,
    *,
    threshold: float = DEFAULT_MATCH_THRESHOLD,
) -> List[ItemMatch]:
    """Run ``library.best_match`` on every non-empty slot.

    Empty slots get an :class:`ItemMatch` with ``item_name=None``.
    Returned list is parallel to ``inv_state.slots`` (length 28).
    """
    out: List[ItemMatch] = []
    if inv_state is None:
        return out
    rx, ry, rw, rh = inv_state.roi
    slot_w = rw // 4
    slot_h = rh // 7
    for slot in inv_state.slots:
        if slot.is_empty:
            out.append(ItemMatch(slot_index=slot.index, item_name=None, distance=0.0))
            continue
        r, c = slot.row, slot.col
        sx0 = rx + c * slot_w + 4
        sy0 = ry + r * slot_h + 4
        sx1 = rx + (c + 1) * slot_w - 4
        sy1 = ry + (r + 1) * slot_h - 4
        if sx1 <= sx0 or sy1 <= sy0:
            out.append(ItemMatch(slot_index=slot.index, item_name=None, distance=0.0))
            continue
        slot_crop = frame[sy0:sy1, sx0:sx1]
        result = library.best_match(slot_crop, threshold=threshold)
        if result is None:
            out.append(ItemMatch(slot_index=slot.index, item_name=None, distance=float("inf")))
        else:
            name, dist = result
            out.append(ItemMatch(slot_index=slot.index, item_name=name, distance=dist))
    return out


def slots_with_item(matches: List[ItemMatch], item_name: str) -> List[int]:
    return [m.slot_index for m in matches if m.item_name == item_name]


# ─────────────────────────────────────────────────────────────────
# Internals
# ─────────────────────────────────────────────────────────────────


def _load_template(name: str, path: Path) -> ItemTemplate:
    """Load a PNG and split into BGR + alpha arrays."""
    from PIL import Image
    img = Image.open(str(path))
    if img.mode != "RGBA":
        img = img.convert("RGBA")
    arr = np.asarray(img, dtype=np.uint8)         # H,W,4 RGBA
    rgb = arr[..., :3]
    alpha = arr[..., 3]
    bgr = np.ascontiguousarray(rgb[..., ::-1])
    return ItemTemplate(
        name=name,
        slug=path.stem,
        bgr=bgr,
        alpha=alpha,
        source_path=path,
    )


# Common size both slot crops and item templates are downsampled to
# before comparison. Wiki "detail" images come in at 500-1000+ px;
# inventory slot crops are ~30-50 px. Normalizing both to a small
# square makes comparisons cheap and stable across HUD scales.
_NORMALIZED_DIM: int = 32


def _resample_nn(arr: np.ndarray, h: int, w: int) -> np.ndarray:
    """Nearest-neighbour resample to (h, w, ...). Input may be 2-D or 3-D."""
    sh, sw = arr.shape[:2]
    yy = np.linspace(0, sh - 1, h).astype(np.int32)
    xx = np.linspace(0, sw - 1, w).astype(np.int32)
    return arr[yy[:, None], xx[None, :]]


def _template_distance(slot_bgr: np.ndarray, tpl: ItemTemplate) -> float:
    """Mean per-channel BGR distance between the slot crop and the
    template, measured only over the template's non-transparent pixels.

    Both slot and template are resampled to ``_NORMALIZED_DIM`` square
    so the comparison is independent of HUD scale and wiki render res.
    """
    if slot_bgr.size == 0:
        return float("inf")
    sh, sw = slot_bgr.shape[:2]
    if sh == 0 or sw == 0:
        return float("inf")
    n = _NORMALIZED_DIM
    slot_n = _resample_nn(slot_bgr, n, n)            # (n, n, 3)
    tpl_n = _resample_nn(tpl.bgr, n, n)
    alpha_n = _resample_nn(tpl.alpha, n, n)
    mask = alpha_n >= 128
    if not mask.any():
        return float("inf")
    diff = np.abs(slot_n.astype(np.int16) - tpl_n.astype(np.int16))
    per_pixel = diff.mean(axis=2)
    return float(per_pixel[mask].mean())
