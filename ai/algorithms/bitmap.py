"""Bitmap (template) matching.

Given a small reference BGR bitmap `T` of size (bh, bw, 3), find all
positions in a larger frame `F` where `T` appears within a per-channel
tolerance. Classic sliding-window template match, with one speedup:
we CTS1-prefilter the frame for the bitmap's anchor pixel (a single
pixel from `T`, chosen for uniqueness) and only validate `T` at those
anchor candidates. Typically drops match time from 100s of ms to <30 ms
on 4K scenes.

The Studio ships this as `rs3vision_studio.algorithms.bitmap.find`; the
`bitmap.find` Studio block wraps it.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Tuple

import numpy as np

import rs3vision as rv


# ─────────────────────────────────────────────────────────────────
# Types
# ─────────────────────────────────────────────────────────────────


@dataclass
class BitmapMatch:
    """One match: top-left position + mean per-pixel similarity."""
    x: int
    y: int
    confidence: float  # 1.0 = exact match, lower = more divergent


# ─────────────────────────────────────────────────────────────────
# PNG I/O
# ─────────────────────────────────────────────────────────────────


def load_png(path: Path | str) -> np.ndarray:
    """Load a PNG → C-contiguous (H, W, 3) uint8 **BGR** array."""
    from PIL import Image
    img = Image.open(str(path)).convert("RGB")
    rgb = np.asarray(img, dtype=np.uint8)
    return np.ascontiguousarray(rgb[..., ::-1])  # RGB → BGR


def save_png(bmp: np.ndarray, path: Path | str) -> None:
    """Save a (H, W, 3) BGR uint8 array as a PNG."""
    from PIL import Image
    if bmp.ndim != 3 or bmp.shape[2] != 3:
        raise ValueError(f"expected (H, W, 3) BGR array, got shape {bmp.shape}")
    rgb = np.ascontiguousarray(bmp[..., ::-1])
    Image.fromarray(rgb).save(str(path))


# ─────────────────────────────────────────────────────────────────
# Anchor picking
# ─────────────────────────────────────────────────────────────────


def _pick_anchor(bmp: np.ndarray) -> Tuple[int, int, Tuple[int, int, int]]:
    """Pick an anchor pixel from `bmp` — the one with the least common
    colour. Uses a quick histogram over quantised colour buckets. Returns
    (dx, dy, bgr) where (dx, dy) is the anchor's offset in the bitmap."""
    bh, bw = bmp.shape[:2]
    if bh == 0 or bw == 0:
        return (0, 0, (0, 0, 0))
    # Quantise to 32 levels per channel for histogram keying.
    quant = (bmp // 8).astype(np.int32)
    flat = quant[..., 0] * 32 * 32 + quant[..., 1] * 32 + quant[..., 2]
    unique, counts = np.unique(flat.reshape(-1), return_counts=True)
    # Find the rarest non-edge pixel (prefer interior anchors).
    order = np.argsort(counts)
    rarest_key = unique[order[0]]
    matches = np.argwhere(flat == rarest_key)
    if matches.size == 0:
        return (0, 0, tuple(int(v) for v in bmp[0, 0]))
    # Prefer pixels not on the outer ring.
    best = matches[0]
    for m in matches:
        y, x = int(m[0]), int(m[1])
        if 0 < y < bh - 1 and 0 < x < bw - 1:
            best = m
            break
    ay, ax = int(best[0]), int(best[1])
    b, g, r = (int(v) for v in bmp[ay, ax])
    return (ax, ay, (b, g, r))


# ─────────────────────────────────────────────────────────────────
# Find
# ─────────────────────────────────────────────────────────────────


def find(
    frame: np.ndarray,
    bitmap: np.ndarray,
    tolerance: int = 5,
    roi: Optional[Tuple[int, int, int, int]] = None,
    max_matches: int = 50,
) -> List[BitmapMatch]:
    """Find every occurrence of `bitmap` in `frame`.

    :param tolerance: per-channel max absolute difference (0 = exact pixel
                      match, 255 = anything goes). 5-15 is typical for
                      UI sprites under mild anti-aliasing.
    """
    if bitmap.ndim != 3 or bitmap.shape[2] != 3:
        raise ValueError("bitmap must be (H, W, 3) BGR uint8")
    bh, bw = bitmap.shape[:2]
    fh, fw = frame.shape[:2]
    if bh > fh or bw > fw:
        return []

    # 1) anchor prefilter via rs3vision color.find (Rust — fast).
    ax, ay, anchor_bgr = _pick_anchor(bitmap)
    anchor_hits = rv.color.find(
        frame, tuple(anchor_bgr), cts=rv.CTS.CTS1, tol=float(tolerance), roi=roi
    )

    # 2) per-candidate exact validation in numpy.
    bmp_int = bitmap.astype(np.int16)
    out: List[BitmapMatch] = []
    for hx, hy, _conf in anchor_hits:
        # Candidate top-left.
        tlx = hx - ax
        tly = hy - ay
        if tlx < 0 or tly < 0 or tlx + bw > fw or tly + bh > fh:
            continue
        window = frame[tly : tly + bh, tlx : tlx + bw].astype(np.int16)
        diff = np.abs(window - bmp_int)
        worst = int(diff.max())
        if worst <= tolerance:
            # Confidence: 1 - mean_difference / tolerance, clamped.
            mean = float(diff.mean())
            conf = max(0.0, 1.0 - (mean / max(1.0, float(tolerance))))
            out.append(BitmapMatch(x=tlx, y=tly, confidence=conf))
            if len(out) >= max_matches:
                break
    return out
