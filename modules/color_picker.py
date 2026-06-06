"""Per-monitor frozen-screenshot eyedropper for picking a target color.

Multi-monitor reality on Windows: a single Toplevel that spans the
virtual desktop with negative-coordinate origin + ``-fullscreen True``
gets snapped to whichever monitor the origin happens to land on, and
the canvas only shows that one monitor's pixels even though the
snapshot covers everything. So instead we create **one Toplevel per
physical monitor**, each pinned to its own monitor with explicit
geometry + ``-overrideredirect`` (no fullscreen flag), each showing
just its own monitor's snapshot. All windows share a single ``_finish``
guard so the first click anywhere wins.

Returns ``(R, G, B), (screen_x, screen_y)`` to ``on_done`` on click,
or ``(None, None)`` on Escape / window-close.
"""

from __future__ import annotations

import tkinter as tk
from typing import Callable, Optional, Tuple

import mss
import numpy as np


class _MonitorOverlay:
    """One Toplevel pinned to one physical monitor. Owns its snapshot,
    canvas, and loupe; delegates `on_pick` / `on_cancel` to the parent
    ``ColorPicker`` so the first event across all monitors wins."""

    def __init__(
        self,
        master: tk.Tk,
        snapshot_rgb: np.ndarray,
        left: int,
        top: int,
        width: int,
        height: int,
        on_pick: Callable[[Tuple[int, int, int], Tuple[int, int]], None],
        on_cancel: Callable[[], None],
    ) -> None:
        self._snapshot_rgb = snapshot_rgb
        self._left = int(left)
        self._top = int(top)
        self._on_pick = on_pick
        self._on_cancel = on_cancel

        self.win = tk.Toplevel(master)
        self.win.configure(bg="#000000", cursor="crosshair")
        self.win.geometry(f"{int(width)}x{int(height)}+{int(left)}+{int(top)}")
        # Borderless + topmost works reliably across monitors on Windows.
        # We deliberately avoid ``-fullscreen`` because Windows rebinds it
        # to a single monitor and stretches/clips the canvas.
        self.win.overrideredirect(True)
        self.win.attributes("-topmost", True)

        self.canvas = tk.Canvas(
            self.win, width=int(width), height=int(height), bg="#000000",
            highlightthickness=0, cursor="crosshair",
        )
        self.canvas.pack(fill="both", expand=True)

        from PIL import Image, ImageTk
        pil = Image.fromarray(snapshot_rgb)
        self._photo = ImageTk.PhotoImage(pil, master=self.win)
        self.canvas.create_image(0, 0, image=self._photo, anchor="nw")

        # Live magnifier — same look as before.
        self._loupe_rect = self.canvas.create_rectangle(
            0, 0, 0, 0, outline="", state="hidden",
        )
        self._loupe_text = self.canvas.create_text(
            0, 0, text="", fill="#ffffff", anchor="nw",
            font=("Segoe UI Variable Text", 11, "bold"),
            state="hidden",
        )
        self._loupe_text_bg = self.canvas.create_rectangle(
            0, 0, 0, 0, fill="#000000", outline="", state="hidden",
        )
        self.canvas.tag_raise(self._loupe_text)

        self.canvas.bind("<Motion>", self._on_motion)
        self.canvas.bind("<Button-1>", self._on_click)
        self.win.bind("<Escape>", lambda e: self._on_cancel())
        self.win.protocol("WM_DELETE_WINDOW", lambda e=None: self._on_cancel())

        self.win.update_idletasks()

    # -- helpers -----------------------------------------------------------

    def _sample(self, canvas_x: int, canvas_y: int
                 ) -> Optional[Tuple[int, int, int]]:
        h, w = self._snapshot_rgb.shape[:2]
        if not (0 <= canvas_x < w and 0 <= canvas_y < h):
            return None
        r, g, b = self._snapshot_rgb[canvas_y, canvas_x]
        return (int(r), int(g), int(b))

    def _on_motion(self, e) -> None:
        rgb = self._sample(e.x, e.y)
        if rgb is None:
            self.canvas.itemconfigure(self._loupe_rect, state="hidden")
            self.canvas.itemconfigure(self._loupe_text, state="hidden")
            self.canvas.itemconfigure(self._loupe_text_bg, state="hidden")
            return
        cx = e.x + 18
        cy = e.y + 18
        hex_color = "#{:02x}{:02x}{:02x}".format(*rgb)
        self.canvas.coords(self._loupe_rect, cx, cy, cx + 38, cy + 38)
        self.canvas.itemconfigure(
            self._loupe_rect, state="normal", fill=hex_color,
            outline="#ffffff", width=2,
        )
        text = f"{hex_color}\nR{rgb[0]} G{rgb[1]} B{rgb[2]}"
        self.canvas.coords(self._loupe_text, cx + 46, cy + 2)
        self.canvas.itemconfigure(
            self._loupe_text, state="normal", text=text,
        )
        bbox = self.canvas.bbox(self._loupe_text)
        if bbox:
            x1, y1, x2, y2 = bbox
            self.canvas.coords(
                self._loupe_text_bg, x1 - 4, y1 - 2, x2 + 4, y2 + 2,
            )
            self.canvas.itemconfigure(self._loupe_text_bg, state="normal")
            self.canvas.tag_raise(self._loupe_text_bg, self._loupe_rect)
            self.canvas.tag_raise(self._loupe_text, self._loupe_text_bg)

    def _on_click(self, e) -> None:
        rgb = self._sample(e.x, e.y)
        if rgb is None:
            return
        screen_xy = (self._left + int(e.x), self._top + int(e.y))
        self._on_pick(rgb, screen_xy)

    def destroy(self) -> None:
        try:
            self.win.destroy()
        except Exception:
            pass


class ColorPicker:
    """Eyedropper across every connected monitor."""

    def __init__(
        self,
        master: tk.Tk,
        on_done: Callable[
            [Optional[Tuple[int, int, int]], Optional[Tuple[int, int]]],
            None,
        ],
    ) -> None:
        self.master = master
        self.on_done = on_done
        self._finished = False
        self._overlays: list[_MonitorOverlay] = []

        # One snapshot per physical monitor so each Toplevel renders only
        # its own pixels — no spanning, no fullscreen-snap surprises.
        with mss.mss() as sct:
            monitors = list(sct.monitors[1:])  # skip [0] = virtual union
            shots = []
            for m in monitors:
                shot = sct.grab(m)
                shots.append((m, shot))

        for m, shot in shots:
            bgra = np.array(shot)
            rgb = bgra[:, :, [2, 1, 0]].copy()  # BGR(A) → RGB
            ov = _MonitorOverlay(
                master=master,
                snapshot_rgb=rgb,
                left=int(m["left"]),
                top=int(m["top"]),
                width=int(m["width"]),
                height=int(m["height"]),
                on_pick=self._on_pick,
                on_cancel=self._on_cancel,
            )
            self._overlays.append(ov)

        # Focus the overlay covering the current cursor position so
        # keyboard (Escape) works without an extra click.
        self._focus_overlay_under_cursor()

    # -- internals ---------------------------------------------------------

    def _focus_overlay_under_cursor(self) -> None:
        try:
            cx = self.master.winfo_pointerx()
            cy = self.master.winfo_pointery()
        except Exception:
            cx = cy = None
        target = None
        if cx is not None and cy is not None:
            for ov in self._overlays:
                if (ov._left <= cx < ov._left + ov._snapshot_rgb.shape[1]
                        and ov._top <= cy < ov._top + ov._snapshot_rgb.shape[0]):
                    target = ov
                    break
        if target is None and self._overlays:
            target = self._overlays[0]
        if target is not None:
            try:
                target.win.focus_force()
            except Exception:
                pass

    def _on_pick(self, rgb: Tuple[int, int, int],
                  screen_xy: Tuple[int, int]) -> None:
        self._finish(rgb, screen_xy)

    def _on_cancel(self) -> None:
        self._finish(None, None)

    def _finish(
        self,
        rgb: Optional[Tuple[int, int, int]],
        screen_xy: Optional[Tuple[int, int]],
    ) -> None:
        if self._finished:
            return
        self._finished = True
        for ov in self._overlays:
            ov.destroy()
        self._overlays = []
        try:
            self.on_done(rgb, screen_xy)
        except Exception:
            pass
