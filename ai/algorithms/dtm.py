"""DTM — Deformable Template Matching.

A DTM is a tiny recipe describing a visual element by a handful of
coloured points in a rigid relative layout. Example: an anvil has a
dark grey top-left corner, a bright orange hot-spot in the middle, and
a dark grey bottom-right corner. Those three points + their offsets
uniquely identify an anvil in a scene — far more robust than a single
colour match and far cheaper than a full bitmap.

A template is:

    name, anchor{ color, tol, cts }, points[ {dx, dy, color, tol, cts}, ... ]

Serialised as YAML (our `.rvscript` format's cousin) — human-readable,
diffable, hand-editable.

Matching procedure:
  1. Prefilter the frame for the anchor colour via `rv.color.find`.
  2. For each anchor candidate, check each secondary point at its
     offset. If every point matches within its tolerance, it's a hit.

The Studio ships this as `rs3vision_studio.algorithms.dtm.find`; the
`dtm.find` Studio block wraps it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional, Tuple

import numpy as np
import yaml

import rs3vision as rv


# ─────────────────────────────────────────────────────────────────
# Types
# ─────────────────────────────────────────────────────────────────


@dataclass
class DtmPoint:
    dx: int = 0
    dy: int = 0
    color: int = 0xFFFFFF  # 0xRRGGBB
    tol: float = 10.0
    cts: int = 2  # 1, 2, or 3

    def to_dict(self) -> dict:
        return {
            "dx": int(self.dx),
            "dy": int(self.dy),
            "color": f"0x{self.color:06X}",
            "tol": float(self.tol),
            "cts": int(self.cts),
        }

    @classmethod
    def from_dict(cls, d: dict) -> "DtmPoint":
        color = d.get("color", 0xFFFFFF)
        if isinstance(color, str):
            s = color.strip().lower()
            if s.startswith("#"):
                s = s[1:]
            if s.startswith("0x"):
                s = s[2:]
            color = int(s, 16)
        return cls(
            dx=int(d.get("dx", 0)),
            dy=int(d.get("dy", 0)),
            color=int(color),
            tol=float(d.get("tol", 10.0)),
            cts=int(d.get("cts", 2)),
        )


@dataclass
class Template:
    name: str = ""
    anchor: DtmPoint = field(default_factory=DtmPoint)
    points: List[DtmPoint] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "dtm": 1,
            "name": self.name,
            "anchor": self.anchor.to_dict(),
            "points": [p.to_dict() for p in self.points],
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Template":
        return cls(
            name=str(d.get("name", "")),
            anchor=DtmPoint.from_dict(d.get("anchor", {})),
            points=[DtmPoint.from_dict(p) for p in d.get("points", [])],
        )


@dataclass
class DtmMatch:
    x: int  # anchor position in frame coords
    y: int
    confidence: float


# ─────────────────────────────────────────────────────────────────
# YAML I/O
# ─────────────────────────────────────────────────────────────────


def load(path: Path | str) -> Template:
    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    return Template.from_dict(raw)


def save(template: Template, path: Path | str) -> None:
    Path(path).write_text(
        yaml.safe_dump(template.to_dict(), sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )


# ─────────────────────────────────────────────────────────────────
# Template synthesis from an image ROI — user UX helper
# ─────────────────────────────────────────────────────────────────


def build_from_roi(
    frame: np.ndarray,
    roi: Tuple[int, int, int, int],
    name: str = "new_template",
    points: int = 5,
) -> Template:
    """Sample `points` pixels from inside `roi` and build a Template.

    Picks the anchor as the rarest-colour pixel in the ROI (easier to
    find later). Adds `points - 1` secondary samples from evenly-spaced
    positions. User can edit the resulting YAML by hand to refine.
    """
    x, y, w, h = roi
    if w < 3 or h < 3:
        raise ValueError("ROI too small to build a template from (need ≥3×3).")
    patch = frame[y : y + h, x : x + w]

    # Anchor: rarest-colour pixel in patch.
    quant = (patch // 8).astype(np.int32)
    flat = quant[..., 0] * 32 * 32 + quant[..., 1] * 32 + quant[..., 2]
    unique, counts = np.unique(flat.reshape(-1), return_counts=True)
    rarest_key = unique[np.argmin(counts)]
    locs = np.argwhere(flat == rarest_key)
    ay, ax = int(locs[0, 0]), int(locs[0, 1])
    b, g, r = (int(v) for v in patch[ay, ax])
    anchor = DtmPoint(
        dx=0, dy=0,
        color=(r << 16) | (g << 8) | b,
        tol=6.0, cts=1,  # CTS1 is fastest; tight tol keeps anchor specific
    )

    # Secondary points: evenly-spaced samples (excluding the anchor position).
    n = max(0, int(points) - 1)
    secondary: List[DtmPoint] = []
    if n > 0:
        # Choose n positions in a grid.
        cols = max(1, int(np.ceil(np.sqrt(n))))
        rows = int(np.ceil(n / cols))
        count = 0
        for gy in range(rows):
            for gx in range(cols):
                if count >= n:
                    break
                # Place inside the patch, biased toward centre.
                py = int((gy + 0.5) * h / rows)
                px = int((gx + 0.5) * w / cols)
                if py == ay and px == ax:
                    continue
                b2, g2, r2 = (int(v) for v in patch[py, px])
                secondary.append(
                    DtmPoint(
                        dx=px - ax,
                        dy=py - ay,
                        color=(r2 << 16) | (g2 << 8) | b2,
                        tol=12.0, cts=2,  # CTS2 for perceptual matching
                    )
                )
                count += 1

    return Template(name=name, anchor=anchor, points=secondary)


# ─────────────────────────────────────────────────────────────────
# Match
# ─────────────────────────────────────────────────────────────────


def _hex_to_bgr(hex_rgb: int) -> Tuple[int, int, int]:
    r = (hex_rgb >> 16) & 0xFF
    g = (hex_rgb >> 8) & 0xFF
    b = hex_rgb & 0xFF
    return (b, g, r)


def find(
    frame: np.ndarray,
    template: Template,
    roi: Optional[Tuple[int, int, int, int]] = None,
    max_matches: int = 10,
    cluster_dist: int = 4,
) -> List[DtmMatch]:
    """Find every position where `template` matches in `frame`."""
    fh, fw = frame.shape[:2]
    anchor_bgr = _hex_to_bgr(template.anchor.color)
    anchor_hits = rv.color.find(
        frame,
        anchor_bgr,
        cts=template.anchor.cts,
        tol=template.anchor.tol,
        roi=roi,
    )
    if not anchor_hits:
        return []

    # Cluster anchor hits so we don't evaluate thousands of adjacent pixels.
    pts = [(x, y) for x, y, _ in anchor_hits]
    clusters = rv.tpa.cluster(pts, dist=cluster_dist) if pts else []
    candidate_centers = []
    for c in clusters:
        cx, cy = rv.tpa.centroid(c)
        candidate_centers.append((int(round(cx)), int(round(cy))))

    out: List[DtmMatch] = []
    for ax, ay in candidate_centers:
        total = 1  # anchor counts
        matched = 1
        conf_sum = 1.0
        for p in template.points:
            px = ax + p.dx
            py = ay + p.dy
            if not (0 <= px < fw and 0 <= py < fh):
                # Point falls outside frame — fail.
                matched = 0
                break
            # Single-pixel check via one-hit rv.color.find on a 1×1 ROI.
            bgr = _hex_to_bgr(p.color)
            hits = rv.color.find(
                frame, bgr, cts=p.cts, tol=p.tol, roi=(px, py, 1, 1)
            )
            if hits:
                total += 1
                matched += 1
                conf_sum += hits[0][2]
            else:
                total += 1
                # All secondary points must match — break on any miss.
                matched = 0
                break
        if matched == len(template.points) + 1:  # anchor + all points
            conf = conf_sum / total if total > 0 else 0.0
            out.append(DtmMatch(x=ax, y=ay, confidence=conf))
            if len(out) >= max_matches:
                break
    return out
