"""Zone dataclass: the geometry a click lands inside.

Three shapes (rect, circle, polygon) share one API: ``contains``,
``aabb``, ``centroid``, ``random_point`` and JSON (de)serialization.
The engine, the recorder, and the Qt overlays all import ``Zone`` from
here, so this module must stay free of GUI imports. The Tk-era
``ZoneDrawer`` / ``ZoneOverlay`` that used to live here were replaced
by ``ui/overlays/zone_drawer.py`` and ``ui/overlays/zone_overlay.py``.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass, field, replace
from typing import Literal, Optional


# Window lock

LOCK_MODE_SCREEN = "screen"
LOCK_MODE_WINDOW = "window"


@dataclass(frozen=True)
class WindowLock:
    """Ties a zone to the top-level window it was drawn over.

    ``anchor_rect`` is that window's DIP rect ``(x, y, w, h)`` at draw
    time. When the window later sits somewhere else (or at another size)
    the zone is translated and scaled from the anchor to the new rect, so
    the click area rides along with the window. ``title`` and ``cls`` are
    what the finder searches for; the hwnd is deliberately not stored
    because it does not survive a game restart.
    """
    title: str
    cls: str
    anchor_rect: tuple[int, int, int, int]

    def to_json(self) -> dict:
        return {
            "mode": LOCK_MODE_WINDOW,
            "title": self.title,
            "cls": self.cls,
            "anchor_rect": [int(v) for v in self.anchor_rect],
        }

    @classmethod
    def from_json(cls, d: object) -> Optional["WindowLock"]:
        if not isinstance(d, dict) or d.get("mode") != LOCK_MODE_WINDOW:
            return None
        rect = d.get("anchor_rect")
        if not isinstance(rect, (list, tuple)) or len(rect) != 4:
            return None
        try:
            anchor = tuple(int(v) for v in rect)
        except (TypeError, ValueError):
            return None
        return cls(title=str(d.get("title") or ""),
                   cls=str(d.get("cls") or ""),
                   anchor_rect=anchor)  # type: ignore[arg-type]


# --------------------------------------------------------------------------- #
# Zone data type
# --------------------------------------------------------------------------- #

@dataclass
class Zone:
    shape: Literal["rect", "circle", "polygon"]
    # rect: (x1, y1, x2, y2); circle: (cx, cy, radius) in first 3 slots;
    # polygon: vertices populated instead.
    rect: Optional[tuple[int, int, int, int]] = None
    circle: Optional[tuple[int, int, int]] = None  # (cx, cy, radius)
    vertices: list[tuple[int, int]] = field(default_factory=list)
    # Non-stationary sampling state. The engine mutates these on the live
    # Zone before each cycle to make the click distribution drift over a
    # session, defeats detectors that fingerprint a stationary Gaussian
    # bell. NOT serialized (to_json / from_json ignore these); a fresh
    # session starts at offset 0 / scale 1.0.
    drift_offset_x: float = 0.0
    drift_offset_y: float = 0.0
    sigma_scale: float = 1.0
    # None means the zone is pinned to screen coordinates (the original
    # behaviour). A WindowLock means the stored geometry is relative to
    # ``lock.anchor_rect`` and must go through ``rebased`` before use.
    lock: Optional[WindowLock] = None

    @classmethod
    def make_rect(cls, x1: int, y1: int, x2: int, y2: int) -> "Zone":
        x1, x2 = sorted((x1, x2))
        y1, y2 = sorted((y1, y2))
        return cls(shape="rect", rect=(x1, y1, x2, y2))

    @classmethod
    def make_circle(cls, cx: int, cy: int, radius: int) -> "Zone":
        return cls(shape="circle", circle=(cx, cy, max(2, radius)))

    @classmethod
    def make_polygon(cls, vertices: list[tuple[int, int]]) -> "Zone":
        return cls(shape="polygon", vertices=list(vertices))

    def aabb(self) -> tuple[int, int, int, int]:
        if self.shape == "rect":
            return self.rect  # type: ignore[return-value]
        if self.shape == "circle":
            cx, cy, r = self.circle  # type: ignore[misc]
            return (cx - r, cy - r, cx + r, cy + r)
        xs = [v[0] for v in self.vertices]
        ys = [v[1] for v in self.vertices]
        return (min(xs), min(ys), max(xs), max(ys))

    def centroid(self) -> tuple[int, int]:
        if self.shape == "rect":
            x1, y1, x2, y2 = self.rect  # type: ignore[misc]
            return ((x1 + x2) // 2, (y1 + y2) // 2)
        if self.shape == "circle":
            cx, cy, _ = self.circle  # type: ignore[misc]
            return (cx, cy)
        # Polygon: signed-area (true geometric) centroid. Mean-of-vertices
        # is biased toward dense corners and can land outside concave shapes;
        # the signed-area formula matches the visual center for convex
        # polygons. If the result still falls outside (deep concavity),
        # fall back to a vertex-midpoint that IS inside.
        n = len(self.vertices)
        if n < 3:
            xs = [v[0] for v in self.vertices] or [0]
            ys = [v[1] for v in self.vertices] or [0]
            return (sum(xs) // len(xs), sum(ys) // len(ys))
        a = 0.0
        cx = 0.0
        cy = 0.0
        for i in range(n):
            x0, y0 = self.vertices[i]
            x1, y1 = self.vertices[(i + 1) % n]
            cross = x0 * y1 - x1 * y0
            a += cross
            cx += (x0 + x1) * cross
            cy += (y0 + y1) * cross
        a *= 0.5
        if abs(a) < 1e-6:
            xs = [v[0] for v in self.vertices]
            ys = [v[1] for v in self.vertices]
            return (sum(xs) // n, sum(ys) // n)
        gx = int(round(cx / (6.0 * a)))
        gy = int(round(cy / (6.0 * a)))
        if _point_in_polygon(gx, gy, self.vertices):
            return (gx, gy)
        # Concave + centroid outside. Try midpoints of non-adjacent vertex
        # pairs; one of these is guaranteed to lie inside any simple
        # polygon (it's how ear-clipping finds an interior diagonal).
        for i in range(n):
            for j in range(i + 2, n):
                if i == 0 and j == n - 1:
                    continue  # adjacent
                mx = (self.vertices[i][0] + self.vertices[j][0]) // 2
                my = (self.vertices[i][1] + self.vertices[j][1]) // 2
                if _point_in_polygon(mx, my, self.vertices):
                    return (mx, my)
        return (gx, gy)

    def contains(self, x: int, y: int) -> bool:
        if self.shape == "rect":
            x1, y1, x2, y2 = self.rect  # type: ignore[misc]
            return x1 <= x <= x2 and y1 <= y <= y2
        if self.shape == "circle":
            cx, cy, r = self.circle  # type: ignore[misc]
            return (x - cx) ** 2 + (y - cy) ** 2 <= r * r
        return _point_in_polygon(x, y, self.vertices)

    def _smaller_dim(self) -> int:
        """Smaller of the zone's two AABB dimensions, in px. Used by
        ``random_point`` to detect "tight" zones where the user wants
        clicks concentrated on the geometric center rather than spread
        with a per-zone-relative Gaussian."""
        try:
            x1, y1, x2, y2 = self.aabb()
            return max(1, min(x2 - x1, y2 - y1))
        except Exception:
            return 9999

    def random_point(self) -> tuple[int, int]:
        """Gaussian-biased random point inside the zone.

        Bimodal aim distribution: 75 % of samples use a tight Gaussian
        (σ ≈ W/8 for rects, r/5 for circles) so most clicks land in the
        central region of the zone; 25 % use a wider Gaussian (σ ≈ W/4
        for rects, r/3 for circles) so occasional clicks drift toward
        the edges. Mimics how a real player aims at a button, most
        attempts hit the visual center deliberately, with rare looser
        attempts.

        Applies the engine-mutable ``drift_offset_x/y`` to the Gaussian
        mean and ``sigma_scale`` to its spread so the distribution can
        slowly walk across a session. Defaults (0, 0, 1.0) reproduce the
        original stationary Gaussian.
        """
        sscale = max(0.5, min(2.5, float(self.sigma_scale)))
        ox = float(self.drift_offset_x)
        oy = float(self.drift_offset_y)

        # Per-shape detection of "tight zone", when the smaller dim is
        # small enough that the actual game element fills most or all of
        # the zone, we use a very tight 90/10 split (vs the normal 75/25)
        # so clicks reliably land on the element. The relaxed 10% still
        # uses a non-trivial sigma so the click distribution isn't a
        # single pixel (which would itself be a strong bot tell).
        tight_zone = self._smaller_dim() <= 16

        if tight_zone:
            tight_aim = random.random() < 0.90
        else:
            # Tight (centered) vs. relaxed (broader) aim. Rolled per-call
            # so the same zone produces a bimodal distribution over many
            # samples, most clicks central, occasional toward edges.
            tight_aim = random.random() < 0.75

        if self.shape == "rect":
            x1, y1, x2, y2 = self.rect  # type: ignore[misc]
            cx = (x1 + x2) / 2 + ox
            cy = (y1 + y2) / 2 + oy
            if tight_zone:
                # Sigma in absolute px, not zone-relative, for a 12x12
                # zone we want σ ≈ 1.2 px (95% of clicks within ±2.4 px
                # of center), not σ = W/8 = 1.5 px which is similar but
                # scales weirdly at the smallest sizes. The 10% relaxed
                # path still uses a wider sigma so the distribution
                # isn't a hard cluster.
                sx = sy = (1.0 if tight_aim else 2.5) * sscale
            else:
                divisor = 8.0 if tight_aim else 4.0
                sx = ((x2 - x1) / divisor or 1) * sscale
                sy = ((y2 - y1) / divisor or 1) * sscale
            for _ in range(20):
                x = int(round(random.gauss(cx, sx)))
                y = int(round(random.gauss(cy, sy)))
                if x1 <= x <= x2 and y1 <= y <= y2:
                    return (x, y)
            # Mean drifted near an edge. Fall back to the un-drifted center
            # with a small jitter so repeated fallbacks never stack on the
            # same pixel (a fixed point is its own fingerprint).
            cx0 = (x1 + x2) / 2
            cy0 = (y1 + y2) / 2
            jx = min(2.0, max(0.0, (x2 - x1) / 4))
            jy = min(2.0, max(0.0, (y2 - y1) / 4))
            x = int(round(cx0 + random.uniform(-jx, jx)))
            y = int(round(cy0 + random.uniform(-jy, jy)))
            return (min(x2, max(x1, x)), min(y2, max(y1, y)))

        if self.shape == "circle":
            # Polar-coord sampling to avoid a square bias inside the circle.
            cx, cy, r = self.circle  # type: ignore[misc]
            theta = random.uniform(0, 2 * math.pi)
            if tight_zone:
                # Keep most clicks within ~r/3 of center via a small
                # absolute sigma; relaxed path still uses the wider r/3.
                sigma_r = (r / 8.0 if tight_aim else r / 3.0) * sscale
            else:
                divisor = 5.0 if tight_aim else 3.0
                sigma_r = (r / divisor) * sscale
            radius = abs(random.gauss(0, sigma_r))
            radius = min(radius, r - 1)
            x = cx + ox + radius * math.cos(theta)
            y = cy + oy + radius * math.sin(theta)
            # Clamp drifted point back inside the original circle so we
            # never return a coord outside the user-defined zone.
            dx = x - cx
            dy = y - cy
            d = math.hypot(dx, dy)
            if d > r - 1 and d > 0:
                k = (r - 1) / d
                x = cx + dx * k
                y = cy + dy * k
            return (int(round(x)), int(round(y)))

        # Polygon: rejection sampling within AABB, biased toward centroid.
        x1, y1, x2, y2 = self.aabb()
        cx, cy = self.centroid()
        cx_d = cx + ox
        cy_d = cy + oy
        if tight_zone:
            sx = sy = (1.0 if tight_aim else 2.5) * sscale
        else:
            divisor = 8.0 if tight_aim else 4.0
            sx = max(1.0, (x2 - x1) / divisor) * sscale
            sy = max(1.0, (y2 - y1) / divisor) * sscale
        for _ in range(50):
            x = int(round(random.gauss(cx_d, sx)))
            y = int(round(random.gauss(cy_d, sy)))
            if _point_in_polygon(x, y, self.vertices):
                return (x, y)
        # Fallback: uniform within AABB (better hit-rate for narrow shapes).
        for _ in range(500):
            x = random.randint(x1, x2)
            y = random.randint(y1, y2)
            if _point_in_polygon(x, y, self.vertices):
                return (x, y)
        # Last-resort: the centroid is guaranteed-inside for non-degenerate
        # polygons (centroid() falls back to an inside vertex-midpoint).
        return (cx, cy)

    # Window lock

    def with_lock(self, lock: Optional[WindowLock]) -> "Zone":
        """Copy of this zone with ``lock`` replaced (None = screen lock)."""
        return replace(self, lock=lock, vertices=list(self.vertices))

    def rebased(self, new_rect: tuple[int, int, int, int]) -> "Zone":
        """Copy translated and scaled from ``lock.anchor_rect`` to ``new_rect``.

        Scale is per axis, so a window that only grew wider stretches the
        zone only horizontally. A circle takes the mean of the two scales
        for its radius because it has no per-axis radius. The copy keeps
        the same lock (anchor included) so a later rebase still measures
        from the original draw, not from an intermediate position. A zone
        with no lock is returned as-is.
        """
        if self.lock is None:
            return self
        ax, ay, aw, ah = self.lock.anchor_rect
        nx, ny, nw, nh = new_rect
        sx = (nw / aw) if aw > 0 else 1.0
        sy = (nh / ah) if ah > 0 else 1.0

        def tx(x: float) -> int:
            return int(round(nx + (x - ax) * sx))

        def ty(y: float) -> int:
            return int(round(ny + (y - ay) * sy))

        rect = None
        circle = None
        vertices: list[tuple[int, int]] = []
        if self.shape == "rect" and self.rect is not None:
            x1, y1, x2, y2 = self.rect
            rect = (tx(x1), ty(y1), tx(x2), ty(y2))
        elif self.shape == "circle" and self.circle is not None:
            cx, cy, r = self.circle
            circle = (tx(cx), ty(cy), max(2, int(round(r * (sx + sy) / 2.0))))
        else:
            vertices = [(tx(vx), ty(vy)) for vx, vy in self.vertices]
        return Zone(
            shape=self.shape, rect=rect, circle=circle, vertices=vertices,
            drift_offset_x=self.drift_offset_x,
            drift_offset_y=self.drift_offset_y,
            sigma_scale=self.sigma_scale,
            lock=self.lock,
        )

    # Serialization

    def to_json(self) -> dict:
        out = {
            "shape": self.shape,
            "rect": list(self.rect) if self.rect else None,
            "circle": list(self.circle) if self.circle else None,
            "vertices": [list(v) for v in self.vertices],
        }
        # Only written when set: unlocked zones keep the exact shape older
        # builds wrote, so a config that never used locks does not churn.
        if self.lock is not None:
            out["lock"] = self.lock.to_json()
        return out

    @classmethod
    def from_json(cls, d: Optional[dict]) -> Optional["Zone"]:
        if not d:
            return None
        shape = d.get("shape")
        zone: Optional[Zone] = None
        if shape == "rect" and d.get("rect"):
            zone = cls.make_rect(*d["rect"])
        elif shape == "circle" and d.get("circle"):
            zone = cls.make_circle(*d["circle"])
        elif shape == "polygon" and d.get("vertices"):
            zone = cls.make_polygon([tuple(v) for v in d["vertices"]])
        if zone is None:
            return None
        # Absent key or {"mode": "screen"} both mean screen lock.
        zone.lock = WindowLock.from_json(d.get("lock"))
        return zone

    # Aliases matching the naming used elsewhere in the docs.
    to_dict = to_json
    from_dict = from_json


def _point_in_polygon(x: float, y: float, verts: list[tuple[int, int]]) -> bool:
    """Ray-casting point-in-polygon. Handles concave polygons."""
    n = len(verts)
    if n < 3:
        return False
    inside = False
    j = n - 1
    for i in range(n):
        xi, yi = verts[i]
        xj, yj = verts[j]
        if ((yi > y) != (yj > y)) and (x < (xj - xi) * (y - yi) / (yj - yi + 1e-12) + xi):
            inside = not inside
        j = i
    return inside


def _segments_intersect(p1, p2, p3, p4) -> bool:
    """True if segment p1-p2 properly intersects segment p3-p4."""
    def ccw(a, b, c):
        return (c[1] - a[1]) * (b[0] - a[0]) > (b[1] - a[1]) * (c[0] - a[0])
    return ccw(p1, p3, p4) != ccw(p2, p3, p4) and ccw(p1, p2, p3) != ccw(p1, p2, p4)


def polygon_self_intersects(verts: list[tuple[int, int]]) -> bool:
    n = len(verts)
    if n < 4:
        return False
    edges = [(verts[i], verts[(i + 1) % n]) for i in range(n)]
    for i in range(n):
        for j in range(i + 1, n):
            if abs(i - j) <= 1 or (i == 0 and j == n - 1):
                continue  # adjacent edges share an endpoint; skip
            if _segments_intersect(edges[i][0], edges[i][1], edges[j][0], edges[j][1]):
                return True
    return False
