"""ClickerActuatorBackend: lets bot rules drive PhantomClick's humanized
mouse + keyboard primitives.

Why this exists:

- The bot framework's :class:`InputBackend` Protocol expects
  ``move/click/press_key`` etc. NXT silently filters every software
  keystroke (SendInput, Interception, PostMessage all fail). Only the
  Arduino HID path (PhantomClick's ``serial_hid`` backend) reliably
  reaches the game, and ``modules.key_timer.fire`` already knows how to
  drive it.
- Mouse clicks are not filtered by NXT, so they stay software, but
  routing them through the same helpers the Click / Record engine uses
  (anti-cluster repulsion, fatigue, post-click micro-wander) means AI
  clicks look like every other PhantomClick click.

The adapter does NOT recreate the Clicker recorder cycle. It composes
the same low-level helpers (``utils.humanizer.move/click``,
``Clicker._anti_cluster``, ``Fatigue.multiplier``, ``Stats.record``,
``Clicker._post_click_micro_wander``) so the canonical pre-click
pipeline (anti-cluster, jitter, fatigued humanized move, fatigued
click, record, wander) is preserved.

Coordinates in are physical screen pixels (what frames and ROIs use).
``humanizer.move`` wants DIPs, so the conversion happens here, once,
at the boundary.
"""

from __future__ import annotations

import threading
import time
from typing import Callable, Optional, Tuple

from pynput.keyboard import Controller as _KbController

from modules import key_timer
from utils import dpi_cursor, humanizer
from utils.fatigue import Fatigue


class ClickerActuatorBackend:
    """Implements the bot ``InputBackend`` Protocol via PhantomClick."""

    name = "phantomclick"

    def __init__(self, app) -> None:
        self._app = app
        # pynput controller is only the fallback path inside
        # ``key_timer.fire``; the active backend is whatever was set via
        # ``key_timer.set_backend(...)`` (Serial HID / Interception /
        # SendInput) and that is what actually emits the keystroke.
        self._kb_controller = _KbController()
        # Clicker's Fatigue lives only inside a running ``_run_inner``
        # call, not on the instance, so AI mode owns its own. Click /
        # Record mode and AI mode are mutually exclusive (one cursor),
        # so the separate Fatigue is never a sharing problem.
        self._fatigue = self._build_fatigue()
        # The actuator owns its stop flag. Borrowing ``Clicker._stop``
        # was a trap: that event stays set after any Click / Record run
        # ends, so every AI move aborted on its first step. BotRunner
        # clears this at start and sets it on stop.
        self._stop_event = threading.Event()
        # Watchdog feed. Every input method stamps ``last_input_at`` and
        # bumps ``input_count`` (single attribute writes, so readers on
        # other threads see a consistent value without a lock) and
        # notifies the optional listener the runner installs.
        self.last_input_at: float = 0.0
        self.input_count: int = 0
        self._listener: Optional[Callable[[str], None]] = None

    def _build_fatigue(self) -> Fatigue:
        c = self._app.clicker
        return Fatigue(
            enabled=getattr(c, "fatigue_enabled", True),
            break_bursts=getattr(c, "break_bursts_enabled", True),
            intensity=getattr(c, "fatigue_intensity", 0.25),
            break_min_clicks=getattr(c, "break_min_clicks", 100),
            break_max_clicks=getattr(c, "break_max_clicks", 200),
            break_min_duration=getattr(c, "break_min_duration", 20.0),
            break_max_duration=getattr(c, "break_max_duration", 60.0),
        )

    def fatigue_multiplier(self) -> float:
        """Current fatigue stretch for AI-mode inputs (1.0 = fresh)."""
        return float(self._fatigue.multiplier())

    def rebuild_fatigue(self) -> None:
        """Re-snapshot Fatigue from the current clicker state.

        The clicker's per-feature behavior values are derived from the
        realism slider. Per-bot realism overrides move the slider for
        the run, so Fatigue has to be rebuilt or AI mode keeps clicking
        against a stale snapshot taken at construction time.
        """
        self._fatigue = self._build_fatigue()

    # ── Run lifecycle (called by BotRunner) ──────────────────────────
    @property
    def stop_event(self) -> threading.Event:
        return self._stop_event

    def reset_stop(self) -> None:
        """Arm for a new run: clear the stop flag so moves can proceed."""
        self._stop_event.clear()

    def request_stop(self) -> None:
        """Abort any in-flight move / click / keystroke immediately."""
        self._stop_event.set()

    def set_input_listener(self, fn: Optional[Callable[[str], None]]) -> None:
        """Install (or clear with None) a callback fired after every
        input action with a kind string: ``"move"``, ``"click"``,
        ``"drag"``, ``"scroll"``, ``"key"``. Runs on the calling
        (bot worker) thread."""
        self._listener = fn

    def _note_input(self, kind: str) -> None:
        self.last_input_at = time.monotonic()
        self.input_count = self.input_count + 1
        fn = self._listener
        if fn is not None:
            try:
                fn(kind)
            except Exception:
                pass

    # ── PhantomClick state shortcuts ─────────────────────────────────
    @property
    def _clicker(self):
        return self._app.clicker

    @property
    def _stop(self) -> threading.Event:
        return self._stop_event

    @staticmethod
    def _to_dip(x: int, y: int) -> Tuple[int, int]:
        # Bot coordinates are physical px; the humanizer and the
        # Clicker helpers work in DIPs. Identity on DPR 1.0 monitors.
        try:
            return dpi_cursor.physical_to_dip(int(x), int(y))
        except Exception:
            return (int(x), int(y))

    # ── Mouse ────────────────────────────────────────────────────────
    def move(self, x: int, y: int) -> None:
        c = self._clicker
        interrupted = humanizer.move(
            self._to_dip(x, y),
            stop=self._stop,
            fatigue=self._fatigue.multiplier(),
            overshoot_enabled=getattr(c, "overshoot_enabled", True),
            overshoot_probability=getattr(c, "overshoot_probability", 0.15),
        )
        if not interrupted:
            self._note_input("move")

    def click(self, x: int, y: int, button: str = "left") -> None:
        c = self._clicker
        target: Tuple[int, int] = self._to_dip(x, y)

        try:
            target = c._anti_cluster(target, zone=None)
        except Exception:
            pass
        try:
            target = c._jitter(target, zone=None)
        except Exception:
            pass

        mult = self._fatigue.multiplier()
        if humanizer.move(
            target,
            stop=self._stop,
            fatigue=mult,
            overshoot_enabled=getattr(c, "overshoot_enabled", True),
            overshoot_probability=getattr(c, "overshoot_probability", 0.15),
        ):
            return

        if humanizer.click(
            button=button,
            mode="single",
            stop=self._stop,
            fatigue=mult,
        ):
            return

        self._after_click(target, mult)

    def click_here(self, button: str = "left") -> None:
        """Click at the current cursor position WITHOUT a humanized
        bezier travel first.

        Used by ``click.fire()`` after a separate ``move()`` + tooltip
        verification step has already positioned the cursor and
        confirmed the target. Re-running ``humanizer.move`` here would
        nudge the cursor a few pixels and potentially miss the
        just-verified element. The press/release cadence is still
        humanized.
        """
        mult = self._fatigue.multiplier()
        if humanizer.click(
            button=button,
            mode="single",
            stop=self._stop,
            fatigue=mult,
        ):
            return
        try:
            target = dpi_cursor.get_pos()
        except Exception:
            target = None
        self._after_click(target, mult)

    def _after_click(self, target: Optional[Tuple[int, int]], mult: float) -> None:
        c = self._clicker
        if target is not None:
            try:
                c._recent.append(target)
            except Exception:
                pass
            try:
                c.stats.record(target)
            except Exception:
                pass
            # Same hook the engine fires per click (target, actual, kind),
            # so the deck's click ring and event log fill in AI mode too.
            cb = getattr(c, "on_click_fired", None)
            if cb is not None:
                try:
                    ax, ay = dpi_cursor.get_pos()
                except Exception:
                    ax, ay = target
                try:
                    cb(int(target[0]), int(target[1]), int(ax), int(ay), "ai")
                except Exception:
                    pass
        try:
            self._fatigue.click_count += 1
        except Exception:
            pass
        self._note_input("click")
        try:
            c._post_click_micro_wander(mult)
        except Exception:
            pass

    def drag(
        self,
        start: Tuple[int, int],
        end: Tuple[int, int],
        button: str = "middle",
    ) -> None:
        """Press ``button`` at ``start``, travel to ``end``, release.

        Camera rotation in RS3 is a middle-button drag, so a plain
        double move (the old implementation) never turned the camera.
        """
        from pynput.mouse import Button, Controller as _MC

        mult = self._fatigue.multiplier()
        if humanizer.move(
            self._to_dip(start[0], start[1]),
            stop=self._stop,
            fatigue=mult,
        ):
            return
        btn = {"left": Button.left, "right": Button.right}.get(
            str(button).lower(), Button.middle
        )
        mouse = _MC()
        mouse.press(btn)
        try:
            # A held button has no overshoot: nobody overshoots and
            # corrects while dragging a camera.
            humanizer.move(
                self._to_dip(end[0], end[1]),
                stop=self._stop,
                fatigue=mult,
                overshoot_enabled=False,
            )
        finally:
            mouse.release(btn)
        self._note_input("drag")

    def scroll(self, dy: int, at: Optional[Tuple[int, int]] = None) -> None:
        from pynput.mouse import Controller as _MC

        if at is not None:
            self.move(at[0], at[1])
        if self._stop.is_set():
            return
        try:
            _MC().scroll(0, int(dy))
        except Exception:
            return
        self._note_input("scroll")

    # ── Keyboard ─────────────────────────────────────────────────────
    def press_key(self, keyname: str) -> None:
        """Press a single key.

        ``keyname`` is a pyautogui-style name (``"space"``, ``"f1"``,
        ``"a"``, ``"ctrl+1"``). :func:`key_timer.parse_combo` handles
        ``+``-joined combos and the alias set covers the names bot
        rules use.
        """
        combo = (keyname or "").strip().lower()
        if not combo or self._stop.is_set():
            return
        key_timer.fire(
            self._kb_controller,
            combo,
            hold_s=0.0,
            stop=self._stop,
        )
        self._note_input("key")

    def type_text(self, text: str) -> None:
        for ch in text or "":
            if self._stop.is_set():
                return
            self.press_key(ch)

    # ── Lifecycle ────────────────────────────────────────────────────
    def shutdown(self) -> None:
        # PhantomClick owns the Clicker / key_timer lifecycle. Per-run
        # cleanup is just dropping the runner's listener.
        self._listener = None

    def snapshot(self) -> dict:
        return {
            "backend": "phantomclick",
            "input_count": int(self.input_count),
            "last_input_at": float(self.last_input_at),
        }
