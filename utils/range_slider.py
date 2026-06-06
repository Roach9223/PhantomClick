"""Dual-thumb range slider widget that fits the CTk dark theme.

Built on tk.Canvas because customtkinter has no native range slider. The two
thumbs cannot cross — dragging the min thumb past max clamps it to max, and
vice versa. Emits `command(min_val, max_val)` on every change.
"""

from __future__ import annotations

import tkinter as tk
from typing import Callable, Optional

import customtkinter as ctk

import theme


_THUMB_R = 9
_TRACK_H = 6


class RangeSlider(ctk.CTkFrame):
    def __init__(
        self,
        master,
        from_: float = 0.0,
        to: float = 100.0,
        init_min: float = 0.0,
        init_max: float = 100.0,
        number_of_steps: Optional[int] = None,
        command: Optional[Callable[[float, float], None]] = None,
        height: int = 28,
        bg_color: str = theme.CARD_BG,
        track_color: str = theme.SLIDER_TRACK,
        fill_color: str = theme.ACCENT,
        thumb_color: str = theme.SLIDER_THUMB,
        **kwargs,
    ):
        super().__init__(master, fg_color="transparent", height=height, **kwargs)
        self.from_ = float(from_)
        self.to = float(to)
        self.command = command
        self.number_of_steps = number_of_steps
        self._track_color = track_color
        self._fill_color = fill_color
        self._thumb_color = thumb_color

        self.min_val = self._clamp(float(init_min))
        self.max_val = self._clamp(float(init_max))
        if self.max_val < self.min_val:
            self.max_val = self.min_val

        self._dragging: Optional[str] = None
        self._suppress_command = False
        # Which thumb has keyboard focus. Click or Tab updates it; arrow keys
        # nudge whichever thumb is focused. None means the slider isn't focused.
        self._focused_thumb: Optional[str] = None

        self.canvas = tk.Canvas(
            self, height=height, bg=bg_color, highlightthickness=0, bd=0,
            takefocus=True,
        )
        self.canvas.pack(fill="both", expand=True)
        self.canvas.bind("<Configure>", lambda e: self._redraw())
        self.canvas.bind("<Button-1>", self._on_press)
        self.canvas.bind("<B1-Motion>", self._on_drag)
        self.canvas.bind("<ButtonRelease-1>", self._on_release)
        self.canvas.bind("<FocusIn>", self._on_focus_in)
        self.canvas.bind("<FocusOut>", self._on_focus_out)
        self.canvas.bind("<Left>", lambda e: self._nudge(-1, e))
        self.canvas.bind("<Right>", lambda e: self._nudge(+1, e))
        self.canvas.bind("<Shift-Left>", lambda e: self._nudge(-10, e))
        self.canvas.bind("<Shift-Right>", lambda e: self._nudge(+10, e))
        # Tab swaps which thumb is focused before falling through to the next
        # widget — return "break" only when we've consumed the key.
        self.canvas.bind("<Tab>", self._on_tab)
        self.canvas.bind("<Shift-Tab>", self._on_tab)

    # -- public API ---------------------------------------------------------

    def get(self) -> tuple[float, float]:
        return (self.min_val, self.max_val)

    def set(self, min_val: float, max_val: float) -> None:
        self._suppress_command = True
        self.min_val = self._clamp(float(min_val))
        self.max_val = self._clamp(float(max_val))
        if self.max_val < self.min_val:
            self.max_val = self.min_val
        self._redraw()
        self._suppress_command = False

    # -- internals ----------------------------------------------------------

    def _clamp(self, v: float) -> float:
        v = max(self.from_, min(v, self.to))
        if self.number_of_steps and self.to > self.from_:
            step = (self.to - self.from_) / self.number_of_steps
            if step > 0:
                v = round((v - self.from_) / step) * step + self.from_
        return v

    def _track_x_bounds(self) -> tuple[int, int]:
        w = self.canvas.winfo_width()
        return (_THUMB_R + 2, max(_THUMB_R + 4, w - _THUMB_R - 2))

    def _val_to_x(self, val: float) -> float:
        x1, x2 = self._track_x_bounds()
        rng = self.to - self.from_
        if rng <= 0:
            return float(x1)
        ratio = (val - self.from_) / rng
        return x1 + ratio * (x2 - x1)

    def _x_to_val(self, x: float) -> float:
        x1, x2 = self._track_x_bounds()
        if x2 <= x1:
            return self.from_
        ratio = (x - x1) / (x2 - x1)
        ratio = max(0.0, min(1.0, ratio))
        return self._clamp(self.from_ + ratio * (self.to - self.from_))

    def _redraw(self) -> None:
        w = self.canvas.winfo_width()
        h = self.canvas.winfo_height()
        if w < 4 or h < 4:
            return
        self.canvas.delete("all")
        ty = h // 2

        x1, x2 = self._track_x_bounds()
        # Background track.
        self.canvas.create_rectangle(
            x1, ty - _TRACK_H // 2, x2, ty + _TRACK_H // 2,
            fill=self._track_color, outline="",
        )
        # Filled segment between thumbs.
        min_x = self._val_to_x(self.min_val)
        max_x = self._val_to_x(self.max_val)
        self.canvas.create_rectangle(
            min_x, ty - _TRACK_H // 2, max_x, ty + _TRACK_H // 2,
            fill=self._fill_color, outline="",
        )
        # Thumbs (max drawn after min so it's on top when they coincide).
        # Add a focus ring around whichever thumb has keyboard focus.
        ring_min = self._focused_thumb == "min"
        ring_max = self._focused_thumb == "max"
        self.canvas.create_oval(
            min_x - _THUMB_R, ty - _THUMB_R, min_x + _THUMB_R, ty + _THUMB_R,
            fill=self._thumb_color,
            outline=("#ffffff" if ring_min else ""),
            width=(2 if ring_min else 0),
        )
        self.canvas.create_oval(
            max_x - _THUMB_R, ty - _THUMB_R, max_x + _THUMB_R, ty + _THUMB_R,
            fill=self._thumb_color,
            outline=("#ffffff" if ring_max else ""),
            width=(2 if ring_max else 0),
        )

    def _pick_thumb(self, x: float) -> str:
        # Pick the closer thumb; if equidistant (e.g. they're stacked), choose
        # by direction so the user can pull them apart.
        min_x = self._val_to_x(self.min_val)
        max_x = self._val_to_x(self.max_val)
        dmin = abs(x - min_x)
        dmax = abs(x - max_x)
        if dmin == dmax:
            return "min" if x < min_x else "max"
        return "min" if dmin < dmax else "max"

    def _on_press(self, event) -> None:
        self.canvas.focus_set()
        self._dragging = self._pick_thumb(event.x)
        self._focused_thumb = self._dragging
        self._update_from_event(event.x)

    def _on_drag(self, event) -> None:
        if self._dragging is None:
            return
        self._update_from_event(event.x)

    def _on_release(self, _event) -> None:
        self._dragging = None

    def _update_from_event(self, x: float) -> None:
        v = self._x_to_val(x)
        if self._dragging == "min":
            self.min_val = min(v, self.max_val)
        else:
            self.max_val = max(v, self.min_val)
        self._redraw()
        if self.command and not self._suppress_command:
            self.command(self.min_val, self.max_val)

    # -- keyboard support ---------------------------------------------------

    def _on_focus_in(self, _event=None) -> None:
        # Focus from Tab — default to the min thumb if neither was focused yet.
        if self._focused_thumb is None:
            self._focused_thumb = "min"
        self._redraw()

    def _on_focus_out(self, _event=None) -> None:
        self._focused_thumb = None
        self._redraw()

    def _on_tab(self, event) -> str:
        # Shift+Tab moves focus to the max thumb first if neither set yet.
        shift = bool(event.state & 0x0001)
        if self._focused_thumb is None:
            self._focused_thumb = "max" if shift else "min"
            self._redraw()
            return "break"
        # Within the slider, swap thumbs once before letting Tab move on.
        target = "max" if self._focused_thumb == "min" else "min"
        # Going forward from max (or backward from min) leaves the widget.
        if (self._focused_thumb == "max" and not shift) or (
            self._focused_thumb == "min" and shift
        ):
            self._focused_thumb = None
            self._redraw()
            return ""  # let Tk advance focus normally
        self._focused_thumb = target
        self._redraw()
        return "break"

    def _nudge(self, units: int, _event=None) -> str:
        if self._focused_thumb is None:
            return ""
        # One "unit" = the step size if defined, otherwise 1% of the range.
        if self.number_of_steps and self.number_of_steps > 0:
            step = (self.to - self.from_) / self.number_of_steps
        else:
            step = (self.to - self.from_) / 100.0
        delta = units * step
        if self._focused_thumb == "min":
            self.min_val = self._clamp(min(self.min_val + delta, self.max_val))
        else:
            self.max_val = self._clamp(max(self.max_val + delta, self.min_val))
        self._redraw()
        if self.command and not self._suppress_command:
            self.command(self.min_val, self.max_val)
        return "break"
