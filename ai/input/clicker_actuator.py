"""ClickerActuatorBackend — adapter that lets RS3_AI bot rules drive
PhantomClick's humanized mouse + keyboard primitives.

Why this exists:

- RS3_AI's :class:`InputBackend` Protocol expects ``move/click/press_key``
  etc. The shipped ``RealInputBackend`` calls pynput directly. That's
  fine for plain Win32 apps, but **NXT silently filters every software
  keystroke** — SendInput, Interception, AND PostMessage all fail. Only
  the Arduino HID path (PhantomClick's ``serial_hid`` backend) reliably
  reaches the game.
- Mouse clicks aren't filtered by NXT, so they can stay software — but
  routing them through PhantomClick's :class:`Clicker`'s humanization
  helpers (anti-cluster repulsion, fatigue, post-click micro-wander)
  means AI-mode clicks contribute to and benefit from the same shared
  state as Click/Record-mode clicks. One humanizer, three modes.

The adapter does NOT recreate the Clicker recorder cycle — it composes
the same low-level helpers (``utils.humanizer.move/click``,
``Clicker._anti_cluster``, ``Fatigue.multiplier``, ``Stats.record``,
``Clicker._post_click_micro_wander``). When the user is on the Click
or Record tab, those helpers run inside ``Clicker._cycle``. When the
user is on the AI tab, BotRunner calls them via this actuator. The
canonical pre-click pipeline (anti-cluster → jitter → fatigued
humanized move → fatigued click → record → wander) is preserved.
"""

from __future__ import annotations

from typing import Optional, Tuple

from pynput.keyboard import Controller as _KbController

from modules import key_timer
from utils import humanizer
from utils.fatigue import Fatigue


class ClickerActuatorBackend:
    """Implements the RS3_AI ``InputBackend`` Protocol via PhantomClick."""

    name = "phantomclick"

    def __init__(self, app) -> None:
        self._app = app
        # pynput controller is only used as the fallback path inside
        # ``key_timer.fire`` — the active backend is whatever was set via
        # ``key_timer.set_backend(...)`` (Serial HID / Interception /
        # SendInput) and that's what actually emits the keystroke.
        self._kb_controller = _KbController()
        # Clicker's Fatigue lives only inside a running ``_run_inner``
        # call, not on the instance — so AI mode owns its own. Click /
        # Record mode and AI mode are mutually exclusive (one cursor),
        # so they never run concurrently and the separate Fatigue isn't
        # a sharing problem.
        self._fatigue = self._build_fatigue()

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

    def rebuild_fatigue(self) -> None:
        """Re-snapshot Fatigue from the current clicker state.

        The clicker's per-feature behavior values (intensity, break gate,
        break-clicks gate, …) are derived from the realism slider via
        :meth:`BehaviorPageBody.apply_realism_preset`. Per-bot realism
        overrides (bundle ``settings.realism``) move the slider for the
        run, so we need to rebuild Fatigue to reflect the new gates —
        otherwise AI mode keeps clicking against a stale snapshot taken
        at actuator-construction time.
        """
        self._fatigue = self._build_fatigue()

    # ── PhantomClick state shortcuts ─────────────────────────────────
    @property
    def _clicker(self):
        return self._app.clicker

    @property
    def _stop(self):
        return self._clicker._stop  # threading.Event

    # ── Mouse ────────────────────────────────────────────────────────
    def move(self, x: int, y: int) -> None:
        c = self._clicker
        humanizer.move(
            (int(x), int(y)),
            stop=self._stop,
            fatigue=self._fatigue.multiplier(),
            overshoot_enabled=getattr(c, "overshoot_enabled", True),
            overshoot_probability=getattr(c, "overshoot_probability", 0.15),
        )

    def click(self, x: int, y: int, button: str = "left") -> None:
        c = self._clicker
        target: Tuple[int, int] = (int(x), int(y))

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

        try:
            c._recent.append(target)
        except Exception:
            pass
        try:
            c.stats.record(target)
        except Exception:
            pass
        try:
            self._fatigue.click_count += 1
        except Exception:
            pass

        try:
            c._post_click_micro_wander(mult)
        except Exception:
            pass

    def click_here(self, button: str = "left") -> None:
        """Click at the current cursor position WITHOUT a humanized
        bezier travel first.

        Used by ``click.fire()`` after a separate ``move()`` + uptext
        verification step has already positioned the cursor and
        confirmed the target. Re-running ``humanizer.move`` here would
        nudge the cursor a few pixels and potentially miss the
        just-verified element. The press/release cadence is still
        humanized.
        """
        c = self._clicker
        mult = self._fatigue.multiplier()
        if humanizer.click(
            button=button,
            mode="single",
            stop=self._stop,
            fatigue=mult,
        ):
            return
        try:
            self._fatigue.click_count += 1
        except Exception:
            pass
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
        humanizer.move(
            (int(start[0]), int(start[1])),
            stop=self._stop,
            fatigue=self._clicker.fatigue.multiplier(),
        )
        humanizer.move(
            (int(end[0]), int(end[1])),
            stop=self._stop,
            fatigue=self._clicker.fatigue.multiplier(),
        )

    def scroll(self, dy: int, at: Optional[Tuple[int, int]] = None) -> None:
        from pynput.mouse import Controller as _MC

        if at is not None:
            self.move(at[0], at[1])
        try:
            _MC().scroll(0, int(dy))
        except Exception:
            pass

    # ── Keyboard ─────────────────────────────────────────────────────
    def press_key(self, keyname: str) -> None:
        """Press a single key.

        ``keyname`` is a pyautogui-style name (``"space"``, ``"f1"``,
        ``"a"``, ``"ctrl+1"``). PhantomClick's :func:`key_timer.parse_combo`
        handles ``+``-joined combos plus the alias set already covers
        the names RS3_AI bot rules use.
        """
        combo = (keyname or "").strip().lower()
        if not combo:
            return
        key_timer.fire(
            self._kb_controller,
            combo,
            hold_s=0.0,
            stop=self._stop,
        )

    def type_text(self, text: str) -> None:
        for ch in text or "":
            self.press_key(ch)

    # ── Lifecycle ────────────────────────────────────────────────────
    def shutdown(self) -> None:
        # PhantomClick owns the Clicker / key_timer lifecycle — nothing
        # to clean up on a per-bot-run basis.
        return None

    def snapshot(self) -> dict:
        return {"backend": "phantomclick"}
