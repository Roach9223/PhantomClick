"""Hover tooltip for Tk / customtkinter widgets.

Usage:
    Tooltip(widget, "Explanation text shown on hover.")

The tooltip is a small borderless Toplevel that appears below the widget
after a short delay and disappears on mouse leave or any mouse press.
"""

from __future__ import annotations

import tkinter as tk

import theme


class Tooltip:
    def __init__(self, widget, text: str, delay_ms: int = 400, wraplength: int = 280):
        self.widget = widget
        self.text = text
        self.delay = delay_ms
        self.wraplength = wraplength
        self._tip: tk.Toplevel | None = None
        self._after_id: str | None = None
        widget.bind("<Enter>", self._on_enter, add="+")
        widget.bind("<Leave>", self._on_leave, add="+")
        widget.bind("<ButtonPress>", self._on_leave, add="+")

    def _on_enter(self, _e) -> None:
        self._cancel()
        self._after_id = self.widget.after(self.delay, self._show)

    def _on_leave(self, _e) -> None:
        self._cancel()
        self._destroy_tip()

    def _cancel(self) -> None:
        if self._after_id is not None:
            try:
                self.widget.after_cancel(self._after_id)
            except Exception:
                pass
            self._after_id = None

    def _destroy_tip(self) -> None:
        if self._tip is not None:
            try:
                self._tip.destroy()
            except tk.TclError:
                pass
            self._tip = None

    def _show(self) -> None:
        try:
            x = self.widget.winfo_rootx() + 14
            y = self.widget.winfo_rooty() + self.widget.winfo_height() + 4
        except tk.TclError:
            return
        tip = tk.Toplevel(self.widget)
        tip.wm_overrideredirect(True)
        tip.wm_attributes("-topmost", True)
        tip.wm_geometry(f"+{x}+{y}")
        tk.Label(
            tip, text=self.text, bg=theme.CARD_BG, fg=theme.TEXT_PRIMARY,
            font=(theme.FONT_FAMILY, 11), padx=10, pady=6,
            relief="solid", borderwidth=1, highlightbackground=theme.CARD_BORDER,
            wraplength=self.wraplength, justify="left",
        ).pack()
        self._tip = tip
