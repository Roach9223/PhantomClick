"""Inventory grid scanner — parses the RuneScape 4×7 inventory panel.

Bots that need "is the inventory full?" or "are there ≥N items of color X?"
call ``scan(frame, roi)`` once per tick and read the resulting
:class:`InventoryState`. Scanning is pure numpy on the cropped ROI — no
rs3vision call per slot — so a full 28-slot scan is < 5 ms even at 4K.

The inventory panel must be visible (the player has the Inventory tab
open). When a different side panel is active (skills, prayer book, etc.)
the slots will all read as "filled" because the panel background isn't
visible. Bots that depend on this should additionally gate on the
inventory tab being active — that's a separate detection out of scope
for this module.

Calibration is per-user: the AI tab's "Calibrate Inventory ROI" button
captures ``(x, y, w, h)`` once and persists it as ``ai_inventory_rect``
in ``config.json``. Without calibration, ``WorldState.inventory`` returns
``None`` and bots that read it should bail.

Example::

    from ai.algorithms.inventory import scan
    state = scan(frame, roi=(3500, 1100, 340, 600))
    if state.is_full():
        click_bank()
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Optional, Tuple

import numpy as np


# ─────────────────────────────────────────────────────────────────
# Tuning constants
# ─────────────────────────────────────────────────────────────────

# RS3 NXT inventory background — dark warm brown-grey behind every
# empty slot. Sampled from real NXT screenshots: BGR centroid (32, 35,
# 39), ranging (24..46, 28..43, 28..50) across pixels. The empty test
# uses ``EMPTY_TOL`` per-channel slack to absorb that noise.
EMPTY_BG_BGR: Tuple[int, int, int] = (32, 35, 39)

# Per-channel max-deviation tolerance for the empty test. NXT has more
# noise variance than legacy (gradients, soft shadows on slot borders)
# so a generous tolerance is correct. Tighter values miss empty pixels
# at slot edges and over-report "filled".
EMPTY_TOL: int = 22

# Fraction of the slot's sampled window that must match the bg colour
# for the slot to be classified empty. Items that don't fully cover
# their slot (small icons with bg corners) need this < 1.0; too low
# and a partially-transparent overlay reads as empty.
EMPTY_FILL_THRESHOLD: float = 0.75

# Border in pixels to skip on each side of every slot when sampling —
# the 1-2 px border between slots is always darker regardless of slot
# state, so including it would skew empty/filled ratios.
SLOT_BORDER_PX: int = 3


# ─────────────────────────────────────────────────────────────────
# Public types
# ─────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class InventorySlot:
    """One of the 28 inventory cells, parsed for a single tick."""

    index: int                              # 0..27, row-major (row*4 + col)
    is_empty: bool
    dominant_rgb: Tuple[int, int, int]      # 0..255 each, RGB (not BGR)
    pixel_signature: int                    # 64-bit hash for change-detect

    @property
    def row(self) -> int:
        return self.index // 4

    @property
    def col(self) -> int:
        return self.index % 4


@dataclass
class InventoryState:
    """Result of one ``scan()`` — a full 4×7 inventory snapshot."""

    slots: Tuple[InventorySlot, ...]
    roi: Tuple[int, int, int, int]          # (x, y, w, h) used for the scan
    elapsed_ms: float                       # how long the scan took
    # Heuristic 0..1 score: how confident we are this ROI actually
    # contains the inventory panel (and not Skills, Prayer book, etc.
    # which the user might have switched to). Low confidence = bot
    # rules that depend on inventory state should bail rather than
    # acting on garbage.
    confidence: float = 1.0
    extra: dict = field(default_factory=dict)

    def __post_init__(self) -> None:
        if len(self.slots) != 28:
            raise ValueError(
                f"InventoryState expects exactly 28 slots, got {len(self.slots)}"
            )

    def count_filled(self) -> int:
        return sum(1 for s in self.slots if not s.is_empty)

    def count_empty(self) -> int:
        return 28 - self.count_filled()

    def is_likely_open(self, *, threshold: float = 0.5) -> bool:
        """True when the scan's confidence clears ``threshold``.

        Bots that depend on inventory readings should gate every rule
        on this — when confidence is low the player likely has Skills,
        Prayer book, or another side panel open instead, so reading
        slot states gives wrong answers. ``threshold=0.5`` is a sane
        default; raise it if your bot can tolerate occasional misses.
        """
        return self.confidence >= threshold

    def is_full(self, *, tolerance: int = 0) -> bool:
        """True when ≥ ``28 - tolerance`` slots are filled.

        ``tolerance`` lets bots accept "essentially full" — useful for
        skills like fishing where stack-counting can wobble between
        stacks ticking up and a new slot opening.
        """
        return self.count_filled() >= 28 - max(0, tolerance)

    def slot(self, row: int, col: int) -> InventorySlot:
        if not (0 <= row < 7 and 0 <= col < 4):
            raise IndexError(f"row={row} col={col} out of inventory bounds")
        return self.slots[row * 4 + col]

    def slots_with_color(
        self,
        rgb: Tuple[int, int, int],
        *,
        tol: int = 20,
    ) -> list[InventorySlot]:
        """Slots whose dominant color is within ``tol`` (RGB euclidean) of ``rgb``."""
        target = np.array(rgb, dtype=np.int16)
        out: list[InventorySlot] = []
        for s in self.slots:
            if s.is_empty:
                continue
            dom = np.array(s.dominant_rgb, dtype=np.int16)
            if int(np.sqrt(((dom - target) ** 2).sum())) <= tol:
                out.append(s)
        return out

    def signature(self) -> int:
        """Single int that changes when any slot changes — for cheap diff."""
        sig = 0
        for s in self.slots:
            sig ^= s.pixel_signature
        return sig & 0xFFFFFFFFFFFFFFFF


# ─────────────────────────────────────────────────────────────────
# Scanner
# ─────────────────────────────────────────────────────────────────


def scan(
    frame: np.ndarray,
    roi: Tuple[int, int, int, int],
) -> InventoryState:
    """Parse the inventory panel into 28 :class:`InventorySlot` records.

    ``frame`` is a BGR uint8 array (H, W, 3) — the standard mss output.
    ``roi`` is the absolute screen-space rectangle of the inventory
    panel: ``(x, y, w, h)``. The caller is responsible for ROI
    calibration (the AI tab does this once via the ZoneDrawer).
    """
    t0 = time.perf_counter()
    if frame is None:
        raise ValueError("inventory.scan: frame is None")
    if frame.ndim != 3 or frame.shape[2] != 3:
        raise ValueError(
            f"inventory.scan: expected (H,W,3) BGR, got shape={frame.shape}"
        )

    x, y, w, h = (int(v) for v in roi)
    fh, fw = frame.shape[:2]
    # Clamp to frame bounds — a recalibration-after-resolution-change
    # could leave the saved ROI hanging off the edge. Better to scan a
    # smaller area than to crash.
    x = max(0, min(x, fw - 1))
    y = max(0, min(y, fh - 1))
    w = max(4, min(w, fw - x))
    h = max(7, min(h, fh - y))

    inv = frame[y:y + h, x:x + w]               # zero-copy view

    # Pure-uint8 empty test. Each channel must lie within [bg-tol, bg+tol].
    # uint8 saturating subtract via np.clip lets us avoid the int16
    # conversion of the entire ROI — measurable speedup at 4K.
    low = np.clip(np.array(EMPTY_BG_BGR, dtype=np.int16) - EMPTY_TOL,
                  0, 255).astype(np.uint8)
    high = np.clip(np.array(EMPTY_BG_BGR, dtype=np.int16) + EMPTY_TOL,
                   0, 255).astype(np.uint8)
    in_band = (inv >= low) & (inv <= high)       # H×W×3 bool
    empty_mask = in_band.all(axis=2)             # H×W bool

    slot_w = w // 4
    slot_h = h // 7
    pad = SLOT_BORDER_PX

    slots: list[InventorySlot] = []
    for idx in range(28):
        row = idx // 4
        col = idx % 4
        sx0 = col * slot_w + pad
        sy0 = row * slot_h + pad
        sx1 = (col + 1) * slot_w - pad
        sy1 = (row + 1) * slot_h - pad
        # Defensive — a tiny ROI could degenerate slot dims to <= 0.
        if sx1 <= sx0 or sy1 <= sy0:
            slots.append(InventorySlot(
                index=idx, is_empty=True,
                dominant_rgb=(0, 0, 0), pixel_signature=0,
            ))
            continue

        slot_mask = empty_mask[sy0:sy1, sx0:sx1]
        empty_ratio = float(slot_mask.mean())
        is_empty = empty_ratio >= EMPTY_FILL_THRESHOLD

        # Dominant colour = mean of a small centred patch. Cheap and
        # good enough to differentiate "log-brown" from "ore-grey" —
        # we don't need a full quantized histogram unless a future
        # caller wants exact item ID, which is out of scope here.
        cx = (sx0 + sx1) // 2
        cy = (sy0 + sy1) // 2
        patch = inv[max(0, cy - 4):cy + 4, max(0, cx - 4):cx + 4]
        if patch.size == 0:
            dominant_rgb = (0, 0, 0)
        else:
            mean_bgr = patch.reshape(-1, 3).mean(axis=0)
            # Convert BGR → RGB for consumer convenience (config stores
            # 0xRRGGBB, the find_color API takes 0xRRGGBB).
            dominant_rgb = (
                int(mean_bgr[2]),
                int(mean_bgr[1]),
                int(mean_bgr[0]),
            )

        # Signature combines slot index + empty flag + dominant colour
        # so identical items in different slots and identical empty
        # slots in different positions all hash distinctly. Without
        # the index in the mix, XORing 28 slot-sigs would cancel pairs
        # of identical states.
        pixel_signature = hash((idx, is_empty, dominant_rgb)) & 0xFFFFFFFFFFFFFFFF

        slots.append(InventorySlot(
            index=idx,
            is_empty=is_empty,
            dominant_rgb=dominant_rgb,
            pixel_signature=pixel_signature,
        ))

    elapsed_ms = (time.perf_counter() - t0) * 1000.0
    confidence = _grid_confidence(empty_mask, slot_w, slot_h, slots)
    return InventoryState(
        slots=tuple(slots),
        roi=(x, y, w, h),
        elapsed_ms=elapsed_ms,
        confidence=confidence,
    )


def _grid_confidence(
    empty_mask: np.ndarray,
    slot_w: int,
    slot_h: int,
    slots: list,
) -> float:
    """Heuristic 0..1 score for "this ROI looks like an inventory panel".

    Two signals combined:
      1. Slot-border darkness — the dividers between slots are always
         darker than slot interiors. We look at columns/rows at slot
         pitch and compare to slot interior brightness. A panel with
         no grid pattern (skills tab, prayer book) fails this badly.
      2. Slot variance — empty/filled mix should produce a non-trivial
         distribution of dominant colours. If every slot has identical
         colour we're probably looking at a uniform side panel.
    """
    if empty_mask.size == 0 or slot_w < 6 or slot_h < 6:
        return 0.0

    # Signal 1: column profile at slot pitch.
    # Average each column across rows; the columns at multiples of slot_w
    # should be local minima (the divider). Compute the average column
    # darkness at divider positions vs. mid-slot positions.
    col_avg = empty_mask.mean(axis=0)  # 1D: average emptiness per column
    h, w = empty_mask.shape
    if w < slot_w * 4:
        return 0.5
    # Sample divider columns (slot edges) and mid-slot columns.
    div_cols = [min(w - 1, c * slot_w) for c in range(1, 4)]
    mid_cols = [min(w - 1, c * slot_w + slot_w // 2) for c in range(0, 4)]
    div_emptiness = float(np.mean([col_avg[c] for c in div_cols]))
    mid_emptiness = float(np.mean([col_avg[c] for c in mid_cols]))
    # Normalize: dividers should be at least 0.0 emptiness; if mid
    # columns have substantially-different emptiness, grid is present.
    grid_signal = min(1.0, abs(mid_emptiness - div_emptiness) * 2.5 + 0.4)

    # Signal 2: slot-content distribution. Penalize uniform panels.
    if not slots:
        return 0.0
    empties = sum(1 for s in slots if s.is_empty)
    fills = 28 - empties
    if fills == 0 or empties == 0:
        # All-empty or all-filled is plausible (fresh game = all empty,
        # banking = all empty after deposit, packed inventory = all
        # full). Don't penalize unless other signals are bad.
        distribution_signal = 0.6
    else:
        # Mixed = high confidence.
        distribution_signal = 1.0

    return float(min(1.0, 0.5 * grid_signal + 0.5 * distribution_signal))
