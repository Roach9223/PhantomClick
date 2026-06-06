"""Zone dataclass, draw overlay (rect/circle/polygon), and persistent
click-through marker overlay.

The persistent overlay uses Plan A from the plan:
  - tk.Toplevel with `-transparentcolor` sentinel so pixels outside the
    zone fill are fully invisible.
  - `-alpha` gives the filled area its translucency.
  - WS_EX_LAYERED | WS_EX_TRANSPARENT applied via ctypes so the entire
    window is click-through (game clicks pass through it).
  - Styles are re-asserted on every `show()` because Tk sometimes clobbers
    them during window attribute changes.

If Plan A ever fails (translucent fill not rendering or clicks being
intercepted), swap to a raw Win32 layered window per the plan. Public API
(`show`, `hide`, `update_style`, `set_zone`) stays identical so app.py
doesn't have to change.
"""

from __future__ import annotations

import ctypes
import math
import random
import tkinter as tk
from dataclasses import dataclass, field
from typing import Callable, Literal, Optional

# Extended window style bits.
GWL_EXSTYLE = -20
WS_EX_LAYERED = 0x00080000
WS_EX_TRANSPARENT = 0x00000020
WS_EX_TOOLWINDOW = 0x00000080
WS_EX_NOACTIVATE = 0x08000000

TRANSPARENT_SENTINEL = "#010203"  # pixels in this color become fully invisible


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
    # session — defeats detectors that fingerprint a stationary Gaussian
    # bell. NOT serialized (to_json / from_json ignore these); a fresh
    # session starts at offset 0 / scale 1.0.
    drift_offset_x: float = 0.0
    drift_offset_y: float = 0.0
    sigma_scale: float = 1.0

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
        the edges. Mimics how a real player aims at a button — most
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

        # Per-shape detection of "tight zone" — when the smaller dim is
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
            # samples — most clicks central, occasional toward edges.
            tight_aim = random.random() < 0.75

        if self.shape == "rect":
            x1, y1, x2, y2 = self.rect  # type: ignore[misc]
            cx = (x1 + x2) / 2 + ox
            cy = (y1 + y2) / 2 + oy
            if tight_zone:
                # Sigma in absolute px, not zone-relative — for a 12x12
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
            # Mean drifted near an edge — fall back to the un-drifted center.
            return ((x1 + x2) // 2, (y1 + y2) // 2)

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

    def to_json(self) -> dict:
        return {
            "shape": self.shape,
            "rect": list(self.rect) if self.rect else None,
            "circle": list(self.circle) if self.circle else None,
            "vertices": [list(v) for v in self.vertices],
        }

    @classmethod
    def from_json(cls, d: Optional[dict]) -> Optional["Zone"]:
        if not d:
            return None
        shape = d.get("shape")
        if shape == "rect" and d.get("rect"):
            return cls.make_rect(*d["rect"])
        if shape == "circle" and d.get("circle"):
            return cls.make_circle(*d["circle"])
        if shape == "polygon" and d.get("vertices"):
            return cls.make_polygon([tuple(v) for v in d["vertices"]])
        return None


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


# --------------------------------------------------------------------------- #
# Draw overlay (fullscreen modal for selecting a zone)
# --------------------------------------------------------------------------- #

class ZoneDrawer:
    """Fullscreen overlay that lets the user define a zone.

    `on_done(zone_or_None)` is called with the resulting Zone, or None
    if the user cancelled.
    """

    def __init__(self, master: tk.Tk, shape: str, on_done: Callable[[Optional[Zone]], None]):
        self.master = master
        self.shape = shape  # "rect" | "circle" | "polygon"
        self.on_done = on_done
        self._finished = False

        self.win = tk.Toplevel(master)
        self.win.configure(bg="#000000", cursor="crosshair")
        # Explicit screen-size geometry first (works even if -fullscreen flakes
        # after DPI-awareness changes). Do NOT call overrideredirect on Windows:
        # it recreates the HWND and clears WS_EX_LAYERED, making -alpha a no-op.
        sw = self.win.winfo_screenwidth()
        sh = self.win.winfo_screenheight()
        self.win.geometry(f"{sw}x{sh}+0+0")

        self.canvas = tk.Canvas(
            self.win, bg="#000000", highlightthickness=0, cursor="crosshair",
            width=sw, height=sh,
        )
        self.canvas.pack(fill="both", expand=True)

        # Realize the window before setting layered attributes so Windows
        # actually applies WS_EX_LAYERED + alpha.
        self.win.update_idletasks()
        self.win.deiconify()
        self.win.attributes("-topmost", True)
        self.win.attributes("-alpha", 0.40)
        self.win.attributes("-fullscreen", True)

        self.win.bind("<Escape>", lambda e: self._finish(None))
        # Closing via Alt-F4 / window manager must also restore the main window;
        # default WM_DELETE_WINDOW just destroys the Toplevel without callback.
        self.win.protocol("WM_DELETE_WINDOW", lambda: self._finish(None))

        # Shape-specific state.
        self._start: Optional[tuple[int, int]] = None
        self._preview_id: Optional[int] = None
        self._vertices: list[tuple[int, int]] = []
        self._vertex_dots: list[int] = []
        self._edge_lines: list[int] = []
        self._rubber_id: Optional[int] = None
        self._toast_ids: list[int] = []

        if shape in ("rect", "circle"):
            self.canvas.bind("<ButtonPress-1>", self._drag_start)
            self.canvas.bind("<B1-Motion>", self._drag_move)
            self.canvas.bind("<ButtonRelease-1>", self._drag_end)
        else:  # polygon
            self.canvas.bind("<Button-1>", self._poly_click)
            self.canvas.bind("<Motion>", self._poly_motion)
            self.canvas.bind("<Double-Button-1>", self._poly_close)
            self.canvas.bind("<Button-3>", self._poly_close)
            self.win.bind("<BackSpace>", self._poly_undo)

        # Focus so keybinds work.
        self.win.focus_force()

    # -- rect / circle drag handlers ----------------------------------------

    def _drag_start(self, e):
        self._start = (e.x_root, e.y_root)
        if self._preview_id is not None:
            self.canvas.delete(self._preview_id)
            self._preview_id = None

    def _drag_move(self, e):
        if self._start is None:
            return
        if self._preview_id is not None:
            self.canvas.delete(self._preview_id)
        x1, y1 = self._start
        x2, y2 = e.x_root, e.y_root
        if self.shape == "rect":
            self._preview_id = self.canvas.create_rectangle(
                x1, y1, x2, y2, outline="#22d3ee", width=3, dash=(8, 5)
            )
        else:  # circle
            r = int(math.hypot(x2 - x1, y2 - y1))
            self._preview_id = self.canvas.create_oval(
                x1 - r, y1 - r, x1 + r, y1 + r, outline="#22d3ee", width=3, dash=(8, 5)
            )

    def _drag_end(self, e):
        if self._start is None:
            return
        x1, y1 = self._start
        x2, y2 = e.x_root, e.y_root
        if self.shape == "rect":
            if abs(x2 - x1) < 8 or abs(y2 - y1) < 8:
                self._start = None
                return
            zone = Zone.make_rect(x1, y1, x2, y2)
        else:
            r = int(math.hypot(x2 - x1, y2 - y1))
            if r < 8:
                self._start = None
                return
            zone = Zone.make_circle(x1, y1, r)
        self._finish(zone)

    # -- polygon handlers ---------------------------------------------------

    def _poly_click(self, e):
        x, y = e.x_root, e.y_root
        # Click near the first vertex closes.
        if len(self._vertices) >= 3:
            fx, fy = self._vertices[0]
            if abs(x - fx) <= 8 and abs(y - fy) <= 8:
                self._poly_close()
                return
        self._vertices.append((x, y))
        dot = self.canvas.create_oval(x - 4, y - 4, x + 4, y + 4, fill="#22d3ee", outline="")
        self._vertex_dots.append(dot)
        if len(self._vertices) >= 2:
            px, py = self._vertices[-2]
            line = self.canvas.create_line(px, py, x, y, fill="#22d3ee", width=2, dash=(6, 4))
            self._edge_lines.append(line)

    def _poly_motion(self, e):
        if not self._vertices:
            return
        lx, ly = self._vertices[-1]
        if self._rubber_id is not None:
            self.canvas.delete(self._rubber_id)
        self._rubber_id = self.canvas.create_line(
            lx, ly, e.x_root, e.y_root, fill="#22d3ee", width=1, dash=(3, 3)
        )

    def _poly_undo(self, e=None):
        if not self._vertices:
            return
        self._vertices.pop()
        if self._vertex_dots:
            self.canvas.delete(self._vertex_dots.pop())
        if self._edge_lines:
            self.canvas.delete(self._edge_lines.pop())

    def _poly_close(self, e=None):
        if len(self._vertices) < 3:
            self._toast("Need at least 3 vertices")
            return
        if polygon_self_intersects(self._vertices):
            self._toast("Edges cross — redraw")
            self._poly_reset()
            return
        self._finish(Zone.make_polygon(self._vertices))

    def _poly_reset(self):
        for d in self._vertex_dots:
            self.canvas.delete(d)
        for l in self._edge_lines:
            self.canvas.delete(l)
        if self._rubber_id is not None:
            self.canvas.delete(self._rubber_id)
            self._rubber_id = None
        self._vertex_dots.clear()
        self._edge_lines.clear()
        self._vertices.clear()

    def _toast(self, msg: str):
        for tid in self._toast_ids:
            self.canvas.delete(tid)
        self._toast_ids.clear()
        w = self.canvas.winfo_screenwidth()
        bg = self.canvas.create_rectangle(
            w // 2 - 180, 40, w // 2 + 180, 80, fill="#22d3ee", outline=""
        )
        txt = self.canvas.create_text(
            w // 2, 60, text=msg, fill="#ffffff", font=("Segoe UI", 14, "bold")
        )
        self._toast_ids = [bg, txt]
        self.win.after(1200, lambda: [self.canvas.delete(t) for t in self._toast_ids])

    # -- finish -------------------------------------------------------------

    def _finish(self, zone: Optional[Zone]):
        if self._finished:
            return
        self._finished = True
        try:
            self.win.destroy()
        except tk.TclError:
            pass
        self.on_done(zone)


# --------------------------------------------------------------------------- #
# Persistent click-through zone marker overlay
# --------------------------------------------------------------------------- #

class ZoneOverlay:
    """Always-on-top, click-through window that marks the active zone.

    Click-through is guaranteed by WS_EX_LAYERED | WS_EX_TRANSPARENT
    applied via ctypes. Visual transparency outside the zone shape uses
    a sentinel transparentcolor. The whole window's opacity is controlled
    by `-alpha` so the filled area appears translucent.
    """

    def __init__(self, master: tk.Tk):
        self.master = master
        self.win: Optional[tk.Toplevel] = None
        self.canvas: Optional[tk.Canvas] = None
        self.zone: Optional[Zone] = None
        self.color: str = "#22d3ee"
        self.opacity: float = 0.25
        self.label: str = "PhantomClick Zone"

    # -- public API ---------------------------------------------------------

    def show(self, zone: Zone, color: str, opacity: float,
             label: str = "PhantomClick Zone") -> None:
        self.zone = zone
        self.color = color
        self.opacity = opacity
        self.label = label
        if self.win is None:
            self._create_window()
        # Undo any previous hide() (which withdrew the window) and re-assert
        # topmost — Tk can drop it across withdraw/deiconify cycles on Windows.
        self.win.deiconify()
        self.win.attributes("-topmost", True)
        self._redraw()
        self._apply_click_through()

    def hide(self) -> None:
        if self.win is not None:
            try:
                self.win.withdraw()
            except tk.TclError:
                pass

    def destroy(self) -> None:
        if self.win is not None:
            try:
                self.win.destroy()
            except tk.TclError:
                pass
            self.win = None
            self.canvas = None

    def update_style(self, color: str, opacity: float) -> None:
        self.color = color
        self.opacity = opacity
        if self.win is None or self.zone is None:
            return
        self._redraw()
        self._apply_click_through()

    def set_zone(self, zone: Zone) -> None:
        self.zone = zone
        if self.win is None or self.zone is None:
            return
        self._redraw()
        self._apply_click_through()

    # -- internals ----------------------------------------------------------

    def _create_window(self) -> None:
        w = tk.Toplevel(self.master)
        w.overrideredirect(True)
        w.attributes("-topmost", True)
        w.attributes("-transparentcolor", TRANSPARENT_SENTINEL)
        w.configure(bg=TRANSPARENT_SENTINEL)
        # Fullscreen primary monitor.
        sw = w.winfo_screenwidth()
        sh = w.winfo_screenheight()
        w.geometry(f"{sw}x{sh}+0+0")
        self.canvas = tk.Canvas(
            w, bg=TRANSPARENT_SENTINEL, highlightthickness=0, width=sw, height=sh
        )
        self.canvas.pack(fill="both", expand=True)
        self.win = w

    def _apply_click_through(self) -> None:
        """Assert layered + transparent styles on the overlay's HWND."""
        if self.win is None:
            return
        try:
            self.win.update_idletasks()
            hwnd = ctypes.windll.user32.GetParent(self.win.winfo_id())
            if not hwnd:
                hwnd = self.win.winfo_id()
            ex_style = ctypes.windll.user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
            new_style = ex_style | WS_EX_LAYERED | WS_EX_TRANSPARENT | WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE
            ctypes.windll.user32.SetWindowLongW(hwnd, GWL_EXSTYLE, new_style)
        except Exception:
            pass

    def _redraw(self) -> None:
        if self.canvas is None or self.zone is None:
            return
        c = self.canvas
        c.delete("all")

        color = self.color
        # Window -alpha gives the filled region its translucency. Outside pixels
        # use the transparentcolor sentinel and stay fully invisible regardless.
        try:
            self.win.attributes("-alpha", max(0.05, min(1.0, self.opacity)))
        except Exception:
            pass

        if self.zone.shape == "rect":
            x1, y1, x2, y2 = self.zone.rect  # type: ignore[misc]
            c.create_rectangle(x1, y1, x2, y2, fill=color, outline="")
            c.create_rectangle(x1, y1, x2, y2, outline=color, width=2, dash=(8, 4))
            self._draw_label_pill(x1 + 4, max(0, y1 - 22), color)
        elif self.zone.shape == "circle":
            cx, cy, r = self.zone.circle  # type: ignore[misc]
            c.create_oval(cx - r, cy - r, cx + r, cy + r, fill=color, outline="")
            c.create_oval(cx - r, cy - r, cx + r, cy + r, outline=color, width=2, dash=(8, 4))
            self._draw_label_pill(cx - r + 4, max(0, cy - r - 22), color)
        else:
            flat = [p for v in self.zone.vertices for p in v]
            if len(flat) >= 6:
                c.create_polygon(*flat, fill=color, outline="")
                # Dashed outline via separate line items.
                n = len(self.zone.vertices)
                for i in range(n):
                    x1, y1 = self.zone.vertices[i]
                    x2, y2 = self.zone.vertices[(i + 1) % n]
                    c.create_line(x1, y1, x2, y2, fill=color, width=2, dash=(8, 4))
                vx, vy = self.zone.vertices[0]
                self._draw_label_pill(vx + 4, max(0, vy - 22), color)

    def _draw_label_pill(self, x: int, y: int, color: str) -> None:
        """Filled pill behind the label so it stays readable against any game
        background. Pill matches the zone color, text is white inside it."""
        if self.canvas is None or not self.label:
            return
        c = self.canvas
        font = ("Segoe UI", 10, "bold")
        # Measure approx text width — Tk's create_text doesn't report bbox
        # before drawing, so we draw, measure, then move/wrap a backing pill.
        tid = c.create_text(x + 8, y + 4, text=self.label,
                             anchor="nw", fill="#ffffff", font=font)
        bx1, by1, bx2, by2 = c.bbox(tid)
        c.create_rectangle(bx1 - 6, by1 - 3, bx2 + 6, by2 + 3,
                            fill=color, outline="")
        c.tag_raise(tid)
